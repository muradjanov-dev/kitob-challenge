"""Bilim Qal'asi — a cooperative live quiz. Everyone answers multiple-choice
literary questions; each correct answer damages a shared boss. If the community
drops the boss to 0 HP before time runs out, every contributor wins Kitobcha.

Boss damage uses an atomic F()-expression update (no row lock) so many correct
answers can land at once without contention.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q, Count
from django.db.models.functions import Greatest
from django.utils import timezone

from tgbot.models import CastleGame, CastleHit
from tgbot.services.chain_game import _add_ball_reward, charge_entry_fee, ENTRY_FEE
from tgbot.services.game_questions import CASTLE_QUESTIONS

LEAD_SECONDS = 30
NUM_QUESTIONS = 15
QUESTION_SECONDS = 20
BOSS_HP = 600
DAMAGE = 10

VICTORY_REWARD = 100      # per contributor (>=1 correct) when the boss falls
CONTRIB_CONSOLATION = 30  # answered but no correct, or defeat


def _prep_questions(raw):
    out = []
    for item in raw:
        opts = list(item["options"])
        correct_text = opts[item["correct"]]
        random.shuffle(opts)
        out.append({"q": item["q"], "options": opts, "correct": opts.index(correct_text)})
    return out


def _recent_used(games_back=33):
    used = set()
    for g in CastleGame.objects.order_by("-starts_at")[:games_back]:
        for item in (g.questions or []):
            used.add(item.get("q"))
    return used


def create_scheduled_castle(lead_seconds: int = LEAD_SECONDS,
                            num_questions: int = NUM_QUESTIONS,
                            boss_hp: int = BOSS_HP) -> CastleGame:
    num_questions = min(num_questions, len(CASTLE_QUESTIONS))
    used = _recent_used()
    fresh = [it for it in CASTLE_QUESTIONS if it["q"] not in used]
    random.shuffle(fresh)
    if len(fresh) < num_questions:
        rest = [it for it in CASTLE_QUESTIONS if it["q"] in used]
        random.shuffle(rest)
        raw = (fresh + rest)[:num_questions]
    else:
        raw = fresh[:num_questions]
    qs = _prep_questions(raw)
    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    total = len(qs) * QUESTION_SECONDS
    return CastleGame.objects.create(
        status=CastleGame.STATUS_SCHEDULED,
        starts_at=starts,
        ends_at=starts + timedelta(seconds=total),
        boss_hp_max=boss_hp, boss_hp=boss_hp, damage_per_hit=DAMAGE,
        questions=qs, question_seconds=QUESTION_SECONDS,
    )


def latest_game():
    return CastleGame.objects.order_by("-starts_at").first()


def _phase(game, now):
    span = game.question_seconds
    nq = len(game.questions or [])
    total = span * nq
    elapsed = (now - game.starts_at).total_seconds()
    if elapsed < 0:
        return "scheduled", -1, int(-elapsed)
    if elapsed >= total:
        return "finished", nq, 0
    qi = int(elapsed // span)
    left = int(span - (elapsed - qi * span)) + 1
    return "live", qi, left


def submit_answer(game_id: int, profile, choice: int) -> dict:
    g = CastleGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    now = timezone.now()
    status, qi, _ = _phase(g, now)
    if status != "live" or qi < 0 or qi >= len(g.questions or []):
        return {"ok": False, "error": "not_live"}

    # Entry fee: joining this competition costs ENTRY_FEE Kitobcha, charged once
    # on the user's first answer of the game.
    is_first = not CastleHit.objects.filter(game_id=g.id, user=profile).exists()
    if is_first and not charge_entry_fee(profile):
        return {"ok": False, "error": "insufficient_balance", "need": ENTRY_FEE}

    q = g.questions[qi]
    correct = (choice == q.get("correct"))

    hit, created = CastleHit.objects.get_or_create(
        game_id=g.id, user=profile, q_index=qi, defaults={"is_correct": correct},
    )
    if not created:
        return {"ok": False, "error": "already_answered",
                "correct": hit.is_correct, "correct_index": q.get("correct")}

    boss_hp = g.boss_hp
    if correct:
        CastleGame.objects.filter(id=g.id).update(
            boss_hp=Greatest(F("boss_hp") - g.damage_per_hit, 0),
        )
        g.refresh_from_db(fields=["boss_hp", "victory"])
        boss_hp = g.boss_hp
        if boss_hp == 0 and not g.victory:
            CastleGame.objects.filter(id=g.id, victory=False).update(victory=True)
    return {"ok": True, "correct": correct, "correct_index": q.get("correct"),
            "boss_hp": boss_hp}


def finalize(game_id: int) -> dict | None:
    with transaction.atomic():
        g = CastleGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        victory = g.victory or g.boss_hp == 0
        if g.status != CastleGame.STATUS_FINISHED:
            g.status = CastleGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    rows = list(
        CastleHit.objects.filter(game=g)
        .values("user_id")
        .annotate(correct=Count("id", filter=Q(is_correct=True)))
    )
    from tgbot.models import TelegramProfile
    users = {u.id: u for u in TelegramProfile.objects.filter(
        id__in=[r["user_id"] for r in rows])}
    contributors = 0
    rewarded = []
    for row in rows:
        uid = row["user_id"]
        correct = row["correct"]
        reward = VICTORY_REWARD if (victory and correct > 0) else CONTRIB_CONSOLATION
        user = users.get(uid)
        if not user:
            continue
        applied = _add_ball_reward(user, reward)
        if correct > 0:
            contributors += 1
        rewarded.append({
            "user_id": uid, "telegram_id": user.telegram_id,
            "name": user.full_name or "Kitobxon", "correct": correct, "reward": applied,
            "boosted": applied != reward,
        })
    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    rewarded.sort(key=lambda r: r["correct"], reverse=True)
    return {"victory": victory, "players": len(rewarded), "contributors": contributors,
            "winners": rewarded}


def finalize_due_games() -> list:
    now = timezone.now()
    out = []
    for g in CastleGame.objects.exclude(status=CastleGame.STATUS_FINISHED).filter(ends_at__lt=now):
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


def _leaderboard(game, limit=10):
    # Single query — pull the name via the FK join instead of a per-row lookup
    # (this runs on every poll during a live game).
    rows = (
        CastleHit.objects.filter(game=game, is_correct=True)
        .values("user_id", "user__full_name")
        .annotate(correct=Count("id"))
        .order_by("-correct")[:limit]
    )
    return [{"name": r["user__full_name"] or "Kitobxon", "correct": r["correct"]} for r in rows]


def _lifetime(profile):
    games = CastleHit.objects.filter(user=profile).values("game").distinct().count()
    correct = CastleHit.objects.filter(user=profile, is_correct=True).count()
    return {"games": games, "correct": correct}


def _history(limit=6):
    out = []
    for g in CastleGame.objects.filter(status=CastleGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        players = CastleHit.objects.filter(game=g).values("user").distinct().count()
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "victory": g.victory or g.boss_hp == 0,
            "players": players,
        })
    return out


def _cached_leaderboard(game, limit=10):
    """Shared across all pollers — computed at most once every 2s (Redis)."""
    from django.core.cache import cache
    key = f"castle:lb:{game.id}:{limit}"
    try:
        v = cache.get(key)
        if v is not None:
            return v
    except Exception:
        pass
    v = _leaderboard(game, limit=limit)
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

    status, qi, left = _phase(g, now)
    nq = len(g.questions or [])
    my_correct = CastleHit.objects.filter(game=g, user=profile, is_correct=True).count()

    payload = {
        "ok": True, "status": status, "game_id": g.id,
        "boss_name": g.boss_name, "boss_hp": g.boss_hp, "boss_hp_max": g.boss_hp_max,
        "victory": g.victory or g.boss_hp == 0,
        "seconds": left, "q_number": qi + 1, "q_total": nq,
        "my_correct": my_correct,
        "leaderboard": _cached_leaderboard(g, 50),
        "lifetime": _lifetime(profile),
        "history": _history() if status != "live" else [],
    }
    if status == "live" and 0 <= qi < nq:
        q = g.questions[qi]
        payload["question"] = q["q"]
        payload["options"] = q["options"]
        hit = CastleHit.objects.filter(game=g, user=profile, q_index=qi).first()
        if hit:
            payload["answered"] = True
            payload["your_correct"] = hit.is_correct
            payload["correct_index"] = q.get("correct")  # revealed only after answering
        else:
            payload["answered"] = False
    if status == "finished":
        victory = g.victory or g.boss_hp == 0
        payload["your_reward"] = (VICTORY_REWARD if (victory and my_correct > 0)
                                  else (CONTRIB_CONSOLATION if my_correct >= 0 and
                                        CastleHit.objects.filter(game=g, user=profile).exists() else 0))
    return payload
