"""Hikmat Xazinasi — live "guess which scholar said it" multiple-choice game.

Same time-based phases as Emoji Kitob (answer window then reveal window per
question), but scoring adds a consecutive-correct streak multiplier: 1st
correct in a streak = 1x, 2nd = 2x, 3rd+ = 3x (capped). A wrong answer resets
the streak to 0. Entry fee is 30 Kitobcha (see ENTRY_FEE below).
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum, Count, Max
from django.utils import timezone

from tgbot.models import WisdomGame, WisdomAnswer, WisdomScore
from tgbot.services.chain_game import _add_ball_reward, charge_entry_fee, REWARD_TIERS, PARTICIPATION
from tgbot.services.game_questions import WISDOM_QUESTIONS

ENTRY_FEE = 30
LEAD_SECONDS = 30
NUM_QUESTIONS = 10
ANSWER_SECONDS = 15
REVEAL_SECONDS = 5
BASE_POINTS = 10
STREAK_CAP = 3  # streak multiplier caps at 3x


def _prep_questions(raw):
    out = []
    for item in raw:
        opts = list(item["options"])
        correct_text = opts[item["correct"]]
        random.shuffle(opts)
        out.append({"quote": item["quote"], "options": opts, "correct": opts.index(correct_text)})
    return out


def _recent_used(games_back=33):
    used = set()
    for g in WisdomGame.objects.order_by("-starts_at")[:games_back]:
        for q in (g.questions or []):
            used.add(q.get("quote"))
    return used


def create_scheduled_wisdom(lead_seconds: int = LEAD_SECONDS,
                            num_questions: int = NUM_QUESTIONS) -> WisdomGame:
    num_questions = min(num_questions, len(WISDOM_QUESTIONS))
    used = _recent_used()
    fresh = [it for it in WISDOM_QUESTIONS if it["quote"] not in used]
    random.shuffle(fresh)
    if len(fresh) < num_questions:
        rest = [it for it in WISDOM_QUESTIONS if it["quote"] in used]
        random.shuffle(rest)
        raw = (fresh + rest)[:num_questions]
    else:
        raw = fresh[:num_questions]
    qs = _prep_questions(raw)
    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    total = len(qs) * (ANSWER_SECONDS + REVEAL_SECONDS)
    return WisdomGame.objects.create(
        status=WisdomGame.STATUS_SCHEDULED,
        starts_at=starts,
        ends_at=starts + timedelta(seconds=total),
        questions=qs, answer_seconds=ANSWER_SECONDS, reveal_seconds=REVEAL_SECONDS,
    )


def latest_game():
    return WisdomGame.objects.order_by("-starts_at").first()


def get_or_activate_live_game():
    now = timezone.now()
    g = WisdomGame.objects.filter(status=WisdomGame.STATUS_LIVE).order_by("-starts_at").first()
    if g:
        return g
    pending = (
        WisdomGame.objects
        .filter(status=WisdomGame.STATUS_SCHEDULED, starts_at__lte=now, ends_at__gte=now)
        .order_by("starts_at").first()
    )
    if not pending:
        return None
    with transaction.atomic():
        g = WisdomGame.objects.select_for_update().get(id=pending.id)
        if g.status == WisdomGame.STATUS_SCHEDULED:
            g.status = WisdomGame.STATUS_LIVE
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


def submit_answer(game_id: int, profile, choice: int) -> dict:
    g = WisdomGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    now = timezone.now()
    status, qi, phase, _ = _phase(g, now)
    if status != "live" or phase != "answer" or qi < 0 or qi >= len(g.questions or []):
        return {"ok": False, "error": "not_answering"}

    is_first = not WisdomAnswer.objects.filter(game_id=g.id, user=profile).exists()
    if is_first and not charge_entry_fee(profile, amount=ENTRY_FEE):
        return {"ok": False, "error": "insufficient_balance", "need": ENTRY_FEE}

    q = g.questions[qi]
    correct = (choice == q.get("correct"))

    hit, created = WisdomAnswer.objects.get_or_create(
        game_id=g.id, user=profile, q_index=qi,
        defaults={"choice": choice, "is_correct": correct},
    )
    if not created:
        return {"ok": False, "error": "already_answered",
                "correct": hit.is_correct, "correct_index": q.get("correct")}

    with transaction.atomic():
        score, _ = WisdomScore.objects.select_for_update().get_or_create(game_id=g.id, user=profile)
        if correct:
            streak = (score.streak or 0) + 1
            mult = min(streak, STREAK_CAP)
            gained = BASE_POINTS * mult
            score.points = (score.points or 0) + gained
            score.streak = streak
            score.best_streak = max(score.best_streak or 0, streak)
        else:
            gained = 0
            score.streak = 0
        score.save(update_fields=["points", "streak", "best_streak", "updated_at"])

    return {"ok": True, "correct": correct, "correct_index": q.get("correct"),
            "gained": gained, "streak": score.streak}


def finalize(game_id: int) -> dict | None:
    with transaction.atomic():
        g = WisdomGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        if g.status != WisdomGame.STATUS_FINISHED:
            g.status = WisdomGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    scores = list(
        WisdomScore.objects.filter(game=g, points__gt=0)
        .select_related("user").order_by("-points", "created_at")
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
            "best_streak": s.best_streak, "reward": applied,
        })
    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    return {"winners": winners, "players": len(scores)}


def finalize_due_games() -> list:
    now = timezone.now()
    out = []
    for g in WisdomGame.objects.exclude(status=WisdomGame.STATUS_FINISHED).filter(ends_at__lt=now):
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


def _leaderboard(game, limit=50):
    rows = (
        WisdomScore.objects.filter(game=game, points__gt=0).select_related("user")
        .order_by("-points", "created_at")[:limit]
    )
    return [{"name": r.user.full_name or "Kitobxon", "points": r.points,
             "best_streak": r.best_streak, "reward": r.reward or 0} for r in rows]


def _lifetime(profile):
    agg = WisdomScore.objects.filter(user=profile).aggregate(
        games=Count("id"), pts=Sum("points"), best=Max("points"), best_streak=Max("best_streak"))
    return {"games": agg["games"] or 0, "points": int(agg["pts"] or 0),
            "best": int(agg["best"] or 0), "best_streak": int(agg["best_streak"] or 0)}


def _history(limit=6):
    out = []
    for g in WisdomGame.objects.filter(status=WisdomGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        top = (WisdomScore.objects.filter(game=g, points__gt=0)
               .select_related("user").order_by("-points").first())
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "winner": (top.user.full_name if top else "—") or "—",
            "winner_points": (top.points if top else 0),
            "players": WisdomScore.objects.filter(game=g, points__gt=0).count(),
        })
    return out


def state_payload(profile) -> dict:
    now = timezone.now()
    g = get_or_activate_live_game() or latest_game()
    if not g:
        return {"ok": True, "status": "none", "lifetime": _lifetime(profile), "history": _history()}

    status, qi, phase, secs = _phase(g, now)
    nq = len(g.questions or [])
    finished = status == "finished"
    my = WisdomScore.objects.filter(game=g, user=profile).first()
    payload = {
        "ok": True, "status": status, "phase": phase, "game_id": g.id,
        "q_index": qi, "q_number": qi + 1, "q_total": nq, "seconds": secs,
        "leaderboard": _leaderboard(g),
        "your_points": (my.points if my else 0),
        "your_streak": (my.streak if my else 0),
        "your_reward": (my.reward if my else 0),
        "lifetime": _lifetime(profile),
        "history": _history() if status != "live" else [],
        "streak_cap": STREAK_CAP,
    }
    if status == "live" and 0 <= qi < nq:
        q = g.questions[qi]
        payload["quote"] = q["quote"]
        payload["options"] = q["options"]
        ans = WisdomAnswer.objects.filter(game=g, user=profile, q_index=qi).first()
        payload["answered"] = bool(ans)
        if ans:
            payload["your_choice"] = ans.choice
            payload["your_correct"] = ans.is_correct
        if phase == "reveal":
            payload["correct_index"] = q.get("correct")
    return payload
