"""Emoji Kitob — live "guess the book from emojis" multiple-choice game.

Time-based phases (like Ko'pchilik): each question has an answer window then a
reveal window, so clients just poll. A correct pick scores points; top scorers
earn Kitobcha at the end (every scorer gets at least the guest reward).
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum, Count, Max
from django.utils import timezone

from tgbot.models import EmojiGame, EmojiAnswer, EmojiScore
from tgbot.services.chain_game import (
    _add_ball_reward, charge_entry_fee, ENTRY_FEE, REWARD_TIERS, PARTICIPATION,
)
from tgbot.services.game_questions import EMOJI_QUESTIONS

LEAD_SECONDS = 30
NUM_QUESTIONS = 10
ANSWER_SECONDS = 15
REVEAL_SECONDS = 5
POINTS = 10


def _prep_questions(raw):
    out = []
    for item in raw:
        opts = list(item["options"])
        correct_text = opts[item["correct"]]
        random.shuffle(opts)
        out.append({"emoji": item["emoji"], "options": opts, "correct": opts.index(correct_text)})
    return out


def _recent_used(games_back=33):
    used = set()
    for g in EmojiGame.objects.order_by("-starts_at")[:games_back]:
        for q in (g.questions or []):
            used.add(q.get("emoji"))
    return used


def create_scheduled_emoji(lead_seconds: int = LEAD_SECONDS,
                           num_questions: int = NUM_QUESTIONS) -> EmojiGame:
    num_questions = min(num_questions, len(EMOJI_QUESTIONS))
    used = _recent_used()
    fresh = [it for it in EMOJI_QUESTIONS if it["emoji"] not in used]
    random.shuffle(fresh)
    if len(fresh) < num_questions:
        rest = [it for it in EMOJI_QUESTIONS if it["emoji"] in used]
        random.shuffle(rest)
        raw = (fresh + rest)[:num_questions]
    else:
        raw = fresh[:num_questions]
    qs = _prep_questions(raw)
    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    total = len(qs) * (ANSWER_SECONDS + REVEAL_SECONDS)
    return EmojiGame.objects.create(
        status=EmojiGame.STATUS_SCHEDULED,
        starts_at=starts,
        ends_at=starts + timedelta(seconds=total),
        questions=qs, answer_seconds=ANSWER_SECONDS, reveal_seconds=REVEAL_SECONDS,
    )


def latest_game():
    return EmojiGame.objects.order_by("-starts_at").first()


def get_or_activate_live_game():
    now = timezone.now()
    g = EmojiGame.objects.filter(status=EmojiGame.STATUS_LIVE).order_by("-starts_at").first()
    if g:
        return g
    pending = (
        EmojiGame.objects
        .filter(status=EmojiGame.STATUS_SCHEDULED, starts_at__lte=now, ends_at__gte=now)
        .order_by("starts_at").first()
    )
    if not pending:
        return None
    with transaction.atomic():
        g = EmojiGame.objects.select_for_update().get(id=pending.id)
        if g.status == EmojiGame.STATUS_SCHEDULED:
            g.status = EmojiGame.STATUS_LIVE
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
    g = EmojiGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    now = timezone.now()
    status, qi, phase, _ = _phase(g, now)
    if status != "live" or phase != "answer" or qi < 0 or qi >= len(g.questions or []):
        return {"ok": False, "error": "not_answering"}

    # Entry fee: joining this competition costs ENTRY_FEE Kitobcha, charged once
    # on the user's first answer of the game.
    is_first = not EmojiAnswer.objects.filter(game_id=g.id, user=profile).exists()
    if is_first and not charge_entry_fee(profile):
        return {"ok": False, "error": "insufficient_balance", "need": ENTRY_FEE}

    q = g.questions[qi]
    correct = (choice == q.get("correct"))

    hit, created = EmojiAnswer.objects.get_or_create(
        game_id=g.id, user=profile, q_index=qi,
        defaults={"choice": choice, "is_correct": correct},
    )
    if not created:
        return {"ok": False, "error": "already_answered",
                "correct": hit.is_correct, "correct_index": q.get("correct")}
    if correct:
        score, _ = EmojiScore.objects.get_or_create(game_id=g.id, user=profile)
        score.points = (score.points or 0) + POINTS
        score.save(update_fields=["points", "updated_at"])
    return {"ok": True, "correct": correct, "correct_index": q.get("correct")}


def finalize(game_id: int) -> dict | None:
    with transaction.atomic():
        g = EmojiGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        if g.status != EmojiGame.STATUS_FINISHED:
            g.status = EmojiGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    scores = list(
        EmojiScore.objects.filter(game=g, points__gt=0)
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
            "name": s.user.full_name or "Kitobxon", "points": s.points, "reward": applied,
            "boosted": applied != reward,
        })
    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    return {"winners": winners, "players": len(scores)}


def finalize_due_games() -> list:
    now = timezone.now()
    out = []
    for g in EmojiGame.objects.exclude(status=EmojiGame.STATUS_FINISHED).filter(ends_at__lt=now):
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


def _leaderboard(game, limit=50):
    rows = (
        EmojiScore.objects.filter(game=game, points__gt=0).select_related("user")
        .order_by("-points", "created_at")[:limit]
    )
    return [{"name": r.user.full_name or "Kitobxon", "points": r.points,
             "reward": r.reward or 0} for r in rows]


def _lifetime(profile):
    agg = EmojiScore.objects.filter(user=profile).aggregate(
        games=Count("id"), pts=Sum("points"), best=Max("points"))
    return {"games": agg["games"] or 0, "points": int(agg["pts"] or 0),
            "best": int(agg["best"] or 0)}


def _history(limit=6):
    out = []
    for g in EmojiGame.objects.filter(status=EmojiGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        top = (EmojiScore.objects.filter(game=g, points__gt=0)
               .select_related("user").order_by("-points").first())
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "winner": (top.user.full_name if top else "—") or "—",
            "winner_points": (top.points if top else 0),
            "players": EmojiScore.objects.filter(game=g, points__gt=0).count(),
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
    my = EmojiScore.objects.filter(game=g, user=profile).first()
    payload = {
        "ok": True, "status": status, "phase": phase, "game_id": g.id,
        "q_index": qi, "q_number": qi + 1, "q_total": nq, "seconds": secs,
        "leaderboard": _leaderboard(g),
        "your_points": (my.points if my else 0),
        "your_reward": (my.reward if my else 0),
        "lifetime": _lifetime(profile),
        "history": _history() if status != "live" else [],
    }
    if status == "live" and 0 <= qi < nq:
        q = g.questions[qi]
        payload["emoji"] = q["emoji"]
        payload["options"] = q["options"]
        ans = EmojiAnswer.objects.filter(game=g, user=profile, q_index=qi).first()
        payload["answered"] = bool(ans)
        if ans:
            payload["your_choice"] = ans.choice
            payload["your_correct"] = ans.is_correct
        if phase == "reveal":
            payload["correct_index"] = q.get("correct")
            counts = {r["choice"]: r["c"] for r in
                      EmojiAnswer.objects.filter(game=g, q_index=qi)
                      .values("choice").annotate(c=Count("id"))}
            payload["counts"] = [counts.get(i, 0) for i in range(len(q["options"]))]
    return payload
