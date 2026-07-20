"""Kitob Zanjiri — live "book chain" game logic.

A session shows a required starting letter; players race to submit a book title
or author name starting with that letter and not already used. The FIRST valid
submission for that letter becomes a "pending" candidate that goes to a crowd
vote (see `submit`/`vote_pending`): if it collects more than ACCEPT_VOTES_THRESHOLD-1
"to'g'ri" votes, or is ahead when the VOTE_WINDOW_SECONDS window closes, it's
accepted and the chain advances (+10, next letter). Otherwise it's rejected —
the letter stays open and the next person to submit for it becomes the new
candidate. No fixed dictionary: any text is accepted as a candidate, the crowd
vets it.

Concurrency: every write locks the ChainGame row (select_for_update), so under
simultaneous answers exactly one becomes the pending candidate.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum, Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tgbot.models import ChainGame, ChainScore, TelegramProfile
from tgbot.services.chain_text import normalize, first_letter, last_letter

ENTRY_FEE = 25  # Kitobcha to join a game (charged once, on first attempt)
POINTS_PER_LINK = 10
DEFAULT_DURATION_MIN = 10
LEAD_SECONDS = 30  # lobby countdown after the announcement, so everyone can join
VOTE_WINDOW_SECONDS = 10  # how long a pending candidate stays open to votes
ACCEPT_VOTES_THRESHOLD = 6  # more than 5 "to'g'ri" votes accepts immediately

# Letters that comfortably start Uzbek book/author names — used for the opening
# letter and as a fallback when a word ends in a hard/rare letter.
START_LETTERS = list("abdegijklmnopqrstuvyfh")

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


def charge_entry_fee(profile) -> bool:
    """Deduct ENTRY_FEE from profile.ball if affordable. Shared by every live
    game (Zanjiri/Ko'pchilik/Qal'a/Emoji) so the 25-Kitobcha join cost is
    consistent across all of them."""
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=profile.id)
        if int(p.ball or 0) < ENTRY_FEE:
            return False
        p.ball = p.ball - ENTRY_FEE
        p.save(update_fields=["ball"])
    return True


def _initial_letter() -> str:
    return random.choice(START_LETTERS)


def _next_letter(word_last: str) -> str:
    return word_last or random.choice(START_LETTERS)


# ── Game lifecycle ───────────────────────────────────────────────────────────
def create_scheduled_game(lead_seconds: int = LEAD_SECONDS,
                          duration_minutes: int = DEFAULT_DURATION_MIN,
                          title: str = "Kitob Zanjiri") -> ChainGame:
    """Create a game that opens after a short lobby (default 30s) so players who
    just saw the announcement can get ready. It auto-flips to live at starts_at
    (see get_or_activate_live_game)."""
    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    return ChainGame.objects.create(
        title=title,
        status=ChainGame.STATUS_SCHEDULED,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=duration_minutes),
        current_letter=_initial_letter(),
        chain=[],
        used_norms=[],
    )


def get_or_activate_live_game():
    """Return the currently-live game, activating a scheduled one whose window
    has opened. Does NOT finish expired games (see finalize)."""
    now = timezone.now()
    g = ChainGame.objects.filter(status=ChainGame.STATUS_LIVE).order_by("-starts_at").first()
    if g:
        return g
    pending = (
        ChainGame.objects
        .filter(status=ChainGame.STATUS_SCHEDULED, starts_at__lte=now, ends_at__gte=now)
        .order_by("starts_at")
        .first()
    )
    if not pending:
        return None
    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=pending.id)
        if g.status == ChainGame.STATUS_SCHEDULED:
            g.status = ChainGame.STATUS_LIVE
            if not g.current_letter:
                g.current_letter = _initial_letter()
            g.save(update_fields=["status", "current_letter", "updated_at"])
    return g


def latest_game():
    return ChainGame.objects.order_by("-starts_at").first()


def _mk_pending(profile, text: str, norm: str, ll: str, letter: str) -> dict:
    display = " ".join((text or "").strip().split())[:60]
    return {
        "norm": norm,
        "display": display,
        "user_id": profile.id,
        "name": (profile.full_name or "Kitobxon")[:40],
        "letter": letter,
        "last_letter": ll,
        "started_at": timezone.now().isoformat(),
        "yes": [],
        "no": [],
    }


def _pending_elapsed(pending: dict) -> float:
    started = parse_datetime(pending["started_at"])
    if started and timezone.is_naive(started):
        started = timezone.make_aware(started)
    return (timezone.now() - started).total_seconds()


def _accept_pending(g: ChainGame) -> dict:
    """Commit the pending candidate as a won link and advance the letter.
    Caller must hold the row lock (select_for_update) on `g`."""
    p = g.pending
    chain = g.chain or []
    chain.append({
        "idx": len(chain),
        "norm": p["norm"],
        "display": p["display"],
        "user_id": p["user_id"],
        "name": p["name"],
        "letter": p["letter"],
        "at": timezone.now().isoformat(),
    })
    used = list(g.used_norms or [])
    used.append(p["norm"])
    g.chain = chain
    g.used_norms = used
    g.current_letter = _next_letter(p.get("last_letter"))
    g.pending = None
    g.rejected_norms = []
    g.save(update_fields=[
        "chain", "used_norms", "current_letter", "pending", "rejected_norms", "updated_at",
    ])

    score, _ = ChainScore.objects.get_or_create(game=g, user_id=p["user_id"])
    score.points = (score.points or 0) + POINTS_PER_LINK
    score.links = (score.links or 0) + 1
    score.save(update_fields=["points", "links", "updated_at"])
    return {
        "accepted": True, "display": p["display"], "gained": POINTS_PER_LINK,
        "next_letter": g.current_letter, "user_id": p["user_id"],
    }


def _reject_pending(g: ChainGame) -> dict:
    """Drop the pending candidate — the letter stays open for the next
    submitter. Strikes the submitter; 3 strikes kicks them from the game."""
    p = g.pending
    rejected = list(g.rejected_norms or [])
    rejected.append(p["norm"])
    g.pending = None
    g.rejected_norms = rejected
    g.save(update_fields=["pending", "rejected_norms", "updated_at"])

    kicked_user = False
    score = ChainScore.objects.filter(game=g, user_id=p["user_id"]).first()
    if score:
        score.strikes = (score.strikes or 0) + 1
        if score.strikes >= 3 and not score.kicked:
            score.kicked = True
            kicked_user = True
        score.save(update_fields=["strikes", "kicked", "updated_at"])
    return {"accepted": False, "display": p["display"], "user_id": p["user_id"], "kicked_user": kicked_user}


def _resolve_if_expired(g: ChainGame) -> dict | None:
    """If the pending candidate's vote window has elapsed, resolve it now:
    accepted if it has more "to'g'ri" than "noto'g'ri" votes, else rejected.
    Caller must hold the row lock. Returns the resolution, or None if there's
    nothing to resolve yet."""
    if not g.pending:
        return None
    if _pending_elapsed(g.pending) < VOTE_WINDOW_SECONDS:
        return None
    yes = len(g.pending.get("yes") or [])
    no = len(g.pending.get("no") or [])
    if yes > no:
        return _accept_pending(g)
    return _reject_pending(g)


def submit(game_id: int, profile, text: str) -> dict:
    """Submit a candidate answer for the current letter. The FIRST valid
    submission becomes the pending candidate and goes to a crowd vote (see
    `vote_pending`) — it does not score immediately. Any later submission while
    a vote is in progress is rejected with `vote_in_progress`."""
    norm = normalize(text)
    fl = first_letter(text)
    ll = last_letter(text)
    if not norm or not fl or len(norm) < 2:
        return {"ok": False, "error": "empty"}

    # Optimistic, LOCK-FREE pre-check: sheds the vast majority of racing / late /
    # wrong submissions without contending on the game row lock, keeping the web
    # responsive during a big live game (only real candidates take the lock below).
    g0 = ChainGame.objects.filter(id=game_id).first()
    now = timezone.now()
    if not g0 or not (g0.status == ChainGame.STATUS_LIVE and g0.starts_at <= now <= g0.ends_at):
        return {"ok": False, "error": "not_live"}

    # Entry fee: joining this competition costs ENTRY_FEE Kitobcha, charged once
    # on the first attempt. The crowd vets every candidate via a vote before it
    # scores; a 3× rejected player is kicked and forfeits reward + entry fee.
    score0, created0 = ChainScore.objects.get_or_create(game_id=g0.id, user=profile)
    if created0:
        if not charge_entry_fee(profile):
            ChainScore.objects.filter(id=score0.id).delete()  # undo the join
            return {"ok": False, "error": "insufficient_balance", "need": ENTRY_FEE}

    if score0.kicked:
        return {"ok": False, "error": "kicked"}
    if g0.current_letter and fl != g0.current_letter:
        return {"ok": False, "error": "wrong_letter", "required": g0.current_letter}
    if norm in (g0.used_norms or []):
        return {"ok": False, "error": "already_used"}

    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=game_id)
        now = timezone.now()
        if not (g.status == ChainGame.STATUS_LIVE and g.starts_at <= now <= g.ends_at):
            return {"ok": False, "error": "not_live"}

        # Fair-play: a player whose candidates were rejected 3× is out of the game.
        mine = ChainScore.objects.filter(game=g, user=profile).first()
        if mine and mine.kicked:
            return {"ok": False, "error": "kicked"}

        # A vote may have just expired — resolve it before deciding what this
        # submission means (acceptance/rejection may change the current letter).
        _resolve_if_expired(g)

        if g.pending:
            return {"ok": False, "error": "vote_in_progress"}

        required = g.current_letter
        if required and fl != required:
            return {"ok": False, "error": "wrong_letter", "required": required}
        if norm in (g.used_norms or []):
            return {"ok": False, "error": "already_used"}
        if norm in (g.rejected_norms or []):
            return {"ok": False, "error": "already_rejected"}

        g.pending = _mk_pending(profile, text, norm, ll, required)
        g.save(update_fields=["pending", "updated_at"])
        return {
            "ok": True, "pending": True, "display": g.pending["display"],
            "seconds": VOTE_WINDOW_SECONDS,
        }


def vote_pending(game_id: int, profile, accept: bool) -> dict:
    """Vote the pending candidate 'to'g'ri' (accept) or 'noto'g'ri' (reject).
    Immediately accepts once ACCEPT_VOTES_THRESHOLD 'to'g'ri' votes are in;
    otherwise waits for the window to close (see `_resolve_if_expired`). You
    can't vote your own candidate, nor vote twice."""
    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=game_id)

        resolved = _resolve_if_expired(g)
        if resolved is not None:
            return {"ok": True, "resolved": True, **resolved}

        if not g.pending:
            return {"ok": False, "error": "no_pending"}
        if g.pending.get("user_id") == profile.id:
            return {"ok": False, "error": "own_pending"}

        yes = list(g.pending.get("yes") or [])
        no = list(g.pending.get("no") or [])
        if profile.id in yes or profile.id in no:
            return {"ok": True, "already": True, "yes": len(yes), "no": len(no)}

        if accept:
            yes.append(profile.id)
        else:
            no.append(profile.id)
        g.pending["yes"] = yes
        g.pending["no"] = no

        if len(yes) >= ACCEPT_VOTES_THRESHOLD:
            resolved = _accept_pending(g)
            return {"ok": True, "resolved": True, **resolved}

        g.save(update_fields=["pending", "updated_at"])
        return {"ok": True, "resolved": False, "yes": len(yes), "no": len(no)}


def finalize(game_id: int) -> dict | None:
    """Mark a game finished and pay Kitobcha to the top scorers (idempotent)."""
    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        # A candidate still awaiting votes when time runs out never scored —
        # just drop it, no strike (the game ending isn't the crowd's fault).
        if g.pending:
            g.pending = None
            g.save(update_fields=["pending", "updated_at"])
        if g.status != ChainGame.STATUS_FINISHED:
            g.status = ChainGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    # Option A — only players who actually SCORED are rewarded. Freeloaders
    # (0 points) and kicked cheaters get nothing and forfeit their entry fee.
    # Top-3 scorers get the tiered prize; every other scorer gets PARTICIPATION.
    scores = list(
        ChainScore.objects.filter(game=g).exclude(kicked=True)
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
    valid_links = sum(1 for c in (g.chain or []) if not c.get("rejected"))
    return {"winners": winners, "players": len(scores), "links": valid_links}


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
            "links": sum(1 for c in (g.chain or []) if not c.get("rejected")),
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

    # Lazily resolve an expired vote so polling clients see the outcome quickly,
    # even if nobody has submitted/voted since the window closed.
    if g.status == ChainGame.STATUS_LIVE and g.pending:
        with transaction.atomic():
            g = ChainGame.objects.select_for_update().get(id=g.id)
            _resolve_if_expired(g)

    chain = g.chain or []
    recent = [
        {
            "idx": c.get("idx"),
            "display": c.get("display", ""),
            "name": c.get("name", ""),
            "letter": c.get("letter", ""),
            "mine": c.get("user_id") == profile.id,
        }
        for c in reversed(chain[-14:])
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

    pending_payload = None
    if status == "live" and g.pending:
        p = g.pending
        yes, no = p.get("yes") or [], p.get("no") or []
        pending_payload = {
            "display": p["display"],
            "name": p["name"],
            "mine": p["user_id"] == profile.id,
            "yes": len(yes),
            "no": len(no),
            "your_vote": "yes" if profile.id in yes else ("no" if profile.id in no else None),
            "seconds_left": max(0, int(VOTE_WINDOW_SECONDS - _pending_elapsed(p))),
        }

    valid_links = sum(1 for c in chain if not c.get("rejected"))
    finished = status == "finished"
    return {
        "ok": True,
        "status": status,
        "game_id": g.id,
        "title": g.title,
        "current_letter": (g.current_letter or "").upper(),
        "seconds": seconds,
        "chain_len": valid_links,
        "recent": recent,
        "pending": pending_payload,
        "vote_threshold": ACCEPT_VOTES_THRESHOLD,
        "vote_seconds": VOTE_WINDOW_SECONDS,
        # Top 50; finished also includes every participant with their Kitobcha.
        "leaderboard": _cached_leaderboard(g, 50, finished),
        "your_points": (my.points if my else 0),
        "your_links": (my.links if my else 0),
        "your_reward": (my.reward if my else 0),
        "your_strikes": (my.strikes if my else 0),
        "kicked": (my.kicked if my else False),
        "lifetime": _lifetime_stats(profile),
        "history": _history() if status != "live" else [],
    }
