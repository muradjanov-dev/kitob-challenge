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


# ── Bilim O'yini — shared engine + shared template for all flavors ────────────
_QUIZ_FLAVORS = (
    "twofacts", "impostor", "connection", "teams",
    "timeline", "matchbook", "reverse", "cover",
    # 30 New Games (🧪 Test / Beta)
    "anagram", "blitz", "crossword", "wordle",
    "cipher", "acronym", "character", "dialogue",
    "plotmap", "sequence", "oddone", "ending",
    "pixel", "aiart", "scenes", "audioquote",
    "mosaic", "hiddendetail", "duel", "buzzer",
    "bracket", "auction", "regions", "king",
    "rhyme", "scholars", "genres", "numbers",
    "worldlit", "mysterybox",
    # 10 Mind, Logic & Conscious Living Games (🧠 Ongli Hayot)
    "mindtrap", "stoic", "antiherd", "dilemma",
    "causeeffect", "masks", "socrates", "memento",
    "strategy", "paradox",
    # 10 Sufism, Nafs Purification & Divine Love Games (✨ Tasavvuf & Ishqulloh)
    "simurgh", "ishq", "nafs", "qalb",
    "naqshband", "yassaviy", "masnaviy", "gazzoliy",
    "fano", "marifat",
)


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


# ── Homepage "live games" widget: countdown + what's on right now + last
# slot's turnout. Public (no initData needed) -- pure schedule/status info,
# same data anyone sees posted in the groups. ──────────────────────────────

_GAME_LABELS_URLS = {
    "chain": ("Kitob Zanjiri", "/zanjir/"),
    "feud": ("Ko'pchilik nima dedi?", "/kopchilik/"),
    "castle": ("Bilim Qal'asi", "/qala/"),
    "emoji": ("Emoji Kitob", "/emoji/"),
    "wisdom": ("Hikmatlar", "/hikmat/"),
    "detective": ("Detektiv", "/detektiv/"),
    "survival": ("Omon qolish", "/omon-qolish/"),
    "twofacts": ("Ikki haqiqat, bir yolg'on", "/ikki-haqiqat/"),
    "impostor": ("Kim yolg'onchi?", "/kim-yolgonchi/"),
    "connection": ("Yashirin bog'lanish", "/bog-lanish/"),
    "teams": ("Jamoa Jangi", "/jamoa-jangi/"),
    "timeline": ("Vaqt Mashinasi", "/vaqt-mashinasi/"),
    "matchbook": ("Muallif-Asar Moslashtirish", "/muallif-asar/"),
    "reverse": ("Teskari Viktorina", "/teskari-viktorina/"),
    "cover": ("Kitob Muqovasi", "/kitob-muqovasi/"),
    # 30 New Games (🧪 Test / Beta)
    "anagram": ("🔠 Anagramma Kitob", "/anagram/"),
    "blitz": ("⚡️ Blitz 60", "/blitz/"),
    "crossword": ("🧩 Mini Krossvord", "/crossword/"),
    "wordle": ("🔤 Harfma-Harf", "/wordle/"),
    "cipher": ("🔐 Sherlok Kodi", "/cipher/"),
    "acronym": ("🎯 Bosh Harflar", "/acronym/"),
    "character": ("👤 Qahramonni Top", "/character/"),
    "dialogue": ("🗣 Kimning gapi?", "/dialogue/"),
    "plotmap": ("🗺 Syujet Xaritasi", "/plotmap/"),
    "sequence": ("⏳ Ketma-ketlik", "/sequence/"),
    "oddone": ("🔍 Ortiqchasini Top", "/oddone/"),
    "ending": ("✍️ Asar Yakuni", "/ending/"),
    "pixel": ("🖼 Piksel Muqova", "/pixel/"),
    "aiart": ("🎨 AI Rasmlar", "/aiart/"),
    "scenes": ("🎭 Sahna Ko'rinishi", "/scenes/"),
    "audioquote": ("🎧 Ovozli Iqtibos", "/audioquote/"),
    "mosaic": ("🧩 Kitob Mozaikasi", "/mosaic/"),
    "hiddendetail": ("🔎 Yashirin Detal", "/hiddendetail/"),
    "duel": ("🤺 1v1 Jonli Duel", "/duel/"),
    "buzzer": ("🔔 Tezkor Qo'ng'iroq", "/buzzer/"),
    "bracket": ("🏆 Haftalik Turnir", "/bracket/"),
    "auction": ("💰 Kitob Auksioni", "/auction/"),
    "regions": ("👥 Viloyatlar Jangi", "/regions/"),
    "king": ("👑 Qirol Taxti", "/king/"),
    "rhyme": ("📜 Bahri-Bayt", "/rhyme/"),
    "scholars": ("🕌 Sharq Allomalari", "/scholars/"),
    "genres": ("📚 Janrlar Ustasi", "/genres/"),
    "numbers": ("🔢 Adabiy Raqamlar", "/numbers/"),
    "worldlit": ("🌍 Jahon Adabiyoti", "/worldlit/"),
    "mysterybox": ("🎁 Sirli Sandiq", "/mysterybox/"),
    # 10 Mind, Logic & Conscious Living Games
    "mindtrap": ("🧠 Fikr Tuzog'i", "/mindtrap/"),
    "stoic": ("🧘‍♂️ Ongli Hayot", "/stoic/"),
    "antiherd": ("🐑 Podadan Ajral", "/antiherd/"),
    "dilemma": ("⚖️ Axloqiy Dilemma", "/dilemma/"),
    "causeeffect": ("🔮 Sabab va Oqibat", "/causeeffect/"),
    "masks": ("🎭 Niqoblar Foshi", "/masks/"),
    "socrates": ("🏛 Sokrat Suhbatlari", "/socrates/"),
    "memento": ("⌛️ Vaqt Paradoksi", "/memento/"),
    "strategy": ("♟ Strategik Tafakkur", "/strategy/"),
    "paradox": ("💡 Paradokslar Olami", "/paradox/"),
    # 10 Sufism, Nafs Purification & Divine Love Games
    "simurgh": ("🕊 Simurg' Parvozi", "/simurgh/"),
    "ishq": ("🕯 Parvona va Sham", "/ishq/"),
    "nafs": ("⚔️ Buyuk Jihod", "/nafs/"),
    "qalb": ("🪞 Qalb Sayqali", "/qalb/"),
    "naqshband": ("🌾 Xalvat dar Anjuman", "/naqshband/"),
    "yassaviy": ("📜 Hikmatlar Daryosi", "/yassaviy/"),
    "masnaviy": ("🪈 Nay Nidosi", "/masnaviy/"),
    "gazzoliy": ("🗝 Kimyoi Saodat", "/gazzoliy/"),
    "fano": ("🌊 Fanofilloh", "/fano/"),
    "marifat": ("☀️ Haqiqat Quyoshi", "/marifat/"),
}
_QUIZ_FLAVOR_SET = set(_QUIZ_FLAVORS)


def _game_participant_count(game_type: str, game_id: int) -> int:
    from tgbot.models import (
        ChainScore, FeudScore, CastleHit, EmojiScore,
        WisdomScore, DetectiveScore, SurvivalPlayer, QuizScore,
    )
    model_by_type = {
        "chain": ChainScore, "feud": FeudScore, "emoji": EmojiScore,
        "wisdom": WisdomScore, "detective": DetectiveScore, "survival": SurvivalPlayer,
    }
    if game_type == "castle":
        return CastleHit.objects.filter(game_id=game_id).values("user_id").distinct().count()
    if game_type in _QUIZ_FLAVOR_SET:
        return QuizScore.objects.filter(game_id=game_id).count()
    model = model_by_type.get(game_type)
    return model.objects.filter(game_id=game_id).count() if model else 0


def _next_slot_at():
    """Next occurrence of 10:00 or 22:00 Tashkent time, as an aware datetime."""
    import datetime as _dt
    from django.utils import timezone as _tz

    now = _tz.localtime()
    for hour in (10, 22):
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > now:
            return candidate
    # Both today's slots have passed -- tomorrow's 10:00.
    tomorrow = now.date() + _dt.timedelta(days=1)
    return _tz.make_aware(_dt.datetime.combine(tomorrow, _dt.time(10, 0)))


@require_GET
def api_games_status(request: HttpRequest) -> JsonResponse:
    from tgbot.models import GameSequence

    active = None
    seq = GameSequence.objects.filter(completed=False).order_by("-date", "-slot").first()
    if seq and seq.current_game_type:
        label, url = _GAME_LABELS_URLS.get(seq.current_game_type, (seq.current_game_type, None))
        active = {
            "slot": seq.slot,
            "game_type": seq.current_game_type,
            "label": label,
            "url": url,
            "index": seq.current_index + 1,
            "total": len(seq.game_types),
        }

    last_result = None
    last_seq = GameSequence.objects.filter(completed=True).order_by("-date", "-slot").first()
    if last_seq:
        games = []
        for gt in last_seq.game_types:
            label, url = _GAME_LABELS_URLS.get(gt, (gt, None))
            # current_game_id only reliably points at the *last* game once the
            # sequence is fully completed (it's overwritten as each one starts),
            # so this is only meaningful for the final entry of game_types --
            # earlier ones just get a label with no participant count.
            games.append({"type": gt, "label": label, "url": url})
        last_result = {
            "slot": last_seq.slot,
            "date": last_seq.date.isoformat(),
            "games": games,
            "last_game_participants": (
                _game_participant_count(last_seq.current_game_type, last_seq.current_game_id)
                if last_seq.current_game_type and last_seq.current_game_id else None
            ),
            "last_game_label": games[-1]["label"] if games else None,
        }

    return JsonResponse({
        "ok": True,
        "next_slot_at": _next_slot_at().isoformat(),
        "active": active,
        "last_result": last_result,
    })
