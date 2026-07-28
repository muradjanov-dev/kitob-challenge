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
import random
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
    ball: int


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
        ).only("id", "telegram_id", "full_name", "language", "ball")
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
            ball=int(user.ball or 0),
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

    # Pick the most impressive personal stat, then a random funny phrasing
    # for it — same tier, different words each time this fires (every 2
    # days), so a persistent free user doesn't see an identical blast.
    if r.streak >= 14:
        hooks = [
            f"🔥 <b>{name}</b>, {r.streak} kunlik streak — bu jiddiy natija!\nSiz allaqachon faol kitobxonlar orasidagi eng barqarorlardan birisiz.",
            f"🏋️ <b>{name}</b>, {r.streak} kun ketma-ket — bu tasodif emas, bu intizom! Premium bunga munosib mukofot.",
            f"😳 {r.streak} kun to'xtamay o'qish... <b>{name}</b>, siz oddiy foydalanuvchi emassiz endi.",
        ]
    elif r.avg_pages >= 40:
        hooks = [
            f"📖 <b>{name}</b>, o'rtacha kuniga <b>{r.avg_pages:.0f} bet</b> — bu sizni TOP kitobxonlar qatoriga qo'yadi.",
            f"🚀 Kuniga {r.avg_pages:.0f} bet?! <b>{name}</b>, siz kitobni o'qimayapsiz, uni yutib yuboryapsiz!",
            f"⚡ <b>{name}</b>, {r.avg_pages:.0f} bet/kun tezligingiz bilan yiliga bir necha o'nlab kitob tugatasiz.",
        ]
    elif r.streak >= 7:
        hooks = [
            f"⚡ <b>{name}</b>, {r.streak} kunlik streak bilan davom etyapsiz — bu odatga aylangan, qutlaymiz!",
            f"🎯 {r.streak} kun uzluksiz o'qish — <b>{name}</b>, streak'ingiz sizdan ko'ra qat'iyatliroq ko'rinadi.",
        ]
    elif r.total_reports >= 30:
        hooks = [
            f"📚 <b>{name}</b>, allaqachon <b>{r.total_reports} ta hisobot</b> — bu sizning jiddiyligingizni ko'rsatadi.",
            f"🗂 {r.total_reports} ta hisobot?! <b>{name}</b>, bu kichik kutubxona darajasida!",
        ]
    elif r.long_conclusions >= 5:
        hooks = [
            f"✍️ <b>{name}</b>, chuqur xulosa yozishingiz — siz kitobni shunchaki o'qimaysiz, tahlil qilasiz.",
            f"🧠 <b>{name}</b>, xulosalaringiz shu qadar chuqurki, ular alohida kitob bo'lishi mumkin.",
        ]
    else:
        hooks = [
            f"📈 <b>{name}</b>, o'qish natijalaringiz o'sib borayapti!",
            f"🌱 <b>{name}</b>, kichik qadamlar katta natijaga olib boradi — davom eting!",
        ]
    hook = random.choice(hooks)

    # Personalized Kitobcha-doubling CTA when they have a meaningful balance,
    # otherwise fall back to a feature-list closer.
    ctas = []
    if r.ball >= 50:
        doubled = r.ball * 2
        ctas.append(
            f"🪙 Sizda hozir <b>{r.ball:,} Kitobcha</b> bor ekan — Premium bilan bu allaqachon "
            f"<b>{doubled:,}</b> bo'lardi! Hali ham kech emas — keyingi Kitobchalaringizni "
            f"2× tezlikda qo'lga kiritishni hozir boshlang."
        )
    ctas += [
        (
            "💎 <b>Premium</b> bilan nima o'zgaradi:\n\n"
            "  📊 Har kuni to'liq shaxsiy tahlil (kecha, hafta, oy, yil)\n"
            "  🤖 Har shanba AI tomonidan yozilgan shaxsiy haftalik hisobot\n"
            "  📚 Haftalik kitob tavsiyalari\n"
            "  💰 Har bir hisobot uchun 2× Kitobcha\n"
            "  🏆 Viktorinada 2× mukofot"
        ),
        (
            "🎁 Xayolingizga kelmagan narsa: Premium narxi bir chashka qahvadan arzon, "
            "ammo har kuni 2× Kitobcha, to'liq shaxsiy statistika va AI hisobot beradi."
        ),
    ]
    cta = random.choice(ctas)

    return f"{hook}\n\n{cta}\n\n<i>Pastdagi tugmani bosing va bugundan boshlang!</i>"


def _format_ru(r: CandidateResult) -> str:
    name = r.full_name

    if r.streak >= 14:
        hooks = [
            f"🔥 <b>{name}</b>, {r.streak} дней подряд — это серьёзный результат!\nВы уже среди самых стабильных читателей.",
            f"🏋️ <b>{name}</b>, {r.streak} дней без перерыва — это не случайность, а дисциплина!",
        ]
    elif r.avg_pages >= 40:
        hooks = [
            f"📖 <b>{name}</b>, в среднем <b>{r.avg_pages:.0f} страниц в день</b> — это ставит вас в ряд топовых читателей.",
            f"🚀 {r.avg_pages:.0f} страниц в день?! <b>{name}</b>, вы не читаете книги, вы их проглатываете!",
        ]
    elif r.streak >= 7:
        hooks = [
            f"⚡ <b>{name}</b>, {r.streak} дней подряд — чтение стало привычкой, поздравляем!",
        ]
    elif r.total_reports >= 30:
        hooks = [
            f"📚 <b>{name}</b>, уже <b>{r.total_reports} отчётов</b> — это говорит о вашей серьёзности.",
        ]
    elif r.long_conclusions >= 5:
        hooks = [
            f"✍️ <b>{name}</b>, вы пишете глубокие выводы — вы не просто читаете, вы анализируете.",
        ]
    else:
        hooks = [
            f"📈 <b>{name}</b>, ваши показатели чтения растут!",
        ]
    hook = random.choice(hooks)

    ctas = []
    if r.ball >= 50:
        doubled = r.ball * 2
        ctas.append(
            f"🪙 У вас сейчас <b>{r.ball:,} Kitobcha</b> — с Premium это было бы уже "
            f"<b>{doubled:,}</b>! Ещё не поздно — начните получать вдвое больше уже сейчас."
        )
    ctas.append(
        "💎 <b>Premium</b> — что изменится:\n\n"
        "  📊 Полный личный анализ каждый день\n"
        "  🤖 Персональный отчёт от AI каждую субботу\n"
        "  📚 Еженедельные рекомендации книг\n"
        "  💰 2× Kitobcha за каждый отчёт\n"
        "  🏆 2× награда в Викторине"
    )
    cta = random.choice(ctas)

    return f"{hook}\n\n{cta}\n\n<i>Нажмите кнопку ниже и начните уже сегодня!</i>"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _compute_streaks(user_ids: list[int]) -> dict[int, int]:
    """
    Compute current streak (consecutive days ending today or yesterday)
    for all given user_ids in a single DB query.
    Returns {user_id: streak_length}.

    Dates covered by a Market 'Streak muzlatish' (StreakFreezeCoverage) count
    as reported even without an actual report.
    """
    from tgbot.models import ConfirmationReport, StreakFreezeCoverage

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
    user_dates: dict[int, set] = defaultdict(set)
    for row in rows:
        user_dates[row["user_id"]].add(row["_d"])

    for row in StreakFreezeCoverage.objects.filter(user_id__in=user_ids).values("user_id", "date"):
        user_dates[row["user_id"]].add(row["date"])

    user_dates = {uid: sorted(dates) for uid, dates in user_dates.items()}

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
