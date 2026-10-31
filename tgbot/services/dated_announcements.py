"""Owner-approved announcements, sent once on their date to the groups and to
every registered user (tasks.send_dated_announcement, hourly).

Every outgoing text is approved by the owner before it is added here, so the
texts are fixed, not generated. An entry is either one text, sent at 11:00, or
{hour: part} for a day explained in parts through the day. A part is a text or
(text, start_arg): start_arg adds a button that opens the bot with
/start <start_arg>. Past dates are never sent again.
"""
import datetime as _dt

_HAMYON = "hamyon"

ANNOUNCEMENTS = {
    # 2026-10-26: the small-changes announcement was sent by hand right after
    # midnight instead (owner's request, a shorter colloquial text, through
    # internal/ops/broadcast campaign changes_2026_10_26), so the 11:00 entry
    # was removed to avoid sending it twice.

    # Wallet launch: told in parts, warmly and always with "Siz" (owner,
    # 2026-11-01). Part 1 went out by hand at 04:20 ("Assalomu alaykum",
    # internal/ops/broadcast campaign wallet_launch_2026_11_01) instead of
    # the 08:00 entry, which was removed so it is not sent twice.
    _dt.date(2026, 11, 1): {
        12: ((
            "📚 <b>Hisobot endi qanday ishlaydi?</b> (2/4)\n\n"
            "Juda oddiy, azizlarim:\n"
            "1️⃣ Bir kunlik hisobot — <b>1 000 so'm</b>. Kuniga faqat bir marta, "
            "birinchi hisobotingizda yechiladi.\n"
            "2️⃣ Uning <b>300 so'migacha</b> qismini Kitobchangiz o'zi to'laydi 🪙 "
            "Kitobchangiz bo'lsa, hamyondan atigi 700 so'm ketadi.\n"
            "3️⃣ Hamyonda mablag' yetmasa, bot hisobotni qabul qilmaydi va "
            "darhol to'ldirish tugmasini ko'rsatadi.\n\n"
            "Kuniga bir piyola choydan ham arzon ☕️, evaziga esa har kungi mutolaa odati 💛"
        ), _HAMYON),
        15: ((
            "💳 <b>Hamyonni qanday to'ldiraman?</b> (3/4)\n\n"
            "1️⃣ Botda <b>👛 Hamyon</b> tugmasini bosing (yoki /hamyon deb yozing).\n"
            "2️⃣ Summani tanlang: 1 000, 2 000, 5 000, 10 000, 30 000 so'm "
            "yoki «✍️ Boshqa miqdor».\n"
            "3️⃣ Ko'rsatilgan kartaga o'tkazing va chek rasmini botga yuboring.\n"
            "4️⃣ Admin tasdiqlashi bilan pul hamyoningizga tushadi ✅\n\n"
            "30 000 so'm butun bir oyga yetadi: bir marta to'ldirasiz, "
            "keyin bemalol o'qiyverasiz 📖"
        ), _HAMYON),
        18: ((
            "💎 <b>Imtiyozlar qayerga ketdi?</b> (4/4)\n\n"
            "Hech qayerga, ular endi hamyonda 😊\n"
            "1️⃣ Hamyonida <b>15 000 so'm</b> va undan ko'p bo'lganlarga sobiq Premium'ning "
            "hamma imtiyozlari: 2× Kitobcha, VIP arena, kuniga bir necha hisobot.\n"
            "2️⃣ Premium muddatingiz hali tugamagan bo'lsa, qolgan har bir kuningiz uchun "
            "hamyoningizga <b>1 000 so'm</b> qo'shildi. Premium imtiyozlari esa "
            "muddati tugaguncha saqlanadi 🤝\n"
            "3️⃣ Do'stingizni taklif qiling: u birinchi hisobotini yuborganda sizga "
            "<b>500 Kitobcha</b> 🎁\n\n"
            "Har bir o'qilgan bet — o'zingizga qilgan sarmoya. Bugungi hisobotni "
            "yuborishni unutmang, azizlarim 💛"
        ), _HAMYON),
    },
}


def announcement_for(date, hour=11):
    """(text, start_arg or None) due at `hour` on `date`, or None."""
    entry = ANNOUNCEMENTS.get(date)
    if isinstance(entry, dict):
        entry = entry.get(hour)
    elif hour != 11:
        entry = None
    if not entry:
        return None
    return entry if isinstance(entry, tuple) else (entry, None)
