"""One-off announcement for Game Speed Ranking, Shop scrolling fix, and 3D Page Curl."""
import json
import time as _time
import requests
from tgbot.models import TelegramProfile
from tgbot.tasks import BOT_TOKEN, _announce_targets, _get_bot_username


def broadcast_update_announcement():
    bot_username = _get_bot_username() or "kitob_challange_bot"
    bot_url = f"https://t.me/{bot_username}"

    text_uz = (
        "🎉 <b>Kitob Challenge'da ajoyib yangilanishlar!</b>\n\n"
        "Hurmatli kitobxonlar, platformamizni siz uchun yanada qulay va qiziqarli qilishda davom etamiz:\n\n"
        "⚡️ <b>O'yinlarda adolatliroq bellashuv:</b>\n"
        "Endi jonli o'yinlar va viktorinalarda nafaqat to'g'ri javob, balki <b>javob berish tezligi</b> ham hisobga olinadi! Kim tezroq va aniqroq javob bersa, peshqadamlar jadvalida yuqoriroq o'rinni egallaydi.\n\n"
        "📖 <b>Kitob o'qish yanada yoqimli:</b>\n"
        "Kutubxonamizdagi kitoblarni mutolaa qilishda haqiqiy kitob varag'idek buklanib ochiluvchi yangi <b>3D varoqlash animatsiyasi</b> qo'shildi. Endi o'qish yanada jonli va estetik!\n\n"
        "🛍 <b>Do'konimiz yanada qulay:</b>\n"
        "Do'kon (Shop) bo'limi optimallashtirildi — mahsulotlarni ko'rish va sahifani surishdagi barcha qotishlar to'liq bartaraf etildi.\n\n"
        "🚀 <i>Hoziroq botga kiring va yangilanishlarni sinab ko'ring!</i>"
    )

    text_ru = (
        "🎉 <b>Отличные обновления в Kitob Challenge!</b>\n\n"
        "Дорогие читатели, мы продолжаем делать платформу ещё удобнее и интереснее:\n\n"
        "⚡️ <b>Справедливые соревнования в играх:</b>\n"
        "Теперь в викторинах и живых играх учитывается не только правильность, но и <b>скорость ответов</b>! Кто отвечает быстрее и точнее, поднимается выше в таблице лидеров.\n\n"
        "📖 <b>Чтение книг стало ещё приятнее:</b>\n"
        "При чтении книг в библиотеке добавлена новая <b>3D анимация реалистичного перелистывания страниц</b>!\n\n"
        "🛍 <b>Магазин стал быстрее:</b>\n"
        "Раздел Shop оптимизирован — устранены задержки и зависания прокрутки.\n\n"
        "🚀 <i>Заходите в бот прямо сейчас и оцените новинки!</i>"
    )

    keyboard = json.dumps({"inline_keyboard": [[{
        "text": "🚀 Botga kirish / Открыть бота", "url": bot_url,
    }]]})

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    groups_sent = 0
    for group_id, thread_id in _announce_targets():
        try:
            data = {"chat_id": group_id, "text": text_uz, "parse_mode": "HTML",
                    "reply_markup": keyboard, "disable_web_page_preview": "true"}
            if thread_id:
                data["message_thread_id"] = thread_id
            resp = requests.post(url, data=data, timeout=10)
            if resp.ok:
                groups_sent += 1
        except Exception as e:
            print(f"announce group {group_id}: {e}")

    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    users_sent = 0
    for tg_id, lang in qs.values_list("telegram_id", "language").iterator():
        text = text_ru if lang == "ru" else text_uz
        try:
            resp = requests.post(
                url,
                data={"chat_id": tg_id, "text": text, "parse_mode": "HTML",
                      "reply_markup": keyboard, "disable_web_page_preview": "true"},
                timeout=5,
            )
            if resp.ok:
                users_sent += 1
            elif resp.status_code == 429:
                _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception:
            pass
        _time.sleep(0.04)

    print(f"broadcast_update_announcement: groups_sent={groups_sent} users_sent={users_sent}")
    return {"groups": groups_sent, "users": users_sent}
