"""Ways to use Kitobcha (owner, 2026-11-01). Every one is a sink for the
Kitobcha readers have piled up, and every move is a KitobchaLedger row (plus
a WalletTransaction when so'm moves):

- transfer   members may give Kitobcha to any reader (a daily cap);
- mentor     pay a newcomer's report days: MENTOR_DAY_PRICE Kitobcha becomes
             DAY_FEE so'm in their wallet; earns the 🎓 Ustoz badge;
- streak gift  readers whose streak is about to burn and who cannot pay
             today are offered to random active readers, who may gift them
             1-3 days of streak freeze (the Market token);
- frames     a decoration around one's group report posts, for FRAME_DAYS;
- honour wall  a permanent place on the "Hurmatli kitobxonlar devori";
- to pot     Kitobcha -> Kitob hamyonchasi at 1:1, monthly cap.

All prices live here, at the top.
"""
import datetime
import random

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

TRANSFER_MIN = 100
TRANSFER_DAILY_CAP = 10000
MENTOR_DAY_PRICE = 1000          # Kitobcha per report day (= DAY_FEE so'm)
MENTOR_NEWCOMER_DAYS = 30        # a reader who joined within this many days
MENTOR_DAY_OPTIONS = (1, 3, 7)
STREAK_GIFT_DAY_PRICE = 750      # the Market's streak freeze
STREAK_GIFT_DAY_OPTIONS = (1, 2, 3)
STREAK_GIFT_MIN_STREAK = 3       # only streaks worth saving are offered
STREAK_GIFT_MAX_PEOPLE = 10      # readers offered per day
STREAK_GIFT_DONORS_EACH = 3      # random readers asked about each
FRAME_PRICE = 3000
FRAME_DAYS = 30
WALL_PRICE = 30000
POT_STEP = 1000
POT_MONTHLY_CAP = 50000

# code: (title, line above the post, line below it)
FRAMES = {
    "oltin": ("🌟 Oltin", "╭──── ✦ 🌟 ✦ ────╮", "╰──── ✦ 📚 ✦ ────╯"),
    "bahor": ("🌸 Bahor", "🌸 ━━━━ 🌿 ━━━━ 🌸", "🌸 ━━━━ 🌿 ━━━━ 🌸"),
    "kosmik": ("🪐 Kosmik", "🌌 ✧ ☄️ ✧ 🪐 ✧ ☄️ ✧ 🌌", "🌌 ✧ ☄️ ✧ 🪐 ✧ ☄️ ✧ 🌌"),
    "sharqona": ("۞ Sharqona", "۞ ━━━━ ✿ ━━━━ ۞", "۞ ━━━━ ✿ ━━━━ ۞"),
}


def _local_midnight(d):
    return timezone.make_aware(datetime.datetime.combine(d, datetime.time.min))


def _day_start():
    return _local_midnight(timezone.localdate())


def _month_start():
    return _local_midnight(timezone.localdate().replace(day=1))


def _spent(user, prefix: str, since) -> int:
    from tgbot.models import KitobchaLedger
    s = KitobchaLedger.objects.filter(user_id=user.id, reason__startswith=prefix, created_at__gte=since,
                                      delta__lt=0).aggregate(s=Sum("delta"))["s"]
    return -int(s or 0)


def _take_locked(p, amount: int, reason: str) -> None:
    from tgbot.models import KitobchaLedger
    p.ball = int(p.ball or 0) - int(amount)
    p.save(update_fields=["ball"])
    KitobchaLedger.objects.create(user=p, delta=-int(amount), reason=reason[:40])


def _first_name(p) -> str:
    return ((p.full_name or "").split() or ["Kitobxon"])[0]


# ── transfer ────────────────────────────────────────────────────────────────

def transfer(sender, recipient, amount: int) -> dict:
    from tgbot.models import KitobchaLedger, TelegramProfile
    from tgbot.services import wallet
    amount = int(amount)
    if not wallet.is_member(sender):
        return {"ok": False, "error": "not_member"}
    if recipient.id == sender.id:
        return {"ok": False, "error": "self"}
    if amount < TRANSFER_MIN:
        return {"ok": False, "error": "too_small"}
    left = TRANSFER_DAILY_CAP - _spent(sender, "transfer_out", _day_start())
    if amount > left:
        return {"ok": False, "error": "daily_cap", "left": max(0, left)}
    with transaction.atomic():
        a, b = sorted([sender.id, recipient.id])
        locked = {p.id: p for p in TelegramProfile.objects.select_for_update().filter(id__in=[a, b])}
        s, r = locked[sender.id], locked[recipient.id]
        if int(s.ball or 0) < amount:
            return {"ok": False, "error": "insufficient", "balance": int(s.ball or 0)}
        _take_locked(s, amount, f"transfer_out:{r.telegram_id}")
        r.ball = int(r.ball or 0) + amount
        r.save(update_fields=["ball"])
        KitobchaLedger.objects.create(user=r, delta=amount, reason=f"transfer_in:{s.telegram_id}"[:40])
    sender.ball = s.ball
    return {"ok": True, "amount": amount, "balance": int(s.ball)}


# ── mentor ──────────────────────────────────────────────────────────────────

def is_newcomer_for_mentor(p) -> bool:
    created = getattr(p, "created_at", None)
    return bool(p.is_registered and created
                and timezone.now() - created <= datetime.timedelta(days=MENTOR_NEWCOMER_DAYS))


def mentor(mentor_user, newcomer, days: int) -> dict:
    from tgbot.models import TelegramProfile, WalletTransaction
    from tgbot.services import wallet
    days = int(days)
    if days not in MENTOR_DAY_OPTIONS:
        return {"ok": False, "error": "days"}
    if newcomer.id == mentor_user.id:
        return {"ok": False, "error": "self"}
    if not is_newcomer_for_mentor(newcomer):
        return {"ok": False, "error": "not_newcomer"}
    price = days * MENTOR_DAY_PRICE
    with transaction.atomic():
        a, b = sorted([mentor_user.id, newcomer.id])
        locked = {p.id: p for p in TelegramProfile.objects.select_for_update().filter(id__in=[a, b])}
        m, n = locked[mentor_user.id], locked[newcomer.id]
        if int(m.ball or 0) < price:
            return {"ok": False, "error": "insufficient", "balance": int(m.ball or 0), "price": price}
        _take_locked(m, price, f"mentor:{n.telegram_id}")
        m.mentor_days_given = int(m.mentor_days_given or 0) + days
        m.save(update_fields=["mentor_days_given"])
        wallet._credit_locked(n, days * wallet.DAY_FEE, WalletTransaction.KIND_MENTOR,
                              f"Ustoz: {m.full_name or m.telegram_id}")
    mentor_user.ball = m.ball
    return {"ok": True, "days": days, "price": price, "balance": int(m.ball)}


# ── streak gift ─────────────────────────────────────────────────────────────

def _gift_key(recipient_id, day=None) -> str:
    return f"streak_gift_done:{recipient_id}:{(day or timezone.localdate()).isoformat()}"


def streak_gift_candidates(limit=STREAK_GIFT_MAX_PEOPLE) -> list:
    """Readers whose streak burns tonight and who cannot pay today's report:
    no report yet, active yesterday, a streak worth saving, no freeze token."""
    from tgbot.models import ConfirmationReport, StreakFreezeCoverage, TelegramProfile
    from tgbot.services import ops_fixes, wallet
    today = timezone.localdate()
    yesterday = today - datetime.timedelta(days=1)
    reported = set(ConfirmationReport.objects.filter(date__date=today).values_list("user_id", flat=True))
    active = set(ConfirmationReport.objects.filter(date__date=yesterday).values_list("user_id", flat=True))
    active |= set(StreakFreezeCoverage.objects.filter(date=yesterday).values_list("user_id", flat=True))
    out = []
    for p in TelegramProfile.objects.filter(id__in=active - reported, is_registered=True, is_blocked=False,
                                            streak_freeze_count=0):
        if wallet.can_report(p):
            continue
        streak = ops_fixes.current_streak(p.id)
        if streak >= STREAK_GIFT_MIN_STREAK:
            out.append((streak, p))
    out.sort(key=lambda r: -r[0])
    return out[:limit]


def streak_gift_donors(recipient, how_many=STREAK_GIFT_DONORS_EACH, exclude=()) -> list:
    """Random active readers who can afford at least one day."""
    from tgbot.models import ConfirmationReport, TelegramProfile
    since = timezone.now() - datetime.timedelta(days=3)
    recent = set(ConfirmationReport.objects.filter(date__gte=since).values_list("user_id", flat=True))
    ids = list(TelegramProfile.objects.filter(id__in=recent, is_registered=True, is_blocked=False,
                                              ball__gte=STREAK_GIFT_DAY_PRICE)
               .exclude(id=recipient.id).exclude(id__in=list(exclude)).values_list("id", flat=True))
    random.shuffle(ids)
    return list(TelegramProfile.objects.filter(id__in=ids[:how_many]))


def gift_streak(donor, recipient, days: int) -> dict:
    """Give `days` streak freeze tokens; once per recipient per day."""
    from django.core.cache import cache
    from tgbot.models import TelegramProfile
    days = int(days)
    if days not in STREAK_GIFT_DAY_OPTIONS:
        return {"ok": False, "error": "days"}
    if donor.id == recipient.id:
        return {"ok": False, "error": "self"}
    price = days * STREAK_GIFT_DAY_PRICE
    if not cache.add(_gift_key(recipient.id), donor.id, 60 * 60 * 26):
        return {"ok": False, "error": "already_saved"}
    try:
        with transaction.atomic():
            a, b = sorted([donor.id, recipient.id])
            locked = {p.id: p for p in TelegramProfile.objects.select_for_update().filter(id__in=[a, b])}
            d, r = locked[donor.id], locked[recipient.id]
            if int(d.ball or 0) < price:
                raise ValueError("insufficient")
            _take_locked(d, price, f"streak_gift:{r.telegram_id}")
            r.streak_freeze_count = int(r.streak_freeze_count or 0) + days
            r.save(update_fields=["streak_freeze_count"])
    except ValueError:
        cache.delete(_gift_key(recipient.id))
        return {"ok": False, "error": "insufficient", "price": price}
    donor.ball = d.ball
    return {"ok": True, "days": days, "price": price, "balance": int(d.ball)}


# ── frames ──────────────────────────────────────────────────────────────────

def active_frame(user):
    code = getattr(user, "report_frame", "") or ""
    until = getattr(user, "report_frame_until", None)
    if code in FRAMES and until and until >= timezone.localdate():
        return code
    return None


def frame_lines(user):
    """(above, below) for the user's group report post, or None."""
    code = active_frame(user)
    return (FRAMES[code][1], FRAMES[code][2]) if code else None


def buy_frame(user, code: str) -> dict:
    from tgbot.models import TelegramProfile
    if code not in FRAMES:
        return {"ok": False, "error": "unknown"}
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        if int(p.ball or 0) < FRAME_PRICE:
            return {"ok": False, "error": "insufficient", "price": FRAME_PRICE}
        _take_locked(p, FRAME_PRICE, f"frame:{code}")
        today = timezone.localdate()
        # Days left on the same frame carry over; a new frame starts today.
        base = p.report_frame_until if (p.report_frame == code and p.report_frame_until
                                        and p.report_frame_until >= today) else today - datetime.timedelta(days=1)
        p.report_frame = code
        p.report_frame_until = base + datetime.timedelta(days=FRAME_DAYS)
        p.save(update_fields=["report_frame", "report_frame_until"])
    user.ball, user.report_frame, user.report_frame_until = p.ball, p.report_frame, p.report_frame_until
    return {"ok": True, "until": p.report_frame_until, "balance": int(p.ball)}


# ── honour wall ─────────────────────────────────────────────────────────────

def join_wall(user) -> dict:
    from tgbot.models import TelegramProfile
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        if p.honor_wall_at:
            return {"ok": False, "error": "already"}
        if int(p.ball or 0) < WALL_PRICE:
            return {"ok": False, "error": "insufficient", "price": WALL_PRICE}
        _take_locked(p, WALL_PRICE, "honor_wall")
        p.honor_wall_at = timezone.now()
        p.save(update_fields=["honor_wall_at"])
    user.ball, user.honor_wall_at = p.ball, p.honor_wall_at
    return {"ok": True, "balance": int(p.ball)}


def wall_entries(limit=300) -> list:
    from tgbot.models import TelegramProfile
    return list(TelegramProfile.objects.filter(honor_wall_at__isnull=False).order_by("honor_wall_at")
                .values_list("full_name", "honor_wall_at")[:limit])


# ── Kitobcha -> Kitob hamyonchasi ───────────────────────────────────────────

def pot_left_this_month(user) -> int:
    return max(0, POT_MONTHLY_CAP - _spent(user, "to_pot", _month_start()))


def to_pot(user, amount: int) -> dict:
    from tgbot.models import TelegramProfile
    from tgbot.services import wallet
    amount = int(amount)
    if amount <= 0 or amount % POT_STEP:
        return {"ok": False, "error": "step"}
    if amount > pot_left_this_month(user):
        return {"ok": False, "error": "monthly_cap", "left": pot_left_this_month(user)}
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        if int(p.ball or 0) < amount:
            return {"ok": False, "error": "insufficient", "balance": int(p.ball or 0)}
        _take_locked(p, amount, "to_pot")
        pot = wallet._pot_add_locked(p, amount)
    user.ball, user.cashback_balance, user.wallet_balance = p.ball, p.cashback_balance, p.wallet_balance
    return {"ok": True, "amount": amount, **pot}
