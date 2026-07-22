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
from tgbot.services import (
    chain_game, feud_game, castle_game, emoji_game,
    wisdom_game, detective_game, survival_game, quiz_game,
)


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
def api_chain_vote(request: HttpRequest) -> JsonResponse:
    """Vote the pending candidate 'to'g'ri' (accept) or 'noto'g'ri' (reject)."""
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    accept = bool(body.get("accept"))
    g = chain_game.get_or_activate_live_game()
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(chain_game.vote_pending(g.id, request.tg_profile, accept))


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


# ── Hikmat Xazinasi ──────────────────────────────────────────────────────────
def wisdom_index(request: HttpRequest) -> HttpResponse:
    resp = render(request, "game/wisdom.html", {})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


@csrf_exempt
@require_GET
@_require_authed
def api_wisdom_state(request: HttpRequest) -> JsonResponse:
    return JsonResponse(wisdom_game.state_payload(request.tg_profile))


@csrf_exempt
@require_POST
@_require_authed
def api_wisdom_submit(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    choice = body.get("choice")
    if not isinstance(choice, int):
        return JsonResponse({"ok": False, "error": "bad_choice"}, status=400)
    g = wisdom_game.get_or_activate_live_game()
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(wisdom_game.submit_answer(g.id, request.tg_profile, choice))


# ── Kitob Detektivi ──────────────────────────────────────────────────────────
def detective_index(request: HttpRequest) -> HttpResponse:
    resp = render(request, "game/detective.html", {})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


@csrf_exempt
@require_GET
@_require_authed
def api_detective_state(request: HttpRequest) -> JsonResponse:
    return JsonResponse(detective_game.state_payload(request.tg_profile))


@csrf_exempt
@require_POST
@_require_authed
def api_detective_submit(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    text = (body.get("text") or "").strip()
    if not text:
        return JsonResponse({"ok": False, "error": "empty"})
    g = detective_game.get_or_activate_live_game()
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(detective_game.submit_guess(g.id, request.tg_profile, text))


# ── Omon qolish ──────────────────────────────────────────────────────────────
def survival_index(request: HttpRequest) -> HttpResponse:
    resp = render(request, "game/survival.html", {})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


@csrf_exempt
@require_GET
@_require_authed
def api_survival_state(request: HttpRequest) -> JsonResponse:
    return JsonResponse(survival_game.state_payload(request.tg_profile))


@csrf_exempt
@require_POST
@_require_authed
def api_survival_submit(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    choice = body.get("choice")
    if not isinstance(choice, int):
        return JsonResponse({"ok": False, "error": "bad_choice"}, status=400)
    g = survival_game.latest_game()
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(survival_game.submit_answer(g.id, request.tg_profile, choice))


# ── Bilim O'yini — shared engine + shared template for 4 flavors ────────────
_QUIZ_FLAVORS = ("twofacts", "impostor", "connection", "teams",
                 "timeline", "matchbook", "reverse")


def quiz_index(request: HttpRequest, flavor: str) -> HttpResponse:
    if flavor not in _QUIZ_FLAVORS:
        return HttpResponse("Not found", status=404)
    resp = render(request, "game/quiz.html", {"flavor": flavor})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


@csrf_exempt
@require_GET
@_require_authed
def api_quiz_state(request: HttpRequest, flavor: str) -> JsonResponse:
    if flavor not in _QUIZ_FLAVORS:
        return JsonResponse({"ok": False, "error": "bad_flavor"}, status=404)
    return JsonResponse(quiz_game.state_payload(request.tg_profile, flavor))


@csrf_exempt
@require_POST
@_require_authed
def api_quiz_submit(request: HttpRequest, flavor: str) -> JsonResponse:
    if flavor not in _QUIZ_FLAVORS:
        return JsonResponse({"ok": False, "error": "bad_flavor"}, status=404)
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    choice = body.get("choice")
    if not isinstance(choice, int):
        return JsonResponse({"ok": False, "error": "bad_choice"}, status=400)
    g = quiz_game.get_or_activate_live_game(flavor)
    if not g:
        return JsonResponse({"ok": False, "error": "not_live"})
    return JsonResponse(quiz_game.submit_answer(g.id, request.tg_profile, choice))
