"""Bilim O'yini — one shared MC-quiz engine for 4 content flavors:

  twofacts   — Ikki haqiqat, bir yolg'on: 3 statements, spot the fake one.
  impostor   — Kim yolg'onchi?: 3 real book/author pairings + 1 fabricated one.
  connection — Yashirin bog'lanish: 4 items share a hidden theme, name it.
  teams      — Jamoa Jangi: players are auto-split into two balanced teams as
               they join (alternating A/B); a TEAM's cumulative correct
               answers (not individuals) decide the winning side, which then
               splits a jackpot.

All four share the same live answer/reveal-phase timing as Ko'pchilik/Emoji;
only content prep and (for "teams") scoring differ.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Sum, Count, Max
from django.utils import timezone

from tgbot.models import QuizGame, QuizAnswer, QuizScore
from tgbot.services.chain_game import _add_ball_flat, charge_entry_fee, REWARD_TIERS, PARTICIPATION
from tgbot.services.game_questions import (
    QUIZ_TWOFACTS_QUESTIONS, QUIZ_IMPOSTOR_QUESTIONS, QUIZ_CONNECTION_QUESTIONS,
    SURVIVAL_QUESTIONS,
)

LEAD_SECONDS = 30
ANSWER_SECONDS = 15
REVEAL_SECONDS = 5
POINTS = 10
TEAM_JACKPOT = 300

TITLES = {
    "twofacts": "Ikki haqiqat, bir yolg'on",
    "impostor": "Kim yolg'onchi?",
    "connection": "Yashirin bog'lanish",
    "teams": "Jamoa Jangi",
}
ENTRY_FEES = {"twofacts": 25, "impostor": 25, "connection": 25, "teams": 30}
NUM_QUESTIONS = {"twofacts": 6, "impostor": 6, "connection": 6, "teams": 10}


def _raw_pool(flavor):
    if flavor == "twofacts":
        return QUIZ_TWOFACTS_QUESTIONS
    if flavor == "connection":
        return QUIZ_CONNECTION_QUESTIONS
    if flavor == "teams":
        return SURVIVAL_QUESTIONS
    if flavor == "impostor":
        return QUIZ_IMPOSTOR_QUESTIONS
    raise ValueError(f"unknown flavor {flavor}")


def _identity(flavor, item):
    """A stable string identifying a raw content item, for no-repeat tracking."""
    if flavor == "impostor":
        return item["fake"]
    return item.get("q") or str(item.get("items"))


def _prep_one(flavor, item):
    if flavor == "impostor":
        options = list(item["real"]) + [item["fake"]]
        fake_text = item["fake"]
        random.shuffle(options)
        return {"q": "Qaysi biri SOXTA (haqiqiy emas)?", "options": options,
                "correct": options.index(fake_text)}
    # twofacts / connection / teams are already {"q","options","correct"}-shaped.
    opts = list(item["options"])
    correct_text = opts[item["correct"]]
    random.shuffle(opts)
    out = {"q": item["q"], "options": opts, "correct": opts.index(correct_text)}
    if "items" in item:
        out["items"] = item["items"]
    return out


def _recent_used(flavor, games_back=33):
    """Identity of each question actually used in recent games. `options[correct]`
    is the reliable identity for "impostor" since its display text is a fixed
    string ("Qaysi biri SOXTA...") — the fake statement's own text (which ends
    up at the `correct` index post-shuffle) is what actually varies."""
    used = set()
    for g in QuizGame.objects.filter(flavor=flavor).order_by("-starts_at")[:games_back]:
        for q in (g.questions or []):
            if flavor == "impostor":
                used.add(q["options"][q["correct"]])
            else:
                used.add(q.get("q"))
    return used


def create_scheduled_quiz(flavor: str, lead_seconds: int = LEAD_SECONDS) -> QuizGame:
    pool = _raw_pool(flavor)
    num_questions = min(NUM_QUESTIONS[flavor], len(pool))
    used_ids = _recent_used(flavor)
    fresh = [it for it in pool if _identity(flavor, it) not in used_ids]
    random.shuffle(fresh)
    if len(fresh) < num_questions:
        rest = [it for it in pool if _identity(flavor, it) in used_ids]
        random.shuffle(rest)
        raw = (fresh + rest)[:num_questions]
    else:
        raw = fresh[:num_questions]
    qs = [_prep_one(flavor, it) for it in raw]

    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    total = len(qs) * (ANSWER_SECONDS + REVEAL_SECONDS)
    return QuizGame.objects.create(
        flavor=flavor, title=TITLES[flavor],
        status=QuizGame.STATUS_SCHEDULED,
        starts_at=starts, ends_at=starts + timedelta(seconds=total),
        questions=qs, answer_seconds=ANSWER_SECONDS, reveal_seconds=REVEAL_SECONDS,
    )


def latest_game(flavor):
    return QuizGame.objects.filter(flavor=flavor).order_by("-starts_at").first()


def get_or_activate_live_game(flavor):
    now = timezone.now()
    g = QuizGame.objects.filter(flavor=flavor, status=QuizGame.STATUS_LIVE).order_by("-starts_at").first()
    if g:
        return g
    pending = (
        QuizGame.objects
        .filter(flavor=flavor, status=QuizGame.STATUS_SCHEDULED, starts_at__lte=now, ends_at__gte=now)
        .order_by("starts_at").first()
    )
    if not pending:
        return None
    with transaction.atomic():
        g = QuizGame.objects.select_for_update().get(id=pending.id)
        if g.status == QuizGame.STATUS_SCHEDULED:
            g.status = QuizGame.STATUS_LIVE
            g.save(update_fields=["status", "updated_at"])
    return g


def _phase(game, now):
    span = game.answer_seconds + game.reveal_seconds
    nq = len(game.questions or [])
    total = span * nq
    elapsed = (now - game.starts_at).total_seconds()
    if elapsed < 0:
        return "scheduled", -1, "lobby", int(-elapsed)
    if elapsed >= total:
        return "finished", nq, "done", 0
    qi = int(elapsed // span)
    within = elapsed - qi * span
    if within < game.answer_seconds:
        return "live", qi, "answer", int(game.answer_seconds - within) + 1
    return "live", qi, "reveal", int(span - within) + 1


def _assign_team(game) -> str:
    """Caller must hold the row lock on `game`. Alternates A/B so team sizes
    never differ by more than one, regardless of join order."""
    a, b = list(game.team_a or []), list(game.team_b or [])
    return "a" if len(a) <= len(b) else "b"


def submit_answer(game_id: int, profile, choice: int) -> dict:
    g = QuizGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    now = timezone.now()
    status, qi, phase, _ = _phase(g, now)
    if status != "live" or phase != "answer" or qi < 0 or qi >= len(g.questions or []):
        return {"ok": False, "error": "not_answering"}

    is_first = not QuizAnswer.objects.filter(game_id=g.id, user=profile).exists()
    if is_first and not charge_entry_fee(profile, amount=ENTRY_FEES[g.flavor]):
        return {"ok": False, "error": "insufficient_balance", "need": ENTRY_FEES[g.flavor]}

    team = ""
    if g.flavor == "teams" and is_first:
        with transaction.atomic():
            gl = QuizGame.objects.select_for_update().get(id=g.id)
            team = _assign_team(gl)
            if team == "a":
                gl.team_a = list(gl.team_a or []) + [profile.id]
            else:
                gl.team_b = list(gl.team_b or []) + [profile.id]
            gl.save(update_fields=["team_a", "team_b", "updated_at"])

    q = g.questions[qi]
    correct = (choice == q.get("correct"))

    hit, created = QuizAnswer.objects.get_or_create(
        game_id=g.id, user=profile, q_index=qi,
        defaults={"choice": choice, "is_correct": correct},
    )
    if not created:
        return {"ok": False, "error": "already_answered",
                "correct": hit.is_correct, "correct_index": q.get("correct")}

    score, score_created = QuizScore.objects.get_or_create(game=g, user=profile)
    if score_created and team:
        score.team = team
        score.save(update_fields=["team"])
    if correct:
        score.points = (score.points or 0) + POINTS
        score.save(update_fields=["points", "updated_at"])
        if g.flavor == "teams" and score.team:
            field = "team_a_points" if score.team == "a" else "team_b_points"
            QuizGame.objects.filter(id=g.id).update(**{field: F(field) + POINTS})

    return {"ok": True, "correct": correct, "correct_index": q.get("correct"), "team": score.team}


def finalize(game_id: int) -> dict | None:
    with transaction.atomic():
        g = QuizGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        if g.status != QuizGame.STATUS_FINISHED:
            g.status = QuizGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    if g.flavor == "teams":
        return _finalize_teams(g)
    return _finalize_individual(g)


def _finalize_individual(g) -> dict:
    scores = list(
        QuizScore.objects.filter(game=g, points__gt=0)
        .select_related("user").order_by("-points", "created_at")
    )
    winners = []
    for i, s in enumerate(scores):
        reward = REWARD_TIERS[i] if i < 3 else PARTICIPATION
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


def _finalize_teams(g) -> dict:
    scores = list(QuizScore.objects.filter(game=g).select_related("user"))
    winning_team = "a" if g.team_a_points >= g.team_b_points else "b"
    tie = g.team_a_points == g.team_b_points
    winners = []
    for s in scores:
        if not s.team:
            continue
        on_winning_side = tie or s.team == winning_team
        reward = 0
        if on_winning_side:
            team_size = len(g.team_a if s.team == "a" else g.team_b) or 1
            reward = max(1, TEAM_JACKPOT // team_size)
        elif s.points > 0:
            reward = PARTICIPATION
        if reward and not s.rewarded:
            applied = _add_ball_flat(s.user, reward)
            s.rewarded = True
            s.reward = applied
            s.save(update_fields=["rewarded", "reward", "updated_at"])
        winners.append({
            "user_id": s.user_id, "telegram_id": s.user.telegram_id,
            "name": s.user.full_name or "Kitobxon", "points": s.points,
            "team": s.team, "reward": s.reward or 0,
        })
    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    winners.sort(key=lambda w: -w["points"])
    return {
        "winners": winners, "players": len(scores), "tie": tie,
        "winning_team": winning_team if not tie else None,
        "team_a_points": g.team_a_points, "team_b_points": g.team_b_points,
    }


def finalize_due_games(flavor=None) -> list:
    now = timezone.now()
    qs = QuizGame.objects.exclude(status=QuizGame.STATUS_FINISHED).filter(ends_at__lt=now)
    if flavor:
        qs = qs.filter(flavor=flavor)
    out = []
    for g in qs:
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


def _leaderboard(game, limit=50):
    rows = (
        QuizScore.objects.filter(game=game, points__gt=0).select_related("user")
        .order_by("-points", "created_at")[:limit]
    )
    return [{"name": r.user.full_name or "Kitobxon", "points": r.points,
             "team": r.team, "reward": r.reward or 0} for r in rows]


def _lifetime(profile, flavor):
    agg = QuizScore.objects.filter(user=profile, game__flavor=flavor).aggregate(
        games=Count("id"), pts=Sum("points"), best=Max("points"))
    return {"games": agg["games"] or 0, "points": int(agg["pts"] or 0), "best": int(agg["best"] or 0)}


def _history(flavor, limit=6):
    out = []
    for g in QuizGame.objects.filter(flavor=flavor, status=QuizGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        top = (QuizScore.objects.filter(game=g, points__gt=0)
               .select_related("user").order_by("-points").first())
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "winner": (top.user.full_name if top else "—") or "—",
            "winner_points": (top.points if top else 0),
            "players": QuizScore.objects.filter(game=g, points__gt=0).count(),
        })
    return out


def state_payload(profile, flavor) -> dict:
    now = timezone.now()
    g = get_or_activate_live_game(flavor) or latest_game(flavor)
    if not g:
        return {"ok": True, "status": "none", "lifetime": _lifetime(profile, flavor),
                "history": _history(flavor)}

    status, qi, phase, secs = _phase(g, now)
    nq = len(g.questions or [])
    finished = status == "finished"
    my = QuizScore.objects.filter(game=g, user=profile).first()
    payload = {
        "ok": True, "status": status, "phase": phase, "game_id": g.id,
        "flavor": g.flavor, "title": g.title,
        "q_index": qi, "q_number": qi + 1, "q_total": nq, "seconds": secs,
        "leaderboard": _leaderboard(g),
        "your_points": (my.points if my else 0),
        "your_team": (my.team if my else ""),
        "your_reward": (my.reward if my else 0),
        "lifetime": _lifetime(profile, flavor),
        "history": _history(flavor) if status != "live" else [],
    }
    if flavor == "teams":
        payload["team_a_points"] = g.team_a_points
        payload["team_b_points"] = g.team_b_points
        payload["team_a_size"] = len(g.team_a or [])
        payload["team_b_size"] = len(g.team_b or [])
    if status == "live" and 0 <= qi < nq:
        q = g.questions[qi]
        payload["q"] = q["q"]
        payload["options"] = q["options"]
        if "items" in q:
            payload["items"] = q["items"]
        ans = QuizAnswer.objects.filter(game=g, user=profile, q_index=qi).first()
        payload["answered"] = bool(ans)
        if ans:
            payload["your_choice"] = ans.choice
            payload["your_correct"] = ans.is_correct
        if phase == "reveal":
            payload["correct_index"] = q.get("correct")
    return payload
