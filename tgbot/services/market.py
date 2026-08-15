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
    ("letter_navoiy", 5),
    ("letter_rumiy", 5),
    ("letter_tolstoy", 4),
    ("letter_bobur", 4),
    ("letter_gazzoliy", 4),
    ("literary_oracle", 6),
    ("magic_audio_quote", 5),
    ("virtual_coffee_break", 5),
    ("secret_key_box", 4),
    ("magic_answer_aid", 4),
    ("quote_wall_post", 3),
    ("friend_gift_premium", 4),
    ("friend_gift_ticket", 5),
    ("aura_gold_reader", 4),
    ("wisdom_chest_key", 3),
    ("title_night_thief", 5),
    ("title_simurgh_wing", 4),
    ("title_library_sage", 4),
    ("title_logic_knight", 4),
    ("title_fast_sorcerer", 4),
    ("title_coffee_philosopher", 5),
    ("title_book_dragon", 3),
    ("title_stoic_master", 4),
    ("title_grand_detective", 4),
    ("title_royal_wordsmith", 4),
    ("title_star_navigator", 4),
    ("title_heart_mirror", 4),
    ("title_mystery_king", 2),
    ("title_legend_scholar", 2),
    ("title_infinite_reader", 3),
    ("ticket_1", 10),
    ("ticket_2", 8),
    ("ticket_3", 6),
    ("ticket_5", 3),
    ("vip_pass_1", 6),
    ("vip_pass_2", 4),
    ("vip_pass_3", 2),
    ("duel_pass", 5),
    ("king_pass", 5),
    ("simurgh_pass", 5),
    ("masnaviy_pass", 5),
    ("gazzoliy_pass", 5),
    ("strategy_pass", 5),
    ("mindtrap_pass", 5),
    ("blitz_pass", 5),
    ("premium_3h", 7),
    ("premium_6h", 6),
    ("premium_12h", 5),
    ("premium_24h", 4),
    ("premium_48h", 3),
    ("premium_3d", 2),
    ("premium_7d", 1),
    ("vip_booster_halfday", 4),
    ("vip_booster_fullday", 3),
    ("all_access_24h", 3),
    ("reading_champion_pass", 3),
    ("night_owl_premium", 5),
    ("dawn_reader_premium", 5),
    ("weekend_vip_pass", 2),
    ("grand_scholar_vip", 1),
    ("life_1", 10),
    ("life_2", 7),
    ("life_3", 5),
    ("life_4", 3),
    ("life_5", 2),
    ("shield_iron", 7),
    ("shield_gold", 3),
    ("shield_diamond", 2),
    ("shield_immortal", 1),
    ("phoenix_feather", 4),
    ("heart_emerald", 3),
    ("titan_armor", 3),
    ("freeze_1", 10),
    ("freeze_2", 6),
    ("freeze_3", 4),
    ("freeze_5", 1),
    ("ice_shield_1", 7),
    ("arctic_barrier", 3),
    ("glacier_armor", 2),
    ("eternal_frost", 1),
    ("streak_guardian_1", 6),
    ("streak_guardian_2", 4),
    ("streak_safezone", 3),
    ("habit_preserver", 4),
    ("ai_1h", 8),
    ("ai_2h", 6),
    ("ai_3h", 5),
    ("ai_6h", 3),
    ("ai_12h", 2),
    ("ai_24h", 1),
    ("ai_critic_pass", 5),
    ("ai_book_architect", 4),
    ("ai_exam_creator", 3),
    ("ai_omnipotent", 1),
    ("discount_20", 7),
    ("discount_30", 5),
    ("discount_50", 3),
    ("discount_70", 1),
    ("discount_80", 1),
    ("refund_box", 5),
    ("cert_personal", 6),
    ("cert_gold", 4),
    ("sponsor_slot", 4),
    ("day_hero_pass", 3),
    ("grand_jackpot", 1),
]

CREATIVE_TANGIBLE_REWARDS = {
    "letter_navoiy": ("💌 Alisher Navoiyning sizga atalgan maxsus ma'naviy maktubi va duosi! (+150 🪙)", 'creative_letter', 'navoiy'),
    "letter_rumiy": ('🪈 Mavlono Rumiyning qalbni yorituvchi shaxsiy visol maktubi! (+150 🪙)', 'creative_letter', 'rumiy'),
    "letter_tolstoy": ("📜 Lev Tolstoyning hayotiy hikmat to'la shaxsiy xati! (+150 🪙)", 'creative_letter', 'tolstoy'),
    "letter_bobur": ('👑 Zahiriddin Muhammad Boburning shohona sadoqat maktubi! (+180 🪙)', 'creative_letter', 'bobur'),
    "letter_gazzoliy": ("🗝 Imom G'azzoliyning Qalb tabobati va saodat o'giti! (+200 🪙)", 'creative_letter', 'gazzoliy'),
    "literary_oracle": ('🔮 Adabiy Bashorat: Bugungi kuningiz uchun klassik asardan maxsus taqdir satri!', 'oracle', 1),
    "magic_audio_quote": ("🎧 Oltin Audio: Buyuk asardan eng ta'sirli monologning jonli ovozli ijrosi!", 'audio_gift', 1),
    "virtual_coffee_break": ("☕️ Virtual Qahva & Mutolaa: 24 soat davomida o'qishda 2X BALL MULTIPLIER!", 'read_2x', 24),
    "secret_key_box": ('🔑 Sirli Qutining Oltin Kaliti: Keyingi qutini 100% BEPUL ochish huquqi!', 'free_box', 1),
    "magic_answer_aid": ("✨ Jonli O'yindagi Sehrli Qutqaruvchi: 1 ta xato javobni to'g'rilovchi yordamchi!", 'game_aid', 1),
    "quote_wall_post": ("📣 Guruhda Siz Tanlagan Iqtibosni Butun Jamiyatga Tantanali E'lon Qilish!", 'broadcast_quote', 1),
    "friend_gift_premium": ("🎁 Do'stingizga 24 Soatlik BEPUL Premium Sovg'a Qilish Kuponi!", 'gift_pass', 1),
    "friend_gift_ticket": ("🎟 Do'stingizga Jonli O'yin Biletini Hadya Qilish Chiptasi!", 'gift_ticket', 1),
    "aura_gold_reader": ('✨ Profilingiz Uchun 24 Soatlik «Oltin Kitobxon Aulasi» Nuri!', 'aura', 24),
    "wisdom_chest_key": ("🗝 Donishmandlik Sandig'i Kaliti: +300 Kitobcha va Faxriy E'tirof!", 'ball_direct', 300),
    "title_night_thief": ("🌙 «Tungi Kitob O'g'risi» — Tunda mutolaa qiluvchi afsonaviy kitobxon unvoni!", 'badge', "🌙 Tungi Kitob O'g'risi"),
    "title_simurgh_wing": ("🦅 «Simurg' Qanoti» — Yuksak ma'rifat sohibi faxriy unvoni!", 'badge', "🦅 Simurg' Qanoti"),
    "title_library_sage": ('🧙\u200d♂️ «Kutubxona Donishmandi» — 1000 kitob sirini biluvchi orif!', 'badge', '🧙\u200d♂️ Kutubxona Donishmandi'),
    "title_logic_knight": ('⚔️ «Mantiq Ritsari» — Bahslarda tengsiz tafakkur egasi unvoni!', 'badge', '⚔️ Mantiq Ritsari'),
    "title_fast_sorcerer": ("⚡️ «Tezkor Mutolaa Afsungari» — Varaqlarni shamoldek o'quvchi unvoni!", 'badge', '⚡️ Tezkor Mutolaa Afsungari'),
    "title_coffee_philosopher": ("☕️ «Qahvaxon Faylasuf» — Har bir sahifadan ma'no teruvchi donishmand!", 'badge', '☕️ Qahvaxon Faylasuf'),
    "title_book_dragon": ('🐉 «Kitoblar Ajdahosi» — Mutolaa ummonining buyuk posboni!', 'badge', '🐉 Kitoblar Ajdahosi'),
    "title_stoic_master": ('🧘\u200d♂️ «Ongli Hayot Ustasi» — Nafsini jilovlagan xotirjam qalb unvoni!', 'badge', '🧘\u200d♂️ Ongli Hayot Ustasi'),
    "title_grand_detective": ('🔎 «Oliy Adabiy Detektiv» — Eng chuqur sirlarni bir zumda topuvchi!', 'badge', '🔎 Oliy Adabiy Detektiv'),
    "title_royal_wordsmith": ("✍️ «Shohona So'z Ustasi» — Go'zal baytlar va nazm bilimdoni!", 'badge', "✍️ Shohona So'z Ustasi"),
    "title_star_navigator": ("🔭 «Yulduzlar Sayyohi» — Farg'oniy va Beruniy izdoshi unvoni!", 'badge', '🔭 Yulduzlar Sayyohi'),
    "title_heart_mirror": ("🪞 «Qalb Sayqallovchisi» — Pokiza va go'zal axloq sohibi!", 'badge', '🪞 Qalb Sayqallovchisi'),
    "title_mystery_king": ('👑 «Sirli Quti Qiroli» — Omad va xazinalar sohibi unvoni!', 'badge', '👑 Sirli Quti Qiroli'),
    "title_legend_scholar": ('🕌 «Buyuk Sharq Allomasi» — Ilm va hikmat faxri!', 'badge', '🕌 Buyuk Sharq Allomasi'),
    "title_infinite_reader": ("♾ «Cheksiz Kitobxon» — Mutolaasi hech qachon to'xtamaydigan qahramon!", 'badge', '♾ Cheksiz Kitobxon'),
    "ticket_1": ("🎟 1 ta Jonli O'yinga BEPUL Chipta", 'ticket', 1),
    "ticket_2": ("🎟🎟 2 ta Jonli O'yinga BEPUL Chipta", 'ticket', 2),
    "ticket_3": ("🎟🎟🎟 3 ta Jonli O'yinga BEPUL Chiptalar", 'ticket', 3),
    "ticket_5": ("🎟👑 5 ta Jonli O'yinga KATTA Biletlar To'plami", 'ticket', 5),
    "vip_pass_1": ("👑 1 ta VIP Premium Arena O'yiniga Oltin Bilet", 'ticket', 1),
    "vip_pass_2": ("👑👑 2 ta VIP Premium Arena O'yiniga Oltin Biletlar", 'ticket', 2),
    "vip_pass_3": ("👑👑👑 3 ta VIP Premium Arena O'yiniga Oltin Biletlar", 'ticket', 3),
    "duel_pass": ('🤺 1v1 Jonli Duel Bepul Kirish Chiptasi', 'ticket', 1),
    "king_pass": ("👑 Qirol Taxti O'yiniga Bepul Oltin Chipta", 'ticket', 1),
    "simurgh_pass": ("🕊 Simurg' Parvozi O'yiniga Bepul Chipta", 'ticket', 1),
    "masnaviy_pass": ("🪈 Nay Nidosi O'yiniga Bepul Chipta", 'ticket', 1),
    "gazzoliy_pass": ("🗝 Kimyoi Saodat O'yiniga Bepul Chipta", 'ticket', 1),
    "strategy_pass": ("♟ Strategik Tafakkur O'yiniga Bepul Chipta", 'ticket', 1),
    "mindtrap_pass": ("🧠 Fikr Tuzog'i O'yiniga Bepul Chipta", 'ticket', 1),
    "blitz_pass": ("⚡️ Blitz 60 O'yiniga Bepul Chipta", 'ticket', 1),
    "premium_3h": ('💎 3 Soatlik BEPUL Premium Obuna', 'premium_hours', 3),
    "premium_6h": ('💎 6 Soatlik BEPUL Premium Obuna', 'premium_hours', 6),
    "premium_12h": ('💎 12 Soatlik BEPUL Premium Obuna', 'premium_hours', 12),
    "premium_24h": ("💎👑 24 SOATLIK (1 KUNLIK) TO'LIQ BEPUL PREMIUM!", 'premium_days', 1),
    "premium_48h": ("💎👑🔥 48 SOATLIK (2 KUNLIK) TO'LIQ BEPUL PREMIUM!", 'premium_days', 2),
    "premium_3d": ('💎⭐️ 3 KUNLIK OLTIN VIP PREMIUM OBUNA!', 'premium_days', 3),
    "premium_7d": ('💎👑🏆 7 KUNLIK (1 HAFTALIK) GRAND VIP PREMIUM!', 'premium_days', 7),
    "vip_booster_halfday": ("⚡️ 12 soatlik 2X Ko'paytirgich va VIP Kirish", 'premium_hours', 12),
    "vip_booster_fullday": ("⚡️👑 24 soatlik 2X Ko'paytirgich va VIP Kirish", 'premium_days', 1),
    "all_access_24h": ("🔓 24 Soatlik Barcha Bo'limlarga Cheksiz Ruxsat", 'premium_days', 1),
    "reading_champion_pass": ('📖 1 Kunlik «Chempion Kitobxon» VIP Statusi', 'premium_days', 1),
    "night_owl_premium": ('🦉 Tungi Mutolaa uchun 6 Soatlik VIP Premium', 'premium_hours', 6),
    "dawn_reader_premium": ('🌅 Tonggi Mutolaa uchun 6 Soatlik VIP Premium', 'premium_hours', 6),
    "weekend_vip_pass": ('🎉 Dam Olish Kunlari Uchun 2 Kunlik VIP Premium', 'premium_days', 2),
    "grand_scholar_vip": ('🕌 «Sharq Allomasi» 3 Kunlik VIP Faxriy Statusi', 'premium_days', 3),
    "life_1": ("❤️ Keyingi Omon qolish o'yiniga +1 QO'SHIMCHA JON", 'survival', 1),
    "life_2": ("💖 Keyingi Omon qolish o'yiniga +2 QO'SHIMCHA JON", 'survival', 2),
    "life_3": ("🛡❤️ Keyingi Omon qolish o'yiniga +3 TA JON (Super Omon)", 'survival', 3),
    "life_4": ("🛡🛡 Keyingi Omon qolish o'yiniga +4 TA SUPER BRONYA JONI", 'survival', 4),
    "life_5": ('🛡❤️🔥 +5 TA AFSONAVIY OMON QOLISH JONLARI!', 'survival', 5),
    "shield_iron": ('🛡 Temir Qalqon: Omon qolish uchun +1 Jon', 'survival', 1),
    "shield_gold": ('🛡 Oltin Qalqon: Omon qolish uchun +3 Jon', 'survival', 3),
    "shield_diamond": ('💎 Olmos Qalqon: Omon qolish uchun +4 Jon', 'survival', 4),
    "shield_immortal": ('👑 Boqiy Qalqon: Omon qolish uchun +5 Super Jon!', 'survival', 5),
    "phoenix_feather": ("🪶 Qaqnus Pati: Mag'lubiyatdan qutqaruvchi +2 Jon", 'survival', 2),
    "heart_emerald": ('💚 Zumrad Yurak: +3 Omon qolish joni', 'survival', 3),
    "titan_armor": ('⚔️ Titan Zirhi: +3 Omon qolish joni', 'survival', 3),
    "freeze_1": ("❄️ 1 ta Streak Muzlatish Tokeni (Kitob o'qiy olmasangiz ham streak uzilmaydi)", 'freeze', 1),
    "freeze_2": ('❄️❄️ 2 ta Streak Muzlatish Tokeni', 'freeze', 2),
    "freeze_3": ('❄️❄️❄️ 3 ta Streak Muzlatish Qalqoni', 'freeze', 3),
    "freeze_5": ('🏔👑 5 TA AFSONAVIY STREAK MUZLATISH QALQONI!', 'freeze', 5),
    "ice_shield_1": ('🧊 Muz Qoplami: 1 ta Streak Muzlatish', 'freeze', 1),
    "arctic_barrier": ("❄️ Arktika To'sig'i: 3 ta Streak Muzlatish", 'freeze', 3),
    "glacier_armor": ("🏔 Muzlik Qopqog'i: 4 ta Streak Muzlatish", 'freeze', 4),
    "eternal_frost": ('❄️👑 Abadiy Qirov: 5 ta Streak Muzlatish!', 'freeze', 5),
    "streak_guardian_1": ('🛡 Streak Posboni: 1 ta Muzlatish', 'freeze', 1),
    "streak_guardian_2": ('🛡🛡 Ikki Qavatli Posbon: 2 ta Muzlatish', 'freeze', 2),
    "streak_safezone": ('🏰 Xavfsiz Hudud: 3 ta Muzlatish', 'freeze', 3),
    "habit_preserver": ('⏳ Odatni Saqlovchi: 2 ta Muzlatish Tokeni', 'freeze', 2),
    "ai_1h": ('🤖 1 Soatlik BEPUL AI Quiz Tuzish Imkoniyati', 'ai_quiz', 1),
    "ai_2h": ('🤖 2 Soatlik BEPUL AI Quiz Tuzish Imkoniyati', 'ai_quiz', 2),
    "ai_3h": ('🤖 3 Soatlik BEPUL AI Quiz Tuzish Imkoniyati', 'ai_quiz', 3),
    "ai_6h": ('🤖🔥 6 Soatlik Kengaytirilgan AI Quiz Passi', 'ai_quiz', 6),
    "ai_12h": ('🤖✨ 12 Soatlik Cheksiz AI Quiz Yaratish!', 'ai_quiz', 12),
    "ai_24h": ("🤖👑 24 SOATLIK (1 KUNLIK) TO'LIQ AI QUIZ MASTER PASS!", 'ai_quiz', 24),
    "ai_critic_pass": ('🧠 AI Adabiy Tahlilchi va Quiz Yaratuvchi (2 Soat)', 'ai_quiz', 2),
    "ai_book_architect": ('📚 AI Kitob Arxitektori Passi (3 Soat)', 'ai_quiz', 3),
    "ai_exam_creator": ('📝 AI Sinov va Test Yaratuvchi Passi (4 Soat)', 'ai_quiz', 4),
    "ai_omnipotent": ('⚡️👑 Cheksiz AI Imkoniyatlari Passi (12 Soat)', 'ai_quiz', 12),
    "discount_20": ('🏷 Keyingi Market xaridingizga 20% Chegirma', 'discount', 20),
    "discount_30": ('🏷 Keyingi Market xaridingizga 30% Chegirma', 'discount', 30),
    "discount_50": ('🏷🔥 KATTA CHEGIRMA! Keyingi xaridga 50% Chegirma!', 'discount', 50),
    "discount_70": ('🏷🔥👑 70% ULKAN MARKET CHEGIRMASI!', 'discount', 70),
    "discount_80": ('🏷🌋 80% GRAND CHEGIRMA KUPONI!', 'discount', 80),
    "refund_box": ("🔁 Qutining to'liq narxi qaytarildi (Bepul aylanish)", 'refund', 200),
    "cert_personal": ('📜 Sizga BEPUL Shaxsiy Kitobxonlik Sertifikati tushdi!', 'certificate', 1),
    "cert_gold": ('📜👑 VIP OLTIN Rangli Shaxsiy Sertifikat yutdingiz!', 'certificate', 1),
    "sponsor_slot": ("🏷 Guruhdagi «Top Kitobxonlar» e'loniga Bepul Sponsorlik O'rni!", 'sponsor', 1),
    "day_hero_pass": ("🌟 Guruh E'lonlarida «Kun Qahramoni» bo'lish imkoniyati!", 'hero', 1),
    "grand_jackpot": ('🌋👑 BUYUK GRAND JEKPOT: +2500 Kitobcha!', 'ball_direct', 2500),
}


def resolve_mystery_box(user):
    """Apply an immediate random prize (creative letters, titles/badges, game buffs,
    tickets, shields, VIP subscriptions, AI passes, certificates, or super jackpots).
    Returns (text, wants_certificate)."""
    import datetime as _dt
    from tgbot.models import TelegramProfile, KitobchaLedger, Payment, LeaderboardSponsor
    from tgbot.tasks import expire_ai_quiz_trial, expire_trial_premium

    pick = random.choices(
        [k for k, _ in MYSTERY_PRIZES],
        weights=[w for _, w in MYSTERY_PRIZES],
        k=1,
    )[0]

    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        now = timezone.now()

        if pick in CREATIVE_TANGIBLE_REWARDS:
            label, ptype, val = CREATIVE_TANGIBLE_REWARDS[pick]

            if ptype == "ticket":
                p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + val
                p.save(update_fields=["bonus_free_game_entries"])
                return f"{label}!", False

            elif ptype == "premium_hours":
                until = max(p.trial_premium_until or now, now) + _dt.timedelta(hours=val)
                p.trial_premium_until = until
                p.save(update_fields=["trial_premium_until"])
                try:
                    expire_trial_premium.apply_async(args=[p.id], countdown=val * 3600)
                except Exception:
                    pass
                return f"{label} — barcha VIP imtiyozlar va o'yinlar faollashtirildi!", False

            elif ptype == "premium_days":
                Payment.grant_or_extend(p, val, amount=0)
                until = max(p.trial_premium_until or now, now) + _dt.timedelta(days=val)
                p.trial_premium_until = until
                p.save(update_fields=["trial_premium_until"])
                return f"{label} — obunangizga +{val} kun qo'shildi!", False

            elif ptype == "survival":
                p.bonus_survival_lives = (p.bonus_survival_lives or 0) + val
                p.save(update_fields=["bonus_survival_lives"])
                return f"{label}!", False

            elif ptype == "freeze":
                p.streak_freeze_count = (p.streak_freeze_count or 0) + val
                p.save(update_fields=["streak_freeze_count"])
                return f"{label}!", False

            elif ptype == "ai_quiz":
                until = max(p.trial_ai_quiz_until or now, now) + _dt.timedelta(hours=val)
                p.trial_ai_quiz_until = until
                p.save(update_fields=["trial_ai_quiz_until"])
                try:
                    expire_ai_quiz_trial.apply_async(args=[p.id], countdown=val * 3600)
                except Exception:
                    pass
                return f"{label}!", False

            elif ptype == "discount":
                p.next_market_discount_pct = max(int(p.next_market_discount_pct or 0), val)
                p.save(update_fields=["next_market_discount_pct"])
                return f"{label}!", False

            elif ptype == "refund":
                amount = ITEMS[MYSTERY_BOX]["price"]
                p.ball = Decimal(p.ball or 0) + Decimal(amount)
                p.save(update_fields=["ball"])
                KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
                return f"🔁 Qutining to'liq narxi qaytarildi — <b>+{amount} Kitobcha</b> (Amalda bepul aylanish)!", False

            elif ptype == "certificate":
                return f"{label} — Shaxsiy sertifikatingiz tayyorlanmoqda!", True

            elif ptype == "sponsor":
                today = timezone.localdate()
                if LeaderboardSponsor.objects.filter(created_at__date=today).count() < LEADERBOARD_SPONSOR_DAILY_LIMIT:
                    LeaderboardSponsor.objects.create(user=p)
                    return f"{label} — Ismingiz keyingi e'londa chiqadi!", False
                else:
                    p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 2
                    p.save(update_fields=["bonus_free_game_entries"])
                    return "🏷 Sponsorlik bugun to'lganligi sababli o'rniga <b>2 ta BEPUL O'yin Chiptasi</b> berildi!", False

            elif ptype == "hero":
                p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 3
                p.save(update_fields=["bonus_free_game_entries"])
                return f"{label} — Shuningdek <b>+3 ta BEPUL o'yin chiptasi</b> berildi!", False

            elif ptype == "creative_letter":
                letters = {
                    "navoiy": "💌 <b>Alisher Navoiyning sizga ma'naviy maktubi:</b>\n<i>«Kelmadi jonimga rohat, ey ko'ngil, dildoridin... Ilm o'rgan, ey tolib, toki qadding xam bo'lmag'ay!»</i>\n\n✨ Sizga <b>+150 Kitobcha</b> va ma'naviy ilhom hadya qilindi!",
                    "rumiy": "🪈 <b>Mavlono Jaloliddin Rumiyning siri:</b>\n<i>«Qidirayotgan narsang ham seni qidirmoqda. Qalbingni g'uborlardan toza tut — nur albatta kiradi!»</i>\n\n✨ Sizga <b>+150 Kitobcha</b> hadya qilindi!",
                    "tolstoy": "📜 <b>Lev Tolstoyning hayotiy hikmati:</b>\n<i>«Inson baxtli bo'lish uchun emas, balki ma'noli yashash uchun tug'ilgan. Kitob — qalbning eng sodiq do'stidir.»</i>\n\n✨ Sizga <b>+150 Kitobcha</b> berildi!",
                    "bobur": "👑 <b>Zahiriddin Muhammad Boburning o'giti:</b>\n<i>«Har kimki vafo qilsa — vafo topqusidur, Har kimki jafo qilsa — jafo topqusidur...»</i>\n\n✨ Shohona xazinadan <b>+180 Kitobcha</b> berildi!",
                    "gazzoliy": "🗝 <b>Imom G'azzoliyning Saodat kimyosi:</b>\n<i>«O'z nafsini tanigan inson Parvardigorini taniydi. Dunyo foniy, ilm va yaxshilik esa boqiydir.»</i>\n\n✨ Saodat xazinasidan <b>+200 Kitobcha</b> berildi!",
                }
                amount = 150 if val not in ("bobur", "gazzoliy") else (180 if val == "bobur" else 200)
                p.ball = Decimal(p.ball or 0) + Decimal(amount)
                p.save(update_fields=["ball"])
                KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
                return letters.get(val, f"💌 Allomalar maktubi: <b>+{amount} Kitobcha</b>!"), False

            elif ptype == "oracle":
                quotes = [
                    "«Qorong'ulikni la'natlagandan ko'ra, bitta sham yoqqan afzal.» — Konfutsiy",
                    "«O'qish — aql uchun jismoniy mashq kabi zarurdir.» — Jozef Addison",
                    "«Dunyoni o'zgartirmoqchi bo'lsang, avval o'zingdan boshla.» — Lev Tolstoy",
                    "«Seni sindirmagan har qanday sinov — seni yanada kuchliroq qiladi.» — Nitsshe",
                ]
                q_txt = random.choice(quotes)
                p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 1
                p.save(update_fields=["bonus_free_game_entries"])
                return f"🔮 <b>Adabiy Bashorat:</b>\n<i>«{q_txt}»</i>\n\n🎟 Sizga <b>+1 ta BEPUL O'yin Chiptasi</b> berildi!", False

            elif ptype == "audio_gift":
                p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 2
                p.save(update_fields=["bonus_free_game_entries"])
                return "🎧 <b>Oltin Audio Parvozi:</b> <i>«O'tkan kunlar» asarining eng go'zal audio lavhasi faollashdi</i> va <b>+2 ta Bepul O'yin Chiptasi</b> berildi!", False

            elif ptype == "read_2x":
                p.streak_freeze_count = (p.streak_freeze_count or 0) + 1
                p.save(update_fields=["streak_freeze_count"])
                return "☕️ <b>Virtual Qahva & Mutolaa:</b> 24 soat davomida mutolaa ilhomi va <b>+1 ta Streak Muzlatish Qalqoni</b> berildi!", False

            elif ptype == "free_box":
                amount = ITEMS[MYSTERY_BOX]["price"]
                p.ball = Decimal(p.ball or 0) + Decimal(amount)
                p.save(update_fields=["ball"])
                KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
                return f"🔑 <b>Sirli Qutining Oltin Kaliti!</b> Quti narxi qaytarildi (+{amount} 🪙) — yana bir bor BEPUL ochishingiz mumkin!", False

            elif ptype == "game_aid":
                p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 2
                p.save(update_fields=["bonus_survival_lives"])
                return "✨ <b>Sehrli Qutqaruvchi:</b> Keyingi o'yiningiz uchun <b>+2 ta Qo'shimcha Jon</b> berildi!", False

            elif ptype == "broadcast_quote":
                p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 2
                p.save(update_fields=["bonus_free_game_entries"])
                return "📣 <b>Adabiy Ilhom:</b> Sizning nomingizdan guruhga hikmatli iqtibos yo'llanadi va <b>+2 ta Bepul Bilet</b> berildi!", False

            elif ptype == "gift_pass":
                Payment.grant_or_extend(p, 1, amount=0)
                return "🎁 <b>Do'stlik & Saxovat In'omi:</b> Sizga <b>24 soatlik BEPUL Premium</b> faollashtirildi!", False

            elif ptype == "gift_ticket":
                p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 2
                p.save(update_fields=["bonus_free_game_entries"])
                return "🎟 <b>Do'stlik Chiptasi:</b> Jonli o'yinlarga <b>2 ta BEPUL Bilet</b> taqdim etildi!", False

            elif ptype == "aura":
                Payment.grant_or_extend(p, 1, amount=0)
                return "✨👑 <b>Oltin Kitobxon Aurasi:</b> Profilingiz 24 soatlik VIP Premium maqomiga ega bo'ldi!", False

            elif ptype == "badge":
                p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 1
                p.ball = Decimal(p.ball or 0) + Decimal(100)
                p.save(update_fields=["bonus_free_game_entries", "ball"])
                KitobchaLedger.objects.create(user=p, delta=100, reason="mystery_box")
                return f"👑 <b>Yangi Faxriy Unvon:</b>\n✨ <b>{val}</b>!\n\n🎁 Profilingizda nishon faollashdi + <b>+100 Kitobcha</b> va <b>+1 ta Chipta</b> berildi!", False

            elif ptype == "ball_direct":
                p.ball = Decimal(p.ball or 0) + Decimal(val)
                p.save(update_fields=["ball"])
                KitobchaLedger.objects.create(user=p, delta=val, reason="mystery_box")
                return f"{label} (<b>+{val} Kitobcha</b>)!", False

        # Fallback default
        p.bonus_free_game_entries = (p.bonus_free_game_entries or 0) + 1
        p.save(update_fields=["bonus_free_game_entries"])
        return "🎟 Keyingi jonli o'yinga <b>1 ta BEPUL chipta</b>!", False


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
