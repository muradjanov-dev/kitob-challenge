"""Muallif bo'lib ko'r — readers write what happens next in a book.

Phases: lobby -> writing (WRITE_SECONDS) -> voting (VOTE_SECONDS) -> done.
While writing, each reader submits (and may rewrite) one continuation of the
scene shown. While voting, every entry is shown without its author, in a
per-reader shuffled order, and each reader may heart up to VOTES_PER_READER
entries other than their own. Most hearts wins; ties go to whoever finished
writing first. A prize needs at least one heart, so a lone writer cannot win
by default -- every accepted entry still gets PARTICIPATION.

Free to enter. Settled only by the Celery tick (finalize single owner, see
chain_game.request_finalize).
"""
import random
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from tgbot.models import AuthorEntry, AuthorGame, AuthorVote
from tgbot.services.chain_game import _add_ball_reward, request_finalize

LEAD_SECONDS = 60
WRITE_SECONDS = 8 * 60
VOTE_SECONDS = 4 * 60
MIN_CHARS = 120
MAX_CHARS = 1500
VOTES_PER_READER = 3
REWARD_TIERS = [500, 300, 200]
PARTICIPATION = 50

# Scenes are retold in our own words (no quoted book text), each ending where
# the reader takes over. Keys are stable: the least-recently-used pick and
# the history read them, so append new scenes rather than renaming keys.
PROMPTS = [
    {
        "key": "kecha_kunduz",
        "book": "Kecha va kunduz", "author": "Cho'lpon",
        "scene": "Cho'lpon romanni ikki qismli qilib yozmoqchi edi: «Kecha» va «Kunduz». "
                 "Bizgacha faqat «Kecha» yetib kelgan — u begunoh Zebining sud qilinib, "
                 "uzoq surgunga jo'natilishi bilan tugaydi. «Kunduz» hech qachon o'quvchiga "
                 "yetib bormadi.",
        "task": "«Kunduz»ning birinchi sahifasini siz yozing.",
    },
    {
        "key": "otkan_kunlar",
        "book": "O'tkan kunlar", "author": "Abdulla Qodiriy",
        "scene": "Otabek va Kumushning fojiali muhabbatidan yolg'iz yodgor — o'g'illari "
                 "Yodgorbek qoldi. Yillar o'tdi, Yodgorbek ulg'aydi.",
        "task": "Yodgorbek ota-onasining hikoyasini ilk bor eshitgan kunni yozing.",
    },
    {
        "key": "kichkina_shahzoda",
        "book": "Kichkina shahzoda", "author": "Antuan de Sent-Ekzyuperi",
        "scene": "Kichkina shahzoda Yerdagi uzoq sayohatidan so'ng o'zining kichkina "
                 "sayyorasiga — yolg'iz qoldirgan guli yoniga qaytdi.",
        "task": "Ular ko'rishgan birinchi daqiqani yozing: shahzoda nima dedi, gul nima deb javob berdi?",
    },
    {
        "key": "chol_va_dengiz",
        "book": "Chol va dengiz", "author": "Ernest Xeminguey",
        "scene": "Keksa baliqchi Santyago ulkan baliqni ushladi, lekin sohilga faqat uning "
                 "skeleti yetib keldi. Bola Manolin endi chol bilan birga dengizga chiqishga "
                 "ahd qildi.",
        "task": "Ularning birga dengizga chiqqan birinchi kunini yozing.",
    },
    {
        "key": "alkimyogar",
        "book": "Alkimyogar", "author": "Paulo Koelo",
        "scene": "Cho'pon yigit Santyago xazinani topdi — u sayohatini boshlagan joyda, eski "
                 "cherkov xarobasi ostida yashiringan ekan. Endi u sahrodagi vohaga, Fotima "
                 "tomon yo'lga chiqadi.",
        "task": "Ularning qayta uchrashuvini yozing.",
    },
    {
        "key": "hayvonlar_xojaligi",
        "book": "Hayvonlar xo'jaligi", "author": "Jorj Oruell",
        "scene": "Romanning so'nggi sahnasida hayvonlar derazadan qarab, cho'chqalarni "
                 "odamlardan ajrata olmay qolishdi.",
        "task": "Ertasi tongda xo'jalikda nima bo'lganini yozing.",
    },
    {
        "key": "jamila",
        "book": "Jamila", "author": "Chingiz Aytmatov",
        "scene": "Jamila va Doniyor kuzgi kechalarning birida ovuldan birga ketishdi. "
                 "Ovul ular haqida uzoq gapirdi.",
        "task": "Oradan o'n yil o'tib, ular qayerda va qanday yashayotganini yozing.",
    },
    {
        "key": "robinzon",
        "book": "Robinzon Kruzo", "author": "Daniel Defo",
        "scene": "Robinzon kimsasiz orolda yigirma sakkiz yil yashab, nihoyat sodiq do'sti "
                 "Juma bilan birga Angliyaga qaytdi.",
        "task": "Jumaning Londondagi birinchi kunini yozing.",
    },
    {
        "key": "sakson_kun",
        "book": "80 kunda dunyo bo'ylab", "author": "Jyul Vern",
        "scene": "Fileas Fogg garovni yutdi va Audaga uylandi. Bir yildan so'ng klubda u "
                 "yana bir g'alati garov o'ynaydi.",
        "task": "Bu qanday garov edi va undan qanday sarguzasht boshlandi?",
    },
    {
        "key": "sherlok",
        "book": "Sherlok Xolms haqida hikoyalar", "author": "Artur Konan Doyl",
        "scene": "Sherlok Xolms professor Moriarti bilan sharshara tepasida olishib, "
                 "g'oyib bo'ldi. Hamma uni halok bo'ldi deb o'yladi. Oradan uch yil o'tdi.",
        "task": "Xolms do'sti doktor Uotson oldida qanday qilib qayta paydo bo'lganini yozing.",
    },
    {
        "key": "dunyoning_ishlari",
        "book": "Dunyoning ishlari", "author": "O'tkir Hoshimov",
        "scene": "Bu kitob onaga bag'ishlangan kichik hikoyalardan iborat — har biri "
                 "oddiy bir xotira, lekin yuragingizni ezib yuboradi.",
        "task": "Kitobga yangi hikoya qo'shing: onangiz bilan bog'liq bir kichik xotira.",
    },
    {
        "key": "farhod_shirin",
        "book": "Farhod va Shirin", "author": "Alisher Navoiy",
        "scene": "Dostonda Farhodga Shirin vafot etdi degan yolg'on xabar yetkaziladi va "
                 "bu uning hayotiga zomin bo'ladi.",
        "task": "Agar o'sha yolg'on xabar Farhodga yetib bormaganida nima bo'lardi? Boshqa yakunni yozing.",
    },
    {
        "key": "xunuk_ordakcha",
        "book": "Xunuk o'rdakcha", "author": "Hans Kristian Andersen",
        "scene": "Hamma masxara qilgan xunuk o'rdakcha bir bahorda go'zal oqqushga "
                 "aylandi.",
        "task": "Bir kuni u o'zi tug'ilgan qo'rg'onga qaytib boradi. U yerda nima bo'lganini yozing.",
    },
]


def _pick_prompt():
    used = [g.prompt.get("key") for g in AuthorGame.objects.order_by("-starts_at")[: len(PROMPTS) - 1]]
    fresh = [p for p in PROMPTS if p["key"] not in used]
    return dict(random.choice(fresh or PROMPTS))


def create_scheduled_author(lead_seconds: int = LEAD_SECONDS) -> AuthorGame:
    now = timezone.now()
    starts = now + timedelta(seconds=lead_seconds)
    writing_ends = starts + timedelta(seconds=WRITE_SECONDS)
    return AuthorGame.objects.create(
        status=AuthorGame.STATUS_SCHEDULED, starts_at=starts,
        writing_ends_at=writing_ends, ends_at=writing_ends + timedelta(seconds=VOTE_SECONDS),
        prompt=_pick_prompt(),
    )


def latest_game():
    return AuthorGame.objects.order_by("-starts_at").first()


def get_or_activate_live_game():
    now = timezone.now()
    g = AuthorGame.objects.filter(status=AuthorGame.STATUS_LIVE, ends_at__gte=now).order_by("-starts_at").first()
    if g:
        return g
    pending = (AuthorGame.objects
               .filter(status=AuthorGame.STATUS_SCHEDULED, starts_at__lte=now, ends_at__gte=now)
               .order_by("starts_at").first())
    if not pending:
        return None
    with transaction.atomic():
        g = AuthorGame.objects.select_for_update().get(id=pending.id)
        if g.status == AuthorGame.STATUS_SCHEDULED:
            g.status = AuthorGame.STATUS_LIVE
            g.save(update_fields=["status", "updated_at"])
    return g


def _phase(game, now):
    """(phase, seconds left in it): lobby | writing | voting | done."""
    if now < game.starts_at:
        return "lobby", int((game.starts_at - now).total_seconds()) + 1
    if now < game.writing_ends_at:
        return "writing", int((game.writing_ends_at - now).total_seconds()) + 1
    if now < game.ends_at:
        return "voting", int((game.ends_at - now).total_seconds()) + 1
    return "done", 0


def _clean(text: str) -> str:
    lines = [" ".join(line.split()) for line in (text or "").replace("\r", "").split("\n")]
    out, blank = [], False
    for line in lines:
        if not line:
            if out and not blank:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    return "\n".join(out).strip()


def submit_entry(game_id: int, profile, text: str) -> dict:
    g = AuthorGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    phase, _ = _phase(g, timezone.now())
    if phase != "writing":
        return {"ok": False, "error": "not_writing"}
    text = _clean(text)
    if len(text) < MIN_CHARS:
        return {"ok": False, "error": "too_short", "min": MIN_CHARS, "len": len(text)}
    if len(text) > MAX_CHARS:
        return {"ok": False, "error": "too_long", "max": MAX_CHARS, "len": len(text)}
    entry, created = AuthorEntry.objects.get_or_create(game=g, user=profile, defaults={"text": text})
    if not created:
        entry.text = text
        entry.save(update_fields=["text", "updated_at"])
    return {"ok": True, "updated": not created, "len": len(text)}


def toggle_vote(game_id: int, profile, entry_id: int) -> dict:
    g = AuthorGame.objects.filter(id=game_id).first()
    if not g:
        return {"ok": False, "error": "not_live"}
    phase, _ = _phase(g, timezone.now())
    if phase != "voting":
        return {"ok": False, "error": "not_voting"}
    entry = AuthorEntry.objects.filter(id=entry_id, game=g, hidden=False).first()
    if not entry:
        return {"ok": False, "error": "no_entry"}
    if entry.user_id == profile.id:
        return {"ok": False, "error": "own_entry"}

    with transaction.atomic():
        existing = AuthorVote.objects.select_for_update().filter(voter=profile, entry=entry).first()
        if existing:
            existing.delete()
            AuthorEntry.objects.filter(id=entry.id, votes__gt=0).update(votes=F("votes") - 1)
            voted = False
        else:
            if AuthorVote.objects.filter(game=g, voter=profile).count() >= VOTES_PER_READER:
                return {"ok": False, "error": "no_votes_left", "max": VOTES_PER_READER}
            try:
                with transaction.atomic():
                    AuthorVote.objects.create(game=g, voter=profile, entry=entry)
            except IntegrityError:
                return {"ok": True, "voted": True}
            AuthorEntry.objects.filter(id=entry.id).update(votes=F("votes") + 1)
            voted = True
    left = VOTES_PER_READER - AuthorVote.objects.filter(game=g, voter=profile).count()
    return {"ok": True, "voted": voted, "votes_left": left}


def _ranked(game):
    return list(
        AuthorEntry.objects.filter(game=game, hidden=False).select_related("user")
        .order_by("-votes", "updated_at", "id")
    )


def finalize(game_id: int) -> dict | None:
    with transaction.atomic():
        g = AuthorGame.objects.select_for_update().get(id=game_id)
        already = g.rewarded
        claim = []
        if g.status != AuthorGame.STATUS_FINISHED:
            g.status = AuthorGame.STATUS_FINISHED
            claim.append("status")
        if not already:
            g.rewarded = True
            claim.append("rewarded")
        if claim:
            g.save(update_fields=claim + ["updated_at"])
    if already:
        return None

    winners, place = [], 0
    for e in _ranked(g):
        if e.votes > 0 and place < len(REWARD_TIERS):
            reward, rank = REWARD_TIERS[place], place + 1
            place += 1
        else:
            reward, rank = PARTICIPATION, None
        if not e.rewarded:
            applied = _add_ball_reward(e.user, reward)
            e.rewarded = True
            e.reward = applied
            e.save(update_fields=["rewarded", "reward", "updated_at"])
        else:
            applied = e.reward or reward
        winners.append({
            "rank": rank, "user_id": e.user_id, "telegram_id": e.user.telegram_id,
            "name": e.user.full_name or "Kitobxon", "votes": e.votes,
            "reward": applied, "text": e.text, "points": e.votes,
        })
    voters = AuthorVote.objects.filter(game=g).values("voter_id").distinct().count()
    return {"winners": winners, "players": len(winners), "voters": voters, "prompt": g.prompt}


def finalize_due_games() -> list:
    now = timezone.now()
    out = []
    for g in AuthorGame.objects.filter(rewarded=False, ends_at__lt=now):
        summary = finalize(g.id)
        if summary is not None:
            out.append((g, summary))
    return out


def _history(limit=5):
    out = []
    for g in AuthorGame.objects.filter(status=AuthorGame.STATUS_FINISHED).order_by("-starts_at")[:limit]:
        top = AuthorEntry.objects.filter(game=g, hidden=False, votes__gt=0).select_related("user") \
            .order_by("-votes", "updated_at").first()
        out.append({
            "date": timezone.localtime(g.starts_at).strftime("%d.%m %H:%M"),
            "book": g.prompt.get("book", ""),
            "winner": (top.user.full_name if top else "—") or "—",
            "votes": top.votes if top else 0,
            "players": AuthorEntry.objects.filter(game=g, hidden=False).count(),
        })
    return out


def state_payload(profile) -> dict:
    now = timezone.now()
    g = get_or_activate_live_game() or latest_game()
    if not g:
        return {"ok": True, "status": "none", "history": _history()}
    phase, secs = _phase(g, now)
    if phase == "done" and not g.rewarded:
        request_finalize("muallif", g.id, g.ends_at, finalize)

    mine = AuthorEntry.objects.filter(game=g, user=profile).first()
    payload = {
        "ok": True, "game_id": g.id, "phase": phase, "seconds": secs,
        "status": {"lobby": "scheduled", "done": "finished"}.get(phase, "live"),
        "prompt": {k: g.prompt.get(k, "") for k in ("book", "author", "scene", "task")},
        "min_chars": MIN_CHARS, "max_chars": MAX_CHARS, "votes_per_reader": VOTES_PER_READER,
        "rewards": REWARD_TIERS, "participation": PARTICIPATION,
        "entries_count": AuthorEntry.objects.filter(game=g, hidden=False).count(),
        "my_text": mine.text if mine else "",
        "my_votes": mine.votes if (mine and phase == "done") else None,
        "my_reward": mine.reward if mine else 0,
    }
    if phase == "voting":
        rows = list(AuthorEntry.objects.filter(game=g, hidden=False).values("id", "text", "user_id"))
        random.Random(f"{g.id}:{profile.id}").shuffle(rows)
        mine_voted = set(AuthorVote.objects.filter(game=g, voter=profile).values_list("entry_id", flat=True))
        payload["entries"] = [{"id": r["id"], "text": r["text"], "own": r["user_id"] == profile.id,
                               "voted": r["id"] in mine_voted} for r in rows]
        payload["votes_left"] = VOTES_PER_READER - len(mine_voted)
    if phase == "done":
        payload["results"] = [
            {"name": e.user.full_name or "Kitobxon", "votes": e.votes, "reward": e.reward, "text": e.text}
            for e in _ranked(g)[:10]
        ]
        payload["history"] = _history()
    if phase == "lobby":
        payload["history"] = _history()
    return payload
