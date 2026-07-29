"""Sayt Statistikasi — lightweight usage analytics for the Mini App pages.

Every page (site/, kutubxona/, shop/, kabinet/, all game/* pages) includes
`_tracking.html`, which fires one pageview beacon on load and one click
beacon per button/link click. Both land here and get stored as `SiteEvent`
rows; the admin "Statistika" dashboard (see admin.py) aggregates them.

Same Telegram WebApp initData auth pattern as shop_views.py / library_views.py
/ cabinet_views.py / report_views.py, but best-effort: an invalid or missing
initData must never block tracking, it just means the event is stored
without a user attached (still counts toward section/button totals).
"""
import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tgbot.models import SiteEvent, TelegramProfile


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


def _resolve_profile_best_effort(init_data: str) -> TelegramProfile | None:
    tg_user = _verify_init_data(init_data)
    if not tg_user:
        return None
    return TelegramProfile.objects.filter(telegram_id=str(tg_user["id"])).first()


@csrf_exempt
@require_POST
def api_track_event(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False}, status=200)

    event_type = body.get("event_type")
    section = (body.get("section") or "").strip()[:32]
    if event_type not in (SiteEvent.TYPE_PAGEVIEW, SiteEvent.TYPE_CLICK) or not section:
        return JsonResponse({"ok": False}, status=200)

    profile = _resolve_profile_best_effort(body.get("initData") or "")

    SiteEvent.objects.create(
        event_type=event_type,
        section=section,
        label=(body.get("label") or "").strip()[:120],
        path=(body.get("path") or "").strip()[:255],
        user=profile,
    )
    return JsonResponse({"ok": True})
