"""Kunning kitob savoli -- one question about books a day in the groups
(owner, 2026-11-11: "kunlik guruhga kitoblardan savollar yuborib tur 1 kunda
1 ta").

Posted as a native Telegram quiz poll: anyone in the group answers with one
tap, Telegram itself shows who was right and the explanation, and nothing has
to be stored here. The question comes from the live-game banks that are about
books and authors; the day picks it from one fixed shuffle of the pool, so a
question comes back only after the whole pool has been used.
"""
import datetime
import random
import re

# Telegram sendPoll limits.
MAX_QUESTION = 300
MAX_OPTION = 100

_TAG = re.compile(r"^\s*\[[^\]]{1,40}\]\s*")


def _plain(item):
    q = _TAG.sub("", str(item.get("q") or "")).strip()
    opts = [str(o).strip() for o in item.get("options") or []]
    c = item.get("correct")
    if not q or len(opts) < 2 or not isinstance(c, int) or not 0 <= c < len(opts):
        return None
    return {"q": q, "options": opts, "correct": c, "explanation": ""}


def _from_character(item):
    who, book = item.get("character"), item.get("book")
    opts = [who] + list(item.get("distractors") or [])
    if not who or len(opts) < 2:
        return None
    return {"q": f"Bu qaysi qahramon?\n\n{item.get('desc', '').strip()}", "options": opts, "correct": 0,
            "explanation": f"{who} — «{book}» asaridan." if book else ""}


def _from_dialogue(item):
    who = item.get("speaker")
    opts = [who] + list(item.get("distractors") or [])
    if not who or not item.get("quote") or len(opts) < 2:
        return None
    ctx = (item.get("context") or "").strip()
    return {"q": f"Bu so'zlar kimga tegishli?\n\n{item['quote'].strip()}", "options": opts, "correct": 0,
            "explanation": f"{who}" + (f" — {ctx}" if ctx else "")}


def _fits(q) -> bool:
    return (len(q["q"]) <= MAX_QUESTION and 2 <= len(q["options"]) <= 10
            and all(0 < len(o) <= MAX_OPTION for o in q["options"])
            and len(set(q["options"])) == len(q["options"]))


def pool() -> list:
    from tgbot.services import questions as Q
    out, seen = [], set()
    sources = [(Q.QUIZ_MATCHBOOK_QUESTIONS, _plain), (Q.QUIZ_WORLDLIT_QUESTIONS, _plain),
               (Q.QUIZ_GENRES_QUESTIONS, _plain), (Q.QUIZ_ENDING_QUESTIONS, _plain),
               (Q.QUIZ_PLOTMAP_QUESTIONS, _plain), (Q.QUIZ_NUMBERS_QUESTIONS, _plain),
               (Q.QUIZ_SCHOLARS_QUESTIONS, _plain), (Q.CHARACTER_QUESTIONS, _from_character),
               (Q.DIALOGUE_QUESTIONS, _from_dialogue)]
    for bank, conv in sources:
        for item in bank:
            q = conv(item) if isinstance(item, dict) else None
            if not q or not _fits(q) or q["q"].lower() in seen:
                continue
            seen.add(q["q"].lower())
            out.append(q)
    # One fixed order for the whole pool: day N takes item N mod len.
    random.Random(20261111).shuffle(out)
    return out


def question_for(day: datetime.date):
    """The day's question with its options shuffled (the banks mostly keep the
    right answer first)."""
    items = pool()
    if not items:
        return None
    q = dict(items[day.toordinal() % len(items)])
    order = list(range(len(q["options"])))
    random.Random(day.toordinal()).shuffle(order)
    q["options"] = [q["options"][i] for i in order]
    q["correct"] = order.index(q["correct"])
    return q


HEADER = "📚 Kunning kitob savoli\n\n"


def poll_question(q) -> str:
    """The poll's question line: the header when it still fits Telegram's
    300 characters (a poll question is plain text, no HTML)."""
    text = HEADER + q["q"]
    return text if len(text) <= MAX_QUESTION else q["q"]
