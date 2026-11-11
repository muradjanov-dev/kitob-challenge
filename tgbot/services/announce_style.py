"""House style for the group announcements (owner, 2026-11-11: "quote bilan
chiroyli copywriting qoidalariga asoslanib yozgin, o'qiganlar mazza qilsin
estetikadan").

One idea per post: a headline, a short quote in a <blockquote>, the news
itself in a few clean lines, one warm call to action. Every quote below is a
proverb or a line whose author is certain -- a wrong attribution in a reading
community is worse than no quote at all.
"""
from html import escape

QUOTES = {
    "reading": [
        ("Kitobxon o'limidan oldin ming bir hayot yashaydi. Kitob o'qimagan odam esa — faqat bittasini.",
         "Jorj R. R. Martin"),
        ("Kitobni seving — u bilim manbai.", "Maksim Gorkiy"),
        ("Bilim — tuganmas xazina.", "xalq maqoli"),
        ("Ilm olish — igna bilan quduq qazish.", "xalq maqoli"),
        ("Takrorlash — ilmning onasi.", "lotin hikmati"),
        ("Kitob — eng sodiq do'st.", "xalq hikmati"),
    ],
    "steady": [
        ("Tomchi-tomchi ko'l bo'lur.", "xalq maqoli"),
        ("Sabr tagi — sariq oltin.", "xalq maqoli"),
        ("Oz-oz o'rganib dono bo'lur, qatra-qatra yig'ilib daryo bo'lur.", "xalq maqoli"),
        ("Ko'p yashagan bilmas, ko'p o'qigan bilar.", "xalq maqoli"),
    ],
    "gift": [
        ("Harakatda — barakat.", "xalq maqoli"),
        ("Mehnatning tagi — rohat.", "xalq maqoli"),
        ("Izlagan — topar.", "xalq maqoli"),
    ],
}


def quote(kind: str, day=None) -> tuple:
    """The (text, author) for `kind`, turning over day by day."""
    pool = QUOTES.get(kind) or QUOTES["reading"]
    n = day.toordinal() if day else 0
    return pool[n % len(pool)]


def quote_block(kind: str, day=None) -> str:
    text, author = quote(kind, day)
    return f"<blockquote><i>«{escape(text, quote=False)}»</i>\n— {escape(author, quote=False)}</blockquote>"


def name(s) -> str:
    """A reader's name, safe for HTML, first 32 characters."""
    return escape((s or "Kitobxon").strip()[:32] or "Kitobxon", quote=False)
