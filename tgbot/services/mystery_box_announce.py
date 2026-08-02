"""One-off announcement: the Sirli quti (mystery box) got 33 new prizes.
Separate module (not tasks.py) so it doesn't get bundled with whatever
else is mid-edit there -- broadcasts to every active group and every
registered, non-blocked user's DM with a button into the Market.
"""


def broadcast_mystery_box_update():
    import time as _time
    import requests
    import json
    from tgbot.models import TelegramProfile
    from tgbot.tasks import BOT_TOKEN, _announce_targets, _get_bot_username

    bot_username = _get_bot_username() or "kitob_challange_bot"
    market_url = f"https://t.me/{bot_username}?start=market"

    text_uz = (
        "🎁 <b>Sirli quti — YANGILANDI!</b>\n\n"
        "Endi Sirli qutida <b>40 dan ortiq</b> xil natija bor — jumladan yangi "
        "syurprizlar:\n\n"
        "🌋 <b>ULTRA MEGA</b> Kitobcha yutuq (2000–3500)!\n"
        "🎟 Jonli o'yinlarga BEPUL biletlar\n"
        "🤖 1 soatlik BEPUL AI Quiz yaratish\n"
        "💎 3 soatlik BEPUL Premium\n"
        "🏷 Market xaridiga 20% yoki 50% chegirma\n"
        "🔁 Qutining narxi qaytariladigan bonus\n"
        "✨ 23 ta yangi, o'ziga xos nomdagi Kitobcha syurprizlari...\n\n"
        "Faqat <b>200 Kitobcha</b>ga bir marta sinab ko'ring — nima chiqishini "
        "hech kim bilmaydi! 👇"
    )
    text_ru = (
        "🎁 <b>Таинственная коробка — ОБНОВЛЕНА!</b>\n\n"
        "Теперь в Sirli quti <b>более 40</b> разных призов — включая новые "
        "сюрпризы:\n\n"
        "🌋 <b>ULTRA MEGA</b> выигрыш Kitobcha (2000–3500)!\n"
        "🎟 Бесплатные билеты на живые игры\n"
        "🤖 1 час БЕСПЛАТНОГО создания AI Quiz\n"
        "💎 3 часа БЕСПЛАТНОГО Premium\n"
        "🏷 Скидка 20% или 50% на покупку в Market\n"
        "🔁 Бонус с возвратом стоимости коробки\n"
        "✨ 23 новых именных сюрприза Kitobcha...\n\n"
        "Всего за <b>200 Kitobcha</b> попробуйте раз — никто не знает, что "
        "выпадет! 👇"
    )

    dm_keyboard = json.dumps({"inline_keyboard": [[{
        "text": "🎁 Sirli qutini ochish", "url": market_url,
    }]]})
    group_keyboard = dm_keyboard  # plain url button -- works in groups too

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    groups_sent = 0
    for group_id, thread_id in _announce_targets():
        try:
            data = {"chat_id": group_id, "text": text_uz, "parse_mode": "HTML",
                     "reply_markup": group_keyboard, "disable_web_page_preview": "true"}
            if thread_id:
                data["message_thread_id"] = thread_id
            resp = requests.post(url, data=data, timeout=10)
            if resp.ok:
                groups_sent += 1
        except Exception as e:
            print(f"mystery box announce group {group_id}: {e}")

    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    users_sent = 0
    for tg_id, lang in qs.values_list("telegram_id", "language").iterator():
        text = text_ru if lang == "ru" else text_uz
        try:
            resp = requests.post(
                url,
                data={"chat_id": tg_id, "text": text, "parse_mode": "HTML",
                      "reply_markup": dm_keyboard, "disable_web_page_preview": "true"},
                timeout=5,
            )
            if resp.ok:
                users_sent += 1
            elif resp.status_code == 429:
                _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception:
            pass
        _time.sleep(0.05)

    print(f"broadcast_mystery_box_update: groups_sent={groups_sent} users_sent={users_sent}")
    return {"groups": groups_sent, "users": users_sent}
