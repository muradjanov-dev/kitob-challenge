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
from tgbot.services import chain_game, feud_game, castle_game, emoji_game


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


# ── Ko'pchilik nima dedi? (Feud) ─────────────────────────────────────────────
def feud_index(request: HttpRequest) -> HttpResponse:
    resp = render(request, "game/feud.html", {})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


@csrf_exempt
@require_GET
@_require_authed
def api_feud_state(request: HttpRequest) -> JsonResponse:
    return JsonResponse(feud_game.state_payload(request.tg_profile))


@csrf_exempt
@require_POST
@_require_authed
def api_feud_submit(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    text = (body.get("text") or "").strip()
    if not text:
        return JsonResponse({"ok": False, "error": "empty"})
    g = feud_game.latest_game()
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(feud_game.submit_answer(g.id, request.tg_profile, text))


# ── Bilim Qal'asi (Castle) ───────────────────────────────────────────────────
def castle_index(request: HttpRequest) -> HttpResponse:
    resp = render(request, "game/castle.html", {})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


@csrf_exempt
@require_GET
@_require_authed
def api_castle_state(request: HttpRequest) -> JsonResponse:
    return JsonResponse(castle_game.state_payload(request.tg_profile))


@csrf_exempt
@require_POST
@_require_authed
def api_castle_submit(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    choice = body.get("choice")
    if not isinstance(choice, int):
        return JsonResponse({"ok": False, "error": "bad_choice"}, status=400)
    g = castle_game.latest_game()
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(castle_game.submit_answer(g.id, request.tg_profile, choice))


# ── Emoji Kitob ──────────────────────────────────────────────────────────────
def emoji_index(request: HttpRequest) -> HttpResponse:
    resp = render(request, "game/emoji.html", {})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


@csrf_exempt
@require_GET
@_require_authed
def api_emoji_state(request: HttpRequest) -> JsonResponse:
    return JsonResponse(emoji_game.state_payload(request.tg_profile))


@csrf_exempt
@require_POST
@_require_authed
def api_emoji_submit(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    choice = body.get("choice")
    if not isinstance(choice, int):
        return JsonResponse({"ok": False, "error": "bad_choice"}, status=400)
    g = emoji_game.latest_game()
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(emoji_game.submit_answer(g.id, request.tg_profile, choice))
