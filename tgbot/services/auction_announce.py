"""One-off announcement for Shop 10-day Book Auction."""
import json
import time as _time
import requests
from tgbot.models import TelegramProfile, ShopProduct
from tgbot.tasks import BOT_TOKEN, _announce_targets, _get_bot_username


def broadcast_auction_announcement():
    bot_username = _get_bot_username() or "kitob_challange_bot"
    bot_url = f"https://t.me/{bot_username}"

    # Get active auction product info if available
    auction_prod = ShopProduct.objects.filter(is_active=True, is_auction=True).first()
    prod_name = auction_prod.name if auction_prod else "Eksklyuziv Kitob"

    text_uz = (
        "🏛 <b>KITOB CHALLENGE'DA KATTA AUKSION BOSHLANDI!</b> 🔥📚\n\n"
        "Hurmatli kitobxonlar! Do'konimizda yangi, qizg'in va hayajonli <b>Auksion formati</b> rasman ishga tushirildi!\n\n"
        f"📖 <b>10 Kunlik Auksion kitobi:</b>\n"
        f"🌟 <b>«{prod_name}»</b> kitobi uchun kimoshdi savdosi boshlandi! Har bir kitobxon to'plagan Kitobchalari bilan qatnashib, ushbu kitobni qo'lga kiritishi mumkin.\n\n"
        "🎯 <b>Qoidalar juda oddiy va qulay:</b>\n"
        "• <b>Minimal taklif:</b> kamida <b>100 Kitobcha</b> (istalgan yuqori summani qo'yishingiz mumkin).\n"
        "• <b>Top 20 Ishtirokchilar:</b> Do'konda kim eng ko'p taklif qilgani va o'z o'rningizni jonli kuzatib borasiz.\n"
        "• <b>100% Xavfsiz (Kafolatlangan Refund):</b> Agar siz #1 g'olib bo'la olmasangiz — auksion yakunida tikkan <b>barcha Kitobchalaringiz to'liq balansingizga qaytariladi!</b>\n\n"
        "⏳ <b>Muddat:</b> Auksion 10 kun davom etadi. Taymer allaqachon ketmoqda!\n\n"
        "👇 <i>Hoziroq «Do'kon»ga kiring, o'z taklifingizni bering va yetakchiga aylaning!</i>"
    )

    text_ru = (
        "🏛 <b>В KITOB CHALLENGE СТАРТОВАЛ БОЛЬШОЙ АУКЦИОН!</b> 🔥📚\n\n"
        "Дорогие читатели! В нашем магазине официально запущен новый, захватывающий <b>формат Аукциона</b>!\n\n"
        f"📖 <b>Книга 10-дневного аукциона:</b>\n"
        f"🌟 Стартовали торги за книгу <b>«{prod_name}»</b>! Каждый участник может сделать ставку своими накопленными Китобча.\n\n"
        "🎯 <b>Простые и безопасные правила:</b>\n"
        "• <b>Минимальная ставка:</b> от <b>100 Китобча</b> (можно указать любую сумму выше).\n"
        "• <b>Топ-20 Лидеров:</b> в Магазине вы в реальном времени видите список лидеров и своё место.\n"
        "• <b>100% Гарантия возврата (Refund):</b> если вы не займете 1-е место — <b>все ваши ставки вернутся на ваш баланс в полном объёме!</b>\n\n"
        "⏳ <b>Срок:</b> аукцион продлится 10 дней. Таймер уже запущен!\n\n"
        "👇 <i>Заходите в Магазин прямо сейчас и делайте свою ставку!</i>"
    )

    from src.settings import WEB_DOMAIN
    base_domain = WEB_DOMAIN if str(WEB_DOMAIN).startswith("http") else f"https://{WEB_DOMAIN}"

    # Group keyboards: use url (Telegram API does not allow web_app in groups)
    group_keyboard_uz = json.dumps({
        "inline_keyboard": [
            [
                {"text": "🏛 Auksionda qatnashish 🪙", "url": f"https://t.me/{bot_username}?start=market"},
            ],
            [
                {"text": "⚡️ Kitobcha ishlash (O'yinlar)", "url": f"https://t.me/{bot_username}?start=games"},
                {"text": "🚀 Botga kirish", "url": bot_url},
            ]
        ]
    })

    # DM keyboards: use native web_app for smooth bottom-sheet Mini App
    dm_keyboard_uz = json.dumps({
        "inline_keyboard": [
            [
                {"text": "🏛 Auksionda qatnashish 🪙", "web_app": {"url": f"{base_domain}/shop/"}},
            ],
            [
                {"text": "⚡️ Kitobcha ishlash (O'yinlar)", "web_app": {"url": f"{base_domain}/"}},
                {"text": "📚 Kutubxona", "web_app": {"url": f"{base_domain}/kutubxona/"}},
            ]
        ]
    })

    dm_keyboard_ru = json.dumps({
        "inline_keyboard": [
            [
                {"text": "🏛 Участвовать в аукционе 🪙", "web_app": {"url": f"{base_domain}/shop/"}},
            ],
            [
                {"text": "⚡️ Заработать Китобча (Игры)", "web_app": {"url": f"{base_domain}/"}},
                {"text": "📚 Библиотека", "web_app": {"url": f"{base_domain}/kutubxona/"}},
            ]
        ]
    })

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # 1. Broadcast to all target groups
    groups_sent = 0
    for group_id, thread_id in _announce_targets():
        try:
            data = {
                "chat_id": group_id,
                "text": text_uz,
                "parse_mode": "HTML",
                "reply_markup": group_keyboard_uz,
                "disable_web_page_preview": "true",
            }
            if thread_id:
                data["message_thread_id"] = thread_id
            resp = requests.post(url, data=data, timeout=10)
            if resp.ok:
                groups_sent += 1
        except Exception as e:
            print(f"announce auction group {group_id}: {e}")

    # 2. Broadcast to all users via DM
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    users_sent = 0
    for tg_id, lang in qs.values_list("telegram_id", "language").iterator():
        text = text_ru if lang == "ru" else text_uz
        kb = dm_keyboard_ru if lang == "ru" else dm_keyboard_uz
        try:
            resp = requests.post(url, data={
                "chat_id": tg_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": kb,
                "disable_web_page_preview": "true",
            }, timeout=8)
            if resp.status_code == 200:
                users_sent += 1
            elif resp.status_code == 403:
                TelegramProfile.objects.filter(telegram_id=tg_id).update(is_blocked=True)
            _time.sleep(0.04)  # Rate limiting
        except Exception:
            pass

    print(f"broadcast_auction_announcement completed: groups_sent={groups_sent}, users_sent={users_sent}")
    return {"groups_sent": groups_sent, "users_sent": users_sent}
