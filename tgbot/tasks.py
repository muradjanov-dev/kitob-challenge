import asyncio
import random
import requests
import environ
import json

from celery import shared_task

from tgbot.models import (
    DailyMessage, ConfirmationReport, TelegramProfile, ScheduledReminder,
    BotPoll, UserAchievement, ScheduledMessageDeletion,
)

from django.utils import timezone
from django.db.models import Sum, Window, F
from django.db.models.functions.window import Rank
from django.utils.html import escape


env = environ.Env()
BOT_TOKEN = env.str("API_TOKEN")


def send_notification(chat_id, text, photo=None, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if photo:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    data = {
        "chat_id": chat_id,
        "parse_mode": "HTML"
    }

    if photo:
        data["caption"] = text
        data["photo"] = photo
    else:
        data["text"] = text

    if reply_markup:
        if isinstance(reply_markup, (dict, list)):
            data['reply_markup'] = json.dumps(reply_markup)
        else:
            data['reply_markup'] = reply_markup

    try:
        response = requests.post(url, data=data)

        if response.status_code != 200:
            # Handle "can't parse entities" error by retrying without HTML
            if response.status_code == 400 and ("can't parse entities" in response.text or "Can't find end tag" in response.text):
                print(
                    f"Warning: Failed to parse entities for {chat_id}. Retrying without HTML.")
                data.pop("parse_mode", None)
                response = requests.post(url, data=data)

            if response.status_code != 200:
                print(
                    f"Failed to send notification to {chat_id}: {response.status_code}, {response.text}")

        return response.text, response.status_code

    except Exception as e:
        print(f"Error in send_notification for {chat_id}: {e}")
        return str(e), 500


@shared_task
def send_notification_with_celery(user_id, notification_message, photo=None, reply_markup=None):
    try:
        text, status = send_notification(
            user_id, notification_message, photo, reply_markup)
        return status
    except Exception as e:
        return str(e)




def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_length = 4096
    for i in range(0, len(text), max_length):
        chunk = text[i:i+max_length]

        data = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML"
        }
        response = requests.post(url, data=data)
        if response.status_code != 200:
            if response.status_code == 400 and ("chat not found" in response.text or "user is deactivated" in response.text):
                print(
                    f"Warning: Failed to send message (User unavailable): {response.status_code}, {response.text}")
            else:
                print(
                    f"Failed to send message: {response.status_code}, {response.text}")
        return response.json(), response.status_code


@shared_task
def run_total_pages():
    asyncio.run(_user_total_pages_read())


async def _user_total_pages_read():
    total_pages_by_user = ConfirmationReport.objects.aggregate(
        total_pages=Sum('pages_read')
    )

    if total_pages_by_user:
        message = f"Shu kungacha Kitob Challenge loyihasi doirasida jami {total_pages_by_user['total_pages']} bet o‘qildi! 📚✨📖\nAjoyib natija! ⚡️⚡️⚡️ Davom etamiz! 🚀"
    else:
        message = "📚 Kecha uchun kitob o'qigan foydalanuvchilar yo'q."

    chat_id = "-1002237773868"
    send_notification(chat_id, message)


@shared_task(acks_late=True)
def send_daily_message():
    today_start = timezone.now().date()
    today_end = today_start + timezone.timedelta(days=1)
    reported_user_ids = set(
        ConfirmationReport.objects.filter(
            date__range=(today_start, today_end)
        ).values_list('user_id', flat=True)
    )

    messages = list(DailyMessage.objects.values_list('message', flat=True))
    if not messages:
        return

    inactive_users = TelegramProfile.objects.exclude(
        id__in=reported_user_ids
    ).only('telegram_id')

    for user in inactive_users:
        send_notification(chat_id=user.telegram_id, text=random.choice(messages))


@shared_task
def daily_top_read_user_action_button():
    asyncio.run(_daily_top_read_user_action_button())


async def _daily_top_read_user_action_button():
    today = timezone.now().date()
    ranked_reports = ConfirmationReport.objects.filter(date__date=today).annotate(
        total_pages=Sum('pages_read'),
        rank=Window(
            expression=Rank(),
            partition_by=F('user_id'),
            order_by=F('total_pages').desc()
        )
    ).filter(rank=1).order_by('-total_pages')[:20]

    if ranked_reports:
        message = f"📚 Bugun eng ko'p kitob o'qigan 20ta Peshqadam foydalanuvchilar: \n\n"
        for index, user in enumerate(ranked_reports, start=1):
            message += f"{index}) <b><a href='tg://user?id={user.user.telegram_id}'>{escape(user.user.full_name)}</a></b>: {user.pages_read} bet 📚\n\n"
    else:
        message = "📚 Kecha uchun kitob o'qigan foydalanuvchilar yo'q."

    chat_id = "-1002237773868"
    send_message(chat_id, message)


def _send_period_report(start_date, end_date, limit, period_name):
    reports = ConfirmationReport.objects.filter(
        date__date__gte=start_date,
        date__date__lte=end_date
    ).values(
        'user__telegram_id', 'user__full_name'
    ).annotate(
        total_pages=Sum('pages_read')
    ).order_by('-total_pages')[:limit]

    reports = list(reports)
    if reports:
        message = f"📚 {period_name} eng ko'p kitob o'qigan {limit}ta Peshqadam foydalanuvchilar: \n\n"
        for index, report in enumerate(reports, start=1):
            full_name = escape(report['user__full_name'] or "Foydalanuvchi")
            tg_id = report['user__telegram_id']
            total_pages = report['total_pages']
            message += f"{index}) <b><a href='tg://user?id={tg_id}'>{full_name}</a></b>: {total_pages} bet 📚\n\n"
    else:
        message = f"📚 {period_name} uchun kitob o'qigan foydalanuvchilar yo'q."

    chat_id = "-1002237773868"
    send_message(chat_id, message)


@shared_task
def daily_top_read_user():
    today = timezone.now().date()
    _send_period_report(today, today, 20, "Bugun")


@shared_task
def three_days_top_read_user():
    end_date = timezone.now().date()
    # Today + 2 previous days = 3 days
    start_date = end_date - timezone.timedelta(days=2)
    _send_period_report(start_date, end_date, 20, "Oxirgi 3 kunda")


@shared_task
def weekly_top_read_user():
    end_date = timezone.now().date()
    # Today + 6 previous days = 7 days
    start_date = end_date - timezone.timedelta(days=6)
    _send_period_report(start_date, end_date, 30, "Bu hafta")


@shared_task
def monthly_top_read_user():
    end_date = timezone.now().date()
    start_date = end_date - timezone.timedelta(days=29)  # 30 days roughly
    _send_period_report(start_date, end_date, 30, "Bu oy")


@shared_task
def three_months_top_read_user():
    end_date = timezone.now().date()
    start_date = end_date - timezone.timedelta(days=90)
    _send_period_report(start_date, end_date, 40, "Oxirgi 3 oyda")


@shared_task
def six_months_top_read_user():
    end_date = timezone.now().date()
    start_date = end_date - timezone.timedelta(days=180)
    _send_period_report(start_date, end_date, 50, "Oxirgi 6 oyda")


@shared_task
def yearly_top_read_user():
    end_date = timezone.now().date()
    start_date = end_date - timezone.timedelta(days=365)
    _send_period_report(start_date, end_date, 60, "Bu yil")


@shared_task
def users_unread_book():
    today = timezone.localdate()
    users = TelegramProfile.objects.exclude(
        confirmationreport__date__date=today)

    if users:
        users_count = users.count()
        message = f"‼️ Bugun hisobot yubormaganlar: {users_count}ta\n\n"
        for user in users:
            if user.full_name is None:
                user.delete()
            else:
                if user.telegram_id != 631751797:
                    message += f"-@{user.username} (<b>{user.full_name}</b>)\n"

        message += "\nKuniga 5-10 daqiqa va siz yana safdasiz 🚀 \n\n *Bizdan qolib ketmysiz degan umiddamiz xurmatli do‘stlar"

        chat_id = "-1002237773868"
        send_message(chat_id, message)


def _build_top_readers_message(start_date, end_date, period_label, limit=20):
    """Top kitobxonlar (period bo'yicha) va 'Jami: X bet' bilan."""
    reports = ConfirmationReport.objects.filter(
        date__date__gte=start_date,
        date__date__lte=end_date,
    ).values(
        'user__telegram_id',
        'user__full_name',
    ).annotate(
        total_pages=Sum('pages_read')
    ).order_by('-total_pages')[:limit]

    reports = list(reports)
    if not reports:
        return None

    grand_total = sum((r['total_pages'] or 0) for r in reports)
    message = f"📚 {period_label} eng ko'p kitob o'qigan Kitobxonlar:\n\n"
    for index, report in enumerate(reports, start=1):
        full_name = escape(report['user__full_name'] or "Foydalanuvchi")
        tg_id = report['user__telegram_id']
        total_pages = report['total_pages'] or 0
        message += f"{index}. <b><a href='tg://user?id={tg_id}'>{full_name}</a></b>: {total_pages} bet 📚\n"
    message += f"\n📊 Jami: <b>{grand_total} bet</b>"
    return message


@shared_task
def weekly_report_for_general():
    """3 kunlik, 7 kunlik va 30 kunlik top kitobxonlarni umumiy kanalga yuboradi."""
    end_date = timezone.localdate()
    general_id = -1002237773868

    periods = [
        (end_date - timezone.timedelta(days=2), end_date, "Oxirgi 3 kunda"),
        (end_date - timezone.timedelta(days=6), end_date, "Oxirgi 7 kunda"),
        (end_date - timezone.timedelta(days=29), end_date, "Oxirgi 30 kunda"),
    ]

    for start_date, period_end, label in periods:
        message = _build_top_readers_message(start_date, period_end, label)
        if message is None:
            message = f"📚 {label} kitob o'qigan foydalanuvchilar yo'q."
        send_message(general_id, message)


INSPIRATION_POOL = [
    "📚 Bir bet — bir qadam. Bugungi qadamingni tashladingmi?",
    "🚀 Kitob o'qiganingni unutma — hisobotni jo'natsang, ball ham, faxr ham seniki!",
    "🔥 Mutolaa — miyangning sport zali. Bugungi mashqni yozib qoldir!",
    "⏳ Vaqt o'tadi, betlar qoladi. Bugun nechta bet o'qiding?",
    "💡 Eng zo'r investitsiya — kitob. Eng oson hisobot — bitta tugma!",
    "🌱 Har kuni bir bet — yil oxiriga 365 bet. Hisobotni unutma!",
    "📖 \"Kitob — eng sodiq do'st\" (xalq maqoli). Do'stingni bugun ziyorat qildingmi?",
    "💪 Kuchli odamlar har kuni o'qiydi. Sen ham kuchlilardansan — isbotla!",
    "🎯 Maqsad — kun bo'yi bir bet. Ortig'i bonus, kami — bahonadan boshqa narsa emas.",
    "✨ Bilim — yorug'lik. Hisobot — uni ko'rsatuvchi shamchiroq.",
    "📊 Statistikani ko'rdingmi? Senikini ham qo'shaylik!",
    "🏆 Chempionlar reytingida bo'shliq seni kutyapti — hisobot bilan to'ldir!",
    "🧠 Miya muskuldek — ishlatmasang, semiradi. Bugun mashq qildingmi?",
    "🌟 Bill Gates yiliga 50 ta kitob o'qiydi. Sen-chi?",
    "📚 Mark Tven aytgan: \"O'qimagan odam — o'qiy olmaydigan odamdan farq qilmaydi.\" Farqni ko'rsat!",
    "🔖 \"Kitob — qalbning oynasi.\" Bugun oynaga qaradingmi?",
    "🎁 Hisobot yuborgan har bir kun — kelajak senga sovg'a.",
    "⚡ 5 daqiqa vaqt + 1 tugma = bugungi hisobot tayyor!",
    "🎓 Buyuklar kitobdan tug'iladi. Bugun bir bet ham yozilmagan tarixing yo'q.",
    "💎 Bir bet o'qish — bir olmos. Kolleksiyangni boyitding-ku, qayd et!",
    "🌍 Dunyoni o'zgartirgan har bir g'oya kitobdan boshlangan. Senikini boshlaylik!",
    "🛤 Yo'l uzoq, lekin har bet — bir qadam. Bugungi qadamni yozib ket!",
    "🔋 Energiya bormi? Kitob — eng yaxshi quvvatlovchi. Hisobotni unutma!",
    "🥇 Bugun reytingda yuqoriga ko'tarilishni xohlaysanmi? Hisobot — eng tez yo'l!",
    "📝 Eslatma: hisobotsiz kun — yo'qotilgan kun. Yo'qotma!",
    "🎬 Ertangi sen bugungi mutolaadan tug'iladi. Kim bo'lishni xohlaysan?",
    "🏃‍♂️ Mutolaa — to'xtab qolmaslikning eng zo'r usuli. Yana bir bet!",
    "🌈 \"Kitob — sehrli eshik.\" Bugun qaysi olamga sayohat qilding?",
    "🧩 Har kun — bir bo'lakcha. Hisobotsiz rasm to'liq bo'lmaydi!",
    "☕ Choy + kitob = mukammal kun. Hisobot esa muhrlaydi!",
    "🎙 Hech kim seni majburlamayapti, lekin hech kim o'rningga ham o'qimaydi.",
    "🦁 Kitob o'qigan odam — qalbi sher. Bugun sher bo'l!",
    "📈 Daromadingni ikki barobarga oshirishni xohlaysanmi? Yiliga 12 ta kitob o'qi!",
    "🛡 Jaholat — eng katta dushman. Qurolib ol — kitob bilan!",
    "🌙 Tun tushdi — kitob ochildi. Ertaga hisobot bilan kunni boshla!",
    "🎈 Hisobot yubormoq — yengil, vijdoning xotirjam. Sinab ko'r!",
    "💌 Kelajakdagi senga xat: \"Bugun hisobotni jo'natdim!\" — yozib ber.",
    "🎯 Aniq maqsad: bugun bir bet. Aniq harakat: hisobot tugmasi.",
    "🔮 Bashorat: hisobot yuborgan odam — ertaga ham yuboradi. Boshlanishi shu yerda!",
    "🥷 Sukutdagi qahramon — har kuni o'qiyotgan odam. Sen ham shulardanmisan?",
    "📿 \"Tomchi-tomchi yig'ilib ko'l bo'ladi.\" Bet-bet yig'ilib — kutubxona!",
    "🚂 Mutolaa poyezdi to'xtamasdan ketyapti — chiqib qolma, hisobot ber!",
    "🪴 Bilim — daraxt. Har bet — bir suv. Suvsiz qoldirma!",
    "🦋 O'zgarish kichik harakatlardan boshlanadi. Bugungi harakat — hisobot.",
    "🧭 Yo'lingni yo'qotma — kitob ko'rsatadi. Qadamingni yoz — hisobot esda tutadi.",
    "🏔 Tog'lar bir kunda zabt etilmaydi. Lekin har kun bir qadam — albatta cho'qqida!",
    "🍀 Omad — tayyorgarlik bilan uchrashishdir. O'qib tayyor bo'l!",
    "🎨 Hayot — sen chizayotgan rasm. Kitob — eng zo'r bo'yoqlar to'plami.",
    "🪄 Sehr yo'q, mehnat bor. Bugungi mehnat — bir bet va bir tugma.",
    "🌅 Yangi kun — yangi imkoniyat. Hisobot bilan boshla, faxr bilan tugat!",
    "📮 Hisobot tugmasi seni kutmoqda. Bosishga tayyormisan? 👇",
]


def _cta_reply_markup():
    """Inline keyboard with the 'Hisobot jo'natish' CTA button."""
    button = {
        "inline_keyboard": [[{
            "text": "📚 Hisobot jo'natish",
            "callback_data": "cta_send_report",
        }]]
    }
    return json.dumps(button)


@shared_task
def send_random_inspiration():
    """Pick a random inspirational text from INSPIRATION_POOL and broadcast to
    all registered users with a 'Hisobot jo'natish' inline CTA button.
    Respects per-user `reminder_count`:
      count=0 → never; count=1 → only 21:00;
      count=2 → 07:00 + 21:00; count=3 → all three slots.
    """
    hour = timezone.localtime().hour
    if hour < 10:
        threshold = 2  # 07:00 slot
    elif hour < 17:
        threshold = 3  # 13:30 slot
    else:
        threshold = 1  # 21:00 slot

    text = random.choice(INSPIRATION_POOL)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    qs = TelegramProfile.objects.filter(
        is_registered=True, is_blocked=False, reminder_count__gte=threshold,
    )
    sent, failed = 0, 0
    reply_markup = _cta_reply_markup()
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup,
                },
                timeout=5,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    print(f"send_random_inspiration: sent={sent} failed={failed}")


@shared_task
def broadcast_random_pool_reminder():
    """Pick ONE random text from all active ScheduledReminder rows and
    broadcast it. Designed to fire at fixed times (09:00, 21:00) via celery
    beat — the per-reminder hour/minute fields are now legacy/ignored."""
    pool = list(
        ScheduledReminder.objects
        .filter(is_active=True)
        .values_list("text", flat=True)
    )
    if not pool:
        return
    broadcast_reminder.delay(random.choice(pool))


@shared_task
def broadcast_reminder(text: str):
    """Send `text` to every registered, non-blocked TelegramProfile."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent, failed = 0, 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    print(f"broadcast_reminder: sent={sent} failed={failed}")


GENERAL_GROUP_ID = -1002237773868


@shared_task
def check_user_achievements(user_id: int):
    """Evaluate achievements for the given TelegramProfile, award new ones,
    and broadcast Tabriklash for each unlock to the general group."""
    from tgbot.services.achievements import award_new_achievements

    user = TelegramProfile.objects.filter(id=user_id).first()
    if not user:
        return
    newly = award_new_achievements(user)
    if not newly:
        return

    plain_name = escape(user.full_name or user.username or "Foydalanuvchi")
    tg_id = user.telegram_id

    for ach in newly:
        title = ach.get("title_uz") or ach.get("title_ru") or ach["code"]
        points = ach.get("points", 0)

        # Award kitobcha for this unlock.
        if points:
            try:
                user.update_ball(True, points)
            except Exception as e:
                print(f"award kitobcha for achievement {ach['code']} failed: {e}")

        points_line = f"\n🪙 <b>+{points} Kitobcha</b>" if points else ""

        # 1) Group congrats — auto-delete after 10 minutes.
        group_text = (
            "🎉 <b>Tabriklaymiz!</b>\n\n"
            f"<a href='tg://user?id={tg_id}'>{plain_name}</a> yangi yutuqni qo'lga kiritdi:\n\n"
            f"{ach['emoji']} <b>{title}</b>"
            f"{points_line}\n\n"
            "Davom etamiz! 📚🔥"
        )
        try:
            url_send = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            resp = requests.post(
                url_send,
                data={
                    "chat_id": GENERAL_GROUP_ID,
                    "text": group_text,
                    "parse_mode": "HTML",
                },
                timeout=5,
            )
            if resp.ok:
                msg_id = resp.json().get("result", {}).get("message_id")
                if msg_id:
                    ScheduledMessageDeletion.objects.create(
                        chat_id=GENERAL_GROUP_ID,
                        message_id=msg_id,
                        delete_at=timezone.now() + timezone.timedelta(minutes=10),
                    )
        except Exception as e:
            print(f"tabriklash group broadcast failed for {tg_id}/{ach['code']}: {e}")

        try:
            UserAchievement.objects.filter(
                user=user, code=ach["code"]
            ).update(congratulated=True)
        except Exception as e:
            print(f"mark congratulated failed: {e}")

        # 2) Personal DM to the achiever (kept, no auto-delete).
        try:
            dm_text = (
                f"🎉 <b>Yangi yutuq!</b>\n\n"
                f"{ach['emoji']} <b>{title}</b>"
                f"{points_line}\n\n"
                "Tabriklaymiz! Davom eting 🚀"
            )
            send_notification(chat_id=user.telegram_id, text=dm_text)
        except Exception as e:
            print(f"achievement DM failed for {tg_id}: {e}")

        # 3) Broadcast to other users with Tabriklash inline button.
        try:
            ua = UserAchievement.objects.filter(user=user, code=ach["code"]).first()
            if ua:
                broadcast_congrats_to_others.delay(ua.id, points)
        except Exception as e:
            print(f"dispatch broadcast_congrats_to_others failed: {e}")


def _gender_match(achiever, recipient) -> bool:
    """Recipient gets the broadcast iff:
       - recipient is willing to congratulate achiever's gender, AND
       - achiever accepts congrats from recipient's gender.
    Empty/unknown genders default to 'any'."""
    a_g = achiever.gender or ""
    r_g = recipient.gender or ""
    sender_pref = recipient.send_congrats_to or "any"
    accept_pref = achiever.accept_congrats_from or "any"
    if sender_pref != "any" and sender_pref != a_g:
        return False
    if accept_pref != "any" and accept_pref != r_g:
        return False
    return True


@shared_task
def broadcast_congrats_to_others(user_achievement_id: int, points: int):
    """For a freshly-unlocked UserAchievement, send a Tabriklash invitation
    DM to every OTHER eligible registered user. Filtering by gender prefs."""
    from tgbot.services.achievements import find_achievement

    ua = UserAchievement.objects.filter(id=user_achievement_id).first()
    if not ua:
        return
    achiever = ua.user
    ach = find_achievement(ua.code)
    if not ach:
        return

    title = ach.get("title_uz") or ach["code"]
    plain_name = escape(achiever.full_name or "Kitobxon")
    points_line = f"🪙 +{points} Kitobcha\n" if points else ""

    text = (
        f"🌟 <b>{plain_name}</b> yutuqqa erishdi!\n\n"
        f"{ach['emoji']} <b>{title}</b>\n"
        f"{points_line}\n"
        "Keling, kitobxonni tabriklaymiz! 🎉"
    )
    keyboard = json.dumps({
        "inline_keyboard": [[{
            "text": "🎉 Tabriklash",
            "callback_data": f"congrats:{ua.id}",
        }]]
    })

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    qs = (
        TelegramProfile.objects
        .filter(is_registered=True, is_blocked=False)
        .exclude(id=achiever.id)
    )
    sent = 0
    for recipient in qs.iterator():
        try:
            if not _gender_match(achiever, recipient):
                continue
            resp = requests.post(
                url,
                data={
                    "chat_id": recipient.telegram_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard,
                },
                timeout=5,
            )
            if resp.ok:
                sent += 1
        except Exception as e:
            print(f"broadcast_congrats_to_others to {recipient.id} failed: {e}")
    print(f"broadcast_congrats_to_others ua={user_achievement_id}: sent={sent}")


@shared_task
def daily_top_readers_reward():
    """Kun oxirida bugungi top kitobxonlarga kitobcha mukofoti beradi.
    1-o'rin: 50, 2-o'rin: 30, 3-o'rin: 15, qolganlari: 5 tadan."""
    today = timezone.localdate()
    reports = (
        ConfirmationReport.objects.filter(date__date=today)
        .values('user_id')
        .annotate(total_pages=Sum('pages_read'))
        .order_by('-total_pages')
    )
    reports = list(reports)
    if not reports:
        return

    rewards_by_rank = {1: 50, 2: 30, 3: 15}
    for rank, row in enumerate(reports, start=1):
        user_id = row['user_id']
        kitobcha = rewards_by_rank.get(rank, 5)
        try:
            user = TelegramProfile.objects.filter(id=user_id).first()
            if not user:
                continue
            user.update_ball(True, kitobcha)
            try:
                pages = row['total_pages'] or 0
                place_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "🏅")
                dm_text = (
                    f"{place_emoji} <b>Bugungi reyting natijangiz!</b>\n\n"
                    f"O'rningiz: <b>{rank}</b>\n"
                    f"O'qigan betlaringiz: <b>{pages}</b>\n"
                    f"🪙 Mukofot: <b>+{kitobcha} Kitobcha</b>\n\n"
                    f"Joriy balans: <b>{int(user.ball)}</b>"
                )
                send_notification(chat_id=user.telegram_id, text=dm_text)
            except Exception as e:
                print(f"daily reward DM failed for {user_id}: {e}")
        except Exception as e:
            print(f"daily reward award failed for {user_id}: {e}")


@shared_task
def broadcast_poll(poll_id: int):
    """Send a BotPoll to every registered user as a message with inline-button options."""
    poll = BotPoll.objects.filter(id=poll_id).first()
    if not poll or not poll.is_active:
        print(f"broadcast_poll: poll {poll_id} not found or inactive")
        return

    text = f"📊 <b>{escape(poll.question)}</b>"
    buttons = []
    for idx, opt in enumerate(poll.options):
        buttons.append([{"text": opt, "callback_data": f"poll_vote:{poll.id}:{idx}"}])
    reply_markup = json.dumps({"inline_keyboard": buttons})

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent, failed = 0, 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup,
                },
                timeout=5,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    print(f"broadcast_poll #{poll_id}: sent={sent} failed={failed}")


# ────────────────────────────────────────────────────────────────────────
# Phase 3: progress bar, percentile & reminders.
# ────────────────────────────────────────────────────────────────────────
LEVELS = [
    (1000,    "🥉", "Bronza",     100),
    (2000,    "🥈", "Kumush",     200),
    (4000,    "🥇", "Oltin",      400),
    (8000,    "🏆", "Chempion",   800),
    (10000,   "💎", "Olmos",     1000),
    (20000,   "🦄", "Afsona",    2000),
    (50000,   "⭐", "Magistr",   5000),
    (100000,  "👑", "Usta",     10000),
]


def _level_for(pages: int):
    """Return (current_idx, current_threshold, current_emoji, current_name,
    next_threshold_or_None) for the given page count."""
    current_idx = -1
    for i, (thr, _, _, _) in enumerate(LEVELS):
        if pages >= thr:
            current_idx = i
        else:
            break
    if current_idx == -1:
        prev_thr = 0
        next_thr = LEVELS[0][0]
        emoji = "📖"
        name = "Yo'lboshi"
    else:
        prev_thr = LEVELS[current_idx][0]
        emoji = LEVELS[current_idx][1]
        name = LEVELS[current_idx][2]
        next_thr = LEVELS[current_idx + 1][0] if current_idx + 1 < len(LEVELS) else None
    return current_idx, prev_thr, emoji, name, next_thr


def _progress_bar_text(pages: int) -> str:
    idx, prev_thr, emoji, name, next_thr = _level_for(pages)
    if next_thr is None:
        bar = "▰" * 12
        line = f"{bar} 100%"
        return (
            f"{emoji} <b>Daraja: {name}</b> (eng yuqori!)\n\n"
            f"{line}\n"
            f"📄 Jami: <b>{pages}</b> bet\n"
            f"🏁 Barcha marralar bosib o'tildi! 👑"
        )
    span = next_thr - prev_thr
    progress = max(0, pages - prev_thr)
    pct = min(100, int(progress * 100 / span))
    filled = int(pct / 100 * 12)
    bar = "▰" * filled + "▱" * (12 - filled)
    return (
        f"{emoji} <b>Daraja: {name}</b>\n\n"
        f"{bar} {pct}%\n"
        f"📄 Sizning betlaringiz: <b>{pages}</b>\n"
        f"🎯 Keyingi marra: <b>{next_thr}</b> bet (yana {next_thr - pages} bet)"
    )


def _award_level_rewards(user: TelegramProfile, pages: int):
    """Award one-time kitobcha for each level threshold the user crosses.
    Levels are tracked as UserAchievement codes lvl_<threshold>."""
    awarded = set(
        UserAchievement.objects.filter(user=user, code__startswith="lvl_")
        .values_list("code", flat=True)
    )
    for thr, emoji, name, points in LEVELS:
        code = f"lvl_{thr}"
        if pages >= thr and code not in awarded:
            try:
                UserAchievement.objects.create(user=user, code=code, congratulated=True)
                user.update_ball(True, points)
                dm = (
                    f"{emoji} <b>Yangi daraja: {name}!</b>\n\n"
                    f"📄 {thr} bet marrasini bosib o'tdingiz!\n"
                    f"🪙 <b>+{points} Kitobcha</b>\n\n"
                    f"Joriy balans: <b>{int(user.ball)}</b>"
                )
                send_notification(chat_id=user.telegram_id, text=dm)
            except Exception as e:
                print(f"level award {code} failed for {user.id}: {e}")


def _send_and_pin_progress(user) -> int:
    """Send fresh progress message to a user, unpin the previous, pin the new
    one, persist the new message_id to user.last_progress_msg_id. Returns the
    new message_id (or 0 on failure)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    pin_url = f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage"
    unpin_url = f"https://api.telegram.org/bot{BOT_TOKEN}/unpinChatMessage"

    pages = (
        ConfirmationReport.objects.filter(user=user)
        .aggregate(s=Sum("pages_read"))["s"] or 0
    )
    _award_level_rewards(user, pages)

    text = _progress_bar_text(pages)
    resp = requests.post(
        url,
        data={
            "chat_id": user.telegram_id,
            "text": text,
            "parse_mode": "HTML",
        },
        timeout=5,
    )
    if not resp.ok:
        return 0
    msg_id = resp.json().get("result", {}).get("message_id")
    if not msg_id:
        return 0

    # Unpin previous (best-effort), pin the new one.
    if user.last_progress_msg_id:
        try:
            requests.post(
                unpin_url,
                data={
                    "chat_id": user.telegram_id,
                    "message_id": user.last_progress_msg_id,
                },
                timeout=3,
            )
        except Exception:
            pass
    try:
        requests.post(
            pin_url,
            data={
                "chat_id": user.telegram_id,
                "message_id": msg_id,
                "disable_notification": True,
            },
            timeout=3,
        )
    except Exception:
        pass

    try:
        TelegramProfile.objects.filter(id=user.id).update(last_progress_msg_id=msg_id)
        user.last_progress_msg_id = msg_id
    except Exception as e:
        print(f"failed to save last_progress_msg_id for {user.id}: {e}")
    return msg_id


@shared_task
def daily_progress_broadcast():
    """At 00:01 Tashkent: refresh each user's pinned progress bar."""
    users = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent = 0
    for user in users.iterator():
        try:
            if _send_and_pin_progress(user):
                sent += 1
        except Exception as e:
            print(f"daily_progress_broadcast failed for {user.id}: {e}")
    print(f"daily_progress_broadcast: sent={sent}")


@shared_task
def ensure_progress_pin():
    """Hourly safety net: every registered user must have a pinned progress.
    - If they already have a stored message_id, try to repin it; on failure
      (message was deleted/unpinned), send a fresh one.
    - If they have no stored message_id yet (first run for this user),
      send-and-pin a fresh one."""
    pin_url = f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage"
    users = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    repinned = resent = bootstrapped = 0
    for user in users.iterator():
        try:
            if user.last_progress_msg_id:
                resp = requests.post(
                    pin_url,
                    data={
                        "chat_id": user.telegram_id,
                        "message_id": user.last_progress_msg_id,
                        "disable_notification": True,
                    },
                    timeout=3,
                )
                if resp.ok:
                    repinned += 1
                    continue
                # Telegram rejected — most likely message was deleted.
                if _send_and_pin_progress(user):
                    resent += 1
            else:
                if _send_and_pin_progress(user):
                    bootstrapped += 1
        except Exception as e:
            print(f"ensure_progress_pin failed for {user.id}: {e}")
    print(
        f"ensure_progress_pin: repinned={repinned} "
        f"resent={resent} bootstrapped={bootstrapped}"
    )


# Heuristic mapping — pages-vs-world-population percentile.
WORLD_PCTILE = [
    (5,   70),
    (10,  80),
    (30,  90),
    (50,  95),
    (100, 98),
    (200, 99),
]


@shared_task
def daily_no_report_reminder():
    """For every registered user who has NOT yet reported today, send a fun
    'X bet o'qisangiz dunyoning Y% aholisidan oldinda bo'lasiz' nudge."""
    today = timezone.localdate()
    reported_ids = set(
        ConfirmationReport.objects.filter(date__date=today)
        .values_list("user_id", flat=True)
    )

    suggestion = random.choice(WORLD_PCTILE)
    pages, percentile = suggestion
    text = (
        "🌍 <b>Bilasizmi?</b>\n\n"
        f"Bugun atigi <b>{pages} bet</b> kitob o'qisangiz, dunyoning "
        f"<b>{percentile}%</b> aholisidan ko'p o'qigan bo'lasiz!\n\n"
        f"Hisobotni tashlash uchun pastdagi tugmani bosing 👇"
    )

    qs = TelegramProfile.objects.filter(
        is_registered=True, is_blocked=False, reminder_count__gte=1,
    ).exclude(id__in=reported_ids)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    reply_markup = _cta_reply_markup()
    sent = 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup,
                },
                timeout=5,
            )
            if resp.ok:
                sent += 1
        except Exception as e:
            print(f"no_report_reminder failed for {chat_id}: {e}")
    print(f"daily_no_report_reminder: sent={sent}")


@shared_task
def end_of_day_percentile():
    """For every user who reported today, send a personal '% of users you
    out-read' message; auto-deletes 72h later via process_scheduled_deletions."""
    today = timezone.localdate()
    rows = list(
        ConfirmationReport.objects.filter(date__date=today)
        .values("user_id")
        .annotate(total=Sum("pages_read"))
        .order_by("-total")
    )
    if not rows:
        return

    pages_by_user = {r["user_id"]: r["total"] or 0 for r in rows}
    all_pages = sorted(pages_by_user.values())
    n = len(all_pages)

    delete_at = timezone.now() + timezone.timedelta(hours=72)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    sent = 0
    for user_id, pages in pages_by_user.items():
        try:
            user = TelegramProfile.objects.filter(id=user_id).first()
            if not user:
                continue
            behind = sum(1 for p in all_pages if p < pages)
            denom = max(n - 1, 1)
            pct = round(behind * 100 / denom)

            text = (
                "📊 <b>Bugungi natijangiz!</b>\n\n"
                f"📄 O'qigan betlaringiz: <b>{pages}</b>\n"
                f"📈 Bugun siz boshqa <b>{pct}%</b> kitobxonlardan ko'p o'qidingiz!\n\n"
                "Davom etamiz! 🚀\n\n"
                "<i>Bu xabar 72 soatdan keyin avtomatik o'chiriladi.</i>"
            )
            resp = requests.post(
                url,
                data={
                    "chat_id": user.telegram_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=5,
            )
            if resp.ok:
                msg_id = resp.json().get("result", {}).get("message_id")
                if msg_id:
                    ScheduledMessageDeletion.objects.create(
                        chat_id=user.telegram_id,
                        message_id=msg_id,
                        delete_at=delete_at,
                    )
                sent += 1
        except Exception as e:
            print(f"end_of_day_percentile failed for {user_id}: {e}")
    print(f"end_of_day_percentile: sent={sent}")


@shared_task
def process_scheduled_deletions():
    """Every minute: delete any messages whose delete_at has passed."""
    now = timezone.now()
    due = ScheduledMessageDeletion.objects.filter(delete_at__lte=now)[:200]
    if not due:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
    deleted_ids = []
    for row in due:
        try:
            requests.post(
                url,
                data={"chat_id": row.chat_id, "message_id": row.message_id},
                timeout=3,
            )
        except Exception:
            pass
        deleted_ids.append(row.id)
    if deleted_ids:
        ScheduledMessageDeletion.objects.filter(id__in=deleted_ids).delete()
