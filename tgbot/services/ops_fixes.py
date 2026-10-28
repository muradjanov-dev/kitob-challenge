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


def restore_streak_days(rows, apply: bool) -> dict:
    """Every day the old server counted for a reader's streak must still
    count. `rows` = [{"telegram_id", "dates": ["YYYY-MM-DD", ...]}] -- the
    reader's report and freeze days in the old server's final dump. A day
    that is neither a report nor a freeze day here any more becomes a
    StreakFreezeCoverage, so no system loss shortens anyone's streak."""
    from tgbot.models import StreakFreezeCoverage, TelegramProfile
    tg_ids = {int(r["telegram_id"]) for r in rows}
    pid = dict(TelegramProfile.objects.filter(telegram_id__in=tg_ids).values_list("telegram_id", "id"))
    days_by_uid = {pid[int(r["telegram_id"])]: {_d(x) for x in r["dates"]}
                   for r in rows if int(r["telegram_id"]) in pid}
    if not days_by_uid:
        return {"matched_users": 0, "missing_days": 0, "users": 0, "created": 0}
    lo = min(min(v) for v in days_by_uid.values() if v)
    hi = max(max(v) for v in days_by_uid.values() if v)
    have = _covered_dates(list(days_by_uid), lo, hi)
    missing = [(uid, d) for uid, days in days_by_uid.items() for d in sorted(days - have.get(uid, set()))]
    created = 0
    if apply and missing:
        with transaction.atomic():
            before = StreakFreezeCoverage.objects.count()
            StreakFreezeCoverage.objects.bulk_create(
                [StreakFreezeCoverage(user_id=uid, date=d) for uid, d in missing], ignore_conflicts=True)
            created = StreakFreezeCoverage.objects.count() - before
    return {"matched_users": len(days_by_uid), "missing_days": len(missing),
            "users": len({m[0] for m in missing}), "created": created,
            "sample": [(uid, str(d)) for uid, d in missing[:10]]}


def achievement_audit(apply: bool = False, active_days: int = 120) -> dict:
    """For every reader active in the last `active_days`: achievements they
    qualify for but never got (paid now when apply -- Kitobcha through
    update_ball, no group Tabriklash), and ones they hold without
    qualifying any more (reported, never taken away)."""
    import datetime as _dt
    from tgbot.models import ConfirmationReport, TelegramProfile, UserAchievement
    from tgbot.services.achievements import ACHIEVEMENTS_RAW, compute_user_stats
    since = timezone.now() - _dt.timedelta(days=active_days)
    uids = set(ConfirmationReport.objects.filter(date__gte=since).values_list("user_id", flat=True))
    have = defaultdict(set)
    for uid, code in UserAchievement.objects.filter(user_id__in=uids).values_list("user_id", "code"):
        have[uid].add(code)
    points = {a["code"]: a.get("points", 0) for a in ACHIEVEMENTS_RAW}
    missing_by_code, extra_by_code = defaultdict(int), defaultdict(int)
    paid_users = paid_total = awarded = 0
    errors = 0
    for user in TelegramProfile.objects.filter(id__in=uids):
        try:
            stats = compute_user_stats(user)
        except Exception:
            errors += 1
            continue
        eligible = {a["code"] for a in ACHIEVEMENTS_RAW if a["cond"](stats)}
        missing = eligible - have[user.id]
        for code in have[user.id] - eligible:
            if code in points:
                extra_by_code[code] += 1
        for code in missing:
            missing_by_code[code] += 1
        if apply and missing:
            got = 0
            for code in missing:
                _, created = UserAchievement.objects.get_or_create(
                    user=user, code=code, defaults={"congratulated": True})
                if created:
                    awarded += 1
                    if points.get(code):
                        got += user.update_ball(True, points[code], reason="achievement")
            if got:
                paid_users += 1
                paid_total += got
    return {"active_users": len(uids), "errors": errors,
            "missing": dict(sorted(missing_by_code.items(), key=lambda kv: -kv[1])),
            "missing_total": sum(missing_by_code.values()),
            "extra": dict(sorted(extra_by_code.items(), key=lambda kv: -kv[1])),
            "applied": {"awarded": awarded, "users_paid": paid_users, "kitobcha": paid_total} if apply else None}


def game_reward_audit(days: int = 14) -> dict:
    """Finished live games of the last `days` that were never settled, and
    scores with points but no reward -- the two ways a prize goes missing."""
    import datetime as _dt
    from django.apps import apps
    since = timezone.now() - _dt.timedelta(days=days)
    out = {}
    for game_model, score_model, score_field in (
        ("ChainGame", "ChainScore", "points"), ("FeudGame", "FeudScore", "points"),
        ("EmojiGame", "EmojiScore", "points"), ("WisdomGame", "WisdomScore", "points"),
        ("DetectiveGame", "DetectiveScore", "points"), ("QuizGame", "QuizScore", "points"),
        ("AuthorGame", "AuthorEntry", None),
    ):
        try:
            G = apps.get_model("tgbot", game_model)
            S = apps.get_model("tgbot", score_model)
        except LookupError:
            continue
        ended = G.objects.filter(ends_at__gte=since, ends_at__lt=timezone.now())
        unsettled = ended.filter(rewarded=False).count()
        unpaid = 0
        if score_field:
            unpaid = S.objects.filter(game__in=ended.filter(rewarded=True), **{f"{score_field}__gt": 0},
                                      reward=0).count()
        out[game_model] = {"ended": ended.count(), "unsettled": unsettled, "scores_without_reward": unpaid}
    return out


def restore_achievements(rows, apply: bool) -> dict:
    """Achievements the old server had awarded that the move lost (645 per
    the restore notes): the cabinet showed them gone. Brought back as rows
    only, already congratulated and unpaid -- the 2026-10-13 data restore
    re-credited their Kitobcha through the ledger.

    `rows` = [{"telegram_id", "code", "awarded_at"}] from the old final dump."""
    from django.utils.dateparse import parse_datetime
    from tgbot.models import TelegramProfile, UserAchievement
    tg_ids = {int(r["telegram_id"]) for r in rows}
    pid = dict(TelegramProfile.objects.filter(telegram_id__in=tg_ids).values_list("telegram_id", "id"))
    have = set(UserAchievement.objects.filter(user_id__in=pid.values()).values_list("user_id", "code"))
    missing = []
    for r in rows:
        uid = pid.get(int(r["telegram_id"]))
        if uid and (uid, r["code"]) not in have:
            missing.append((uid, r["code"], r.get("awarded_at")))
            have.add((uid, r["code"]))
    created = 0
    if apply and missing:
        with transaction.atomic():
            before = UserAchievement.objects.count()
            UserAchievement.objects.bulk_create(
                [UserAchievement(user_id=uid, code=code, congratulated=True) for uid, code, _ in missing],
                ignore_conflicts=True)
            created = UserAchievement.objects.count() - before
            # awarded_at is auto_now_add, so the original date goes in afterwards.
            for uid, code, at in missing:
                when = parse_datetime(at) if at else None
                if when:
                    UserAchievement.objects.filter(user_id=uid, code=code).update(awarded_at=when)
    return {"matched_users": len(pid), "missing": len(missing),
            "users": len({m[0] for m in missing}), "created": created}


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


# ── One-off Kitobcha credits ───────────────────────────────────────────────

def kitobcha_credit(rows, tag: str, apply: bool, notify_text: str = "") -> dict:
    """Credit fixed amounts owed to named readers, once per reader per `tag`.

    Used for auction #26 on the old server: it was due 09-20 but the server
    stopped on 09-18, so it never settled and nobody got their bids back.
    `rows` = [{"telegram_id", "amount"}] worked out from the old final dump
    (kept outside the public repo). The ledger row carrying `tag` is the
    marker: a second run credits nobody twice. `notify_text` (optional, may
    use {amount} and {balance}) is sent to each credited reader."""
    import os

    import requests
    from tgbot.models import KitobchaLedger, TelegramProfile

    tag = tag[:40]
    out = []
    for r in rows:
        tg, amount = int(r["telegram_id"]), int(r["amount"])
        p = TelegramProfile.objects.filter(telegram_id=tg).first()
        row = {"telegram_id": tg, "amount": amount, "found": bool(p),
               "name": p.full_name if p else None, "balance": int(p.ball or 0) if p else None,
               "done_before": bool(p and KitobchaLedger.objects.filter(user=p, reason=tag).exists())}
        if apply and p and amount > 0 and not row["done_before"]:
            with transaction.atomic():
                q = TelegramProfile.objects.select_for_update().get(id=p.id)
                if not KitobchaLedger.objects.filter(user=q, reason=tag).exists():
                    q.ball = (q.ball or 0) + amount
                    q.save(update_fields=["ball"])
                    KitobchaLedger.objects.create(user=q, delta=amount, reason=tag)
                    row["credited"] = True
                    row["balance"] = int(q.ball)
            if row.get("credited") and notify_text:
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{os.environ.get('API_TOKEN', '')}/sendMessage",
                        data={"chat_id": tg, "parse_mode": "HTML",
                              "text": notify_text.format(amount=f"{amount:,}".replace(",", " "),
                                                         balance=f"{row['balance']:,}".replace(",", " "))},
                        timeout=10)
                except Exception as e:
                    row["notify_error"] = str(e)[:80]
        out.append(row)
    return {"tag": tag, "rows": out,
            "owed_total": sum(r["amount"] for r in out if r["found"] and not r["done_before"]),
            "credited_total": sum(r["amount"] for r in out if r.get("credited"))}


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
