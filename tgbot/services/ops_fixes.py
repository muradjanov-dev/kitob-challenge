"""One-off data repairs, driven through views.internal_ops (dry run on GET,
apply on POST) because the production box has no shell access.

- streak_gap:  the server move (old server stopped 2026-09-18) left days
  nobody could report on. Readers whose streak was alive when the bot went
  down and who came back right after it returned get those days covered
  with StreakFreezeCoverage, the same rows a Market "Streak muzlatish"
  makes -- every streak count already reads them.
- themes:      Market themes were charged for but never painted the Mini
  App; ownership bought on the old server after the copied snapshot was
  also lost. Re-grants every theme paid for and, with refund=1, returns
  the Kitobcha (once per purchase, keyed in the ledger reason).
- set_admin:   flags a TelegramProfile as admin.
"""
import datetime
from collections import defaultdict

from django.db import transaction
from django.db.models.functions import TruncDate
from django.utils import timezone


def _d(value):
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value))


# ── Streak gap ──────────────────────────────────────────────────────────────

def daily_reporters(since, until=None) -> list:
    """[(date, distinct readers who reported that day)] — shows where the
    outage days are."""
    from tgbot.models import ConfirmationReport
    since = _d(since)
    until = _d(until) if until else timezone.localdate()
    counts = defaultdict(set)
    for day, uid in (ConfirmationReport.objects
                     .filter(date__date__gte=since, date__date__lte=until)
                     .annotate(_day=TruncDate("date"))
                     .values_list("_day", "user_id").distinct()):
        counts[day].add(uid)
    out, day = [], since
    while day <= until:
        out.append((day.isoformat(), len(counts.get(day, ()))))
        day += datetime.timedelta(days=1)
    return out


def _covered_dates(user_ids, lo, hi) -> dict:
    """{user_id: set(dates)} of report or freeze-covered days in [lo, hi]."""
    from tgbot.models import ConfirmationReport, StreakFreezeCoverage
    out = defaultdict(set)
    q = ConfirmationReport.objects.filter(date__date__gte=lo, date__date__lte=hi)
    if user_ids is not None:
        q = q.filter(user_id__in=user_ids)
    for uid, day in q.annotate(_day=TruncDate("date")).values_list("user_id", "_day").distinct():
        out[uid].add(day)
    c = StreakFreezeCoverage.objects.filter(date__gte=lo, date__lte=hi)
    if user_ids is not None:
        c = c.filter(user_id__in=user_ids)
    for uid, day in c.values_list("user_id", "date"):
        out[uid].add(day)
    return out


def streak_gap_plan(gap_start, gap_end, grace_days=2) -> list:
    """Readers to bridge across [gap_start, gap_end].

    Eligible: reported (or was freeze-covered) on gap_start-1 or during the
    gap, and again within `grace_days` after gap_end -- people needed a day
    or two to notice the bot was back. Every missing day between those two
    reports gets covered."""
    from tgbot.models import TelegramProfile
    gap_start, gap_end = _d(gap_start), _d(gap_end)
    lo = gap_start - datetime.timedelta(days=1)
    hi = gap_end + datetime.timedelta(days=1 + int(grace_days))
    dates = _covered_dates(None, lo, hi)

    plan = []
    for uid, days in dates.items():
        before = [d for d in days if d <= gap_end]
        after = [d for d in days if d > gap_end]
        if not before or not after:
            continue
        b, a = max(before), min(after)
        fill = []
        day = b + datetime.timedelta(days=1)
        while day < a:
            if day not in days:
                fill.append(day)
            day += datetime.timedelta(days=1)
        if fill:
            plan.append({"user_id": uid, "last_before": b, "first_after": a, "fill": fill})

    names = dict(
        TelegramProfile.objects.filter(id__in=[p["user_id"] for p in plan])
        .values_list("id", "full_name")
    )
    tg_ids = dict(
        TelegramProfile.objects.filter(id__in=[p["user_id"] for p in plan])
        .values_list("id", "telegram_id")
    )
    for p in plan:
        p["name"] = names.get(p["user_id"]) or "—"
        p["telegram_id"] = tg_ids.get(p["user_id"])
    plan.sort(key=lambda p: p["user_id"])
    return plan


def current_streak(user_id) -> int:
    from tgbot.services.premium_conversion import _compute_streaks
    return _compute_streaks([user_id]).get(user_id, 0)


def apply_streak_gap(plan) -> int:
    from tgbot.models import StreakFreezeCoverage
    rows = [StreakFreezeCoverage(user_id=p["user_id"], date=d) for p in plan for d in p["fill"]]
    with transaction.atomic():
        before = StreakFreezeCoverage.objects.count()
        StreakFreezeCoverage.objects.bulk_create(rows, ignore_conflicts=True)
        return StreakFreezeCoverage.objects.count() - before


def user_dates(telegram_id, since) -> dict:
    """Diagnostics for one reader: report and coverage days since `since`."""
    from tgbot.models import TelegramProfile
    p = TelegramProfile.objects.filter(telegram_id=int(telegram_id)).first()
    if not p:
        return {"found": False}
    days = _covered_dates([p.id], _d(since), timezone.localdate()).get(p.id, set())
    return {"found": True, "user_id": p.id, "name": p.full_name,
            "streak_now": current_streak(p.id),
            "dates": sorted(d.isoformat() for d in days)}


# ── Market themes ──────────────────────────────────────────────────────────

def theme_plan(old_owners=None) -> list:
    """Every reader who paid for a theme, with what to re-grant and refund.

    `old_owners` = [{"telegram_id", "theme", "price", "purchase_id"}] from
    the old server's final dump: purchases made there after the snapshot the
    new server started from, which this database never saw."""
    from tgbot.models import KitobchaLedger, MarketPurchase, TelegramProfile
    from tgbot.services.market import ITEMS

    bought = defaultdict(list)  # profile id -> [(purchase key, theme, price)]
    for pid, uid, key, price in (MarketPurchase.objects
                                 .filter(item_key__startswith="theme_")
                                 .values_list("id", "user_id", "item_key", "price")):
        bought[uid].append((f"theme_refund:{pid}", key, int(price)))
    for row in old_owners or []:
        p = TelegramProfile.objects.filter(telegram_id=int(row["telegram_id"])).only("id").first()
        if p:
            bought[p.id].append((f"theme_refund:old{row['purchase_id']}", row["theme"], int(row["price"])))

    refunded = set(
        KitobchaLedger.objects.filter(reason__startswith="theme_refund:").values_list("reason", flat=True)
    )
    profiles = TelegramProfile.objects.in_bulk(list(bought))
    plan = []
    for uid, items in bought.items():
        p = profiles.get(uid)
        if not p:
            continue
        owned = list(p.unlocked_themes or [])
        themes = [t for _, t, _ in items if t in ITEMS]
        missing = sorted({t for t in themes if t not in owned})
        refunds = [(reason, t, price) for reason, t, price in items if reason not in refunded]
        plan.append({
            "user_id": uid, "telegram_id": p.telegram_id, "name": p.full_name or "—",
            "owned": owned, "active": p.active_theme, "grant": missing,
            "refunds": refunds, "refund_total": sum(r[2] for r in refunds),
        })
    plan.sort(key=lambda r: r["user_id"])
    return plan


def apply_themes(plan, refund: bool) -> dict:
    from tgbot.models import KitobchaLedger, TelegramProfile
    granted = refunded_users = refunded_total = 0
    for row in plan:
        with transaction.atomic():
            p = TelegramProfile.objects.select_for_update().get(id=row["user_id"])
            owned = list(p.unlocked_themes or [])
            fields = []
            for t in row["grant"]:
                if t not in owned:
                    owned.append(t)
                    granted += 1
            if owned != list(p.unlocked_themes or []):
                p.unlocked_themes = owned
                fields.append("unlocked_themes")
            if owned and (not p.active_theme or p.active_theme not in owned):
                p.active_theme = owned[-1]
                fields.append("active_theme")
            if refund and row["refunds"]:
                done = set(KitobchaLedger.objects.filter(
                    user=p, reason__in=[r[0] for r in row["refunds"]]).values_list("reason", flat=True))
                total = 0
                for reason, _theme, price in row["refunds"]:
                    if reason in done:
                        continue
                    KitobchaLedger.objects.create(user=p, delta=price, reason=reason[:40])
                    total += price
                if total:
                    p.ball = (p.ball or 0) + total
                    fields.append("ball")
                    refunded_users += 1
                    refunded_total += total
            if fields:
                p.save(update_fields=sorted(set(fields)))
    return {"themes_granted": granted, "refunded_users": refunded_users,
            "refunded_total": refunded_total}


# ── Admins ─────────────────────────────────────────────────────────────────

def set_admin(telegram_id, apply: bool) -> dict:
    from tgbot.models import TelegramProfile
    p = TelegramProfile.objects.filter(telegram_id=int(telegram_id)).first()
    if not p:
        return {"found": False, "telegram_id": int(telegram_id)}
    if apply and not p.is_admin:
        p.is_admin = True
        p.save(update_fields=["is_admin"])
    return {"found": True, "telegram_id": p.telegram_id, "name": p.full_name,
            "is_admin": p.is_admin, "is_registered": p.is_registered}
