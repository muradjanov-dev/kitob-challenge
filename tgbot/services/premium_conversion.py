"""
Premium Conversion Predictor
-----------------------------
Scores every free user 0–100 on their likelihood to convert to Premium,
then returns the top candidates with a personalised upsell message that
references something *specific* about their own reading activity.

Algorithm — weighted feature scoring (no external ML libraries):
────────────────────────────────────────────────────────────────
We use a hand-crafted logistic-style score built from behavioural signals
that correlate with Premium intent:

  Feature                          Max pts  Why it matters
  ────────────────────────────────────────────────────────
  Streak ≥ 7 days                    20     Habit-formed users value the stats
  Streak ≥ 14 days (bonus)           +10    Even stronger signal
  Total reports ≥ 10                 15     Past commitment → future investment
  Total reports ≥ 30 (bonus)        +10     Power user
  Avg pages/day ≥ 20                 15     High-volume readers want detailed tracking
  Avg pages/day ≥ 40 (bonus)        +10     Very high volume
  Has long conclusions (≥ 5)         10     Reflective readers love the AI report
  Quiz plays ≥ 5                      5     Engaged with premium-gated features
  Books finished ≥ 2                  5     Progress-oriented → values milestones
  Report in last 3 days               5     Currently active (warm lead)
  Report in last 7 days (partial)    +3     Still warm
  Rank in top 25% today               5     Competitive → attracted to leaderboard

Max possible: 100 pts.
Threshold for upsell: ≥ 40 pts (configurable).

Why rule-based instead of trained ML?
  • You don't yet have labelled conversion data (who was nudged AND converted).
  • Once you have ~200 conversions you can replace this with a logistic
    regression or gradient boost trained on these same features.
  • The weights here encode domain logic you already know to be true.

Entry points:
    score_user(user_id)             → int (0–100)
    get_top_candidates(limit, min_score) → list[CandidateResult]
    format_upsell_message(result, language) → str
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db.models import Avg, Count, Sum
from django.db.models.functions import Length, TruncDate
from django.utils import timezone


# ── Tuneable thresholds ───────────────────────────────────────────────────────
MIN_SCORE = 40          # only contact users scoring at least this
DEFAULT_LIMIT = 200     # max users to message per run (avoid overloading Telegram)


# ── Feature weights ───────────────────────────────────────────────────────────
W_STREAK_7      = 20
W_STREAK_14     = 10   # bonus on top of W_STREAK_7
W_REPORTS_10    = 15
W_REPORTS_30    = 10   # bonus
W_AVG_PAGES_20  = 15
W_AVG_PAGES_40  = 10   # bonus
W_LONG_CONCL    = 10
W_QUIZ_PLAYS    = 5
W_BOOKS_FIN     = 5
W_ACTIVE_3D     = 5
W_ACTIVE_7D     = 3    # partial credit
W_TOP_QUARTILE  = 5


@dataclass
class CandidateResult:
    user_id: int
    telegram_id: int
    full_name: str
    language: str
    score: int
    streak: int
    avg_pages: float
    total_reports: int
    books_finished: int
    long_conclusions: int
    active_days_last_7: int


# ── Public API ────────────────────────────────────────────────────────────────

def get_top_candidates(
    limit: int = DEFAULT_LIMIT,
    min_score: int = MIN_SCORE,
) -> list[CandidateResult]:
    """
    Return up to `limit` free users ordered by conversion score descending,
    filtered to those scoring >= min_score.

    Excludes:
    - Users who already have an active Premium subscription
    - Blocked / unregistered users
    """
    from tgbot.models import (
        TelegramProfile, ConfirmationReport, Payment, BooksToRead, BookQuizAnswer
    )

    today = timezone.localdate()

    # ── Who is already Premium? ───────────────────────────────────────────────
    premium_user_ids = set(
        Payment.objects.filter(
            status="paid", end_date__gte=today
        ).values_list("user_id", flat=True)
    )

    # ── Candidate pool: registered free users ─────────────────────────────────
    candidates = list(
        TelegramProfile.objects.filter(
            is_registered=True, is_blocked=False,
        ).exclude(
            id__in=premium_user_ids
        ).only("id", "telegram_id", "full_name", "language")
    )

    if not candidates:
        return []

    candidate_ids = [u.id for u in candidates]

    # ── Pre-fetch aggregates in bulk (one query each) ─────────────────────────
    # Total reports per user
    report_counts = {
        r["user_id"]: r["cnt"]
        for r in ConfirmationReport.objects.filter(user_id__in=candidate_ids)
        .values("user_id").annotate(cnt=Count("id"))
    }

    # Average pages per report (non-audio)
    avg_pages_map = {
        r["user_id"]: float(r["avg"] or 0)
        for r in ConfirmationReport.objects.filter(
            user_id__in=candidate_ids, is_audio=False
        ).values("user_id").annotate(avg=Avg("pages_read"))
    }

    # Long conclusions count (>= 200 chars)
    long_concl_map = {
        r["user_id"]: r["cnt"]
        for r in ConfirmationReport.objects.filter(user_id__in=candidate_ids)
        .annotate(_l=Length("conclusion")).filter(_l__gte=200)
        .values("user_id").annotate(cnt=Count("id"))
    }

    # Books finished
    books_fin_map = {
        r["user"]: r["cnt"]
        for r in BooksToRead.objects.filter(
            user_id__in=candidate_ids,
            total_pages__gt=0,
        ).extra(where=["current_page >= total_pages"])
        .values("user").annotate(cnt=Count("id"))
    }

    # Quiz answers (plays)
    quiz_map = {
        r["user_id"]: r["cnt"]
        for r in BookQuizAnswer.objects.filter(user_id__in=candidate_ids)
        .values("user_id").annotate(cnt=Count("id"))
    }

    # Active days in last 3 and 7 days
    three_days_ago = today - datetime.timedelta(days=3)
    seven_days_ago = today - datetime.timedelta(days=7)

    active_3d = set(
        ConfirmationReport.objects.filter(
            user_id__in=candidate_ids, date__date__gte=three_days_ago
        ).values_list("user_id", flat=True).distinct()
    )
    active_7d = set(
        ConfirmationReport.objects.filter(
            user_id__in=candidate_ids, date__date__gte=seven_days_ago
        ).values_list("user_id", flat=True).distinct()
    )

    # Current streaks — compute per user from report dates
    streak_map = _compute_streaks(candidate_ids)

    # Today's ranking — who is in top 25%?
    today_ranks = list(
        ConfirmationReport.objects.filter(
            date__date=today, is_audio=False, user_id__in=candidate_ids
        ).values("user_id").annotate(pages=Sum("pages_read"))
        .order_by("-pages")
    )
    total_today = len(today_ranks)
    top_quartile_ids: set[int] = set()
    if total_today:
        cutoff = max(1, total_today // 4)
        top_quartile_ids = {r["user_id"] for r in today_ranks[:cutoff]}

    # ── Score every candidate ─────────────────────────────────────────────────
    results: list[CandidateResult] = []

    for user in candidates:
        uid = user.id
        streak        = streak_map.get(uid, 0)
        total_reports = report_counts.get(uid, 0)
        avg_pages     = avg_pages_map.get(uid, 0.0)
        long_concl    = long_concl_map.get(uid, 0)
        books_fin     = books_fin_map.get(uid, 0)
        quiz_plays    = quiz_map.get(uid, 0)
        in_3d         = uid in active_3d
        in_7d         = uid in active_7d
        top_q         = uid in top_quartile_ids

        score = 0
        if streak >= 7:
            score += W_STREAK_7
        if streak >= 14:
            score += W_STREAK_14
        if total_reports >= 10:
            score += W_REPORTS_10
        if total_reports >= 30:
            score += W_REPORTS_30
        if avg_pages >= 20:
            score += W_AVG_PAGES_20
        if avg_pages >= 40:
            score += W_AVG_PAGES_40
        if long_concl >= 5:
            score += W_LONG_CONCL
        if quiz_plays >= 5:
            score += W_QUIZ_PLAYS
        if books_fin >= 2:
            score += W_BOOKS_FIN
        if in_3d:
            score += W_ACTIVE_3D
        elif in_7d:
            score += W_ACTIVE_7D
        if top_q:
            score += W_TOP_QUARTILE

        if score < min_score:
            continue

        results.append(CandidateResult(
            user_id=uid,
            telegram_id=user.telegram_id,
            full_name=user.full_name or "Kitobxon",
            language=user.language or "uz",
            score=score,
            streak=streak,
            avg_pages=avg_pages,
            total_reports=total_reports,
            books_finished=books_fin,
            long_conclusions=long_concl,
            active_days_last_7=1 if in_7d else 0,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


def format_upsell_message(result: CandidateResult, language: str = "uz") -> str:
    """
    Build a personalised Premium upsell message that references the user's
    specific strongest signal — so it feels like an observation, not a blast.
    """
    if language == "ru":
        return _format_ru(result)
    return _format_uz(result)


# ── Message formatters ────────────────────────────────────────────────────────

def _format_uz(r: CandidateResult) -> str:
    name = r.full_name

    # Pick the most impressive personal stat to lead with
    if r.streak >= 14:
        hook = (
            f"🔥 <b>{name}</b>, {r.streak} kunlik streak — bu jiddiy natija!\n"
            f"Siz allaqachon faol kitobxonlar orasidagi eng barqarorlardan birisiz."
        )
    elif r.avg_pages >= 40:
        hook = (
            f"📖 <b>{name}</b>, o'rtacha kuniga <b>{r.avg_pages:.0f} bet</b> — "
            f"bu sizni TOP kitobxonlar qatoriga qo'yadi."
        )
    elif r.streak >= 7:
        hook = (
            f"⚡ <b>{name}</b>, {r.streak} kunlik streak bilan davom etyapsiz — "
            f"bu odatga aylangan, qutlaymiz!"
        )
    elif r.total_reports >= 30:
        hook = (
            f"📚 <b>{name}</b>, allaqachon <b>{r.total_reports} ta hisobot</b> — "
            f"bu sizning jiddiyligingizni ko'rsatadi."
        )
    elif r.long_conclusions >= 5:
        hook = (
            f"✍️ <b>{name}</b>, chuqur xulosa yozishingiz — "
            f"siz kitobni shunchaki o'qimaysiz, tahlil qilasiz."
        )
    else:
        hook = (
            f"📈 <b>{name}</b>, o'qish natijalaringiz o'sib borayapti!"
        )

    return (
        f"{hook}\n\n"
        f"💎 <b>Premium obuna</b> sizga nima beradi:\n\n"
        f"  📊 Har kuni to'liq shaxsiy tahlil (kecha, hafta, oy, yil)\n"
        f"  🤖 Har shanba AI tomonidan yozilgan shaxsiy haftalik hisobot\n"
        f"  📚 Haftalik kitob tavsiyalari (siz o'qigan kitoblar asosida)\n"
        f"  💰 Har bir hisobot uchun 2× Kitobcha — 2 baravar tez to'plasiz\n"
        f"  🏆 Viktorina to'g'ri javobida 2× mukofot\n\n"
        f"<i>Menyudan 💎 Premium tugmasini bosing va bugundan boshlang!</i>"
    )


def _format_ru(r: CandidateResult) -> str:
    name = r.full_name

    if r.streak >= 14:
        hook = (
            f"🔥 <b>{name}</b>, {r.streak} дней подряд — это серьёзный результат!\n"
            f"Вы уже среди самых стабильных читателей."
        )
    elif r.avg_pages >= 40:
        hook = (
            f"📖 <b>{name}</b>, в среднем <b>{r.avg_pages:.0f} страниц в день</b> — "
            f"это ставит вас в ряд топовых читателей."
        )
    elif r.streak >= 7:
        hook = (
            f"⚡ <b>{name}</b>, {r.streak} дней подряд — "
            f"чтение стало привычкой, поздравляем!"
        )
    elif r.total_reports >= 30:
        hook = (
            f"📚 <b>{name}</b>, уже <b>{r.total_reports} отчётов</b> — "
            f"это говорит о вашей серьёзности."
        )
    elif r.long_conclusions >= 5:
        hook = (
            f"✍️ <b>{name}</b>, вы пишете глубокие выводы — "
            f"вы не просто читаете, вы анализируете."
        )
    else:
        hook = (
            f"📈 <b>{name}</b>, ваши показатели чтения растут!"
        )

    return (
        f"{hook}\n\n"
        f"💎 <b>Подписка Premium</b> — что вы получите:\n\n"
        f"  📊 Полный личный анализ каждый день (вчера, неделя, месяц, год)\n"
        f"  🤖 Персональный еженедельный отчёт от AI каждую субботу\n"
        f"  📚 Еженедельные рекомендации книг на основе вашей истории\n"
        f"  💰 2× Kitobcha за каждый отчёт — накапливаете вдвое быстрее\n"
        f"  🏆 2× награда за правильный ответ в Викторине\n\n"
        f"<i>Нажмите 💎 Premium в меню и начните уже сегодня!</i>"
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _compute_streaks(user_ids: list[int]) -> dict[int, int]:
    """
    Compute current streak (consecutive days ending today or yesterday)
    for all given user_ids in a single DB query.
    Returns {user_id: streak_length}.
    """
    from tgbot.models import ConfirmationReport

    today = timezone.localdate()

    # Fetch all distinct report dates per user, ordered ascending
    rows = list(
        ConfirmationReport.objects.filter(user_id__in=user_ids)
        .annotate(_d=TruncDate("date"))
        .values("user_id", "_d")
        .distinct()
        .order_by("user_id", "_d")
    )

    # Group by user
    from collections import defaultdict
    user_dates: dict[int, list[datetime.date]] = defaultdict(list)
    for row in rows:
        user_dates[row["user_id"]].append(row["_d"])

    streaks: dict[int, int] = {}
    for uid, dates in user_dates.items():
        if not dates:
            streaks[uid] = 0
            continue
        # Walk backwards from today
        streak = 0
        expected = today
        for d in reversed(dates):
            if d == expected:
                streak += 1
                expected -= datetime.timedelta(days=1)
            elif d < expected:
                # Gap found — check if streak started from yesterday (still valid)
                if streak == 0 and d == today - datetime.timedelta(days=1):
                    streak = 1
                    expected = d - datetime.timedelta(days=1)
                else:
                    break
        streaks[uid] = streak

    return streaks
