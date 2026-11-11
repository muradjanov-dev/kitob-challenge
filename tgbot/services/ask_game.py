"""Eng zo'r savol -- a live game where the players write the questions
(owner, 2026-11-11).

Every round the system picks one player who has not asked yet; that player
writes a question for everyone (ASK_SECONDS). The others type their answers
(ANSWER_SECONDS = 20, the owner's limit). The asker then picks the right or
the closest answer (PICK_SECONDS): its author gets BEST_POINTS, the asker
ASKER_POINTS for a question that drew answers. The best answer is shown to
everyone (REVEAL_SECONDS) and the next player asks.

The game moves on time alone: every state poll, every submission and the
minute tick call advance(), which -- under the game's row lock -- walks the
phases whose deadline has passed. So the game keeps going even when the asker
closes the page (their round is skipped).
"""
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone

from tgbot.models import AskAnswer, AskGame, AskPlayer, AskRound

LEAD_SECONDS = 60
ASK_SECONDS = 45
ANSWER_SECONDS = 20
PICK_SECONDS = 30
REVEAL_SECONDS = 7
MAX_ROUNDS = 6
MAX_MINUTES = 12
MIN_PLAYERS = 2
# A game nobody (or only one reader) joined ends this long after its start
# instead of holding the evening sequence for MAX_MINUTES.
WAIT_SECONDS = 180
BEST_POINTS = 100
ASKER_POINTS = 30
MAX_QUESTION = 200
MAX_ANSWER = 120


def create_scheduled_game(lead_seconds: int = LEAD_SECONDS) -> AskGame:
    starts = timezone.now() + timedelta(seconds=lead_seconds)
    return AskGame.objects.create(status=AskGame.STATUS_SCHEDULED, starts_at=starts,
                                  ends_at=starts + timedelta(minutes=MAX_MINUTES), phase="lobby")


def latest_game():
    return AskGame.objects.order_by("-starts_at").first()


def _current_round(g):
    if g.round_index < 0:
        return None
    return AskRound.objects.filter(game=g, index=g.round_index).select_related("asker").first()


def _set_phase(g, phase, now, seconds=None):
    g.phase = phase
    g.phase_ends_at = now + timedelta(seconds=seconds) if seconds is not None else None


def _finish(g, now):
    g.status = AskGame.STATUS_FINISHED
    _set_phase(g, "done", now)
    if g.ends_at > now:
        g.ends_at = now


def _start_next_round(g, now):
    """Pick the next asker, or wait for players, or end the game."""
    if now >= g.ends_at or g.round_index + 1 >= MAX_ROUNDS:
        _finish(g, now)
        return
    players = list(AskPlayer.objects.filter(game=g))
    if len(players) < MIN_PLAYERS:
        _set_phase(g, "waiting", now)
        return
    candidates = [p for p in players if not p.has_asked]
    if not candidates:
        _finish(g, now)
        return
    pick = secrets.SystemRandom().choice(candidates)
    AskPlayer.objects.filter(id=pick.id).update(has_asked=True)
    g.round_index += 1
    AskRound.objects.create(game=g, index=g.round_index, asker_id=pick.user_id)
    _set_phase(g, "ask", now, ASK_SECONDS)


def _step(g, now) -> bool:
    """Move one phase on if its time is up. True when something changed."""
    if g.status == AskGame.STATUS_FINISHED:
        return False
    if g.phase == "lobby":
        if now < g.starts_at:
            return False
        g.status = AskGame.STATUS_LIVE
        _start_next_round(g, now)
        return True
    if g.phase == "waiting":
        if now >= g.ends_at or now >= g.starts_at + timedelta(seconds=WAIT_SECONDS):
            _finish(g, now)
            return True
        if AskPlayer.objects.filter(game=g).count() >= MIN_PLAYERS:
            _start_next_round(g, now)
            return True
        return False
    if g.phase_ends_at and now < g.phase_ends_at:
        return False
    r = _current_round(g)
    if g.phase == "ask":
        if r:
            r.skipped = True
            r.save(update_fields=["skipped", "updated_at"])
        _start_next_round(g, now)
    elif g.phase == "answer":
        if r and AskAnswer.objects.filter(round=r).exists():
            _set_phase(g, "pick", now, PICK_SECONDS)
        else:
            _set_phase(g, "reveal", now, REVEAL_SECONDS)
    elif g.phase == "pick":
        _set_phase(g, "reveal", now, REVEAL_SECONDS)
    elif g.phase == "reveal":
        _start_next_round(g, now)
    else:
        return False
    return True


def _needs_step(g, now) -> bool:
    if g.status == AskGame.STATUS_FINISHED:
        return False
    if g.phase == "lobby":
        return now >= g.starts_at
    if g.phase == "waiting":
        return True
    return bool(g.phase_ends_at and now >= g.phase_ends_at)


def advance(game_id, now=None):
    """Walk every phase whose deadline has passed; returns the fresh game."""
    now = now or timezone.now()
    g = AskGame.objects.filter(id=game_id).first()
    if not g or not _needs_step(g, now):
        return g
    with transaction.atomic():
        g = AskGame.objects.select_for_update().get(id=game_id)
        changed = False
        for _ in range(12):
            if not _step(g, now):
                break
            changed = True
        if changed:
            g.save()
    return g


def _open_game():
    g = latest_game()
    if not g:
        return None
    return advance(g.id)


# ── Player actions ───────────────────────────────────────────────────────────

def join(profile) -> dict:
    g = _open_game()
    if not g or g.status == AskGame.STATUS_FINISHED:
        return {"ok": False, "error": "not_live"}
    AskPlayer.objects.get_or_create(game=g, user=profile)
    return {"ok": True}


def submit_question(profile, text: str) -> dict:
    text = " ".join((text or "").split())[:MAX_QUESTION]
    if len(text) < 3:
        return {"ok": False, "error": "empty"}
    g = _open_game()
    if not g:
        return {"ok": False, "error": "not_live"}
    now = timezone.now()
    with transaction.atomic():
        g = AskGame.objects.select_for_update().get(id=g.id)
        r = _current_round(g)
        if g.phase != "ask" or not r or r.asker_id != profile.id:
            return {"ok": False, "error": "not_your_turn"}
        r.question = text
        r.save(update_fields=["question", "updated_at"])
        _set_phase(g, "answer", now, ANSWER_SECONDS)
        g.save()
    return {"ok": True}


def submit_answer(profile, text: str) -> dict:
    text = " ".join((text or "").split())[:MAX_ANSWER]
    if not text:
        return {"ok": False, "error": "empty"}
    g = _open_game()
    if not g or g.phase != "answer":
        return {"ok": False, "error": "not_answering"}
    r = _current_round(g)
    if not r:
        return {"ok": False, "error": "not_answering"}
    if r.asker_id == profile.id:
        return {"ok": False, "error": "you_asked"}
    AskPlayer.objects.get_or_create(game=g, user=profile)
    AskAnswer.objects.update_or_create(round=r, user=profile, defaults={"text": text})
    return {"ok": True}


def pick(profile, answer_id) -> dict:
    g = _open_game()
    if not g:
        return {"ok": False, "error": "not_live"}
    now = timezone.now()
    with transaction.atomic():
        g = AskGame.objects.select_for_update().get(id=g.id)
        r = _current_round(g)
        if g.phase != "pick" or not r or r.asker_id != profile.id:
            return {"ok": False, "error": "not_your_turn"}
        a = AskAnswer.objects.filter(round=r, id=answer_id).first()
        if not a:
            return {"ok": False, "error": "bad_answer"}
        r.best_answer_id = a.id
        r.save(update_fields=["best_answer_id", "updated_at"])
        from django.db.models import F
        AskPlayer.objects.filter(game=g, user_id=a.user_id).update(points=F("points") + BEST_POINTS)
        AskPlayer.objects.filter(game=g, user_id=r.asker_id).update(points=F("points") + ASKER_POINTS)
        _set_phase(g, "reveal", now, REVEAL_SECONDS)
        g.save()
    return {"ok": True}


# ── End of game ──────────────────────────────────────────────────────────────

def finalize(game_id: int):
    from tgbot.services.chain_game import PARTICIPATION, REWARD_TIERS, _add_ball_reward
    with transaction.atomic():
        g = AskGame.objects.select_for_update().get(id=game_id)
        if g.rewarded:
            return None
        if g.status != AskGame.STATUS_FINISHED:
            _finish(g, timezone.now())
        g.rewarded = True
        g.save()
    # Only players who took part: asked a question, or answered one.
    active = set(AskAnswer.objects.filter(round__game=g).values_list("user_id", flat=True))
    active |= set(AskRound.objects.filter(game=g).exclude(question="").values_list("asker_id", flat=True))
    rows = list(AskPlayer.objects.filter(game=g, user_id__in=active).select_related("user")
                .order_by("-points", "created_at"))
    winners = []
    for i, s in enumerate(rows):
        reward = REWARD_TIERS[i] if (s.points > 0 and i < 3) else PARTICIPATION
        if not s.rewarded:
            applied = _add_ball_reward(s.user, reward)
            s.rewarded, s.reward = True, applied
            s.save(update_fields=["rewarded", "reward", "updated_at"])
        else:
            applied = s.reward or reward
        winners.append({"rank": i + 1, "user_id": s.user_id, "telegram_id": s.user.telegram_id,
                        "name": s.user.full_name or "Kitobxon", "points": s.points, "reward": applied,
                        "boosted": applied != reward})
    best = []
    for r in AskRound.objects.filter(game=g, best_answer_id__isnull=False).select_related("asker"):
        a = AskAnswer.objects.filter(id=r.best_answer_id).select_related("user").first()
        if a:
            best.append({"question": r.question, "answer": a.text, "by": a.user.full_name or "Kitobxon",
                         "asker": r.asker.full_name or "Kitobxon"})
    return {"winners": winners, "players": len(rows), "best": best}


def finalize_due_games() -> list:
    """For the minute tick: move live games on, then settle finished ones."""
    now = timezone.now()
    for g in AskGame.objects.filter(rewarded=False).exclude(status=AskGame.STATUS_FINISHED):
        advance(g.id, now)
    out = []
    for g in AskGame.objects.filter(rewarded=False, status=AskGame.STATUS_FINISHED):
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


# ── What a player sees ───────────────────────────────────────────────────────

def _first(name) -> str:
    return ((name or "").split() or ["Kitobxon"])[0]


def _leaderboard(g, limit=20):
    return [{"name": p.user.full_name or "Kitobxon", "points": p.points, "reward": p.reward}
            for p in AskPlayer.objects.filter(game=g).select_related("user").order_by("-points", "created_at")[:limit]]


def _lifetime(profile):
    agg = AskPlayer.objects.filter(user=profile).aggregate(games=Count("id"), pts=Sum("points"), best=Max("points"))
    return {"games": agg["games"] or 0, "points": int(agg["pts"] or 0), "best": int(agg["best"] or 0)}


def _history(limit=5):
    out = []
    for g in AskGame.objects.filter(status=AskGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        top = AskPlayer.objects.filter(game=g, points__gt=0).select_related("user").order_by("-points").first()
        out.append({"date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
                    "winner": (top.user.full_name if top else "—") or "—",
                    "winner_points": top.points if top else 0,
                    "players": AskPlayer.objects.filter(game=g).count()})
    return out


def state_payload(profile) -> dict:
    g = _open_game()
    if not g:
        return {"ok": True, "status": "none", "lifetime": _lifetime(profile), "history": _history()}
    now = timezone.now()
    me = AskPlayer.objects.filter(game=g, user=profile).first()
    if g.phase == "lobby":
        secs = max(0, int((g.starts_at - now).total_seconds()))
    elif g.phase_ends_at:
        secs = max(0, int((g.phase_ends_at - now).total_seconds()) + 1)
    else:
        secs = max(0, int((g.ends_at - now).total_seconds()))
    p = {
        "ok": True, "status": g.status, "phase": g.phase, "game_id": g.id, "seconds": secs,
        "round": g.round_index + 1, "rounds_max": MAX_ROUNDS, "joined": bool(me),
        "your_points": me.points if me else 0, "your_reward": me.reward if me else 0,
        "players": AskPlayer.objects.filter(game=g).count(), "min_players": MIN_PLAYERS,
        "leaderboard": _leaderboard(g), "lifetime": _lifetime(profile),
        "history": _history() if g.status == AskGame.STATUS_FINISHED else [],
        "limits": {"question": MAX_QUESTION, "answer": MAX_ANSWER, "answer_seconds": ANSWER_SECONDS},
    }
    r = _current_round(g)
    if not r or g.status == AskGame.STATUS_FINISHED:
        return p
    p.update({"asker": _first(r.asker.full_name), "is_asker": r.asker_id == profile.id,
              "question": r.question})
    answers = list(AskAnswer.objects.filter(round=r).select_related("user"))
    mine = next((a for a in answers if a.user_id == profile.id), None)
    p["answers_count"] = len(answers)
    p["your_answer"] = mine.text if mine else ""
    if g.phase == "pick":
        # Anonymous while the asker chooses: the answer is judged, not its author.
        p["answers"] = [{"id": a.id, "text": a.text} for a in answers]
    elif g.phase == "reveal":
        p["answers"] = [{"id": a.id, "text": a.text, "name": _first(a.user.full_name),
                         "best": a.id == r.best_answer_id} for a in answers]
        best = next((a for a in answers if a.id == r.best_answer_id), None)
        p["best"] = {"text": best.text, "name": best.user.full_name or "Kitobxon"} if best else None
    return p
