"""Omon qolish — live elimination-survival multiple-choice game.

Every question round, any joined (non-eliminated) player who answers wrong OR
doesn't answer at all loses a life. `max_lives` (default 3) lives; 0 lives =
eliminated. Whoever is still standing when the rounds run out splits the
jackpot; if everyone gets eliminated, the highest correct-answer count(s)
split it instead so there's always a discernible winner. Free to enter
(every live game became free on 2026-08-19; see chain_game.charge_entry_fee).
"""

import random
from datetime import timedelta

from django.db import transaction

from django.utils import timezone

from django.db.models import F

from tgbot.models import (
    SurvivalGame, SurvivalPlayer, SurvivalAnswer, TelegramProfile, GameJoker,
)
from tgbot.services.chain_game import _add_ball_reward, charge_entry_fee, PARTICIPATION
from tgbot.services import game_jokers
from tgbot.services.game_questions import SURVIVAL_QUESTIONS

GAME_TYPE = "survival"  # GameJoker.game_type
ENTRY_FEE = 0  # bepul (2026-08-19)
LEAD_SECONDS = 30
NUM_QUESTIONS = 12
QUESTION_SECONDS = 15
MAX_LIVES = 3
JACKPOT = 400


def _prep_questions(raw):
    out = []
    for item in raw:
        opts = list(item["options"])
        correct_text = opts[item["correct"]]
        random.shuffle(opts)
        out.append({"q": item["q"], "options": opts, "correct": opts.index(correct_text)})
    return out


from tgbot.services.question_picker import pick_least_recently_used


def create_scheduled_survival(lead_seconds: int = LEAD_SECONDS,
                              num_questions: int = NUM_QUESTIONS,
                              max_lives: int = MAX_LIVES,
                              jackpot: int = JACKPOT) -> SurvivalGame:
    recent_games = SurvivalGame.objects.order_by("-starts_at")[:100]
    raw = pick_least_recently_used(
        pool=SURVIVAL_QUESTIONS,
        get_key_fn=lambda it: it.get("q"),
        recent_games=recent_games,
        get_game_keys_fn=lambda g: [q.get("q") for q in (g.questions or []) if isinstance(q, dict)],
        count=num_questions,
    )
    qs = _prep_questions(raw)
    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    total = len(qs) * QUESTION_SECONDS
    return SurvivalGame.objects.create(
        status=SurvivalGame.STATUS_SCHEDULED,
        starts_at=starts,
        ends_at=starts + timedelta(seconds=total),
        questions=qs, question_seconds=QUESTION_SECONDS,
        max_lives=max_lives, jackpot=jackpot,
    )


def latest_game():
    return SurvivalGame.objects.order_by("-starts_at").first()


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


def _ensure_lives_resolved(game, closed_count):
    """Deduct a life from every joined, non-eliminated player for each round
    that has closed without a correct answer from them. Idempotent via
    `scored_indices`."""
    if closed_count <= len(game.scored_indices or []):
        return
    with transaction.atomic():
        g = SurvivalGame.objects.select_for_update().get(id=game.id)
        done = set(g.scored_indices or [])
        changed = False
        for qi in range(0, min(closed_count, len(g.questions or []))):
            if qi in done:
                continue
            correct_user_ids = set(
                SurvivalAnswer.objects.filter(game=g, q_index=qi, is_correct=True)
                .values_list("user_id", flat=True)
            )
            players = SurvivalPlayer.objects.select_for_update().filter(game=g, eliminated=False)
            for p in players:
                if p.user_id in correct_user_ids:
                    p.correct_count = (p.correct_count or 0) + 1
                    p.save(update_fields=["correct_count", "updated_at"])
                else:
                    p.lives = max(0, (p.lives or 0) - 1)
                    if p.lives == 0:
                        p.eliminated = True
                        p.eliminated_at_round = qi
                        p.save(update_fields=["lives", "eliminated", "eliminated_at_round", "updated_at"])
                    else:
                        p.save(update_fields=["lives", "updated_at"])
            done.add(qi)
            changed = True
        if changed:
            g.scored_indices = sorted(done)
            g.save(update_fields=["scored_indices", "updated_at"])


def _join(game, profile):
    """O'yinchi qatorini oladi yoki yaratadi. `(player, error)` qaytaradi.

    Birinchi javob ham, birinchi joker ham shu yerdan o'tadi — o'yinga kirish
    (kirish to'lovi va Market 'Sirli quti' bonus jonlari) faqat bir marta,
    bir joyda qo'llanishi uchun.
    """
    player, created = SurvivalPlayer.objects.get_or_create(
        game_id=game.id, user=profile, defaults={"lives": game.max_lives},
    )
    if created:
        if not charge_entry_fee(profile, amount=ENTRY_FEE):
            SurvivalPlayer.objects.filter(id=player.id).delete()
            return None, "insufficient_balance"
        # Spend any Market 'Sirli quti' bonus lives (capped at +2) on join.
        bonus = min(int(getattr(profile, "bonus_survival_lives", 0) or 0), 2)
        if bonus:
            TelegramProfile.objects.filter(id=profile.id).update(bonus_survival_lives=0)
            player.lives = player.lives + bonus
            player.save(update_fields=["lives"])
    return player, None


def submit_answer(game_id: int, profile, choice: int) -> dict:
    g = SurvivalGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    now = timezone.now()
    status, qi, _ = _phase(g, now)
    if status != "live" or qi < 0 or qi >= len(g.questions or []):
        return {"ok": False, "error": "not_live"}

    _ensure_lives_resolved(g, qi)  # resolve any rounds that closed before this one

    player, err = _join(g, profile)
    if err:
        return {"ok": False, "error": err, "need": ENTRY_FEE}
    if player.eliminated:
        return {"ok": False, "error": "eliminated"}

    q = g.questions[qi]
    correct = (choice == q.get("correct"))

    span = g.question_seconds
    elapsed = (now - g.starts_at).total_seconds()
    within = max(0.01, elapsed - qi * span)
    time_taken = round(within, 3)

    answer, created_ans = SurvivalAnswer.objects.get_or_create(
        game_id=g.id, user=profile, q_index=qi,
        defaults={"choice": choice, "is_correct": correct, "time_taken": time_taken},
    )
    if not created_ans:
        return {"ok": False, "error": "already_answered",
                "correct": answer.is_correct, "correct_index": q.get("correct")}

    player.total_time = round((player.total_time or 0.0) + time_taken, 3)
    player.save(update_fields=["total_time", "updated_at"])

    return {"ok": True, "correct": correct, "correct_index": q.get("correct"),
            "lives": player.lives}


def use_joker(game_id: int, profile, kind: str) -> dict:
    """💡/❤️/🎯 jokerini sotib olish va qo'llash (Omon qolish).

    ❤️ bu yerda haqiqiy qo'shimcha jon: `SurvivalPlayer.lives` ga +1. Ataylab
    faqat chetlatilishdan OLDIN olinadi — chetlatilgandan keyin "tirilish"
    yo'q, aks holda balansi katta o'yinchi umuman yutqazmasdi.
    """
    if kind not in game_jokers.KINDS:
        return {"ok": False, "error": "bad_joker"}
    g = SurvivalGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    now = timezone.now()
    status, qi, _ = _phase(g, now)
    if status != "live" or qi < 0 or qi >= len(g.questions or []):
        return {"ok": False, "error": "not_live"}

    # Avval yopilgan turlarni hisoblab qo'yamiz: aks holda aslida allaqachon
    # chetlatilgan o'yinchi "tirik" ko'rinib, joker sotib olib yuborardi.
    _ensure_lives_resolved(g, qi)

    player, err = _join(g, profile)
    if err:
        return {"ok": False, "error": err, "need": ENTRY_FEE}
    player.refresh_from_db()
    if player.eliminated:
        return {"ok": False, "error": "eliminated", "balance": int(profile.ball or 0)}

    q = g.questions[qi]
    price = game_jokers.PRICES[kind]
    balance = int(profile.ball or 0)
    answered = SurvivalAnswer.objects.filter(game_id=g.id, user=profile, q_index=qi).exists()

    if kind in (game_jokers.FIFTY, game_jokers.SNIPER) and answered:
        return {"ok": False, "error": "already_answered", "balance": balance}

    # 50/50 va snayper savolning to'g'ri javob indeksiga tayanadi. Agar u
    # buzuq bo'lsa (int emas yoki diapazondan tashqarida), 50/50 to'g'ri
    # javobni yashirib qo'yishi, snayper esa saqlab bo'lmaydigan javob
    # yozishga urinishi mumkin edi — shuning uchun pul yechilmasdan to'xtaymiz.
    if kind in (game_jokers.FIFTY, game_jokers.SNIPER):
        ci = q.get("correct")
        if not isinstance(ci, int) or not (0 <= ci < len(q.get("options") or [])):
            return {"ok": False, "error": "joker_unavailable", "balance": balance}

    payload = None
    if kind == game_jokers.FIFTY:
        hidden = game_jokers.pick_hidden(q.get("options") or [], q.get("correct", -1))
        if not hidden:
            return {"ok": False, "error": "joker_unavailable", "balance": balance}
        payload = {"hidden": hidden}
    elif kind == game_jokers.SHIELD:
        if game_jokers.shield_count(profile, GAME_TYPE, g.id) >= game_jokers.MAX_SHIELDS_PER_GAME:
            return {"ok": False, "error": "joker_limit", "balance": balance}
        # Bir turda bitta jon — takroriy so'rov ikkinchi jonni sotib olib
        # yubormasin. Ikkinchisini keyingi savolda olish mumkin.
        if game_jokers.find(profile, GAME_TYPE, g.id, qi, game_jokers.SHIELD):
            return {"ok": False, "error": "joker_round_limit", "balance": balance}

    joker, created, err = game_jokers.buy(
        profile, game_type=GAME_TYPE, game_id=g.id, q_index=qi, kind=kind,
        payload=payload,
    )
    if err:
        return {"ok": False, "error": err, "need": price, "balance": balance}

    out = {"ok": True, "kind": kind, "charged": price if created else 0,
           "balance": int(profile.ball or 0)}

    if kind == game_jokers.FIFTY:
        out["hidden"] = list((joker.payload or {}).get("hidden") or [])
    elif kind == game_jokers.SHIELD:
        if created:
            # F() bilan — shu payt boshqa tur yopilib jon yechilayotgan
            # bo'lsa ham qo'shimcha jon yo'qolib ketmasin.
            SurvivalPlayer.objects.filter(id=player.id, eliminated=False).update(
                lives=F("lives") + 1,
            )
            player.refresh_from_db()
        out["lives"] = player.lives
        out["shields_bought"] = game_jokers.shield_count(profile, GAME_TYPE, g.id)
    elif kind == game_jokers.SNIPER:
        res = submit_answer(g.id, profile, q.get("correct"))
        if not res.get("ok") and res.get("error") != "already_answered":
            if created:
                GameJoker.objects.filter(id=joker.id).delete()
                game_jokers.refund(profile, price, f"joker_{kind}_refund")
            return {"ok": False, "error": res.get("error") or "failed",
                    "balance": int(profile.ball or 0)}
        out["choice"] = q.get("correct")
        out["correct_index"] = q.get("correct")
        out["correct"] = True
        out["balance"] = int(profile.ball or 0)
    return out


def finalize(game_id: int) -> dict | None:
    with transaction.atomic():
        g = SurvivalGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        if g.status != SurvivalGame.STATUS_FINISHED:
            g.status = SurvivalGame.STATUS_FINISHED
            g.save(update_fields=["status", "updated_at"])
    if already:
        return None

    _ensure_lives_resolved(g, len(g.questions or []))  # resolve any remaining rounds

    players = list(SurvivalPlayer.objects.filter(game=g).select_related("user"))
    survivors = [p for p in players if not p.eliminated]
    winners = []

    if survivors:
        share = max(1, g.jackpot // len(survivors))
        for p in survivors:
            applied = _add_ball_reward(p.user, share)
            p.reward = applied
            p.rewarded = True
            p.save(update_fields=["reward", "rewarded", "updated_at"])
            winners.append({
                "user_id": p.user_id, "telegram_id": p.user.telegram_id,
                "name": p.user.full_name or "Kitobxon", "correct": p.correct_count,
                "total_time": p.total_time or 0.0,
                "time": round(p.total_time or 0.0, 1),
                "survived": True, "reward": applied,
            })
        for p in players:
            if p.eliminated and p.correct_count > 0 and not p.rewarded:
                applied = _add_ball_reward(p.user, PARTICIPATION)
                p.reward = applied
                p.rewarded = True
                p.save(update_fields=["reward", "rewarded", "updated_at"])
    else:
        # Everyone was eliminated — the highest correct-answer count(s) split
        # the jackpot instead, so the game always has a winner.
        best = max((p.correct_count for p in players), default=0)
        top = [p for p in players if best > 0 and p.correct_count == best]
        if top:
            share = max(1, g.jackpot // len(top))
            for p in top:
                applied = _add_ball_reward(p.user, share)
                p.reward = applied
                p.rewarded = True
                p.save(update_fields=["reward", "rewarded", "updated_at"])
                winners.append({
                    "user_id": p.user_id, "telegram_id": p.user.telegram_id,
                    "name": p.user.full_name or "Kitobxon", "correct": p.correct_count,
                    "total_time": p.total_time or 0.0,
                    "time": round(p.total_time or 0.0, 1),
                    "survived": False, "reward": applied,
                })

    winners.sort(key=lambda w: (-w["survived"], -w["correct"], w.get("total_time", 0.0)))
    g.rewarded = True
    g.save(update_fields=["rewarded", "updated_at"])
    return {"winners": winners, "players": len(players), "survivors": len(survivors)}


def finalize_due_games() -> list:
    now = timezone.now()
    out = []
    for g in SurvivalGame.objects.exclude(status=SurvivalGame.STATUS_FINISHED).filter(ends_at__lt=now):
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


def _leaderboard(game, limit=50):
    rows = (
        SurvivalPlayer.objects.filter(game=game).select_related("user")
        .order_by("eliminated", "-correct_count", "total_time", "created_at")[:limit]
    )
    return [{"name": r.user.full_name or "Kitobxon", "lives": r.lives,
             "correct": r.correct_count, "eliminated": r.eliminated,
             "reward": r.reward or 0} for r in rows]


def _lifetime(profile):
    games = SurvivalPlayer.objects.filter(user=profile).values("game").distinct().count()
    survived = SurvivalPlayer.objects.filter(user=profile, eliminated=False).count()
    return {"games": games, "survived": survived}


def _history(limit=6):
    out = []
    for g in SurvivalGame.objects.filter(status=SurvivalGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        survivors = SurvivalPlayer.objects.filter(game=g, eliminated=False).count()
        players = SurvivalPlayer.objects.filter(game=g).count()
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "survivors": survivors, "players": players,
        })
    return out


def state_payload(profile) -> dict:
    now = timezone.now()
    g = latest_game()
    if not g:
        return {"ok": True, "status": "none", "lifetime": _lifetime(profile),
                "history": _history(), "balance": int(profile.ball or 0),
                "joker_prices": game_jokers.prices_payload()}

    status, qi, left = _phase(g, now)
    nq = len(g.questions or [])
    if status == "live":
        _ensure_lives_resolved(g, qi)
    my = SurvivalPlayer.objects.filter(game=g, user=profile).first()

    # Before joining (no SurvivalPlayer row yet), preview lives including any
    # pending Market 'Sirli quti' bonus — otherwise the lobby shows the bare
    # max_lives and it looks like the bonus "didn't work" until the user's
    # first answer actually creates the row and applies it.
    if my:
        preview_lives = my.lives
    else:
        pending_bonus = min(int(getattr(profile, "bonus_survival_lives", 0) or 0), 2)
        preview_lives = g.max_lives + pending_bonus

    payload = {
        "ok": True, "status": status, "game_id": g.id,
        "q_number": qi + 1, "q_total": nq, "seconds": left,
        "max_lives": g.max_lives, "jackpot": g.jackpot,
        "your_lives": preview_lives,
        "your_correct": (my.correct_count if my else 0),
        "eliminated": (my.eliminated if my else False),
        "your_reward": (my.reward if my else 0),
        "leaderboard": _leaderboard(g),
        "lifetime": _lifetime(profile),
        "history": _history() if status != "live" else [],
        "balance": int(profile.ball or 0),
        "joker_prices": game_jokers.prices_payload(),
    }
    if status == "live" and 0 <= qi < nq:
        q = g.questions[qi]
        payload["question"] = q["q"]
        payload["options"] = q["options"]
        if my:
            ans = SurvivalAnswer.objects.filter(game=g, user=profile, q_index=qi).first()
            if ans:
                payload["answered"] = True
                payload["your_correct_this_round"] = ans.is_correct
                payload["correct_index"] = q.get("correct")
            else:
                payload["answered"] = False
        else:
            payload["answered"] = False
        payload["jokers"] = game_jokers.summarize(
            game_jokers.game_rows(profile, GAME_TYPE, g.id), qi,
        )
    return payload
