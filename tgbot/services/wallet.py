"""Hamyon — the real-money wallet that replaces Premium on 1 November 2026.

Owner's decisions (2026-10-25):
- every reader has a wallet in so'm; a report day costs DAY_FEE (1 000), taken
  once per day on the day's first report. No balance -> no report.
- up to KITOBCHA_SHARE_PCT (30%) of the fee is paid in Kitobcha
  (1 Kitobcha = 1 so'm) unless the reader switches it off;
- everyone gets LAUNCH_BONUS (3 000) once; paid Premium days left at the
  launch become DAY_FEE each in the wallet, and Premium ends;
- Premium's perks (2x Kitobcha, VIP arena, many reports a day, AI quiz
  allowance) go to members -- see is_member(), which has_active_premium()
  defers to. Membership is bought, not held (owner, 2026-11-01): a single
  top-up of MEMBER_MIN (15 000 so'm) or more gives one perk day per DAY_FEE,
  added after any days still left (wallet_member_until). Holding a balance
  earns nothing -- a perk for keeping money parked would look like a benefit
  on a loan, and a balance threshold took the perks away at the first fee;
- a Premium bought before the launch keeps those perks until its own end
  date, whatever the wallet holds -- that was the promise when it was sold.
  Its days left are ALSO credited to the wallet (DAY_FEE each);
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
MEMBER_MIN = 15000
# A member's 2nd, 3rd... report of the day (owner, 2026-11-01: free extras would
# leave members' money untouched, the full price would make the perk pointless).
EXTRA_FEE_MEMBER = 100
TOPUP_PRESETS = (1000, 2000, 5000, 10000, 15000, 30000)
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

def kitobcha_part(user, amount=None) -> int:
    if not getattr(user, "wallet_use_kitobcha", True):
        return 0
    amount = DAY_FEE if amount is None else int(amount)
    return max(0, min(int(user.ball or 0), amount * KITOBCHA_SHARE_PCT // 100))


def paid_on(user, day=None) -> bool:
    from tgbot.models import WalletTransaction
    day = day or timezone.localdate()
    return WalletTransaction.objects.filter(user_id=user.id, kind=WalletTransaction.KIND_REPORT_FEE,
                                            day=day).exists()


def fees_today(user, day=None) -> int:
    """Report charges taken today (first + extra) = the number of the next one."""
    from tgbot.models import WalletTransaction
    day = day or timezone.localdate()
    return WalletTransaction.objects.filter(
        user_id=user.id, day=day,
        kind__in=[WalletTransaction.KIND_REPORT_FEE, WalletTransaction.KIND_REPORT_EXTRA],
    ).count()


def report_price(user, day=None) -> int:
    """What the next report costs: the day's first DAY_FEE; every further one
    DAY_FEE again, or EXTRA_FEE_MEMBER for a member."""
    if not paid_on(user, day):
        return DAY_FEE
    return EXTRA_FEE_MEMBER if is_member(user) else DAY_FEE


def fee_split(user, amount=None) -> tuple:
    """(so'm from the wallet, Kitobcha) for the next report's price."""
    amount = report_price(user) if amount is None else int(amount)
    k = kitobcha_part(user, amount)
    return amount - k, k


def can_report(user) -> bool:
    cash, _ = fee_split(user)
    return int(user.wallet_balance or 0) >= cash


def _fee_ok_key(user, n, day=None) -> str:
    return f"wallet_fee_ok:{user.id}:{(day or timezone.localdate()).isoformat()}:{n}"


def fee_confirmed(user, day=None) -> bool:
    """The reader said yes to the next report's price. Asked before every
    charge; charge_report uses the yes up (owner, 2026-11-01)."""
    from django.core.cache import cache
    return bool(cache.get(_fee_ok_key(user, fees_today(user, day), day)))


def confirm_fee(user, n=None, day=None) -> bool:
    """Record the yes for the day's charge number `n` (the one the reader was
    asked about). A stale n -- that charge already happened, e.g. a doubled
    tap -- is ignored, so one yes can never pay twice."""
    from django.core.cache import cache
    current = fees_today(user, day)
    if n is not None and int(n) != current:
        return False
    cache.set(_fee_ok_key(user, current, day), 1, 60 * 60 * 24)
    return True


def fee_confirm_plain(user) -> str:
    """Short question for the site's native confirm popup (Telegram allows
    256 characters there)."""
    cash, kit = fee_split(user)
    n = fees_today(user)
    som = lambda v: f"{int(v or 0):,}".replace(",", " ")  # noqa: E731
    if (getattr(user, "language", None) or "uz") == "ru":
        part = f"{som(cash)} сум" + (f" + {kit} Kitobcha" if kit else "")
        which = "За сегодняшний отчёт" if n == 0 else f"За {n + 1}-й отчёт сегодня"
        return f"{which} спишется {part}. В кошельке: {som(user.wallet_balance)} сум. Подтверждаете?"
    part = f"{som(cash)} so'm" + (f" + {kit} Kitobcha" if kit else "")
    which = "Bugungi hisobotingiz" if n == 0 else f"Bugungi {n + 1}-hisobotingiz"
    return f"{which} uchun {part} yechiladi. Hamyoningizda: {som(user.wallet_balance)} so'm. Tasdiqlaysizmi?"


def legacy_premium(user) -> bool:
    """A Premium paid for before the launch, still inside its term."""
    from tgbot.models import Payment
    return Payment.objects.filter(user_id=user.id, status="paid", end_date__gte=timezone.localdate()).exists()


def member_until(user):
    """Last day of the perks a top-up bought, or None when none are left."""
    until = getattr(user, "wallet_member_until", None)
    return until if until and until >= timezone.localdate() else None


_UZ_MONTHS = ("yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul",
              "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr")


def uz_date(d) -> str:
    """16-noyabr"""
    return f"{d.day}-{_UZ_MONTHS[d.month - 1]}"


def member_days_for(amount) -> int:
    """Perk days one top-up buys: one per DAY_FEE, from MEMBER_MIN up."""
    return int(amount) // DAY_FEE if int(amount) >= MEMBER_MIN else 0


def _extend_membership_locked(p, days: int) -> None:
    """Add `days` after the perk days still left (or from today)."""
    yesterday = timezone.localdate() - datetime.timedelta(days=1)
    start = max(p.wallet_member_until or yesterday, yesterday)
    p.wallet_member_until = start + datetime.timedelta(days=days)
    p.save(update_fields=["wallet_member_until"])


def is_member(user) -> bool:
    return member_until(user) is not None or legacy_premium(user)


def member_ids() -> set:
    """Bulk is_member() for broadcasts and leaderboards."""
    from tgbot.models import Payment, TelegramProfile
    ids = set(TelegramProfile.objects.filter(wallet_member_until__gte=timezone.localdate())
              .values_list("id", flat=True))
    ids |= set(Payment.objects.filter(status="paid", end_date__gte=timezone.localdate())
               .values_list("user_id", flat=True))
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


def charge_report(user, day=None) -> dict:
    """Take one report's price, only with the reader's yes for exactly this
    charge (confirm_fee), which it uses up. {"ok": True, "cash", "kitobcha",
    "balance", "price", "extra"} or {"ok": False, "error": "insufficient" |
    "confirm", ...}."""
    from django.core.cache import cache
    from tgbot.models import KitobchaLedger, TelegramProfile, WalletTransaction
    day = day or timezone.localdate()
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        n = fees_today(p, day)
        price = report_price(p, day)
        cash, kit = fee_split(p, price)
        balance = int(p.wallet_balance or 0)
        if balance < cash:
            return {"ok": False, "error": "insufficient", "need": cash - balance, "balance": balance,
                    "cash": cash, "kitobcha": kit}
        if not cache.delete(_fee_ok_key(p, n, day)):
            return {"ok": False, "error": "confirm", "balance": balance, "cash": cash, "kitobcha": kit}
        p.wallet_balance = balance - cash
        fields = ["wallet_balance"]
        if kit:
            p.ball = p.ball - kit
            fields.append("ball")
            KitobchaLedger.objects.create(user=p, delta=-kit, reason="report_fee")
        p.save(update_fields=fields)
        WalletTransaction.objects.create(
            user=p, kind=WalletTransaction.KIND_REPORT_FEE if n == 0 else WalletTransaction.KIND_REPORT_EXTRA,
            delta=-cash, kitobcha=kit, day=day, balance_after=p.wallet_balance)
    user.wallet_balance = p.wallet_balance
    user.ball = p.ball
    return {"ok": True, "extra": n > 0, "price": price, "cash": cash, "kitobcha": kit,
            "balance": p.wallet_balance}


# Money the project gave (bonus, Premium days turned into so'm -- the Premium
# itself still runs to its end date): never refunded (owner, 2026-11-01).
GIFT_KINDS = ("bonus", "premium_conversion")


def refundable(user) -> int:
    """Paid money still unspent -- what a reader may take back. Only top-ups
    count; spending is taken from gifts first, so a reader never loses
    refundable money to a bonus they did not ask for."""
    from django.db.models import Sum
    from tgbot.models import WalletTransaction
    sums = dict(WalletTransaction.objects.filter(user_id=user.id).values("kind")
                .annotate(s=Sum("delta")).values_list("kind", "s"))
    admin_in = int(WalletTransaction.objects.filter(user_id=user.id, kind="admin", delta__gt=0)
                   .aggregate(s=Sum("delta"))["s"] or 0)
    admin_out = -int(WalletTransaction.objects.filter(user_id=user.id, kind="admin", delta__lt=0)
                     .aggregate(s=Sum("delta"))["s"] or 0)
    paid_in = int(sums.get("topup") or 0)
    gifts_in = sum(int(sums.get(k) or 0) for k in GIFT_KINDS) + admin_in
    spent = -int(sums.get("report_fee") or 0) - int(sums.get("report_extra") or 0) + admin_out
    refunded = -int(sums.get("refund") or 0)
    paid_spent = max(0, spent - gifts_in)
    return max(0, min(int(user.wallet_balance or 0), paid_in - paid_spent - refunded))


def refund(user, amount=None, note: str = "") -> dict:
    """Take a refund out of the wallet (the money itself goes back by hand,
    to the reader's card): at most refundable(); the whole of it when no
    amount is given."""
    from tgbot.models import TelegramProfile, WalletTransaction
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        can = refundable(p)
        take = can if amount is None else min(int(amount), can)
        if take <= 0:
            return {"ok": False, "refundable": can}
        p.wallet_balance = int(p.wallet_balance or 0) - take
        p.save(update_fields=["wallet_balance"])
        WalletTransaction.objects.create(user=p, kind=WalletTransaction.KIND_REFUND, delta=-take,
                                         balance_after=p.wallet_balance, note=(note or "Qaytarildi")[:120])
    user.wallet_balance = p.wallet_balance
    return {"ok": True, "refunded": take, "balance": p.wallet_balance}


def day_summary(day=None) -> dict:
    """One day of money: wallet moves by kind, top-ups by status, report
    charges against report submissions (any reader who reported without a
    charge shows up in `unpaid`), Kitobcha in and out."""
    from django.db.models import Count, Sum
    from tgbot.models import ConfirmationReport, KitobchaLedger, TelegramProfile, WalletTopup, WalletTransaction
    day = day or timezone.localdate()
    if isinstance(day, str):
        day = datetime.date.fromisoformat(day)
    moves = {k: {"n": r["n"], "som": int(r["s"] or 0), "kitobcha": int(r["k"] or 0)}
             for k, r in ((r["kind"], r) for r in WalletTransaction.objects.filter(created_at__date=day)
                          .values("kind").annotate(n=Count("id"), s=Sum("delta"), k=Sum("kitobcha")))}
    topups = {r["status"]: {"n": r["n"], "som": int(r["s"] or 0)}
              for r in WalletTopup.objects.filter(created_at__date=day)
              .values("status").annotate(n=Count("id"), s=Sum("amount"))}
    submissions = set(ConfirmationReport.objects.filter(date__date=day).values_list("user_id", "date"))
    reporters = {u for u, _ in submissions}
    charges = WalletTransaction.objects.filter(
        day=day, kind__in=[WalletTransaction.KIND_REPORT_FEE, WalletTransaction.KIND_REPORT_EXTRA])
    per_user = dict(charges.values("user_id").annotate(n=Count("id")).values_list("user_id", "n"))
    sub_per_user = {}
    for u, _ in submissions:
        sub_per_user[u] = sub_per_user.get(u, 0) + 1
    short = {u: sub_per_user[u] - per_user.get(u, 0) for u in reporters if sub_per_user[u] > per_user.get(u, 0)}
    names = dict(TelegramProfile.objects.filter(id__in=short).values_list("id", "full_name"))
    tg = dict(TelegramProfile.objects.filter(id__in=short).values_list("id", "telegram_id"))
    kit_in = KitobchaLedger.objects.filter(created_at__date=day, delta__gt=0).aggregate(n=Count("id"), s=Sum("delta"))
    kit_out = KitobchaLedger.objects.filter(created_at__date=day, delta__lt=0).aggregate(n=Count("id"), s=Sum("delta"))
    return {
        "day": day.isoformat(),
        "moves": moves,
        "topups": topups,
        "reporters": len(reporters),
        "submissions": len(submissions),
        "charges": sum(per_user.values()),
        "unpaid": [{"telegram_id": tg.get(u), "name": names.get(u), "missing": m} for u, m in short.items()],
        "submission_list": [
            {"telegram_id": t, "name": n, "at": timezone.localtime(d).strftime("%H:%M")}
            for t, n, d in sorted(ConfirmationReport.objects.filter(date__date=day)
                                  .values_list("user__telegram_id", "user__full_name", "date").distinct(),
                                  key=lambda r: r[2])[:300]
        ],
        "kitobcha_in": {"n": kit_in["n"] or 0, "sum": int(kit_in["s"] or 0)},
        "kitobcha_out": {"n": kit_out["n"] or 0, "sum": -int(kit_out["s"] or 0)},
        "wallets_total": int(TelegramProfile.objects.aggregate(s=Sum("wallet_balance"))["s"] or 0),
        "members": len(member_ids()),
    }


def day_summary_text(s: dict) -> str:
    """The wallet + Kitobcha block of the admin daily report."""
    som = lambda v: f"{int(v or 0):,}".replace(",", " ")  # noqa: E731

    def mv(kind):
        m = s["moves"].get(kind) or {"n": 0, "som": 0, "kitobcha": 0}
        return m["n"], abs(m["som"]), m["kitobcha"]

    t_ok = s["topups"].get("approved", {"n": 0, "som": 0})
    t_wait = s["topups"].get("pending", {"n": 0, "som": 0})
    t_no = s["topups"].get("rejected", {"n": 0, "som": 0})
    f_n, f_som, f_kit = mv("report_fee")
    e_n, e_som, e_kit = mv("report_extra")
    b_n, b_som, _ = mv("bonus")
    a_n, a_som, _ = mv("admin")
    lines = [
        "👛 <b>Hamyon (so'm):</b>",
        f"  ➕ To'ldirish: tasdiqlangan <b>{t_ok['n']}</b> ta — <b>{som(t_ok['som'])}</b>; "
        f"kutilmoqda {t_wait['n']} ta — {som(t_wait['som'])}; rad etilgan {t_no['n']} ta",
        f"  🧾 Hisobot to'lovlari: <b>{f_n + e_n}</b> ta — <b>{som(f_som + e_som)}</b> so'm + "
        f"{som(f_kit + e_kit)} Kitobcha (birinchi {f_n}, qo'shimcha {e_n})",
        f"  🎁 Bonus: {b_n} ta — {som(b_som)} · 🛠 Admin: {a_n} ta — {som(a_som)}",
        f"  📊 Hisobot yuborishlar: {s['submissions']} ta, {s['reporters']} kishi · to'lovlar: {s['charges']} ta",
    ]
    if s["unpaid"]:
        who = ", ".join(f"{u['name'] or u['telegram_id']} ({u['missing']})" for u in s["unpaid"][:8])
        lines.append(f"  ⚠️ <b>To'lovsiz hisobot: {sum(u['missing'] for u in s['unpaid'])} ta</b> — {who}")
    else:
        lines.append("  ✅ Har bir hisobot to'langan")
    lines += [
        f"  💰 Hamyonlardagi jami qoldiq: <b>{som(s['wallets_total'])}</b> · 💎 imtiyozlilar: <b>{s['members']}</b>",
        "",
        "🪙 <b>Kitobcha tranzaksiyalari:</b>",
        f"  Kirim: <b>{s['kitobcha_in']['n']}</b> ta — +{som(s['kitobcha_in']['sum'])}",
        f"  Chiqim: <b>{s['kitobcha_out']['n']}</b> ta — −{som(s['kitobcha_out']['sum'])}",
    ]
    return "\n".join(lines)


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
                # The days are credited AND the Premium runs to its end date:
                # its perks were promised for that term (legacy_premium()).
                _credit_locked(p, days * DAY_FEE, WalletTransaction.KIND_PREMIUM,
                               f"{days} kunlik Premium → hamyon")
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
        days = member_days_for(t.amount)
        if days:
            _extend_membership_locked(p, days)
        t.user.wallet_balance = p.wallet_balance
        t.user.wallet_member_until = p.wallet_member_until
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
