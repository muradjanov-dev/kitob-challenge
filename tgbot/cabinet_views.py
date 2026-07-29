"""Kabinet (profile/dashboard) — web port of the bot's "👤 Kabinet" menu
(tgbot/bot/handlers/users/cabinet.py). Same Telegram WebApp initData auth
pattern as shop_views.py / library_views.py.
"""
import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from django.conf import settings
from django.db.models import Avg, Count, F, Sum
from django.db.models.functions import ExtractHour, ExtractWeekDay
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from tgbot.models import BookQuizAnswer, BookReport, BooksToRead, ConfirmationReport, TelegramProfile


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
    return request.headers.get("X-Telegram-Init-Data") or request.GET.get("initData") or ""


def _resolve_profile(init_data: str):
    tg_user = _verify_init_data(init_data)
    if not tg_user:
        return None, "invalid_init_data"
    profile = TelegramProfile.objects.filter(telegram_id=str(tg_user["id"])).first()
    if not profile:
        return None, "not_registered"
    return profile, None


def cabinet_index(request: HttpRequest) -> HttpResponse:
    resp = render(request, "cabinet/index.html", {})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


_WEEKDAY_UZ = {
    1: "Yakshanba", 2: "Dushanba", 3: "Seshanba", 4: "Chorshanba",
    5: "Payshanba", 6: "Juma", 7: "Shanba",
}


@require_GET
def api_cabinet_me(request: HttpRequest) -> JsonResponse:
    init_data = _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=403)

    completed_books_count = BooksToRead.objects.filter(
        user=profile, is_audio=False, total_pages__gt=0, current_page__gte=F("total_pages"),
    ).count()
    completed_audio_count = BooksToRead.objects.filter(
        user=profile, is_audio=True, total_pages__gt=0, current_page__gte=F("total_pages"),
    ).count()

    total_pages_read = ConfirmationReport.objects.filter(
        user=profile, is_audio=False
    ).aggregate(total=Sum("pages_read"))["total"] or 0

    audio_reports_qs = ConfirmationReport.objects.filter(user=profile, is_audio=True)
    total_audio_minutes = audio_reports_qs.aggregate(total=Sum("minutes_listened"))["total"] or 0

    avg_pages_per_day = ConfirmationReport.objects.filter(
        user=profile, is_audio=False
    ).aggregate(avg=Avg("pages_read"))["avg"] or 0

    weekday_stats = (
        BookReport.objects.filter(user=profile)
        .annotate(weekday=ExtractWeekDay("created_at"))
        .values("weekday").annotate(count=Count("id")).order_by("-count")
    )
    most_active_day = _WEEKDAY_UZ.get(weekday_stats[0]["weekday"]) if weekday_stats else None

    hour_stats = (
        BookReport.objects.filter(user=profile)
        .annotate(hour=ExtractHour("created_at"))
        .values("hour").annotate(count=Count("id")).order_by("-count")
    )
    active_hour = None
    if hour_stats:
        h = hour_stats[0]["hour"]
        active_hour = f"{h:02d}:00–{(h + 1) % 24:02d}:00"

    # Ranking by total pages read (text books only), same method as the bot.
    pct_ahead = pct_behind = None
    pages_to_overtake = None
    try:
        all_user_pages = list(
            ConfirmationReport.objects.filter(is_audio=False)
            .values("user_id").annotate(total=Sum("pages_read"))
            .values_list("total", flat=True)
        )
        active_user_ids = set(
            ConfirmationReport.objects.filter(is_audio=False).values_list("user_id", flat=True).distinct()
        )
        zero_count = max(TelegramProfile.objects.filter(is_registered=True).count() - len(active_user_ids), 0)
        all_user_pages.extend([0] * zero_count)
        total_users = len(all_user_pages)
        my_pages = total_pages_read or 0
        if total_users > 1:
            behind_me = sum(1 for p in all_user_pages if (p or 0) < my_pages)
            ahead_of_me = sum(1 for p in all_user_pages if (p or 0) > my_pages)
            pct_ahead = round(behind_me * 100 / max(total_users - 1, 1))
            pct_behind = round(ahead_of_me * 100 / max(total_users - 1, 1))
            pages_above = sorted(p for p in all_user_pages if (p or 0) > my_pages)
            if pages_above:
                pages_to_overtake = pages_above[0] - my_pages + 1
    except Exception:
        pass

    is_premium = profile.has_active_premium()
    quiz_correct_count = None
    if is_premium:
        quiz_correct_count = BookQuizAnswer.objects.filter(user=profile, is_correct=True).count()

    return JsonResponse({
        "ok": True,
        "full_name": profile.full_name or "Kitobxon",
        "is_premium": is_premium,
        "balance": int(profile.ball or 0),
        "completed_books": completed_books_count,
        "completed_audio": completed_audio_count,
        "total_pages_read": total_pages_read,
        "total_audio_minutes": total_audio_minutes,
        "avg_pages_per_day": round(avg_pages_per_day),
        "most_active_day": most_active_day,
        "active_hour": active_hour,
        "pct_ahead": pct_ahead,
        "pct_behind": pct_behind,
        "pages_to_overtake": pages_to_overtake,
        "quiz_correct_count": quiz_correct_count,
    })
