"""Kitob Zanjiri — live "missing letter" game logic.

A round shows a real book title with 1-2 letters blanked out; players race to
type the missing letter(s), in left-to-right order. The FIRST correct guess
wins the round immediately (+10, no crowd vote needed — the answer is a known
fact, not an opinion), and a new round starts right away with a different book
title. Titles are drawn from the real `GlobalBook` catalog, no repeats within
a game.

Concurrency: every write locks the ChainGame row (select_for_update), so under
simultaneous guesses exactly one submission wins the round.

Field reuse note: this replaces the old free-text "book chain" mechanic
in-place, reusing the same nullable JSON columns instead of adding new ones —
`pending` now holds the in-progress round (book/masked title/blanks) instead
of a vote candidate, `chain` holds solved-round history instead of accepted
chain links, `used_norms` holds used GlobalBook ids instead of normalized
words. `current_letter`, `rejected_norms` and ChainScore's `strikes`/`kicked`
are no longer written — there's nothing to vote down or strike in the new
mechanic, since every answer is checked against a known correct title.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum, Count
from django.utils import timezone

from tgbot.models import ChainGame, ChainScore, TelegramProfile, GlobalBook
from tgbot.services.chain_text import normalize

ENTRY_FEE = 25  # Kitobcha to join a game (charged once, on first attempt)
POINTS_PER_ROUND = 10
DEFAULT_DURATION_MIN = 10
LEAD_SECONDS = 30  # lobby countdown after the announcement, so everyone can join
MIN_TITLE_LETTERS = 4  # skip titles too short to blank meaningfully

REWARD_TIERS = {0: 300, 1: 200, 2: 100}
PARTICIPATION = 30  # guest Kitobcha for EVERY participant who didn't place


def _add_ball_flat(user, amount: int) -> int:
    """Add Kitobcha WITHOUT the premium 2× multiplier — competition prizes are
    strictly by rank (otherwise a Premium 2nd place could out-earn a 1st)."""
    with transaction.atomic():
        user.refresh_from_db(fields=["ball"])
        user.ball = (user.ball or 0) + amount
        user.save(update_fields=["ball"])
    return amount


def charge_entry_fee(profile, amount: int = ENTRY_FEE) -> bool:
    """Deduct `amount` Kitobcha from profile.ball if affordable (defaults to
    ENTRY_FEE=25). Shared by every live game so the join-cost logic is
    consistent; newer games pass a higher `amount` for their pricier entry."""
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=profile.id)
        if int(p.ball or 0) < amount:
            return False
        p.ball = p.ball - amount
        p.save(update_fields=["ball"])
    return True


def _pick_round(used_book_ids) -> dict | None:
    """Pick a random GlobalBook not already used this game, blank 1-2 of its
    letters. Falls back to allowing repeats if every eligible book has been
    used (small catalog / long game) rather than stalling the game."""
    all_books = [
        (i, t) for i, t in GlobalBook.objects.values_list("id", "title")
        if sum(c.isalpha() for c in t) >= MIN_TITLE_LETTERS
    ]
    if not all_books:
        return None
    fresh = [b for b in all_books if b[0] not in (used_book_ids or [])]
    book_id, title = random.choice(fresh or all_books)

    letter_positions = [i for i, c in enumerate(title) if c.isalpha()]
    n_blanks = min(random.choice([1, 2]), len(letter_positions))
    positions = sorted(random.sample(letter_positions, n_blanks))
    blanks = [{"pos": p, "letter": title[p]} for p in positions]
    masked = list(title)
    for b in blanks:
        masked[b["pos"]] = "_"

    return {
        "book_id": book_id,
        "title": title,
        "masked": "".join(masked),
        "blanks": blanks,
        "started_at": timezone.now().isoformat(),
    }


# ── Game lifecycle ───────────────────────────────────────────────────────────
def create_scheduled_game(lead_seconds: int = LEAD_SECONDS,
                          duration_minutes: int = DEFAULT_DURATION_MIN,
                          title: str = "Kitob Zanjiri") -> ChainGame:
    """Create a game that opens after a short lobby (default 30s) so players who
    just saw the announcement can get ready. It auto-flips to live at starts_at
    (see get_or_activate_live_game), which is also when the first round starts."""
    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    return ChainGame.objects.create(
        title=title,
        status=ChainGame.STATUS_SCHEDULED,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=duration_minutes),
        chain=[],
        used_norms=[],
    )


def get_or_activate_live_game():
    """Return the currently-live game, activating a scheduled one whose window
    has opened (and starting its first round). Does NOT finish expired games
    (see finalize)."""
    now = timezone.now()
    g = ChainGame.objects.filter(status=ChainGame.STATUS_LIVE).order_by("-starts_at").first()
    if g:
        return g
    scheduled = (
        ChainGame.objects
        .filter(status=ChainGame.STATUS_SCHEDULED, starts_at__lte=now, ends_at__gte=now)
        .order_by("starts_at")
        .first()
    )
    if not scheduled:
        return None
    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=scheduled.id)
        if g.status == ChainGame.STATUS_SCHEDULED:
            g.status = ChainGame.STATUS_LIVE
            if not g.pending:
                g.pending = _pick_round(g.used_norms or [])
            g.save(update_fields=["status", "pending", "updated_at"])
    return g


def latest_game():
    return ChainGame.objects.order_by("-starts_at").first()


def _accept_round(g: ChainGame, round_: dict, profile) -> dict:
    """Commit the winning guess: score it, record the solved round, start the
    next one. Caller must hold the row lock (select_for_update) on `g`."""
    solved = g.chain or []
    solved.append({
        "idx": len(solved),
        "title": round_["title"],
        "masked": round_["masked"],
        "user_id": profile.id,
        "name": (profile.full_name or "Kitobxon")[:40],
        "at": timezone.now().isoformat(),
    })
    used = list(g.used_norms or [])
    used.append(round_["book_id"])
    g.chain = solved
    g.used_norms = used
    g.pending = _pick_round(used)
    g.save(update_fields=["chain", "used_norms", "pending", "updated_at"])

    score, _created = ChainScore.objects.get_or_create(game=g, user_id=profile.id)
    score.points = (score.points or 0) + POINTS_PER_ROUND
    score.links = (score.links or 0) + 1
    score.save(update_fields=["points", "links", "updated_at"])
    return {"title": round_["title"], "gained": POINTS_PER_ROUND}


def submit(game_id: int, profile, guess: str) -> dict:
    """Submit a guess for the current round's missing letter(s). Correct
    guesses score immediately and start a new round; wrong guesses just get
    rejected so the round stays open for someone else."""
    guess_norm = normalize(guess).replace(" ", "")
    if not guess_norm:
        return {"ok": False, "error": "empty"}

    # Optimistic, LOCK-FREE pre-check: sheds the vast majority of racing / late /
    # wrong submissions without contending on the game row lock, keeping the web
    # responsive during a big live game (only real winners take the lock below).
    g0 = ChainGame.objects.filter(id=game_id).first()
    now = timezone.now()
    if not g0 or not (g0.status == ChainGame.STATUS_LIVE and g0.starts_at <= now <= g0.ends_at):
        return {"ok": False, "error": "not_live"}

    # Entry fee: joining this competition costs ENTRY_FEE Kitobcha, charged once
    # on the first attempt.
    score0, created0 = ChainScore.objects.get_or_create(game_id=g0.id, user=profile)
    if created0:
        if not charge_entry_fee(profile):
            ChainScore.objects.filter(id=score0.id).delete()  # undo the join
            return {"ok": False, "error": "insufficient_balance", "need": ENTRY_FEE}

    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=game_id)
        now = timezone.now()
        if not (g.status == ChainGame.STATUS_LIVE and g.starts_at <= now <= g.ends_at):
            return {"ok": False, "error": "not_live"}

        round_ = g.pending
        if not round_:
            # Shouldn't normally happen (activation always starts a round), but
            # don't stall the game if it does.
            round_ = _pick_round(g.used_norms or [])
            if not round_:
                return {"ok": False, "error": "no_books"}
            g.pending = round_
            g.save(update_fields=["pending", "updated_at"])

        expected = normalize("".join(b["letter"] for b in round_["blanks"])).replace(" ", "")
        if guess_norm != expected:
            return {"ok": False, "error": "wrong_guess"}

        result = _accept_round(g, round_, profile)
        return {"ok": True, **result}


def finalize(game_id: int) -> dict | None:
    """Mark a game finished and pay Kitobcha to the top scorers (idempotent)."""
    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        if g.pending:
            g.pending = None
            g.save(update_fields=["pending", "updated_at"])
        if g.status != ChainGame.STATUS_FINISHED:
            g.status = ChainGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    # Option A — only players who actually SCORED are rewarded. Freeloaders
    # (0 points) get nothing and forfeit their entry fee. Top-3 scorers get
    # the tiered prize; every other scorer gets PARTICIPATION.
    scores = list(
        ChainScore.objects.filter(game=g)
        .select_related("user")
        .order_by("-points", "created_at")
    )
    winners = []
    for i, s in enumerate(scores):
        if s.points <= 0:
            reward = 0
        elif i < 3:
            reward = REWARD_TIERS[i]
        else:
            reward = PARTICIPATION
        if reward and not s.rewarded:
            applied = _add_ball_flat(s.user, reward)
            s.rewarded = True
            s.reward = applied
            s.save(update_fields=["rewarded", "reward", "updated_at"])
        elif reward:
            applied = s.reward or reward
        else:
            applied = 0
        winners.append({
            "rank": i + 1,
            "user_id": s.user_id,
            "telegram_id": s.user.telegram_id,
            "name": s.user.full_name or "Kitobxon",
            "points": s.points,
            "links": s.links,
            "reward": applied,
        })

    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    return {"winners": winners, "players": len(scores), "links": len(g.chain or [])}


def finalize_due_games() -> list:
    now = timezone.now()
    out = []
    for g in ChainGame.objects.filter(status=ChainGame.STATUS_LIVE, ends_at__lt=now):
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


# ── State for the Mini App ───────────────────────────────────────────────────
def _leaderboard(game, limit: int = 10, include_all: bool = False):
    qs = ChainScore.objects.filter(game=game).select_related("user")
    if not include_all:
        qs = qs.filter(points__gt=0)  # live board: only those who've scored
    rows = qs.order_by("-points", "created_at")[:limit]
    return [
        {
            "name": r.user.full_name or "Kitobxon",
            "points": r.points,
            "links": r.links,
            "reward": r.reward or 0,
        }
        for r in rows
    ]


def _lifetime_stats(profile) -> dict:
    """Cumulative Kitob Zanjiri stats for one user across every game played."""
    from django.db.models import Max
    # NB: alias names must NOT shadow the field name — an alias `points` makes
    # Max("points") resolve to the aggregate instead of the column (FieldError).
    agg = ChainScore.objects.filter(user=profile).aggregate(
        games=Count("id"), pts=Sum("points"), lnk=Sum("links"), best=Max("points"),
    )
    return {
        "games": agg["games"] or 0,
        "points": int(agg["pts"] or 0),
        "links": int(agg["lnk"] or 0),
        "best": int(agg["best"] or 0),
    }


def _history(limit: int = 6) -> list:
    """Recent finished games with their winner, for the history screen."""
    out = []
    for g in ChainGame.objects.filter(status=ChainGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        top = (
            ChainScore.objects.filter(game=g, points__gt=0)
            .select_related("user").order_by("-points").first()
        )
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "winner": (top.user.full_name if top else "—") or "—",
            "winner_points": (top.points if top else 0),
            "players": ChainScore.objects.filter(game=g).count(),
            "links": len(g.chain or []),
        })
    return out


def _cached_leaderboard(game, limit, include_all):
    """Leaderboard is identical for every poller — compute it at most once every
    2s and share it across all clients (via Redis) to cut per-poll DB load."""
    from django.core.cache import cache
    key = f"chain:lb:{game.id}:{limit}:{int(include_all)}"
    try:
        v = cache.get(key)
        if v is not None:
            return v
    except Exception:
        pass
    v = _leaderboard(game, limit=limit, include_all=include_all)
    try:
        cache.set(key, v, 2)
    except Exception:
        pass
    return v


def state_payload(profile) -> dict:
    """Everything the game page needs in one poll."""
    now = timezone.now()
    g = get_or_activate_live_game()
    if not g:
        g = latest_game()
    if not g:
        return {"ok": True, "status": "none", "lifetime": _lifetime_stats(profile),
                "history": _history()}

    solved = g.chain or []
    recent = [
        {
            "idx": c.get("idx"),
            "title": c.get("title", ""),
            "masked": c.get("masked", ""),
            "name": c.get("name", ""),
            "mine": c.get("user_id") == profile.id,
        }
        for c in reversed(solved[-14:])
    ]
    my = ChainScore.objects.filter(game=g, user=profile).first()

    if g.status == ChainGame.STATUS_LIVE and g.starts_at <= now <= g.ends_at:
        status = "live"
        seconds = max(0, int((g.ends_at - now).total_seconds()))
    elif g.status == ChainGame.STATUS_SCHEDULED and now < g.starts_at:
        status = "scheduled"
        seconds = max(0, int((g.starts_at - now).total_seconds()))
    else:
        status = "finished"
        seconds = 0

    round_payload = None
    if status == "live" and g.pending:
        r = g.pending
        round_payload = {
            "masked": r.get("masked", ""),
            "blanks": len(r.get("blanks") or []),
        }

    finished = status == "finished"
    return {
        "ok": True,
        "status": status,
        "game_id": g.id,
        "title": g.title,
        "seconds": seconds,
        "chain_len": len(solved),
        "recent": recent,
        "round": round_payload,
        # Top 50; finished also includes every participant with their Kitobcha.
        "leaderboard": _cached_leaderboard(g, 50, finished),
        "your_points": (my.points if my else 0),
        "your_links": (my.links if my else 0),
        "your_reward": (my.reward if my else 0),
        "lifetime": _lifetime_stats(profile),
        "history": _history() if status != "live" else [],
    }
