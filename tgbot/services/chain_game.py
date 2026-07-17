"""Kitob Zanjiri — live "book chain" game logic.

A session shows a required starting letter; players race to submit a book title
or author name starting with that letter and not already used. The first valid
submission wins the link (+10) and the chain advances to that word's last letter.

No fixed dictionary: ANY answer is accepted (only the starting letter + no
repeats are enforced). Bad answers are moderated by the crowd — any player can
tap "❌ Bunday kitob yo'q" on a link; once it collects REJECT_VOTES votes the
link is invalidated and its point is revoked.

Concurrency: every write locks the ChainGame row (select_for_update), so under
simultaneous answers exactly one wins the current letter.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum, Count
from django.utils import timezone

from tgbot.models import ChainGame, ChainScore
from tgbot.services.chain_text import normalize, first_letter, last_letter

POINTS_PER_LINK = 10
DEFAULT_DURATION_MIN = 10
REJECT_VOTES = 3  # community votes that invalidate a link

# Letters that comfortably start Uzbek book/author names — used for the opening
# letter and as a fallback when a word ends in a hard/rare letter.
START_LETTERS = list("abdegijklmnopqrstuvyfh")

REWARD_TIERS = {0: 300, 1: 200, 2: 100}
PARTICIPATION = 25
PARTICIPATION_MAX_RANK = 20


def _initial_letter() -> str:
    return random.choice(START_LETTERS)


def _next_letter(word_last: str) -> str:
    return word_last or random.choice(START_LETTERS)


# ── Game lifecycle ───────────────────────────────────────────────────────────
def create_live_game(duration_minutes: int = DEFAULT_DURATION_MIN,
                     title: str = "Kitob Zanjiri") -> ChainGame:
    now = timezone.now()
    return ChainGame.objects.create(
        title=title,
        status=ChainGame.STATUS_LIVE,
        starts_at=now,
        ends_at=now + timedelta(minutes=duration_minutes),
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


def submit(game_id: int, profile, text: str) -> dict:
    """Validate a submission and, if it wins the current letter, record the link
    and advance the chain. No dictionary — any answer with the right starting
    letter that hasn't been used is accepted."""
    norm = normalize(text)
    fl = first_letter(text)
    ll = last_letter(text)
    if not norm or not fl or len(norm) < 2:
        return {"ok": False, "error": "empty"}

    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=game_id)
        now = timezone.now()
        if not (g.status == ChainGame.STATUS_LIVE and g.starts_at <= now <= g.ends_at):
            return {"ok": False, "error": "not_live"}

        required = g.current_letter
        if required and fl != required:
            return {"ok": False, "error": "wrong_letter", "required": required}

        used = list(g.used_norms or [])
        if norm in used:
            return {"ok": False, "error": "already_used"}

        chain = g.chain or []
        display = " ".join((text or "").strip().split())[:60]
        link = {
            "idx": len(chain),
            "norm": norm,
            "display": display,
            "user_id": profile.id,
            "name": (profile.full_name or "Kitobxon")[:40],
            "letter": required,
            "at": now.isoformat(),
            "votes": [],
            "rejected": False,
        }
        chain.append(link)
        used.append(norm)
        g.chain = chain
        g.used_norms = used
        g.current_letter = _next_letter(ll)
        g.save(update_fields=["chain", "used_norms", "current_letter", "updated_at"])

        score, _ = ChainScore.objects.get_or_create(game=g, user=profile)
        score.points = (score.points or 0) + POINTS_PER_LINK
        score.links = (score.links or 0) + 1
        score.save(update_fields=["points", "links", "updated_at"])

        return {
            "ok": True,
            "gained": POINTS_PER_LINK,
            "display": display,
            "next_letter": g.current_letter,
            "your_points": score.points,
        }


def challenge(game_id: int, profile, idx: int) -> dict:
    """Vote a chain link as "not a real book". At REJECT_VOTES the link is
    invalidated and the submitter's point is revoked. You can't vote your own
    link, nor vote twice."""
    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=game_id)
        chain = g.chain or []
        if idx is None or idx < 0 or idx >= len(chain):
            return {"ok": False, "error": "bad_index"}
        link = chain[idx]
        if link.get("rejected"):
            return {"ok": True, "count": len(link.get("votes") or []), "rejected": True}
        if link.get("user_id") == profile.id:
            return {"ok": False, "error": "own_link"}

        votes = list(link.get("votes") or [])
        if profile.id in votes:
            return {"ok": True, "count": len(votes), "rejected": False, "already": True}
        votes.append(profile.id)
        link["votes"] = votes
        rejected = len(votes) >= REJECT_VOTES
        link["rejected"] = rejected
        chain[idx] = link
        g.chain = chain
        g.save(update_fields=["chain", "updated_at"])

        if rejected:
            s = ChainScore.objects.filter(game=g, user_id=link.get("user_id")).first()
            if s:
                s.points = max(0, (s.points or 0) - POINTS_PER_LINK)
                s.links = max(0, (s.links or 0) - 1)
                s.save(update_fields=["points", "links", "updated_at"])
        return {"ok": True, "count": len(votes), "rejected": rejected}


def finalize(game_id: int) -> dict | None:
    """Mark a game finished and pay Kitobcha to the top scorers (idempotent)."""
    with transaction.atomic():
        g = ChainGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        if g.status != ChainGame.STATUS_FINISHED:
            g.status = ChainGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    scores = list(
        ChainScore.objects.filter(game=g, points__gt=0)
        .select_related("user")
        .order_by("-points", "created_at")
    )
    winners = []
    for i, s in enumerate(scores):
        reward = REWARD_TIERS.get(i, PARTICIPATION) if i < PARTICIPATION_MAX_RANK else 0
        applied = 0
        if reward and not s.rewarded:
            applied = s.user.update_ball(True, reward)
            s.rewarded = True
            s.save(update_fields=["rewarded", "updated_at"])
        elif reward:
            applied = reward
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
def _leaderboard(game, limit: int = 10):
    rows = (
        ChainScore.objects.filter(game=game, points__gt=0)
        .select_related("user")
        .order_by("-points", "created_at")[:limit]
    )
    return [
        {"name": r.user.full_name or "Kitobxon", "points": r.points, "links": r.links}
        for r in rows
    ]


def _lifetime_stats(profile) -> dict:
    """Cumulative Kitob Zanjiri stats for one user across every game played."""
    agg = ChainScore.objects.filter(user=profile).aggregate(
        games=Count("id"), points=Sum("points"), links=Sum("links"),
    )
    return {
        "games": agg["games"] or 0,
        "points": int(agg["points"] or 0),
        "links": int(agg["links"] or 0),
    }


def state_payload(profile) -> dict:
    """Everything the game page needs in one poll."""
    now = timezone.now()
    g = get_or_activate_live_game()
    if not g:
        g = latest_game()
    if not g:
        return {"ok": True, "status": "none", "lifetime": _lifetime_stats(profile)}

    chain = g.chain or []
    recent = []
    for c in reversed(chain[-14:]):
        votes = c.get("votes") or []
        recent.append({
            "idx": c.get("idx"),
            "display": c.get("display", ""),
            "name": c.get("name", ""),
            "letter": c.get("letter", ""),
            "votes": len(votes),
            "rejected": bool(c.get("rejected")),
            "mine": c.get("user_id") == profile.id,
            "voted": profile.id in votes,
        })
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

    valid_links = sum(1 for c in chain if not c.get("rejected"))
    return {
        "ok": True,
        "status": status,
        "game_id": g.id,
        "title": g.title,
        "current_letter": (g.current_letter or "").upper(),
        "seconds": seconds,
        "chain_len": valid_links,
        "recent": recent,
        "leaderboard": _leaderboard(g),
        "your_points": (my.points if my else 0),
        "your_links": (my.links if my else 0),
        "lifetime": _lifetime_stats(profile),
        "reject_votes": REJECT_VOTES,
    }
