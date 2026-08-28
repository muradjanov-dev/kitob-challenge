"""Bilim O'yini — one shared MC-quiz engine for 8 content flavors:

  twofacts   — Ikki haqiqat, bir yolg'on: 3 statements, spot the fake one.
  impostor   — Kim yolg'onchi?: 3 real book/author pairings + 1 fabricated one.
  connection — Yashirin bog'lanish: 4 items share a hidden theme, name it.
  teams      — Jamoa Jangi: players are auto-split into two balanced teams as
               they join (alternating A/B); a TEAM's cumulative correct
               answers (not individuals) decide the winning side, which then
               splits a jackpot.
  timeline   — Vaqt Mashinasi: guess which era/century a book or thinker
               belongs to.
  matchbook  — Muallif-Asar Moslashtirish: given an author, pick their real
               book from 4 options.
  reverse    — Teskari Viktorina: the answer is shown first, pick which of 4
               questions it actually matches (Jeopardy-style).
  cover      — Kitob Muqovasi: a real library book cover, blurred, pick the
               right title from 4 options. Unlike the other flavors (static
               authored question banks), its pool is built live from
               GlobalBook.cover uploads and each question carries an
               "image" URL alongside the usual q/options/correct.

All eight share the same live answer/reveal-phase timing as Ko'pchilik/Emoji;
only content prep and (for "teams") scoring differ.
"""

import io
import random
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Sum, Count, Max
from django.utils import timezone

from tgbot.models import QuizGame, QuizAnswer, QuizScore, GameJoker
from tgbot.services.chain_game import _add_ball_reward, charge_entry_fee, REWARD_TIERS, PARTICIPATION
from tgbot.services import game_jokers
from tgbot.services.game_questions import (
    QUIZ_TWOFACTS_QUESTIONS, QUIZ_IMPOSTOR_QUESTIONS, QUIZ_CONNECTION_QUESTIONS,
    QUIZ_TIMELINE_QUESTIONS, QUIZ_MATCHBOOK_QUESTIONS, QUIZ_REVERSE_QUESTIONS,
    SURVIVAL_QUESTIONS,
    ANAGRAM_QUESTIONS, BLITZ_QUESTIONS, CROSSWORD_QUESTIONS, WORDLE_QUESTIONS,
    CIPHER_QUESTIONS, ACRONYM_QUESTIONS, CHARACTER_QUESTIONS, DIALOGUE_QUESTIONS,
    QUIZ_PLOTMAP_QUESTIONS, QUIZ_SEQUENCE_QUESTIONS, QUIZ_ODDONE_QUESTIONS,
    QUIZ_ENDING_QUESTIONS, QUIZ_PIXEL_QUESTIONS, QUIZ_AIART_QUESTIONS,
    QUIZ_SCENES_QUESTIONS, QUIZ_AUDIOQUOTE_QUESTIONS, QUIZ_MOSAIC_QUESTIONS,
    QUIZ_HIDDENDETAIL_QUESTIONS, QUIZ_DUEL_QUESTIONS, QUIZ_BUZZER_QUESTIONS,
    QUIZ_BRACKET_QUESTIONS, QUIZ_AUCTION_QUESTIONS, QUIZ_REGIONS_QUESTIONS,
    QUIZ_KING_QUESTIONS, QUIZ_RHYME_QUESTIONS, QUIZ_SCHOLARS_QUESTIONS,
    QUIZ_GENRES_QUESTIONS, QUIZ_NUMBERS_QUESTIONS, QUIZ_WORLDLIT_QUESTIONS,
    QUIZ_MYSTERYBOX_QUESTIONS, QUIZ_MINDTRAP_QUESTIONS, QUIZ_STOIC_QUESTIONS,
    QUIZ_ANTIHERD_QUESTIONS, QUIZ_DILEMMA_QUESTIONS, QUIZ_CAUSEEFFECT_QUESTIONS,
    QUIZ_MASKS_QUESTIONS, QUIZ_SOCRATES_QUESTIONS, QUIZ_MEMENTO_QUESTIONS,
    QUIZ_STRATEGY_QUESTIONS, QUIZ_PARADOX_QUESTIONS,
    QUIZ_SIMURGH_QUESTIONS, QUIZ_ISHQ_QUESTIONS, QUIZ_NAFS_QUESTIONS,
    QUIZ_QALB_QUESTIONS, QUIZ_NAQSHBAND_QUESTIONS, QUIZ_YASSAVIY_QUESTIONS,
    QUIZ_MASNAVIY_QUESTIONS, QUIZ_GAZZOLIY_QUESTIONS, QUIZ_FANO_QUESTIONS,
    QUIZ_MARIFAT_QUESTIONS,
    # 10 New Interactive Games
    WORDLOCK_QUESTIONS, SPEEDTYPE_QUESTIONS, TILEPUZZLE_QUESTIONS,
    ASSOCIATION_QUESTIONS, HANGMAN_QUESTIONS, BOOKMEMORY_QUESTIONS,
    SPELLCHECK_QUESTIONS, LABYRINTH_QUESTIONS, BOOKBIDDING_QUESTIONS,
    CHARACTERCLASH_QUESTIONS,
    # 5 New Novelty & Deduction Interactive Games
    RIDDLEBOX_QUESTIONS, QUOTECHAIN_QUESTIONS, TIMETRAVELER_QUESTIONS,
    BLUFFMASTER_QUESTIONS, SYMBOLMATCH_QUESTIONS,
)

GAME_TYPE = "quiz"  # GameJoker.game_type — jokerlar qaysi o'yin jadvaliga tegishli
LEAD_SECONDS = 30
ANSWER_SECONDS = 20
REVEAL_SECONDS = 0
POINTS = 10
TEAM_BASE_REWARD = 60
TEAM_SIZE_BANDS = [
    (16, 4),
    (30, 3),
    (40, 2),
    (50, 2),
    (60, 1),
    (100, 1),
]
TEAM_RANK_BONUS = {0: 40, 1: 25, 2: 10}
COVER_BLUR_RADIUS = 14

# VIP Premium Arena Rewards & Rules
VIP_TOP_GAMES = [
    "king", "duel", "teams", "survival", "mysterybox", "mindtrap", "stoic", "strategy", "simurgh", "masnaviy",
    "gazzoliy", "wordlock", "speedtype", "association", "tilepuzzle", "labyrinth", "characterclash",
    "riddlebox", "quotechain", "timetraveler", "bluffmaster", "symbolmatch"
]
VIP_REWARD_TIERS = {0: 350, 1: 200, 2: 100}  # Rebalanced Kitobcha rewards
VIP_PREMIUM_HOURS_BONUS = {0: 24, 1: 12, 2: 6}  # 1-o'rin: 1 kun (24 soat), 2-o'rin: 12 soat, 3-o'rin: 6 soat
VIP_PREMIUM_DAYS_BONUS = {0: 1, 1: 0, 2: 0}  # legacy backwards compatibility
VIP_PARTICIPATION = 30


def _dynamic_base(team_size, is_vip=False):
    base = 150 if is_vip else TEAM_BASE_REWARD
    prev = 1
    for upper, step in TEAM_SIZE_BANDS:
        if team_size <= upper:
            return base + step * (team_size - prev)
        base += step * (upper - prev)
        prev = upper
    return base

TITLES = {
    "twofacts": "Ikki haqiqat, bir yolg'on",
    "impostor": "Kim yolg'onchi?",
    "connection": "Yashirin bog'lanish",
    "teams": "Jamoa Jangi",
    "timeline": "Vaqt Mashinasi",
    "matchbook": "Muallif-Asar Moslashtirish",
    "reverse": "Teskari Viktorina",
    "cover": "Kitob Muqovasi",
    # 30 New Games
    "anagram": "🔠 Anagramma Kitob",
    "blitz": "⚡️ Blitz 60",
    "crossword": "🧩 Mini Krossvord",
    "wordle": "🔤 Harfma-Harf",
    "cipher": "🔐 Sherlok Kodi",
    "acronym": "🎯 Bosh Harflar",
    "character": "👤 Qahramonni Top",
    "dialogue": "🗣 Kimning gapi?",
    "plotmap": "🗺 Syujet Xaritasi",
    "sequence": "⏳ Ketma-ketlik",
    "oddone": "🔍 Ortiqchasini Top",
    "ending": "✍️ Asar Yakuni",
    "pixel": "🖼 Piksel Muqova",
    "aiart": "🎨 AI Rasmlar",
    "scenes": "🎭 Sahna Ko'rinishi",
    "audioquote": "🎧 Ovozli Iqtibos",
    "mosaic": "🧩 Kitob Mozaikasi",
    "hiddendetail": "🔎 Yashirin Detal",
    "duel": "🤺 1v1 Jonli Duel",
    "buzzer": "🔔 Tezkor Qo'ng'iroq",
    "bracket": "🏆 Haftalik Turnir",
    "auction": "💰 Kitob Auksioni",
    "regions": "👥 Viloyatlar Jangi",
    "king": "👑 Qirol Taxti",
    "rhyme": "📜 Bahri-Bayt",
    "scholars": "🕌 Sharq Allomalari",
    "genres": "📚 Janrlar Ustasi",
    "numbers": "🔢 Adabiy Raqamlar",
    "worldlit": "🌍 Jahon Adabiyoti",
    "mysterybox": "🎁 Sirli Sandiq",
    # 10 Mind, Logic & Conscious Living Games
    "mindtrap": "🧠 Fikr Tuzog'i",
    "stoic": "🧘‍♂️ Ongli Hayot",
    "antiherd": "🐑 Podadan Ajral",
    "dilemma": "⚖️ Axloqiy Dilemma",
    "causeeffect": "🔮 Sabab va Oqibat",
    "masks": "🎭 Niqoblar Foshi",
    "socrates": "🏛 Sokrat Suhbatlari",
    "memento": "⌛️ Vaqt Paradoksi",
    "strategy": "♟ Strategik Tafakkur",
    "paradox": "💡 Paradokslar Olami",
    # 10 Sufism, Nafs Purification & Divine Love Games
    "simurgh": "🕊 Simurg' Parvozi",
    "ishq": "🕯 Parvona va Sham",
    "nafs": "🛡 Nafs Tarbiyasi",
    "qalb": "🪞 Qalb Sayqali",
    "naqshband": "🌾 Xalvat dar Anjuman",
    "yassaviy": "📜 Hikmatlar Daryosi",
    "masnaviy": "🪈 Nay Nidosi",
    "gazzoliy": "🗝 Kimyoi Saodat",
    "fano": "🌊 Fanofilloh",
    "marifat": "☀️ Haqiqat Quyoshi",
    # 10 New Non-Test Interactive Games
    "wordlock": "🗝 So'z Qulfi",
    "speedtype": "⚡️ Tezkor Terish",
    "tilepuzzle": "🧩 Adabiy Mozaika",
    "association": "🔗 So'z Assotsiatsiyasi",
    "hangman": "🪢 Dorboz / Harf Qidiruv",
    "bookmemory": "🃏 Kitob Xotirasi",
    "spellcheck": "✍️ Imlo Saralovchi",
    "labyrinth": "🧭 Adabiy Labirint",
    "bookbidding": "💰 Jonli Auksion Jangi",
    "characterclash": "🤺 Qahramonlar To'qnashuvi",
    # 5 New Novelty & Deduction Interactive Games
    "riddlebox": "🧩 Adabiy Jumboq",
    "quotechain": "🔗 Iqtiboslar Halqasi",
    "timetraveler": "⏳ Tarixiy Sayohatchi",
    "bluffmaster": "🎭 Haqiqatmi yoki Uydirma?",
    "symbolmatch": "🗝 Adabiy Ramzlar",
}

ENTRY_FEES = {k: 0 for k in TITLES}  # barcha o'yinlar bepul (2026-08-19)
NUM_QUESTIONS = {k: (10 if k == "cover" else 11) for k in TITLES}


def _raw_pool(flavor):
    _MAP = {
        "twofacts": QUIZ_TWOFACTS_QUESTIONS,
        "connection": QUIZ_CONNECTION_QUESTIONS,
        "teams": SURVIVAL_QUESTIONS,
        "impostor": QUIZ_IMPOSTOR_QUESTIONS,
        "timeline": QUIZ_TIMELINE_QUESTIONS,
        "matchbook": QUIZ_MATCHBOOK_QUESTIONS,
        "reverse": QUIZ_REVERSE_QUESTIONS,
        "cover": None,
        "anagram": ANAGRAM_QUESTIONS,
        "blitz": BLITZ_QUESTIONS,
        "crossword": CROSSWORD_QUESTIONS,
        "wordle": WORDLE_QUESTIONS,
        "cipher": CIPHER_QUESTIONS,
        "acronym": ACRONYM_QUESTIONS,
        "character": CHARACTER_QUESTIONS,
        "dialogue": DIALOGUE_QUESTIONS,
        "plotmap": QUIZ_PLOTMAP_QUESTIONS,
        "sequence": QUIZ_SEQUENCE_QUESTIONS,
        "oddone": QUIZ_ODDONE_QUESTIONS,
        "ending": QUIZ_ENDING_QUESTIONS,
        "pixel": QUIZ_PIXEL_QUESTIONS,
        "aiart": QUIZ_AIART_QUESTIONS,
        "scenes": QUIZ_SCENES_QUESTIONS,
        "audioquote": QUIZ_AUDIOQUOTE_QUESTIONS,
        "mosaic": QUIZ_MOSAIC_QUESTIONS,
        "hiddendetail": QUIZ_HIDDENDETAIL_QUESTIONS,
        "duel": QUIZ_DUEL_QUESTIONS,
        "buzzer": QUIZ_BUZZER_QUESTIONS,
        "bracket": QUIZ_BRACKET_QUESTIONS,
        "auction": QUIZ_AUCTION_QUESTIONS,
        "regions": QUIZ_REGIONS_QUESTIONS,
        "king": QUIZ_KING_QUESTIONS,
        "rhyme": QUIZ_RHYME_QUESTIONS,
        "scholars": QUIZ_SCHOLARS_QUESTIONS,
        "genres": QUIZ_GENRES_QUESTIONS,
        "numbers": QUIZ_NUMBERS_QUESTIONS,
        "worldlit": QUIZ_WORLDLIT_QUESTIONS,
        "mysterybox": QUIZ_MYSTERYBOX_QUESTIONS,
        # 10 Mind, Logic & Conscious Living Games
        "mindtrap": QUIZ_MINDTRAP_QUESTIONS,
        "stoic": QUIZ_STOIC_QUESTIONS,
        "antiherd": QUIZ_ANTIHERD_QUESTIONS,
        "dilemma": QUIZ_DILEMMA_QUESTIONS,
        "causeeffect": QUIZ_CAUSEEFFECT_QUESTIONS,
        "masks": QUIZ_MASKS_QUESTIONS,
        "socrates": QUIZ_SOCRATES_QUESTIONS,
        "memento": QUIZ_MEMENTO_QUESTIONS,
        "strategy": QUIZ_STRATEGY_QUESTIONS,
        "paradox": QUIZ_PARADOX_QUESTIONS,
        # 10 Sufism, Nafs Purification & Divine Love Games
        "simurgh": QUIZ_SIMURGH_QUESTIONS,
        "ishq": QUIZ_ISHQ_QUESTIONS,
        "nafs": QUIZ_NAFS_QUESTIONS,
        "qalb": QUIZ_QALB_QUESTIONS,
        "naqshband": QUIZ_NAQSHBAND_QUESTIONS,
        "yassaviy": QUIZ_YASSAVIY_QUESTIONS,
        "masnaviy": QUIZ_MASNAVIY_QUESTIONS,
        "gazzoliy": QUIZ_GAZZOLIY_QUESTIONS,
        "fano": QUIZ_FANO_QUESTIONS,
        "marifat": QUIZ_MARIFAT_QUESTIONS,
        # 10 New Non-Test Interactive Games
        "wordlock": WORDLOCK_QUESTIONS,
        "speedtype": SPEEDTYPE_QUESTIONS,
        "tilepuzzle": TILEPUZZLE_QUESTIONS,
        "association": ASSOCIATION_QUESTIONS,
        "hangman": HANGMAN_QUESTIONS,
        "bookmemory": BOOKMEMORY_QUESTIONS,
        "spellcheck": SPELLCHECK_QUESTIONS,
        "labyrinth": LABYRINTH_QUESTIONS,
        "bookbidding": BOOKBIDDING_QUESTIONS,
        "characterclash": CHARACTERCLASH_QUESTIONS,
        # 5 New Novelty & Deduction Interactive Games
        "riddlebox": RIDDLEBOX_QUESTIONS,
        "quotechain": QUOTECHAIN_QUESTIONS,
        "timetraveler": TIMETRAVELER_QUESTIONS,
        "bluffmaster": BLUFFMASTER_QUESTIONS,
        "symbolmatch": SYMBOLMATCH_QUESTIONS,
    }
    if flavor == "cover":
        return _cover_raw_pool()
    if flavor in _MAP:
        return _MAP[flavor]
    raise ValueError(f"unknown flavor {flavor}")


def _cover_raw_pool():
    from tgbot.models import GlobalBook
    books = GlobalBook.objects.exclude(cover="").exclude(cover__isnull=True)
    return [{"book_id": b.id, "title": b.title, "book": b} for b in books]


def _blurred_cover_url(book) -> str:
    import time as _time
    from PIL import Image, ImageFilter
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from django.conf import settings as _settings

    with book.cover.open("rb") as f:
        img = Image.open(f)
        img = img.convert("RGB")
        img = img.filter(ImageFilter.GaussianBlur(radius=COVER_BLUR_RADIUS))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()

    path = f"game/cover_blur/book_{book.id}_{int(_time.time() * 1000)}.jpg"
    saved_path = default_storage.save(path, ContentFile(data))
    return f"{_settings.WEB_DOMAIN}{default_storage.url(saved_path)}"


def _identity(flavor, item):
    if flavor == "impostor":
        return item.get("fake") or item.get("q", "")
    if flavor in ("connection", "association"):
        return str(item.get("items")) if "items" in item else item.get("q", "")
    if flavor == "cover":
        return item.get("title", "")
    if flavor in ("anagram", "wordlock", "hangman"):
        return item.get("word") or item.get("anagram", "")
    if flavor == "wordle":
        return item.get("word", "")
    if flavor == "cipher":
        return item.get("code", "")
    if flavor == "acronym":
        return item.get("acronym", "")
    if flavor == "character":
        return item.get("desc", "")
    if flavor in ("dialogue", "speedtype"):
        return item.get("quote", "")
    if flavor == "crossword":
        return item.get("clue", "")
    return item.get("q", "")


def _prep_one(flavor, item):
    def _do_prep():
        if flavor == "impostor" and "fake" in item:
            options = list(item["real"]) + [item["fake"]]
            fake_text = item["fake"]
            random.shuffle(options)
            return {"q": "Qaysi biri SOXTA (haqiqiy emas)?", "options": options,
                    "correct": options.index(fake_text)}
        if flavor == "cover":
            return _prep_cover_question(item)
        if flavor == "anagram":
            options = [item["answer"]] + list(item["distractors"])
            ans = item["answer"]
            random.shuffle(options)
            return {
                "q": f"🔠 Anagramma: <b>{item['anagram']}</b>\n(Maslahat: {item.get('hint', '')})",
                "options": options,
                "correct": options.index(ans),
            }
        if flavor == "wordlock":
            options = [item["word"]] + list(item["distractors"])
            ans = item["word"]
            random.shuffle(options)
            return {
                "q": f"🗝 So'z Qulfi: <b>{item['word']}</b>\n(Maslahat: {item.get('hint', '')})",
                "options": options,
                "correct": options.index(ans),
            }
        if flavor == "hangman":
            options = [item["word"]] + list(item["distractors"])
            ans = item["word"]
            random.shuffle(options)
            return {
                "q": f"🪢 Dorboz / Harf Qidiruv:\n(Maslahat: <b>{item.get('hint', '')}</b>)",
                "options": options,
                "correct": options.index(ans),
            }
        if flavor == "speedtype":
            options = [item["speaker"]] + list(item["distractors"])
            ans = item["speaker"]
            random.shuffle(options)
            return {
                "q": f"⚡️ Tezkor Iqtibos:\n«<b>{item['quote']}</b>»\n({item.get('context', '')})",
                "options": options,
                "correct": options.index(ans),
            }
        if flavor == "association":
            options = list(item["options"])
            ci = item["correct"]
            correct_text = options[ci]
            random.shuffle(options)
            items_str = " · ".join(item.get("items", []))
            return {
                "q": f"🔗 Bog'lovchi kalit so'zlar:\n<b>[{items_str}]</b>\n{item.get('q', '')}",
                "options": options,
                "correct": options.index(correct_text),
                "items": item.get("items", []),
            }
        if flavor == "crossword":
            options = [item["answer"]] + list(item["distractors"])
            ans = item["answer"]
            random.shuffle(options)
            return {
                "q": f"🧩 Krossvord katagi:\n<b>{item['clue']}</b>",
                "options": options,
                "correct": options.index(ans),
            }
        if flavor == "wordle":
            options = [item["word"]] + list(item["distractors"])
            ans = item["word"]
            random.shuffle(options)
            return {
                "q": f"🔤 Harfma-harf toping: <b>{item['hint']}</b>",
                "options": options,
                "correct": options.index(ans),
            }
        if flavor == "cipher":
            options = [item["author"]] + list(item["distractors"])
            ans = item["author"]
            random.shuffle(options)
            return {
                "q": f"🔐 Sherlok Kodi: <b>{item['code']}</b>\n({item['decoded']})\nMuallifi / egasi kim?",
                "options": options,
                "correct": options.index(ans),
            }
        if flavor == "acronym":
            options = [item["full"]] + list(item["distractors"])
            ans = item["full"]
            random.shuffle(options)
            return {
                "q": f"🎯 Bosh harflar: <b>{item['acronym']}</b> ({item['author']})\nQaysi asar?",
                "options": options,
                "correct": options.index(ans),
            }
        if flavor == "character":
            options = [item["character"]] + list(item["distractors"])
            ans = item["character"]
            random.shuffle(options)
            return {
                "q": f"👤 Qahramonni toping:\n«{item['desc']}»",
                "options": options,
                "correct": options.index(ans),
            }
        if flavor == "dialogue":
            options = [item["speaker"]] + list(item["distractors"])
            ans = item["speaker"]
            random.shuffle(options)
            return {
                "q": f"🗣 Kimning gapi?\n<b>{item['quote']}</b>\n({item.get('context', '')})",
                "options": options,
                "correct": options.index(ans),
            }
        # Standard format {"q", "options", "correct"}
        if "correct" in item and isinstance(item["correct"], str):
            correct_text = item["correct"]
            options = [correct_text] + list(item.get("distractors", []))
        else:
            opts = list(item["options"])
            correct_text = opts[item["correct"]]
            options = opts

        random.shuffle(options)
        out = {"q": item["q"], "options": options, "correct": options.index(correct_text)}
        if "items" in item:
            out["items"] = item["items"]
        return out

    result = _do_prep()
    result["key"] = _identity(flavor, item)
    return result


def _prep_cover_question(item, pool_titles=None):
    """Build one Kitob Muqovasi question: blur `item`'s cover, pick 3 decoy
    titles from the rest of the library, shuffle into options."""
    from tgbot.models import GlobalBook, normalize_uzbek_text

    book = item["book"]
    if pool_titles is None:
        pool_titles = list(GlobalBook.objects.exclude(title__exact="").values_list("title", flat=True))
    correct_norm = normalize_uzbek_text(book.title)
    decoy_pool = [t for t in pool_titles if normalize_uzbek_text(t) != correct_norm]
    decoys = random.sample(decoy_pool, min(3, len(decoy_pool)))
    options = decoys + [book.title]
    random.shuffle(options)
    return {
        "q": "Bu xira muqova qaysi kitobga tegishli?",
        "options": options,
        "correct": options.index(book.title),
        "image": _blurred_cover_url(book),
    }


from tgbot.services.question_picker import pick_least_recently_used


def _ensure_quiz_schema():
    """Ensure is_vip column exists in quiz_games table."""
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE quiz_games ADD COLUMN IF NOT EXISTS is_vip boolean DEFAULT false;")
    except Exception:
        pass


def create_scheduled_quiz(flavor: str, lead_seconds: int = LEAD_SECONDS, is_vip: bool = False) -> QuizGame:
    _ensure_quiz_schema()
    pool = _raw_pool(flavor)
    num_questions = min(NUM_QUESTIONS[flavor], len(pool))
    recent_games = QuizGame.objects.filter(flavor=flavor).order_by("-starts_at")[:100]

    def _extract_game_keys(game):
        keys = []
        for q in (game.questions or []):
            if "key" in q:
                keys.append(q["key"])
                continue
            # Legacy fallback for old games without "key"
            if flavor == "impostor" or flavor == "cover":
                opts = q.get("options") or []
                c = q.get("correct", 0)
                if opts and 0 <= c < len(opts):
                    keys.append(opts[c])
            elif flavor == "connection":
                keys.append(str(q.get("items")))
            else:
                keys.append(q.get("q"))
        return keys

    raw = pick_least_recently_used(
        pool=pool,
        get_key_fn=lambda it: _identity(flavor, it),
        recent_games=recent_games,
        get_game_keys_fn=_extract_game_keys,
        count=num_questions,
    )
    qs = [_prep_one(flavor, it) for it in raw]

    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    total = len(qs) * (ANSWER_SECONDS + REVEAL_SECONDS)
    title = f"⭐️ {TITLES[flavor]} (VIP Premium)" if is_vip else TITLES[flavor]
    return QuizGame.objects.create(
        flavor=flavor, title=title,
        status=QuizGame.STATUS_SCHEDULED,
        starts_at=starts, ends_at=starts + timedelta(seconds=total),
        questions=qs, answer_seconds=ANSWER_SECONDS, reveal_seconds=REVEAL_SECONDS,
        is_vip=is_vip,
    )


def latest_game(flavor):
    return QuizGame.objects.filter(flavor=flavor).order_by("-starts_at").first()


def get_or_activate_live_game(flavor):
    now = timezone.now()
    g = QuizGame.objects.filter(flavor=flavor, status=QuizGame.STATUS_LIVE).order_by("-starts_at").first()
    if g:
        return g
    pending = (
        QuizGame.objects.filter(flavor=flavor, status=QuizGame.STATUS_SCHEDULED, starts_at__lte=now)
        .order_by("starts_at").first()
    )
    if not pending:
        return None
    with transaction.atomic():
        g = QuizGame.objects.select_for_update().get(id=pending.id)
        if g.status == QuizGame.STATUS_SCHEDULED:
            g.status = QuizGame.STATUS_LIVE
            g.save(update_fields=["status", "updated_at"])
    return g


def _phase(game, now):
    span = game.answer_seconds + game.reveal_seconds
    nq = len(game.questions or [])
    total = span * nq
    elapsed = (now - game.starts_at).total_seconds()
    if elapsed < 0:
        return "scheduled", -1, "lobby", int(-elapsed)
    if elapsed >= total:
        return "finished", nq, "done", 0
    qi = int(elapsed // span)
    within = elapsed - qi * span
    if within < game.answer_seconds:
        return "live", qi, "answer", int(game.answer_seconds - within) + 1
    return "live", qi, "reveal", int(span - within) + 1


def _assign_team(game) -> str:
    """Caller must hold the row lock on `game`. Alternates A/B so team sizes
    never differ by more than one, regardless of join order."""
    a, b = list(game.team_a or []), list(game.team_b or [])
    return "a" if len(a) <= len(b) else "b"


def submit_answer(game_id: int, profile, choice: int) -> dict:
    g = QuizGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    if g.is_vip and not (profile and profile.has_active_premium()):
        return {
            "ok": False,
            "error": "premium_required",
            "message": "⭐️ Ushbu arena faqat VIP Premium a'zolari uchun! Qatnashish uchun Premium obunani faollashtiring.",
        }
    now = timezone.now()
    status, qi, phase, _ = _phase(g, now)
    if status != "live" or phase != "answer" or qi < 0 or qi >= len(g.questions or []):
        return {"ok": False, "error": "not_answering"}

    is_first = not QuizAnswer.objects.filter(game_id=g.id, user=profile).exists()
    if is_first and not charge_entry_fee(profile, amount=ENTRY_FEES[g.flavor]):
        return {"ok": False, "error": "insufficient_balance", "need": ENTRY_FEES[g.flavor]}

    team = ""
    if g.flavor == "teams" and is_first:
        with transaction.atomic():
            gl = QuizGame.objects.select_for_update().get(id=g.id)
            team = _assign_team(gl)
            if team == "a":
                gl.team_a = list(gl.team_a or []) + [profile.id]
            else:
                gl.team_b = list(gl.team_b or []) + [profile.id]
            gl.save(update_fields=["team_a", "team_b", "updated_at"])

    q = g.questions[qi]
    correct = (choice == q.get("correct"))

    span = g.answer_seconds + g.reveal_seconds
    elapsed = (now - g.starts_at).total_seconds()
    within = max(0.01, elapsed - qi * span)
    time_taken = round(within, 3)

    hit, created = QuizAnswer.objects.get_or_create(
        game_id=g.id, user=profile, q_index=qi,
        defaults={"choice": choice, "is_correct": correct, "time_taken": time_taken},
    )
    if not created:
        return {"ok": False, "error": "already_answered",
                "correct": hit.is_correct, "correct_index": q.get("correct")}

    # ❤️ Qalqon: sotib olingan, hali sarflanmagan qalqon bo'lsa, bitta xato
    # javob kechiriladi va ochko baribir beriladi. Sarflangani javob qatoridagi
    # `shielded` bayrog'i bilan qayd etiladi — shuning uchun alohida hisoblagich
    # kerak emas va bir qalqon ikki marta ishlatilib qolmaydi.
    shielded = False
    if not correct:
        shielded = _consume_shield(g, profile)
        if shielded:
            hit.shielded = True
            hit.save(update_fields=["shielded", "updated_at"])

    score, score_created = QuizScore.objects.get_or_create(game=g, user=profile)
    fields = ["points", "total_time", "updated_at"]
    if team and not score.team:
        score.team = team
        fields.append("team")
    score.total_time = round((score.total_time or 0.0) + time_taken, 3)
    if correct or shielded:
        score.points = (score.points or 0) + POINTS
        if g.flavor == "teams" and score.team:
            field = "team_a_points" if score.team == "a" else "team_b_points"
            QuizGame.objects.filter(id=g.id).update(**{field: F(field) + POINTS})
    score.save(update_fields=fields)

    return {"ok": True, "correct": correct, "shielded": shielded,
            "correct_index": q.get("correct"), "team": score.team}


def _shields_available(game, profile, bought: int | None = None) -> int:
    """Sotib olingan qalqonlardan nechtasi hali sarflanmaganini qaytaradi.

    Sarflangani alohida hisoblagichda emas, `QuizAnswer.shielded` bayroqlarida
    turadi — javob qatori bilan bitta tranzaksiyada yozilgani uchun qayta
    yuborilgan so'rov bitta qalqonni ikki marta sarflay olmaydi.
    """
    if bought is None:
        bought = game_jokers.shield_count(profile, GAME_TYPE, game.id)
    if not bought:
        return 0
    spent = QuizAnswer.objects.filter(game=game, user=profile, shielded=True).count()
    return max(0, bought - spent)


def _consume_shield(game, profile) -> bool:
    return _shields_available(game, profile) > 0


def use_joker(game_id: int, profile, kind: str) -> dict:
    """💡/❤️/🎯 jokerini sotib olish va qo'llash.

    Har uchala joker faqat javob fazasida ishlaydi. Pul yechilishidan oldin
    o'yin holati to'liq tekshiriladi, snayperda esa javob yuborilmay qolsa
    Kitobcha qaytariladi — hech qanday holatda pul "yo'qolib" ketmaydi.
    """
    if kind not in game_jokers.KINDS:
        return {"ok": False, "error": "bad_joker"}
    g = QuizGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    if g.is_vip and not (profile and profile.has_active_premium()):
        return {"ok": False, "error": "premium_required"}

    status, qi, phase, _ = _phase(g, timezone.now())
    if status != "live" or phase != "answer" or qi < 0 or qi >= len(g.questions or []):
        return {"ok": False, "error": "not_answering"}

    q = g.questions[qi]
    price = game_jokers.PRICES[kind]
    balance = int(profile.ball or 0)
    answered = QuizAnswer.objects.filter(game_id=g.id, user=profile, q_index=qi).exists()

    # 50/50 va snayper joriy savolga tegishli — javob berilgandan keyin ular
    # foydasiz, shuning uchun pul yechilmaydi.
    if kind in (game_jokers.FIFTY, game_jokers.SNIPER) and answered:
        return {"ok": False, "error": "already_answered", "balance": balance}

    # 50/50 va snayper savolning to'g'ri javob indeksiga tayanadi. Agar u
    # buzuq bo'lsa (int emas yoki diapazondan tashqarida), 50/50 to'g'ri
    # javobni yashirib qo'yishi, snayper esa saqlab bo'lmaydigan javob
    # yozishga urinishi mumkin edi — shuning uchun pul yechilmasdan to'xtaymiz.
    if kind in (game_jokers.FIFTY, game_jokers.SNIPER):
        ci = q.get("correct")
        if not isinstance(ci, int) or not (0 <= ci < len(q.get("options") or [])):
            return {"ok": False, "error": "joker_unavailable", "balance": balance}

    payload = None
    if kind == game_jokers.FIFTY:
        hidden = game_jokers.pick_hidden(q.get("options") or [], q.get("correct", -1))
        if not hidden:
            return {"ok": False, "error": "joker_unavailable", "balance": balance}
        payload = {"hidden": hidden}
    elif kind == game_jokers.SHIELD:
        if game_jokers.shield_count(profile, GAME_TYPE, g.id) >= game_jokers.MAX_SHIELDS_PER_GAME:
            return {"ok": False, "error": "joker_limit", "balance": balance}
        # Bir savolda bitta — takroriy so'rov (tarmoq uzilishi, ikki marta
        # bosish) ikkinchi qalqonni sotib olib yubormasligi uchun. Ikkinchisini
        # keyingi savolda olish mumkin.
        if game_jokers.find(profile, GAME_TYPE, g.id, qi, game_jokers.SHIELD):
            return {"ok": False, "error": "joker_round_limit", "balance": balance}

    joker, created, err = game_jokers.buy(
        profile, game_type=GAME_TYPE, game_id=g.id, q_index=qi, kind=kind,
        flavor=g.flavor, payload=payload,
    )
    if err:
        return {"ok": False, "error": err, "need": price, "balance": balance}

    out = {"ok": True, "kind": kind, "charged": price if created else 0,
           "balance": int(profile.ball or 0)}

    if kind == game_jokers.FIFTY:
        out["hidden"] = list((joker.payload or {}).get("hidden") or [])
    elif kind == game_jokers.SHIELD:
        out["shields"] = _shields_available(g, profile)
        out["shields_bought"] = game_jokers.shield_count(profile, GAME_TYPE, g.id)
    elif kind == game_jokers.SNIPER:
        res = submit_answer(g.id, profile, q.get("correct"))
        if not res.get("ok") and res.get("error") != "already_answered":
            # Javob o'tmadi — jokerni bekor qilib, Kitobchani qaytaramiz.
            if created:
                GameJoker.objects.filter(id=joker.id).delete()
                game_jokers.refund(profile, price, f"joker_{kind}_refund")
            return {"ok": False, "error": res.get("error") or "failed",
                    "balance": int(profile.ball or 0)}
        out["choice"] = q.get("correct")
        out["correct_index"] = q.get("correct")
        out["correct"] = True
        out["balance"] = int(profile.ball or 0)
    return out


def ranked_scores(game, include_zero=False):
    """Every QuizScore for `game`, in official finishing order.

    Ordering is points desc, then **effective time** asc, then join order.

    Effective time = time actually spent answering + the full answer window
    charged for every question left unanswered. Raw `total_time` only counted
    questions a player attempted, so two players on identical points were
    separated in favour of whoever answered *fewer* questions: guessing and
    getting one wrong added seconds, staying silent added none. That punished
    taking part, which is backwards — with this, skipping is never cheaper
    than answering, and the time shown in the results post is measured over
    the same number of questions for everybody.

    Each row is annotated in place with `answered_count` and `effective_time`
    so callers can display them without a second query.
    """
    nq = len(game.questions or [])
    max_t = float(game.answer_seconds or ANSWER_SECONDS)
    answered = {
        row["user_id"]: row["c"]
        for row in QuizAnswer.objects.filter(game=game).values("user_id").annotate(c=Count("id"))
    }
    qs = QuizScore.objects.filter(game=game).select_related("user")
    if not include_zero:
        qs = qs.filter(points__gt=0)
    rows = list(qs)
    for s in rows:
        s.answered_count = int(answered.get(s.user_id, 0))
        s.effective_time = round(
            (s.total_time or 0.0) + max(0, nq - s.answered_count) * max_t, 3
        )
    rows.sort(key=lambda s: (-(s.points or 0), s.effective_time, s.created_at))
    return rows


def finalize(game_id: int) -> dict | None:
    with transaction.atomic():
        g = QuizGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        if g.status != QuizGame.STATUS_FINISHED:
            g.status = QuizGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    if g.flavor == "teams":
        return _finalize_teams(g)
    return _finalize_individual(g)


def get_vip_premium_label(rank: int) -> str:
    hours = VIP_PREMIUM_HOURS_BONUS.get(rank, 0)
    if hours == 24:
        return "1 kun"
    elif hours > 0:
        return f"{hours} soat"
    return ""


def grant_vip_premium(score, rank: int) -> dict:
    """Hand the VIP arena's top-3 Premium bonus (1st: 1 kun/24h, 2nd: 12 soat, 3rd: 6 soat) to one winner, exactly once.

    `QuizScore.premium_days` is both the receipt and the idempotency guard, so
    a re-finalize or a late settle run can never double-grant. Failures are
    swallowed deliberately.
    """
    hours = VIP_PREMIUM_HOURS_BONUS.get(rank, 0)
    label = get_vip_premium_label(rank)
    if not hours or score.premium_days:
        return {
            "hours": hours if score.premium_days else 0,
            "days": 1 if (score.premium_days and hours >= 24) else 0,
            "text": label if score.premium_days else "",
        }
    try:
        from tgbot.services.premium import grant_premium
        grant_premium(score.user, hours=hours)
    except Exception as e:
        print(f"grant_vip_premium: score={score.id} rank={rank}: {e}")
        return {"hours": 0, "days": 0, "text": ""}
    score.premium_days = 1 if hours >= 24 else hours
    score.save(update_fields=["premium_days", "updated_at"])
    return {"hours": hours, "days": 1 if hours >= 24 else 0, "text": label}


def _finalize_individual(g) -> dict:
    scores = ranked_scores(g)
    winners = []
    tiers = VIP_REWARD_TIERS if g.is_vip else REWARD_TIERS
    participation = VIP_PARTICIPATION if g.is_vip else PARTICIPATION
    for i, s in enumerate(scores):
        reward = tiers[i] if i < 3 else (participation if i < 10 else 10)
        if not s.rewarded:
            applied = _add_ball_reward(s.user, reward)
            s.rewarded = True
            s.reward = applied
            s.save(update_fields=["rewarded", "reward", "updated_at"])
        else:
            applied = s.reward or reward
        prem_info = grant_vip_premium(s, i) if g.is_vip else {"hours": 0, "days": 0, "text": ""}
        prem_text = prem_info.get("text", "")
        prem_days = prem_info.get("days", 0)
        prem_hours = prem_info.get("hours", 0)
        winners.append({
            "rank": i + 1, "user_id": s.user_id, "telegram_id": s.user.telegram_id,
            "name": s.user.full_name or "Kitobxon", "points": s.points, "reward": applied,
            "boosted": applied != reward,
            "correct": s.points // POINTS, "q_total": len(g.questions or []),
            "time": round(s.effective_time, 1), "answered": s.answered_count,
            "premium_days": prem_days,
            "premium_hours": prem_hours,
            "premium_text": prem_text,
        })
    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    return {"winners": winners, "players": len(scores)}


def _finalize_teams(g) -> dict:
    scores = ranked_scores(g, include_zero=True)
    winning_team = "a" if g.team_a_points >= g.team_b_points else "b"
    tie = g.team_a_points == g.team_b_points
    team_sizes = {"a": len(g.team_a or []), "b": len(g.team_b or [])}

    rank_by_score_id = {}
    for team in ("a", "b"):
        if not (tie or team == winning_team):
            continue
        # `scores` is already in official order, so filtering preserves it.
        team_scores = [s for s in scores if s.team == team and s.points > 0]
        for r, s in enumerate(team_scores):
            rank_by_score_id[s.id] = r

    winners = []
    base_calc = _dynamic_base(team_sizes.get(winning_team, 0), is_vip=g.is_vip)
    for s in scores:
        if tie or s.team == winning_team:
            rank = rank_by_score_id.get(s.id)
            bonus = TEAM_RANK_BONUS.get(rank, 0) if rank is not None else 0
            if g.is_vip and rank is not None and rank < 3:
                bonus += 50
            reward = base_calc + bonus
        else:
            reward = VIP_PARTICIPATION if g.is_vip else PARTICIPATION
        if not s.rewarded:
            applied = _add_ball_reward(s.user, reward)
            s.rewarded = True
            s.reward = applied
            s.save(update_fields=["rewarded", "reward", "updated_at"])
        else:
            applied = s.reward or reward
        winners.append({
            "user_id": s.user_id, "telegram_id": s.user.telegram_id,
            "name": s.user.full_name or "Kitobxon", "points": s.points,
            "team": s.team, "reward": applied,
            "correct": s.points // POINTS, "q_total": len(g.questions or []),
            "time": round(s.effective_time, 1), "answered": s.answered_count,
            "premium_days": 0,
        })
    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    return {
        "winners": winners, "players": len(scores),
        "team_a_points": g.team_a_points, "team_b_points": g.team_b_points,
        "winning_team": winning_team if not tie else None, "tie": tie,
    }


def finalize_due_games(flavor=None) -> list:
    now = timezone.now()
    qs = QuizGame.objects.exclude(status=QuizGame.STATUS_FINISHED).filter(ends_at__lt=now)
    if flavor:
        qs = qs.filter(flavor=flavor)
    out = []
    for g in qs:
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


def _leaderboard(game, limit=50):
    """Public standings. Carries each player's correct-answer count and the
    exact time the ranking used, so anyone can check the order for themselves
    instead of taking the points on trust."""
    nq = len(game.questions or [])
    return [{"name": r.user.full_name or "Kitobxon", "points": r.points,
             "team": r.team, "reward": r.reward or 0,
             "correct": r.points // POINTS, "q_total": nq,
             "time": round(r.effective_time, 1), "answered": r.answered_count,
             "premium_days": r.premium_days or 0}
            for r in ranked_scores(game)[:limit]]


def _lifetime(profile, flavor):
    agg = QuizScore.objects.filter(user=profile, game__flavor=flavor).aggregate(
        games=Count("id"), pts=Sum("points"), best=Max("points"))
    return {"games": agg["games"] or 0, "points": int(agg["pts"] or 0), "best": int(agg["best"] or 0)}


def _history(flavor, limit=6):
    out = []
    for g in QuizGame.objects.filter(flavor=flavor, status=QuizGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        top = (QuizScore.objects.filter(game=g, points__gt=0)
               .select_related("user").order_by("-points").first())
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "winner": (top.user.full_name if top else "—") or "—",
            "winner_points": (top.points if top else 0),
            "players": QuizScore.objects.filter(game=g, points__gt=0).count(),
        })
    return out


def state_payload(profile, flavor) -> dict:
    now = timezone.now()
    g = get_or_activate_live_game(flavor) or latest_game(flavor)
    if not g:
        return {"ok": True, "status": "none", "lifetime": _lifetime(profile, flavor),
                "history": _history(flavor), "balance": int(profile.ball or 0),
                "joker_prices": game_jokers.prices_payload()}

    status, qi, phase, secs = _phase(g, now)
    nq = len(g.questions or [])
    finished = status == "finished"
    my = QuizScore.objects.filter(game=g, user=profile).first()
    has_prem = profile.has_active_premium() if profile else False
    payload = {
        "ok": True, "status": status, "phase": phase, "game_id": g.id,
        "flavor": g.flavor, "title": g.title,
        "is_vip": g.is_vip,
        "has_premium": has_prem,
        "vip_locked": bool(g.is_vip and not has_prem),
        "q_index": qi, "q_number": qi + 1, "q_total": nq, "seconds": secs,
        "leaderboard": _leaderboard(g),
        "your_points": (my.points if my else 0),
        "your_team": (my.team if my else ""),
        "your_reward": (my.reward if my else 0),
        "your_premium_days": (my.premium_days if my else 0),
        "lifetime": _lifetime(profile, flavor),
        "history": _history(flavor) if status != "live" else [],
        "balance": int(profile.ball or 0),
        "joker_prices": game_jokers.prices_payload(),
    }
    if finished:
        # Full answer key once the game is over — anyone can re-check every
        # question against what they picked, so the scoring is auditable
        # rather than something players have to take our word for.
        payload["answer_key"] = [
            {"n": i + 1, "q": (q.get("q") or "")[:160],
             "answer": (q.get("options") or [""])[q.get("correct", 0)]
             if 0 <= q.get("correct", -1) < len(q.get("options") or []) else ""}
            for i, q in enumerate(g.questions or [])
        ]
        mine = {a.q_index: a for a in QuizAnswer.objects.filter(game=g, user=profile)}
        for row in payload["answer_key"]:
            a = mine.get(row["n"] - 1)
            # "shield" — javob xato edi, lekin ❤️ Qalqon jokeri ochkoni saqlab
            # qoldi. Reytingdagi to'g'ri javoblar soni ochkodan hisoblangani
            # uchun bu qatorlar ham unda ko'rinadi; kalitda alohida belgi
            # qo'yilishi shuni tushuntirib turadi.
            if a is None:
                row["you"] = "skip"
            elif a.is_correct:
                row["you"] = "ok"
            elif a.shielded:
                row["you"] = "shield"
            else:
                row["you"] = "no"
            row["secs"] = round(a.time_taken, 1) if a else None
    if flavor == "teams":
        payload["team_a_points"] = g.team_a_points
        payload["team_b_points"] = g.team_b_points
        payload["team_a_size"] = len(g.team_a or [])
        payload["team_b_size"] = len(g.team_b or [])
    if status == "live" and 0 <= qi < nq:
        q = g.questions[qi]
        payload["q"] = q["q"]
        payload["options"] = q["options"]
        if "items" in q:
            payload["items"] = q["items"]
        if "image" in q:
            payload["image"] = q["image"]
        ans = QuizAnswer.objects.filter(game=g, user=profile, q_index=qi).first()
        payload["answered"] = bool(ans)
        if ans:
            payload["your_choice"] = ans.choice
            payload["your_correct"] = ans.is_correct
            payload["your_shielded"] = ans.shielded
        if phase == "reveal":
            payload["correct_index"] = q.get("correct")
        jok = game_jokers.summarize(
            game_jokers.game_rows(profile, GAME_TYPE, g.id), qi,
        )
        jok["shields"] = _shields_available(g, profile, bought=jok["shields_bought"])
        payload["jokers"] = jok
    return payload
