"""Bilim O'yini — one shared MC-quiz engine for 8 content flavors:

  twofacts   — Ikki haqiqat, bir yolg'on: 3 statements, spot the fake one.
  impostor   — Kim yolg'onchi?: 3 real book/author pairings + 1 fabricated one.
  connection — Yashirin bog'lanish: 4 items share a hidden theme, name it.
  teams      — Jamoa Jangi: players are auto-split into two balanced teams as
               they join (alternating A/B); a TEAM's cumulative correct
               answers (not individuals) decide the winning side, which then
               splits a jackpot.
  timeline   — Vaqt Mashinasi: guess which era/century a book or thinker
               belongs to.
  matchbook  — Muallif-Asar Moslashtirish: given an author, pick their real
               book from 4 options.
  reverse    — Teskari Viktorina: the answer is shown first, pick which of 4
               questions it actually matches (Jeopardy-style).
  cover      — Kitob Muqovasi: a real library book cover, blurred, pick the
               right title from 4 options. Unlike the other flavors (static
               authored question banks), its pool is built live from
               GlobalBook.cover uploads and each question carries an
               "image" URL alongside the usual q/options/correct.

All eight share the same live answer/reveal-phase timing as Ko'pchilik/Emoji;
only content prep and (for "teams") scoring differ.
"""

import io
import random
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Sum, Count, Max
from django.utils import timezone

from tgbot.models import QuizGame, QuizAnswer, QuizScore
from tgbot.services.chain_game import _add_ball_reward, charge_entry_fee, REWARD_TIERS, PARTICIPATION
from tgbot.services.game_questions import (
    QUIZ_TWOFACTS_QUESTIONS, QUIZ_IMPOSTOR_QUESTIONS, QUIZ_CONNECTION_QUESTIONS,
    QUIZ_TIMELINE_QUESTIONS, QUIZ_MATCHBOOK_QUESTIONS, QUIZ_REVERSE_QUESTIONS,
    SURVIVAL_QUESTIONS,
)

LEAD_SECONDS = 30
ANSWER_SECONDS = 20
REVEAL_SECONDS = 8
POINTS = 10
# Winning-team reward: a per-person BASE that grows with that team's own
# turnout, banded so growth tapers off for very large teams instead of
# running away, plus a rank bonus for the top-3 scorers on the team -- so
# joining a bigger team never shrinks your cut, AND outscoring your
# teammates is worth more.
TEAM_BASE_REWARD = 60
# (team-size upper bound, Kitobcha added per member within this band).
# Cumulative base at each threshold: 16->120, 30->162, 40->182, 50->202,
# 60->212, 100->252. Beyond 100 members the base stays flat at 252.
TEAM_SIZE_BANDS = [
    (16, 4),
    (30, 3),
    (40, 2),
    (50, 2),
    (60, 1),
    (100, 1),
]
TEAM_RANK_BONUS = {0: 40, 1: 25, 2: 10}  # extra Kitobcha for the team's top 3 scorers
COVER_BLUR_RADIUS = 14  # strong enough that any title text on the cover is unreadable


def _dynamic_base(team_size):
    base = TEAM_BASE_REWARD
    prev = 1
    for upper, step in TEAM_SIZE_BANDS:
        if team_size <= upper:
            return base + step * (team_size - prev)
        base += step * (upper - prev)
        prev = upper
    return base  # 100+ members: flat at the last band's cumulative value

TITLES = {
    "twofacts": "Ikki haqiqat, bir yolg'on",
    "impostor": "Kim yolg'onchi?",
    "connection": "Yashirin bog'lanish",
    "teams": "Jamoa Jangi",
    "timeline": "Vaqt Mashinasi",
    "matchbook": "Muallif-Asar Moslashtirish",
    "reverse": "Teskari Viktorina",
    "cover": "Kitob Muqovasi",
}
ENTRY_FEES = {
    "twofacts": 25, "impostor": 25, "connection": 25, "teams": 30,
    "timeline": 25, "matchbook": 25, "reverse": 25, "cover": 25,
}
NUM_QUESTIONS = {
    "twofacts": 11, "impostor": 11, "connection": 11, "teams": 11,
    "timeline": 11, "matchbook": 11, "reverse": 11, "cover": 10,
}


def _raw_pool(flavor):
    if flavor == "twofacts":
        return QUIZ_TWOFACTS_QUESTIONS
    if flavor == "connection":
        return QUIZ_CONNECTION_QUESTIONS
    if flavor == "teams":
        return SURVIVAL_QUESTIONS
    if flavor == "impostor":
        return QUIZ_IMPOSTOR_QUESTIONS
    if flavor == "timeline":
        return QUIZ_TIMELINE_QUESTIONS
    if flavor == "matchbook":
        return QUIZ_MATCHBOOK_QUESTIONS
    if flavor == "reverse":
        return QUIZ_REVERSE_QUESTIONS
    if flavor == "cover":
        return _cover_raw_pool()
    raise ValueError(f"unknown flavor {flavor}")


def _cover_raw_pool():
    """Every GlobalBook with a cover image, as raw {"book_id","title","book"}
    items -- built live from library uploads, not a static authored bank
    like every other flavor."""
    from tgbot.models import GlobalBook

    books = GlobalBook.objects.exclude(cover="").exclude(cover__isnull=True)
    return [{"book_id": b.id, "title": b.title, "book": b} for b in books]


def _blurred_cover_url(book) -> str:
    """Generate a strongly-blurred JPEG from `book.cover` and save it to
    storage, returning the full public URL. Generated fresh per question
    (not cached) -- covers rarely change and the blur is cheap."""
    import time as _time
    from PIL import Image, ImageFilter
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from django.conf import settings as _settings

    with book.cover.open("rb") as f:
        img = Image.open(f)
        img = img.convert("RGB")
        img = img.filter(ImageFilter.GaussianBlur(radius=COVER_BLUR_RADIUS))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()

    path = f"game/cover_blur/book_{book.id}_{int(_time.time() * 1000)}.jpg"
    saved_path = default_storage.save(path, ContentFile(data))
    return f"{_settings.WEB_DOMAIN}{default_storage.url(saved_path)}"


def _identity(flavor, item):
    """A stable string identifying a raw content item, for no-repeat tracking.
    "connection" items reuse the same handful of generic question texts
    ("Bu 4 asarni nima bog'laydi?" etc.) across distinct puzzles — the actual
    `items` list is what varies, so it's the identity there, not `q`."""
    if flavor == "impostor":
        return item["fake"]
    if flavor == "connection":
        return str(item.get("items"))
    if flavor == "cover":
        return item["title"]
    return item.get("q")


def _prep_one(flavor, item):
    if flavor == "impostor":
        options = list(item["real"]) + [item["fake"]]
        fake_text = item["fake"]
        random.shuffle(options)
        return {"q": "Qaysi biri SOXTA (haqiqiy emas)?", "options": options,
                "correct": options.index(fake_text)}
    if flavor == "cover":
        return _prep_cover_question(item)
    # twofacts / connection / teams are already {"q","options","correct"}-shaped.
    opts = list(item["options"])
    correct_text = opts[item["correct"]]
    random.shuffle(opts)
    out = {"q": item["q"], "options": opts, "correct": opts.index(correct_text)}
    if "items" in item:
        out["items"] = item["items"]
    return out


def _prep_cover_question(item, pool_titles=None):
    """Build one Kitob Muqovasi question: blur `item`'s cover, pick 3 decoy
    titles from the rest of the library, shuffle into options."""
    from tgbot.models import GlobalBook, normalize_uzbek_text

    book = item["book"]
    if pool_titles is None:
        pool_titles = list(GlobalBook.objects.exclude(title__exact="").values_list("title", flat=True))
    correct_norm = normalize_uzbek_text(book.title)
    decoy_pool = [t for t in pool_titles if normalize_uzbek_text(t) != correct_norm]
    decoys = random.sample(decoy_pool, min(3, len(decoy_pool)))
    options = decoys + [book.title]
    random.shuffle(options)
    return {
        "q": "Bu xira muqova qaysi kitobga tegishli?",
        "options": options,
        "correct": options.index(book.title),
        "image": _blurred_cover_url(book),
    }


def _recent_used(flavor, games_back=33):
    """Identity of each question actually used in recent games. `options[correct]`
    is the reliable identity for "impostor" since its display text is a fixed
    string ("Qaysi biri SOXTA...") — the fake statement's own text (which ends
    up at the `correct` index post-shuffle) is what actually varies. "connection"
    uses `items` for the same reason its `q` text repeats across puzzles.
    "cover" reuses the same static `q` for every question, so its identity is
    the correct title too."""
    used = set()
    for g in QuizGame.objects.filter(flavor=flavor).order_by("-starts_at")[:games_back]:
        for q in (g.questions or []):
            if flavor == "impostor" or flavor == "cover":
                used.add(q["options"][q["correct"]])
            elif flavor == "connection":
                used.add(str(q.get("items")))
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


def _finalize_teams(g) -> dict:
    scores = list(QuizScore.objects.filter(game=g).select_related("user"))
    winning_team = "a" if g.team_a_points >= g.team_b_points else "b"
    tie = g.team_a_points == g.team_b_points
    team_sizes = {"a": len(g.team_a or []), "b": len(g.team_b or [])}

    # Rank each winning side's own scorers (ties make both sides "winning",
    # each ranked separately) so the top-3 scorers get a bonus on top of the
    # size-scaled base, instead of everyone on the team earning the same cut.
    rank_by_score_id = {}
    for team in ("a", "b"):
        if not (tie or team == winning_team):
            continue
        ranked = sorted(
            (s for s in scores if s.team == team),
            key=lambda s: (-s.points, s.created_at),
        )
        for i, s in enumerate(ranked):
            rank_by_score_id[s.id] = i

    winners = []
    for s in scores:
        if not s.team:
            continue
        on_winning_side = tie or s.team == winning_team
        reward = 0
        if on_winning_side:
            base = _dynamic_base(team_sizes[s.team])
            reward = base + TEAM_RANK_BONUS.get(rank_by_score_id.get(s.id), 0)
        elif s.points > 0:
            reward = PARTICIPATION
        if reward and not s.rewarded:
            applied = _add_ball_reward(s.user, reward)
            s.rewarded = True
            s.reward = applied
            s.save(update_fields=["rewarded", "reward", "updated_at"])
        winners.append({
            "user_id": s.user_id, "telegram_id": s.user.telegram_id,
            "name": s.user.full_name or "Kitobxon", "points": s.points,
            "team": s.team, "reward": s.reward or 0,
            "boosted": bool(s.reward) and s.reward != reward,
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
        if "image" in q:
            payload["image"] = q["image"]
        ans = QuizAnswer.objects.filter(game=g, user=profile, q_index=qi).first()
        payload["answered"] = bool(ans)
        if ans:
            payload["your_choice"] = ans.choice
            payload["your_correct"] = ans.is_correct
        if phase == "reveal":
            payload["correct_index"] = q.get("correct")
    return payload
