# -*- coding: utf-8 -*-
"""Bilim O'yini: Hidden Connection (Yashirin bog'lanish)"""

QUIZ_CONNECTION_QUESTIONS = [
    {"q": "Otabek, Kumush, Ziyo shohichi, Homid — bu qahramonlarni nima bog'lab turadi?", "options": ["«O'tkan kunlar» romani", "«Mehrobdan chayon» romani", "«Kecha va kunduz» romani", "«Sarob» romani"], "correct": 0},
    {"q": "Anvar, Ra'no, Domla Shahobiddin, Solih maxdum — bu qahramonlar qaysi asardan?", "options": ["«Mehrobdan chayon»", "«O'tkan kunlar»", "«Diyonat»", "«Shaytanat»"], "correct": 0},
    {"q": "Farhod, Shirin, Shopur, Xusrav — bu obrazlar qaysi doston qahramonlari?", "options": ["«Farhod va Shirin»", "«Layli va Majnun»", "«Tohir va Zuhra»", "«Alpomish»"], "correct": 0},
    {"q": "Raskolnikov, Sonya Marmeladova, Razumixin, Porfiriy Petrovich — bular qaysi romandan?", "options": ["«Jinoyat va jazo»", "«Telba»", "«Aka-uka Karamazovlar»", "«Ona»"], "correct": 0},
    {"q": "Andrey Bolkonskiy, Pyer Bezuxov, Natasha Rostova — bu qahramonlar qaysi asardan?", "options": ["«Urush va tinchlik»", "«Anna Karenina»", "«Tinch Don»", "«Ota va bolalar»"], "correct": 0},
    {"q": "Atos, Portos, Aramis, D'Artanyan — bu to'rtlikni nima birlashtiradi?", "options": ["«Uch mushketyor»", "«Graf Monte-Kristo»", "«Notr-Dam ibodatxonasi»", "«Ayvengo»"], "correct": 0},
    {"q": "Edmond Dantes, Mersedes, Fernan, Abbe Faria — bular qaysi asardan?", "options": ["«Graf Monte-Kristo»", "«Sefillar»", "«Uch mushketyor»", "«Don Kixot»"], "correct": 0},
    {"q": "Kimsan, Robiya, Shomurod, Mirvali — bu qahramonlar qaysi romanda uchraydi?", "options": ["«Ikki eshik orasi»", "«Dunyoning ishlari»", "«Ufq»", "«Chinor»"], "correct": 0},
    {"q": "Jan Valjan, Jover, Fantina, Kozetta — bu qahramonlar qaysi kitobdan?", "options": ["«Sefillar»", "«Notr-Dam ibodatxonasi»", "«Graf Monte-Kristo»", "«Ona»"], "correct": 0},
    {"q": "Kvazimodo, Esmeralda, Klod Frollo, Feb — bular qaysi asardan?", "options": ["«Notr-Dam ibodatxonasi»", "«Sefillar»", "«Faust»", "«Hamlet»"], "correct": 0},
]

# ── 2026-08 qo'shimcha: yashirin bog'lanishni topish ─────────────────────
QUIZ_CONNECTION_QUESTIONS += [
  {"q": "Anvar, Ra'no, Solih maxdum, Xudoyorxon — bularni nima bog'laydi?", "options": ["«Mehrobdan chayon» romani", "«O'tkan kunlar» romani", "«Kecha va kunduz»", "«Sarob» romani"], "correct": 0},
  {"q": "Hayrat ul-abror, Farhod va Shirin, Layli va Majnun, Sab'ai sayyor — umumiyligi nima?", "options": ["Navoiy «Xamsa»siga kiruvchi dostonlar", "Bobur asarlari", "Xalq dostonlari", "Jahon romanlari"], "correct": 0},
  {"q": "Beruniy, Ibn Sino, Al-Xorazmiy, Farg'oniy — bularni nima birlashtiradi?", "options": ["Sharq Uyg'onish davri allomalari", "Zamonaviy yozuvchilar", "Xalq baxshilari", "Sufiy shoirlar"], "correct": 0},
  {"q": "Alpomish, Go'ro'g'li, Kuntug'mish, Ravshan — umumiy jihati nima?", "options": ["O'zbek xalq dostonlari", "Qodiriy romanlari", "Jahon adabiyoti asarlari", "Tasavvuf risolalari"], "correct": 0},
  {"q": "Cho'lpon, Fitrat, Behbudiy, Avloniy — bularni nima bog'laydi?", "options": ["Jadidchilik harakati namoyandalari", "Astronomiya olimlari", "Xalq baxshilari", "Tabiblar"], "correct": 0},
  {"q": "Buxoriy, Termiziy, Abu Dovud, Nasoiy — umumiyligi nimada?", "options": ["Mashhur hadis to'plovchi muhaddislar", "Astronomlar", "Shoirlar", "Sayyohlar"], "correct": 0},
  {"q": "Tolstoy, Dostoyevskiy, Chexov, Turgenev — bularni nima birlashtiradi?", "options": ["Rus klassik adabiyoti", "Frantsuz romantizmi", "Ingliz dramaturgiyasi", "Ispan adabiyoti"], "correct": 0},
  {"q": "Samarqand, Buxoro, Xiva, Shahrisabz — adabiy jihatdan umumiyligi nima?", "options": ["Sharq ilmi va adabiyoti markazlari bo'lgan qadimiy shaharlar", "Faqat zamonaviy sanoat shaharlari", "Roman qahramonlari ismlari", "Doston nomlari"], "correct": 0},
  {"q": "Rumiy, Attor, Yassaviy, Naqshband — bularni nima bog'laydi?", "options": ["Tasavvuf ta'limoti namoyandalari", "Matematiklar", "Tarixchi solnomachilar", "Zamonaviy shoirlar"], "correct": 0},
  {"q": "Zebi, Kumush, Ra'no, Barchinoy — umumiy jihati nima?", "options": ["O'zbek adabiyotidagi ayol qahramonlar", "Shoira ayollar", "Tarixiy malikalar", "Asar nomlari"], "correct": 0},
  {"q": "Boburnoma, Temur tuzuklari, Boburning kundaliklari — janriy umumiyligi nima?", "options": ["Memuar va tarixiy-hujjatli asarlar", "Sevgi dostonlari", "Hadis to'plamlari", "Sahna asarlari"], "correct": 0},
  {"q": "G'azal, ruboiy, tuyuq, muxammas — bularni nima birlashtiradi?", "options": ["Mumtoz she'riy janrlar", "Nasriy janrlar", "Sahna janrlari", "Ilmiy janrlar"], "correct": 0},
  {"q": "Ulug'bek, Farg'oniy, Beruniy — kasbiy umumiyligi nima?", "options": ["Astronomiya bilan shug'ullanganlar", "Hadis to'plaganlar", "Doston yozganlar", "Tabiblik qilganlar"], "correct": 0},
  {"q": "Qoravoy, Otabek, Anvar, Alpomish — umumiyligi nima?", "options": ["Adabiyotdagi erkak bosh qahramonlar", "Tarixiy hukmdorlar", "Muallif taxalluslari", "Shahar nomlari"], "correct": 0},
  {"q": "Xamsa, Devon, Tazkira, Kulliyot — bular nimani anglatadi?", "options": ["Mumtoz adabiyotdagi to'plam turlari", "Shahar nomlari", "Qahramon ismlari", "She'r vaznlari"], "correct": 0},
]
