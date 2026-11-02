import asyncio
import threading
import time
import traceback

from django.db import connections
from django.shortcuts import render
from .webhook import proceed_update_from_body
from django.http import HttpResponse, HttpRequest, JsonResponse
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
        # Force-close, not close_old_connections() -- that only closes a
        # connection once it's already past CONN_MAX_AGE, so this persistent
        # background thread (see _bot_loop above) just kept accumulating a
        # live connection across updates instead of releasing it. See
        # celery_app.py's _close_db_connections_after_task for the same fix
        # applied on the Celery side (2026-08-02 outage).
        connections.close_all()
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
    from tgbot.services import app_shell
    if app_shell.wanted(request):
        return app_shell.render_shell(request, "/kutubxona/")
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
    from tgbot.services import app_shell
    if app_shell.wanted(request):
        return app_shell.render_shell(request, "/")
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
def internal_diag_achievements(request: HttpRequest):
    """One-off diagnostic + fix: for every user with at least one BookComment
    or recent ConfirmationReport, run award_new_achievements SYNCHRONOUSLY
    (bypassing Celery entirely) and report what happened. Confirms whether
    the achievement CODE itself is sound (any exception here is a real bug,
    not a delivery gap) and, separately, catches anyone whose achievements
    should already have fired via the normal check_user_achievements.delay()
    path but didn't (celery_worker not picking up new task code -- the same
    class of gap found earlier this session with launch_referral_boom).
    POST only, guarded, safe to re-run (award_new_achievements is itself
    idempotent -- already-awarded codes are skipped)."""
    import os as _os
    from tgbot.models import TelegramProfile, BookComment, ConfirmationReport
    from tgbot.services.achievements import award_new_achievements, compute_user_stats, ACHIEVEMENTS

    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    commenter_ids = set(BookComment.objects.values_list("user_id", flat=True).distinct())
    recent_reporter_ids = set(
        ConfirmationReport.objects.order_by("-date").values_list("user_id", flat=True)[:300]
    )
    candidate_ids = list(commenter_ids | recent_reporter_ids)[:400]

    newly_awarded = []
    errors = []
    checked = 0
    for uid in candidate_ids:
        user = TelegramProfile.objects.filter(id=uid).first()
        if not user:
            continue
        checked += 1
        try:
            newly = award_new_achievements(user)
        except Exception as e:
            errors.append({"user_id": uid, "error": str(e)})
            continue
        if newly:
            newly_awarded.append({
                "user_id": uid,
                "name": user.full_name,
                "codes": [a["code"] for a in newly],
            })

    return JsonResponse({
        "total_achievements_defined": len(ACHIEVEMENTS),
        "candidates_checked": checked,
        "users_newly_awarded": newly_awarded,
        "errors": errors,
    }, json_dumps_params={"indent": 2, "default": str})


@csrf_exempt
def internal_grant_ai_quiz_bonus_everyone(request: HttpRequest):
    """One-off trigger for ai_quiz_bonus.grant_ai_quiz_bonus_to_everyone --
    grants every registered user the same 1-hour AI-quiz window the Sirli
    quti prize gives, making good on the grants the qz:ai gate bug denied.
    POST only, runs in a background thread (the broadcast runs well past
    gunicorn's request timeout). ?announce=0 grants silently. Delete this
    view/URL once used."""
    import os as _os

    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    from tgbot.services.ai_quiz_bonus import drip_ai_quiz_bonus, DRIP_USERS_PER_HOUR, BONUS_HOURS

    try:
        limit = int(request.GET.get("limit", DRIP_USERS_PER_HOUR))
    except ValueError:
        limit = DRIP_USERS_PER_HOUR
    try:
        hours = int(request.GET.get("hours", BONUS_HOURS))
    except ValueError:
        hours = BONUS_HOURS
    force = request.GET.get("force", "0") == "1"

    def _run():
        try:
            drip_ai_quiz_bonus(limit=limit, hours=hours, force=force)
        except Exception as e:
            print(f"internal_grant_ai_quiz_bonus_everyone failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return HttpResponse(f"started limit={limit} hours={hours} force={force}", status=202)


@csrf_exempt
def internal_ai_quiz_bonus_status(request: HttpRequest):
    """Progress of the drip campaign: how many are left, whether it's
    currently inside its sending window, and the projected finish. GET,
    read-only."""
    import os as _os

    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    from tgbot.services.ai_quiz_bonus import drip_status

    return JsonResponse(drip_status(), json_dumps_params={"indent": 2, "default": str})


@csrf_exempt
def internal_diag_ai_quiz_trial_backlog(request: HttpRequest):
    """One-off diagnostic: find every user currently holding a non-null
    TelegramProfile.trial_ai_quiz_until (Market 'Sirli quti' ai_quiz_trial
    win, or the daily grant_daily_ai_quiz_trial giveaway). Normally this
    field self-clears an hour after grant (tasks.expire_ai_quiz_trial), so
    anyone still holding a value now either (a) is mid-window, or (b) had
    their whole window silently wasted by the qz:ai button's Premium-only
    gate bug (fixed same session as this endpoint) and never got to use it
    because celery never got the chance to null the field either way that
    matters for the user experience. GET, read-only."""
    import os as _os
    from django.utils import timezone
    from tgbot.models import TelegramProfile

    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    now = timezone.now()
    rows = list(
        TelegramProfile.objects.filter(trial_ai_quiz_until__isnull=False)
        .values("id", "telegram_id", "full_name", "trial_ai_quiz_until")
    )
    for r in rows:
        r["still_active"] = r["trial_ai_quiz_until"] >= now

    return JsonResponse({
        "now": now,
        "total": len(rows),
        "still_active_count": sum(1 for r in rows if r["still_active"]),
        "stale_expired_count": sum(1 for r in rows if not r["still_active"]),
        "users": rows,
    }, json_dumps_params={"indent": 2, "default": str})


@csrf_exempt
def internal_fix_ai_quiz_trial_backlog(request: HttpRequest):
    """One-off fix, paired with internal_diag_ai_quiz_trial_backlog: for
    every user currently holding a non-null trial_ai_quiz_until, refresh it
    to a fresh AI_QUIZ_TRIAL_HOURS window starting now and (re)schedule the
    matching expire_ai_quiz_trial task, so the access the gate bug silently
    denied them is actually usable now that the bug is fixed. POST only,
    guarded, safe to re-run (each call just grants another fresh hour)."""
    import os as _os
    import datetime as _dt
    from django.utils import timezone
    from tgbot.models import TelegramProfile
    from tgbot.tasks import expire_ai_quiz_trial, AI_QUIZ_TRIAL_HOURS

    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    now = timezone.now()
    until = now + _dt.timedelta(hours=AI_QUIZ_TRIAL_HOURS)
    profiles = list(
        TelegramProfile.objects.filter(trial_ai_quiz_until__isnull=False)
        .values("id", "telegram_id", "full_name")
    )
    for p in profiles:
        TelegramProfile.objects.filter(id=p["id"]).update(trial_ai_quiz_until=until)
        expire_ai_quiz_trial.apply_async(args=[p["id"]], countdown=AI_QUIZ_TRIAL_HOURS * 3600)

    return JsonResponse({
        "refreshed_until": until,
        "count": len(profiles),
        "users": profiles,
    }, json_dumps_params={"indent": 2, "default": str})


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
    # action=1 is UPDATE (0=create, 2=delete) -- the CREATE flood (every new
    # registration logs is_blocked None->False, which isn't a block event at
    # all) was swamping a plain "most recent 500" scan. __has_key targets
    # exactly the field we care about via the JSONField index instead.
    entries = (
        LogEntry.objects.filter(content_type=ct, action=1, changes__has_key="is_blocked")
        .order_by("-timestamp")[:200]
    )
    to_true = []
    to_false = []
    for e in entries:
        changes = e.changes or {}
        old, new = changes.get("is_blocked", [None, None])
        row = {
            "object_pk": e.object_pk,
            "object_repr": e.object_repr,
            "actor": str(e.actor) if e.actor_id else None,
            "remote_addr": e.remote_addr,
            "timestamp": e.timestamp.isoformat(),
            "is_blocked_change": [old, new],
        }
        if new == "True":
            to_true.append(row)
        elif new == "False":
            to_false.append(row)

    currently_blocked = TelegramProfile.objects.filter(is_blocked=True).count()
    currently_blocked_recent = list(
        TelegramProfile.objects.filter(is_blocked=True)
        .order_by("-id").values("id", "telegram_id", "full_name", "is_registered")[:30]
    )

    return JsonResponse({
        "currently_blocked_total": currently_blocked,
        "currently_blocked_sample": currently_blocked_recent,
        "recent_blocked_true_events": to_true[:100],
        "recent_blocked_false_events_(unblocks)": to_false[:20],
    }, json_dumps_params={"indent": 2, "default": str})


@csrf_exempt
def internal_diag_challenge_reward_history(request: HttpRequest):
    """One-off diagnostic: were past 3-day Challenges actually finalized and
    winners rewarded, or did some sit overdue/un-finalized (the exact
    failure mode tgbot/management/commands/diagnose_challenges.py was
    written to investigate -- same class of bug as the boom launch task
    that never ran because celery_worker was stale). GET, read-only."""
    import os as _os
    from django.utils import timezone
    from tgbot.models import Challenge, ChallengeParticipant

    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    today = timezone.localdate()
    rows = []
    for c in Challenge.objects.order_by("-created_at")[:15]:
        participants = ChallengeParticipant.objects.filter(challenge=c)
        total = participants.count()
        rewarded = participants.filter(reward_given=True).count()
        top3 = list(
            participants.filter(reward_given=True).order_by("rank")
            .values_list("rank", "user__full_name", "days_completed")[:3]
        )
        overdue = bool(c.is_active and c.end_date and c.end_date < today)
        rows.append({
            "id": c.id, "title": c.title,
            "condition_type": c.condition_type, "condition_value": c.condition_value,
            "start_date": c.start_date, "end_date": c.end_date,
            "is_active": c.is_active, "announced_at": c.announced_at,
            "participant_count": total, "rewarded_count": rewarded,
            "top3": top3, "OVERDUE_NOT_FINALIZED": overdue,
        })

    return JsonResponse({
        "server_today": str(today),
        "challenges": rows,
    }, json_dumps_params={"indent": 2, "default": str})


@csrf_exempt
def internal_diag_challenge_boom_state(request: HttpRequest):
    """One-off diagnostic: current active Challenge (if any) + its
    participants' progress, and current active/queued ReferralBoom state.
    Needed before deciding how to transition off the 3-day Challenge into
    the Yaxshilik ulashuvchi window without guessing at live data. GET,
    read-only. Delete once the investigation is done."""
    import os as _os
    from tgbot.models import Challenge, ChallengeParticipant, ReferralBoom, ReferralBoomParticipant

    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    challenge = Challenge.objects.filter(is_active=True).order_by("-created_at").first()
    challenge_data = None
    if challenge:
        participants = list(
            ChallengeParticipant.objects.filter(challenge=challenge)
            .values("user_id", "days_completed", "reward_given")
            .order_by("-days_completed")[:200]
        )
        challenge_data = {
            "id": challenge.id, "title": challenge.title,
            "condition_type": challenge.condition_type,
            "condition_value": challenge.condition_value,
            "start_date": challenge.start_date, "end_date": challenge.end_date,
            "participant_count": len(participants),
            "participants_with_progress": len([p for p in participants if p["days_completed"] > 0]),
            "sample_participants": participants[:20],
        }

    boom = ReferralBoom.objects.filter(is_active=True).order_by("-created_at").first()
    boom_data = None
    if boom:
        boom_data = {
            "id": boom.id, "title": boom.title,
            "start_at": boom.start_at, "end_at": boom.end_at,
            "planned_days": boom.planned_days,
            "participant_count": ReferralBoomParticipant.objects.filter(boom=boom).count(),
        }
    queued_boom = ReferralBoom.objects.filter(is_queued=True).order_by("-created_at").first()

    # Any boom row at all, active/queued or not -- catches an orphaned draft
    # created by the bot wizard whose launch_referral_boom.delay() Celery
    # task never actually ran (celery_worker doesn't auto-redeploy on push).
    recent_rows = list(
        ReferralBoom.objects.order_by("-created_at")[:8]
        .values("id", "title", "is_active", "is_queued", "created_at", "image")
    )

    return JsonResponse({
        "active_challenge": challenge_data,
        "active_boom": boom_data,
        "recent_boom_rows": recent_rows,
        "queued_boom": {"id": queued_boom.id, "title": queued_boom.title} if queued_boom else None,
    }, json_dumps_params={"indent": 2, "default": str})


@csrf_exempt
def internal_unblock_false_positives(request: HttpRequest):
    """One-off trigger for tgbot.tasks.unblock_and_apologize_false_positives.
    POST only, runs in a background thread (can run well past gunicorn's
    request timeout). Delete this view/URL once used."""
    import os as _os

    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    from tgbot.tasks import unblock_and_apologize_false_positives

    def _run():
        try:
            unblock_and_apologize_false_positives()
        except Exception as e:
            print(f"internal_unblock_false_positives failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return HttpResponse("started", status=202)


@csrf_exempt
def internal_broadcast_mystery_box_update(request: HttpRequest):
    """One-off trigger for mystery_box_announce.broadcast_mystery_box_update.
    POST only, runs in a background thread. Delete this view/URL once used."""
    import os as _os

    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    from tgbot.services.mystery_box_announce import broadcast_mystery_box_update

    def _run():
        try:
            broadcast_mystery_box_update()
        except Exception as e:
            print(f"internal_broadcast_mystery_box_update failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return HttpResponse("started", status=202)


@csrf_exempt
def internal_broadcast_update_announcement(request: HttpRequest):
    """One-off trigger for update_announce.broadcast_update_announcement.
    POST only, runs in a background thread."""
    import os as _os

    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    from tgbot.services.update_announce import broadcast_update_announcement

    def _run():
        try:
            broadcast_update_announcement()
        except Exception as e:
            print(f"internal_broadcast_update_announcement failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return HttpResponse("started", status=202)


@csrf_exempt
def internal_broadcast_auction_announcement(request: HttpRequest):
    """One-off trigger for auction_announce.broadcast_auction_announcement.
    POST only, runs in a background thread."""
    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    from src.settings import API_TOKEN, SECRET_KEY
    if not secret or secret not in (API_TOKEN, SECRET_KEY):
        return HttpResponse(status=403)

    from tgbot.services.auction_announce import broadcast_auction_announcement

    def _run():
        try:
            broadcast_auction_announcement()
        except Exception as e:
            print(f"internal_broadcast_auction_announcement failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return HttpResponse("started", status=202)


@csrf_exempt
def internal_ops(request: HttpRequest, action: str):
    """Data repairs and approved announcements (services/ops_fixes.py,
    services/ops_broadcast.py). POST a JSON body; nothing changes unless it
    carries "apply": true, so every call can be made as a dry run first."""
    import json as _json
    import os as _os

    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)
    try:
        body = _json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    apply = bool(body.get("apply"))

    from tgbot.services import ops_fixes, ops_broadcast

    def _iso(rows):
        return [{**r, "last_before": str(r["last_before"]), "first_after": str(r["first_after"]),
                 "fill": [str(d) for d in r["fill"]]} for r in rows]

    if action == "streak-gap":
        out = {"ok": True, "daily": ops_fixes.daily_reporters(body.get("since") or "2026-08-25")}
        if body.get("gap_start") and body.get("gap_end"):
            plan = ops_fixes.streak_gap_plan(body["gap_start"], body["gap_end"], int(body.get("grace", 2)))
            out["users"] = len(plan)
            out["days"] = sum(len(p["fill"]) for p in plan)
            out["plan"] = _iso(plan) if body.get("full") else _iso(plan[:40])
            if apply:
                out["created"] = ops_fixes.apply_streak_gap(plan)
        return JsonResponse(out)

    if action == "coverage":
        missing = ops_fixes.coverage_plan(body.get("rows") or [])
        out = {"ok": True, "missing": len(missing), "users": len({m["user_id"] for m in missing})}
        if apply:
            out["created"] = ops_fixes.apply_coverage(missing)
        return JsonResponse(out)

    if action == "streak-achievements":
        from tgbot.models import TelegramProfile
        plan = ops_fixes.streak_achievement_plan()
        paid_before =[(r["telegram_id"], r["code"]) for r in body.get("paid_before") or []]
        pb = {(int(t), c) for t, c in paid_before}
        tg = dict(TelegramProfile.objects.filter(id__in=[p["user_id"] for p in plan])
                  .values_list("id", "telegram_id"))
        out = {"ok": True, "users": len(plan), "achievements": sum(len(p["codes"]) for p in plan),
               "points": sum(p["points"] for p in plan),
               "already_paid_on_old_server": sum(1 for p in plan for c in p["codes"]
                                                 if (int(tg.get(p["user_id"], 0)), c) in pb),
               "plan": plan[:60]}
        if apply:
            out["applied"] = ops_fixes.apply_streak_achievements(plan, paid_before)
        return JsonResponse(out)

    if action == "restore-streak-days":
        return JsonResponse({"ok": True, **ops_fixes.restore_streak_days(body.get("rows") or [], apply)})

    if action == "game-reward-audit":
        return JsonResponse({"ok": True, "games": ops_fixes.game_reward_audit(int(body.get("days") or 14))})

    if action == "achievement-audit":
        # compute_user_stats runs ~30 queries a reader: background job,
        # result in the cache, poll with {"poll": true}.
        from django.core.cache import cache
        key = "ops_achievement_audit"
        if body.get("poll"):
            return JsonResponse({"ok": True, "result": cache.get(key)})
        cache.set(key, {"state": "running", "apply": apply}, 3600)

        def _run_audit():
            try:
                res = ops_fixes.achievement_audit(apply=apply, active_days=int(body.get("active_days") or 120))
                cache.set(key, {"state": "done", "apply": apply, **res}, 86400)
            except Exception:
                cache.set(key, {"state": "error", "trace": traceback.format_exc()[-1500:]}, 86400)
            finally:
                connections.close_all()

        threading.Thread(target=_run_audit, daemon=True).start()
        return JsonResponse({"ok": True, "started": True, "apply": apply}, status=202)

    if action == "restore-achievements":
        return JsonResponse({"ok": True, **ops_fixes.restore_achievements(body.get("rows") or [], apply)})

    if action == "kitobcha-economy":
        from tgbot.services import economy
        r = economy.report(int(body.get("days") or 7))
        return JsonResponse({"ok": True, **r, "text": economy.report_text(r)})

    if action == "wallet-testers":
        from tgbot.services import wallet
        if apply:
            wallet.set_testers(body.get("telegram_ids") or [])
        return JsonResponse({"ok": True, "testers": sorted(wallet._testers()) if not apply
                             else sorted(int(t) for t in body.get("telegram_ids") or [])})

    if action == "wallet-preview":
        # What the launch will credit, without crediting anything.
        from django.db.models import Max
        from tgbot.models import Payment, TelegramProfile
        from tgbot.services import wallet
        registered = TelegramProfile.objects.filter(is_registered=True).count()
        ends = (Payment.objects.filter(status="paid", end_date__gte=wallet.LAUNCH_DATE)
                .values("user_id").annotate(m=Max("end_date")))
        days = [(r["m"] - wallet.LAUNCH_DATE).days + 1 for r in ends]
        return JsonResponse({"ok": True, "registered": registered,
                             "bonus_total": registered * wallet.LAUNCH_BONUS,
                             "premium_users": len(days), "premium_days": sum(days),
                             "premium_total": sum(days) * wallet.DAY_FEE})

    if action == "newcomer-topup":
        # Readers who joined on/after the launch and got the 3 000 launch
        # bonus: +2 000 so their welcome gift is 5 000 like every newcomer's,
        # once each; `text` ({name}) DMed to each one topped up.
        import html
        import os as _os

        import requests
        from tgbot.models import TelegramProfile, WalletTransaction
        from tgbot.services import wallet
        got_3000 = WalletTransaction.objects.filter(kind=WalletTransaction.KIND_BONUS,
                                                    delta__lt=wallet.NEWCOMER_BONUS).values_list("user_id", flat=True)
        people = [p for p in TelegramProfile.objects.filter(id__in=list(got_3000)).order_by("id") if wallet.is_newcomer(p)]
        template = body.get("text") or ""
        rows = []
        for p in people:
            done = WalletTransaction.objects.filter(user=p, kind=WalletTransaction.KIND_ADMIN,
                                                    note=wallet.NEWCOMER_TOPUP_NOTE).exists()
            row = {"telegram_id": p.telegram_id, "name": p.full_name, "joined": str(p.created_at.date()),
                   "done_before": done}
            if apply and not done:
                row["added"] = wallet.newcomer_topup(p)
                if row["added"] and template and not p.is_blocked:
                    try:
                        requests.post(
                            f"https://api.telegram.org/bot{_os.environ.get('API_TOKEN', '')}/sendMessage",
                            data={"chat_id": p.telegram_id, "parse_mode": "HTML",
                                  "text": template.format(name=html.escape((p.full_name or "Kitobxon").split()[0]))},
                            timeout=8)
                    except Exception as e:
                        row["dm_error"] = str(e)[:80]
                    time.sleep(0.05)
            rows.append(row)
        return JsonResponse({"ok": True, "count": len(rows), "rows": rows})

    if action == "admin-grant":
        # A gift to every admin (profiles with is_admin + settings.ADMINS):
        # `amount` so'm into the wallet and `member_days` perk days, once per
        # admin per `tag` (the WalletTransaction note is the marker); `text`
        # ({name} {som} {until}) is DMed to each one credited.
        import html
        import os as _os

        import requests
        from django.conf import settings as _settings
        from django.db import transaction as _txn
        from tgbot.models import TelegramProfile, WalletTransaction
        from tgbot.services import wallet
        tag = (body.get("tag") or "Admin sovg'asi")[:120]
        amount, days = int(body.get("amount") or 0), int(body.get("member_days") or 0)
        env_ids = {int(a) for a in getattr(_settings, "ADMINS", []) if str(a).strip().lstrip("-").isdigit()}
        admins = list(TelegramProfile.objects.filter(is_admin=True)) + list(
            TelegramProfile.objects.filter(telegram_id__in=env_ids, is_admin=False))
        template = body.get("text") or ""
        rows = []
        for p in admins:
            done = WalletTransaction.objects.filter(user=p, kind=WalletTransaction.KIND_ADMIN, note=tag).exists()
            row = {"telegram_id": p.telegram_id, "name": p.full_name, "done_before": done}
            if apply and not done and amount > 0:
                with _txn.atomic():
                    q = TelegramProfile.objects.select_for_update().get(id=p.id)
                    wallet._credit_locked(q, amount, WalletTransaction.KIND_ADMIN, tag)
                    if days:
                        wallet._extend_membership_locked(q, days)
                row.update(credited=amount, balance=q.wallet_balance, until=str(q.wallet_member_until))
                if template and not q.is_blocked:
                    try:
                        requests.post(
                            f"https://api.telegram.org/bot{_os.environ.get('API_TOKEN', '')}/sendMessage",
                            data={"chat_id": q.telegram_id, "parse_mode": "HTML", "text": template.format(
                                name=html.escape(q.full_name or "Admin"), som=f"{amount:,}".replace(",", " "),
                                until=wallet.uz_date(q.wallet_member_until) if q.wallet_member_until else "")},
                            timeout=8)
                    except Exception as e:
                        row["dm_error"] = str(e)[:80]
                time.sleep(0.05)
            rows.append(row)
        return JsonResponse({"ok": True, "admins": len(rows), "rows": rows})

    if action == "dm-list":
        # DM one approved text to a list of readers ("ids") or to every admin
        # ("admins": true), optionally with one button -- a Mini App button
        # when "web_app" is true (private chats only). Readers who blocked the
        # bot are skipped. Without apply: the count and the text back.
        import os as _os
        import requests
        from django.conf import settings as _settings
        from tgbot.models import TelegramProfile
        text = body.get("text") or ""
        if not text:
            return JsonResponse({"ok": False, "error": "text_required"}, status=400)
        if body.get("admins"):
            env = {int(a) for a in getattr(_settings, "ADMINS", []) if str(a).strip().lstrip("-").isdigit()}
            people = list(TelegramProfile.objects.filter(is_admin=True)) + list(
                TelegramProfile.objects.filter(telegram_id__in=env, is_admin=False))
        else:
            ids = [int(i) for i in body.get("ids") or []]
            people = list(TelegramProfile.objects.filter(telegram_id__in=ids))
        markup = None
        if body.get("button_text") and body.get("button_url"):
            btn = {"text": body["button_text"]}
            btn["web_app" if body.get("web_app") else "url"] = (
                {"url": body["button_url"]} if body.get("web_app") else body["button_url"])
            markup = _json.dumps({"inline_keyboard": [[btn]]})
        out = {"ok": True, "people": len(people), "blocked": sum(1 for p in people if p.is_blocked), "preview": text}
        if not apply:
            return JsonResponse(out)
        sent = failed = 0
        api = f"https://api.telegram.org/bot{_os.environ.get('API_TOKEN', '')}/sendMessage"
        for p in people:
            if p.is_blocked:
                continue
            data = {"chat_id": p.telegram_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
            if markup:
                data["reply_markup"] = markup
            try:
                r = requests.post(api, data=data, timeout=8)
                if r.ok:
                    sent += 1
                else:
                    failed += 1
                    if r.status_code == 403:
                        TelegramProfile.objects.filter(id=p.id).update(is_blocked=True)
            except Exception:
                failed += 1
            time.sleep(0.05)
        out.update(sent=sent, failed=failed)
        return JsonResponse(out)

    if action == "broadcast-edit":
        # Edit every message an ops broadcast sent (ids kept since 2026-11-03).
        import os as _os
        import requests
        msgs = ops_broadcast.sent_messages(body.get("campaign", ""))
        text = body.get("text") or ""
        if not apply or not text:
            return JsonResponse({"ok": True, "messages": len(msgs)})
        api = f"https://api.telegram.org/bot{_os.environ.get('API_TOKEN', '')}/editMessageText"
        edited = 0
        for chat_id, mid in msgs:
            try:
                r = requests.post(api, data={"chat_id": chat_id, "message_id": mid, "text": text,
                                             "parse_mode": "HTML", "disable_web_page_preview": "true"}, timeout=8)
                edited += r.ok
            except Exception:
                pass
            time.sleep(0.05)
        return JsonResponse({"ok": True, "messages": len(msgs), "edited": edited})

    if action == "group-find-delete":
        # Find the bot's own older post in a group by how its text starts and
        # delete it. The Bot API cannot read a chat, so each message below
        # `below` is forwarded silently to the admin group, its text checked,
        # and the forwarded copy deleted at once; nothing in the group is
        # touched except the one match (and only with apply).
        import os as _os
        import requests
        api = f"https://api.telegram.org/bot{_os.environ.get('API_TOKEN', '')}"
        probe_chat = _os.environ.get("ADMIN_GROUP_ID", "")
        chat, below = str(body.get("chat") or ""), int(body.get("below") or 0)
        start = (body.get("startswith") or "").strip()
        depth = max(1, min(int(body.get("depth") or 150), 400))
        if not (probe_chat and chat and below and start):
            return JsonResponse({"ok": False, "error": "chat, below, startswith required"}, status=400)
        found, probed = None, 0
        for mid in range(below - 1, max(0, below - 1 - depth), -1):
            try:
                r = requests.post(f"{api}/forwardMessage", data={"chat_id": probe_chat, "from_chat_id": chat,
                                                                 "message_id": mid, "disable_notification": "true"},
                                  timeout=8).json()
            except Exception:
                continue
            probed += 1
            if not r.get("ok"):
                continue
            fwd = r["result"]
            try:
                requests.post(f"{api}/deleteMessage", data={"chat_id": probe_chat, "message_id": fwd["message_id"]}, timeout=8)
            except Exception:
                pass
            if (fwd.get("text") or "").strip().startswith(start):
                found = mid
                break
            time.sleep(0.03)
        out = {"ok": True, "found": found, "probed": probed}
        if apply and found:
            r = requests.post(f"{api}/deleteMessage", data={"chat_id": chat, "message_id": found}, timeout=8).json()
            out["deleted"] = bool(r.get("ok"))
        return JsonResponse(out)

    if action == "games":
        # {"do": "inspect"}: what the Celery worker holds right now and
        # today's sequences. {"do": "start", "slot": "evening", "apply": true}:
        # start a slot that beat missed (start_game_sequence is idempotent per
        # slot and day, so a slot already running is left alone).
        from django.utils import timezone as _tz
        from tgbot.models import GameSequence
        do = body.get("do") or "inspect"
        seqs = list(GameSequence.objects.filter(date=_tz.localdate()).values(
            "slot", "game_types", "current_index", "current_game_type", "current_game_id", "completed"))
        if do == "start":
            slot = body.get("slot") or "evening"
            if apply:
                from tgbot.tasks import start_game_sequence
                start_game_sequence(slot)
                seqs = list(GameSequence.objects.filter(date=_tz.localdate()).values(
                    "slot", "game_types", "current_index", "current_game_type", "current_game_id", "completed"))
            return JsonResponse({"ok": True, "sequences": seqs}, json_dumps_params={"default": str})
        from collections import Counter
        from src.celery_app import app as _celery
        i = _celery.control.inspect(timeout=3)

        def _names(d):
            c = Counter()
            for tasks in (d or {}).values():
                for t in tasks:
                    c[(t.get("request") or t).get("name") or t.get("name")] += 1
            return dict(c)
        return JsonResponse({"ok": True, "sequences": seqs, "active": _names(i.active()),
                             "reserved": _names(i.reserved()), "scheduled": _names(i.scheduled())},
                            json_dumps_params={"default": str})

    if action == "group-prune":
        # Readers with no report for more than `days` days (or none at all,
        # if they joined that long ago) leave the reading groups: a kick (ban
        # + unban), not a ban -- the bot's join buttons let them back in any
        # time. Bot admins and chat admins stay. Walks readers by id: `limit`
        # per call from `after_id`; answers "next_after_id" and "left".
        import datetime as _dt
        import os as _os

        import requests
        from django.conf import settings as _settings
        from django.utils import timezone as _tz
        from tgbot.models import BroadcastGroup, ConfirmationReport, TelegramProfile
        days = max(30, int(body.get("days") or 100))
        cutoff = _tz.now() - _dt.timedelta(days=days)
        chats = [str(c).strip() for c in (body.get("chats") or [
            _os.environ.get("BOYS_GROUP_ID", ""), _os.environ.get("GIRLS_GROUP_ID", "")]) if str(c).strip()]
        env_admins = [int(a) for a in getattr(_settings, "ADMINS", []) if str(a).strip().lstrip("-").isdigit()]
        recent = ConfirmationReport.objects.filter(date__gte=cutoff).values("user_id")
        qs = (TelegramProfile.objects.filter(created_at__lt=cutoff, is_admin=False)
              .exclude(telegram_id__in=env_admins).exclude(id__in=recent).order_by("id"))
        after_id = int(body.get("after_id") or 0)
        if not apply:
            ever = ConfirmationReport.objects.values("user_id")
            sample = []
            for p in qs[:15]:
                last = ConfirmationReport.objects.filter(user=p).order_by("-date").values_list("date", flat=True).first()
                sample.append({"name": p.full_name, "last_report": str(last.date()) if last else None})
            return JsonResponse({"ok": True, "days": days, "cutoff": str(cutoff.date()), "chats": chats,
                                 "candidates": qs.count(), "never_reported": qs.exclude(id__in=ever).count(),
                                 "other_bot_groups": list(BroadcastGroup.objects.filter(is_active=True)
                                                          .exclude(chat_id__in=chats).values_list("chat_id", "title")),
                                 "sample": sample})
        api = f"https://api.telegram.org/bot{_os.environ.get('API_TOKEN', '')}"
        limit = max(1, min(int(body.get("limit") or 20), 50))
        batch = list(qs.filter(id__gt=after_id)[:limit])
        kicked, errors = [], 0
        for p in batch:
            for chat in chats:
                try:
                    m = requests.post(f"{api}/getChatMember", data={"chat_id": chat, "user_id": p.telegram_id},
                                      timeout=8).json()
                    time.sleep(0.04)
                    if not m.get("ok") or (m.get("result") or {}).get("status") not in ("member", "restricted"):
                        continue
                    b = requests.post(f"{api}/banChatMember", data={
                        "chat_id": chat, "user_id": p.telegram_id,
                        "until_date": int(_tz.now().timestamp()) + 60}, timeout=8).json()
                    requests.post(f"{api}/unbanChatMember", data={
                        "chat_id": chat, "user_id": p.telegram_id, "only_if_banned": "true"}, timeout=8)
                    time.sleep(0.08)
                    if b.get("ok"):
                        kicked.append({"telegram_id": p.telegram_id, "name": p.full_name, "chat": chat})
                    else:
                        errors += 1
                except Exception:
                    errors += 1
        nxt = batch[-1].id if batch else after_id
        return JsonResponse({"ok": True, "checked": len(batch), "kicked": kicked, "errors": errors,
                             "next_after_id": nxt, "left": qs.filter(id__gt=nxt).count()})

    if action == "wallet-gift":
        # A gift of `amount` so'm to every registered reader whose wallet
        # holds less than `below`, once per reader per `tag` (the note is the
        # marker), `limit` readers per call -- call again until "left" is 0.
        # `text` ({name} {som} {balance}) is DMed to each one credited.
        import html
        import os as _os

        import requests
        from django.db import transaction as _txn
        from tgbot.models import TelegramProfile, WalletTransaction
        from tgbot.services import wallet
        tag = (body.get("tag") or "")[:120]
        amount, below = int(body.get("amount") or 0), int(body.get("below") or 0)
        if not tag or amount <= 0 or below <= 0:
            return JsonResponse({"ok": False, "error": "tag, amount and below are required"}, status=400)
        limit = max(1, min(int(body.get("limit") or 200), 500))
        done_ids = WalletTransaction.objects.filter(kind=WalletTransaction.KIND_ADMIN, note=tag).values("user_id")
        todo = (TelegramProfile.objects.filter(is_registered=True, wallet_balance__lt=below)
                .exclude(id__in=done_ids).order_by("id"))
        left = todo.count()
        out = {"ok": True, "eligible_left": left, "done_before": done_ids.count(),
               "total_if_all": left * amount, "blocked_among_left": todo.filter(is_blocked=True).count()}
        if not apply:
            return JsonResponse(out)
        template = body.get("text") or ""
        credited = dms = 0
        for p in todo[:limit]:
            with _txn.atomic():
                q = TelegramProfile.objects.select_for_update().get(id=p.id)
                if q.wallet_balance >= below or WalletTransaction.objects.filter(
                        user=q, kind=WalletTransaction.KIND_ADMIN, note=tag).exists():
                    continue
                wallet._credit_locked(q, amount, WalletTransaction.KIND_ADMIN, tag)
            credited += 1
            if template and not q.is_blocked:
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{_os.environ.get('API_TOKEN', '')}/sendMessage",
                        data={"chat_id": q.telegram_id, "parse_mode": "HTML", "text": template.format(
                            name=html.escape((q.full_name or "Kitobxon").split()[0]),
                            som=f"{amount:,}".replace(",", " "),
                            balance=f"{q.wallet_balance:,}".replace(",", " "))},
                        timeout=8)
                    dms += 1
                except Exception:
                    pass
                time.sleep(0.05)
        out.update(credited=credited, dms=dms, eligible_left=todo.count())
        return JsonResponse(out)

    if action == "shop-product-refund":
        # Take a product off the shop and give every buyer their Kitobcha back,
        # once per purchase (status -> refunded, ledger shop_refund:<id>);
        # straight to the balance, so no member 2x. `text` ({name} {amount})
        # is DMed to each refunded buyer.
        import html
        import os as _os

        import requests
        from django.db import transaction as _txn
        from django.db.models import F
        from tgbot.models import KitobchaLedger, ShopProduct, ShopPurchase, TelegramProfile
        product = ShopProduct.objects.filter(id=int(body["product_id"])).first()
        if not product:
            return JsonResponse({"ok": False, "error": "not_found"}, status=404)
        purchases = list(ShopPurchase.objects.filter(product=product).select_related("user").order_by("id"))
        owed = {}
        if apply:
            ShopProduct.objects.filter(id=product.id).update(is_active=False)
            for pu in purchases:
                with _txn.atomic():
                    claimed = ShopPurchase.objects.filter(id=pu.id).exclude(
                        status=ShopPurchase.STATUS_REFUNDED).update(status=ShopPurchase.STATUS_REFUNDED)
                    if not claimed:
                        continue
                    TelegramProfile.objects.filter(id=pu.user_id).update(ball=F("ball") + pu.price_at_purchase)
                    KitobchaLedger.objects.create(user_id=pu.user_id, delta=pu.price_at_purchase,
                                                  reason=f"shop_refund:{pu.id}"[:40])
                owed[pu.user_id] = owed.get(pu.user_id, 0) + pu.price_at_purchase
            template = body.get("text") or ""
            for pu in purchases:
                amount = owed.pop(pu.user_id, 0)
                if not (template and amount and not pu.user.is_blocked):
                    continue
                try:
                    requests.post(f"https://api.telegram.org/bot{_os.environ.get('API_TOKEN', '')}/sendMessage",
                                  data={"chat_id": pu.user.telegram_id, "parse_mode": "HTML",
                                        "text": template.format(name=html.escape(pu.user.full_name or "Kitobxon"),
                                                                amount=f"{amount:,}".replace(",", " "))},
                                  timeout=8)
                except Exception as e:
                    print(f"shop-product-refund DM {pu.user_id}: {e}")
                time.sleep(0.05)
        rows = [{"purchase": pu.id, "telegram_id": pu.user.telegram_id, "name": pu.user.full_name,
                 "price": pu.price_at_purchase, "status": pu.status, "date": pu.created_at.date().isoformat()}
                for pu in ShopPurchase.objects.filter(product=product).select_related("user").order_by("id")]
        return JsonResponse({"ok": True, "product": product.name, "is_active": ShopProduct.objects.get(id=product.id).is_active,
                             "purchases": len(rows), "kitobcha_total": sum(r["price"] for r in rows), "rows": rows})

    if action == "wallet-refund":
        # Support tool: what a reader may take back (dry), or take it out of
        # the wallet once the money has gone back to their card (apply).
        from tgbot.models import TelegramProfile
        from tgbot.services import wallet
        p = TelegramProfile.objects.filter(telegram_id=int(body["telegram_id"])).first()
        if not p:
            return JsonResponse({"ok": False, "error": "not_found"}, status=404)
        out = {"ok": True, "name": p.full_name, "balance": p.wallet_balance, "refundable": wallet.refundable(p)}
        if apply:
            out["result"] = wallet.refund(p, body.get("amount"), body.get("note") or "")
        return JsonResponse(out)

    if action == "premium-notify":
        # One personal DM to every reader whose Premium days became so'm at the
        # launch, once each (cache marker); `text` uses {name} {days} {som} {until}.
        import html
        import os as _os
        import re as _re

        import requests
        from django.core.cache import cache
        from django.db.models import Max
        from tgbot.models import Payment, WalletTransaction
        from tgbot.services import wallet
        rows = WalletTransaction.objects.filter(kind=WalletTransaction.KIND_PREMIUM).select_related("user")
        template = body.get("text") or ""
        out = []
        for t in rows:
            p = t.user
            m = _re.match(r"(\d+)", t.note or "")
            days = int(m.group(1)) if m else t.delta // wallet.DAY_FEE
            until = Payment.objects.filter(user=p, status="paid").aggregate(m=Max("end_date"))["m"]
            text = template.format(name=html.escape(p.full_name or "Kitobxon"), days=days,
                                   som=f"{t.delta:,}".replace(",", " "),
                                   until=wallet.uz_date(until) if until else "")
            row = {"telegram_id": p.telegram_id, "name": p.full_name, "days": days, "som": t.delta,
                   "until": str(until), "sent_before": bool(cache.get(f"premium_notify:{p.id}"))}
            if apply and template and not row["sent_before"] and not p.is_blocked:
                r = requests.post(f"https://api.telegram.org/bot{_os.environ.get('API_TOKEN', '')}/sendMessage",
                                  data={"chat_id": p.telegram_id, "text": text, "parse_mode": "HTML"}, timeout=8)
                row["sent"] = r.ok
                if r.ok:
                    cache.set(f"premium_notify:{p.id}", 1, None)
                elif r.status_code == 403:
                    p.__class__.objects.filter(id=p.id).update(is_blocked=True)
                time.sleep(0.05)
            out.append(row)
        preview = template.format(name="Kitobxon", days=10, som="10 000", until="10-noyabr") if template else ""
        return JsonResponse({"ok": True, "count": len(out), "rows": out, "preview": preview})

    if action == "app-shell":
        # The site's swipe shell (services/app_shell.py): {"on": true|false}
        # with apply switches it for everyone; without apply, the state.
        from tgbot.services import app_shell
        if apply and "on" in body:
            app_shell.set_enabled(bool(body.get("on")))
        return JsonResponse({"ok": True, "on": app_shell.enabled()})

    if action == "wallet-audit":
        # One day of money: wallet moves, top-ups, report charges against
        # report submissions (unpaid lists any report without its charge).
        from tgbot.services import wallet
        s = wallet.day_summary(body.get("date"))
        return JsonResponse({"ok": True, **s, "text": wallet.day_summary_text(s)})

    if action == "wallet-credit":
        # Support tool: credit (or, negative, debit) one reader's wallet.
        from tgbot.models import TelegramProfile, WalletTransaction
        from tgbot.services import wallet
        p = TelegramProfile.objects.filter(telegram_id=int(body["telegram_id"])).first()
        if not p:
            return JsonResponse({"ok": False, "error": "not_found"}, status=404)
        amount = int(body.get("amount") or 0)
        out = {"ok": True, "name": p.full_name, "balance": p.wallet_balance, "amount": amount}
        if apply and amount:
            if amount > 0:
                out["balance"] = wallet.credit(p, amount, WalletTransaction.KIND_ADMIN, body.get("note") or "")
            else:
                from django.db import transaction as _txn
                with _txn.atomic():
                    q = TelegramProfile.objects.select_for_update().get(id=p.id)
                    take = min(-amount, q.wallet_balance)
                    q.wallet_balance -= take
                    q.save(update_fields=["wallet_balance"])
                    WalletTransaction.objects.create(user=q, kind=WalletTransaction.KIND_ADMIN, delta=-take,
                                                     balance_after=q.wallet_balance,
                                                     note=(body.get("note") or "")[:120])
                out["balance"] = q.wallet_balance
        return JsonResponse(out)

    if action == "alphabet":
        from tgbot.services import alphabet
        if "on" in body and apply:
            alphabet.set_enabled(bool(body["on"]))
        return JsonResponse({"ok": True, "on": alphabet.enabled(),
                             "sample": alphabet.to_new(body.get("text") or "")})

    if action == "user-dates":
        return JsonResponse({"ok": True, **ops_fixes.user_dates(body["telegram_id"], body.get("since") or "2026-08-01")})

    if action == "themes":
        plan = ops_fixes.theme_plan(body.get("old_owners"))
        out = {"ok": True, "buyers": len(plan),
               "to_grant": sum(len(r["grant"]) for r in plan),
               "refund_total": sum(r["refund_total"] for r in plan), "plan": plan}
        if apply:
            out["applied"] = ops_fixes.apply_themes(plan, refund=bool(body.get("refund")))
        return JsonResponse(out)

    if action == "set-admin":
        return JsonResponse({"ok": True, **ops_fixes.set_admin(body["telegram_id"], apply)})

    if action == "kitobcha-credit":
        if not body.get("tag"):
            return JsonResponse({"ok": False, "error": "tag_required"}, status=400)
        return JsonResponse({"ok": True, **ops_fixes.kitobcha_credit(
            body.get("rows") or [], body["tag"], apply, body.get("notify_text") or "")})

    if action == "broadcast":
        campaign, text = body.get("campaign", ""), body.get("text", "")
        if not campaign or not text:
            return JsonResponse({"ok": False, "error": "campaign_and_text_required"}, status=400)
        if not apply:
            return JsonResponse({"ok": True, "preview": text, "status": ops_broadcast.status(campaign)})

        def _run():
            try:
                ops_broadcast.run(campaign, text, groups=body.get("groups", True),
                                  users=body.get("users", True),
                                  button_text=body.get("button_text", ""),
                                  button_url=body.get("button_url", ""))
            except Exception:
                print("internal_ops broadcast failed:\n" + traceback.format_exc())

        threading.Thread(target=_run, daemon=True).start()
        return JsonResponse({"ok": True, "started": campaign}, status=202)

    if action == "broadcast-status":
        return JsonResponse({"ok": True, "status": ops_broadcast.status(body.get("campaign", ""))})

    if action == "headliner":
        from tgbot.tasks import _GAME_STARTERS, set_slot_headliner, slot_headliner
        day, slot, game = body.get("date", ""), body.get("slot", "evening"), body.get("game")
        if not day:
            return JsonResponse({"ok": False, "error": "date_required"}, status=400)
        if game and game not in _GAME_STARTERS:
            return JsonResponse({"ok": False, "error": "unknown_game"}, status=400)
        if apply:
            set_slot_headliner(day, slot, game or None)
        return JsonResponse({"ok": True, "date": day, "slot": slot, "headliner": slot_headliner(day, slot)})

    return JsonResponse({"ok": False, "error": "unknown_action"}, status=404)


@csrf_exempt
def internal_retire_challenge_and_launch_boom(request: HttpRequest):
    """One-off trigger for tgbot.tasks.retire_challenge_and_launch_boom.
    POST only. WARNING: this launches the boom, which sends the full
    announcement broadcast to every group + registered user immediately --
    same scale as any other boom launch. Runs in a background thread since
    it can run well past gunicorn's request timeout. Delete this view/URL
    once used."""
    import os as _os

    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
        return HttpResponse(status=403)

    from tgbot.tasks import retire_challenge_and_launch_boom

    def _run():
        try:
            retire_challenge_and_launch_boom()
        except Exception as e:
            print(f"internal_retire_challenge_and_launch_boom failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return HttpResponse("started", status=202)


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
