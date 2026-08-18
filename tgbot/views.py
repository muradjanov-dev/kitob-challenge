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
def internal_broadcast_auction_announcement(request: HttpRequest):
    """One-off trigger for auction_announce.broadcast_auction_announcement.
    POST only, runs in a background thread."""
    import os as _os

    if request.method != "POST":
        return HttpResponse(status=405)
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != _os.environ.get("API_TOKEN", ""):
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
