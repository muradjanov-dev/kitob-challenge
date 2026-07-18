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

# Uzbek Cyrillic → Latin, so a book typed in either script chains by the same
# letters (many users type in Cyrillic — "Ўтган кунлар" must match letter "o").
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h", "ҷ": "j", "ъ".upper(): "'",
}


def _translit(t: str) -> str:
    return "".join(_CYR.get(c, c) for c in t)


def normalize(text: str) -> str:
    """Lowercase, unify apostrophes, transliterate Uzbek Cyrillic to Latin, and
    collapse whitespace. Used as the dedupe / lookup key so 'O‘tkan Kunlar',
    \"o'tkan  kunlar\" and 'Ўткан кунлар' all line up."""
    t = (text or "").strip().lower().translate(_APOS)
    t = _translit(t)
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
