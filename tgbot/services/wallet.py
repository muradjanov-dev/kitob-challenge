"""Hamyon — the real-money wallet that replaces Premium on 1 November 2026.

Owner's decisions (2026-10-25):
- every reader has a wallet in so'm; a report day costs DAY_FEE (1 000), taken
  once per day on the day's first report. No balance -> no report.
- up to KITOBCHA_SHARE_PCT (30%) of the fee is paid in Kitobcha
  (1 Kitobcha = 1 so'm) unless the reader switches it off;
- everyone gets LAUNCH_BONUS (3 000) once; paid Premium days left at the
  launch become DAY_FEE each in the wallet, and Premium ends;
- Premium's perks (2x Kitobcha, VIP arena, many reports a day, AI quiz
  allowance) go to members: wallet >= MEMBER_MIN, or today's fee paid --
  see is_member(), which TelegramProfile.has_active_premium() defers to;
- top-ups: preset or typed amount, card transfer, receipt approved by an admin.

Money only moves here, each move with a WalletTransaction written in the
same transaction under a row lock on the profile. The unique constraints on
WalletTransaction (one fee per user-day, one bonus, one conversion) make
retries and races harmless.

Before LAUNCH_DATE everything is dormant, except for testers (admins added via
internal/ops/wallet-testers/), who can try the whole flow early. A tester never
gets Premium converted early.
"""
import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

LAUNCH_DATE = datetime.date(2026, 11, 1)
DAY_FEE = 1000
LAUNCH_BONUS = 3000
KITOBCHA_SHARE_PCT = 30
MEMBER_MIN = DAY_FEE
TOPUP_PRESETS = (1000, 2000, 5000, 10000, 30000)
MIN_TOPUP = 1000
MAX_TOPUP = 2_000_000

_TESTERS_KEY = "wallet_testers"
# has_active_premium() runs on every Kitobcha credit, so the tester list is
# read from the cache at most every 30 s per process.
_testers_memo = {"at": 0.0, "ids": set()}


def _testers() -> set:
    import time
    now = time.monotonic()
    if now - _testers_memo["at"] > 30:
        try:
            from django.core.cache import cache
            _testers_memo["ids"] = set(cache.get(_TESTERS_KEY) or [])
        except Exception:
            pass
        _testers_memo["at"] = now
    return _testers_memo["ids"]


def set_testers(telegram_ids) -> None:
    from django.core.cache import cache
    cache.set(_TESTERS_KEY, sorted({int(t) for t in telegram_ids}), None)
    _testers_memo["at"] = 0.0


def launched(user=None) -> bool:
    if timezone.localdate() >= LAUNCH_DATE:
        return True
    return bool(user is not None and int(getattr(user, "telegram_id", 0) or 0) in _testers())


def is_live_launch() -> bool:
    """The real launch date has come (not just a tester preview)."""
    return timezone.localdate() >= LAUNCH_DATE


# ── Reading the wallet ──────────────────────────────────────────────────────

def kitobcha_part(user) -> int:
    if not getattr(user, "wallet_use_kitobcha", True):
        return 0
    return max(0, min(int(user.ball or 0), DAY_FEE * KITOBCHA_SHARE_PCT // 100))


def fee_split(user) -> tuple:
    """(so'm from the wallet, Kitobcha) for today's fee."""
    k = kitobcha_part(user)
    return DAY_FEE - k, k


def paid_on(user, day=None) -> bool:
    from tgbot.models import WalletTransaction
    day = day or timezone.localdate()
    return WalletTransaction.objects.filter(user_id=user.id, kind=WalletTransaction.KIND_REPORT_FEE,
                                            day=day).exists()


def can_report(user) -> bool:
    if paid_on(user):
        return True
    cash, _ = fee_split(user)
    return int(user.wallet_balance or 0) >= cash


def is_member(user) -> bool:
    return int(user.wallet_balance or 0) >= MEMBER_MIN or paid_on(user)


def member_ids() -> set:
    """Bulk is_member() for broadcasts and leaderboards."""
    from tgbot.models import TelegramProfile, WalletTransaction
    ids = set(TelegramProfile.objects.filter(wallet_balance__gte=MEMBER_MIN).values_list("id", flat=True))
    ids |= set(WalletTransaction.objects.filter(kind=WalletTransaction.KIND_REPORT_FEE,
                                                day=timezone.localdate()).values_list("user_id", flat=True))
    return ids


def days_left(user) -> int:
    """Report days the wallet (plus Kitobcha) still covers, today's paid day excluded."""
    bal, kit = int(user.wallet_balance or 0), int(user.ball or 0) if user.wallet_use_kitobcha else 0
    days = 0
    max_kit = DAY_FEE * KITOBCHA_SHARE_PCT // 100
    while days < 3650:
        k = min(kit, max_kit)
        if bal < DAY_FEE - k:
            break
        bal -= DAY_FEE - k
        kit -= k
        days += 1
    return days


# ── Moving money ────────────────────────────────────────────────────────────

def _credit_locked(p, amount: int, kind: str, note: str = ""):
    from tgbot.models import WalletTransaction
    p.wallet_balance = int(p.wallet_balance or 0) + int(amount)
    p.save(update_fields=["wallet_balance"])
    return WalletTransaction.objects.create(user=p, kind=kind, delta=int(amount),
                                            balance_after=p.wallet_balance, note=note[:120])


def credit(user, amount: int, kind: str, note: str = "") -> int:
    from tgbot.models import TelegramProfile
    if int(amount) <= 0:
        return int(user.wallet_balance or 0)
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        _credit_locked(p, amount, kind, note)
    user.wallet_balance = p.wallet_balance
    return p.wallet_balance


def charge_day(user, day=None) -> dict:
    """Take today's report fee, once. {"ok": True, "already": bool, ...} or
    {"ok": False, "need": so'm short, "balance": ...}."""
    from tgbot.models import KitobchaLedger, TelegramProfile, WalletTransaction
    day = day or timezone.localdate()
    try:
        with transaction.atomic():
            p = TelegramProfile.objects.select_for_update().get(id=user.id)
            if WalletTransaction.objects.filter(user=p, kind=WalletTransaction.KIND_REPORT_FEE, day=day).exists():
                return {"ok": True, "already": True, "balance": p.wallet_balance}
            cash, kit = fee_split(p)
            if int(p.wallet_balance or 0) < cash:
                return {"ok": False, "need": cash - int(p.wallet_balance or 0),
                        "balance": int(p.wallet_balance or 0), "cash": cash, "kitobcha": kit}
            p.wallet_balance = int(p.wallet_balance or 0) - cash
            fields = ["wallet_balance"]
            if kit:
                p.ball = p.ball - kit
                fields.append("ball")
                KitobchaLedger.objects.create(user=p, delta=-kit, reason="report_fee")
            p.save(update_fields=fields)
            WalletTransaction.objects.create(user=p, kind=WalletTransaction.KIND_REPORT_FEE, delta=-cash,
                                             kitobcha=kit, day=day, balance_after=p.wallet_balance)
    except IntegrityError:
        # A second report of the same day raced this one and won.
        return {"ok": True, "already": True, "balance": int(user.wallet_balance or 0)}
    user.wallet_balance = p.wallet_balance
    user.ball = p.ball
    return {"ok": True, "already": False, "cash": cash, "kitobcha": kit, "balance": p.wallet_balance}


# ── Launch ──────────────────────────────────────────────────────────────────

def premium_days_left(user, from_day=None) -> int:
    from django.db.models import Max
    from tgbot.models import Payment
    from_day = from_day or LAUNCH_DATE
    end = Payment.objects.filter(user=user, status="paid", end_date__gte=from_day) \
        .aggregate(m=Max("end_date"))["m"]
    return (end - from_day).days + 1 if end else 0


def ensure_launch_credit(user) -> dict:
    """The launch bonus and the Premium conversion, each at most once.
    Returns what was credited now: {"bonus": so'm, "premium_days": n, "premium": so'm}."""
    from tgbot.models import Payment, TelegramProfile, WalletTransaction
    out = {"bonus": 0, "premium_days": 0, "premium": 0}
    if not launched(user):
        return out
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        kinds = set(WalletTransaction.objects.filter(
            user=p, kind__in=[WalletTransaction.KIND_BONUS, WalletTransaction.KIND_PREMIUM],
        ).values_list("kind", flat=True))
        if WalletTransaction.KIND_BONUS not in kinds:
            _credit_locked(p, LAUNCH_BONUS, WalletTransaction.KIND_BONUS, "Hamyon ishga tushdi")
            out["bonus"] = LAUNCH_BONUS
        # Premium is converted only on the real launch -- a tester previewing
        # the wallet in October must keep the Premium they paid for.
        if is_live_launch() and WalletTransaction.KIND_PREMIUM not in kinds:
            days = premium_days_left(p)
            if days > 0:
                _credit_locked(p, days * DAY_FEE, WalletTransaction.KIND_PREMIUM,
                               f"{days} kunlik Premium → hamyon")
                Payment.objects.filter(user=p, status="paid", end_date__gte=LAUNCH_DATE) \
                    .update(end_date=LAUNCH_DATE - datetime.timedelta(days=1))
                out["premium_days"], out["premium"] = days, days * DAY_FEE
            if p.trial_premium_until:
                p.trial_premium_until = None
                p.save(update_fields=["trial_premium_until"])
    user.wallet_balance = p.wallet_balance
    return out


def run_launch() -> dict:
    """Credit every registered reader (idempotent; the launch tick runs it)."""
    from tgbot.models import TelegramProfile
    users = bonus = converted = so_m = 0
    for p in TelegramProfile.objects.filter(is_registered=True).iterator():
        got = ensure_launch_credit(p)
        if got["bonus"] or got["premium"]:
            users += 1
        bonus += got["bonus"]
        converted += 1 if got["premium"] else 0
        so_m += got["premium"]
    return {"users": users, "bonus_total": bonus, "premium_users": converted, "premium_total": so_m}


# ── Top-ups ─────────────────────────────────────────────────────────────────

def create_topup(user, amount: int, photo_file_id: str):
    from tgbot.models import WalletTopup
    return WalletTopup.objects.create(user=user, amount=int(amount), photo_file_id=photo_file_id or "")


def approve_topup(topup_id: int, admin=None):
    """(topup, credited_now). Only the click that moves it out of pending
    credits the wallet, so a second admin (group + DM buttons) cannot."""
    from tgbot.models import TelegramProfile, WalletTopup, WalletTransaction
    with transaction.atomic():
        t = WalletTopup.objects.select_for_update().select_related("user").filter(id=topup_id).first()
        if not t or t.status != WalletTopup.STATUS_PENDING:
            return t, False
        t.status = WalletTopup.STATUS_APPROVED
        t.reviewed_by = admin
        t.reviewed_at = timezone.now()
        t.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        p = TelegramProfile.objects.select_for_update().get(id=t.user_id)
        _credit_locked(p, t.amount, WalletTransaction.KIND_TOPUP, f"To'ldirish #{t.id}")
        t.user.wallet_balance = p.wallet_balance
    return t, True


def reject_topup(topup_id: int, admin=None, reason: str = ""):
    from tgbot.models import WalletTopup
    with transaction.atomic():
        t = WalletTopup.objects.select_for_update().select_related("user").filter(id=topup_id).first()
        if not t or t.status != WalletTopup.STATUS_PENDING:
            return t, False
        t.status = WalletTopup.STATUS_REJECTED
        t.reviewed_by = admin
        t.reviewed_at = timezone.now()
        t.reject_reason = reason or ""
        t.save(update_fields=["status", "reviewed_by", "reviewed_at", "reject_reason", "updated_at"])
    return t, True


def parse_amount(text: str):
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    if not digits:
        return None
    n = int(digits)
    return n if MIN_TOPUP <= n <= MAX_TOPUP else None
