"""
Achievement system. Achievement metadata lives here in code (not DB).

Workflow:
    1. After each ConfirmationReport save, call `award_new_achievements(user)`.
    2. It computes `compute_user_stats(user)`, evaluates each ACHIEVEMENT's
       condition, creates a UserAchievement row for any newly-unlocked code,
       and queues a Tabriklash broadcast for each.
"""
from datetime import timedelta
from typing import Callable, List, Optional, TypedDict

from django.db.models import Count, Sum, Avg, F, Max, Min
from django.db.models.functions import Length, TruncDate
from django.utils import timezone

from tgbot.models import (
    TelegramProfile, ConfirmationReport, BooksToRead, UserAchievement,
    UserReferal, ChainScore, FeudScore, CastleHit, EmojiScore, WisdomScore,
    DetectiveScore, SurvivalPlayer, QuizScore, ShopPurchase, Payment, BookComment,
)


GENERAL_GROUP_ID = -1002237773868


# ──────────────────────────────────────────────────────────────────────────
# Stats container.
# ──────────────────────────────────────────────────────────────────────────
class Stats(TypedDict):
    reports: int
    pages: int
    books_finished: int
    max_streak: int
    long_conclusions: int
    referrals: int
    avg_pages: float
    contact_messages: int
    audio_minutes: int
    max_day_pages: int
    quizzes_played: int
    quiz_correct: int
    live_games_played: int
    live_games_won: int
    shop_purchases: int
    premium_payments: int
    account_age_days: int
    perfect_months: int
    combo_days: int
    distinct_authors: int
    wisdom_best_streak: int
    book_comments: int
    long_comments_300: int
    long_comments_500: int
    pioneer_comments: int
    comment_languages: int
    comment_days: int


def compute_user_stats(user: TelegramProfile) -> Stats:
    from tgbot.models import QuizParticipant, BookQuizAnswer
    from django.db.models.functions import TruncDate as _TD

    reports = ConfirmationReport.objects.filter(user=user)
    reports_count = reports.count()
    pages = reports.filter(is_audio=False).aggregate(s=Sum("pages_read"))["s"] or 0
    avg_pages = reports.filter(is_audio=False).aggregate(a=Avg("pages_read"))["a"] or 0

    books_finished = BooksToRead.objects.filter(
        user=user, current_page__gte=F("total_pages"), total_pages__gt=0
    ).count()

    long_conclusions = (
        ConfirmationReport.objects.filter(user=user)
        .annotate(_l=Length("conclusion"))
        .filter(_l__gte=200)
        .count()
    )

    referrals = UserReferal.objects.filter(referrer=user).count()
    max_streak = _max_consecutive_days(user)
    contact_messages = getattr(user, "contact_count", 0) or 0

    audio_minutes = (
        ConfirmationReport.objects.filter(user=user, is_audio=True)
        .aggregate(s=Sum("minutes_listened"))["s"] or 0
    )

    day_rows = list(
        ConfirmationReport.objects.filter(user=user, is_audio=False)
        .annotate(_d=_TD("date"))
        .values("_d")
        .annotate(dp=Sum("pages_read"))
        .order_by("-dp")[:1]
    )
    max_day_pages = day_rows[0]["dp"] if day_rows else 0

    quizzes_played = QuizParticipant.objects.filter(user=user).count()
    quiz_correct = BookQuizAnswer.objects.filter(user=user, is_correct=True).count()

    live_games_played, live_games_won = _live_games_stats(user)
    shop_purchases = ShopPurchase.objects.filter(user=user).count()
    premium_payments = Payment.objects.filter(user=user, status="paid").count()
    account_age_days = (timezone.now() - user.created_at).days
    report_dates = list(
        ConfirmationReport.objects.filter(user=user)
        .annotate(_d=TruncDate("date")).values_list("_d", flat=True).distinct().order_by("_d")
    )
    perfect_months = _perfect_months_count(report_dates)
    combo_days = _combo_days_count(user)
    distinct_authors = (
        BooksToRead.objects.filter(
            user=user, current_page__gte=F("total_pages"), total_pages__gt=0,
            global_book__author__isnull=False,
        ).exclude(global_book__author="")
        .values_list("global_book__author", flat=True).distinct().count()
    )
    wisdom_best_streak = WisdomScore.objects.filter(user=user).aggregate(m=Max("best_streak"))["m"] or 0

    (
        book_comments, long_comments_300, long_comments_500,
        pioneer_comments, comment_languages, comment_days,
    ) = _book_comment_stats(user)

    return {
        "reports": reports_count,
        "pages": pages,
        "books_finished": books_finished,
        "max_streak": max_streak,
        "long_conclusions": long_conclusions,
        "referrals": referrals,
        "avg_pages": float(avg_pages or 0),
        "contact_messages": contact_messages,
        "audio_minutes": audio_minutes,
        "max_day_pages": max_day_pages,
        "quizzes_played": quizzes_played,
        "quiz_correct": quiz_correct,
        "live_games_played": live_games_played,
        "live_games_won": live_games_won,
        "shop_purchases": shop_purchases,
        "premium_payments": premium_payments,
        "account_age_days": account_age_days,
        "perfect_months": perfect_months,
        "combo_days": combo_days,
        "distinct_authors": distinct_authors,
        "wisdom_best_streak": wisdom_best_streak,
        "book_comments": book_comments,
        "long_comments_300": long_comments_300,
        "long_comments_500": long_comments_500,
        "pioneer_comments": pioneer_comments,
        "comment_languages": comment_languages,
        "comment_days": comment_days,
    }


def _book_comment_stats(user: TelegramProfile) -> tuple[int, int, int, int, int, int]:
    """(total comments, 300+ char comments, 500+ char comments, "pioneer"
    comments -- ones that were the first ever left on their book, distinct
    book languages commented on, distinct days commented on)."""
    rows = list(
        BookComment.objects.filter(user=user)
        .annotate(_len=Length("text"))
        .values_list("book_id", "created_at", "_len")
    )
    if not rows:
        return 0, 0, 0, 0, 0, 0

    total = len(rows)
    long_300 = sum(1 for _, _, l in rows if l >= 300)
    long_500 = sum(1 for _, _, l in rows if l >= 500)

    book_ids = [bid for bid, _, _ in rows]
    first_at_by_book = dict(
        BookComment.objects.filter(book_id__in=book_ids)
        .values("book_id").annotate(first_at=Min("created_at"))
        .values_list("book_id", "first_at")
    )
    pioneer = sum(1 for bid, created_at, _ in rows if first_at_by_book.get(bid) == created_at)

    languages = (
        BookComment.objects.filter(user=user)
        .values_list("book__language", flat=True).distinct().count()
    )
    days = (
        BookComment.objects.filter(user=user)
        .annotate(_d=TruncDate("created_at"))
        .values_list("_d", flat=True).distinct().count()
    )
    return total, long_300, long_500, pioneer, languages, days


# Reward value that separates "placed/won" from mere participation across the
# live-game score tables (all use PARTICIPATION=30 for non-placing players and
# REWARD_TIERS starting at 100 for 3rd place — see chain_game.py).
_WIN_REWARD_THRESHOLD = 100


def _live_games_stats(user: TelegramProfile) -> tuple[int, int]:
    """(games played, games won) across all 7 live-game types. Castle is a
    cooperative boss fight with no stored per-user reward, so it only counts
    toward `played` (via distinct games in CastleHit), never `won`."""
    played = 0
    won = 0
    for model in (ChainScore, FeudScore, EmojiScore, WisdomScore, DetectiveScore, SurvivalPlayer, QuizScore):
        rows = model.objects.filter(user=user).values_list("reward", flat=True)
        played += len(rows)
        won += sum(1 for r in rows if (r or 0) >= _WIN_REWARD_THRESHOLD)
    played += CastleHit.objects.filter(user=user).values("game_id").distinct().count()
    return played, won


def _perfect_months_count(dates: list) -> int:
    """Count calendar months where the user has a report on every day (through
    today, for the current month)."""
    if not dates:
        return 0
    from calendar import monthrange
    by_month = {}
    for d in dates:
        by_month.setdefault((d.year, d.month), set()).add(d.day)
    today = timezone.localdate()
    count = 0
    for (y, m), days in by_month.items():
        last_day = today.day if (y, m) == (today.year, today.month) else monthrange(y, m)[1]
        if days >= set(range(1, last_day + 1)):
            count += 1
    return count


def _combo_days_count(user: TelegramProfile) -> int:
    """Days on which the user logged both a page report and an audio report."""
    page_dates = set(
        ConfirmationReport.objects.filter(user=user, is_audio=False)
        .annotate(_d=TruncDate("date")).values_list("_d", flat=True)
    )
    audio_dates = set(
        ConfirmationReport.objects.filter(user=user, is_audio=True)
        .annotate(_d=TruncDate("date")).values_list("_d", flat=True)
    )
    return len(page_dates & audio_dates)


def _max_consecutive_days(user: TelegramProfile) -> int:
    """Longest streak (in days) of consecutive ConfirmationReport dates.
    Dates covered by a Market 'Streak muzlatish' (StreakFreezeCoverage) count
    as reported even without an actual report."""
    from tgbot.models import StreakFreezeCoverage
    dates = set(
        ConfirmationReport.objects.filter(user=user)
        .annotate(_d=TruncDate("date"))
        .values_list("_d", flat=True)
        .distinct()
    )
    dates |= set(StreakFreezeCoverage.objects.filter(user=user).values_list("date", flat=True))
    dates = sorted(dates)
    if not dates:
        return 0
    best = current = 1
    for prev, curr in zip(dates, dates[1:]):
        if curr - prev == timedelta(days=1):
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best


# ──────────────────────────────────────────────────────────────────────────
# Achievement definitions: 30 entries.
# Each: (code, emoji, title_uz, title_ru, condition: Stats -> bool)
# ──────────────────────────────────────────────────────────────────────────
def _at_least(field: str, n: int) -> Callable[[Stats], bool]:
    return lambda s: s.get(field, 0) >= n


def _all_others_unlocked(awarded_codes: set) -> Callable[[Stats], bool]:
    """Master achievement — unlocked when user has all 29 prior achievements."""
    required = {a["code"] for a in ACHIEVEMENTS_RAW}
    return lambda s: required.issubset(awarded_codes)


# Listed without "yulduz" — added at runtime so it can reference others.
# `points` = kitobcha awarded on unlock.
ACHIEVEMENTS_RAW = [
    # — Reports —
    {"code": "rep_1",   "emoji": "🐣", "title_uz": "Birinchi qadam",        "title_ru": "Первый шаг",            "cond": _at_least("reports", 1),   "points": 10},
    {"code": "rep_5",   "emoji": "🌱", "title_uz": "Yashil kurtak",          "title_ru": "Зелёный росток",        "cond": _at_least("reports", 5),   "points": 20},
    {"code": "rep_10",  "emoji": "🥉", "title_uz": "O'n hisobot",            "title_ru": "Десять отчётов",        "cond": _at_least("reports", 10),  "points": 35},
    {"code": "rep_30",  "emoji": "🥈", "title_uz": "O'ttiz hisobot",         "title_ru": "Тридцать отчётов",      "cond": _at_least("reports", 30),  "points": 75},
    {"code": "rep_100", "emoji": "🥇", "title_uz": "Yuz hisobot — donishmand", "title_ru": "Сто отчётов — мудрец","cond": _at_least("reports", 100), "points": 150},
    {"code": "rep_365", "emoji": "🏔", "title_uz": "Yil bo'yi — gigant",     "title_ru": "Целый год — гигант",    "cond": _at_least("reports", 365), "points": 400},

    # — Pages —
    {"code": "pg_50",    "emoji": "📖", "title_uz": "Boshlovchi mutolaachi",  "title_ru": "Начинающий читатель",   "cond": _at_least("pages", 50),    "points": 10},
    {"code": "pg_100",   "emoji": "📚", "title_uz": "Yuz bet",                "title_ru": "Сто страниц",           "cond": _at_least("pages", 100),   "points": 20},
    {"code": "pg_500",   "emoji": "📕", "title_uz": "Yarim ming bet",         "title_ru": "Полтысячи страниц",     "cond": _at_least("pages", 500),   "points": 50},
    {"code": "pg_1000",  "emoji": "📘", "title_uz": "Ming bet",               "title_ru": "Тысяча страниц",        "cond": _at_least("pages", 1000),  "points": 100},
    {"code": "pg_5000",  "emoji": "📗", "title_uz": "Besh ming bet",          "title_ru": "Пять тысяч страниц",    "cond": _at_least("pages", 5000),  "points": 250},
    {"code": "pg_10000", "emoji": "📙", "title_uz": "O'n ming bet — usta",    "title_ru": "Десять тысяч — мастер", "cond": _at_least("pages", 10000), "points": 500},

    # — Books finished —
    {"code": "bk_1",  "emoji": "🏁", "title_uz": "Birinchi kitob tugadi",   "title_ru": "Первая книга прочитана", "cond": _at_least("books_finished", 1),  "points": 30},
    {"code": "bk_3",  "emoji": "🏆", "title_uz": "Uch kitob",                "title_ru": "Три книги",             "cond": _at_least("books_finished", 3),  "points": 75},
    {"code": "bk_5",  "emoji": "👑", "title_uz": "Beshta kitob",             "title_ru": "Пять книг",             "cond": _at_least("books_finished", 5),  "points": 150},
    {"code": "bk_10", "emoji": "💎", "title_uz": "O'n kitob",                "title_ru": "Десять книг",           "cond": _at_least("books_finished", 10), "points": 300},
    {"code": "bk_20", "emoji": "🦄", "title_uz": "Yigirma kitob — afsona",   "title_ru": "Двадцать книг — легенда","cond": _at_least("books_finished", 20), "points": 600},

    # — Streak —
    {"code": "st_3",   "emoji": "🔥",   "title_uz": "3 kunlik streak",       "title_ru": "Серия 3 дня",          "cond": _at_least("max_streak", 3),   "points": 30},
    {"code": "st_7",   "emoji": "🔥🔥", "title_uz": "7 kunlik streak",       "title_ru": "Серия 7 дней",         "cond": _at_least("max_streak", 7),   "points": 70},
    {"code": "st_14",  "emoji": "⚡",   "title_uz": "14 kunlik streak",      "title_ru": "Серия 14 дней",        "cond": _at_least("max_streak", 14),  "points": 150},
    {"code": "st_30",  "emoji": "🔥🔥🔥", "title_uz": "30 kunlik streak",   "title_ru": "Серия 30 дней",        "cond": _at_least("max_streak", 30),  "points": 300},
    {"code": "st_100", "emoji": "🦾",   "title_uz": "100 kunlik streak — temir iroda", "title_ru": "100 дней — железная воля", "cond": _at_least("max_streak", 100), "points": 1000},

    # — Long conclusions —
    {"code": "wr_1",  "emoji": "✍️", "title_uz": "Mazmunli xulosa",          "title_ru": "Содержательный вывод",  "hint_uz": "Kamida 200 belgidan iborat mazmunli xulosa yozing.", "hint_ru": "Напишите содержательный вывод не менее 200 символов.", "cond": _at_least("long_conclusions", 1),  "points": 20},
    {"code": "wr_5",  "emoji": "📝", "title_uz": "Yozuvchi",                  "title_ru": "Писатель",              "hint_uz": "Kamida 200 belgidan iborat 5 ta xulosa yozing.", "hint_ru": "Напишите 5 выводов не менее 200 символов каждый.", "cond": _at_least("long_conclusions", 5),  "points": 75},
    {"code": "wr_20", "emoji": "🖋", "title_uz": "Mualif — yigirma xulosa",   "title_ru": "Автор — двадцать выводов","hint_uz": "Kamida 200 belgidan iborat 20 ta xulosa yozing.", "hint_ru": "Напишите 20 выводов не менее 200 символов каждый.", "cond": _at_least("long_conclusions", 20), "points": 250},

    # — Referrals —
    {"code": "rf_1",  "emoji": "👥", "title_uz": "Birinchi do'st",           "title_ru": "Первый друг",           "cond": _at_least("referrals", 1),  "points": 50},
    {"code": "rf_5",  "emoji": "🤝", "title_uz": "Beshta referral",          "title_ru": "Пять рефералов",        "cond": _at_least("referrals", 5),  "points": 200},
    {"code": "rf_10", "emoji": "🌍", "title_uz": "O'n referral — elchi",     "title_ru": "Десять рефералов — посол","cond": _at_least("referrals", 10), "points": 500},

    # — Speed —
    {"code": "spd_30",  "emoji": "🚀", "title_uz": "Tezkor o'qish (30+ bet/kun)",  "title_ru": "Скоростное чтение (30+ стр)",  "cond": lambda s: s.get("avg_pages", 0) >= 30  and s.get("reports", 0) >= 5, "points": 100},
    {"code": "spd_50",  "emoji": "⚡", "title_uz": "Tez mutolaaachi (50+ bet/kun)", "title_ru": "Быстрый читатель (50+ стр)",   "cond": lambda s: s.get("avg_pages", 0) >= 50  and s.get("reports", 0) >= 5, "points": 200},
    {"code": "spd_100", "emoji": "🛸", "title_uz": "Raketa (100+ bet/kun)",         "title_ru": "Ракета (100+ стр/день)",       "cond": lambda s: s.get("avg_pages", 0) >= 100 and s.get("reports", 0) >= 5, "points": 500},

    # — Contact admin —
    {"code": "ca_1",  "emoji": "💬",   "title_uz": "Birinchi murojaat",          "title_ru": "Первое обращение",          "hint_uz": "«📞 Admin bilan bog'lanish» orqali murojaat yuboring.", "hint_ru": "Напишите администратору через «📞 Admin bilan bog'lanish».", "cond": _at_least("contact_messages", 1),  "points": 15},
    {"code": "ca_3",  "emoji": "📞",   "title_uz": "Uch murojaat",               "title_ru": "Три обращения",             "hint_uz": "Admin bilan bog'lanish orqali 3 marta murojaat yuboring.", "hint_ru": "Напишите администратору 3 раза.", "cond": _at_least("contact_messages", 3),  "points": 35},
    {"code": "ca_5",  "emoji": "📬",   "title_uz": "Faol muloqot",               "title_ru": "Активное общение",          "hint_uz": "Admin bilan bog'lanish orqali 5 marta murojaat yuboring.", "hint_ru": "Напишите администратору 5 раз.", "cond": _at_least("contact_messages", 5),  "points": 60},
    {"code": "ca_10", "emoji": "🗨",   "title_uz": "O'n murojaat",               "title_ru": "Десять обращений",          "hint_uz": "Admin bilan bog'lanish orqali 10 marta murojaat yuboring.", "hint_ru": "Напишите администратору 10 раз.", "cond": _at_least("contact_messages", 10), "points": 120},
    {"code": "ca_20", "emoji": "🔊",   "title_uz": "Aktiv muloqotchi",           "title_ru": "Активный собеседник",       "hint_uz": "Admin bilan bog'lanish orqali 20 marta murojaat yuboring.", "hint_ru": "Напишите администратору 20 раз.", "cond": _at_least("contact_messages", 20), "points": 250},
    {"code": "ca_30", "emoji": "🤝",   "title_uz": "Bot do'sti — 30 murojaat",   "title_ru": "Друг бота — 30 обращений", "hint_uz": "Admin bilan bog'lanish orqali 30 marta murojaat yuboring.", "hint_ru": "Напишите администратору 30 раз.", "cond": _at_least("contact_messages", 30), "points": 400},

    # ── NEW ACHIEVEMENTS ──────────────────────────────────────────────────────

    # — Extra report milestones —
    {"code": "rep_50",  "emoji": "🌿", "title_uz": "Ellik hisobot",              "title_ru": "Пятьдесят отчётов",         "cond": _at_least("reports", 50),  "points": 100},
    {"code": "rep_200", "emoji": "🔱", "title_uz": "Ikki yuz hisobot",           "title_ru": "Двести отчётов",            "cond": _at_least("reports", 200), "points": 300},
    {"code": "rep_500", "emoji": "🌋", "title_uz": "Besh yuz hisobot — vulqon",  "title_ru": "Пятьсот отчётов — вулкан", "cond": _at_least("reports", 500), "points": 750},

    # — Extra page milestones —
    {"code": "pg_20",    "emoji": "🌾", "title_uz": "Yigirma bet",                "title_ru": "Двадцать страниц",          "cond": _at_least("pages", 20),    "points": 5},
    {"code": "pg_20000", "emoji": "🏛", "title_uz": "Yigirma ming bet — titan",   "title_ru": "Двадцать тысяч — титан",   "cond": _at_least("pages", 20000), "points": 1000},
    {"code": "pg_50000", "emoji": "👑", "title_uz": "Ellik ming bet — afsonaviy", "title_ru": "Пятьдесят тысяч — легенда","cond": _at_least("pages", 50000), "points": 2500},

    # — Extra streak milestones —
    {"code": "st_21",  "emoji": "🌈",   "title_uz": "21 kun — odat shakllandi!",  "title_ru": "21 день — привычка!",      "cond": _at_least("max_streak", 21),  "points": 200},
    {"code": "st_50",  "emoji": "💫",   "title_uz": "50 kunlik streak",           "title_ru": "Серия 50 дней",            "cond": _at_least("max_streak", 50),  "points": 500},
    {"code": "st_200", "emoji": "🪐",   "title_uz": "200 kunlik streak — titan",  "title_ru": "Серия 200 дней — титан",   "cond": _at_least("max_streak", 200), "points": 2000},
    {"code": "st_365", "emoji": "🌞",   "title_uz": "Bir yillik streak — quyosh", "title_ru": "365 дней — солнце",        "cond": _at_least("max_streak", 365), "points": 5000},

    # — Extra book milestones —
    {"code": "bk_7",  "emoji": "🎯", "title_uz": "Yetti kitob",                  "title_ru": "Семь книг",                "cond": _at_least("books_finished", 7),  "points": 175},
    {"code": "bk_15", "emoji": "🌟", "title_uz": "O'n besh kitob",               "title_ru": "Пятнадцать книг",          "cond": _at_least("books_finished", 15), "points": 400},
    {"code": "bk_30", "emoji": "🦅", "title_uz": "O'ttiz kitob — lochin",        "title_ru": "Тридцать книг — орёл",     "cond": _at_least("books_finished", 30), "points": 1000},
    {"code": "bk_50", "emoji": "🧿", "title_uz": "Ellik kitob — afsonaviy",      "title_ru": "Пятьдесят книг — легенда", "cond": _at_least("books_finished", 50), "points": 2000},

    # — Extra long conclusion milestones —
    {"code": "wr_10",  "emoji": "🖊",  "title_uz": "O'n xulosa",                 "title_ru": "Десять выводов",            "hint_uz": "Kamida 200 belgidan iborat 10 ta xulosa yozing.", "hint_ru": "Напишите 10 выводов не менее 200 символов каждый.", "cond": _at_least("long_conclusions", 10),  "points": 150},
    {"code": "wr_50",  "emoji": "📜",  "title_uz": "Ellik xulosa — tarixchi",    "title_ru": "Пятьдесят выводов",         "hint_uz": "Kamida 200 belgidan iborat 50 ta xulosa yozing.", "hint_ru": "Напишите 50 выводов не менее 200 символов каждый.", "cond": _at_least("long_conclusions", 50),  "points": 500},
    {"code": "wr_100", "emoji": "🏺",  "title_uz": "Yuz xulosa — faylasuf",      "title_ru": "Сто выводов — философ",     "hint_uz": "Kamida 200 belgidan iborat 100 ta xulosa yozing.", "hint_ru": "Напишите 100 выводов не менее 200 символов каждый.", "cond": _at_least("long_conclusions", 100), "points": 1000},

    # — Extra referral milestones —
    {"code": "rf_3",   "emoji": "🌱", "title_uz": "Uch do'st",                   "title_ru": "Три друга",                 "cond": _at_least("referrals", 3),   "points": 100},
    {"code": "rf_20",  "emoji": "🌳", "title_uz": "Yigirma referral — daraxt",   "title_ru": "Двадцать рефералов — дерево","cond": _at_least("referrals", 20),  "points": 700},
    {"code": "rf_50",  "emoji": "🌲", "title_uz": "Ellik referral — o'rmon",     "title_ru": "Пятьдесят рефералов",       "cond": _at_least("referrals", 50),  "points": 1500},
    {"code": "rf_100", "emoji": "🏙", "title_uz": "Yuz referral — shaharlik",    "title_ru": "Сто рефералов — город",     "cond": _at_least("referrals", 100), "points": 3000},

    # — Audiobook milestones —
    {"code": "au_1h",  "emoji": "🎧", "title_uz": "1 soat audio",                "title_ru": "1 час аудио",               "cond": _at_least("audio_minutes", 60),   "points": 30},
    {"code": "au_10h", "emoji": "🎵", "title_uz": "10 soat audio",               "title_ru": "10 часов аудио",            "cond": _at_least("audio_minutes", 600),  "points": 150},
    {"code": "au_50h", "emoji": "🎼", "title_uz": "50 soat audio — bastankor",   "title_ru": "50 часов аудио — маэстро",  "cond": _at_least("audio_minutes", 3000), "points": 600},

    # — Single-day marathon —
    {"code": "day_100", "emoji": "🏃", "title_uz": "Kunlik marafon (100+ bet)",  "title_ru": "Дневной марафон (100+ стр)", "cond": _at_least("max_day_pages", 100), "points": 250},

    # — Quiz milestones —
    {"code": "qz_1",  "emoji": "🧩", "title_uz": "Birinchi quiz",               "title_ru": "Первый квиз",               "hint_uz": "«📝 Kitob Quiz» bo'limida (yakka yoki guruhda) quiz o'ynang.", "hint_ru": "Сыграйте в квиз в разделе «📝 Kitob Quiz».", "cond": _at_least("quizzes_played", 1),  "points": 25},
    {"code": "qz_5",  "emoji": "🎮", "title_uz": "Beshta quiz",                 "title_ru": "Пять квизов",               "hint_uz": "«📝 Kitob Quiz» bo'limida 5 marta quiz o'ynang.", "hint_ru": "Сыграйте в квиз в разделе «📝 Kitob Quiz» 5 раз.", "cond": _at_least("quizzes_played", 5),  "points": 100},
    {"code": "qz_10", "emoji": "🏆", "title_uz": "O'n quiz — chempion",         "title_ru": "Десять квизов — чемпион",   "hint_uz": "«📝 Kitob Quiz» bo'limida 10 marta quiz o'ynang.", "hint_ru": "Сыграйте в квиз в разделе «📝 Kitob Quiz» 10 раз.", "cond": _at_least("quizzes_played", 10), "points": 250},

    # — Viktorina correct-answer milestones —
    {"code": "vq_1",   "emoji": "🧩", "title_uz": "Viktorinachi",                "title_ru": "Викторинщик",               "hint_uz": "Kunlik «Kitob Viktorina»da (guruhda, kuniga 2 marta) to'g'ri javob bering.", "hint_ru": "Ответьте правильно в ежедневной «Kitob Viktorina» (в группе).", "cond": _at_least("quiz_correct", 1),   "points": 30},
    {"code": "vq_10",  "emoji": "🔍", "title_uz": "Iqtibos izlovchi",            "title_ru": "Искатель цитат",            "hint_uz": "Kunlik «Kitob Viktorina»da 10 marta to'g'ri javob bering.", "hint_ru": "Ответьте правильно в «Kitob Viktorina» 10 раз.", "cond": _at_least("quiz_correct", 10),  "points": 100},
    {"code": "vq_25",  "emoji": "📚", "title_uz": "Kitob bilimdon",              "title_ru": "Книжный знаток",            "hint_uz": "Kunlik «Kitob Viktorina»da 25 marta to'g'ri javob bering.", "hint_ru": "Ответьте правильно в «Kitob Viktorina» 25 раз.", "cond": _at_least("quiz_correct", 25),  "points": 250},
    {"code": "vq_50",  "emoji": "🏆", "title_uz": "Viktorina chempioni",         "title_ru": "Чемпион викторины",         "hint_uz": "Kunlik «Kitob Viktorina»da 50 marta to'g'ri javob bering.", "hint_ru": "Ответьте правильно в «Kitob Viktorina» 50 раз.", "cond": _at_least("quiz_correct", 50),  "points": 500},
    {"code": "vq_100", "emoji": "🌟", "title_uz": "Viktorina ustasi — 100 ta",   "title_ru": "Мастер викторины — 100",    "hint_uz": "Kunlik «Kitob Viktorina»da 100 marta to'g'ri javob bering.", "hint_ru": "Ответьте правильно в «Kitob Viktorina» 100 раз.", "cond": _at_least("quiz_correct", 100), "points": 1000},

    # ── NEW ACHIEVEMENTS ROUND 2 — 30 entries, new behavioral dimensions ──────

    # — Live games participation —
    {"code": "lg_1",   "emoji": "🎲", "title_uz": "Birinchi jonli o'yin",          "title_ru": "Первая live-игра",           "hint_uz": "Har kuni 10:00/22:00dagi jonli o'yinlardan (Zanjiri, Ko'pchilik va h.k.) biriga qatnashing.", "hint_ru": "Поучаствуйте в одной из live-игр (10:00/22:00).", "cond": _at_least("live_games_played", 1),   "points": 20},
    {"code": "lg_10",  "emoji": "🕹", "title_uz": "O'n jonli o'yin",               "title_ru": "Десять live-игр",            "hint_uz": "Jonli o'yinlarda jami 10 marta qatnashing (istalgan turdagi).", "hint_ru": "Поучаствуйте в live-играх 10 раз.", "cond": _at_least("live_games_played", 10),  "points": 100},
    {"code": "lg_50",  "emoji": "🎰", "title_uz": "Ellik jonli o'yin — faol o'yinchi", "title_ru": "Пятьдесят live-игр",     "hint_uz": "Jonli o'yinlarda jami 50 marta qatnashing.", "hint_ru": "Поучаствуйте в live-играх 50 раз.", "cond": _at_least("live_games_played", 50),  "points": 350},
    {"code": "lg_200", "emoji": "🎳", "title_uz": "Ikki yuz jonli o'yin — afsonaviy o'yinchi", "title_ru": "Двести live-игр — легенда", "hint_uz": "Jonli o'yinlarda jami 200 marta qatnashing.", "hint_ru": "Поучаствуйте в live-играх 200 раз.", "cond": _at_least("live_games_played", 200), "points": 800},

    # — Live game wins (top-3 / jackpot reward, not mere participation) —
    {"code": "lgw_1",  "emoji": "🥉", "title_uz": "Birinchi g'alaba",              "title_ru": "Первая победа",              "hint_uz": "Jonli o'yinda birinchi 3 o'rin yoki katta mukofot (100+ Kitobcha) yutib oling.", "hint_ru": "Займите топ-3 или выиграйте крупный приз (100+ Kitobcha) в live-игре.", "cond": _at_least("live_games_won", 1),   "points": 50},
    {"code": "lgw_5",  "emoji": "🥈", "title_uz": "Besh g'alaba",                  "title_ru": "Пять побед",                 "hint_uz": "Jonli o'yinlarda 5 marta g'olib bo'ling.", "hint_ru": "Победите в live-играх 5 раз.", "cond": _at_least("live_games_won", 5),   "points": 200},
    {"code": "lgw_20", "emoji": "🥇", "title_uz": "Yigirma g'alaba — chempion",    "title_ru": "Двадцать побед — чемпион",   "hint_uz": "Jonli o'yinlarda 20 marta g'olib bo'ling.", "hint_ru": "Победите в live-играх 20 раз.", "cond": _at_least("live_games_won", 20),  "points": 700},
    {"code": "lgw_50", "emoji": "👑", "title_uz": "Ellik g'alaba — yengilmas",     "title_ru": "Пятьдесят побед — непобедим","hint_uz": "Jonli o'yinlarda 50 marta g'olib bo'ling.", "hint_ru": "Победите в live-играх 50 раз.", "cond": _at_least("live_games_won", 50),  "points": 1500},

    # — Shop purchases —
    {"code": "shop_1",  "emoji": "🛍", "title_uz": "Birinchi xarid",               "title_ru": "Первая покупка",             "hint_uz": "🏪 Do'kondan biror mahsulot sotib oling.", "hint_ru": "Совершите покупку в магазине 🏪.", "cond": _at_least("shop_purchases", 1),  "points": 20},
    {"code": "shop_5",  "emoji": "🛒", "title_uz": "Besh xarid — doimiy mijoz",    "title_ru": "Пять покупок — постоянный клиент", "hint_uz": "🏪 Do'kondan 5 marta xarid qiling.", "hint_ru": "Совершите 5 покупок в магазине.", "cond": _at_least("shop_purchases", 5),  "points": 150},
    {"code": "shop_15", "emoji": "🏪", "title_uz": "O'n besh xarid — VIP mijoz",   "title_ru": "Пятнадцать покупок — VIP",   "hint_uz": "🏪 Do'kondan 15 marta xarid qiling.", "hint_ru": "Совершите 15 покупок в магазине.", "cond": _at_least("shop_purchases", 15), "points": 500},

    # — Premium loyalty (count of paid Payment rows) —
    {"code": "prem_1", "emoji": "⭐", "title_uz": "Premium a'zo",                  "title_ru": "Premium-участник",           "hint_uz": "💎 Premium obuna sotib oling.", "hint_ru": "Оформите 💎 Premium подписку.", "cond": _at_least("premium_payments", 1), "points": 100},
    {"code": "prem_3", "emoji": "🌠", "title_uz": "Sodiq Premium a'zo",            "title_ru": "Верный Premium-участник",    "hint_uz": "💎 Premium obunani jami 3 marta sotib oling/uzaytiring.", "hint_ru": "Оформите/продлите 💎 Premium 3 раза.", "cond": _at_least("premium_payments", 3), "points": 400},
    {"code": "prem_6", "emoji": "💫", "title_uz": "Premium faxriysi",              "title_ru": "Ветеран Premium",            "hint_uz": "💎 Premium obunani jami 6 marta sotib oling/uzaytiring.", "hint_ru": "Оформите/продлите 💎 Premium 6 раз.", "cond": _at_least("premium_payments", 6), "points": 900},

    # — Anniversary —
    {"code": "anniv_1", "emoji": "🎂", "title_uz": "Bir yillik a'zo",              "title_ru": "Год с нами",                 "cond": _at_least("account_age_days", 365), "points": 200},
    {"code": "anniv_2", "emoji": "🎉", "title_uz": "Ikki yillik a'zo — faxriy kitobxon", "title_ru": "Два года — почётный читатель", "cond": _at_least("account_age_days", 730), "points": 500},

    # — Perfect month (report every single day of a calendar month) —
    {"code": "pm_1", "emoji": "🗓", "title_uz": "Mukammal oy",                    "title_ru": "Идеальный месяц",            "hint_uz": "Bir oyning HAR BIR kunida hisobot yuboring (bironta kun ham o'tkazib yubormang).", "hint_ru": "Отправляйте отчёт КАЖДЫЙ день одного месяца без пропусков.", "cond": _at_least("perfect_months", 1), "points": 300},
    {"code": "pm_3", "emoji": "📅", "title_uz": "Uch mukammal oy — barqaror",     "title_ru": "Три идеальных месяца",       "hint_uz": "3 ta oyning har birida, har kuni hisobot yuboring.", "hint_ru": "Отправляйте отчёт каждый день в течение 3 месяцев.", "cond": _at_least("perfect_months", 3), "points": 800},

    # — Combo days: both a page report and an audio report the same day —
    {"code": "combo_5",  "emoji": "🎧", "title_uz": "Ikki tomonlama kitobxon",     "title_ru": "Читатель на два фронта",     "hint_uz": "Bitta kunda HAM bet o'qib, HAM audiokitob eshitib, ikkalasidan ham hisobot yuboring — buni 5 marta qiling.", "hint_ru": "В один день отправьте и отчёт о страницах, и об аудио — 5 раз.", "cond": _at_least("combo_days", 5),  "points": 80},
    {"code": "combo_20", "emoji": "🎼", "title_uz": "Gibrid o'quvchi ustasi",      "title_ru": "Мастер гибридного чтения",   "hint_uz": "Bitta kunda ham bet, ham audio hisobot yuborishni 20 marta qiling.", "hint_ru": "Совмещайте отчёт о страницах и аудио в один день — 20 раз.", "cond": _at_least("combo_days", 20), "points": 300},
    {"code": "combo_50", "emoji": "🎹", "title_uz": "Yuz foiz gibrid — afsonaviy", "title_ru": "Гибрид на все сто — легенда","hint_uz": "Bitta kunda ham bet, ham audio hisobot yuborishni 50 marta qiling.", "hint_ru": "Совмещайте отчёт о страницах и аудио в один день — 50 раз.", "cond": _at_least("combo_days", 50), "points": 900},

    # — Distinct authors among finished books (reading breadth) —
    {"code": "auth_5",  "emoji": "📗", "title_uz": "Besh muallif",                "title_ru": "Пять авторов",               "hint_uz": "Turli 5 ta mualliflardan kitob tugating (kutubxonadagi kitoblar asosida hisoblanadi).", "hint_ru": "Завершите книги 5 разных авторов (из библиотеки).", "cond": _at_least("distinct_authors", 5),  "points": 60},
    {"code": "auth_15", "emoji": "📘", "title_uz": "O'n besh muallif — ufqi keng", "title_ru": "Пятнадцать авторов",        "hint_uz": "Turli 15 ta mualliflardan kitob tugating.", "hint_ru": "Завершите книги 15 разных авторов.", "cond": _at_least("distinct_authors", 15), "points": 250},
    {"code": "auth_30", "emoji": "📙", "title_uz": "O'ttiz muallif — bilimdon",   "title_ru": "Тридцать авторов — знаток",  "hint_uz": "Turli 30 ta mualliflardan kitob tugating.", "hint_ru": "Завершите книги 30 разных авторов.", "cond": _at_least("distinct_authors", 30), "points": 600},
    {"code": "auth_50", "emoji": "📕", "title_uz": "Ellik muallif — universal kitobxon", "title_ru": "Пятьдесят авторов — универсал", "hint_uz": "Turli 50 ta mualliflardan kitob tugating.", "hint_ru": "Завершите книги 50 разных авторов.", "cond": _at_least("distinct_authors", 50), "points": 1200},

    # — Comeback: a long silent gap followed by a fresh streak —
    {"code": "cmb_1", "emoji": "🌅", "title_uz": "Qaytgan qahramon",              "title_ru": "Вернувшийся герой",          "hint_uz": "Kamida 14 kun uzilishdan so'ng, qayta 7 kun ketma-ket hisobot bering.", "hint_ru": "После перерыва от 14 дней читайте 7 дней подряд.", "cond": lambda s: s.get("comeback", False), "points": 150},
    {"code": "cmb_2", "emoji": "🔥", "title_uz": "Feniks — qayta tug'ilish",      "title_ru": "Феникс — возрождение",       "hint_uz": "Kamida 30 kun uzilishdan so'ng, qayta 14 kun ketma-ket hisobot bering.", "hint_ru": "После перерыва от 30 дней читайте 14 дней подряд.", "cond": lambda s: s.get("phoenix", False),  "points": 400},

    # — Hikmat Xazinasi consecutive-correct streak (personal best) —
    {"code": "wst_3",  "emoji": "🧠", "title_uz": "Hikmat seriyasi — 3",          "title_ru": "Серия мудрости — 3",         "hint_uz": "☪️ Hikmat Xazinasi jonli o'yinida ketma-ket 3 marta to'g'ri javob bering.", "hint_ru": "В игре «Hikmat Xazinasi» ответьте правильно 3 раза подряд.", "cond": _at_least("wisdom_best_streak", 3),  "points": 50},
    {"code": "wst_10", "emoji": "🦉", "title_uz": "Hikmat seriyasi — 10, dono",   "title_ru": "Серия мудрости — 10",        "hint_uz": "☪️ Hikmat Xazinasi jonli o'yinida ketma-ket 10 marta to'g'ri javob bering.", "hint_ru": "В игре «Hikmat Xazinasi» ответьте правильно 10 раз подряд.", "cond": _at_least("wisdom_best_streak", 10), "points": 300},
    {"code": "wst_20", "emoji": "🔮", "title_uz": "Hikmat seriyasi — 20, ustoz",  "title_ru": "Серия мудрости — 20",        "hint_uz": "☪️ Hikmat Xazinasi jonli o'yinida ketma-ket 20 marta to'g'ri javob bering.", "hint_ru": "В игре «Hikmat Xazinasi» ответьте правильно 20 раз подряд.", "cond": _at_least("wisdom_best_streak", 20), "points": 900},

    # — Book comments (kutubxona) — ladder + quality/pioneer/diversity —
    {"code": "cm_1",  "emoji": "💬", "title_uz": "Birinchi fikr",                 "title_ru": "Первый отзыв",               "hint_uz": "Kutubxonadagi istalgan kitobga izoh qoldiring.", "hint_ru": "Оставьте комментарий к любой книге в библиотеке.", "cond": _at_least("book_comments", 1),  "points": 15},
    {"code": "cm_3",  "emoji": "🗨",  "title_uz": "Uch fikr",                      "title_ru": "Три отзыва",                 "hint_uz": "Jami 3 ta kitobga izoh qoldiring.", "hint_ru": "Оставьте комментарии к 3 книгам.", "cond": _at_least("book_comments", 3),  "points": 30},
    {"code": "cm_5",  "emoji": "📣", "title_uz": "Besh fikr",                     "title_ru": "Пять отзывов",               "hint_uz": "Jami 5 ta kitobga izoh qoldiring.", "hint_ru": "Оставьте комментарии к 5 книгам.", "cond": _at_least("book_comments", 5),  "points": 50},
    {"code": "cm_10", "emoji": "📢", "title_uz": "O'n fikr — faol sharhlovchi",   "title_ru": "Десять отзывов — активный рецензент", "hint_uz": "Jami 10 ta kitobga izoh qoldiring.", "hint_ru": "Оставьте комментарии к 10 книгам.", "cond": _at_least("book_comments", 10), "points": 100},
    {"code": "cm_25", "emoji": "🏛", "title_uz": "Yigirma besh fikr — kutubxona jonkuyari", "title_ru": "Двадцать пять — душа библиотеки", "hint_uz": "Jami 25 ta kitobga izoh qoldiring.", "hint_ru": "Оставьте комментарии к 25 книгам.", "cond": _at_least("book_comments", 25), "points": 250},
    {"code": "cm_50", "emoji": "🏆", "title_uz": "Ellik fikr — kutubxona faoli",  "title_ru": "Пятьдесят отзывов — активист библиотеки", "hint_uz": "Jami 50 ta kitobga izoh qoldiring.", "hint_ru": "Оставьте комментарии к 50 книгам.", "cond": _at_least("book_comments", 50), "points": 500},

    {"code": "cml_1", "emoji": "✍️", "title_uz": "Mulohazakor",                  "title_ru": "Вдумчивый читатель",         "hint_uz": "Kamida 300 belgidan iborat chuqur izoh yozing.", "hint_ru": "Напишите содержательный комментарий не менее 300 символов.", "cond": _at_least("long_comments_300", 1), "points": 25},
    {"code": "cml_5", "emoji": "📜", "title_uz": "Chuqur mutafakkir",             "title_ru": "Глубокий мыслитель",         "hint_uz": "500+ belgidan iborat 5 ta izoh yozing.", "hint_ru": "Напишите 5 комментариев не менее 500 символов каждый.", "cond": _at_least("long_comments_500", 5), "points": 150},

    {"code": "cmpi_1", "emoji": "🧭", "title_uz": "Birinchi kashfiyotchi",        "title_ru": "Первый первопроходец",       "hint_uz": "Hech kim izoh qoldirmagan kitobga BIRINCHI bo'lib izoh yozing.", "hint_ru": "Оставьте ПЕРВЫЙ комментарий к книге, у которой ещё не было отзывов.", "cond": _at_least("pioneer_comments", 1), "points": 40},
    {"code": "cmpi_5", "emoji": "🗺",  "title_uz": "Beshta kashfiyot — yo'l ochuvchi", "title_ru": "Пять открытий — первопроходец", "hint_uz": "5 xil kitobga birinchi bo'lib izoh yozing.", "hint_ru": "Оставьте первый комментарий к 5 разным книгам.", "cond": _at_least("pioneer_comments", 5), "points": 200},

    {"code": "cmlang_3", "emoji": "🌐", "title_uz": "Ko'p tilli sharhlovchi",     "title_ru": "Многоязычный рецензент",     "hint_uz": "3 xil tildagi kitoblarga izoh qoldiring.", "hint_ru": "Оставьте комментарии к книгам на 3 разных языках.", "cond": _at_least("comment_languages", 3), "points": 80},
    {"code": "cmday_10", "emoji": "📆", "title_uz": "Kundalik fikr ustasi",       "title_ru": "Мастер ежедневных отзывов",  "hint_uz": "10 xil kunda izoh qoldiring (bir kunda bir nechtasi bitta kun sifatida hisoblanadi).", "hint_ru": "Оставляйте комментарии в 10 разных дней.", "cond": _at_least("comment_days", 10), "points": 150},
]


# Master achievement — references the codes above.
def _master_cond(awarded_codes: set):
    required = {a["code"] for a in ACHIEVEMENTS_RAW}
    def _check(stats: Stats) -> bool:
        return required.issubset(awarded_codes)
    return _check


ACHIEVEMENTS = ACHIEVEMENTS_RAW + [
    {
        "code": "yulduz",
        "emoji": "⭐",
        "title_uz": "Yulduz — barcha yutuqlar",
        "title_ru": "Звезда — все достижения",
        "cond": None,  # filled per-call (depends on awarded_codes)
        "points": 2000,
    }
]


def find_achievement(code: str) -> Optional[dict]:
    for a in ACHIEVEMENTS:
        if a["code"] == code:
            return a
    return None


# ──────────────────────────────────────────────────────────────────────────
# Award + Tabriklash broadcast.
# ──────────────────────────────────────────────────────────────────────────
def award_new_achievements(user: TelegramProfile) -> List[dict]:
    """Evaluate all achievements; create UserAchievement rows for newly
    unlocked ones; return the list of newly awarded achievement dicts."""
    if not user:
        return []

    stats = compute_user_stats(user)
    already_awarded_codes = set(
        UserAchievement.objects.filter(user=user).values_list("code", flat=True)
    )

    newly = []
    for ach in ACHIEVEMENTS_RAW:
        if ach["code"] in already_awarded_codes:
            continue
        if ach["cond"](stats):
            obj, created = UserAchievement.objects.get_or_create(
                user=user, code=ach["code"]
            )
            if created:
                newly.append(ach)
                already_awarded_codes.add(ach["code"])

    # Master achievement: requires all others.
    if "yulduz" not in already_awarded_codes:
        required = {a["code"] for a in ACHIEVEMENTS_RAW}
        if required.issubset(already_awarded_codes):
            obj, created = UserAchievement.objects.get_or_create(
                user=user, code="yulduz"
            )
            if created:
                newly.append(find_achievement("yulduz"))

    return newly


def list_user_achievements(user: TelegramProfile):
    """All achievements with awarded/locked flag, sorted by ACHIEVEMENTS order."""
    awarded_codes = set(
        UserAchievement.objects.filter(user=user).values_list("code", flat=True)
    )
    out = []
    for ach in ACHIEVEMENTS:
        out.append({
            "code": ach["code"],
            "emoji": ach["emoji"],
            "title_uz": ach["title_uz"],
            "title_ru": ach["title_ru"],
            "hint_uz": ach.get("hint_uz"),
            "hint_ru": ach.get("hint_ru"),
            "unlocked": ach["code"] in awarded_codes,
        })
    return out
