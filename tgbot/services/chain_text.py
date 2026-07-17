"""Pure text helpers for the Kitob Zanjiri (book chain) game.

No Django imports — safe to use from data migrations and the game service.
Chaining is done on single Latin letters (a-z). Uzbek digraphs (sh, ch, ng)
and the o'/g' apostrophe letters are treated by their base letter, which keeps
matching simple and predictable for players.
"""

import re

# Unify the various apostrophe glyphs Uzbek text uses into a plain "'".
_APOS = str.maketrans({
    "‘": "'", "’": "'", "`": "'",
    "ʻ": "'", "ʼ": "'", "´": "'",
})


def normalize(text: str) -> str:
    """Lowercase, unify apostrophes, collapse whitespace. Used as the dedupe /
    lookup key so 'O‘tkan Kunlar' and \"o'tkan  kunlar\" match."""
    t = (text or "").strip().lower().translate(_APOS)
    t = re.sub(r"\s+", " ", t)
    return t


def _letters(text: str):
    return [c for c in normalize(text) if "a" <= c <= "z"]


def first_letter(text: str) -> str:
    """First Latin letter of the (normalized) text, or '' if none."""
    ls = _letters(text)
    return ls[0] if ls else ""


def last_letter(text: str) -> str:
    """Last Latin letter of the (normalized) text, or '' if none."""
    ls = _letters(text)
    return ls[-1] if ls else ""
