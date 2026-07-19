"""Ko'pchilik nima dedi? — live "Family Feud" style game.

Each question runs for an answer window then a reveal window (all time-based, so
clients just poll). After a question's answer window closes, answers are grouped
and everyone who gave a given answer scores count×10 — matching the crowd wins.
Top scorers earn Kitobcha at the end; every player who answered gets a guest 30.
"""

import random
from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum, Count
from django.utils import timezone

from tgbot.models import FeudGame, FeudAnswer, FeudScore
from tgbot.services.chain_text import normalize
from tgbot.services.chain_game import _add_ball_flat, REWARD_TIERS, PARTICIPATION
from tgbot.services.game_questions import FEUD_QUESTIONS

LEAD_SECONDS = 30
NUM_QUESTIONS = 8
MATCH_POINTS = 10  # per person who gave the same answer


def _pick_fresh(pool, used, count):
    """Prefer questions not used in recent games; top up if not enough."""
    fresh = [x for x in pool if x not in used]
    random.shuffle(fresh)
    if len(fresh) >= count:
        return fresh[:count]
    rest = [x for x in pool if x in used]
    random.shuffle(rest)
    return (fresh + rest)[:count]


def _recent_used(games_back=6):
    used = set()
    for g in FeudGame.objects.order_by("-starts_at")[:games_back]:
        for q in (g.questions or []):
            used.add(q)
    return used


def create_scheduled_feud(lead_seconds: int = LEAD_SECONDS,
                          num_questions: int = NUM_QUESTIONS) -> FeudGame:
    qs = _pick_fresh(FEUD_QUESTIONS, _recent_used(), min(num_questions, len(FEUD_QUESTIONS)))
    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    answer_s, reveal_s = 25, 8
    total = len(qs) * (answer_s + reveal_s)
    return FeudGame.objects.create(
        status=FeudGame.STATUS_SCHEDULED,
        starts_at=starts,
        ends_at=starts + timedelta(seconds=total),
        questions=qs,
        answer_seconds=answer_s,
        reveal_seconds=reveal_s,
        scored_indices=[],
    )


def latest_game():
    return FeudGame.objects.order_by("-starts_at").first()


def _phase(game, now):
    """Return (status, q_index, phase, seconds_left_in_phase)."""
    span = game.answer_seconds + game.reveal_seconds
    total = span * len(game.questions or [])
    elapsed = (now - game.starts_at).total_seconds()
    if elapsed < 0:
        return "scheduled", -1, "lobby", int(-elapsed)
    if elapsed >= total:
        return "finished", len(game.questions or []), "done", 0
    qi = int(elapsed // span)
    within = elapsed - qi * span
    if within < game.answer_seconds:
        return "live", qi, "answer", int(game.answer_seconds - within) + 1
    return "live", qi, "reveal", int(span - within) + 1


def _closed_count(status, qi, phase, nq):
    if status == "scheduled":
        return 0
    if status == "finished":
        return nq
    return qi + 1 if phase == "reveal" else qi


def _score_question(g, q_index):
    answers = list(FeudAnswer.objects.filter(game=g, q_index=q_index))
    counts = Counter(a.norm for a in answers)
    for a in answers:
        pts = counts[a.norm] * MATCH_POINTS
        score, _ = FeudScore.objects.get_or_create(game=g, user_id=a.user_id)
        score.points = (score.points or 0) + pts
        score.save(update_fields=["points", "updated_at"])


def _ensure_scored(game, closed_count):
    """Score every question whose answer window has closed (idempotent)."""
    if closed_count <= len(game.scored_indices or []):
        return  # nothing new — cheap fast path, no lock
    with transaction.atomic():
        g = FeudGame.objects.select_for_update().get(id=game.id)
        done = set(g.scored_indices or [])
        changed = False
        for qi in range(0, min(closed_count, len(g.questions or []))):
            if qi in done:
                continue
            _score_question(g, qi)
            done.add(qi)
            changed = True
        if changed:
            g.scored_indices = sorted(done)
            g.save(update_fields=["scored_indices", "updated_at"])


def submit_answer(game_id: int, profile, text: str) -> dict:
    norm = normalize(text)
    if not norm or len(norm) < 1:
        return {"ok": False, "error": "empty"}
    g = FeudGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    now = timezone.now()
    status, qi, phase, _ = _phase(g, now)
    if status != "live" or phase != "answer":
        return {"ok": False, "error": "not_answering"}
    FeudAnswer.objects.update_or_create(
        game_id=g.id, user=profile, q_index=qi,
        defaults={"text": text.strip()[:120], "norm": norm},
    )
    return {"ok": True, "q_index": qi}


def finalize(game_id: int) -> dict | None:
    with transaction.atomic():
        g = FeudGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        if g.status != FeudGame.STATUS_FINISHED:
            g.status = FeudGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None
    _ensure_scored(g, len(g.questions or []))  # score any remaining questions

    scores = list(
        FeudScore.objects.filter(game=g).select_related("user").order_by("-points", "created_at")
    )
    winners = []
    for i, s in enumerate(scores):
        reward = REWARD_TIERS[i] if (s.points > 0 and i < 3) else PARTICIPATION
        if not s.rewarded:
            applied = _add_ball_flat(s.user, reward)
            s.rewarded = True
            s.reward = applied
            s.save(update_fields=["rewarded", "reward", "updated_at"])
        else:
            applied = s.reward or reward
        winners.append({
            "rank": i + 1, "user_id": s.user_id, "telegram_id": s.user.telegram_id,
            "name": s.user.full_name or "Kitobxon", "points": s.points, "reward": applied,
        })
    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    return {"winners": winners, "players": len(scores)}


def finalize_due_games() -> list:
    now = timezone.now()
    out = []
    for g in FeudGame.objects.exclude(status=FeudGame.STATUS_FINISHED).filter(ends_at__lt=now):
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


def _reveal(game, q_index, limit=6):
    rows = FeudAnswer.objects.filter(game=game, q_index=q_index).values_list("text", "norm")
    counts, display = Counter(), {}
    for text, norm in rows:
        counts[norm] += 1
        display.setdefault(norm, text)
    return [{"text": display[n], "count": c} for n, c in counts.most_common(limit)]


def _leaderboard(game, limit=10, include_all=False):
    rows = (
        FeudScore.objects.filter(game=game).select_related("user")
        .order_by("-points", "created_at")[:limit]
    )
    return [
        {"name": r.user.full_name or "Kitobxon", "points": r.points, "reward": r.reward or 0}
        for r in rows
    ]


def _lifetime(profile):
    from django.db.models import Max
    # Alias must not shadow the field name (else Max("points") → FieldError).
    agg = FeudScore.objects.filter(user=profile).aggregate(
        games=Count("id"), pts=Sum("points"), best=Max("points"))
    return {"games": agg["games"] or 0, "points": int(agg["pts"] or 0),
            "best": int(agg["best"] or 0)}


def _history(limit=6):
    out = []
    for g in FeudGame.objects.filter(status=FeudGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        top = (FeudScore.objects.filter(game=g, points__gt=0)
               .select_related("user").order_by("-points").first())
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "winner": (top.user.full_name if top else "—") or "—",
            "winner_points": (top.points if top else 0),
            "players": FeudScore.objects.filter(game=g).count(),
        })
    return out


def _cached_leaderboard(game, limit, include_all):
    """Shared across all pollers — computed at most once every 2s (Redis)."""
    from django.core.cache import cache
    key = f"feud:lb:{game.id}:{limit}:{int(include_all)}"
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
    now = timezone.now()
    g = latest_game()
    if not g:
        return {"ok": True, "status": "none", "lifetime": _lifetime(profile),
                "history": _history()}

    status, qi, phase, secs = _phase(g, now)
    nq = len(g.questions or [])
    _ensure_scored(g, _closed_count(status, qi, phase, nq))

    finished = status == "finished"
    payload = {
        "ok": True,
        "status": status,
        "phase": phase,
        "game_id": g.id,
        "q_index": qi,
        "q_total": nq,
        "seconds": secs,
        "leaderboard": _cached_leaderboard(g, 50, finished),
        "your_points": 0,
        "lifetime": _lifetime(profile),
        "history": _history() if status != "live" else [],
    }
    my = FeudScore.objects.filter(game=g, user=profile).first()
    payload["your_points"] = my.points if my else 0
    payload["your_reward"] = my.reward if my else 0

    if status == "live" and 0 <= qi < nq:
        payload["question"] = g.questions[qi]
        payload["q_number"] = qi + 1
        if phase == "answer":
            ans = FeudAnswer.objects.filter(game=g, user=profile, q_index=qi).first()
            payload["your_answer"] = ans.text if ans else ""
        else:  # reveal
            payload["reveal"] = _reveal(g, qi)
            ans = FeudAnswer.objects.filter(game=g, user=profile, q_index=qi).first()
            payload["your_answer"] = ans.text if ans else ""
    return payload
