"""
Book Recommendation Engine — Item-Based Collaborative Filtering
---------------------------------------------------------------
Algorithm (no external ML libraries needed — pure Python + Django ORM):

  1. Build a user→books matrix from ConfirmationReport history.
     Each book a user has read = 1 "interaction" (binary signal).

  2. For each book pair (A, B), compute Jaccard similarity:
        J(A, B) = |readers(A) ∩ readers(B)| / |readers(A) ∪ readers(B)|
     Jaccard is ideal here because it naturally handles popularity bias —
     a book read by 5 000 people doesn't dominate just because of volume.

  3. For a target user who has read books {A, B, C, …}, their recommendation
     score for an unseen book X is:
        score(X) = max( J(A, X), J(B, X), J(C, X), … )
     We take the max (not sum) so a single very strong neighbour carries the
     recommendation even if only one of the user's books is similar to X.

  4. Return the top-N unseen books sorted by descending score,
     filtered to those with score ≥ MIN_SIMILARITY.

Why item-based CF and not user-based?
  • Stable: book similarity changes rarely; user similarity needs daily recompute.
  • Explainable: "Because you read X, you might like Y" is a natural message.
  • Scales well: O(books²) pre-computation, O(user_books × candidates) at query time.

Entry points:
    get_recommendations(user_id, top_n=3)   → list[dict]  (title, score, because)
    build_similarity_index()                → dict         (cached in module-level var)
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import NamedTuple

from django.db.models import Count

MIN_SIMILARITY = 0.05   # ignore book pairs that share fewer than ~5% of readers
MIN_READERS = 3         # ignore books read by fewer than this many users (too sparse)
MIN_USER_BOOKS = 2      # user needs at least this many distinct books for CF to work
CACHE_TTL_SECONDS = 3600 * 6   # rebuild similarity index at most every 6 hours

# ── Module-level similarity cache ────────────────────────────────────────────
_similarity_index: dict[str, list[tuple[str, float]]] = {}  # book → [(similar_book, score)]
_index_built_at: float = 0.0


class Recommendation(NamedTuple):
    title: str          # book title to recommend
    score: float        # Jaccard similarity (0–1)
    because: str        # title of the user's book that drives this recommendation


# ── Public API ────────────────────────────────────────────────────────────────

def get_recommendations(user_id: int, top_n: int = 3) -> list[Recommendation]:
    """
    Return up to top_n book recommendations for the given TelegramProfile pk.
    Returns [] if the user has too few books or no good neighbours exist.
    """
    from tgbot.models import ConfirmationReport

    user_books: set[str] = set(
        ConfirmationReport.objects
        .filter(user_id=user_id, is_audio=False)
        .exclude(book__isnull=True)
        .exclude(book="")
        .values_list("book", flat=True)
        .distinct()
    )

    if len(user_books) < MIN_USER_BOOKS:
        return []

    index = _get_index()
    if not index:
        return []

    # score every unseen book
    candidates: dict[str, tuple[float, str]] = {}  # title → (best_score, because_title)
    for user_book in user_books:
        for similar_title, sim_score in index.get(user_book, []):
            if similar_title in user_books:
                continue   # user already read it
            prev_score, _ = candidates.get(similar_title, (0.0, ""))
            if sim_score > prev_score:
                candidates[similar_title] = (sim_score, user_book)

    if not candidates:
        return []

    ranked = sorted(candidates.items(), key=lambda kv: kv[1][0], reverse=True)
    return [
        Recommendation(title=title, score=score, because=because)
        for title, (score, because) in ranked[:top_n]
    ]


def get_popular_fallback(user_id: int, top_n: int = 3) -> list[Recommendation]:
    """Fallback for users with too little history for personalized CF
    (< MIN_USER_BOOKS distinct books): the N most-read books overall (by
    distinct reader count), excluding anything the user has already read.
    `because` is set to "" since there's no personal anchor book — callers
    should render these as "popular among readers" rather than "because you
    read X"."""
    from tgbot.models import ConfirmationReport

    user_books: set[str] = set(
        ConfirmationReport.objects
        .filter(user_id=user_id, is_audio=False)
        .exclude(book__isnull=True).exclude(book="")
        .values_list("book", flat=True).distinct()
    )

    rows = (
        ConfirmationReport.objects
        .filter(is_audio=False)
        .exclude(book__isnull=True).exclude(book="")
        .values("book")
        .annotate(readers=Count("user_id", distinct=True))
        .order_by("-readers")
    )

    out = []
    for row in rows:
        title = row["book"]
        if title in user_books:
            continue
        out.append(Recommendation(title=title, score=0.0, because=""))
        if len(out) >= top_n:
            break
    return out


def build_similarity_index(force: bool = False) -> dict[str, list[tuple[str, float]]]:
    """
    Build and cache the book-book Jaccard similarity index.
    Reads ConfirmationReport to find which users read which books, then
    computes pairwise similarity for all books with enough readers.

    Set force=True to bypass the cache TTL (e.g., run from management command).
    """
    global _similarity_index, _index_built_at

    if not force and _similarity_index and (time.time() - _index_built_at) < CACHE_TTL_SECONDS:
        return _similarity_index

    from tgbot.models import ConfirmationReport

    # Step 1: book → set of user_ids who read it
    rows = (
        ConfirmationReport.objects
        .filter(is_audio=False)
        .exclude(book__isnull=True)
        .exclude(book="")
        .values("book", "user_id")
        .distinct()
    )

    book_readers: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        book_readers[row["book"]].add(row["user_id"])

    # Step 2: drop books with too few readers (noise)
    qualified = {b: readers for b, readers in book_readers.items() if len(readers) >= MIN_READERS}

    if len(qualified) < 2:
        _similarity_index = {}
        _index_built_at = time.time()
        return _similarity_index

    # Step 3: compute pairwise Jaccard similarity
    books = list(qualified.keys())
    index: dict[str, list[tuple[str, float]]] = defaultdict(list)

    for i in range(len(books)):
        readers_a = qualified[books[i]]
        for j in range(i + 1, len(books)):
            readers_b = qualified[books[j]]
            intersection = len(readers_a & readers_b)
            if intersection == 0:
                continue
            union = len(readers_a | readers_b)
            jaccard = intersection / union
            if jaccard >= MIN_SIMILARITY:
                index[books[i]].append((books[j], jaccard))
                index[books[j]].append((books[i], jaccard))

    # Step 4: sort each entry by descending similarity for fast query-time lookup
    for book in index:
        index[book].sort(key=lambda x: x[1], reverse=True)

    _similarity_index = dict(index)
    _index_built_at = time.time()
    return _similarity_index


# ── Message formatters ────────────────────────────────────────────────────────

def format_recommendations_uz(
    full_name: str,
    recs: list[Recommendation],
) -> str:
    if not recs:
        return ""
    lines = [f"📚 <b>{full_name}</b>, sizga o'xshash kitobxonlar o'qigan kitoblar:\n"]
    for i, rec in enumerate(recs, 1):
        lines.append(
            f"{i}. <b>{rec.title}</b>\n"
            f"   <i>«{rec.because}»ni o'qiganlar bu kitobni ham yoqtirgan</i>"
        )
    lines.append("\n<i>Bu tavsiyalar sizning o'qish tarixingiz asosida tayyorlandi.</i>")
    return "\n".join(lines)


def format_recommendations_ru(
    full_name: str,
    recs: list[Recommendation],
) -> str:
    if not recs:
        return ""
    lines = [f"📚 <b>{full_name}</b>, книги, которые читают похожие на вас читатели:\n"]
    for i, rec in enumerate(recs, 1):
        lines.append(
            f"{i}. <b>{rec.title}</b>\n"
            f"   <i>Читатели «{rec.because}» также полюбили эту книгу</i>"
        )
    lines.append("\n<i>Рекомендации подготовлены на основе вашей истории чтения.</i>")
    return "\n".join(lines)


def format_recommendations(
    full_name: str,
    recs: list[Recommendation],
    language: str = "uz",
) -> str:
    if language == "ru":
        return format_recommendations_ru(full_name, recs)
    return format_recommendations_uz(full_name, recs)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_index() -> dict[str, list[tuple[str, float]]]:
    """Return cached index, building it if stale."""
    return build_similarity_index(force=False)
