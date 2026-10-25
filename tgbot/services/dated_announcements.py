"""Owner-approved announcements, each sent once on its date at 11:00 to the
groups and to every registered user (tasks.send_dated_announcement).

Every outgoing text is approved by the owner before it is added here, so the
texts are fixed, not generated. Add an entry under a new date to schedule the
next one; past dates are never sent again.
"""
import datetime as _dt

ANNOUNCEMENTS = {
    # Approved 2026-10-25 (extended the same night): the small changes of the
    # past weeks, apart from the 1 November paid system, which has its own
    # countdown.
    _dt.date(2026, 10, 26): (
        "🛠 <b>Kitob Challenge'da yangilanishlar</b>\n\n"
        "So'nggi kunlarda kiritilgan o'zgarishlar:\n\n"
        "🕤 <b>Kechki o'yinlar endi 21:30 da</b> boshlanadi (avval 22:00 edi). "
        "Ertalabki o'yinlar — odatdagidek 10:00 da.\n"
        "😄 <b>Kunning latifasi</b> — har kuni soat 17:00 da guruhlarda kitobxonlar "
        "haqida bitta latifa.\n"
        "🔥 <b>Streaklar tiklandi</b> — server ko'chirilgan kunlarda (18–19-sentyabr) "
        "uzilib qolgan 48 kitobxonning streaki qayta ulandi.\n"
        "🎨 <b>Do'kondagi mavzular tuzatildi</b> — sotib olingan mavzu endi barcha "
        "sahifalarda to'g'ri ko'rinadi, bir mavzuni ikki marta sotib olib qo'yish ham "
        "mumkin emas. Ilgari mavzu sotib olganlarga noqulaylik uchun Kitobcha to'liq "
        "qaytarildi.\n"
        "🔤 O'yinlarda kitob nomlari endi faqat <b>lotin yozuvida</b> ko'rsatiladi va "
        "shunday qabul qilinadi.\n"
        "🤖 <b>AI test tuzish</b> — Premium'siz ham ochiq: 3 000 Kitobcha. Test "
        "yaratilmasa, Kitobcha avtomatik qaytariladi.\n"
        "🎉 <b>Tabriklash tugmasi</b> — har bir reytingni endi bir marta tabriklaysiz, "
        "do'stlaringizga takroriy xabarlar bormaydi.\n"
        "📖 <b>Kutubxonada varaqlash</b> yumshoqroq bo'ldi — sahifa qog'ozdek bukiladi "
        "va barmog'ingizga ergashadi.\n\n"
        "⏳ Eng muhimi esa oldinda — <b>1-noyabrda katta yangilik!</b> Kuzatib boring.\n\n"
        "Taklif va kamchiliklarni botdagi «📞 Admin bilan bog'lanish» orqali yuboring — "
        "har biriga e'tibor beramiz 🙌"
    ),
}


def announcement_for(date):
    return ANNOUNCEMENTS.get(date)
