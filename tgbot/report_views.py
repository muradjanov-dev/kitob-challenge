"""Daily reading report — web port of the bot's "📚 Kitob hisoboti" flow
(tgbot/bot/handlers/users/report.py). Same Telegram WebApp initData auth
pattern as shop_views.py / library_views.py / cabinet_views.py.

Supports the same shape as the bot: one or more books in a single report
(picked from the user's own BooksToRead, or typed as brand-new), and a
mixed paper+audio submission in one go. Still one report a day for
non-Premium (Premium's in-place group-message editing across same-day
resubmits stays bot-only for now -- the web form always posts a fresh
group message)."""
import hashlib
import hmac
import json
import random
from urllib.parse import parse_qsl

import requests
from django.conf import settings
from django.db.models import F
from django.db.models.functions import TruncDate
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from tgbot.bot.consts import (
    BOYS_GROUP_ID, GIRLS_GROUP_ID,
    B_BOYS_THREAD_ID, B_GIRLS_THREAD_ID,
    D_BOYS_THREAD_ID, D_GIRLS_THREAD_ID,
    C_BOYS_THREAD_ID, C_GIRLS_THREAD_ID,
    E_BOYS_THREAD_ID, E_GIRLS_THREAD_ID,
)
from tgbot.bot.handlers.users.report import MOTIVATIONS, PREMIUM_CTAS, PREMIUM_CTA_CHANCE, _pick_praise
from tgbot.models import (
    BookReport, BooksToRead, ConfirmationReport, GlobalBook, TelegramProfile, normalize_uzbek_text,
)

BOT_TOKEN = settings.API_TOKEN


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
    return request.headers.get("X-Telegram-Init-Data") or request.POST.get("initData") or ""


def _resolve_profile(init_data: str):
    tg_user = _verify_init_data(init_data)
    if not tg_user:
        return None, "invalid_init_data"
    profile = TelegramProfile.objects.filter(telegram_id=str(tg_user["id"])).first()
    if not profile:
        return None, "not_registered"
    return profile, None


def _compute_reading_day(user, today) -> int:
    distinct_days = (
        ConfirmationReport.objects.filter(user=user)
        .annotate(_d=TruncDate("date")).values("_d").distinct().count()
    )
    has_today = ConfirmationReport.objects.filter(user=user, date__date=today).exists()
    return distinct_days if has_today else distinct_days + 1


def _resolve_or_create_book(title: str, global_book_id, is_audio: bool):
    gbook = None
    if global_book_id:
        gbook = GlobalBook.objects.filter(id=global_book_id).first()
    if not gbook:
        normalized = normalize_uzbek_text(title)
        gbook = GlobalBook.objects.filter(normalized_title=normalized).first()
        if not gbook:
            gbook = GlobalBook.objects.filter(title__iexact=title.strip()).first()
            if not gbook:
                try:
                    gbook = GlobalBook.objects.create(title=title.strip())
                except Exception:
                    gbook = GlobalBook.objects.filter(normalized_title=normalized).first()
    return gbook


@require_GET
def api_my_report_books(request: HttpRequest) -> JsonResponse:
    """Same book list + % complete the bot's send_book_selection_menu shows,
    for the report form's dropdown -- active books first, then not-started,
    then already-finished (mirrors get_user_books' sort_order)."""
    init_data = _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=403)

    from django.db.models import Case, When, IntegerField, Value

    books = (
        BooksToRead.objects.filter(user=profile)
        .annotate(
            sort_order=Case(
                When(current_page=0, then=Value(1)),
                When(total_pages__gt=0, current_page__gte=F("total_pages"), then=Value(2)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("sort_order", "-created_at")[:100]
    )
    return JsonResponse({
        "ok": True,
        "books": [
            {
                "id": b.id,
                "title": b.title,
                "is_audio": b.is_audio,
                "percent": int((b.current_page / b.total_pages) * 100) if b.total_pages else 0,
            }
            for b in books
        ],
    })


def _entry_book_obj(profile, entry):
    """Resolve one report entry to (BooksToRead row, is_audio, amount, label)."""
    amount = int(entry.get("amount"))
    if amount <= 0:
        raise ValueError("invalid_amount")

    book_to_read_id = entry.get("book_to_read_id")
    if book_to_read_id:
        book_obj = BooksToRead.objects.filter(id=book_to_read_id, user=profile).first()
        if not book_obj:
            raise ValueError("book_not_found")
        return book_obj, book_obj.is_audio, amount

    title = (entry.get("book_title") or "").strip()
    if not title:
        raise ValueError("book_title required")
    if len(title) > 255:
        raise ValueError("book_title_too_long")
    is_audio = bool(entry.get("is_audio"))
    gbook = _resolve_or_create_book(title, entry.get("global_book_id"), is_audio)
    book_obj = BooksToRead.objects.filter(user=profile, global_book=gbook, is_audio=is_audio).first()
    if not book_obj:
        book_obj = BooksToRead.objects.create(
            user=profile, global_book=gbook, title=gbook.title if gbook else title,
            is_audio=is_audio, total_pages=0, current_page=0,
        )
    return book_obj, is_audio, amount


@csrf_exempt
@require_POST
def api_submit_report(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    init_data = body.get("initData") or _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=403)

    if profile.is_blocked:
        return JsonResponse({"ok": False, "error": "blocked"}, status=403)

    entries = body.get("entries")
    if not isinstance(entries, list) or not entries:
        return JsonResponse({"ok": False, "error": "entries required"}, status=400)
    if len(entries) > 20:
        return JsonResponse({"ok": False, "error": "too_many_entries"}, status=400)

    conclusion = (body.get("conclusion") or "").strip() or None

    try:
        resolved = [_entry_book_obj(profile, e) for e in entries]
    except ValueError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)

    is_premium = profile.has_active_premium()
    today = timezone.localdate()
    already_today = ConfirmationReport.objects.filter(user=profile, date__date=today).exists()
    if already_today and not is_premium:
        return JsonResponse({"ok": False, "error": "already_reported_today"}, status=409)

    reading_day = _compute_reading_day(profile, today)
    now = timezone.now()

    text_entries = [(b, a) for b, is_a, a in resolved if not is_a]
    audio_entries = [(b, a) for b, is_a, a in resolved if is_a]

    reports = []
    if text_entries:
        total_pages = sum(a for _, a in text_entries)
        r = ConfirmationReport.objects.create(
            user=profile, pages_read=total_pages, date=now, conclusion=conclusion,
            book=text_entries[0][0].title[:255], is_audio=False,
        )
        r.books.set([b.id for b, _ in text_entries])
        reports.append(r)
    if audio_entries:
        total_minutes = sum(a for _, a in audio_entries)
        r = ConfirmationReport.objects.create(
            user=profile, pages_read=0, date=now, conclusion=conclusion,
            book=audio_entries[0][0].title[:255], is_audio=True, minutes_listened=total_minutes,
        )
        r.books.set([b.id for b, _ in audio_entries])
        reports.append(r)

    # Advance each book's own progress and log a per-book BookReport row --
    # same per-book granularity as the bot's book_reports loop.
    lines = []
    for book_obj, is_audio, amount in resolved:
        book_obj.current_page += amount
        if book_obj.total_pages > 0 and book_obj.current_page > book_obj.total_pages:
            book_obj.current_page = book_obj.total_pages
        book_obj.save(update_fields=["current_page", "updated_at"])
        BookReport.objects.create(
            user=profile, global_book=book_obj.global_book, reading_day=reading_day,
            book=book_obj.title, pages_read=amount,
        )
        unit = "daqiqa" if is_audio else "bet"
        icon = "🎧" if is_audio else "📖"
        lines.append(f"{icon} {book_obj.title}: {amount} {unit}")

    # ── Group post (same gender/page-tier routing as the bot; posts a fresh
    # message even for a Premium user's Nth report today -- no in-place
    # group-message editing/aggregation on the web form yet). ──
    prem_badge = "💎 " if is_premium else ""
    motivation = random.choice(MOTIVATIONS)
    conclusion_block = (
        f"<b>💡 Olingan xulosa:</b>\n<blockquote expandable>{conclusion}</blockquote>"
        if conclusion else ""
    )
    books_block = "<b>O'qilgan kitoblar:</b>\n\n" + "\n".join(lines)
    report_message = (
        f"<b><a href='tg://user?id={profile.telegram_id}'>{prem_badge}{profile.full_name}</a></b>:\n\n"
        f"📊#kun - {reading_day}  ({now.strftime('%Y-%m-%d')})\n\n"
        f"{books_block}\n\n"
        f"{conclusion_block}\n\n"
        f"<b>{motivation}</b>"
        f"\n\n<i>🌌 Parallel olam orqali yuborildi</i>"
    )

    routing_pages = sum(a for _, a in text_entries)
    if profile.gender == "male":
        target_chat_id = BOYS_GROUP_ID
        target_thread_id = (
            B_BOYS_THREAD_ID if routing_pages <= 50 else
            D_BOYS_THREAD_ID if routing_pages <= 100 else
            C_BOYS_THREAD_ID if routing_pages <= 500 else E_BOYS_THREAD_ID
        )
    else:
        target_chat_id = GIRLS_GROUP_ID
        target_thread_id = (
            B_GIRLS_THREAD_ID if routing_pages <= 50 else
            D_GIRLS_THREAD_ID if routing_pages <= 100 else
            C_GIRLS_THREAD_ID if routing_pages <= 500 else E_GIRLS_THREAD_ID
        )

    group_message_id = None
    if target_chat_id:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": target_chat_id, "message_thread_id": target_thread_id,
                    "text": report_message, "parse_mode": "HTML",
                },
                timeout=8,
            )
            if resp.ok:
                group_message_id = resp.json().get("result", {}).get("message_id")
        except Exception:
            pass

    if group_message_id:
        ConfirmationReport.objects.filter(id__in=[r.id for r in reports]).update(
            group_chat_id=target_chat_id, group_message_id=group_message_id,
            group_thread_id=target_thread_id, reading_day=reading_day,
        )

    # Kitobcha only on the first report of the day (race-safe: only the
    # smallest-id row from today triggers it), same as the bot.
    todays_first_id = (
        ConfirmationReport.objects.filter(user=profile, date__date=today)
        .order_by("id").values_list("id", flat=True).first()
    )
    awarded = 0
    premium_cta = None
    if todays_first_id in {r.id for r in reports}:
        awarded = profile.update_ball(True, 25)
        if awarded == 25 and random.random() < PREMIUM_CTA_CHANCE:
            premium_cta = random.choice(PREMIUM_CTAS)

    try:
        from tgbot.tasks import check_user_achievements
        check_user_achievements.delay(profile.id)
    except Exception:
        pass

    # Deferred referral credit -- same "any report counts" rule as the bot.
    # process_referral is async (aiogram-side helper); bridge it since this
    # view runs synchronously.
    if profile.pending_referral_code:
        code = profile.pending_referral_code
        TelegramProfile.objects.filter(id=profile.id).update(pending_referral_code=None)
        try:
            from asgiref.sync import async_to_sync
            from tgbot.services.referral import ReferralService
            async_to_sync(ReferralService.process_referral)(profile, code)
        except Exception as e:
            # Match report.py's bot-side path: the code is already cleared by
            # now (prevents double-counting on concurrent triggers), so a
            # failure here silently loses the referral with zero trace unless
            # logged -- this was previously a bare `except Exception: pass`.
            print(f"deferred referral processing failed (web report) for profile {profile.id}: {e}")

    return JsonResponse({
        "ok": True,
        "praise": _pick_praise(profile),
        "reading_day": reading_day,
        "awarded": awarded,
        "balance": int(profile.ball or 0),
        "premium_cta": premium_cta,
        "posted_to_group": bool(group_message_id),
    })
