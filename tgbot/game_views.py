"""Kitob Zanjiri — Telegram Mini App views.

Reuses the shop's initData verification (`_require_authed`) so every API call is
authenticated as a real TelegramProfile. The page itself renders without a valid
initData; the gate is on the API calls.
"""

import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from tgbot.shop_views import _require_authed
from tgbot.services import chain_game


def chain_index(request: HttpRequest) -> HttpResponse:
    resp = render(request, "game/chain.html", {})
    # Same aggressive no-cache as the shop/landing (Telegram WebView2 caches).
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


@csrf_exempt
@require_GET
@_require_authed
def api_chain_state(request: HttpRequest) -> JsonResponse:
    return JsonResponse(chain_game.state_payload(request.tg_profile))


@csrf_exempt
@require_POST
@_require_authed
def api_chain_submit(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    text = (body.get("text") or "").strip()
    if not text:
        return JsonResponse({"ok": False, "error": "empty"})
    g = chain_game.get_or_activate_live_game()
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(chain_game.submit(g.id, request.tg_profile, text))


@csrf_exempt
@require_POST
@_require_authed
def api_chain_challenge(request: HttpRequest) -> JsonResponse:
    """Vote a chain link as 'not a real book'. At the vote threshold the link is
    invalidated and its point revoked."""
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    idx = body.get("idx")
    if not isinstance(idx, int):
        return JsonResponse({"ok": False, "error": "bad_index"}, status=400)
    g = chain_game.get_or_activate_live_game()
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(chain_game.challenge(g.id, request.tg_profile, idx))
