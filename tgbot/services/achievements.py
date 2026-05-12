"""
30-achievement system. Achievement metadata lives here in code (not DB).

Workflow:
    1. After each ConfirmationReport save, call `award_new_achievements(user)`.
    2. It computes `compute_user_stats(user)`, evaluates each ACHIEVEMENT's
       condition, creates a UserAchievement row for any newly-unlocked code,
       and queues a Tabriklash broadcast for each.
"""
from datetime import timedelta
from typing import Callable, List, Optional, TypedDict

from django.db.models import Count, Sum, Avg, F
from django.db.models.functions import Length, TruncDate
from django.utils import timezone

from tgbot.models import (
    TelegramProfile, ConfirmationReport, BooksToRead, UserAchievement,
    UserReferal,
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


def compute_user_stats(user: TelegramProfile) -> Stats:
    reports = ConfirmationReport.objects.filter(user=user)
    reports_count = reports.count()
    pages = reports.aggregate(s=Sum("pages_read"))["s"] or 0
    avg_pages = reports.aggregate(a=Avg("pages_read"))["a"] or 0

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

    return {
        "reports": reports_count,
        "pages": pages,
        "books_finished": books_finished,
        "max_streak": max_streak,
        "long_conclusions": long_conclusions,
        "referrals": referrals,
        "avg_pages": float(avg_pages or 0),
        "contact_messages": contact_messages,
    }


def _max_consecutive_days(user: TelegramProfile) -> int:
    """Longest streak (in days) of consecutive ConfirmationReport dates."""
    dates = list(
        ConfirmationReport.objects.filter(user=user)
        .annotate(_d=TruncDate("date"))
        .values_list("_d", flat=True)
        .distinct()
        .order_by("_d")
    )
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
    {"code": "wr_1",  "emoji": "✍️", "title_uz": "Mazmunli xulosa",          "title_ru": "Содержательный вывод",  "cond": _at_least("long_conclusions", 1),  "points": 20},
    {"code": "wr_5",  "emoji": "📝", "title_uz": "Yozuvchi",                  "title_ru": "Писатель",              "cond": _at_least("long_conclusions", 5),  "points": 75},
    {"code": "wr_20", "emoji": "🖋", "title_uz": "Mualif — yigirma xulosa",   "title_ru": "Автор — двадцать выводов","cond": _at_least("long_conclusions", 20), "points": 250},

    # — Referrals —
    {"code": "rf_1",  "emoji": "👥", "title_uz": "Birinchi do'st",           "title_ru": "Первый друг",           "cond": _at_least("referrals", 1),  "points": 50},
    {"code": "rf_5",  "emoji": "🤝", "title_uz": "Beshta referral",          "title_ru": "Пять рефералов",        "cond": _at_least("referrals", 5),  "points": 200},
    {"code": "rf_10", "emoji": "🌍", "title_uz": "O'n referral — elchi",     "title_ru": "Десять рефералов — посол","cond": _at_least("referrals", 10), "points": 500},

    # — Speed —
    {"code": "spd_30", "emoji": "🚀", "title_uz": "Tezkor o'qish (30+ bet/kun)", "title_ru": "Скоростное чтение (30+ стр)", "cond": lambda s: s.get("avg_pages", 0) >= 30 and s.get("reports", 0) >= 5, "points": 100},

    # — Contact admin —
    {"code": "ca_1",  "emoji": "💬",   "title_uz": "Birinchi murojaat",          "title_ru": "Первое обращение",          "cond": _at_least("contact_messages", 1),  "points": 15},
    {"code": "ca_3",  "emoji": "📞",   "title_uz": "Uch murojaat",               "title_ru": "Три обращения",             "cond": _at_least("contact_messages", 3),  "points": 35},
    {"code": "ca_5",  "emoji": "📬",   "title_uz": "Faol muloqot",               "title_ru": "Активное общение",          "cond": _at_least("contact_messages", 5),  "points": 60},
    {"code": "ca_10", "emoji": "🗨",   "title_uz": "O'n murojaat",               "title_ru": "Десять обращений",          "cond": _at_least("contact_messages", 10), "points": 120},
    {"code": "ca_20", "emoji": "🔊",   "title_uz": "Aktiv muloqotchi",           "title_ru": "Активный собеседник",       "cond": _at_least("contact_messages", 20), "points": 250},
    {"code": "ca_30", "emoji": "🤝",   "title_uz": "Bot do'sti — 30 murojaat",   "title_ru": "Друг бота — 30 обращений", "cond": _at_least("contact_messages", 30), "points": 400},
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
            "unlocked": ach["code"] in awarded_codes,
        })
    return out
