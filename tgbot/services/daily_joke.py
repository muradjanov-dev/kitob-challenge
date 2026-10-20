"""Kunning latifasi: one reader-themed joke a day for the groups.

The jokes are a fixed, owner-approved list (every text that goes out to the
groups is approved first), not generated on the fly. The one for a given day
is picked by its date, so a retried or doubled beat run posts the same joke,
and the list simply starts over after the last one.
"""

HEADER = "😄 <b>Kitobxon latifasi</b> #{n}"

JOKES = [
    # 1
    "Kitobxon soatsozga kelibdi:\n"
    "— Usta, soatim juda tez yuryapti. Kechqurun 21:00 da kitob ochib, bitta bob "
    "o'qiyman — qarasam, 03:40!\n"
    "Usta soatni uzoq tekshirib, qaytarib beribdi:\n"
    "— Soatingiz joyida. Nosozlik — kitobda.",
    # 2
    "Dunyodagi eng ko'p aytiladigan yolg'onlar reytingi:\n\n"
    "🥉 «Uyimda o'qilmagan kitob yo'q»\n"
    "🥈 «Bu kitobni ertaga albatta qaytaraman»\n"
    "🥇 «Faqat bitta bob o'qiyman-da, keyin uxlayman»",
    # 3
    "Xatcho'p qo'shnisiga nolibdi:\n"
    "— Egam meni 47-betga qo'yib ketgan. O'shandan beri ikki yil o'tdi...\n"
    "— Shukr qil, — debdi yonidagi 50 ming so'mlik pul. — Meni ham xatcho'p qilib "
    "qo'yishgandi, keyin kitobni kutubxonaga topshirib yuborishdi. Uch yildan beri "
    "«Urush va tinchlik»ning 812-betida yashayapman.",
    # 4
    "Kitobxon nihoyat «Urush va tinchlik»ni o'qib tugatibdi.\n"
    "— Xo'sh, qanday ekan? — deb so'rabdi do'sti.\n"
    "— Bilmadim. Boshini eslay olmayapman.",
    # 5
    "Kitobxonning kun tartibi:\n\n"
    "21:00 — «Bugun erta yotaman»\n"
    "21:59 — «Bitta o'yin o'ynayman-u, yotaman»\n"
    "22:30 — «Yutqazdim. Revansh kerak»\n"
    "00:10 — «Endi bitta bob o'qib, yotaman»\n"
    "03:40 — Kitob tugadi.\n\n"
    "Erta yotish — ertaga.",
    # 6
    "Kitobxon kutubxonachidan so'rabdi:\n"
    "— Menga «Vaqtni qanday boshqarish kerak» kitobini bering.\n"
    "— Afsus, uni olgan odam uch haftadan beri qaytarmayapti. Topshirishga vaqt "
    "topolmayotgan ekan.",
    # 7
    "Tasavvur qiling, kitob qahramonlari ham sizni kuzatib turibdi...\n\n"
    "Kumush: «Bu odam bizni to'rt oydan beri 112-betda qoldirgan».\n"
    "Otabek: «Marg'ilonga yo'lga chiqqanimga to'rt oy bo'ldi. Otim ham "
    "charchadi, men ham».\n\n"
    "🤔 Sizning kitobingiz qahramonlari hozir siz haqingizda nima deyayotgan bo'lardi?",
    # 8
    "Sherlok Xolms kitobxonning xonasiga kiribdi-yu, bir qarashda aytibdi:\n"
    "— Siz kecha soat ikkigacha detektiv o'qigansiz va qotil bog'bon emas deb "
    "o'ylayapsiz.\n"
    "— Qanday bildingiz?!\n"
    "— Ko'zlaringiz qizargan, kitob oxirgi boblarida ochiq turibdi, hoshiyaga esa "
    "uch marta «BOG'BON EMAS!!!» deb yozib qo'ygansiz.",
    # 9
    "Kitob do'konida:\n"
    "— Sizda «Dangasalikni qanday yengish mumkin» kitobi bormi?\n"
    "— Bor, ana u eng yuqori tokchada.\n"
    "— ...Mayli, ertaga kelaman.",
    # 10
    "Dostoyevskiy o'qiyotgan kitobxondan so'rashibdi:\n"
    "— Bosh qahramon kim?\n"
    "— Rodion Romanovich Raskolnikov. Ba'zan Rodya, ba'zan Rodka, ba'zan "
    "Romanich, ba'zan shunchaki «u».\n"
    "— To'rt kishi ekan-da?\n"
    "— Yo'q, bitta. Men ham 200-betgacha to'rtta deb yurgandim.",
    # 11
    "Kitobxon sun'iy intellektdan so'rabdi:\n"
    "— 300 betlik romanni bitta jumlada aytib ber.\n"
    "— «Hammasi yaxshi tugadi, lekin undan oldin juda yomon bo'lgandi».\n"
    "— Bu qaysi roman?\n"
    "— Deyarli hammasi.",
    # 12
    "Yaponlarda «tsundoku» degan so'z bor — kitobni sotib olib, o'qimay uyib "
    "qo'yish.\n\n"
    "O'zbek tilida buning alohida nomi yo'q. Chunki biz buni oddiygina "
    "«kelajak uchun jamg'arma» deymiz. 📚📚📚",
    # 13
    "Ikki kitobxon bahslashibdi:\n"
    "— Kitob kinodan yaxshiroq!\n"
    "— Isbotla!\n"
    "— Kinoda bosh qahramonni qaysi aktyor o'ynasa, o'sha bo'ladi. Kitobda esa "
    "uni men o'ynayman. Men esa har doim zo'r o'ynayman.",
    # 14
    "Kitobxonning moliyaviy rejasi:\n\n"
    "1. Maosh oldim.\n"
    "2. Kitob do'koniga «shunchaki ko'rib chiqish uchun» kirdim.\n"
    "3. Maosh tugadi.\n"
    "4. Uyda 37 ta o'qilmagan kitob bor. Lekin ular orasida mana bu yangisi yo'q edi-da!",
    # 15
    "Kitobxon avtobusda shunaqa qiziq joyini o'qiyotgan ekanki, o'z bekatidan "
    "o'tib ketibdi. Keyingisidan ham. Oxirgi bekatda haydovchi so'rabdi:\n"
    "— Uka, o'zi qayerga ketyapsiz?\n"
    "— 1812-yilga. Napoleon Moskvaga yaqinlashib qoldi!",
    # 16
    "Bir kuni «o» harfi ish tashlabdi: «O'zbek tilida hammadan ko'p men "
    "ishlayman. Dam olaman!»\n\n"
    "Ertasiga gazetada e'lon chiqibdi:\n"
    "«Shahrimizda yangi kutubxna childi. Hamma qishga shiqsin!»\n\n"
    "Kitobxonlar hammasini tushunibdi va qishgacha sabr qilib turishibdi. ❄️",
    # 17
    "Gregor Zamza bir kuni ertalab uyg'onib, o'zining... kitobxonga aylanib "
    "qolganini ko'ribdi.\n\n"
    "Oilasi dahshatga tushibdi: u nonushtada ham, avtobusda ham, navbatda ham "
    "o'qirdi. Eng qo'rqinchlisi — endi u kitoblarini hech kimga qarzga bermay qo'ydi.",
    # 18
    "Savol: Qaysi matnni dunyoda hech kim oxirigacha o'qimagan?\n\n"
    "Javob: Telefondagi «Foydalanish shartlari»ni. Hamma «Roziman»ni bosadi, lekin "
    "aslida nimaga rozi bo'lganini hech kim bilmaydi. Balki u yerda «Har kuni "
    "50 bet kitob o'qishga roziman» deb yozilgandir. 🤷",
    # 19
    "Kechasi javondagi yangi kitob qo'shnisidan so'rabdi:\n"
    "— Bu uyda qachondan beri turibsiz?\n"
    "— Uch yildan beri.\n"
    "— Voy! Shu vaqtda sizni necha marta o'qishdi?\n"
    "— Hali bir marta ham. Lekin har oy changimni artib turishadi. Bu ham bir hurmat.\n\n"
    "🤔 Sizning javoningizdagi kitoblar kechasi siz haqingizda nima deb gaplashardi?",
    # 20
    "Optimist kitobxon: «Hali o'qiladigan qancha zo'r kitob bor!»\n"
    "Pessimist kitobxon: «Umr hammasini o'qishga yetmaydi...»\n"
    "Realist kitobxon indamay yana uchta kitob sotib oladi.",
    # 21
    "Kutubxonachi kitobni olib, qog'ozdagi sanaga qarabdi:\n"
    "— Siz bu kitobni 1998-yilda olgansiz!\n"
    "— Ha, — debdi kitobxon. — Lekin juda sinchiklab o'qidim.",
    # 22
    "Kitobxondan so'rashibdi:\n"
    "— Uyingizda mebel juda kam ekan-ku?\n"
    "— Kam emas. Divan «O'tkan kunlar» bilan «Mehrobdan chayon» ustida turibdi, "
    "stol — ensiklopediyalar ustida. Faqat bittasini o'qimoqchi bo'lsam, uy "
    "qulab tushadi.",
    # 23
    "O'qituvchi so'rabdi:\n"
    "— Bolalar, kitob nima uchun kerak?\n"
    "— Bilim olish uchun!\n"
    "— Tasavvurni o'stirish uchun!\n"
    "Orqa partadan Vali:\n"
    "— Stolning qisqa oyog'i tagiga qo'yish uchun! Bizning uyda eng foydali kitob — "
    "«Fizika, 7-sinf». Stol besh yildan beri qimirlamaydi.",
    # 24
    "Dunyodagi eng xavfli odam kim?\n\n"
    "Siz kitob o'qib o'tirganingizda yoningizga kelib, «Voy, shu kitobni yaxshi "
    "ko'raman! Ayniqsa oxirida...» deb gap boshlaydigan odam.\n\n"
    "Shuning uchun tajribali kitobxonlar quloqchin taqib o'qiydi. Hatto musiqa "
    "eshitmasa ham. 🎧",
    # 25
    "— Agar kimsasiz orolga faqat bitta kitob olib borish mumkin bo'lsa, qaysini "
    "olasiz?\n"
    "— «Qayiq yasash bo'yicha qo'llanma».\n"
    "— Juda aqlli tanlov!\n"
    "— Ha. Qayiq yasayman, qaytib kelaman va qolgan 200 ta kitobimni olib ketaman.",
    # 26
    "Kitobxonlar lug'ati:\n\n"
    "📖 <b>Uxlash</b> — kitob qo'ldan tushgan holat.\n"
    "📖 <b>Dam olish</b> — boshqa kitobga o'tish.\n"
    "📖 <b>Ko'chib o'tish</b> — 14 quti kitob va 1 quti boshqa narsalar.\n"
    "📖 <b>Bo'sh vaqt</b> — afsonaviy tushuncha, ilmda hali isbotlanmagan.",
    # 27
    "Telefon kitobga maqtanibdi:\n"
    "— Menda internet ham, o'yinlar ham, videolar ham bor!\n"
    "Kitob xotirjam javob beribdi:\n"
    "— Mening zaryadim hech qachon tugamaydi. Menga sho'ng'igan odam esa sening "
    "bildirishnomalaringni eshitmay ham qoladi.",
    # 28
    "Detektiv janridagi eng qisqa hikoya:\n"
    "«Kitobning oxirgi sahifasi yirtilgan edi».\n\n"
    "Eng qo'rqinchli hikoya:\n"
    "«Kitobning oxirgi sahifasi yirtilgan edi. Kitob — detektiv edi».\n\n"
    "✍️ Siz ham bitta jumlalik hikoya o'ylab ko'ring!",
    # 29
    "Kitobxon yangi kitob sotib olib, birinchi bo'lib uni... hidlabdi.\n"
    "— Nima qilyapsiz? — deb so'rabdi yonidagi odam.\n"
    "— Sifatini tekshiryapman.\n"
    "— Xo'sh?\n"
    "— Besh yulduz. Endi o'qisa ham bo'ladi.",
    # 30
    "Kitobxon tushida 80 bet o'qibdi. Ertalab turib, botga hisobot yuboribdi:\n"
    "«80 bet. Kitob nomi — eslay olmayman. Muallifi — ham. Lekin juda zo'r edi».\n\n"
    "Bot javob beribdi: «Hisobot qabul qilinmadi. Lekin tushingizdagi "
    "kutubxonaning manzilini yuboring — biz ham boraylik».",
]


def joke_number_for(day) -> int:
    """1-based number of the joke posted on `day` (a date): the list is walked
    by calendar day, starting over after the last joke."""
    return day.toordinal() % len(JOKES) + 1


def joke_text_for(day) -> str:
    n = joke_number_for(day)
    return HEADER.format(n=n) + "\n\n" + JOKES[n - 1]
