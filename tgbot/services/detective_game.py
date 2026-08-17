"""Kitob Detektivi — live "guess the mystery book" free-text race game.

Each round reveals a mystery book through progressively less vague clues
(clue 0 = vague, clue N-1 = specific), one clue every `clue_interval_seconds`.
The FIRST correct free-text guess in a round wins it — the earlier the guess
(fewer clues seen), the more points. Entry fee is 40 Kitobcha.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum, Count

from django.utils import timezone

from tgbot.models import DetectiveGame, DetectiveScore
from tgbot.services.chain_text import normalize
from tgbot.services.chain_game import _add_ball_reward, charge_entry_fee, REWARD_TIERS, PARTICIPATION
from tgbot.services.game_questions import DETECTIVE_BOOKS

ENTRY_FEE = 40
LEAD_SECONDS = 30
NUM_ROUNDS = 8
ROUND_SECONDS = 45
CLUE_INTERVAL_SECONDS = 15
# Points by clue stage at the moment of a correct guess (0 = only the vaguest
# clue was visible, i.e. fastest/best guess).
POINTS_BY_STAGE = {0: 30, 1: 20, 2: 10}


from tgbot.services.question_picker import pick_least_recently_used


def create_scheduled_detective(lead_seconds: int = LEAD_SECONDS,
                               num_rounds: int = NUM_ROUNDS) -> DetectiveGame:
    recent_games = DetectiveGame.objects.order_by("-starts_at")[:100]
    rounds = pick_least_recently_used(
        pool=DETECTIVE_BOOKS,
        get_key_fn=lambda it: it.get("display"),
        recent_games=recent_games,
        get_game_keys_fn=lambda g: [r.get("display") for r in (g.rounds or []) if isinstance(r, dict)],
        count=num_rounds,
    )
    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    total = len(rounds) * ROUND_SECONDS
    return DetectiveGame.objects.create(
        status=DetectiveGame.STATUS_SCHEDULED,
        starts_at=starts,
        ends_at=starts + timedelta(seconds=total),
        rounds=rounds, round_seconds=ROUND_SECONDS,
        clue_interval_seconds=CLUE_INTERVAL_SECONDS, solved={},
    )


def latest_game():
    return DetectiveGame.objects.order_by("-starts_at").first()


def get_or_activate_live_game():
    now = timezone.now()
    g = DetectiveGame.objects.filter(status=DetectiveGame.STATUS_LIVE).order_by("-starts_at").first()
    if g:
        return g
    pending = (
        DetectiveGame.objects
        .filter(status=DetectiveGame.STATUS_SCHEDULED, starts_at__lte=now, ends_at__gte=now)
        .order_by("starts_at").first()
    )
    if not pending:
        return None
    with transaction.atomic():
        g = DetectiveGame.objects.select_for_update().get(id=pending.id)
        if g.status == DetectiveGame.STATUS_SCHEDULED:
            g.status = DetectiveGame.STATUS_LIVE
            g.save(update_fields=["status", "updated_at"])
    return g


def _phase(game, now):
    """Return (status, round_index, clue_stage, seconds_left_in_round)."""
    nr = len(game.rounds or [])
    total = game.round_seconds * nr
    elapsed = (now - game.starts_at).total_seconds()
    if elapsed < 0:
        return "scheduled", -1, 0, int(-elapsed)
    if elapsed >= total:
        return "finished", nr, 0, 0
    ri = int(elapsed // game.round_seconds)
    within = elapsed - ri * game.round_seconds
    max_stage = len(game.rounds[ri].get("clues") or []) - 1
    clue_stage = min(max_stage, int(within // game.clue_interval_seconds))
    left = int(game.round_seconds - within) + 1
    return "live", ri, clue_stage, left


def submit_guess(game_id: int, profile, text: str) -> dict:
    norm = normalize(text)
    if not norm:
        return {"ok": False, "error": "empty"}

    g0 = DetectiveGame.objects.filter(id=game_id).first()
    now = timezone.now()
    if not g0:
        return {"ok": False, "error": "not_live"}
    status, ri, clue_stage, _ = _phase(g0, now)
    if status != "live":
        return {"ok": False, "error": "not_live"}
    if str(ri) in (g0.solved or {}):
        return {"ok": False, "error": "already_solved"}

    score0, created0 = DetectiveScore.objects.get_or_create(game_id=g0.id, user=profile)
    if created0 and not charge_entry_fee(profile, amount=ENTRY_FEE):
        DetectiveScore.objects.filter(id=score0.id).delete()
        return {"ok": False, "error": "insufficient_balance", "need": ENTRY_FEE}

    accepted = set(g0.rounds[ri].get("norms") or [])
    if norm not in accepted:
        return {"ok": False, "error": "wrong"}

    with transaction.atomic():
        g = DetectiveGame.objects.select_for_update().get(id=game_id)
        status, ri2, clue_stage2, _ = _phase(g, timezone.now())
        if status != "live" or ri2 != ri:
            return {"ok": False, "error": "not_live"}
        if str(ri) in (g.solved or {}):
            return {"ok": False, "error": "already_solved"}

        points = POINTS_BY_STAGE.get(clue_stage2, POINTS_BY_STAGE[max(POINTS_BY_STAGE)])
        solved = dict(g.solved or {})
        solved[str(ri)] = {
            "user_id": profile.id, "name": (profile.full_name or "Kitobxon")[:40],
            "display": g.rounds[ri]["display"], "clue_stage": clue_stage2,
            "points": points, "at": timezone.now().isoformat(),
        }
        g.solved = solved
        g.save(update_fields=["solved", "updated_at"])

        elapsed = (timezone.now() - g.starts_at).total_seconds()
        within = max(0.01, elapsed - ri * g.round_seconds)
        time_taken = round(within, 3)

        score, _ = DetectiveScore.objects.get_or_create(game=g, user=profile)
        score.points = (score.points or 0) + points
        score.solved_count = (score.solved_count or 0) + 1
        score.total_time = round((score.total_time or 0.0) + time_taken, 3)
        score.save(update_fields=["points", "solved_count", "total_time", "updated_at"])

        return {"ok": True, "gained": points, "display": g.rounds[ri]["display"],
                "your_points": score.points}


def finalize(game_id: int) -> dict | None:
    with transaction.atomic():
        g = DetectiveGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        if g.status != DetectiveGame.STATUS_FINISHED:
            g.status = DetectiveGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    scores = list(
        DetectiveScore.objects.filter(game=g, points__gt=0)
        .select_related("user").order_by("-points", "total_time", "created_at")
    )
    winners = []
    for i, s in enumerate(scores):
        reward = REWARD_TIERS[i] if i < 3 else PARTICIPATION
        if not s.rewarded:
            applied = _add_ball_reward(s.user, reward)
            s.rewarded = True
            s.reward = applied
            s.save(update_fields=["rewarded", "reward", "updated_at"])
        else:
            applied = s.reward or reward
        winners.append({
            "rank": i + 1, "user_id": s.user_id, "telegram_id": s.user.telegram_id,
            "name": s.user.full_name or "Kitobxon", "points": s.points,
            "solved_count": s.solved_count, "reward": applied,
            "correct": s.solved_count,
            "time": round(s.total_time or 0.0, 1),
        })
    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    return {"winners": winners, "players": len(scores), "solved": len(g.solved or {})}


def finalize_due_games() -> list:
    now = timezone.now()
    out = []
    for g in DetectiveGame.objects.exclude(status=DetectiveGame.STATUS_FINISHED).filter(ends_at__lt=now):
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


def _leaderboard(game, limit=50):
    rows = (
        DetectiveScore.objects.filter(game=game, points__gt=0).select_related("user")
        .order_by("-points", "total_time", "created_at")[:limit]
    )
    return [{"name": r.user.full_name or "Kitobxon", "points": r.points,
             "solved_count": r.solved_count, "reward": r.reward or 0} for r in rows]


def _lifetime(profile):
    agg = DetectiveScore.objects.filter(user=profile).aggregate(
        games=Count("id"), pts=Sum("points"), solved=Sum("solved_count"))
    return {"games": agg["games"] or 0, "points": int(agg["pts"] or 0),
            "solved": int(agg["solved"] or 0)}


def _history(limit=6):
    out = []
    for g in DetectiveGame.objects.filter(status=DetectiveGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        top = (DetectiveScore.objects.filter(game=g, points__gt=0)
               .select_related("user").order_by("-points").first())
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "winner": (top.user.full_name if top else "—") or "—",
            "winner_points": (top.points if top else 0),
            "players": DetectiveScore.objects.filter(game=g, points__gt=0).count(),
        })
    return out


def state_payload(profile) -> dict:
    now = timezone.now()
    g = get_or_activate_live_game() or latest_game()
    if not g:
        return {"ok": True, "status": "none", "lifetime": _lifetime(profile), "history": _history()}

    status, ri, clue_stage, secs = _phase(g, now)
    nr = len(g.rounds or [])
    finished = status == "finished"
    my = DetectiveScore.objects.filter(game=g, user=profile).first()
    payload = {
        "ok": True, "status": status, "game_id": g.id,
        "round_index": ri, "round_number": ri + 1, "round_total": nr, "seconds": secs,
        "leaderboard": _leaderboard(g),
        "your_points": (my.points if my else 0),
        "your_solved": (my.solved_count if my else 0),
        "your_reward": (my.reward if my else 0),
        "lifetime": _lifetime(profile),
        "history": _history() if status != "live" else [],
    }
    if status == "live" and 0 <= ri < nr:
        rnd = g.rounds[ri]
        payload["clues"] = rnd["clues"][:clue_stage + 1]
        payload["clue_stage"] = clue_stage
        payload["clue_total"] = len(rnd["clues"])
        solved_info = (g.solved or {}).get(str(ri))
        if solved_info:
            payload["solved"] = True
            payload["solved_by"] = solved_info["name"]
            payload["solved_display"] = solved_info["display"]
            payload["solved_mine"] = solved_info.get("user_id") == profile.id
        else:
            payload["solved"] = False
    return payload
