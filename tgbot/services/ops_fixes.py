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


def coverage_plan(rows) -> list:
    """Streak-freeze days the old server recorded that this database lacks.

    `rows` = [{"telegram_id", "date"}] from the old server's final dump: the
    server move restored reports but not these, so a frozen day became a
    hole in the streak again."""
    from tgbot.models import StreakFreezeCoverage, TelegramProfile
    tg_ids = {int(r["telegram_id"]) for r in rows}
    pid = dict(TelegramProfile.objects.filter(telegram_id__in=tg_ids).values_list("telegram_id", "id"))
    have = set(StreakFreezeCoverage.objects.filter(user_id__in=pid.values()).values_list("user_id", "date"))
    out = []
    for r in rows:
        uid = pid.get(int(r["telegram_id"]))
        day = _d(r["date"])
        if uid and (uid, day) not in have:
            out.append({"user_id": uid, "date": day})
            have.add((uid, day))
    return out


def apply_coverage(missing) -> int:
    from tgbot.models import StreakFreezeCoverage
    with transaction.atomic():
        before = StreakFreezeCoverage.objects.count()
        StreakFreezeCoverage.objects.bulk_create(
            [StreakFreezeCoverage(user_id=m["user_id"], date=m["date"]) for m in missing],
            ignore_conflicts=True)
        return StreakFreezeCoverage.objects.count() - before


def _max_streaks(user_ids=None) -> dict:
    """{user_id: longest run of reported-or-covered days}, in two queries."""
    from tgbot.models import ConfirmationReport, StreakFreezeCoverage
    days = defaultdict(set)
    q = ConfirmationReport.objects.all()
    c = StreakFreezeCoverage.objects.all()
    if user_ids is not None:
        q, c = q.filter(user_id__in=user_ids), c.filter(user_id__in=user_ids)
    for uid, day in q.annotate(_day=TruncDate("date")).values_list("user_id", "_day").distinct():
        days[uid].add(day)
    for uid, day in c.values_list("user_id", "date"):
        days[uid].add(day)
    out = {}
    for uid, ds in days.items():
        ds = sorted(ds)
        best = cur = 1
        for a, b in zip(ds, ds[1:]):
            cur = cur + 1 if (b - a).days == 1 else 1
            best = max(best, cur)
        out[uid] = best
    return out


def streak_achievement_plan() -> list:
    """Streak achievements (st_*) readers now qualify for but never got --
    the outage broke the run that would have unlocked them."""
    from tgbot.models import TelegramProfile, UserAchievement
    from tgbot.services.achievements import ACHIEVEMENTS_RAW
    streak_achs = [a for a in ACHIEVEMENTS_RAW if a["code"].startswith("st_")]
    best = _max_streaks()
    have = defaultdict(set)
    for uid, code in UserAchievement.objects.filter(code__startswith="st_").values_list("user_id", "code"):
        have[uid].add(code)
    plan = []
    for uid, n in best.items():
        due = [a for a in streak_achs if a["code"] not in have[uid] and a["cond"]({"max_streak": n})]
        if due:
            plan.append({"user_id": uid, "max_streak": n,
                         "codes": [a["code"] for a in due], "points": sum(a.get("points", 0) for a in due)})
    names = dict(TelegramProfile.objects.filter(id__in=[p["user_id"] for p in plan]).values_list("id", "full_name"))
    for p in plan:
        p["name"] = names.get(p["user_id"]) or "—"
    plan.sort(key=lambda p: -p["points"])
    return plan


def apply_streak_achievements(plan, paid_before=()) -> dict:
    """Award them the way check_user_achievements does (Kitobcha via
    update_ball, so Premium gets 2x) but without the group Tabriklash -- dozens
    of those at once would flood the groups.

    `paid_before` = {(telegram_id, code)} the old server had already awarded:
    the move lost those rows but the data restore re-credited their Kitobcha
    through the ledger, so they come back as rows only, unpaid."""
    from tgbot.models import TelegramProfile, UserAchievement
    from tgbot.services.achievements import ACHIEVEMENTS_RAW
    points = {a["code"]: a.get("points", 0) for a in ACHIEVEMENTS_RAW}
    paid_before = {(int(t), c) for t, c in paid_before}
    users = achievements = restored_only = paid = 0
    for p in plan:
        user = TelegramProfile.objects.filter(id=p["user_id"]).first()
        if not user:
            continue
        got = 0
        for code in p["codes"]:
            _, created = UserAchievement.objects.get_or_create(
                user=user, code=code, defaults={"congratulated": True})
            if not created:
                continue
            achievements += 1
            if (int(user.telegram_id), code) in paid_before:
                restored_only += 1
            elif points.get(code):
                got += user.update_ball(True, points[code], reason="achievement")
        if got:
            users += 1
            paid += got
    return {"users_paid": users, "achievements": achievements,
            "restored_without_pay": restored_only, "kitobcha": paid}


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
