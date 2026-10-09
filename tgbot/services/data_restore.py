"""Give users back what the server move lost, on top of what they have now.

Production moved to a new server that was started from an older copy of the
database, so everything users earned or bought after that copy -- up to the
moment the old server stopped -- was missing. `run_restore` takes a snapshot of
the OLD database (built off-server from its dump; it carries only what this
needs, keyed by telegram_id) and puts the difference back without touching
anything that has happened since:

  Kitobcha  every old ledger row the server does not have is summed per user
            and credited as one "restore:<tag>" ledger row. Never negative: a
            user who spent more than they earned in the gap is not charged.
  Premium   the days a user had left when the old server stopped are resumed
            from today, on top of any Premium bought since.
  Library   reading progress is raised to the old values; catalog books and
            profiles that only existed on the old server are re-added.
  Reports   reading reports missing from the server are re-added, so the
            leaderboards count them again.

Idempotent: a second run, or a later run with a newer snapshot, only adds what
is still missing. Matching relies on the server's copy of the old rows keeping
their exact timestamps; if too few of them line up the apply is refused, since
every row would otherwise look missing and be paid twice.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone as dt_tz
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from tgbot.models import (
    BooksToRead, ConfirmationReport, GlobalBook, Group, KitobchaLedger, Payment,
    Region, TelegramProfile,
)

PREM = "restore_prem:"
MONO = ("max_page_reached", "credited_pages", "active_seconds", "page_reward_total_granted", "current_page")
# Below this share of matching rows the server's copy is not lined up with the
# snapshot (different timestamps or a different database) and nothing is applied.
MIN_MATCH_RATIO = 0.95


class RestoreRefused(Exception):
    pass


def _parse(s):
    return datetime.fromisoformat(s).replace(tzinfo=dt_tz.utc)


def _key(dt):
    return dt.astimezone(dt_tz.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _merge(a, b):
    """Several old rows can describe the same book for one user; keep the
    furthest progress of each field so no row undoes another."""
    out = dict(a)
    for f in MONO + ("total_pages",):
        out[f] = max(a[f], b[f])
    out["fee_charged"] = a["fee_charged"] or b["fee_charged"]
    out["topped_up"] = a["topped_up"] or b["topped_up"]
    out["global_book_title"] = a["global_book_title"] or b["global_book_title"]
    return out


def run_restore(snap, apply=False, with_reports=True, stopped_at=None):
    tag = snap["tag"]
    rest_reason = f"restore:{tag}"[:40]
    since_dt = _parse(snap["since"] + "T00:00:00.000000")
    taken_dt = _parse(snap["taken_at"])
    stop_dt = _parse(stopped_at) if stopped_at else taken_dt
    today = timezone.localdate()
    stop_date = timezone.localtime(stop_dt).date()

    snap_users = {u["tg"]: u for u in snap["users"]}
    profiles = defaultdict(list)
    for p in TelegramProfile.objects.filter(telegram_id__in=list(snap_users)).order_by("id"):
        profiles[p.telegram_id].append(p)

    def profile_for(t):
        ps = profiles.get(t)
        if not ps:
            return None
        reg = [p for p in ps if p.is_registered]
        return (reg or ps)[0]

    # ── Kitobcha ─────────────────────────────────────────────────────────
    present = Counter()
    post_sum, already, prem_already = defaultdict(int), defaultdict(int), defaultdict(int)
    server_window_rows = 0
    for t, c, d, r in KitobchaLedger.objects.filter(
            user__telegram_id__in=list(snap_users), created_at__gte=since_dt,
    ).values_list("user__telegram_id", "created_at", "delta", "reason"):
        r = r or ""
        if r.startswith("restore:"):
            already[t] += d
        elif r.startswith(PREM):
            prem_already[t] += int(r[len(PREM):] or 0)
        elif c > taken_dt:
            post_sum[t] += d
        else:
            present[(t, _key(c), d, r)] += 1
            server_window_rows += 1

    net, matched, missing_rows, last_matched = defaultdict(int), 0, 0, None
    for t, c, d, r in snap["ledger"]:
        k = (t, c, d, r)
        if present[k] > 0:
            present[k] -= 1
            matched += 1
            last_matched = max(last_matched or c, c)
        else:
            net[t] += d
            missing_rows += 1
    match_ratio = (matched / server_window_rows) if server_window_rows else 0.0

    credit = {t: max(0, n - already[t]) for t, n in net.items()}
    pay = {t: c for t, c in credit.items() if c > 0}
    bal_check = {}
    for t in net:
        p = profile_for(t)
        if p:
            start = Decimal(p.ball) - post_sum[t] - already[t]
            bal_check[t] = int(Decimal(snap_users[t]["ball"] or 0) - start)
    mism = [t for t in pay if t in bal_check and abs(bal_check[t] - (net[t] - already[t])) > 1]

    # ── Premium ──────────────────────────────────────────────────────────
    snap_end, snap_pay_keys = {}, defaultdict(set)
    for t, _c, amount, start, end in snap["payments"]:
        e = datetime.fromisoformat(end).date()
        snap_end[t] = max(snap_end.get(t, e), e)
        snap_pay_keys[t].add((start, end, str(Decimal(amount).quantize(Decimal("0.01")))))
    srv_old_end = {}
    for t, s, e, a in Payment.objects.filter(
            user__telegram_id__in=list(snap_end), status="paid",
    ).values_list("user__telegram_id", "start_date", "end_date", "amount"):
        if (s.isoformat(), e.isoformat(), str(Decimal(a).quantize(Decimal("0.01")))) in snap_pay_keys[t]:
            srv_old_end[t] = max(srv_old_end.get(t, e), e)
    owed = {}
    for t, e in snap_end.items():
        left = (e - stop_date).days
        if left <= 0:
            continue
        still = max(0, (srv_old_end[t] - today).days) if t in srv_old_end else 0
        o = left - still - prem_already[t]
        if o > 0:
            owed[t] = o

    # ── Library ──────────────────────────────────────────────────────────
    srv_books = {b.title: b for b in GlobalBook.objects.all()}
    books_add = [b for b in snap["global_books"] if b["title"] not in srv_books]
    gb_titles = set(srv_books) | {b["title"] for b in books_add}

    def gb(title):
        # Only a catalog book that will exist after this run can tie two rows
        # together; otherwise the created row is matched by its title alone.
        return type("GB", (), {"title": title})() if title and title in gb_titles else None

    class Pending:
        def __init__(self, s):
            self.s, self.id = s, None
            self.title, self.is_audio = s["title"], s["is_audio"]
            self.global_book = gb(s["global_book_title"])

    btr = defaultdict(list)
    for row in BooksToRead.objects.filter(
            user__telegram_id__in=list(snap_users)).select_related("global_book", "user"):
        btr[row.user.telegram_id].append(row)

    def find_btr(t, s):
        for row in btr.get(t, []):
            if s["global_book_title"] and row.global_book and row.global_book.title == s["global_book_title"]:
                return row
        for row in btr.get(t, []):
            if row.title == s["title"] and row.is_audio == s["is_audio"]:
                return row
        return None

    raise_by_row, row_of, pending = {}, {}, []
    for s in snap["books_to_read"]:
        row = find_btr(s["tg"], s)
        if row is None:
            pend = Pending(s)
            pending.append(pend)
            btr[s["tg"]].append(pend)
        elif isinstance(row, Pending):
            row.s = _merge(row.s, s)
            row.global_book = row.global_book or gb(row.s["global_book_title"])
        else:
            raise_by_row[row.id] = _merge(raise_by_row[row.id], s) if row.id in raise_by_row else s
            row_of[row.id] = row
    for t in list(btr):
        btr[t] = [r for r in btr[t] if not isinstance(r, Pending)]
    progress_new = [p.s for p in pending]
    progress_raise = []
    for rid, s in raise_by_row.items():
        row = row_of[rid]
        changes = {f: s[f] for f in MONO if s[f] > getattr(row, f)}
        if s["fee_charged"] and not row.fee_charged:
            changes["fee_charged"] = True
        if s["topped_up"] and not row.topped_up:
            changes["topped_up"] = True
        if changes:
            progress_raise.append((row, changes))

    # ── Reports ──────────────────────────────────────────────────────────
    rep_present = Counter(
        (t, _key(d), p) for t, d, p in ConfirmationReport.objects.filter(
            user__telegram_id__in=list(snap_users), date__gte=since_dt, date__lte=taken_dt,
        ).values_list("user__telegram_id", "date", "pages_read")
    )
    reports_add = []
    for r in snap["reports"]:
        k = (r["tg"], r["date"], r["pages_read"])
        if rep_present[k] > 0:
            rep_present[k] -= 1
        else:
            reports_add.append(r)
    if not with_reports:
        reports_add = []

    # ── Per-user result ──────────────────────────────────────────────────
    per = defaultdict(lambda: {"kitobcha": 0, "premium_days": 0, "books_new": 0,
                               "books_raised": 0, "reports": 0, "pages": 0})
    for t, c in pay.items():
        per[t]["kitobcha"] = c
    for t, d in owed.items():
        per[t]["premium_days"] = d
    for s in progress_new:
        per[s["tg"]]["books_new"] += 1
    for row, _ch in progress_raise:
        per[row.user.telegram_id]["books_raised"] += 1
    for r in reports_add:
        per[r["tg"]]["reports"] += 1
        per[r["tg"]]["pages"] += r["pages_read"] or 0
    create_users = sorted(t for t in per if not profile_for(t))

    summary = {
        "tag": tag, "taken_at": snap["taken_at"], "stop_date": stop_date.isoformat(),
        "today": today.isoformat(), "applied": False,
        "server_copy_ends_at": last_matched, "server_window_rows": server_window_rows,
        "matched_rows": matched, "match_ratio": round(match_ratio, 4),
        "missing_ledger_rows": missing_rows,
        "kitobcha_total": sum(pay.values()), "kitobcha_users": len(pay),
        "spent_more_than_earned": sum(1 for t, n in net.items() if n - already[t] < 0),
        "balance_check_mismatch": len(mism),
        "premium_days_total": sum(owed.values()), "premium_users": len(owed),
        "progress_new": len(progress_new), "progress_raised": len(progress_raise),
        "books_missing": len(books_add), "reports_missing": len(reports_add),
        "profiles_to_create": len(create_users),
    }
    users_out = [
        {"tg": t, "name": snap_users[t]["full_name"], "on_server": bool(profile_for(t)),
         "balance_check": bal_check.get(t), "ledger_net": net.get(t, 0), **v}
        for t, v in per.items()
    ]
    if not apply:
        return {"summary": summary, "users": users_out}

    if server_window_rows < 100 or match_ratio < MIN_MATCH_RATIO:
        raise RestoreRefused(
            f"only {matched}/{server_window_rows} of the server's old ledger rows match the "
            f"snapshot -- timestamps do not line up, applying would pay everything twice")
    if len(mism) > max(5, len(pay) // 10):
        raise RestoreRefused(f"balance cross-check disagrees for {len(mism)} of {len(pay)} users")

    done = Counter()
    with transaction.atomic():
        regions = set(Region.objects.values_list("id", flat=True))
        groups = set(Group.objects.values_list("id", flat=True))
        for t in create_users:
            u = snap_users[t]
            p = TelegramProfile.objects.create(
                telegram_id=t, username=u["username"], language=u["language"],
                full_name=u["full_name"], phone_number=u["phone_number"],
                is_registered=u["is_registered"], gender=u["gender"], age_range=u["age_range"],
                region_id=int(u["region_id"]) if u["region_id"] and int(u["region_id"]) in regions else None,
                group_id=int(u["group_id"]) if u["group_id"] and int(u["group_id"]) in groups else None,
            )
            profiles[t] = [p]
            done["profiles"] += 1

        for t, c in pay.items():
            p = profile_for(t)
            TelegramProfile.objects.filter(id=p.id).update(ball=F("ball") + Decimal(c))
            KitobchaLedger.objects.create(user=p, delta=c, reason=rest_reason)
            done["kitobcha"] += c

        for t, days in owed.items():
            p = profile_for(t)
            Payment.grant_or_extend(p, days=days, amount=0)
            KitobchaLedger.objects.create(user=p, delta=0, reason=f"{PREM}{days}")
            done["premium_days"] += days

        for b in books_add:
            if GlobalBook.objects.filter(title=b["title"]).exists():
                continue
            g = GlobalBook(title=b["title"], author=b["author"], description=b["description"] or "",
                           language=b["language"] or "uz", is_premium_only=b["is_premium_only"])
            g.cover.name = b["cover"] or None
            g.pdf_file.name = b["pdf_file"] or None
            g.audio_file.name = b["audio_file"] or None
            g.save()
            srv_books[g.title] = g
            done["books"] += 1

        for row, changes in progress_raise:
            BooksToRead.objects.filter(id=row.id).update(**changes)
            done["progress_raised"] += 1
        for s in progress_new:
            row = BooksToRead.objects.create(
                user=profile_for(s["tg"]),
                global_book=srv_books.get(s["global_book_title"]) if s["global_book_title"] else None,
                title=s["title"], is_audio=s["is_audio"], total_pages=s["total_pages"],
                current_page=s["current_page"], fee_charged=s["fee_charged"],
                max_page_reached=s["max_page_reached"], credited_pages=s["credited_pages"],
                active_seconds=s["active_seconds"],
                page_reward_total_granted=s["page_reward_total_granted"], topped_up=s["topped_up"],
            )
            btr[s["tg"]].append(row)
            done["progress_new"] += 1

        for r in reports_add:
            rep = ConfirmationReport.objects.create(
                user=profile_for(r["tg"]), date=_parse(r["date"]), book=r["book"],
                pages_read=r["pages_read"], spent_time=r["spent_time"], conclusion=r["conclusion"],
                is_audio=r["is_audio"], minutes_listened=r["minutes_listened"],
                reading_day=r["reading_day"],
            )
            rows = [x for x in btr.get(r["tg"], []) for title, audio in r["books"]
                    if x.title == title and x.is_audio == audio]
            if rows:
                rep.books.add(*rows)
            done["reports"] += 1

    summary["applied"] = True
    summary["done"] = dict(done)
    # Balances after the restore, for the personal "here is what came back" note.
    ids = {u["tg"]: profile_for(u["tg"]).id for u in users_out if profile_for(u["tg"])}
    after = dict(TelegramProfile.objects.filter(id__in=list(ids.values())).values_list("id", "ball"))
    for u in users_out:
        u["balance_after"] = int(after.get(ids.get(u["tg"]), 0))
    return {"summary": summary, "users": users_out}
