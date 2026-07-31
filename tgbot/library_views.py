"""Library API — comments on GlobalBook entries, and the web e-reader's
reading economy (start fee, per-page reward, finish top-up guarantee).

Auth: Telegram WebApp initData, same pattern as shop_views.py.
Users who haven't registered in the bot yet get a 403.
Each user can leave one comment per book (upsert on re-submit).
"""
import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from tgbot.models import BookComment, BooksToRead, GlobalBook, KitobchaLedger, TelegramProfile

# ── Web e-reader economy ────────────────────────────────────────────────────
# Starting a book costs this once; finishing pays 1 Kitobcha/page (2x
# Premium) as pages are genuinely read, topped up to at least cover the
# start fee if the book turned out shorter than break-even.
BOOK_START_FEE = 375
SECONDS_PER_PAGE = 18  # 30 min minimum for a 100-page book, scaled from there
MAX_IDLE_GAP_SECONDS = 600  # >10 min since the last real interaction = AFK, not reading


# ── initData auth ──────────────────────────────────────────────────────────

def _verify_init_data(init_data: str) -> dict | None:
    if not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    except ValueError:
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", settings.API_TOKEN.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return None
    user_json = pairs.get("user")
    if not user_json:
        return None
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user


def _read_init_data(request: HttpRequest) -> str:
    return (
        request.headers.get("X-Telegram-Init-Data")
        or request.POST.get("initData")
        or request.GET.get("initData")
        or ""
    )


def _resolve_profile(init_data: str) -> tuple:
    tg_user = _verify_init_data(init_data)
    if not tg_user:
        return None, "invalid_init_data"
    profile = TelegramProfile.objects.filter(telegram_id=str(tg_user["id"])).first()
    if not profile:
        return None, "not_registered"
    return profile, None


# ── GET /kutubxona/api/comments/?book_id=N ────────────────────────────────

@require_GET
def api_comments(request: HttpRequest):
    book_id = request.GET.get("book_id")
    if not book_id or not book_id.isdigit():
        return JsonResponse({"error": "book_id required"}, status=400)

    comments = (
        BookComment.objects
        .filter(book_id=int(book_id))
        .select_related("user")
        .order_by("-created_at")[:50]
    )
    return JsonResponse({
        "comments": [
            {
                "id": c.id,
                "user": c.user.full_name or "Kitobxon",
                "text": c.text,
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for c in comments
        ]
    })


# ── POST /kutubxona/api/comment/ ──────────────────────────────────────────

@csrf_exempt
@require_POST
def api_add_comment(request: HttpRequest):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    init_data = body.get("initData") or _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_id = body.get("book_id")
    text = (body.get("text") or "").strip()

    if not book_id:
        return JsonResponse({"error": "book_id required"}, status=400)
    if not text:
        return JsonResponse({"error": "text required"}, status=400)
    if len(text) > 1000:
        return JsonResponse({"error": "too_long"}, status=400)

    book = GlobalBook.objects.filter(id=book_id).first()
    if not book:
        return JsonResponse({"error": "not_found"}, status=404)

    comment, created = BookComment.objects.update_or_create(
        book=book,
        user=profile,
        defaults={"text": text},
    )
    return JsonResponse({
        "ok": True,
        "created": created,
        "comment": {
            "id": comment.id,
            "user": profile.full_name or "Kitobxon",
            "text": comment.text,
            "created_at": comment.created_at.strftime("%Y-%m-%d %H:%M"),
        },
    })


# ── DELETE /kutubxona/api/comment/ ────────────────────────────────────────

@csrf_exempt
def api_delete_comment(request: HttpRequest):
    if request.method != "DELETE":
        return JsonResponse({"error": "method_not_allowed"}, status=405)
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    init_data = body.get("initData") or _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_id = body.get("book_id")
    if not book_id:
        return JsonResponse({"error": "book_id required"}, status=400)

    deleted, _ = BookComment.objects.filter(book_id=book_id, user=profile).delete()
    return JsonResponse({"ok": True, "deleted": deleted > 0})


# ── GET /kutubxona/api/my-books/ ──────────────────────────────────────────────

@require_GET
def api_my_books(request: HttpRequest):
    init_data = _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    started = list(
        BooksToRead.objects
        .filter(user=profile, total_pages__gt=0, global_book_id__isnull=False)
        .values("global_book_id", "current_page", "total_pages")
        .order_by("-updated_at")
    )
    book_ids = [r["global_book_id"] for r in started]
    # In progress = has a real page position, hasn't reached the end --
    # feeds the "davom eting" continue-reading carousel on the shelf page.
    in_progress = [
        {
            "id": r["global_book_id"],
            "current_page": r["current_page"],
            "total_pages": r["total_pages"],
            "pct": round(r["current_page"] * 100 / r["total_pages"]),
        }
        for r in started
        if 0 < r["current_page"] < r["total_pages"]
    ]
    return JsonResponse({"book_ids": book_ids, "in_progress": in_progress})


def _get_reading_record(profile, book_id, for_update=False):
    """No unique_together on (user, global_book) historically (and the bot's
    own self-report flow, report.py, can create rows against the same
    GlobalBook), so a couple of accounts may already carry more than one row
    for the same book -- always take the first instead of update_or_create()
    to avoid MultipleObjectsReturned.

    Critical: prefer an already fee_charged=True row over any duplicate.
    Plain .first() with no ordering is non-deterministic across calls, so if
    one duplicate was already charged and another wasn't, an unordered pick
    could intermittently show the book as "not started" and charge
    BOOK_START_FEE a second time -- or, in api_save_progress, silently split
    page-reward/top-up bookkeeping across two different rows. Preferring the
    charged row (deterministically, by id) makes "already started" durable
    regardless of which duplicate a plain query would otherwise have picked.
    Single source of truth for all three read/write sites in this file --
    they must all resolve the exact same row for the same (user, book)."""
    qs = BooksToRead.objects.filter(user=profile, global_book_id=book_id)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(fee_charged=True).order_by("id").first() or qs.order_by("id").first()


# ── POST /kutubxona/api/start-reading/ ─────────────────────────────────────
# Called right before the reader opens. Charges BOOK_START_FEE exactly once
# per (user, book); repeat calls (re-opening a book already started) are free
# and just return the saved position to resume from.

@csrf_exempt
@require_POST
def api_start_reading(request: HttpRequest):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    init_data = body.get("initData") or _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_id = body.get("book_id")
    if not book_id:
        return JsonResponse({"error": "book_id required"}, status=400)
    book = GlobalBook.objects.filter(id=book_id).first()
    if not book:
        return JsonResponse({"error": "not_found"}, status=404)

    # Fast path, no lock needed: already started, nothing to charge.
    record = _get_reading_record(profile, book.id)
    if record and record.fee_charged:
        return JsonResponse({
            "ok": True, "charged": False,
            "current_page": record.max_page_reached, "total_pages": record.total_pages,
        })

    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=profile.id)
        # Re-check under the profile lock: a concurrent duplicate tap (double
        # click, retried request) blocks here until the first one commits,
        # then sees fee_charged=True and must not charge a second time.
        record = _get_reading_record(profile, book.id)
        if record and record.fee_charged:
            return JsonResponse({
                "ok": True, "charged": False,
                "current_page": record.max_page_reached, "total_pages": record.total_pages,
            })

        if p.ball < BOOK_START_FEE:
            return JsonResponse({
                "error": "insufficient_balance",
                "balance": int(p.ball or 0),
                "required": BOOK_START_FEE,
            }, status=402)
        p.ball = p.ball - BOOK_START_FEE
        p.save(update_fields=["ball"])
        KitobchaLedger.objects.create(user=p, delta=-BOOK_START_FEE, reason="book_start_fee")

        if record:
            record.fee_charged = True
            record.save(update_fields=["fee_charged", "updated_at"])
        else:
            record = BooksToRead.objects.create(
                user=profile, global_book=book, title=book.title,
                is_audio=False, current_page=0, total_pages=0, fee_charged=True,
            )

    return JsonResponse({
        "ok": True, "charged": True, "balance": int(p.ball or 0),
        "current_page": record.max_page_reached, "total_pages": record.total_pages,
    })


# ── GET /kutubxona/api/progress/?book_id=N ────────────────────────────────

@require_GET
def api_premium_access(request: HttpRequest):
    """A premium-only book's pdf/audio URL is never sent in the public page
    JSON (books_json in views.py doesn't know who's viewing). Premium/Extra-
    Premium readers fetch the real file URL here instead, once initData
    proves who they are."""
    init_data = _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=403)

    book_id = request.GET.get("book_id")
    if not book_id or not book_id.isdigit():
        return JsonResponse({"ok": False, "error": "book_id required"}, status=400)

    book = GlobalBook.objects.filter(id=book_id).first()
    if not book:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    if not book.is_premium_only:
        # Not actually gated -- the public JSON already carries this one.
        return JsonResponse({
            "ok": True,
            "pdf": book.pdf_file.url if book.pdf_file else None,
            "audio": book.audio_file.url if book.audio_file else None,
        })

    if not profile.has_active_premium():
        return JsonResponse({"ok": False, "error": "premium_required"}, status=403)

    return JsonResponse({
        "ok": True,
        "pdf": book.pdf_file.url if book.pdf_file else None,
        "audio": book.audio_file.url if book.audio_file else None,
    })


@require_GET
def api_get_progress(request: HttpRequest):
    init_data = _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_id = request.GET.get("book_id")
    if not book_id or not book_id.isdigit():
        return JsonResponse({"error": "book_id required"}, status=400)

    record = _get_reading_record(profile, int(book_id))
    # Resume from max_page_reached, not current_page -- current_page can be
    # nudged by the bot's unrelated self-report flow (report.py), which
    # shares this same row/table but has no idea about the web reader.
    return JsonResponse({
        "current_page": record.max_page_reached if record else 0,
        "total_pages": record.total_pages if record else 0,
    })


# ── POST /kutubxona/api/progress/ ─────────────────────────────────────────
# Called on every real page turn and on other in-reader interactions
# (scroll/zoom), never on a blind timer -- see SECONDS_PER_PAGE /
# MAX_IDLE_GAP_SECONDS docs above for why that distinction matters.

@csrf_exempt
@require_POST
def api_save_progress(request: HttpRequest):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    init_data = body.get("initData") or _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_id = body.get("book_id")
    if not book_id:
        return JsonResponse({"error": "book_id required"}, status=400)
    try:
        current_page = int(body.get("current_page"))
        total_pages = int(body.get("total_pages"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_pages"}, status=400)
    if current_page < 0 or total_pages < 0:
        return JsonResponse({"error": "invalid_pages"}, status=400)

    book = GlobalBook.objects.filter(id=book_id).first()
    if not book:
        return JsonResponse({"error": "not_found"}, status=404)

    now = timezone.now()
    granted_now = 0
    finished = False

    # Locked for the whole read-compute-write so two near-simultaneous pings
    # for the same (user, book) can't both read the same credited_pages and
    # both grant a reward for the same pages -- they serialize instead.
    with transaction.atomic():
        record = _get_reading_record(profile, book.id, for_update=True)
        if record:
            gap_seconds = (now - record.updated_at).total_seconds()
        else:
            # Defensive fallback: start-reading wasn't called first for some
            # reason. Create the row without charging -- no fee was taken,
            # so this book also won't be eligible for the finish top-up.
            record = BooksToRead.objects.create(
                user=profile, global_book=book, title=book.title,
                is_audio=False, current_page=0, total_pages=0,
            )
            gap_seconds = 0

        if 0 < gap_seconds <= MAX_IDLE_GAP_SECONDS:
            record.active_seconds += int(gap_seconds)
        # else: either the very first ping (gap==0) or > 10 min idle -- the
        # gap itself is simply not counted; active_seconds already earned stands.

        record.title = book.title
        record.is_audio = False
        record.current_page = current_page
        record.total_pages = total_pages
        record.max_page_reached = max(record.max_page_reached, current_page)

        if total_pages > 0:
            pending_pages = min(record.max_page_reached, total_pages) - record.credited_pages
            time_allowed_pages = record.active_seconds // SECONDS_PER_PAGE
            pages_to_credit = min(pending_pages, max(0, time_allowed_pages - record.credited_pages))
            if pages_to_credit > 0:
                granted_now = profile.update_ball(True, pages_to_credit)
                record.credited_pages += pages_to_credit
                record.page_reward_total_granted += granted_now

            if (
                record.max_page_reached >= total_pages
                and record.credited_pages >= total_pages
                and record.fee_charged
                and not record.topped_up
            ):
                shortfall = BOOK_START_FEE - record.page_reward_total_granted
                if shortfall > 0:
                    p = TelegramProfile.objects.select_for_update().get(id=profile.id)
                    p.ball = p.ball + shortfall
                    p.save(update_fields=["ball"])
                    KitobchaLedger.objects.create(user=p, delta=shortfall, reason="book_finish_topup")
                record.topped_up = True
                finished = True

        record.save(update_fields=[
            "title", "is_audio", "current_page", "total_pages", "max_page_reached",
            "active_seconds", "credited_pages", "page_reward_total_granted",
            "topped_up", "updated_at",
        ])

    return JsonResponse({
        "ok": True,
        "current_page": record.current_page,
        "total_pages": record.total_pages,
        "granted_now": granted_now,
        "total_granted": record.page_reward_total_granted,
        "finished": finished,
    })


# ── GET /kutubxona/api/comments/recent/ ───────────────────────────────────────

@require_GET
def api_recent_comments(request: HttpRequest):
    limit = min(int(request.GET.get("limit", 20)), 50)
    comments = (
        BookComment.objects
        .select_related("user", "book")
        .order_by("-created_at")[:limit]
    )
    return JsonResponse({
        "comments": [
            {
                "id": c.id,
                "book": c.book.title,
                "book_id": c.book_id,
                "user": c.user.full_name or "Kitobxon",
                "text": c.text,
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for c in comments
        ]
    })
