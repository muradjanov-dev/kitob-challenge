"""Kitob Challenge Market — bot-chat purchasable perks.

Distinct from the ShopProduct catalog (admin-curated physical/Premium prizes,
bought through the Mini App, still gated to admins for testing — see
tgbot/shop_views.py). These 5 items are small, code-defined mechanics that
give Kitobcha somewhere fun and low-friction to go, entirely inside the chat
— no WebApp, no admin hand-off (except where noted).
"""
import random
from decimal import Decimal
from io import BytesIO

from django.db import transaction
from django.utils import timezone

STREAK_FREEZE = "streak_freeze"
MYSTERY_BOX = "mystery_box"
CERTIFICATE = "certificate"
DAY_HERO = "day_hero"
LEADERBOARD_SPONSOR = "leaderboard_sponsor"

ITEMS = {
    STREAK_FREEZE: {
        "emoji": "🛡",
        "title": "Streak muzlatish",
        "price": 750,
        "description": (
            "Bir kun hisobot yubormay qolib ketsangiz ham, ketma-ketligingiz "
            "(streak) buzilmaydi — birinchi bo'sh kuningizga avtomatik ishlatiladi."
        ),
    },
    MYSTERY_BOX: {
        "emoji": "🎁",
        "title": "Sirli quti",
        "price": 200,
        "description": (
            "Tasodifiy mukofot: turli xil va miqdorlarda Kitobcha (hattoki ULTRA "
            "MEGA yutuq!), Omon qolish o'yiniga qo'shimcha jon, bonus streak-"
            "muzlatish, bepul Shaxsiy sertifikat, BEPUL jonli o'yin biletlari, "
            "1 soatlik AI Quiz, 3 soatlik Premium, Market chegirmasi va yana "
            "ko'plab syurprizlar — 140 dan ortiq xil ajoyib natijalar va yangi 100 xil unikal yutuqlar bor!"
        ),
    },
    CERTIFICATE: {
        "emoji": "📜",
        "title": "Shaxsiy sertifikat",
        "price": 150,
        "description": "O'z statistikangiz (bet, kitob, streak) bilan chiroyli rasm-sertifikat — darhol yuboriladi.",
    },
    DAY_HERO: {
        "emoji": "🌟",
        "title": "Kun qahramoni",
        "price": 500,
        "description": "Siz haqingizda tantanali e'lon guruhning E'lonlar bo'limiga darhol joylanadi.",
    },
    LEADERBOARD_SPONSOR: {
        "emoji": "🏷",
        "title": "Reyting sponsorligi",
        "price": 300,
        "description": (
            "Keyingi \"Top kitobxonlar\" e'lonida ismingiz sponsor sifatida "
            "ko'rsatiladi. Kuniga faqat 7 ta joy bor!"
        ),
    },
}

LEADERBOARD_SPONSOR_DAILY_LIMIT = 7


def leaderboard_sponsor_slots_left_today() -> int:
    from tgbot.models import LeaderboardSponsor
    today = timezone.localdate()
    used_today = LeaderboardSponsor.objects.filter(created_at__date=today).count()
    return max(0, LEADERBOARD_SPONSOR_DAILY_LIMIT - used_today)


def log_purchase(user, item_key: str, price: int) -> None:
    """Durable audit row for a fulfilled Market purchase — StreakFreezeCoverage/
    LeaderboardSponsor/etc. only capture each item's live *effect*, so this is
    the only place spend-by-item stats can be reconstructed from later."""
    from tgbot.models import MarketPurchase
    MarketPurchase.objects.create(user=user, item_key=item_key, price=price)


def charge(user, price: int) -> bool:
    """Deduct `price` Kitobcha from `user` if affordable (or refund, when
    `price` is negative — see the Reyting sponsorligi race-loss refund).
    Atomic + row-locked so concurrent taps can't double-spend.

    A banked Market discount (Market 'Sirli quti' win) is applied and
    consumed here, on the first purchase after winning it -- only for a
    real charge (price > 0), never on a refund."""
    from tgbot.models import TelegramProfile, KitobchaLedger
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        effective_price = price
        discount_pct = int(p.next_market_discount_pct or 0)
        if price > 0 and discount_pct > 0:
            effective_price = max(0, price - (price * discount_pct) // 100)
            p.next_market_discount_pct = 0
        if Decimal(p.ball or 0) < Decimal(effective_price):
            return False
        p.ball = Decimal(p.ball or 0) - Decimal(effective_price)
        p.save(update_fields=["ball", "next_market_discount_pct"])
        KitobchaLedger.objects.create(user=p, delta=-effective_price, reason="market_charge")
    return True


def admin_grant_kitobcha(target, amount: int) -> Decimal:
    """Flat admin-issued Kitobcha adjustment (no Premium 2x multiplier, unlike
    update_ball) — bosh admin can hand any amount to any user from the bot's
    /kitobcha command. Always ledgered so it shows up in daily earned/spent
    totals same as every other balance change."""
    from tgbot.models import TelegramProfile, KitobchaLedger
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=target.id)
        p.ball = Decimal(p.ball or 0) + Decimal(amount)
        p.save(update_fields=["ball"])
        KitobchaLedger.objects.create(user=p, delta=int(amount), reason="admin_grant")
        return p.ball


MYSTERY_PRIZES = [
    ("kitobcha_small", 22),
    ("kitobcha_big", 9),
    ("kitobcha_mega", 2),
    ("kitobcha_ultra_mega", 1),
    ("survival_life_1", 13),
    ("survival_life_2", 4),
    ("survival_life_3", 2),
    ("streak_freeze", 11),
    ("streak_freeze_2", 3),
    ("free_certificate", 6),
    ("free_game_ticket_1", 8),
    ("free_game_ticket_2", 3),
    ("ai_quiz_trial", 4),
    ("premium_trial_3h", 3),
    ("refund_box_cost", 5),
    ("market_discount_20", 4),
    ("market_discount_50", 1),
    # Flavor Kitobcha family — same underlying mechanic as kitobcha_small/
    # big/mega, but each with its own themed name, emoji and amount range,
    # so the "what did I win" moment stays varied and playful.
    ("flavor_kutubxonachi", 5),
    ("flavor_sahifalar_sehri", 5),
    ("flavor_muallif_duosi", 4),
    ("flavor_yarim_tun", 4),
    ("flavor_qadimiy_xazina", 3),
    ("flavor_kitob_qurti", 5),
    ("flavor_bilim_yogdusi", 5),
    ("flavor_varaqlar", 5),
    ("flavor_kutubxona_kaliti", 4),
    ("flavor_soz_ustasi", 4),
    ("flavor_uyqusiz_kecha", 4),
    ("flavor_ilk_bob", 5),
    ("flavor_oxirgi_sahifa", 3),
    ("flavor_changbosgan_javon", 3),
    ("flavor_sirli_xat", 4),
    ("flavor_kutubxona_arvohi", 4),
    ("flavor_qissa_qahramoni", 4),
    ("flavor_sehrli_xatchop", 5),
    ("flavor_sehrli_chirog", 4),
    ("flavor_kitobxonlar_ittifoqi", 3),
    ("flavor_tong_saharlik", 5),
    ("flavor_yulduzli_tun", 4),
    ("flavor_buyuk_kutubxona", 1),
    # ── 100 YANGI SIRLI QUTI YUTUQLARI ──
    ("navoiy_gavhari", 4),
    ("bobur_xazinasi", 3),
    ("ibn_sino_jomi", 4),
    ("xorazmiy_tilsimi", 5),
    ("beruniy_kombasi", 4),
    ("rumiy_nayi", 4),
    ("attor_atri", 4),
    ("yassaviy_durdonasi", 3),
    ("naqshband_duosi", 3),
    ("gazzoliy_kimyosi", 3),
    ("firdavsiy_toji", 4),
    ("bedil_tilsimi", 4),
    ("mashrab_olovli", 4),
    ("ogahiy_chashmasi", 5),
    ("furqat_sadosi", 5),
    ("muqimiy_tuhfasi", 5),
    ("nodirabegim_marjoni", 4),
    ("uvaysiy_topishmog'i", 5),
    ("zebunniso_bayti", 4),
    ("al_fargoni_astrolabi", 4),
    ("termiziy_rivoyati", 4),
    ("moturidiy_qalqoni", 3),
    ("zamaxshariy_lugati", 4),
    ("qoshgariy_devoni", 3),
    ("yusuf_xos_hojib", 2),
    ("don_kixot_qalqoni", 5),
    ("sherlok_lupasi", 4),
    ("monte_kristo_oltini", 2),
    ("shahzoda_guli", 4),
    ("faust_kompasi", 4),
    ("gamlet_monologi", 4),
    ("robinzon_oroli", 5),
    ("alisa_oynasi", 4),
    ("garri_tayoqchasi", 3),
    ("odisseya_kemasi", 3),
    ("dante_yulduzlari", 2),
    ("kapitan_granto", 5),
    ("tom_soyer_xazinasi", 5),
    ("mobi_dik_kompasi", 4),
    ("uch_mushketyor", 4),
    ("urush_va_tinchlik", 3),
    ("jinoyat_va_jazo", 3),
    ("chol_va_dengiz", 4),
    ("yuz_yil_yolgizlik", 3),
    ("1984_haqiqati", 3),
    ("kichik_qora_baliqcha", 5),
    ("otamdan_qolgan_dalalar", 4),
    ("otkan_kunlar_kumush", 2),
    ("mehrobdan_chayon", 4),
    ("sarob_romani", 4),
    ("simurgh_pati", 2),
    ("humoy_soyasi", 2),
    ("zulmat_obihayot", 3),
    ("kohna_xarita", 4),
    ("oltin_xatchop", 4),
    ("zumrad_siyohdon", 3),
    ("kumush_qalam", 5),
    ("alifbo_tilsimi", 5),
    ("hikmat_javohiri", 3),
    ("haqiqat_kozgusi", 3),
    ("ilm_mashalasi", 4),
    ("sabab_oqibat_toshi", 4),
    ("tavakkul_gavhari", 3),
    ("qanoat_xazinasi", 3),
    ("shukr_chirogi", 4),
    ("sabr_qalqoni", 3),
    ("saxovat_daryosi", 3),
    ("odob_ziynati", 4),
    ("farosat_kozoynagi", 4),
    ("ziyoli_qalb_nuri", 3),
    ("kitobsevar_tulpori", 4),
    ("munozara_qilichi", 4),
    ("mutolaa_halovati", 5),
    ("sahifa_nafasi", 5),
    ("oltin_sandıq", 1),
    ("vip_gold_ticket_1", 3),
    ("vip_gold_ticket_2", 2),
    ("vip_gold_ticket_3", 1),
    ("premium_pass_1d", 2),
    ("premium_pass_2d", 1),
    ("survival_armor_4", 2),
    ("survival_armor_5", 1),
    ("freeze_shield_3", 2),
    ("market_mega_discount_70", 1),
    ("market_discount_30", 3),
    ("market_discount_40", 2),
    ("ai_quiz_pass_3h", 2),
    ("ai_quiz_pass_6h", 1),
    ("gold_certificate_vip", 3),
    ("double_refund_box", 2),
    ("triple_refund_box", 1),
    ("fortune_booster_100", 4),
    ("fortune_booster_250", 3),
    ("fortune_booster_500", 2),
    ("fortune_booster_777", 1),
    ("legend_reader_gift", 2),
    ("champion_bonus", 2),
    ("royal_kitobcha", 1),
    ("secret_mastery", 1),
    ("grand_mystery_jackpot", 1),
]

# key -> (label incl. emoji, min amount, max amount)
FLAVOR_KITOBCHA = {
    "flavor_kutubxonachi":        ("📖 Kutubxonachi in'omi", 75, 200),
    "flavor_sahifalar_sehri":     ("✨ Sahifalar sehri", 60, 180),
    "flavor_muallif_duosi":       ("🙏 Muallif duosi", 100, 250),
    "flavor_yarim_tun":           ("🌙 Yarim tungi kashfiyot", 90, 220),
    "flavor_qadimiy_xazina":      ("🏺 Qadimiy xazina", 150, 400),
    "flavor_kitob_qurti":         ("🐛 Kitob qurti bonusi", 40, 120),
    "flavor_bilim_yogdusi":       ("💡 Bilim yog'dusi", 75, 190),
    "flavor_varaqlar":            ("🍃 Varaqlar shitirlashi", 50, 140),
    "flavor_kutubxona_kaliti":    ("🗝 Kutubxona kaliti", 110, 280),
    "flavor_soz_ustasi":          ("✍️ So'z ustasi in'omi", 85, 210),
    "flavor_uyqusiz_kecha":       ("🦉 Uyqusiz kecha mukofoti", 95, 230),
    "flavor_ilk_bob":             ("📗 Ilk bob hayajoni", 65, 160),
    "flavor_oxirgi_sahifa":       ("🎉 Oxirgi sahifa zavqi", 120, 300),
    "flavor_changbosgan_javon":   ("🗄 Chang bosgan javon xazinasi", 140, 350),
    "flavor_sirli_xat":           ("💌 Yozuvchining sirli xati", 100, 260),
    "flavor_kutubxona_arvohi":    ("👻 Kutubxona arvohi sovg'asi", 80, 200),
    "flavor_qissa_qahramoni":     ("⚔️ Qissa qahramonining duosi", 110, 270),
    "flavor_sehrli_xatchop":      ("🔖 Sehrli xatcho'p", 60, 150),
    "flavor_sehrli_chirog":       ("🪔 Sehrli chiroq bergan tilak", 70, 190),
    "flavor_kitobxonlar_ittifoqi": ("🤝 Kitobxonlar ittifoqi bonusi", 130, 320),
    "flavor_tong_saharlik":       ("🌅 Tong saharlik ilhom", 55, 140),
    "flavor_yulduzli_tun":        ("🌌 Yulduzli tun mukofoti", 105, 260),
    "flavor_buyuk_kutubxona":     ("🏛 Buyuk kutubxona duosi", 300, 600),
    # ── 100 YANGI XAZINALAR VA MUKOFOTLAR ──
    "navoiy_gavhari": ('💎 Alisher Navoiyning nazm gavhari', 150, 350),
    "bobur_xazinasi": ('👑 Zahiriddin Muhammad Boburning Hind xazinasi', 200, 450),
    "ibn_sino_jomi": ('🧪 Abu Ali ibn Sinoning hayot sharbati', 120, 300),
    "xorazmiy_tilsimi": ('📐 Al-Xorazmiyning algebraik tilsimi', 100, 260),
    "beruniy_kombasi": ('🌍 Abu Rayhon Beruniyning globusi', 130, 310),
    "rumiy_nayi": ('🪈 Mavlono Rumiyning ilohiy nayi', 160, 380),
    "attor_atri": ('🌸 Farididdin Attorning 7 vodiy atri', 140, 320),
    "yassaviy_durdonasi": ('📜 Xoja Ahmad Yassaviyning Hikmat durdonasi', 175, 400),
    "naqshband_duosi": ('🌾 Bahouddin Naqshbandning «Dil ba Yoru» duosi', 180, 420),
    "gazzoliy_kimyosi": ("🗝 Imom G'azzoliyning Saodat kimyosi", 190, 440),
    "firdavsiy_toji": ('👑 Firdavsiy «Shohnoma»sining Rustam toji', 160, 360),
    "bedil_tilsimi": ('📜 Mirzo Bedilning botiniy sirlar kitobi', 130, 290),
    "mashrab_olovli": ("🔥 Boborahim Mashrabning olovli g'azali", 150, 340),
    "ogahiy_chashmasi": ("💧 Ogahiyning ma'rifat chashmasi", 110, 270),
    "furqat_sadosi": ('🪕 Zokirjon Furqatning musofirlik nolasi', 95, 240),
    "muqimiy_tuhfasi": ("🎭 Muhammad Aminxo'ja Muqimiy tuhfasi", 90, 230),
    "nodirabegim_marjoni": ('📿 Nodirabegimning adabiy marjoni', 125, 280),
    "uvaysiy_topishmog'i": ('🧩 Jahonotin Uvaysiyning sirli chistoni', 115, 260),
    "zebunniso_bayti": ('✍️ Zebunniso begimning oltin bayti', 135, 300),
    "al_fargoni_astrolabi": ("🔭 Ahmad al-Farg'oniyning yulduzlar jadvali", 145, 330),
    "termiziy_rivoyati": ('🕌 Imom at-Termiziyning nurlari', 155, 350),
    "moturidiy_qalqoni": ('🛡 Imom Moturidiyning tafakkur qalqoni', 170, 390),
    "zamaxshariy_lugati": ("📚 Mahmud az-Zamaxshariyning «Asos ul-balog'a» duri", 140, 310),
    "qoshgariy_devoni": ("🗺 Mahmud Qoshg'ariyning qadimiy turkiy xaritasi", 185, 410),
    "yusuf_xos_hojib": ("👑 Yusuf Xos Hojibning «Qutadg'u Bilig» baxt kaliti", 220, 500),
    "don_kixot_qalqoni": ('🛡 Don Kixot va Lamanchaning jasorat qalqoni', 100, 250),
    "sherlok_lupasi": ('🔎 Sherlok Xolmsning detektiv lupasi', 140, 320),
    "monte_kristo_oltini": ("💰 Graf Monte-Kristoning if qal'asi oltinlari", 250, 600),
    "shahzoda_guli": ('🌹 Kichik Shahzodaning sayyoradagi yagona atirguli', 130, 290),
    "faust_kompasi": ('🧭 Gyotening «Faust» qadimiy kompasi', 120, 280),
    "gamlet_monologi": ("💀 Shekspirning «Bo'lmoq yo bo'lmaslik» javohiri", 150, 340),
    "robinzon_oroli": ('🏝 Robinzon Kruzoning kashfiyot xaritasi', 110, 260),
    "alisa_oynasi": ("🪞 Alisaning Mo''jizalar mamlakati oynasi", 125, 290),
    "garri_tayoqchasi": ('🪄 Sehrgarlar maktabining zumrad tayoqchasi', 160, 370),
    "odisseya_kemasi": ('⛵️ Gomerning «Odisseya» epik kemasi', 170, 380),
    "dante_yulduzlari": ('✨ Dantening «Ilohiy Komediya» jannat yulduzlari', 200, 450),
    "kapitan_granto": ('🗺 Kapitan Grantning 37-parallel xabarnomasi', 105, 250),
    "tom_soyer_xazinasi": ("🏴\u200d☠️ Tom Soyer va Geklberri Finning g'or xazinasi", 115, 270),
    "mobi_dik_kompasi": ('🐋 Oq kit (Mobi Dik) dengizchilari kompasi', 135, 300),
    "uch_mushketyor": ("🤺 D'Artanyan va Uch Mushketyor qilichi", 145, 330),
    "urush_va_tinchlik": ('📜 Lev Tolstoyning «Urush va Tinchlik» sahifasi', 180, 400),
    "jinoyat_va_jazo": ('⚖️ Fyodor Dostoyevskiyning vijdon tarozisi', 165, 370),
    "chol_va_dengiz": ('🎣 Ernest Xemingueyning sabr va matonati', 120, 270),
    "yuz_yil_yolgizlik": ('🦋 Gabriel Garsia Markesning sariq kapalaklari', 155, 350),
    "1984_haqiqati": ('👁 Jorj Oruellning «1984» erkin tafakkur siri', 175, 390),
    "kichik_qora_baliqcha": ('🐟 Samad Behrangiyning ozodlik oqimi', 85, 210),
    "otamdan_qolgan_dalalar": ("🌾 Tog'ay Murodning xalqona samimiyati", 160, 360),
    "otkan_kunlar_kumush": ("👰 Abdulla Qodiriyning «O'tkan kunlar» sadoqati", 210, 480),
    "mehrobdan_chayon": ("🕌 Anvar va Ra'noning pokiza sevgisi", 150, 330),
    "sarob_romani": ('🌫 Abdulla Qahhorning yuksak mahorati', 130, 290),
    "simurgh_pati": ("🪶 Qof tog'i Simurg'ining oltin pati", 200, 500),
    "humoy_soyasi": ('🦅 Humoy qushining saodatli soyasi', 250, 550),
    "zulmat_obihayot": ('🧪 Xizr chashmasining tiriklik suvi (Obihayot)', 180, 420),
    "kohna_xarita": ('🗺 Aleksandriya kutubxonasining qadimiy xaritasi', 140, 330),
    "oltin_xatchop": ("🔖 Qadimiy qo'lyozmaning sof oltin xatcho'pi", 120, 280),
    "zumrad_siyohdon": ('🖋 Podshohlar kotibining zumrad siyohdoni', 150, 350),
    "kumush_qalam": ('✏️ Shoirlar ilhomining kumush qalami', 110, 260),
    "alifbo_tilsimi": ('🔤 Ming yillik qadimiy alifbo tilsimi', 100, 240),
    "hikmat_javohiri": ('💎 Qalbni yorituvchi hikmat javohiri', 170, 390),
    "haqiqat_kozgusi": ("🪞 Soxtalikni fosh etuvchi Haqiqat ko'zgusi", 160, 370),
    "ilm_mashalasi": ("🔥 Qorong'ulikni quvuvchi Ilm mash'alasi", 135, 310),
    "sabab_oqibat_toshi": ("🔮 Taqdir sabablarini ko'rsatuvchi sirli tosh", 145, 340),
    "tavakkul_gavhari": ('✨ Xotirjam qalbning Tavakkul gavhari', 175, 400),
    "qanoat_xazinasi": ('🏺 Hech qachon tugamaydigan Qanoat xazinasi', 190, 430),
    "shukr_chirogi": ("🪔 Baraka keltiruvchi Shukr chirog'i", 150, 350),
    "sabr_qalqoni": ('🛡 Barcha qiyinchiliklarni yenguvchi Sabr qalqoni', 165, 380),
    "saxovat_daryosi": ('🌊 Muruvvatli insonning Saxovat daryosi', 185, 410),
    "odob_ziynati": ('👑 Har qanday boylikdan ustun Odob ziynati', 130, 300),
    "farosat_kozoynagi": ("👓 Inson botinini anglovchi Farosat ko'zoynagi", 140, 320),
    "ziyoli_qalb_nuri": ('💡 Jamiyatni yorituvchi Ziyoli qalb nuri', 155, 360),
    "kitobsevar_tulpori": ('🐎 Bilim vodiysiga eltuvchi tulpor', 125, 290),
    "munozara_qilichi": ('⚔️ Mantiqiy bahsda yengilmas Munozara qilichi', 135, 310),
    "mutolaa_halovati": ('☕️ Issiq choy va sokin Mutolaa halovati', 95, 230),
    "sahifa_nafasi": ('🍃 Yangi kitob varaqlarining muattar hidi', 105, 250),
    "oltin_sandıq": ("🎁 Sirli qutining eng qimmatbaho Oltin Sandig'i", 300, 750),
    "double_refund_box": ('🔁🔁 2 BARAVAR QUTI QAYTIMI: +400 Kitobcha!', 400, 400),
    "triple_refund_box": ('💥💥 3 BARAVAR QUTI QAYTIMI: +600 Kitobcha!', 600, 600),
    "fortune_booster_100": ('⚡️ Omadli Tezlatkich: +100 Kitobcha!', 100, 100),
    "fortune_booster_250": ('⚡️⚡️ Super Tezlatkich: +250 Kitobcha!', 250, 250),
    "fortune_booster_500": ('⚡️🔥 Oltin Tezlatkich: +500 Kitobcha!', 500, 500),
    "fortune_booster_777": ('🎰 777 OMAD JEKPOTI: +777 Kitobcha!', 777, 777),
    "legend_reader_gift": ('🌟 Afsonaviy Kitobxon Mukofoti: +333 Kitobcha!', 333, 333),
    "champion_bonus": ('🏆 Chempionlik Ilhomi: +444 Kitobcha!', 444, 444),
    "royal_kitobcha": ("👑 Shohona Kitobcha Sovg'asi: +555 Kitobcha!", 555, 555),
    "secret_mastery": ('🗝 Mutolaa Ustasi Xazinasi: +666 Kitobcha!', 666, 666),
    "grand_mystery_jackpot": ('🌋👑 BUYUK SIRLI QUTI GRAND JEKPOTI: +3000 Kitobcha!', 3000, 3000),
}


def resolve_mystery_box(user):
    """Apply an immediate random prize (always something — this is meant to
    feel generous, not disappointing). Returns (text, wants_certificate) —
    the bot handler sends the certificate photo itself when the flag is set,
    since certificate delivery is a Telegram API call, not a DB write."""
    from tgbot.models import TelegramProfile, KitobchaLedger
    pick = random.choices(
        [k for k, _ in MYSTERY_PRIZES],
        weights=[w for _, w in MYSTERY_PRIZES],
        k=1,
    )[0]
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)

        if pick in FLAVOR_KITOBCHA:
            label, lo, hi = FLAVOR_KITOBCHA[pick]
            amount = random.randint(lo, hi)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
            return f"{label}: <b>+{amount} Kitobcha</b>!", False

        if pick == "kitobcha_small":
            amount = random.randint(50, 150)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
            return f"🪙 <b>+{amount} Kitobcha</b> yutdingiz!", False
        if pick == "kitobcha_big":
            amount = random.randint(250, 500)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
            return f"🤑 KATTA YUTUQ! <b>+{amount} Kitobcha</b>!", False
        if pick == "kitobcha_mega":
            amount = random.randint(800, 1500)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
            return f"💥 MEGA YUTUQ!!! <b>+{amount} Kitobcha</b>!!! 🎉", False
        if pick == "kitobcha_ultra_mega":
            amount = random.randint(2000, 3500)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
            return f"🌋 ULTRA MEGA YUTUQ!!! <b>+{amount} Kitobcha</b>!!! 🏆🎉", False

        if pick == "survival_life_1":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 1
            p.save(update_fields=["bonus_survival_lives"])
            return "❤️ Keyingi <b>Omon qolish</b> o'yiningizga <b>+1 qo'shimcha jon</b>!", False
        if pick == "survival_life_2":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 2
            p.save(update_fields=["bonus_survival_lives"])
            return "💖 OMON! Keyingi <b>Omon qolish</b> o'yiningizga <b>+2 qo'shimcha jon</b>!", False
        if pick == "survival_life_3":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 3
            p.save(update_fields=["bonus_survival_lives"])
            return "🛡❤️ SUPER OMON! Keyingi <b>Omon qolish</b> o'yiningizga <b>+3 qo'shimcha jon</b>!", False

        if pick == "free_certificate":
            return "📜 Sizga <b>BEPUL Shaxsiy sertifikat</b> tushdi — tayyorlanmoqda!", True

        if pick == "free_game_ticket_1":
            p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 1
            p.save(update_fields=["bonus_free_game_entries"])
            return "🎟 Keyingi jonli o'yinga <b>1 ta BEPUL bilet</b> yutdingiz!", False
        if pick == "free_game_ticket_2":
            p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 2
            p.save(update_fields=["bonus_free_game_entries"])
            return "🎟🎟 Keyingi jonli o'yinlarga <b>2 ta BEPUL bilet</b> yutdingiz!", False

        if pick == "ai_quiz_trial":
            import datetime as _dt
            from tgbot.tasks import expire_ai_quiz_trial
            until = timezone.now() + _dt.timedelta(hours=1)
            p.trial_ai_quiz_until = until
            p.save(update_fields=["trial_ai_quiz_until"])
            expire_ai_quiz_trial.apply_async(args=[p.id], countdown=3600)
            return "🤖 <b>1 soatlik BEPUL AI Quiz yaratish</b> imkoniyati yutdingiz!", False
        if pick == "premium_trial_3h":
            import datetime as _dt
            from tgbot.tasks import expire_trial_premium
            until = timezone.now() + _dt.timedelta(hours=3)
            p.trial_premium_until = until
            p.save(update_fields=["trial_premium_until"])
            expire_trial_premium.apply_async(args=[p.id], countdown=3 * 3600)
            return "💎 <b>3 soatlik BEPUL Premium</b> yutdingiz — barcha imtiyozlar ochiq!", False

        if pick == "refund_box_cost":
            amount = ITEMS[MYSTERY_BOX]["price"]
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
            return f"🔁 Qutining narxi qaytarildi — <b>+{amount} Kitobcha</b>! Amalda bepul aylanish edi 😄", False
        if pick == "market_discount_20":
            p.next_market_discount_pct = max(int(p.next_market_discount_pct or 0), 20)
            p.save(update_fields=["next_market_discount_pct"])
            return "🏷 Keyingi Market xaridingizga <b>20% chegirma</b> yutdingiz!", False
        if pick == "market_discount_50":
            p.next_market_discount_pct = max(int(p.next_market_discount_pct or 0), 50)
            p.save(update_fields=["next_market_discount_pct"])
            return "🏷🔥 KATTA CHEGIRMA! Keyingi Market xaridingizga <b>50% chegirma</b>!", False


        # ── MAXSUS YANGI 100 TALIK MUKOFOTLARNI ISHLATISH ──
        if pick == "free_game_ticket_3":
            p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 3
            p.save(update_fields=["bonus_free_game_entries"])
            return "🎟🎟🎟 OLTIN CHIPTA! Keyingi jonli o'yinlarga <b>3 ta BEPUL bilet</b> yutdingiz!", False

        if pick == "premium_1d":
            import datetime as _dt
            from tgbot.models import Payment
            Payment.grant_or_extend(p, 1, amount=0)
            until = timezone.now() + _dt.timedelta(days=1)
            p.trial_premium_until = max(p.trial_premium_until or until, until)
            p.save(update_fields=["trial_premium_until"])
            return "💎👑 <b>24 SOATLIK (1 KUN) TO'LIQ BEPUL PREMIUM!</b> Barcha VIP o'yinlar va imtiyozlar siz uchun ochiq!", False

        if pick == "premium_2d":
            import datetime as _dt
            from tgbot.models import Payment
            Payment.grant_or_extend(p, 2, amount=0)
            until = timezone.now() + _dt.timedelta(days=2)
            p.trial_premium_until = max(p.trial_premium_until or until, until)
            p.save(update_fields=["trial_premium_until"])
            return "💎👑🔥 <b>48 SOATLIK (2 KUN) TO'LIQ BEPUL PREMIUM!</b> Barcha VIP o'yinlar va imtiyozlar siz uchun ochiq!", False

        if pick == "survival_4":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 4
            p.save(update_fields=["bonus_survival_lives"])
            return "🛡🛡 SUPER BRONYA! Keyingi <b>Omon qolish</b> o'yiningizga <b>+4 qo'shimcha jon</b>!", False

        if pick == "survival_5":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 5
            p.save(update_fields=["bonus_survival_lives"])
            return "🛡❤️ AFSONAVIY BRONYA! Keyingi <b>Omon qolish</b> o'yiningizga <b>+5 TA SUPER JON</b>!", False

        if pick == "freeze_3":
            p.streak_freeze_count = (p.streak_freeze_count or 0) + 3
            p.save(update_fields=["streak_freeze_count"])
            return "❄️❄️❄️ QALQON! Bonus <b>3 ta Streak muzlatish</b> tokeni yutdingiz!", False

        if pick == "discount_70":
            p.next_market_discount_pct = max(int(p.next_market_discount_pct or 0), 70)
            p.save(update_fields=["next_market_discount_pct"])
            return "🏷🔥 SUPER CHEGIRMA! Keyingi Market xaridingizga <b>70% CHEGIRMA</b>!", False

        if pick == "discount_30":
            p.next_market_discount_pct = max(int(p.next_market_discount_pct or 0), 30)
            p.save(update_fields=["next_market_discount_pct"])
            return "🏷 Keyingi Market xaridingizga <b>30% chegirma</b> yutdingiz!", False

        if pick == "discount_40":
            p.next_market_discount_pct = max(int(p.next_market_discount_pct or 0), 40)
            p.save(update_fields=["next_market_discount_pct"])
            return "🏷 Keyingi Market xaridingizga <b>40% chegirma</b> yutdingiz!", False

        if pick == "ai_quiz_3h":
            import datetime as _dt
            from tgbot.tasks import expire_ai_quiz_trial
            until = timezone.now() + _dt.timedelta(hours=3)
            p.trial_ai_quiz_until = until
            p.save(update_fields=["trial_ai_quiz_until"])
            expire_ai_quiz_trial.apply_async(args=[p.id], countdown=3 * 3600)
            return "🤖 <b>3 soatlik BEPUL AI Quiz yaratish</b> imkoniyati yutdingiz!", False

        if pick == "ai_quiz_6h":
            import datetime as _dt
            from tgbot.tasks import expire_ai_quiz_trial
            until = timezone.now() + _dt.timedelta(hours=6)
            p.trial_ai_quiz_until = until
            p.save(update_fields=["trial_ai_quiz_until"])
            expire_ai_quiz_trial.apply_async(args=[p.id], countdown=6 * 3600)
            return "🤖🔥 <b>6 soatlik CHEKSIZ AI Quiz yaratish</b> imkoniyati yutdingiz!", False

        p.streak_freeze_count = (p.streak_freeze_count or 0) + 1
        if pick == "streak_freeze_2":
            p.streak_freeze_count += 1
            p.save(update_fields=["streak_freeze_count"])
            return "🛡🛡 Bonus <b>2 ta Streak muzlatish</b> tokeni yutdingiz!", False
        p.save(update_fields=["streak_freeze_count"])
        return "🛡 Bonus <b>Streak muzlatish</b> tokeni yutdingiz!", False


def apply_streak_freeze_purchase(user) -> int:
    from tgbot.models import TelegramProfile
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)

        # ── MAXSUS YANGI 100 TALIK MUKOFOTLARNI ISHLATISH ──
        if pick == "free_game_ticket_3":
            p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 3
            p.save(update_fields=["bonus_free_game_entries"])
            return "🎟🎟🎟 OLTIN CHIPTA! Keyingi jonli o'yinlarga <b>3 ta BEPUL bilet</b> yutdingiz!", False

        if pick == "premium_1d":
            import datetime as _dt
            from tgbot.models import Payment
            Payment.grant_or_extend(p, 1, amount=0)
            until = timezone.now() + _dt.timedelta(days=1)
            p.trial_premium_until = max(p.trial_premium_until or until, until)
            p.save(update_fields=["trial_premium_until"])
            return "💎👑 <b>24 SOATLIK (1 KUN) TO'LIQ BEPUL PREMIUM!</b> Barcha VIP o'yinlar va imtiyozlar siz uchun ochiq!", False

        if pick == "premium_2d":
            import datetime as _dt
            from tgbot.models import Payment
            Payment.grant_or_extend(p, 2, amount=0)
            until = timezone.now() + _dt.timedelta(days=2)
            p.trial_premium_until = max(p.trial_premium_until or until, until)
            p.save(update_fields=["trial_premium_until"])
            return "💎👑🔥 <b>48 SOATLIK (2 KUN) TO'LIQ BEPUL PREMIUM!</b> Barcha VIP o'yinlar va imtiyozlar siz uchun ochiq!", False

        if pick == "survival_4":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 4
            p.save(update_fields=["bonus_survival_lives"])
            return "🛡🛡 SUPER BRONYA! Keyingi <b>Omon qolish</b> o'yiningizga <b>+4 qo'shimcha jon</b>!", False

        if pick == "survival_5":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 5
            p.save(update_fields=["bonus_survival_lives"])
            return "🛡❤️ AFSONAVIY BRONYA! Keyingi <b>Omon qolish</b> o'yiningizga <b>+5 TA SUPER JON</b>!", False

        if pick == "freeze_3":
            p.streak_freeze_count = (p.streak_freeze_count or 0) + 3
            p.save(update_fields=["streak_freeze_count"])
            return "❄️❄️❄️ QALQON! Bonus <b>3 ta Streak muzlatish</b> tokeni yutdingiz!", False

        if pick == "discount_70":
            p.next_market_discount_pct = max(int(p.next_market_discount_pct or 0), 70)
            p.save(update_fields=["next_market_discount_pct"])
            return "🏷🔥 SUPER CHEGIRMA! Keyingi Market xaridingizga <b>70% CHEGIRMA</b>!", False

        if pick == "discount_30":
            p.next_market_discount_pct = max(int(p.next_market_discount_pct or 0), 30)
            p.save(update_fields=["next_market_discount_pct"])
            return "🏷 Keyingi Market xaridingizga <b>30% chegirma</b> yutdingiz!", False

        if pick == "discount_40":
            p.next_market_discount_pct = max(int(p.next_market_discount_pct or 0), 40)
            p.save(update_fields=["next_market_discount_pct"])
            return "🏷 Keyingi Market xaridingizga <b>40% chegirma</b> yutdingiz!", False

        if pick == "ai_quiz_3h":
            import datetime as _dt
            from tgbot.tasks import expire_ai_quiz_trial
            until = timezone.now() + _dt.timedelta(hours=3)
            p.trial_ai_quiz_until = until
            p.save(update_fields=["trial_ai_quiz_until"])
            expire_ai_quiz_trial.apply_async(args=[p.id], countdown=3 * 3600)
            return "🤖 <b>3 soatlik BEPUL AI Quiz yaratish</b> imkoniyati yutdingiz!", False

        if pick == "ai_quiz_6h":
            import datetime as _dt
            from tgbot.tasks import expire_ai_quiz_trial
            until = timezone.now() + _dt.timedelta(hours=6)
            p.trial_ai_quiz_until = until
            p.save(update_fields=["trial_ai_quiz_until"])
            expire_ai_quiz_trial.apply_async(args=[p.id], countdown=6 * 3600)
            return "🤖🔥 <b>6 soatlik CHEKSIZ AI Quiz yaratish</b> imkoniyati yutdingiz!", False

        p.streak_freeze_count = (p.streak_freeze_count or 0) + 1
        p.save(update_fields=["streak_freeze_count"])
        return p.streak_freeze_count


def queue_leaderboard_sponsor(user) -> bool:
    """Create a LeaderboardSponsor row unless today's 5-slot scarcity cap is
    already full. Returns False (no-op, no row created) if sold out."""
    from tgbot.models import LeaderboardSponsor
    with transaction.atomic():
        today = timezone.localdate()
        used_today = LeaderboardSponsor.objects.filter(created_at__date=today).count()
        if used_today >= LEADERBOARD_SPONSOR_DAILY_LIMIT:
            return False
        LeaderboardSponsor.objects.create(user=user)
        return True


_GOLD = (212, 175, 90)
_GOLD_LIGHT = (238, 210, 140)
_CREAM = (238, 232, 214)
_NAVY_DARK = (10, 13, 24)
_NAVY_MID = (18, 23, 40)
_MUTED = (150, 155, 175)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def generate_certificate(user) -> bytes:
    """Render a shareable, premium-styled PNG certificate with the user's key
    stats: gold-on-navy, ornamental double border with corner flourishes, a
    stat-card row, and a wax-seal-style medallion. Uses Pillow's bundled
    scalable default font (no system/TTF dependency — Pillow >= 10.1's
    ImageFont.load_default(size=...)).

    Square canvas (1:1) is deliberate: users set this as their Telegram
    profile photo, and Telegram center-crops any non-square image to a
    square for the circular avatar -- a landscape certificate (the old
    1400x900) lost its outer stat cards to that crop. Square means nothing
    ever needs to be cropped."""
    from PIL import Image, ImageDraw, ImageFont
    from tgbot.services.achievements import compute_user_stats
    import os as _os

    stats = compute_user_stats(user)
    full_name = user.full_name or "Kitobxon"

    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), _NAVY_DARK)
    draw = ImageDraw.Draw(img, "RGBA")

    # Vertical gradient background (subtle — lighter in the middle band).
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)], fill=_lerp(_NAVY_DARK, _NAVY_MID, (0.5 - abs(t - 0.5)) * 2))

    # Ornamental double border, rounded, with a small gold diamond at each corner.
    margin = 36
    draw.rounded_rectangle([margin, margin, W - margin, H - margin], radius=22, outline=_GOLD, width=4)
    margin2 = margin + 14
    draw.rounded_rectangle([margin2, margin2, W - margin2, H - margin2], radius=14, outline=_GOLD, width=1)

    def diamond(cx, cy, size, color=_GOLD):
        draw.polygon([(cx, cy - size), (cx + size, cy), (cx, cy + size), (cx - size, cy)], fill=color)

    for cx_, cy_ in [(margin, margin), (W - margin, margin), (margin, H - margin), (W - margin, H - margin)]:
        diamond(cx_, cy_, 10)

    title_font = ImageFont.load_default(size=30)
    script_font = ImageFont.load_default(size=64)
    name_font = ImageFont.load_default(size=50)
    label_font = ImageFont.load_default(size=20)
    num_font = ImageFont.load_default(size=44)
    small_font = ImageFont.load_default(size=20)
    tiny_font = ImageFont.load_default(size=16)
    seal_font = ImageFont.load_default(size=40)

    def center_text(y, text, font, fill=_CREAM):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((W - w) / 2, y), text, font=font, fill=fill)
        return w

    def center_text_spaced(y, text, font, fill, letter_spacing=8):
        widths = [draw.textbbox((0, 0), ch, font=font)[2] for ch in text]
        total = sum(widths) + letter_spacing * (len(text) - 1)
        x = (W - total) / 2
        for ch, wch in zip(text, widths):
            draw.text((x, y), ch, font=font, fill=fill)
            x += wch + letter_spacing

    # Header ornament: line – diamond – line.
    top_y = 100
    diamond(W // 2, top_y, 7)
    draw.line([(W // 2 - 160, top_y), (W // 2 - 20, top_y)], fill=_GOLD, width=2)
    draw.line([(W // 2 + 20, top_y), (W // 2 + 160, top_y)], fill=_GOLD, width=2)

    center_text_spaced(130, "KITOB CHALLENGE", title_font, _GOLD)

    title = "SERTIFIKAT"
    bbox = draw.textbbox((0, 0), title, font=script_font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) / 2 + 3, 183), title, font=script_font, fill=(0, 0, 0, 90))  # soft shadow
    draw.text(((W - tw) / 2, 180), title, font=script_font, fill=_CREAM)

    draw.line([(W // 2 - 220, 270), (W // 2 + 220, 270)], fill=_GOLD, width=2)

    center_text(305, "Ushbu sertifikat quyidagi kitobxonga taqdim etiladi:", label_font, _MUTED)

    name_y = 350
    name_w = center_text(name_y, full_name, name_font, _GOLD_LIGHT)
    uy = name_y + 68
    draw.line([(W // 2 - name_w / 2 - 30, uy), (W // 2 + name_w / 2 + 30, uy)], fill=_GOLD, width=2)
    diamond(W // 2 - name_w / 2 - 40, uy, 5)
    diamond(W // 2 + name_w / 2 + 40, uy, 5)

    # Stat-card row.
    stat_items = [
        (str(stats["pages"]), "BET O'QILDI"),
        (str(stats["books_finished"]), "KITOB TUGALLANDI"),
        (str(stats["max_streak"]), "KUNLIK STREAK"),
        (str(stats["referrals"]), "TAKLIF QILINGAN"),
    ]
    n = len(stat_items)
    card_y0, card_y1 = 470, 620
    pad_outer = 90
    col_w = (W - 2 * pad_outer) / n
    for i, (num, label) in enumerate(stat_items):
        cx_ = pad_outer + col_w * i + col_w / 2
        if i > 0:
            draw.line(
                [(pad_outer + col_w * i, card_y0 + 10), (pad_outer + col_w * i, card_y1 - 10)],
                fill=(*_GOLD, 90), width=1,
            )
        num_w = draw.textbbox((0, 0), num, font=num_font)[2]
        draw.text((cx_ - num_w / 2, card_y0), num, font=num_font, fill=_GOLD_LIGHT)
        lbl_w = draw.textbbox((0, 0), label, font=small_font)[2]
        draw.text((cx_ - lbl_w / 2, card_y0 + 70), label, font=small_font, fill=_MUTED)

    # Bot link + growth hook, right-aligned in the gap between the stat row
    # and the seal (avoids the seal's ellipse/ribbon footprint below it).
    bot_username = _os.environ.get("BOT_USERNAME", "kitob_challange_bot")
    link_text = f"t.me/{bot_username}"
    hook_text = "2 000 000+ o'qilgan betlar"
    right_edge = W - margin2 - 30
    lw = draw.textbbox((0, 0), link_text, font=small_font)[2]
    draw.text((right_edge - lw, 690), link_text, font=small_font, fill=_CREAM)
    hw = draw.textbbox((0, 0), hook_text, font=tiny_font)[2]
    draw.text((right_edge - hw, 722), hook_text, font=tiny_font, fill=_GOLD_LIGHT)

    # Seal / medallion, bottom-right.
    seal_cx, seal_cy, seal_r = W - 210, H - 155, 55
    draw.ellipse([seal_cx - seal_r, seal_cy - seal_r, seal_cx + seal_r, seal_cy + seal_r], outline=_GOLD, width=3)
    draw.ellipse(
        [seal_cx - seal_r + 10, seal_cy - seal_r + 10, seal_cx + seal_r - 10, seal_cy + seal_r - 10],
        outline=_GOLD, width=1,
    )
    bbox = draw.textbbox((0, 0), "K", font=seal_font)
    sw, sh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((seal_cx - sw / 2, seal_cy - sh / 2 - bbox[1]), "K", font=seal_font, fill=_GOLD)
    draw.polygon(
        [(seal_cx - 30, seal_cy + seal_r - 5), (seal_cx - 10, seal_cy + seal_r + 40), (seal_cx - 2, seal_cy + seal_r + 10)],
        fill=_GOLD,
    )
    draw.polygon(
        [(seal_cx + 30, seal_cy + seal_r - 5), (seal_cx + 10, seal_cy + seal_r + 40), (seal_cx + 2, seal_cy + seal_r + 10)],
        fill=_GOLD,
    )

    draw.text((margin2 + 30, H - 175), "KITOB CHALLENGE", font=tiny_font, fill=_MUTED)
    draw.text((margin2 + 30, H - 150), "Rasmiy Sertifikat", font=small_font, fill=_CREAM)
    draw.text(
        (margin2 + 30, H - 100),
        f"Sana: {timezone.localdate().strftime('%d.%m.%Y')}",
        font=tiny_font, fill=_MUTED,
    )

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
