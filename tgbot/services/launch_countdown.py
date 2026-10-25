"""Countdown to the 1 November launch, posted once a day to the groups.

The texts are fixed and were approved by the owner on 2026-10-25 -- every
outgoing text is approved first, so nothing here is generated. One post per
date; dates outside the table post nothing, so the beat entry can stay in
place after the launch without side effects.
"""
import datetime as _dt

LAUNCH_DATE = _dt.date(2026, 11, 1)

TEXTS = {
    _dt.date(2026, 10, 26): (
        "🤫 <b>Diqqat, kitobxonlar!</b>\n\n"
        "Kitob Challenge'da <b>siz kutmagan darajada katta yangilik</b> tayyorlanmoqda — "
        "loyiha tarixida bunaqasi bo'lmagan.\n\n"
        "Hozircha sir. Faqat shuni aytamiz: bu har bir kitobxonga bevosita tegishli 🎁\n\n"
        "⏳ <b>Ochilishiga 6 kun qoldi</b> — 1-noyabr.\n\n"
        "Kuzatib boring 👀"
    ),
    _dt.date(2026, 10, 27): (
        "⏳ <b>5 kun qoldi!</b>\n\n"
        "Sanoq davom etmoqda. Birinchi ishora 🔑: "
        "<b>mutolaangiz endi butunlay yangi qiymatga ega bo'ladi</b> 📚✨\n\n"
        "1-noyabrda hammasi ochiladi."
    ),
    _dt.date(2026, 10, 28): (
        "⏳ <b>4 kun qoldi!</b>\n\n"
        "Ikkinchi ishora 🔑: yangilik bilan birga "
        "<b>har bir kitobxonni katta sovg'a kutmoqda</b> — hech kim chetda qolmaydi, "
        "faqat botdan chiqib ketmang 😉"
    ),
    _dt.date(2026, 10, 29): (
        "⏳ <b>3 kun qoldi!</b>\n\n"
        "Uchinchi ishora 🔑: kitob o'qish "
        "<b>shunchaki odat emas, o'zingizga bergan haqiqiy va'daga</b> aylanadi 💪📖\n\n"
        "Tayyormisiz?"
    ),
    _dt.date(2026, 10, 30): (
        "⏳ <b>2 kun qoldi!</b>\n\n"
        "Oxirgi sinovlar ketmoqda ⚙️\n"
        "Ishora: shaxsiy kabinetingizda <b>yangi bo'lim</b> paydo bo'ladi. "
        "Unda nima bo'ladi deb o'ylaysiz? 🤔\n\n"
        "Taxminlaringizni guruhda yozing!"
    ),
    _dt.date(2026, 10, 31): (
        "🔥 <b>Ertaga!</b>\n\n"
        "1-noyabr kuni Kitob Challenge'da <b>siz kutmagan darajada katta yangilik</b> "
        "ishga tushadi va barcha kitobxonlarga <b>katta bonus</b> beriladi 🎁\n\n"
        "Ochilish lahzasini o'tkazib yubormang! 🔔"
    ),
}


def countdown_text_for(date):
    return TEXTS.get(date)
