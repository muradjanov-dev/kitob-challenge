"""One-off make-good: the 'qz:ai' button used to be blocked by the blanket
admin-or-Premium gate, so anyone who won the Sirli quti's 1-hour AI-quiz
prize (or the daily giveaway) could never actually redeem it. Rather than
try to reconstruct who was affected from records that don't exist, this
grants the same 1-hour window to every registered user at once.

Separate module (not tasks.py) so it doesn't get bundled with whatever else
is mid-edit there -- same reasoning as mystery_box_announce.
"""

BONUS_HOURS = 1


def grant_ai_quiz_bonus_to_everyone(hours: int = BONUS_HOURS, announce: bool = True):
    import datetime as _dt
    import json
    import time as _time

    import requests
    from django.utils import timezone

    from tgbot.models import TelegramProfile
    from tgbot.tasks import BOT_TOKEN, _announce_targets, _get_bot_username

    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)

    # Everyone must get the full `hours` counted from when THEY receive the
    # DM, not from when the grant runs -- DMing tens of thousands of users
    # takes many minutes, so a flat now+hours would leave the last people
    # notified with an almost-expired window. Add the projected broadcast
    # duration as headroom (~0.15s/user observed: 0.05s pacing sleep plus
    # request latency), so even the final recipient still has a full hour.
    headroom = _dt.timedelta(seconds=qs.count() * 0.15) if announce else _dt.timedelta(0)
    until = timezone.now() + headroom + _dt.timedelta(hours=hours)

    # Bulk update on purpose: this is a uniform bonus grant to everyone, not
    # a per-user decision worth an audit row each. No per-user
    # expire_ai_quiz_trial task is scheduled either -- that task only nulls
    # the field and DMs an upsell, and scheduling one per user would flood
    # the queue. The access gate compares trial_ai_quiz_until against now,
    # so the window closes on its own regardless.
    granted = qs.update(trial_ai_quiz_until=until)
    print(f"grant_ai_quiz_bonus_to_everyone: granted={granted} until={until} headroom={headroom}")

    if not announce:
        return {"granted": granted, "until": until, "groups": 0, "users": 0}

    bot_username = _get_bot_username() or "kitob_challange_bot"
    aiquiz_url = f"https://t.me/{bot_username}?start=aiquiz"

    text_uz = (
        "🎁 <b>Hammaga sovg'a: 1 soat BEPUL AI Quiz!</b>\n\n"
        "Sirli qutidan chiqadigan 🤖 <b>AI yordamida quiz tuzish</b> imkoniyati "
        "ba'zi kitobxonlarga texnik nosozlik tufayli ochilmay qolgan edi. "
        "Kechirim so'raymiz — qarzdor bo'lib qolmaslik uchun bu imkoniyatni "
        "<b>hammaga</b> ochib qo'ydik!\n\n"
        f"⏳ Keyingi <b>{hours} soat</b> davomida — Premium bo'lmasangiz ham — "
        "AI yordamida o'z quizingizni tuzishingiz mumkin.\n\n"
        "📖 Matn, rasm yoki PDF kitob yuboring — AI o'zi savollar tuzib beradi. "
        "Tayyor quizni do'stlaringizga yoki guruhingizga ulashing!\n\n"
        "Hoziroq sinab ko'ring 👇"
    )
    text_ru = (
        "🎁 <b>Подарок всем: 1 час БЕСПЛАТНОГО AI Quiz!</b>\n\n"
        "Возможность 🤖 <b>создания квиза с помощью AI</b>, выпадающая из "
        "Таинственной коробки, из-за технической ошибки не открывалась у части "
        "читателей. Приносим извинения — чтобы не остаться в долгу, мы открыли "
        "её <b>для всех</b>!\n\n"
        f"⏳ В течение следующего <b>{hours} часа</b> — даже без Premium — вы "
        "можете создать свой квиз с помощью AI.\n\n"
        "📖 Отправьте текст, изображение или PDF-книгу — AI сам составит "
        "вопросы. Готовым квизом поделитесь с друзьями или в группе!\n\n"
        "Попробуйте прямо сейчас 👇"
    )

    keyboard = json.dumps({"inline_keyboard": [[{
        "text": "🤖 AI bilan quiz tuzish", "url": aiquiz_url,
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
            print(f"ai quiz bonus announce group {group_id}: {e}")

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
        _time.sleep(0.05)

    print(f"grant_ai_quiz_bonus_to_everyone: groups_sent={groups_sent} users_sent={users_sent}")
    return {"granted": granted, "until": until, "groups": groups_sent, "users": users_sent}
