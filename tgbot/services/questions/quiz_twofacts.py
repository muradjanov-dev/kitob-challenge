# -*- coding: utf-8 -*-
"""Bilim O'yini: Two facts, one lie (Ikki haqiqat, bir yolg'on)"""

QUIZ_TWOFACTS_QUESTIONS = [
    {"q": "“O'tkan kunlar” haqida qaysi gap YOLG'ON?", "options": ["Bu birinchi o'zbek romani hisoblanadi", "Bosh qahramonlari Otabek va Kumush", "Muallifi Abdulla Qodiriy uni frantsuz tilida yozgan"], "correct": 2},
    {"q": "“Boburnoma” haqida qaysi gap YOLG'ON?", "options": ["Uni Zahiriddin Muhammad Bobur yozgan", "Bu — memuar (xotira) janridagi asar", "Asar to'liq she'riy vaznda yozilgan"], "correct": 2},
    {"q": "Ibn Sino haqida qaysi gap YOLG'ON?", "options": ["U “Al-Qonun fit-tib” asarining muallifi", "Uning asari asrlar davomida Yevropada darslik bo'lgan", "U faqat shoir bo'lgan, tibbiyot bilan shug'ullanmagan"], "correct": 2},
    {"q": "Mirzo Ulug'bek haqida qaysi gap YOLG'ON?", "options": ["U Samarqandda observatoriya qurdirgan", "U buyuk astronom bo'lgan", "U hech qachon yulduzlar jadvalini tuzmagan"], "correct": 2},
    {"q": "“Xamsa” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Alisher Navoiy", "U besh dostondan iborat", "U roman janrida yozilgan, dostonlardan iborat emas"], "correct": 2},
    {"q": "Imom Buxoriy haqida qaysi gap YOLG'ON?", "options": ["U “Sahih al-Buxoriy” hadis to'plamining muallifi", "U buyuk muhaddis (hadis olimi) bo'lgan", "U faqat shifokor bo'lib, hadis bilan shug'ullanmagan"], "correct": 2},
    {"q": "“Urush va tinchlik” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Lev Tolstoy", "Voqealar Napoleon urushlari davrida kechadi", "Roman atigi 50 betdan iborat qisqa qissa"], "correct": 2},
    {"q": "Ahmad Yassaviy haqida qaysi gap YOLG'ON?", "options": ["U “Hikmatlar devoni” muallifi", "U Yassaviya tariqatiga asos solgan", "U hech qachon hikmatli she'r yozmagan"], "correct": 2},
    {"q": "“Hamlet” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Uilyam Shekspir", "Bosh qahramon Daniya shahzodasi", "Asar baxtli sevgi haqidagi komediya"], "correct": 2},
    {"q": "“Don Kixot” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Migel de Servantes", "Bosh qahramon shamol tegirmonlariga hujum qiladi", "Asar XX asrda Amerikada yozilgan"], "correct": 2},
    {"q": "“Kichkina shahzoda” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Antuan de Sent-Ekzyuperi", "Qahramon boshqa sayyoradan kelgan bola", "Asar qonli urush haqidagi doston"], "correct": 2},
    {"q": "“Shum bola” haqida qaysi gap YOLG'ON?", "options": ["Muallifi G'afur G'ulom", "Qahramon sho'x yetim bola", "Asarda voqealar Londonda kechadi"], "correct": 2},
    {"q": "“Alkimyogar” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Paulo Koelo", "Bosh qahramon cho'pon Santyago", "Asar kosmik robotlar jangiga bag'ishlangan"], "correct": 2},
    {"q": "“1984” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Jorj Oruell", "Asarda Katta Birodar obrazi bor", "Asar bolalar uchun qadimgi ertak"], "correct": 2},
    {"q": "“Jinoyat va jazo” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Fyodor Dostoyevskiy", "Bosh qahramon Raskolnikov", "Raskolnikov bank xodimi bo'lib, boyib ketadi"], "correct": 2},
    {"q": "“Qutadg'u bilig” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Yusuf Xos Hojib", "XI asrda yozilgan turkiy meros", "Uni Navoiy Hirotda yozgan"], "correct": 2},
    {"q": "Abu Rayhon Beruniy haqida qaysi gap YOLG'ON?", "options": ["U qomusiy olim va astronom bo'lgan", "Yer radiusini juda aniq o'lchagan", "U faqat musiqachi bo'lgan"], "correct": 2},
    {"q": "Muhammad al-Xorazmiy haqida qaysi gap YOLG'ON?", "options": ["U algebra faniga asos solgan", "Algoritm atamasi uning nomidan kelib chiqqan", "U hech qachon hisob-kitob bilan shug'ullanmagan"], "correct": 2},
    {"q": "“Yulduzli tunlar” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Pirimqul Qodirov", "Bosh qahramon Bobur Mirzo", "Asarda Amir Temurning bolaligi tasvirlangan"], "correct": 2},
    {"q": "“Ulug'bek xazinasi” haqida qaysi gap YOLG'ON?", "options": ["Muallifi Odil Yoqubov", "Mirzo Ulug'bek va uning ilmiy merosi haqida", "Asar kulgili komediya pyesasidir"], "correct": 2},
]

# ── 2026-08 qo'shimcha: uchta gapdan yolg'onini top (3 variant) ──────────
QUIZ_TWOFACTS_QUESTIONS += [
  {"q": "«Boburnoma» haqida qaysi gap YOLG'ON?", "options": ["Muallifi Zahiriddin Muhammad Bobur", "Memuar janrida yozilgan", "Asar arab tilida yozilgan"], "correct": 2},
  {"q": "Alisher Navoiy haqida qaysi gap YOLG'ON?", "options": ["«Xamsa» muallifi", "Husayn Boyqaro saroyida faoliyat yuritgan", "XX asrda yashagan"], "correct": 2},
  {"q": "Ibn Sino haqida qaysi gap YOLG'ON?", "options": ["«Tib qonunlari» muallifi", "«Shayx ur-rais» laqabi bilan mashhur", "Ulug'bek rasadxonasini qurdirgan"], "correct": 2},
  {"q": "«Alpomish» haqida qaysi gap YOLG'ON?", "options": ["O'zbek xalq dostoni", "Baxshilar tomonidan og'zaki ijro etilgan", "Muallifi Abdulla Qodiriy"], "correct": 2},
  {"q": "Mirzo Ulug'bek haqida qaysi gap YOLG'ON?", "options": ["Amir Temurning nabirasi", "Yulduzlar jadvalini tuzgan", "«O'tkan kunlar» romanini yozgan"], "correct": 2},
  {"q": "Imom Buxoriy haqida qaysi gap YOLG'ON?", "options": ["Hadis ilmi allomasi", "«Sahih al-Buxoriy» to'plami muallifi", "Algebra faniga asos solgan"], "correct": 2},
  {"q": "«Kecha va kunduz» haqida qaysi gap YOLG'ON?", "options": ["Muallifi Cho'lpon", "Bosh qahramoni Zebi", "She'riy doston shaklida yozilgan"], "correct": 2},
  {"q": "Al-Xorazmiy haqida qaysi gap YOLG'ON?", "options": ["«Algoritm» atamasi uning nomidan olingan", "Algebra faniga asos solgan", "Tasavvuf tariqatiga asos solgan"], "correct": 2},
  {"q": "«Mantiq ut-tayr» haqida qaysi gap YOLG'ON?", "options": ["Ramziy-tasavvufiy doston", "Qushlar yetti vodiydan o'tadi", "Voqealar Hindistonda kechadi"], "correct": 2},
  {"q": "Abdulla Qodiriy haqida qaysi gap YOLG'ON?", "options": ["«O'tkan kunlar» muallifi", "«Mehrobdan chayon» muallifi", "«Shohnoma» muallifi"], "correct": 2},
  {"q": "Ahmad Yassaviy haqida qaysi gap YOLG'ON?", "options": ["«Devoni hikmat» muallifi", "Tasavvuf allomasi", "Ulug'bek davrida yashagan"], "correct": 2},
  {"q": "«Farhod va Shirin» haqida qaysi gap YOLG'ON?", "options": ["Navoiy «Xamsa»siga kiradi", "Farhod tog'ni teshadi", "Asar baxtli yakun topadi"], "correct": 2},
  {"q": "Beruniy haqida qaysi gap YOLG'ON?", "options": ["«Hindiston» asarini yozgan", "Yer aylanasini hisoblagan", "«Xamsa» dostonlarini yozgan"], "correct": 2},
  {"q": "«Qutadg'u bilig» haqida qaysi gap YOLG'ON?", "options": ["Muallifi Yusuf Xos Hojib", "Adolatli boshqaruv haqida", "XX asrda yozilgan"], "correct": 2},
  {"q": "«Chol va dengiz» haqida qaysi gap YOLG'ON?", "options": ["Muallifi Ernest Xeminguey", "Qahramoni Santyago", "Chol butun baliqni uyiga olib keladi"], "correct": 2},
]
