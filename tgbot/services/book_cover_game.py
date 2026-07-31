"""Kitob Muqovasi — build the daily "guess the book from its blurred cover"
game from real library uploads (GlobalBook.cover), render its copy, and
produce the blurred image bytes.

The round-building + image helpers touch the ORM/filesystem and run from the
sync Celery side; the copy builders are pure and safe to import anywhere.
"""
import io
import json
import random

from tgbot.models import BookCoverRound, GlobalBook, normalize_uzbek_text

REWARD_KITOBCHA = 100
CONSOLATION_KITOBCHA = 5
# Don't reuse a book that was the source of one of the last N rounds.
RECENT_ROUNDS_EXCLUDE = 20
# Gaussian blur radius applied to the cover -- strong enough that any title
# text on the cover is unreadable, while shapes/colors stay guessable.
BLUR_RADIUS = 14


def _library_titles() -> list:
    """Every distinct GlobalBook title -- the distractor pool."""
    return list(GlobalBook.objects.exclude(title__exact="").values_list("title", flat=True))


def build_cover_round():
    """Pick a random book with a cover image (not recently used) + 3 decoy
    titles, create and return a fresh BookCoverRound. None if there isn't
    enough material (too few covers, or too few decoys)."""
    used_book_ids = set(
        BookCoverRound.objects.order_by("-created_at")
        .values_list("book_id", flat=True)[:RECENT_ROUNDS_EXCLUDE]
    )
    candidates = list(
        GlobalBook.objects.exclude(cover="").exclude(cover__isnull=True)
        .exclude(id__in=used_book_ids)
    )
    if not candidates:
        # Pool exhausted (fewer covers than RECENT_ROUNDS_EXCLUDE) -- allow repeats.
        candidates = list(GlobalBook.objects.exclude(cover="").exclude(cover__isnull=True))
    if not candidates:
        return None

    library = _library_titles()
    random.shuffle(candidates)

    for book in candidates:
        correct_norm = normalize_uzbek_text(book.title)
        decoy_pool = [t for t in library if normalize_uzbek_text(t) != correct_norm]
        if len(decoy_pool) < 3:
            continue

        decoys = random.sample(decoy_pool, 3)
        options = decoys + [book.title]
        random.shuffle(options)
        correct_index = options.index(book.title)

        return BookCoverRound.objects.create(
            book=book,
            options=options,
            correct_index=correct_index,
            reward=REWARD_KITOBCHA,
            consolation=CONSOLATION_KITOBCHA,
            is_active=True,
        )

    return None


def build_blurred_cover_bytes(cover_round) -> bytes:
    """Open the round's book cover, apply a strong Gaussian blur, return JPEG
    bytes ready to upload -- nothing is written back to storage, generated
    fresh per broadcast."""
    from PIL import Image, ImageFilter

    with cover_round.book.cover.open("rb") as f:
        img = Image.open(f)
        img = img.convert("RGB")
        img = img.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


# ── Copy + keyboards ─────────────────────────────────────────────────────────
def build_cover_text(cover_round) -> str:
    return (
        "🖼 <b>KITOB MUQOVASI</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "📚 <b>Bu xira muqova qaysi kitobga tegishli?</b>\n\n"
        f"🎯 To'g'ri javob → <b>+{cover_round.reward}</b> 🪙\n"
        f"🎁 Noto'g'ri ham → <b>+{cover_round.consolation}</b> 🪙 <i>(urinish uchun)</i>\n"
        "💎 Premium → <b>×2</b>\n\n"
        "👇 <b>Variantni tanlang:</b>"
    )


def build_results_block(cover_round) -> str:
    """The live 'who answered right / wrong' board, rebuilt from the DB."""
    from tgbot.models import BookCoverAnswer

    answers = list(
        BookCoverAnswer.objects.filter(cover_round=cover_round)
        .select_related("user").order_by("created_at")
    )
    if not answers:
        return ""

    correct = [a for a in answers if a.is_correct]
    wrong = [a for a in answers if not a.is_correct]

    def _names(lst, cap=25):
        # Plain bold text, not mention links -- see feedback_keep_group_
        # leaderboards memory: many hidden tg://user?id= links in one message
        # previously tripped Telegram's spam filter and silently stripped it.
        out = []
        for a in lst[:cap]:
            u = a.user
            nm = _escape((u.full_name if u and u.full_name else "Kitobxon"))
            out.append(f"<b>{nm}</b>")
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


def build_cover_text_with_board(cover_round) -> str:
    return build_cover_text(cover_round) + build_results_block(cover_round)


def cover_keyboard(cover_round) -> str:
    """JSON inline keyboard: one button per option, A/B/C/D labelled."""
    labels = ["A", "B", "C", "D"]
    rows = []
    for idx, opt in enumerate(cover_round.options):
        label = labels[idx] if idx < len(labels) else str(idx + 1)
        rows.append([{
            "text": f"  {label}  ·  {opt}",
            "callback_data": f"bc:{cover_round.id}:{idx}",
        }])
    return json.dumps({"inline_keyboard": rows})


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
