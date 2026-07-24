"""Pure text helpers for the Kitob Zanjiri (missing-letter) game.

No Django imports — safe to use from data migrations and the game service.
`normalize`/`is_guessable_letter` are used by the current mechanic (guessing
blanked-out letters in a real book title); `first_letter`/`last_letter` are
leftovers from the earlier free-text chain mechanic, unused today but kept
since ChainWordAdmin (admin.py) still calls them for the legacy dictionary.
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


# Apostrophe glyphs unified above, plus the plain apostrophe itself — any of
# these are typeable as "'" and match via normalize().
_GUESSABLE_APOS = set("'‘’`ʻʼ´")


def is_guessable_letter(c: str) -> bool:
    """True if `c` is a character a player could plausibly type on an
    ordinary keyboard: plain ASCII letters, Cyrillic (typeable in Cyrillic or
    its Latin transliteration — both match via normalize()), or one of the
    apostrophe glyphs used for Uzbek's o'/g' digraphs.

    Excludes diacritic Latin letters (ö, ü, ş, ə, ĝ, ģ, ...) that occasionally
    show up in imported book titles (Turkish titles, or data-entry mistakes
    substituting a single accented letter for Uzbek's "g'"/"o'" digraphs).
    Those can't be reproduced by a player who can only see a blank — masking
    one would make the round unsolvable."""
    if not c:
        return False
    if c in _GUESSABLE_APOS:
        return True
    lc = c.lower()
    if "a" <= lc <= "z":
        return True
    return lc in _CYR
