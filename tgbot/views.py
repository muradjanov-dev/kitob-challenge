import asyncio
import threading
import time
import traceback

from django.db import close_old_connections
from django.shortcuts import render
from .webhook import proceed_update_from_body
from django.http import HttpResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import redis
from celery import Celery
from celery.exceptions import OperationalError


# Persistent background event loop. aioredis (used by aiogram RedisStorage2)
# holds connections tied to whatever loop they were created in. If we spin up
# a fresh loop per request via async_to_sync, the next request hits the old
# loop's connections and dies with "Event loop is closed". One forever-running
# loop in a daemon thread keeps Redis connections healthy.
_bot_loop = asyncio.new_event_loop()


def _run_loop_forever():
    asyncio.set_event_loop(_bot_loop)
    _bot_loop.run_forever()


threading.Thread(target=_run_loop_forever, daemon=True, name="bot-loop").start()


async def _process_with_cleanup(body_bytes: bytes) -> None:
    start = time.monotonic()
    try:
        await proceed_update_from_body(body_bytes)
    except Exception:
        print("webhook bg error:\n" + traceback.format_exc())
    finally:
        close_old_connections()
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if elapsed_ms > 500:
            print(f"webhook handler took {elapsed_ms} ms")


def _fmt_num(n):
    return f"{int(n or 0):,}".replace(",", " ")


def _empty_landing_ctx():
    return {
        "readers_count": "0", "total_pages": "0",
        "finished_books": "0", "reading_books": "0",
        "lb_pages": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
        "lb_books": [], "lb_reports": [], "lb_active": [],
    }


def _build_landing_context():
    """Live platform stats + leaderboards for the landing page. Heavy-ish
    aggregations, so the caller caches the result for a few minutes."""
    import datetime as _dt
    from django.utils import timezone
    from django.db.models import Sum, Count, F
    from tgbot.models import TelegramProfile, ConfirmationReport, BooksToRead

    today = timezone.localdate()

    readers = TelegramProfile.objects.filter(is_registered=True).count()
    total_pages = (ConfirmationReport.objects.filter(is_audio=False)
                   .aggregate(s=Sum('pages_read'))['s']) or 0
    finished_books = BooksToRead.objects.filter(
        total_pages__gt=0, current_page__gte=F('total_pages')).count()
    reading_books = (BooksToRead.objects
                     .filter(current_page__gt=0, total_pages__gt=0)
                     .exclude(current_page__gte=F('total_pages')).count())

    def _rows(qs, key):
        return [{'name': (r['user__full_name'] or 'Kitobxon'),
                 'value': _fmt_num(r[key])} for r in qs]

    def top_pages(start, end, limit=10):
        qs = (ConfirmationReport.objects
              .filter(date__date__gte=start, date__date__lte=end,
                      is_audio=False, user__is_blocked=False)
              .values('user__full_name').annotate(total=Sum('pages_read'))
              .filter(total__gt=0).order_by('-total')[:limit])
        return _rows(qs, 'total')

    lb_pages = {
        'daily':   top_pages(today, today),
        'weekly':  top_pages(today - _dt.timedelta(days=6), today),
        'monthly': top_pages(today - _dt.timedelta(days=29), today),
        'yearly':  top_pages(today - _dt.timedelta(days=364), today),
    }
    lb_books = _rows(
        BooksToRead.objects
        .filter(total_pages__gt=0, current_page__gte=F('total_pages'),
                user__is_blocked=False)
        .values('user__full_name').annotate(c=Count('id'))
        .order_by('-c')[:10], 'c')
    lb_reports = _rows(
        ConfirmationReport.objects.filter(user__is_blocked=False)
        .values('user__full_name').annotate(c=Count('id'))
        .order_by('-c')[:10], 'c')
    lb_active = _rows(
        ConfirmationReport.objects
        .filter(user__is_blocked=False, reading_day__isnull=False)
        .values('user__full_name')
        .annotate(c=Count('reading_day', distinct=True))
        .order_by('-c')[:10], 'c')

    return {
        'readers_count': _fmt_num(readers),
        'total_pages': _fmt_num(total_pages),
        'finished_books': _fmt_num(finished_books),
        'reading_books': _fmt_num(reading_books),
        'lb_pages': lb_pages,
        'lb_books': lb_books,
        'lb_reports': lb_reports,
        'lb_active': lb_active,
    }


def library_view(request: HttpRequest):
    from django.db.models import Count, Q, F
    from tgbot.models import GlobalBook, BooksToRead

    books_qs = (
        GlobalBook.objects
        .exclude(pdf_file='')
        .exclude(pdf_file__isnull=True)
        .annotate(
            # "Started"/"finished" must only reflect real web-reader activity
            # (fee_charged=True -- i.e. actually opened via kutubxona/'s PDF
            # reader), never the bot's free-text self-report flow. That flow
            # resolves book titles by fuzzy/normalized match against this same
            # GlobalBook table, so a brand-new upload can inherit years of
            # unrelated BooksToRead rows (arbitrary total_pages a user typed
            # in, long since "finished" by honor-system standards) that have
            # nothing to do with this actual PDF's real page count.
            started_count=Count(
                'user_books',
                filter=Q(user_books__total_pages__gt=0, user_books__fee_charged=True),
                distinct=True,
            ),
            finished_count=Count(
                'user_books',
                filter=Q(
                    user_books__total_pages__gt=0,
                    user_books__current_page__gte=F('user_books__total_pages'),
                    user_books__fee_charged=True,
                ),
                distinct=True,
            ),
        )
        .order_by('-started_count', '-finished_count', 'title')
    )

    # Group books by language for shelf display
    lang_order = [('uz', "O'zbekcha"), ('ru', 'Ruscha'), ('en', 'Inglizcha'),
                  ('tr', 'Turkcha'), ('ar', 'Arabcha'), ('other', 'Boshqa')]
    shelves = []
    all_books = list(books_qs)
    for lang_code, lang_label in lang_order:
        group = [b for b in all_books if b.language == lang_code]
        if group:
            shelves.append({'code': lang_code, 'label': lang_label, 'books': group})

    total_readers = BooksToRead.objects.filter(total_pages__gt=0).values('user').distinct().count()
    total_finished = BooksToRead.objects.filter(
        total_pages__gt=0,
        current_page__gte=F('total_pages'),
    ).count()

    import json as _json
    books_json = _json.dumps([
        {
            'id': b.id,
            'title': b.title,
            'author': b.author or '',
            'lang': b.language,
            'premium': b.is_premium_only,
            'started': b.started_count,
            'finished': b.finished_count,
            'desc': b.description or '',
            'cover': b.cover.url if b.cover else None,
            'pdf': b.pdf_file.url if (b.pdf_file and not b.is_premium_only) else None,
            'audio': b.audio_file.url if (b.audio_file and not b.is_premium_only) else None,
            'hasPdf': bool(b.pdf_file),
            'hasAudio': bool(b.audio_file),
        }
        for b in all_books
    ], ensure_ascii=False)

    ctx = {
        'books': all_books,
        'shelves': shelves,
        'books_json': books_json,
        'total_books': len(all_books),
        'total_readers': total_readers,
        'total_finished': total_finished,
        'query': request.GET.get('q', ''),
    }
    resp = render(request, 'library/index.html', ctx)
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


def home(request: HttpRequest):
    from django.core.cache import cache
    ctx = cache.get("landing_ctx_v1")
    if ctx is None:
        try:
            ctx = _build_landing_context()
        except Exception as e:
            print(f"landing context build failed: {e}")
            ctx = _empty_landing_ctx()
        cache.set("landing_ctx_v1", ctx, 600)  # refresh every 10 min
    resp = render(request, 'site/index.html', ctx)
    # Served as a Telegram Mini App — WebView2 caches aggressively, so force a
    # fresh fetch on every open (same as the shop page).
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


@csrf_exempt
def telegram(request: HttpRequest):
    body = request.body
    asyncio.run_coroutine_threadsafe(_process_with_cleanup(body), _bot_loop)
    return HttpResponse(status=200)


@csrf_exempt
def internal_diag_blocked_users(request: HttpRequest):
    """One-off diagnostic: recent is_blocked changes on TelegramProfile via
    django-auditlog, to find out who/what has been wrongly blocking new
    users and when. GET, read-only. Delete once the investigation is done."""
    import os as _os
    from auditlog.models import LogEntry
    from django.contrib.contenttypes.models import ContentType
    from tgbot.models import TelegramProfile

    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    ct = ContentType.objects.get_for_model(TelegramProfile)
    entries = (
        LogEntry.objects.filter(content_type=ct)
        .order_by("-timestamp")[:500]
    )
    hits = []
    for e in entries:
        changes = e.changes or {}
        if "is_blocked" in changes:
            hits.append({
                "object_pk": e.object_pk,
                "object_repr": e.object_repr,
                "action": e.action,
                "actor": str(e.actor) if e.actor_id else None,
                "actor_email": e.actor_email,
                "remote_addr": e.remote_addr,
                "timestamp": e.timestamp.isoformat(),
                "is_blocked_change": changes.get("is_blocked"),
            })
        if len(hits) >= 60:
            break

    currently_blocked = TelegramProfile.objects.filter(is_blocked=True).count()
    currently_blocked_recent = list(
        TelegramProfile.objects.filter(is_blocked=True)
        .order_by("-id").values("id", "telegram_id", "full_name", "is_registered")[:30]
    )

    return JsonResponse({
        "currently_blocked_total": currently_blocked,
        "currently_blocked_sample": currently_blocked_recent,
        "is_blocked_audit_hits": hits,
    }, json_dumps_params={"indent": 2, "default": str})


app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Configure Redis connection
redis_client = redis.StrictRedis(
    host="redis",
    port="6379",
    db=0,
)


@api_view(["GET"])
def health_check_redis(request):
    try:
        redis_client.ping()
        return Response({"status": "success"}, status=status.HTTP_200_OK)
    except redis.ConnectionError:
        return Response(
            {"status": "error", "message": "Redis server is not working."},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
def health_check_celery(request):
    try:
        response = app.control.ping()
        if response:
            return Response(
                {"status": "success", "workers": response}, status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"status": "error", "message": "No Celery workers responded."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    except OperationalError:
        return Response(
            {"status": "error", "message": "Celery OperationalError occurred."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
