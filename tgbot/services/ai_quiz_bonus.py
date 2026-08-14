"""One-off make-good: the 'qz:ai' button used to be blocked by the blanket
admin-or-Premium gate, so anyone who won the Sirli quti's 1-hour AI-quiz
prize (or the daily giveaway) could never actually redeem it. Rather than
try to reconstruct who was affected from records that don't exist, the same
1-hour window is granted to every registered non-Premium user -- but dripped
out in small hourly batches rather than all at once.

Separate module (not tasks.py) so it doesn't get bundled with whatever else
is mid-edit there -- same reasoning as mystery_box_announce.
"""

BONUS_HOURS = 1

# Drip pacing. The bonus goes out to a fixed number of users per hour rather
# than to everyone at once: a single mass send would both crowd the AI-quiz
# global rate limit (quiz_ai.AI_QUIZ_GLOBAL_PER_MINUTE) and land in a lot of
# pockets at 3am.
DRIP_USERS_PER_HOUR = 100

# Hours (Asia/Tashkent, see settings.TIME_ZONE) the drip is allowed to send
# in: 05:00 through 00:59. Nobody gets woken at 01:00-04:59 -- and since each
# batch's usable window starts when THEY are notified, sending at night would
# also mean sleeping through the whole gift.
DRIP_ACTIVE_HOURS = set(range(5, 24)) | {0}


def _eligible_qs():
    """Registered, reachable, and not already holding Premium.

    Premium subscribers are excluded deliberately: AI quiz creation has
    always been available to them, so the apology doesn't apply and DMing
    them an irrelevant "now it's open to you too" would be noise.
    """
    from django.utils import timezone
    from tgbot.models import TelegramProfile

    return (
        TelegramProfile.objects
        .filter(is_registered=True, is_blocked=False)
        .exclude(payments__status="paid", payments__end_date__gte=timezone.localdate())
        .distinct()
    )


def _build_texts(hours: int):
    text_uz = (
        "🎁 <b>Sizga sovg'a: 1 soat BEPUL AI Quiz!</b>\n\n"
        "Sirli qutidan chiqadigan 🤖 <b>AI yordamida quiz tuzish</b> imkoniyati "
        "ba'zi kitobxonlarga texnik nosozlik tufayli ochilmay qolgan edi. "
        "Kechirim so'raymiz — qarzdor bo'lib qolmaslik uchun bu imkoniyatni "
        "sizga ham ochib qo'ydik!\n\n"
        f"⏳ Keyingi <b>{hours} soat</b> davomida — Premium bo'lmasangiz ham — "
        "AI yordamida o'z quizingizni tuzishingiz mumkin.\n\n"
        "📖 Matn, rasm yoki PDF kitob yuboring — AI o'zi savollar tuzib beradi. "
        "Tayyor quizni do'stlaringizga yoki guruhingizga ulashing!\n\n"
        "Hoziroq sinab ko'ring 👇"
    )
    text_ru = (
        "🎁 <b>Вам подарок: 1 час БЕСПЛАТНОГО AI Quiz!</b>\n\n"
        "Возможность 🤖 <b>создания квиза с помощью AI</b>, выпадающая из "
        "Таинственной коробки, из-за технической ошибки не открывалась у части "
        "читателей. Приносим извинения — чтобы не остаться в долгу, мы открыли "
        "её и для вас!\n\n"
        f"⏳ В течение следующего <b>{hours} часа</b> — даже без Premium — вы "
        "можете создать свой квиз с помощью AI.\n\n"
        "📖 Отправьте текст, изображение или PDF-книгу — AI сам составит "
        "вопросы. Готовым квизом поделитесь с друзьями или в группе!\n\n"
        "Попробуйте прямо сейчас 👇"
    )
    return text_uz, text_ru


def drip_ai_quiz_bonus(limit: int = DRIP_USERS_PER_HOUR, hours: int = BONUS_HOURS,
                       force: bool = False):
    """Send the bonus to the next `limit` users who haven't had it yet.

    Intended to run hourly from celery beat. Outside DRIP_ACTIVE_HOURS it
    does nothing (pass force=True to override, e.g. for a manual test).
    """
    import datetime as _dt
    import json
    import time as _time

    import requests
    from django.utils import timezone

    from tgbot.models import TelegramProfile
    from tgbot.tasks import BOT_TOKEN, _get_bot_username

    local_hour = timezone.localtime().hour
    if not force and local_hour not in DRIP_ACTIVE_HOURS:
        print(f"drip_ai_quiz_bonus: hour {local_hour} outside active window, skipping")
        return {"skipped": "outside_active_hours", "hour": local_hour}

    batch = list(
        _eligible_qs()
        .filter(ai_quiz_bonus_sent_at__isnull=True)
        .values_list("id", "telegram_id", "language")[:limit]
    )
    if not batch:
        print("drip_ai_quiz_bonus: nobody left to send to")
        return {"sent": 0, "remaining": 0, "done": True}

    # Each batch gets its own fresh window, counted from when THIS batch is
    # notified -- so every user gets the full `hours` no matter how far into
    # the campaign they are. Headroom covers this batch's own send duration
    # (~0.15s/user: 0.05s pacing sleep plus request latency).
    headroom = _dt.timedelta(seconds=len(batch) * 0.15)
    until = timezone.now() + headroom + _dt.timedelta(hours=hours)
    TelegramProfile.objects.filter(id__in=[b[0] for b in batch]).update(
        trial_ai_quiz_until=until,
    )

    bot_username = _get_bot_username() or "kitob_challange_bot"
    keyboard = json.dumps({"inline_keyboard": [[{
        "text": "🤖 AI bilan quiz tuzish",
        "url": f"https://t.me/{bot_username}?start=aiquiz",
    }]]})
    text_uz, text_ru = _build_texts(hours)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    sent = 0
    for uid, tg_id, lang in batch:
        text = text_ru if lang == "ru" else text_uz
        try:
            resp = requests.post(
                url,
                data={"chat_id": tg_id, "text": text, "parse_mode": "HTML",
                      "reply_markup": keyboard, "disable_web_page_preview": "true"},
                timeout=5,
            )
            if resp.ok:
                sent += 1
            elif resp.status_code == 429:
                _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception:
            pass
        # Marked whether or not the send succeeded: a permanently unreachable
        # user (blocked the bot, deleted account) must not be re-picked every
        # hour forever, which would stall the queue behind them.
        TelegramProfile.objects.filter(id=uid).update(ai_quiz_bonus_sent_at=timezone.now())
        _time.sleep(0.05)

    remaining = _eligible_qs().filter(ai_quiz_bonus_sent_at__isnull=True).count()
    print(f"drip_ai_quiz_bonus: sent={sent}/{len(batch)} remaining={remaining} until={until}")
    return {"sent": sent, "batch": len(batch), "remaining": remaining, "until": until}


def drip_status():
    """Progress snapshot for the campaign — used by the status endpoint."""
    from django.utils import timezone

    eligible = _eligible_qs()
    total = eligible.count()
    remaining = eligible.filter(ai_quiz_bonus_sent_at__isnull=True).count()
    hours_left = (remaining / DRIP_USERS_PER_HOUR) if DRIP_USERS_PER_HOUR else 0
    active_hours_per_day = len(DRIP_ACTIVE_HOURS)
    return {
        "eligible_total": total,
        "already_sent": total - remaining,
        "remaining": remaining,
        "per_hour": DRIP_USERS_PER_HOUR,
        "active_hours": sorted(DRIP_ACTIVE_HOURS),
        "current_hour_tashkent": timezone.localtime().hour,
        "sending_now": timezone.localtime().hour in DRIP_ACTIVE_HOURS,
        "est_sending_hours_left": round(hours_left, 1),
        "est_days_left": round(hours_left / active_hours_per_day, 1) if active_hours_per_day else None,
    }
