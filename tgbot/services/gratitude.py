"""Personal thank-you letters from Kitob Challenge (owner, 2026-11-11).

Every reader gets a letter written for them alone, from what they actually
did here: their conclusions (a short phrase quoted back), the books, their
pages, streaks and days with the project. Warm, in the "Siz" form, with a
pinch of kind irony to wake up ambition -- never a jab -- thanking them for
standing among awakened readers on the way to knowing themselves. A reader
with no report yet gets a gentle, smiling invitation instead.

The model is reached through services.llm (OpenAI, Google Gemini as the
fallback); if both fail, a short template letter is used so nobody is
skipped. Sending: tasks.send_gratitude_letters, a few readers per Celery run,
re-queued until done, each reader once per CAMPAIGN (cache marker).
"""
import re
from html import escape

from django.db.models import Sum
from django.utils import timezone

CAMPAIGN = "2026-11"

SYSTEM = (
    "Sen «Kitob Challenge» kitobxonlar loyihasi nomidan bitta kitobxonga shaxsiy tashakkur maktubi yozasan. "
    "Qoidalar:\n"
    "- Faqat o'zbek tilida, lotin yozuvida yoz. Kitobxonga doim «Siz» deb murojaat qil (Siz, Sizning — bosh harf bilan).\n"
    "- 80–120 so'z, 2 ta xatboshi. Ohang: iliq, samimiy, ruhlantiruvchi; bitta joyda yengil, mehribon kinoya "
    "yoki hazil bo'lsin — himmatini qo'zg'atadigan, lekin hech qachon kamsitmaydigan, uyaltirmaydigan.\n"
    "- Maktub aynan shu insonga xos bo'lsin: berilgan ma'lumotdan aniq tafsilotlarni ishlat — kitob nomlari, "
    "betlar, ketma-ketlik kunlari; agar xulosalari berilgan bo'lsa, ulardan bitta qisqa iborani «...» ichida "
    "keltirib, unga munosabat bildir.\n"
    "- Uyg'oq kitobxonlar safida ekani va O'zligini anglash yo'lida ekani uchun Kitob Challenge nomidan "
    "tashakkur ayt — bu iboralarni qo'shtirnoqsiz, jumla ichida tabiiy ishlat.\n"
    "- Ketma-ketlik 0 bo'lsa, raqamni aytma — yo'lni qayta davom ettirishga iliq chaqir.\n"
    "- Hisoboti bo'lmasa: kitob javonda uni sabr bilan kutayotgani haqida yengil hazil qil va bugun birinchi "
    "sahifadan boshlashga iliq taklif qil.\n"
    "- Ma'lumotda yo'q narsani to'qima. Raqamlarni o'zgartirma.\n"
    "- Formatlash: oddiy matn. Faqat <b> va <i> teglari mumkin; boshqa teg, markdown, sarlavha yozma.\n"
    "- Salomlashish («Assalomu alaykum», «Hurmatli ...») va imzo («Hurmat bilan», «... jamoasi») yozma — "
    "murojaat va imzoni tizim o'zi qo'shadi. Birinchi gapdanoq mazmunga o't."
)


def _first(name) -> str:
    return ((name or "").split() or ["Kitobxon"])[0]


def reader_facts(p) -> dict:
    from tgbot.models import ConfirmationReport
    from tgbot.services import ops_fixes
    from tgbot.services.book_quiz import _clean_conclusion, _is_meaningful
    reps = ConfirmationReport.objects.filter(user=p)
    total = reps.count()
    pages = int(reps.filter(is_audio=False).aggregate(s=Sum("pages_read"))["s"] or 0)
    books = []
    for b in reps.exclude(book__isnull=True).exclude(book="").order_by("-date").values_list("book", flat=True)[:30]:
        if b not in books:
            books.append(b)
    quotes = []
    for c in reps.exclude(conclusion__isnull=True).exclude(conclusion="").order_by("-date").values_list("conclusion", flat=True)[:12]:
        c = _clean_conclusion(c)
        if _is_meaningful(c) and len(c) >= 40 and c[:280] not in quotes:
            quotes.append(c[:280])
        if len(quotes) >= 3:
            break
    joined = timezone.localtime(p.created_at).date() if getattr(p, "created_at", None) else None
    days_with_us = (timezone.localdate() - joined).days if joined else None
    report_days = reps.dates("date", "day").count() if total else 0
    return {
        "name": _first(p.full_name), "reports": total, "report_days": report_days, "pages": pages,
        "books": books[:5], "conclusions": quotes, "streak_now": ops_fixes.current_streak(p.id) if total else 0,
        "days_with_us": days_with_us, "kitobcha": int(p.ball or 0),
    }


def _facts_text(f) -> str:
    lines = [f"Ismi: {f['name']}",
             f"Loyihada: {f['days_with_us']} kundan beri" if f["days_with_us"] is not None else "",
             f"Hisobotlar: {f['reports']} ta ({f['report_days']} kun)",
             f"O'qigan betlari: {f['pages']}",
             # A zero is left out: told to the model, it gets said to the reader.
             f"Hozirgi ketma-ketlik: {f['streak_now']} kun" if f["streak_now"] else "",
             "Kitoblari: " + ("; ".join(f["books"]) if f["books"] else "—")]
    if f["conclusions"]:
        lines.append("Xulosalaridan:")
        lines += [f"- {c}" for c in f["conclusions"]]
    return "\n".join(l for l in lines if l)


_ALLOWED = re.compile(r"&lt;(/?)(b|i)&gt;")


_SIGN_OFF = re.compile(r"^\s*(hurmat bilan|chuqur hurmat bilan|samimiy hurmat bilan|«?kitob challenge»? jamoasi)",
                       re.IGNORECASE)
_GREETING = re.compile(r"^\s*(assalomu alaykum|hurmatli|aziz|qadrli)\b[^\n]{0,60}[!,.]?\s*$", re.IGNORECASE)


def _strip_frame(text: str) -> str:
    """The letter has its own address line and signature: drop the model's."""
    lines = [l for l in (text or "").strip().split("\n")]
    while lines and (not lines[0].strip() or _GREETING.match(lines[0])):
        lines.pop(0)
    while lines and (not lines[-1].strip() or _SIGN_OFF.match(lines[-1])):
        lines.pop()
    return "\n".join(lines).strip()


_SIZ = re.compile(r"(?<![\w'’ʻʼ])siz(?=[a-zʻʼ'’]*\b)")


def _clean_html(text: str) -> str:
    """Escape everything, then let <b>/<i> back in; drop markdown stars;
    the reader is always "Siz" with a capital (owner's rule)."""
    text = _strip_frame(text)
    text = _SIZ.sub("Siz", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "").replace("*", "")
    text = escape(text.strip(), quote=False)
    text = _ALLOWED.sub(r"<\1\2>", text)
    # an unbalanced tag would make Telegram reject the whole message
    for t in ("b", "i"):
        if text.count(f"<{t}>") != text.count(f"</{t}>"):
            text = text.replace(f"<{t}>", "").replace(f"</{t}>", "")
    return text


def _fallback(f) -> str:
    if f["reports"]:
        return (f"Siz bilan birga o'tgan har bir sahifa — {f['pages']} bet, {f['reports']} ta hisobot — "
                "Kitob Challenge uchun katta quvonch. Uyg'oq kitobxonlar safida bo'lganingiz va O'zligingizni "
                "anglash yo'lidan qaytmayotganingiz uchun chin dildan rahmat! Kitoblaringiz Sizni hali ko'p "
                "ajablantiradi — biz esa shu yo'lda doim yoningizdamiz.")
    return ("Kitob javonda Sizni sabr bilan kutib turibdi — u hali ham Sizga ishonadi! Kitob Challenge safiga "
            "qo'shilganingiz uchun rahmat. Uyg'oq kitobxonlar orasida o'z joyingiz bor: bugun bir necha sahifadan "
            "boshlang — O'zligingizni anglash yo'li aynan shunday boshlanadi.")


class RateLimited(Exception):
    """Every model refused for quota / rate: wait and retry, no template."""


def letter_for(p) -> tuple:
    """(message HTML, source) -- source is the model's name or "template".
    Raises RateLimited when the models are out of quota for now."""
    from tgbot.services import llm
    f = reader_facts(p)
    try:
        body, src = llm.complete([{"role": "system", "content": SYSTEM},
                                  {"role": "user", "content": _facts_text(f)}], max_tokens=1500, timeout=90)
        body = _clean_html(body)
        if len(body) < 120:
            raise ValueError("too short")
    except Exception as e:
        msg = str(e)
        print(f"gratitude letter {p.id}: {msg[:200]}")
        low = msg.lower()
        if "429" in msg or "quota" in low or "rate limit" in low or "resource_exhausted" in low:
            try:
                from django.core.cache import cache
                cache.set(f"gratitude_last_error:{CAMPAIGN}", msg[:300], 60 * 60 * 24)
            except Exception:
                pass
            raise RateLimited(msg[:200])
        body, src = _fallback(f), "template"
    text = (f"💌 <b>{escape(f['name'], quote=False)}, Kitob Challenge'dan Sizga maktub</b>\n\n"
            f"{body}\n\n— <i>Kitob Challenge jamoasi</i> 📚")
    return text[:4000], src


def sent_key(user_id) -> str:
    return f"gratitude_sent:{CAMPAIGN}:{user_id}"


def pending_ids() -> list:
    from django.core.cache import cache
    from tgbot.models import TelegramProfile
    ids = list(TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
               .order_by("id").values_list("id", flat=True))
    sent = cache.get_many([sent_key(i) for i in ids])
    return [i for i in ids if sent_key(i) not in sent]
