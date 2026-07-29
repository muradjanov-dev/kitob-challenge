"""Daily reading report — web port of the bot's "📚 Kitob hisoboti" flow
(tgbot/bot/handlers/users/report.py). Same Telegram WebApp initData auth
pattern as shop_views.py / library_views.py / cabinet_views.py.

Deliberately a simplified single-book port: the bot flow also supports
selecting multiple books in one report, combined audio+text entries, and
editing a Premium user's group message in place across same-day resubmits.
Those stay bot-only for now -- the web form covers the common case (one
book, one report a day) so accountability the pinned-progress economy is
already built on doesn't fork into two different data shapes.
"""
import hashlib
import hmac
import json
import random
from urllib.parse import parse_qsl

import requests
from django.conf import settings
from django.db.models.functions import TruncDate
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tgbot.bot.consts import (
    BOYS_GROUP_ID, GIRLS_GROUP_ID,
    B_BOYS_THREAD_ID, B_GIRLS_THREAD_ID,
    D_BOYS_THREAD_ID, D_GIRLS_THREAD_ID,
    C_BOYS_THREAD_ID, C_GIRLS_THREAD_ID,
    E_BOYS_THREAD_ID, E_GIRLS_THREAD_ID,
)
from tgbot.bot.handlers.users.report import MOTIVATIONS, PREMIUM_CTAS, PREMIUM_CTA_CHANCE, _pick_praise
from tgbot.models import BookReport, ConfirmationReport, GlobalBook, TelegramProfile, normalize_uzbek_text

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

    book_title = (body.get("book_title") or "").strip()
    if not book_title:
        return JsonResponse({"ok": False, "error": "book_title required"}, status=400)
    if len(book_title) > 255:
        return JsonResponse({"ok": False, "error": "book_title_too_long"}, status=400)

    global_book_id = body.get("global_book_id")
    is_audio = bool(body.get("is_audio"))
    conclusion = (body.get("conclusion") or "").strip() or None

    try:
        amount = int(body.get("amount"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "invalid_amount"}, status=400)
    if amount <= 0:
        return JsonResponse({"ok": False, "error": "invalid_amount"}, status=400)

    is_premium = profile.has_active_premium()
    today = timezone.localdate()
    already_today = ConfirmationReport.objects.filter(user=profile, date__date=today).exists()
    if already_today and not is_premium:
        return JsonResponse({"ok": False, "error": "already_reported_today"}, status=409)

    reading_day = _compute_reading_day(profile, today)
    now = timezone.now()

    pages_read = 0 if is_audio else amount
    minutes_listened = amount if is_audio else None

    report = ConfirmationReport.objects.create(
        user=profile, pages_read=pages_read, date=now, conclusion=conclusion,
        book=book_title[:255], is_audio=is_audio, minutes_listened=minutes_listened,
    )

    # Attach/advance the matching BooksToRead row the same way the bot does,
    # so this shows up correctly in "mening kitoblarim" and the reader.
    gbook = _resolve_or_create_book(book_title, global_book_id, is_audio)
    from tgbot.models import BooksToRead
    book_obj = BooksToRead.objects.filter(user=profile, global_book=gbook, is_audio=is_audio).first()
    if not book_obj:
        book_obj = BooksToRead.objects.create(
            user=profile, global_book=gbook, title=gbook.title if gbook else book_title,
            is_audio=is_audio, total_pages=0, current_page=0,
        )
    book_obj.current_page += amount
    if book_obj.total_pages > 0 and book_obj.current_page > book_obj.total_pages:
        book_obj.current_page = book_obj.total_pages
    book_obj.save(update_fields=["current_page", "updated_at"])
    report.books.set([book_obj.id])

    BookReport.objects.create(
        user=profile, global_book=gbook, reading_day=reading_day,
        book=book_obj.title, pages_read=amount,
    )

    # ── Group post (same gender/page-tier routing as the bot; simplified to
    # a single book/report, no Premium in-place-edit aggregation). ──
    unit = "daqiqa" if is_audio else "bet"
    icon = "🎧" if is_audio else "📖"
    prem_badge = "💎 " if is_premium else ""
    motivation = random.choice(MOTIVATIONS)
    conclusion_block = (
        f"<b>💡 Olingan xulosa:</b>\n<blockquote expandable>{conclusion}</blockquote>"
        if conclusion else ""
    )
    report_message = (
        f"<b><a href='tg://user?id={profile.telegram_id}'>{prem_badge}{profile.full_name}</a></b>:\n\n"
        f"📊#kun - {reading_day}  ({report.date.strftime('%Y-%m-%d')})\n\n"
        f"<b>O'qilgan kitoblar:</b>\n\n{icon} {book_title} ({amount} {unit})\n\n"
        f"{conclusion_block}\n\n"
        f"<b>{motivation}</b>"
        f"\n\n<i>🌌 Parallel olam orqali yuborildi</i>"
    )

    routing_pages = pages_read
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
        ConfirmationReport.objects.filter(id=report.id).update(
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
    if todays_first_id == report.id:
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
        except Exception:
            pass

    return JsonResponse({
        "ok": True,
        "praise": _pick_praise(profile),
        "reading_day": reading_day,
        "awarded": awarded,
        "balance": int(profile.ball or 0),
        "premium_cta": premium_cta,
        "posted_to_group": bool(group_message_id),
    })
