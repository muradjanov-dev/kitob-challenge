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


# Display transliteration (case-preserving, standard Uzbek Latin spelling),
# unlike _CYR above, which only builds lowercase comparison keys.
_CYR_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "'",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}
_HAS_CYR = re.compile("[Ѐ-ӿ]")
_YE_AFTER = set("аеёиоуэюяўъь")


def to_latin(text):
    """Uzbek Cyrillic -> Latin for anything a game shows or asks the player
    to type: "Ўтган кунлар" -> "O'tgan kunlar", "ШАЙТАНАТ" -> "SHAYTANAT".
    Latin text comes back unchanged -- which also strips the odd Cyrillic
    look-alike letter hidden inside a Latin word (a Cyrillic "О" in
    "RUBОIY" looks right and cannot be typed on a Latin keyboard)."""
    if not text or not isinstance(text, str) or not _HAS_CYR.search(text):
        return text
    out = []
    for i, ch in enumerate(text):
        low = ch.lower()
        lat = _CYR_LATIN.get(low)
        if lat is None:
            out.append(ch)
            continue
        if low == "е":
            prev = text[i - 1].lower() if i else ""
            if not prev.isalpha() or prev in _YE_AFTER:
                lat = "ye"
        if ch != low and lat:
            nxt = text[i + 1] if i + 1 < len(text) else ""
            prv = text[i - 1] if i else ""
            all_caps = nxt.isupper() or (not nxt.isalpha() and prv.isupper())
            lat = lat.upper() if all_caps else lat[0].upper() + lat[1:]
        out.append(lat)
    return "".join(out)


def normalize(text: str) -> str:
    """Lowercase, unify apostrophes, transliterate Uzbek Cyrillic to Latin, and
    collapse whitespace. Used as the dedupe / lookup key so 'O‘tkan Kunlar',
    \"o'tkan  kunlar\" and 'Ўткан кунлар' all line up."""
    t = (text or "").strip().lower().translate(_APOS)
    t = _translit(t)
    t = re.sub(r"\s+", " ", t)
    return t


# Latin letters with diacritics that turn up in imported titles/answers
# ("BOYBÖRI", Turkish spellings). Folded to what a player would actually type.
_DIACRITICS = str.maketrans({
    "ö": "o", "ü": "u", "ı": "i", "ə": "a", "ğ": "g", "ş": "sh", "ç": "ch",
    "â": "a", "î": "i", "û": "u", "é": "e", "è": "e", "ñ": "n",
})


def answer_key(text: str) -> str:
    """Comparison key for typed answers: normalize(), drop "(...)" notes, fold
    diacritics, then keep only a-z/0-9. So "O‘tkan kunlar", "otkan  kunlar!",
    "Cho'lpon" vs "cholpon" and "Oybek (Muso Toshmuhammad o'g'li)" vs "oybek"
    all compare equal. Apostrophes go too -- players type o'/g' every which
    way (or not at all), and no two answers differ only by one."""
    t = re.sub(r"\([^)]*\)", " ", text or "")
    t = normalize(t).translate(_DIACRITICS)
    return re.sub(r"[^0-9a-z]", "", t)


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, giving up (returning limit+1) once it exceeds `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def typo_allowance(key: str) -> int:
    """How many typos a key of this length forgives: none for short words
    (where one letter IS the answer), one up to 7 letters, two beyond."""
    n = len(key)
    if n <= 3:
        return 0
    return 1 if n <= 7 else 2


def keys_match(typed: str, target: str) -> bool:
    """True if two answer_key()s are the same answer, allowing for typos."""
    if not typed or not target:
        return False
    if typed == target:
        return True
    allow = typo_allowance(target)
    return bool(allow) and _edit_distance(typed, target, allow) <= allow


def match_text_answer(text: str, options, correct: int, allow_names: bool = False) -> int:
    """Map a typed answer onto an option index; -1 if it matches nothing.

    Exact key match against any option wins first (typing a distractor is a
    wrong answer, not a typo of the right one). Then the correct option is
    accepted within typo_allowance(), unless the typed text is at least as
    close to some other option. With `allow_names`, a distinctive word of the
    correct answer alone is enough ("Qodiriy" for "Abdulla Qodiriy", "Attor"
    for "Navoiy / Attor") -- used where the answer is a person's full name."""
    typed = answer_key(text)
    if not typed or not options or not (0 <= correct < len(options)):
        return -1
    keys = [answer_key(str(o)) for o in options]
    if typed == keys[correct]:
        return correct
    for i, k in enumerate(keys):
        if typed == k:
            return i

    def dist(k):
        allow = typo_allowance(k)
        return _edit_distance(typed, k, allow) if allow else (0 if typed == k else 99)

    d_correct = dist(keys[correct])
    if d_correct <= typo_allowance(keys[correct]):
        others = [dist(k) for i, k in enumerate(keys) if i != correct]
        if not others or d_correct < min(others):
            return correct

    if allow_names:
        other_words = set()
        for i, o in enumerate(options):
            if i != correct:
                other_words.update(answer_key(w) for w in re.split(r"[\s/,\-]+", str(o)))
        raw = re.sub(r"\([^)]*\)", " ", str(options[correct]))
        for w in re.split(r"[\s/,\-]+", raw):
            wk = answer_key(w)
            if len(wk) >= 4 and wk not in other_words and keys_match(typed, wk):
                return correct
    return -1


def matches_any(text: str, accepted) -> bool:
    """True if `text` is (a typo of) any of the `accepted` answers."""
    typed = answer_key(text)
    return any(keys_match(typed, answer_key(a)) for a in (accepted or []) if a)


_MASK_KEEP = set(" -'‘’`ʻʼ´.,:;!?«»\"")


def letter_mask(answer: str, reveal_ratio: float = 0.0, rng=None,
                reveal_first: bool = True) -> str:
    """Letter-slot hint for a typed answer: "O ' _ _ _ _   K _ _ _ _ _".

    Shows how many letters each word has, keeps spaces/apostrophes/hyphens,
    reveals each word's first letter (unless `reveal_first` is False) plus
    roughly `reveal_ratio` of the rest, picked with `rng` so a stored game
    shows every poller the same mask."""
    import random as _random
    rng = rng or _random
    raw = re.sub(r"\s*\([^)]*\)", "", answer or "").strip()
    chars = list(raw.upper())
    slots = [i for i, c in enumerate(chars) if c not in _MASK_KEEP]
    shown = set()
    if reveal_first:
        start = True
        for i, c in enumerate(chars):
            if c in _MASK_KEEP:
                start = c == " " or c == "-" or start
                continue
            if start:
                shown.add(i)
            start = False
    rest = [i for i in slots if i not in shown]
    k = int(round(len(rest) * max(0.0, min(1.0, reveal_ratio))))
    if len(rest) - k < 1 and rest:
        k = len(rest) - 1  # always leave at least one letter to find
    shown.update(rng.sample(rest, k) if k > 0 else [])
    out = []
    for i, c in enumerate(chars):
        if c == " ":
            out.append(" ")
        elif c in _MASK_KEEP or i in shown:
            out.append(c)
        else:
            out.append("_")
    # One space between slots, three between words, so blanks stay countable.
    return "   ".join(" ".join(word) for word in "".join(out).split(" ") if word)


def scramble_letters(answer: str, rng=None) -> str:
    """Anagram display built from the answer itself, word by word, keeping the
    o'/g' digraphs whole: "O'tkan kunlar" -> "N K O' A T / L K U R A N".
    The stored anagram strings did not always spell the answer (15 of 109)."""
    import random as _random
    rng = rng or _random
    words = []
    for word in re.sub(r"\s*\([^)]*\)", "", answer or "").upper().split():
        units = re.findall(r"[^\W\d_]['‘’`ʻʼ]?|\d", word)
        if len(units) > 1:
            original = list(units)
            for _ in range(6):
                rng.shuffle(units)
                if units != original:
                    break
        words.append(" ".join(units))
    return "  /  ".join(w for w in words if w)


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
