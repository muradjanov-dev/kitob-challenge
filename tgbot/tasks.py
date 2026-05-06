import asyncio
import random
import requests
import environ
import json

from celery import shared_task

from tgbot.models import DailyMessage, ConfirmationReport, TelegramProfile, Group, ScheduledReminder, BotPoll

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


def weekly_report_for_group(group: Group):
    end_date = timezone.now()
    start_date = end_date - timezone.timedelta(days=3)

    message = f"📚 Oxirgi 3 kunda eng ko'p kitob o'qigan {group.title} guruhining a'zolari:\n\n"

    reports = ConfirmationReport.objects.filter(
        date__gte=start_date,
        date__lte=end_date,
        user__group=group
    ).values(
        'user__full_name',
        'user__telegram_id',
    ).annotate(
        total_page=Sum('pages_read')
    ).order_by('-total_page')

    group_total_pages = 0

    for index, report in enumerate(iterable=reports, start=1):
        telegram_id = report.get('user__telegram_id')
        full_name = report.get('user__full_name', 'No fullname')
        total_pages = report.get('total_page', 0)

        group_total_pages += total_pages

        message += f"{index}. <b><a href='tg://user?id={telegram_id}'>{full_name}</a></b>: {total_pages} bet 📚\n"

    return (group_total_pages, group.title, message)


@shared_task
def weekly_report_for_general():
    groups = Group.objects.all()

    groups_sorted = sorted(
        [weekly_report_for_group(group) for group in groups],
        key=lambda x: x[0],
        reverse=True
    )

    message = "📚 Oxirgi 3 kunda eng ko'p kitob o'qigan guruhlar:\n\n"
    for index, group in enumerate(iterable=groups_sorted, start=1):
        if group[0] != 0:
            message += f"{index}. <b>{group[1]}</b>. Jami {group[0]} bet\n"

    general_id = -1002237773868
    send_message(general_id, message)
    send_message(general_id, groups_sorted[0][2])


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
    all registered users with a 'Hisobot jo'natish' inline CTA button."""
    text = random.choice(INSPIRATION_POOL)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
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
def check_and_dispatch_reminders():
    """Beat-driven: every minute, if any reminder is due, broadcast ONE random
    text from the pool of all active reminders. Schedules act as triggers; the
    text sent is independent of which reminder fired."""
    now = timezone.localtime()
    due_exists = ScheduledReminder.objects.filter(
        is_active=True, hour=now.hour, minute=now.minute
    ).exists()
    if not due_exists:
        return
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
