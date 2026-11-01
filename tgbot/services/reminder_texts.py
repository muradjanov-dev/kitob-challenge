"""Reminder texts: the daily inspiration DMs and the 20:00 streak reminder.

Owner (2026-11-01): funny but sincere and simple, always with "Siz", never
"sen"; one-liners plus rubrics -- short stories, reader life, talking books,
proverbs, "did you know" about the bot. "Bilasizmi?" only states what the
bot really does, and "Kun hikmati" only uses well-known folk proverbs, so
nothing here can be a made-up fact.
"""
import random

SHORT_TEXTS = [
    "📚 Kitobingiz javonda turib: «Meni ham bir eslab qo'yishsa-chi...» deb o'tiribdi 🥺 Bugun bir-ikki bet o'qib, ko'nglini olib qo'ying!",
    "☕️ Choy damlandi, kitob ochildi — endi faqat siz kerak edingiz 😊",
    "📖 Telefonni 5 daqiqaga qo'yib turamiz, kitobni 5 daqiqaga ochamiz. Kelishdikmi? 🤝",
    "😴 Uxlashdan oldin 10 bet o'qisangiz, tushingiz ham kitobdagidek qiziq chiqadi. Ilmiy isboti yo'q, lekin sinab ko'rsa bo'ladi 😄",
    "🧠 Miyangiz bugun: «Menga ham ozgina ovqat bering!» Kitob — eng to'yimli taom 🍲",
    "🐢 Sekin o'qisangiz ham mayli. Toshbaqa ham oxiri marraga yetib kelgan 😉",
    "🔖 Xatcho'pingiz bir joyda turaverib zerikib qoldi. Uni ozgina oldinga surib qo'ying 😄",
    "🍉 Tarvuzni bir o'tirishda yeb bo'lmaydi, kitobni ham. Bo'lak-bo'lak, har kuni ozdan 😋",
    "🚶 Ming chaqirimlik yo'l bir qadamdan boshlanadi. Ming betlik kitob esa — bir betdan 📖",
    "🌧 Yomg'ir yog'sa — kitob o'qishga bahona. Quyosh chiqsa — bu ham bahona ☀️ Bahona doim topiladi 😄",
    "📱 Bugun lentani necha marta varaqladingiz? Endi bir marta kitob varag'ini varaqlab ko'ring 😉",
    "🧸 Bolaligimizda ertak eshitmasdan uxlamasdik. Hozir-chi? Bir-ikki bet — kattalar uchun ertak 🌙",
    "🏋️ Sport zaliga bormasangiz ham mayli, lekin aqlning sport zali — kitob — bepul va uyingizda 😊",
    "🥇 Bugun kechagi o'zingizdan bir bet o'zib ketsangiz — bu ham g'alaba!",
    "🍵 «Choy sovib qolibdi» — demak, kitob juda qiziq ekan. Shunaqa kunlar ko'p bo'lsin 😄",
    "📚 Kitobxonlar ikki xil bo'ladi: bugun o'qiganlar va hozir o'qishni boshlaydiganlar. Siz qaysi birisiz? 😉",
    "😊 Hech kim ko'rmasa ham, kitob o'qigan kuningiz ko'nglingizda kichik bayram bo'ladi.",
    "🛋 Divan qulay, choy issiq, kitob yoningizda. Yana nima kerak? Bir tomchi xohish 💛",
    "📖 Bitta bet — bor-yo'g'i 2 daqiqa. Reklama ko'rishdan ham qisqa 😄",
    "🎒 Sumkangizda kitob bormi? Navbatda, avtobusda, kutib turganda — eng yaxshi hamroh 🚌",
    "👀 Ko'zingiz charchagan bo'lsa — audiokitob! Quloqlar ham o'qiy oladi 🎧",
    "🤫 Sir aytaymi? Har kuni ozgina o'qiydiganlar yil oxirida o'zlari ham hayron qolishadi 😉",
    "🌱 Bugungi 5 bet — ertangi aqlli fikringizning urug'i 🌳",
    "📝 O'qidingizmi? Hisobotni ham yuborib qo'ying — mehnatingiz «ko'rinmas» bo'lib qolmasin 😄",
    "🕰 «Vaqtim yo'q» — dunyodagi eng mashhur kitob. Lekin uni hali hech kim o'qib tugatmagan 😉",
    "🍪 Kitob pechenyega o'xshaydi: bittasini boshlasangiz, to'xtash qiyin 😋",
    "🎧 Ovqat pishirayotganda, yo'lda, sayrda — audiokitob bilan vaqtingiz ikki barobar foydali!",
    "💛 Bugun ham o'qishga vaqt topsangiz — o'zingizga bir «rahmat» deb qo'ying.",
    "🪙 Kitobchangiz shunchaki chiroyli raqam emas: u har kungi hisobot to'lovining 300 so'migacha qismini o'zi to'laydi. O'qing, yuting, tejang 😉",
    "👛 Hamyoningiz yana necha kunga yetishini bilmoqchimisiz? «👛 Hamyon» tugmasi hammasini ko'rsatadi.",
    "🎁 Do'stingizni ham kitobga «yuqtiring» 😄 U birinchi hisobotini yuborganda hamyoningizga <b>500 so'm</b>! Havola: «Kabinet → 🌟 Yaxshilik ulashuvchi».",
    "👥 Birga o'qish — birga choy ichishdek gap 😊 Do'stingizni chaqiring: har bir faol do'st uchun <b>500 so'm</b>, 30 tadan keyin — <b>1 000 so'm</b> 🎁",
]

RUBRIC_TEXTS = [
    # ── 📖 Kichik hikoya ─────────────────────────────────────────────────
    "📖 <b>Kichik hikoya</b>\n\n"
    "Bir bobo har oqshom nevarasiga bitta bet kitob o'qib berar ekan. Nevara so'rabdi: "
    "«Bobojon, nega faqat bitta bet?» Bobo kulib javob beribdi: «Qolganini ertaga o'qiymiz — "
    "ertaga ham shu yerda uchrashamiz.»\n\n"
    "Yillar o'tib nevara o'zi kitob yozibdi. Birinchi betiga shunday deb yozibdi: "
    "«Bir betdan boshlangan hamma narsa uchun — bobomga.» 💛\n\n"
    "Bugungi bitta betingiz ham kimningdir hikoyasining boshi bo'lishi mumkin 😊",

    "📖 <b>Kichik hikoya</b>\n\n"
    "Malika har kuni avtobusda 20 daqiqa yo'l yurardi va doim «yo'l juda uzoq» deb nolirdi. "
    "Bir kuni telefon o'rniga kitob ochdi. Bir oydan keyin hisoblasa — 3 ta kitob!\n\n"
    "Endi u boshqa narsadan noliydi: «Bekatga juda tez yetib qolyapman, eng qiziq joyida tushishim kerak» 😄\n\n"
    "Sizning «avtobus vaqtingiz» qachon? 🚌📖",

    "📖 <b>Kichik hikoya</b>\n\n"
    "Aziz aka doim «vaqtim yo'q» derdi. Bir kuni telefonidagi ekran vaqtini ko'rib qoldi — kuniga 4 soat! "
    "O'sha kuni o'ziga va'da berdi: shundan atigi 15 daqiqasi kitobga.\n\n"
    "Yil oxirida qarasa, 14 ta kitob o'qibdi. 4 soatdan 15 daqiqa kamayganini esa sezmabdi ham 😄\n\n"
    "Bugun sizning 15 daqiqangiz qayerda yashirinib yotgan ekan? 😉",

    "📖 <b>Kichik hikoya</b>\n\n"
    "Dilnoza kitob ochishi bilan mushugi kelib, aynan o'qiyotgan beti ustiga yotib olardi 🐈 "
    "Bir kuni Dilnoza kulib qo'ydi: «Demak, bu bet juda muhim ekan.»\n\n"
    "O'shandan beri u mushuk yotgan betlarni belgilab qo'yadi. Qiziq, eng sevimli parchalari aynan o'sha betlarda ekan 😄\n\n"
    "Bugun kitobingizdan o'zingizning «mushuk yotadigan» betingizni toping 📖",

    "📖 <b>Kichik hikoya</b>\n\n"
    "Ikki dugona kelishib olishdi: kim ko'p o'qisa, ikkinchisi unga choy damlab beradi ☕️ "
    "Bir oy o'tdi — ikkalasi ham bir xil o'qibdi.\n\n"
    "Shunday qilib, endi har hafta bir-biriga choy damlab, o'qigan kitoblarini gaplashib o'tirishadi. "
    "Musobaqada ikkalasi ham yutibdi 😊\n\n"
    "Sizning kitob «sherigingiz» bormi? Bo'lmasa, bugun bittasini taklif qiling 🤝",

    "📖 <b>Kichik hikoya</b>\n\n"
    "Bir yigit kutubxonadagi eng qalin kitobni ko'rib qo'rqib ketdi: «Buni qachon tugataman?» "
    "Kutubxonachi ayol jilmaydi: «Bugun faqat birinchi betini o'qing. Qolganini kitobning o'zi so'raydi.»\n\n"
    "Haqiqatan ham so'radi. Ikki haftada tugatdi 😄\n\n"
    "Qalin kitobdan qo'rqmang — bugun faqat bir necha bet 📚",

    # ── 😄 Kitobxon hayotidan ─────────────────────────────────────────────
    "😄 <b>Kitobxon hayotidan</b>\n\n"
    "— «Faqat bitta bob o'qiyman, keyin uxlayman.»\n"
    "— Soat 02:00. Bob tugadi. Keyingisi ham qisqagina ekan...\n\n"
    "Tanish holatmi? 😅 Bugun ham shunday «faqat bitta bob» qiling — hisobotni yuborishni unutmang!",

    "😄 <b>Kitobxon hayotidan</b>\n\n"
    "Kitob do'koniga «faqat qarab chiqaman» deb kirdingiz.\n"
    "Chiqishda qo'lingizda 3 ta kitob, cho'ntakda esa shamol 😅\n\n"
    "Uyda o'qilmagan kitoblar navbat kutyapti — bugun bittasiga navbat bering 📚",

    "😄 <b>Kitobxon hayotidan</b>\n\n"
    "Qahramon xafa bo'lsa — siz ham xafasiz.\n"
    "Qahramon kulsa — siz avtobusda yolg'iz o'zingiz kulib o'tirasiz 😂\n"
    "Yoningizdagilar hayron: «Bu kishiga nima bo'ldi?»\n\n"
    "Bugun ham shunday bir kitob topilsin! 📖",

    "😄 <b>Kitobxon hayotidan</b>\n\n"
    "Kitobni yarmida qoldirib, filmini ko'rdingiz.\n"
    "Filmdan keyin: «Kitobi yaxshiroq edi...» 🙄\n\n"
    "Kitobxonlarning eng sevimli gapi 😄 Kitobingizni oxirigacha o'qib, buni o'zingiz tasdiqlang!",

    "😄 <b>Kitobxon hayotidan</b>\n\n"
    "Xatcho'p yo'q. Qo'lga nima tushsa, o'sha: chek, chipta, qalam, hatto... non bo'lagi 😅\n\n"
    "Xatcho'pingiz nima bo'lsa ham, bugun uni bir necha bet oldinga suring 📖",

    "😄 <b>Kitobxon hayotidan</b>\n\n"
    "Kimdir: «Qaysi kitobni tavsiya qilasiz?»\n"
    "Kitobxon: 40 daqiqalik ma'ruza, 12 ta kitob nomi va «hammasini o'qing, afsuslanmaysiz» 😄\n\n"
    "Bugun o'qiganingizni hisobotda yozing — balki ertaga siz ham kimgadir tavsiya qilasiz!",

    # ── 🎭 Agar kitoblar gapira olsa ──────────────────────────────────────
    "🎭 <b>Agar kitoblar gapira olsa...</b>\n\n"
    "📕 Javondagi kitob: «Meni sotib olishdi, rasmimni olishdi, hatto eng chiroyli joyga qo'yishdi... "
    "Faqat o'qishni unutishdi 😢»\n\n"
    "Uyingizda shunday kitob bormi? Bugun uning ko'nglini oling 😊",

    "🎭 <b>Agar kitoblar gapira olsa...</b>\n\n"
    "📗 Yarmida qoldirilgan kitob: «Eng qiziq joyi hali oldinda edi-ku! Qaytib keling, hammasini aytib beraman 🤫»",

    "🎭 <b>Agar kitoblar gapira olsa...</b>\n\n"
    "📘 Lug'at: «Meni faqat bitta so'z uchun ochishadi. Men esa butun boshli dunyoni bilaman 😌»\n\n"
    "Bugun bitta yangi so'z o'rganish ham — kichik g'alaba!",

    "🎭 <b>Agar kitoblar gapira olsa...</b>\n\n"
    "🎧 Audiokitob: «Meni ko'z bilan o'qish shart emas, shunchaki tinglang. "
    "Siz idish yuvayotganingizda ham hikoya aytib beraman 😄»",

    # ── 💬 Kun hikmati (xalq maqollari) ────────────────────────────────────
    "💬 <b>Kun hikmati</b>\n\n"
    "«O'qigan o'zar, o'qimagan to'zar.» (xalq maqoli)\n\n"
    "Bugun biz qaysi birimiz? 😊 Bir necha bet — va javob aniq!",

    "💬 <b>Kun hikmati</b>\n\n"
    "«Ilm — aql chirog'i.» (xalq maqoli)\n\n"
    "Chiroq yoqish uchun ko'p narsa kerak emas — bir necha bet kifoya 💡",

    "💬 <b>Kun hikmati</b>\n\n"
    "«Sabr tagi — sariq oltin.» (xalq maqoli)\n\n"
    "Qalin kitobni ko'rib qo'rqmang: har kuni ozdan o'qisangiz, oxirida albatta «oltin» chiqadi 😉",

    "💬 <b>Kun hikmati</b>\n\n"
    "«Tomchi-tomchi ko'l bo'lur.» (xalq maqoli)\n\n"
    "Kuniga 10 bet — oyiga 300 bet. Bu bitta qalin kitob degani! 📚",

    # ── 🤔 Bilasizmi? (faqat botning haqiqiy imkoniyatlari) ─────────────────
    "🤔 <b>Bilasizmi?</b>\n\n"
    "Kitobchangiz kunlik hisobot to'lovining 300 so'migacha qismini o'zi to'laydi 🪙 "
    "Ya'ni o'yinlarda yutgan Kitobchangiz — hamyoningizdagi tejalgan pul!\n\n"
    "O'qing, o'ynang, tejang 😉",

    "🤔 <b>Bilasizmi?</b>\n\n"
    "Bir kun hisobot yubora olmay qolsangiz, Market'dagi «🧊 Streak muzlatish» streakingizni asrab qoladi. "
    "Kasal bo'lgan yoki safarga chiqqan kunlar uchun ajoyib «sug'urta» 😊",

    "🤔 <b>Bilasizmi?</b>\n\n"
    "Har kuni 10:00 va 21:30 da botda jonli o'yinlar bo'ladi 🎮 "
    "Kitob bilimingizni sinab, Kitobcha yutishingiz mumkin. Bugun ham qatnashing!",

    "🤔 <b>Bilasizmi?</b>\n\n"
    "Hamyonni bir martada 15 000 so'm va undan ko'p to'ldirsangiz — har 1 000 so'm uchun 1 kunlik imtiyoz: "
    "Kitobchalar ikki barobar 💎, VIP arena va kunning keyingi hisobotlari atigi 100 so'm. 30 000 so'm — butun 30 kun!",

    "🤔 <b>Bilasizmi?</b>\n\n"
    "Audiokitob tinglaganingiz ham hisobot bo'ladi 🎧 Yo'lda, oshxonada, sayrda — "
    "quloqlaringiz ham kitobxon bo'la oladi!",
]

INSPIRATION_POOL = SHORT_TEXTS + RUBRIC_TEXTS

# 20:00, to readers who have not reported today.
STREAK_WARNING_POOL = [
    "🔥 Streakingiz deraza oldida o'tirib, sizni kutyapti 🥺 Bir necha bet o'qib, uni xursand qilib qo'ying!",
    "😊 Kun hali tugamadi! Bir necha bet — va streakingiz «uf, qutuldim» deb yengil nafas oladi 😄",
    "⏰ Bugungi hisobot hali yo'q. Streakingiz biroz xavotirda, lekin sizga ishonadi 💪",
    "🌙 Oy chiqdi, yulduzlar chiqdi, faqat bugungi hisobotingiz hali chiqmadi 😄 Bir necha bet kifoya!",
    "🤍 Shuncha kun yiqqan streakingizni bugun asrab qoling — u sizning mehnatingiz!",
    "📖 Kitobingiz ochilishini kutyapti, streakingiz esa — hisobotingizni. Ikkalasini ham xursand qiling 😊",
    "🕯 Uxlashdan oldin 5 daqiqa: bir necha bet va bitta hisobot. Tushingizda ham streak yonib tursin 🔥",
    "💪 Bugun band bo'lgandirsiz, tushunamiz. Lekin 5 daqiqa topilsa — streakingiz saqlanib qoladi!",
    "🫖 Choy damlanguncha bir bet o'qisa bo'ladi. Choy tayyor bo'lguncha — hisobot ham tayyor 😉",
    "🔔 Do'stona eslatma: bugungi hisobot hali yo'q. Streakingiz «meni unutmadingizmi?» deb so'rayapti 🥺",
    "🏃 Hali ulgurasiz! Marra yaqin — bir necha bet va streakingiz yana bir kunga uzayadi 🔥",
    "🌟 Siz har kuni o'qiydiganlardansiz — bugun ham shu ajoyib odatni davom ettiring 😊",
    "📚 Streak — kunma-kun qurilgan uy. Bugun ham bitta g'isht qo'yib qo'ying 🧱",
    "🔥 Olovni o'chirmang! Bir necha bet — va streakingiz yana gurillab yonadi.",
    "😌 Kun og'ir o'tgan bo'lsa, bir necha bet kitob ko'ngilni yengil qiladi. Ham dam, ham hisobot 💛",
    "🐣 Streakingiz hali kichkina bo'lsa ham, uni boqish kerak 😄 Bugungi «ovqati» — bir necha bet!",
    "🧊 Bugun umuman imkon bo'lmasa — Market'dagi «Streak muzlatish» streakingizni asrab qoladi.",
]

_RECENT_KEY = "inspiration_recent"
_RECENT_KEEP = 25


def pick_inspiration() -> str:
    """One text for this send: a rubric piece about every other time,
    otherwise a one-liner; the last 25 picks are not repeated."""
    from django.core.cache import cache
    recent = cache.get(_RECENT_KEY) or []
    pool = RUBRIC_TEXTS if random.random() < 0.5 else SHORT_TEXTS
    text = random.choice([t for t in pool if t not in recent] or pool)
    cache.set(_RECENT_KEY, (recent + [text])[-_RECENT_KEEP:], 60 * 60 * 24 * 14)
    return text
