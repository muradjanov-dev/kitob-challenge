"""Kitob Viktorina — build the twice-daily "guess the book" quiz from real user
conclusions, render its copy, and hold the pool of creative promo reminders.

The quiz-building helpers touch the ORM and run from the sync Celery side; the
copy builders + pools are pure and safe to import from the async bot handlers.
"""
import json
import random
import re

from tgbot.models import (
    BookQuizRound, ConfirmationReport, GlobalBook, normalize_uzbek_text,
)


# How many Kitobcha a correct guess is worth.
REWARD_KITOBCHA = 100
# A conclusion needs at least this many real letters/digits to be a fair quiz —
# guards against junk entries that are only symbols (".", '"', "/", "-", …).
MIN_MEANINGFUL_CHARS = 20
# Cap the quoted text so a giant xulosa doesn't blow past Telegram limits.
MAX_CONCLUSION_LEN = 700
# Don't reuse a report that was the source of one of the last N rounds.
RECENT_ROUNDS_EXCLUDE = 40
# How many candidate reports to pull and shuffle when picking a fresh quote.
CANDIDATE_POOL = 120


# Symbols some users dump as a "conclusion": lone dots, slashes, quotes, dashes.
_EDGE_JUNK = " \t\n\r.,;:!?\"'`«»“”‘’/\\|-–—_*•·=+~#@()[]{}<>"
_MEANINGFUL_RE = re.compile(r"[^\W_]", re.UNICODE)  # any letter or digit


def _clean_conclusion(text: str) -> str:
    """Strip stray symbols some users type instead of (or around) a real
    conclusion — leading/trailing dots, quotes, slashes, dashes — and collapse
    whitespace. Returns '' if nothing of substance is left."""
    if not text:
        return ""
    text = " ".join(text.split())          # collapse newlines/runs of spaces
    text = text.strip(_EDGE_JUNK)           # peel junk off both ends
    return text.strip()


def _is_meaningful(text: str) -> bool:
    """True only if the text carries enough real letters/digits to quiz on —
    rejects entries that are essentially just punctuation/symbols."""
    return len(_MEANINGFUL_RE.findall(text)) >= MIN_MEANINGFUL_CHARS


def _resolve_title(report) -> str:
    """The book a conclusion belongs to: the free-text `book`, else the first
    linked book title. Returns '' when nothing usable is found."""
    title = (report.book or "").strip()
    if title:
        return title
    m2m = list(report.books.values_list("title", flat=True))
    return (m2m[0].strip() if m2m and m2m[0] else "")


def _library_titles() -> list:
    """Every distinct book title known to the platform — the distractor pool.
    Combines the canonical GlobalBook list with free-text report titles so even
    books that never got a GlobalBook row can show up as decoys."""
    titles = list(GlobalBook.objects.values_list("title", flat=True))
    titles += list(
        ConfirmationReport.objects
        .exclude(book__isnull=True).exclude(book__exact="")
        .values_list("book", flat=True)
        .distinct()
    )
    # De-duplicate on the normalized form, keep the first display spelling.
    seen, unique = set(), []
    for t in titles:
        t = (t or "").strip()
        if not t:
            continue
        norm = normalize_uzbek_text(t)
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(t)
    return unique


def build_quiz_round():
    """Pick a real conclusion + 3 random decoy books, create and return a fresh
    BookQuizRound. Returns None when there isn't enough material yet."""
    used_report_ids = set(
        BookQuizRound.objects.order_by("-created_at")
        .values_list("source_report_id", flat=True)[:RECENT_ROUNDS_EXCLUDE]
    )

    candidates = list(
        ConfirmationReport.objects
        .filter(conclusion__isnull=False)
        .exclude(conclusion__exact="")
        .exclude(id__in=used_report_ids)
        .select_related("user")
        .order_by("-id")[:CANDIDATE_POOL]
    )
    random.shuffle(candidates)

    library = _library_titles()

    for report in candidates:
        conclusion = _clean_conclusion(report.conclusion)
        if not _is_meaningful(conclusion):
            continue
        correct = _resolve_title(report)
        if not correct:
            continue

        correct_norm = normalize_uzbek_text(correct)
        decoy_pool = [t for t in library if normalize_uzbek_text(t) != correct_norm]
        if len(decoy_pool) < 3:
            continue

        if len(conclusion) > MAX_CONCLUSION_LEN:
            conclusion = conclusion[:MAX_CONCLUSION_LEN].rstrip() + "…"

        decoys = random.sample(decoy_pool, 3)
        options = decoys + [correct]
        random.shuffle(options)
        correct_index = options.index(correct)

        # Close any still-open round before opening the new one.
        BookQuizRound.objects.filter(is_active=True).update(is_active=False)

        return BookQuizRound.objects.create(
            source_report=report,
            source_user=report.user,
            conclusion=conclusion,
            correct_title=correct,
            options=options,
            correct_index=correct_index,
            reward=REWARD_KITOBCHA,
            is_active=True,
        )

    return None


# ── Copy + keyboards ─────────────────────────────────────────────────────────
def build_quiz_text(quiz_round) -> str:
    consolation = getattr(quiz_round, "consolation", 5)
    return (
        "🧩 <b>KITOB VIKTORINASI</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "📖 <b>Bu iqtibos qaysi kitobdan?</b>\n\n"
        f"💬 <i>«{_escape(quiz_round.conclusion)}»</i>\n\n"
        f"🎯 To'g'ri javob → <b>+{quiz_round.reward}</b> 🪙\n"
        f"🎁 Noto'g'ri ham → <b>+{consolation}</b> 🪙 <i>(urinish uchun)</i>\n"
        "💎 Premium → <b>×2</b>\n\n"
        "👇 <b>Variantni tanlang:</b>"
    )


def build_results_block(quiz_round) -> str:
    """The live 'who answered right / wrong' board, rebuilt from the DB. Empty
    string until the first answer lands. Names are clickable mentions."""
    from tgbot.models import BookQuizAnswer

    answers = list(
        BookQuizAnswer.objects.filter(quiz_round=quiz_round)
        .select_related("user").order_by("created_at")
    )
    if not answers:
        return ""

    correct = [a for a in answers if a.is_correct]
    wrong = [a for a in answers if not a.is_correct]

    def _names(lst, cap=25):
        out = []
        for a in lst[:cap]:
            u = a.user
            nm = _escape((u.full_name if u and u.full_name else "Kitobxon"))
            tid = u.telegram_id if u else 0
            out.append(f"<a href='tg://user?id={tid}'>{nm}</a>")
        s = ", ".join(out)
        extra = len(lst) - cap
        if extra > 0:
            s += f" <i>+{extra}</i>"
        return s

    parts = ["\n━━━━━━━━━━━━━━━", "📊 <b>Natijalar</b>"]
    if correct:
        parts.append(f"✅ <b>To'g'ri ({len(correct)}):</b> {_names(correct)}")
    if wrong:
        parts.append(f"❌ <b>Noto'g'ri ({len(wrong)}):</b> {_names(wrong)}")
    return "\n".join(parts)


def build_quiz_text_with_board(quiz_round) -> str:
    return build_quiz_text(quiz_round) + build_results_block(quiz_round)


def quiz_keyboard(quiz_round) -> str:
    """JSON inline keyboard: one button per option, A/B/C/D labelled."""
    labels = ["🅰️", "🅱️", "🇨", "🇩"]
    rows = []
    for idx, opt in enumerate(quiz_round.options):
        label = labels[idx] if idx < len(labels) else str(idx + 1)
        rows.append([{
            "text": f"{label} {opt}"[:60],
            "callback_data": f"bq:{quiz_round.id}:{idx}",
        }])
    return json.dumps({"inline_keyboard": rows})


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Creative promo reminders ─────────────────────────────────────────────────
# Goal: tease the new Viktorina, keep it light — jokes (latifa), mood-lifters,
# and gentle conscience-nudges about reading. Each entry is a full HTML message;
# the broadcaster appends the standard "how to join" footer.
VIKTORINA_PROMO_POOL = [
    (
        "🧩 <b>Yangilik: KITOB VIKTORINASI!</b>\n\n"
        "Har kuni 2 marta — ertalab 08:30 va kechqurun 21:00 — guruhga bitta "
        "iqtibos tashlanadi. Vazifa oddiy: <b>qaysi kitobdan ekanini toping</b>!\n"
        "To'g'ri topsangiz — <b>+100 Kitobcha</b> cho'ntakda 🪙"
    ),
    (
        "😄 <i>Latifa:</i> Kitobni so'rabdilar: «Nega doim ochiqsan?» — "
        "«Chunki yopilsam, hech kim meni o'qimaydi» debdi.\n\n"
        "Sen ham yopilib qolma — bugungi <b>Viktorinada</b> qatnash, "
        "iqtibosni top, <b>+100 Kitobcha</b> yutib ol! 🧩"
    ),
    (
        "🤔 Bir savol: oxirgi o'qigan kitobingdan bitta iqtibos eslay olasanmi?\n\n"
        "Eslay olmasang — vijdon biroz qiynaladi-a? 😅 "
        "<b>Kitob Viktorinasi</b> aynan shu xotirani charxlaydi. "
        "Kuniga 2 marta, har to'g'ri javob <b>+100 Kitobcha</b>!"
    ),
    (
        "🧠 Miya — mushak. Ishlatmasang, dangasalashadi.\n\n"
        "Kuniga 2 daqiqa <b>Kitob Viktorinasi</b> bilan uni charxla: "
        "iqtibosni o'qi, kitobni top, <b>+100 Kitobcha</b> ol. Oson, ammo zo'r! 💪"
    ),
    (
        "📚 Kitob o'qiganlar biladi: eng yaxshi iqtiboslar yodda qoladi.\n\n"
        "Endi yodingdagi narsa <b>pul ishlaydi</b> 😎 — <b>Viktorinada</b> "
        "iqtibosni to'g'ri kitobga bog'la, har safar <b>+100 Kitobcha</b>!"
    ),
    (
        "😏 Rostini ayt: bugun necha bet o'qiding?\n\n"
        "Agar javob noqulay bo'lsa — hech qisi yo'q, hammasi seniki. "
        "Lekin <b>Kitob Viktorinasi</b> seni yana kitobga qaytaradi. "
        "Ertalab 08:30 va kechqurun 21:00 — qatnash, <b>+100 Kitobcha</b> yut! 🔥"
    ),
    (
        "🎯 <b>Viktorina qanday ishlaydi?</b>\n\n"
        "1️⃣ Kuni 2 marta guruhga haqiqiy iqtibos tashlanadi\n"
        "2️⃣ 4 ta kitob varianti chiqadi\n"
        "3️⃣ To'g'risini tanla — <b>+100 Kitobcha</b> seniki!\n\n"
        "Iqtiboslar — o'zimizning kitobxonlar yuborgan xulosalardan 📝"
    ),
    (
        "😅 <i>Latifa:</i> «Eng aqlli do'sting kim?» — «Kitob. Hech qachon bahslashmaydi, "
        "doim o'rgatadi».\n\n"
        "Aqlli do'sting bilan o'ynashni xohlaysanmi? <b>Kitob Viktorinasi</b> kutyapti — "
        "iqtibosni top, <b>+100 Kitobcha</b> ol! 🧩"
    ),
    (
        "🌙 Kechqurun 21:00 — qahva sovub, telefon qo'lda...\n\n"
        "Aynan shu payt <b>Kitob Viktorinasi</b> chiqadi. Bitta iqtibos, 4 ta kitob — "
        "to'g'risini topgin-chi? To'g'ri javob <b>+100 Kitobcha</b> 🪙"
    ),
    (
        "🔥 Reytingda yuqoriga chiqmoqchimisan?\n\n"
        "Kitobcha yig'ishning eng mazali yo'li — <b>Viktorina</b>. "
        "Kuniga 2 ta iqtibos, har biri <b>+100 Kitobcha</b>. "
        "O'qiganing ham, topganing ham — foyda! 📈"
    ),
    (
        "🤫 Sir: eng oson Kitobcha — Viktorinada.\n\n"
        "Iqtibosni diqqat bilan o'qisang, kitobni darrov sezasan. "
        "Kuniga 2 imkoniyat, har to'g'ri javob <b>+100 Kitobcha</b>. "
        "Bugun o'tkazib yubormagin! 💎"
    ),
    (
        "📖 «Kitob — tafakkur qanotidir» deyishadi.\n\n"
        "Qanotlaringni sina: <b>Kitob Viktorinasida</b> iqtibosni to'g'ri kitobga "
        "bog'la, <b>+100 Kitobcha</b> bilan parvoz qil! 🕊️"
    ),
    (
        "😌 Vijdoningni yoqimli qiynaymizmi?\n\n"
        "Sen yuborgan xulosalar boshqalar uchun savolga aylanmoqda. "
        "Sen ham boshqalarnikini topib ko'r — <b>Viktorina</b>, kuniga 2 marta, "
        "<b>+100 Kitobcha</b> har to'g'ri javobga 🧩"
    ),
]

PROMO_FOOTER = (
    "\n\n📚 Javob berish uchun kitobxonlar guruhiga a'zo bo'lish kifoya — "
    "bepul!\n"
    "💎 <b>Premium</b> bo'lsangiz: mukofot <b>×2</b> bo'ladi va topgan "
    "iqtiboslaringiz statistikasini ko'rasiz! 👤"
)


def pick_promo_text() -> str:
    return random.choice(VIKTORINA_PROMO_POOL) + PROMO_FOOTER
