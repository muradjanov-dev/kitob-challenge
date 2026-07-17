"""Kitob Zanjiri — live "book chain" game logic.

A session shows a required starting letter; players race to submit a book title
or author name (from the ChainWord dictionary) starting with that letter and not
already used. The first valid submission wins the link: it scores a point and
the chain advances to a new letter (the last letter of the won word when the
dictionary still has unused words for it, otherwise a random reachable letter —
so the game never dead-ends). Top scorers earn Kitobcha when the game ends.

Concurrency: every submission locks the ChainGame row (select_for_update), so
under simultaneous answers exactly one wins the current letter; the rest get a
'wrong_letter' / 'already_used' response against the freshly-advanced state.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from tgbot.models import ChainGame, ChainWord, ChainScore
from tgbot.services.chain_text import normalize, first_letter, last_letter

POINTS_PER_LINK = 10
DEFAULT_DURATION_MIN = 10

# Reward tiers (Kitobcha) by final rank; everyone else in the top 20 with at
# least one link gets PARTICIPATION.
REWARD_TIERS = {0: 300, 1: 200, 2: 100}
PARTICIPATION = 25
PARTICIPATION_MAX_RANK = 20


# ── Letter selection ─────────────────────────────────────────────────────────
def _available_letters(exclude_norms):
    qs = ChainWord.objects.filter(is_active=True)
    if exclude_norms:
        qs = qs.exclude(norm__in=list(exclude_norms))
    return list(qs.values_list("first_letter", flat=True).distinct())


def pick_letter(exclude_norms, prefer: str = "") -> str:
    """A letter that still has at least one unused dictionary word. Prefers
    `prefer` (the chain's natural next letter) when it's reachable."""
    letters = [l for l in _available_letters(exclude_norms) if l]
    if not letters:
        return ""
    if prefer and prefer in letters:
        return prefer
    return random.choice(letters)


# ── Game lifecycle ───────────────────────────────────────────────────────────
def create_live_game(duration_minutes: int = DEFAULT_DURATION_MIN,
                     title: str = "Kitob Zanjiri") -> ChainGame:
    now = timezone.now()
    return ChainGame.objects.create(
        title=title,
        status=ChainGame.STATUS_LIVE,
        starts_at=now,
        ends_at=now + timedelta(minutes=duration_minutes),
        current_letter=pick_letter([]),
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
                g.current_letter = pick_letter(g.used_norms or [])
            g.save(update_fields=["status", "current_letter", "updated_at"])
    return g


def latest_game():
    return ChainGame.objects.order_by("-starts_at").first()


def submit(game_id: int, profile, text: str) -> dict:
    """Validate a submission and, if it wins the current letter, record the link
    and advance the chain. Returns a small result dict."""
    norm = normalize(text)
    fl = first_letter(text)
    if not norm or not fl:
        return {"ok": False, "error": "empty"}

    word = ChainWord.objects.filter(norm=norm, is_active=True).first()
    if not word:
        return {"ok": False, "error": "not_in_dictionary"}

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

        link = {
            "norm": norm,
            "display": word.display,
            "user_id": profile.id,
            "name": (profile.full_name or "Kitobxon")[:40],
            "letter": required,
            "at": now.isoformat(),
        }
        g.chain = (g.chain or []) + [link]
        used.append(norm)
        g.used_norms = used
        g.current_letter = pick_letter(used, prefer=word.last_letter)
        g.save(update_fields=["chain", "used_norms", "current_letter", "updated_at"])

        score, _ = ChainScore.objects.get_or_create(game=g, user=profile)
        score.points = (score.points or 0) + POINTS_PER_LINK
        score.links = (score.links or 0) + 1
        score.save(update_fields=["points", "links", "updated_at"])

        return {
            "ok": True,
            "gained": POINTS_PER_LINK,
            "display": word.display,
            "next_letter": g.current_letter,
            "your_points": score.points,
        }


def finalize(game_id: int) -> dict | None:
    """Mark a game finished and pay Kitobcha to the top scorers (idempotent).
    Returns a summary for announcing, or None if already rewarded."""
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
        if i < PARTICIPATION_MAX_RANK:
            reward = REWARD_TIERS.get(i, PARTICIPATION)
        else:
            reward = 0
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
    return {"winners": winners, "players": len(scores), "links": len(g.chain or [])}


def finalize_due_games() -> list:
    """Finish + reward every live game past its end time. Returns summaries."""
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


def state_payload(profile) -> dict:
    """Everything the game page needs in one poll."""
    now = timezone.now()
    g = get_or_activate_live_game()
    if not g:
        g = latest_game()

    if not g:
        return {"ok": True, "status": "none"}

    # recent chain, newest first, trimmed
    recent = list(reversed(g.chain or []))[:12]
    recent_links = [
        {"display": c.get("display", ""), "name": c.get("name", ""), "letter": c.get("letter", "")}
        for c in recent
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

    return {
        "ok": True,
        "status": status,
        "game_id": g.id,
        "title": g.title,
        "current_letter": (g.current_letter or "").upper(),
        "seconds": seconds,
        "chain_len": len(g.chain or []),
        "recent": recent_links,
        "leaderboard": _leaderboard(g),
        "your_points": (my.points if my else 0),
        "your_links": (my.links if my else 0),
    }
