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
from django.db.models import Sum
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
        message = f"Shu kungacha Kitob Challenge loyihasi doirasida jami {total_pages_by_user['total_pages']} bet o'qildi! 📚✨📖\nAjoyib natija! ⚡️⚡️⚡️ Davom etamiz! 🚀"
    else:
        message = "📚 Kecha uchun kitob o'qigan foydalanuvchilar yo'q."

    for _cid in _group_chat_ids():
        send_notification(_cid, message)


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


def _build_combined_top_rows(start_date, end_date, limit):
    """Merge page and audio aggregates per user across [start, end].

    Returns list of dicts: {tg_id, full_name, pages, minutes}, sorted by
    (pages desc, minutes desc). Anyone with pages>0 OR minutes>0 is included,
    so audio-only listeners show up at the bottom of the list.
    """
    # Exclude blocked users (e.g. for cheating/scamming) from all top lists.
    pages_rows = (
        ConfirmationReport.objects.filter(
            date__date__gte=start_date,
            date__date__lte=end_date,
            is_audio=False,
            user__is_blocked=False,
        )
        .values('user__telegram_id', 'user__full_name')
        .annotate(total=Sum('pages_read'))
        .filter(total__gt=0)
    )
    audio_rows = (
        ConfirmationReport.objects.filter(
            date__date__gte=start_date,
            date__date__lte=end_date,
            is_audio=True,
            user__is_blocked=False,
        )
        .values('user__telegram_id', 'user__full_name')
        .annotate(total=Sum('minutes_listened'))
        .filter(total__gt=0)
    )
    merged = {}
    for r in pages_rows:
        tg = r['user__telegram_id']
        merged[tg] = {
            'tg_id': tg,
            'full_name': r['user__full_name'],
            'pages': r['total'] or 0,
            'minutes': 0,
        }
    for r in audio_rows:
        tg = r['user__telegram_id']
        if tg in merged:
            merged[tg]['minutes'] = r['total'] or 0
        else:
            merged[tg] = {
                'tg_id': tg,
                'full_name': r['user__full_name'],
                'pages': 0,
                'minutes': r['total'] or 0,
            }
    ordered = sorted(merged.values(), key=lambda x: (-x['pages'], -x['minutes']))
    return ordered[:limit]


def _format_top_stat(pages, minutes):
    """Render `502 bet 📚 · 2326 daq 🎧`, omitting any zero column."""
    parts = []
    if pages:
        parts.append(f"{pages} bet 📚")
    if minutes:
        parts.append(f"{minutes} daq 🎧")
    return " · ".join(parts) or "—"


@shared_task
def daily_top_read_user_action_button():
    asyncio.run(_daily_top_read_user_action_button())


async def _daily_top_read_user_action_button():
    today = timezone.now().date()
    premium_ids = _get_premium_tg_ids()

    rows = _build_combined_top_rows(today, today, 20)

    if rows:
        message = "📚 Bugun eng faol kitobxonlar (📚 Kitob va 🎧 Audio):\n\n"
        for index, r in enumerate(rows, start=1):
            tg_id = r['tg_id']
            name = escape(r['full_name'] or "Foydalanuvchi")
            badge = "💎 " if tg_id in premium_ids else ""
            stat = _format_top_stat(r['pages'], r['minutes'])
            message += f"{index}) <b><a href='tg://user?id={tg_id}'>{badge}{name}</a></b>: {stat}\n\n"
    else:
        message = "📚 Bugun hisobot yuborgan foydalanuvchilar yo'q."

    for _cid in _group_chat_ids():
        send_message(_cid, message)


def _get_premium_tg_ids() -> set:
    """Return set of telegram_ids that currently have an active premium subscription."""
    from tgbot.models import Payment
    return set(
        Payment.objects.filter(
            status="paid", end_date__gte=timezone.localdate()
        ).values_list("user__telegram_id", flat=True)
    )


def _send_period_report(start_date, end_date, limit, period_name):
    premium_ids = _get_premium_tg_ids()

    rows = _build_combined_top_rows(start_date, end_date, limit)

    if not rows:
        message = f"📚 {period_name} uchun hisobot yuborgan foydalanuvchilar yo'q."
    else:
        message = f"📚 {period_name} eng faol kitobxonlar:\n\n"
        for index, r in enumerate(rows, start=1):
            tg_id = r['tg_id']
            full_name = escape(r['full_name'] or "Foydalanuvchi")
            badge = "💎 " if tg_id in premium_ids else ""
            stat = _format_top_stat(r['pages'], r['minutes'])
            message += f"{index}. <b><a href='tg://user?id={tg_id}'>{badge}{full_name}</a></b>: {stat}\n"

    for _cid in _group_chat_ids():
        send_message(_cid, message)


@shared_task
def daily_top_read_user():
    import datetime as _dt
    today = timezone.localdate()
    date_str = today.strftime("%Y%m%d")
    # _broadcast_top_to_groups_and_users covers both group posts AND user DMs
    # with a Tabriklash button. Calling _send_period_report on top of it was
    # producing duplicate identical group posts.
    msg = _build_top_readers_message(today, today, "Bugun 🔥", limit=20)
    if msg:
        _broadcast_top_to_groups_and_users(msg, "daily", date_str)


@shared_task
def three_days_top_read_user():
    import datetime as _dt
    end_date = timezone.localdate()
    start_date = end_date - _dt.timedelta(days=2)
    _send_period_report(start_date, end_date, 20, "Oxirgi 3 kunda")


@shared_task
def weekly_top_read_user():
    import datetime as _dt
    end_date = timezone.localdate()
    start_date = end_date - _dt.timedelta(days=6)
    date_str = end_date.strftime("%Y%m%d")
    msg = _build_top_readers_message(start_date, end_date, "Bu hafta 🏆", limit=30)
    if msg:
        _broadcast_top_to_groups_and_users(msg, "weekly", date_str)


@shared_task
def monthly_top_read_user():
    import datetime as _dt
    end_date = timezone.localdate()
    start_date = end_date - _dt.timedelta(days=29)
    date_str = end_date.strftime("%Y%m%d")
    msg = _build_top_readers_message(start_date, end_date, "Bu oy 📅", limit=30)
    if msg:
        _broadcast_top_to_groups_and_users(msg, "monthly", date_str)


@shared_task
def three_months_top_read_user():
    import datetime as _dt
    end_date = timezone.localdate()
    start_date = end_date - _dt.timedelta(days=89)
    date_str = end_date.strftime("%Y%m%d")
    msg = _build_top_readers_message(start_date, end_date, "3 oylik 📊", limit=40)
    if msg:
        _broadcast_top_to_groups_and_users(msg, "3monthly", date_str)


@shared_task
def six_months_top_read_user():
    import datetime as _dt
    end_date = timezone.localdate()
    start_date = end_date - _dt.timedelta(days=180)
    _send_period_report(start_date, end_date, 50, "Oxirgi 6 oyda")


@shared_task
def yearly_top_read_user():
    import datetime as _dt
    end_date = timezone.localdate()
    start_date = end_date - _dt.timedelta(days=364)
    date_str = end_date.strftime("%Y%m%d")
    msg = _build_top_readers_message(start_date, end_date, "Yillik 🏅", limit=60)
    if msg:
        _broadcast_top_to_groups_and_users(msg, "yearly", date_str)


def _is_user_in_chat(chat_id, user_id) -> bool:
    """Returns True only if the user is a current member (creator/admin/member/restricted)."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
            data={"chat_id": chat_id, "user_id": user_id},
            timeout=5,
        ).json()
        if not resp.get("ok"):
            return False
        status = resp.get("result", {}).get("status")
        return status in ("creator", "administrator", "member", "restricted")
    except Exception:
        return False


@shared_task
def users_unread_book():
    """Per-group reminder: in each gender group, list ONLY members of that
    specific group who haven't reported today. Users who left the group are
    skipped — no point pinging strangers."""
    import os as _os
    import time as _time

    today = timezone.localdate()
    non_reporters = list(
        TelegramProfile.objects
        .exclude(confirmationreport__date__date=today)
        .filter(is_registered=True, is_blocked=False)
    )

    if not non_reporters:
        return

    boys_chat = _os.environ.get("BOYS_GROUP_ID", "").strip()
    girls_chat = _os.environ.get("GIRLS_GROUP_ID", "").strip()
    general_chat = str(GENERAL_GROUP_ID)

    # group_chat_id -> ordered list of users to check membership against this chat
    targets = []
    if boys_chat:
        targets.append((boys_chat, [u for u in non_reporters if u.gender == "male"]))
    if girls_chat:
        targets.append((girls_chat, [u for u in non_reporters if u.gender == "female"]))
    # General group: combined of everyone (we'll dedupe by checking general membership)
    targets.append((general_chat, list(non_reporters)))

    suffix = (
        "\nKuniga 5-10 daqiqa va siz yana safdasiz 🚀 \n\n"
        " *Bizdan qolib ketmysiz degan umiddamiz xurmatli do'stlar"
    )

    for chat_id, candidate_users in targets:
        members_present = []
        for u in candidate_users:
            if u.full_name is None:
                try:
                    u.delete()
                except Exception:
                    pass
                continue
            if u.telegram_id == 631751797:
                continue
            if _is_user_in_chat(chat_id, u.telegram_id):
                members_present.append(u)
            _time.sleep(0.04)  # gentle pacing to avoid 429

        if not members_present:
            continue

        message = f"‼️ Bugun hisobot yubormaganlar: {len(members_present)}ta\n\n"
        for u in members_present:
            handle = f"@{u.username}" if u.username else f'<a href="tg://user?id={u.telegram_id}">{u.full_name}</a>'
            message += f"-{handle} (<b>{u.full_name}</b>)\n"
        message += suffix

        try:
            send_message(chat_id, message)
        except Exception as e:
            print(f"users_unread_book send to {chat_id} failed: {e}")


def _build_top_readers_message(start_date, end_date, period_label, limit=20):
    """Top kitobxonlar (period bo'yicha): pages + audio minutes per user."""
    premium_ids = _get_premium_tg_ids()

    rows = _build_combined_top_rows(start_date, end_date, limit)

    if not rows:
        return None

    grand_pages = sum(r['pages'] for r in rows)
    grand_minutes = sum(r['minutes'] for r in rows)
    # period_label is the time descriptor only (e.g. 'Bugun', 'Oxirgi 3 kunda',
    # 'Bu hafta 🏆'). The 'Top {limit} Kitobxonlar:' suffix is composed here so
    # all callers stay consistent.
    message = f"📚 {period_label} Top {limit} Kitobxonlar:\n\n"
    for index, r in enumerate(rows, start=1):
        tg_id = r['tg_id']
        full_name = escape(r['full_name'] or "Foydalanuvchi")
        badge = "💎 " if tg_id in premium_ids else ""
        stat = _format_top_stat(r['pages'], r['minutes'])
        message += f"{index}. <b><a href='tg://user?id={tg_id}'>{badge}{full_name}</a></b>: {stat}\n"
    total_stat = _format_top_stat(grand_pages, grand_minutes)
    message += f"\n📊 Jami: <b>{total_stat}</b>"
    return message


def _toplist_congrats_keyboard(period: str, date_str: str) -> str:
    """Returns JSON inline keyboard with a Tabriklash button for top lists."""
    return json.dumps({
        "inline_keyboard": [[{
            "text": "🎉 Tabriklash",
            "callback_data": f"toplist_congrats:{period}:{date_str}",
        }]]
    })


def _broadcast_top_to_groups_and_users(message: str, period: str, date_str: str):
    """Send top list to all groups and to all registered users (with Tabriklash button)."""
    keyboard = _toplist_congrats_keyboard(period, date_str)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # Build group list: general group + boys + girls
    import os as _os
    girls_group = _os.environ.get("GIRLS_GROUP_ID", "").strip()
    group_ids = list(_group_chat_ids())
    if girls_group and girls_group not in group_ids:
        group_ids.append(girls_group)

    print(f"_broadcast_top_to_groups_and_users: sending to groups {group_ids}")
    for group_id in group_ids:
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": group_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                    "reply_markup": keyboard,
                },
                timeout=10,
            )
            print(f"group send {group_id}: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"group send {group_id} exception: {e}")

    import time as _time
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent = failed = 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                    "reply_markup": keyboard,
                },
                timeout=10,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
                if resp.status_code == 429:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                    _time.sleep(retry_after)
        except Exception:
            failed += 1
        _time.sleep(0.05)  # stay under Telegram's 30 msg/sec global limit
    print(f"_broadcast_top_to_groups_and_users({period}): sent={sent} failed={failed}")


@shared_task
def process_toplist_congrats(period: str, date_str: str, congratulator_tg_id: int):
    """When a user presses Tabriklash on a top-list broadcast, send
    a congratulation DM to every user in that period's top list."""
    import datetime as _dt

    try:
        end_date = _dt.datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        return

    period_map = {
        "daily":    (_dt.timedelta(days=0),   "Kunlik",   20),
        "3days":    (_dt.timedelta(days=2),   "3 kunlik", 20),
        "weekly":   (_dt.timedelta(days=6),   "Haftalik", 30),
        "monthly":  (_dt.timedelta(days=29),  "Oylik",    30),
        "3monthly": (_dt.timedelta(days=89),  "3 oylik",  40),
        "yearly":   (_dt.timedelta(days=364), "Yillik",   60),
    }
    if period not in period_map:
        return

    delta, period_label, limit = period_map[period]
    start_date = end_date - delta

    congratulator = TelegramProfile.objects.filter(telegram_id=congratulator_tg_id).first()
    if not congratulator:
        return
    presser_name = escape(congratulator.full_name or "Kitobxon")

    rows = list(
        ConfirmationReport.objects
        .filter(date__date__gte=start_date, date__date__lte=end_date)
        .values("user__telegram_id", "user__full_name")
        .annotate(total=Sum("pages_read"))
        .order_by("-total")[:limit]
    )
    if not rows:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for row in rows:
        tg_id = row["user__telegram_id"]
        if tg_id == congratulator_tg_id:
            continue
        try:
            text = (
                f"🎉 <b>{presser_name}</b> sizi tabriklamoqda!\n\n"
                f"📊 <b>{period_label}</b> top ro'yxatida bo'lganingiz uchun!\n\n"
                "Zo'r natija! Davom eting 📚🔥"
            )
            requests.post(
                url,
                data={"chat_id": tg_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception as e:
            print(f"toplist congrats DM failed for {tg_id}: {e}")


def _post_period_top(start_date, end_date, label, limit):
    """Build a 'Top N Kitobxonlar' message for the period and post to all
    groups. Returns nothing — purely a side-effect helper used by the three
    periodic tasks below and the legacy bundled admin action."""
    msg = _build_top_readers_message(start_date, end_date, label, limit=limit)
    if msg is None:
        msg = f"📚 {label} Top {limit} Kitobxonlar: ma'lumot yo'q."
    for _cid in _group_chat_ids():
        send_message(_cid, msg)


@shared_task
def three_day_top_report():
    """3 kunlik Top 20 Kitobxonlar — scheduled every 3 days."""
    import datetime as _dt
    end_date = timezone.localdate()
    _post_period_top(end_date - _dt.timedelta(days=2), end_date, "Oxirgi 3 kunda", 20)


@shared_task
def seven_day_top_report():
    """7 kunlik Top 25 Kitobxonlar — scheduled weekly."""
    import datetime as _dt
    end_date = timezone.localdate()
    _post_period_top(end_date - _dt.timedelta(days=6), end_date, "Oxirgi 7 kunda", 25)


@shared_task
def thirty_day_top_report():
    """30 kunlik Top 30 Kitobxonlar — scheduled monthly."""
    import datetime as _dt
    end_date = timezone.localdate()
    _post_period_top(end_date - _dt.timedelta(days=29), end_date, "Oxirgi 30 kunda", 30)


@shared_task
def weekly_report_for_general():
    """Legacy bundled task: fires all three (3/7/30-day) at once. Still wired
    to the Django-admin action button. The Celery beat schedule no longer
    uses this — the three reports are scheduled independently and on their
    own cadences so they don't collide with the daily top (23:35)."""
    three_day_top_report()
    seven_day_top_report()
    thirty_day_top_report()


# ──────────────────────────────────────────────────────────────────────────
# Daily features spotlight broadcast.
# ──────────────────────────────────────────────────────────────────────────
_FEATURES_TEXT = (
    "📣 <b>Kitob Challenge boti imkoniyatlari</b>\n\n"
    "📚 <b>Kitob hisoboti</b> — har kuni o'qigan sahifalaringizni kiriting va reytingda ko'taring\n\n"
    "👤 <b>Kabinet</b> — statistika: jami betlar, reytingdagi o'rin, o'qish tezligi, streak kalendar\n\n"
    "🏆 <b>Yutuqlar</b> — 30+ yutuq: hisobotlar, betlar, streak, referrallar, tezlik va boshqalar\n\n"
    "📊 <b>Reyting</b> — kunlik, haftalik, oylik, 3 oylik va yillik top kitobxonlar\n\n"
    "📈 <b>Darajalar</b> — 100 → 500 → 1000 → ... bet bosib o'tganda daraja va Kitobcha mukofoti!\n\n"
    "💎 <b>Premium</b> — qo'shimcha imkoniyatlar uchun obuna\n\n"
    "⚙️ <b>Sozlamalar</b> — eslatmalar soni, til, tabriqlash filtrlari\n\n"
    "👥 <b>Referral</b> — do'stingizni taklif qiling va bonus oling"
)


def _features_keyboard():
    kb = {
        "inline_keyboard": [
            [
                {"text": "📚 Hisobot", "callback_data": "cta_send_report"},
                {"text": "👤 Kabinet", "callback_data": "menu:cabinet"},
            ],
            [
                {"text": "🏆 Yutuqlar", "callback_data": "menu:achievements"},
                {"text": "📊 Reyting",  "callback_data": "menu:reyting"},
            ],
            [
                {"text": "💎 Premium",    "callback_data": "menu:premium"},
                {"text": "⚙️ Sozlamalar", "callback_data": "menu:settings"},
            ],
            [{"text": "❓ Qanday ishlaydi?", "callback_data": "menu:how"}],
        ]
    }
    return json.dumps(kb)


@shared_task
def send_daily_features():
    """Once a day: send bot features overview with inline navigation buttons to all users."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    keyboard = _features_keyboard()
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent = failed = 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": _FEATURES_TEXT,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard,
                },
                timeout=5,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    print(f"send_daily_features: sent={sent} failed={failed}")


@shared_task
def broadcast_top_readers_to_all():
    """Admin-triggered: send weekly top-20 readers DM to every registered user."""
    end_date = timezone.localdate()
    start_date = end_date - timezone.timedelta(days=6)
    msg = _build_top_readers_message(start_date, end_date, "Bu hafta", limit=20)
    if not msg:
        print("broadcast_top_readers_to_all: no data")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent, failed = 0, 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML",
                      "disable_web_page_preview": "true"},
                timeout=5,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    print(f"broadcast_top_readers_to_all: sent={sent} failed={failed}")


@shared_task
def broadcast_period_top(period_key: str):
    """Admin-triggered: broadcast top readers for a specific period to all users."""
    import datetime as _dt
    today = timezone.localdate()
    period_cfg = {
        "daily":    (today,                           today, "Bugun 🔥 Top kitobxonlar",    20),
        "3days":    (today - _dt.timedelta(days=2),   today, "3 kunlik Top kitobxonlar",    20),
        "weekly":   (today - _dt.timedelta(days=6),   today, "Bu hafta 🏆 Top kitobxonlar", 30),
        "monthly":  (today - _dt.timedelta(days=29),  today, "Bu oy 📅 Top kitobxonlar",    30),
        "3monthly": (today - _dt.timedelta(days=89),  today, "3 oylik 📊 Top kitobxonlar",  40),
        "yearly":   (today - _dt.timedelta(days=364), today, "Yillik 🏅 Top kitobxonlar",   60),
    }
    if period_key not in period_cfg:
        print(f"broadcast_period_top: unknown period {period_key!r}")
        return
    start_date, end_date, label, limit = period_cfg[period_key]
    date_str = end_date.strftime("%Y%m%d")
    msg = _build_top_readers_message(start_date, end_date, label, limit=limit)
    if not msg:
        print(f"broadcast_period_top({period_key}): no data")
        return
    # Groups are sent immediately from the admin handler (bot process).
    # Here we only send user DMs.
    import time as _time
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    keyboard = _toplist_congrats_keyboard(period_key, date_str)
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent = failed = 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": msg,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                    "reply_markup": keyboard,
                },
                timeout=10,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
                if resp.status_code == 429:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                    _time.sleep(retry_after)
        except Exception:
            failed += 1
        _time.sleep(0.05)
    print(f"broadcast_period_top({period_key}): user DMs sent={sent} failed={failed}")


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


# ────────────────────────────────────────────────────────────────────────
# Streak-burning warning — sent at 22:00 to users who haven't reported today.
# ────────────────────────────────────────────────────────────────────────
STREAK_WARNING_POOL = [
    "🔥 Voyyy, streak kuyib ketmoqda! Hali ham hisobot yo'q... 1 bet o'qi, qoqindiq bo'lib qolma!",
    "😬 Streak — bu qo'lga kiritilmaydi, asrash kerak. Bugun hali 0 bet. Shoshil, kuyib ketadi!",
    "🚨 OGOHLANTIRISH: Streakin bugun xavf ostida! Bitta bet o'qi, bitta tugma bos. Qoqindiq emassan-ku?",
    "😤 Boshqalar hisobot yuborib bo'ldi, sen-chi? Streak 1-kundan boshlansa uyalamaysanmi? 1 bet kifoya!",
    "🫠 Streak = mehnat. Bugun mehnat qilmadingmi? Hech bo'lmasa 1 bet o'qi, qoqindiq bo'lib qolma!",
    "⚠️ Diqqat! Streak yonmoqda... Yaxshi kitobxonlarga bu xabar kerak emas, lekin sen hali hisobot bermagansan. Tez bo'l!",
    "🐢 Sekin-sekin bo'lsa ham, lekin bugun hali 0 bet? Streak kuymoqda! 1 bet o'qi, qoqindiq!",
    "😅 Kech bo'lsa ham kech emas! Hali vaqt bor, 1 bet o'qi va streak'ni qutqar. Qoqindiq bo'lma!",
    "🤦 Uh, bugun hisobot yo'q... Streak 1-kundan boshlanishini xohlaysanmi? Hech bo'lmasa 1 bet — bitta tugma!",
    "🔔 Eslatma: Streakin bugun kuyib ketmoqda. Ertaga \"ey nima bo'ldi\" dema. 1 bet o'qi, qoqindiq!",
    "💀 Streak murdaga aylanmoqda! Uni tiriltirishning yagona yo'li — hisobot. Hoziroq, 1 bet ham yetadi!",
    "😒 Kuniga 1 bet... 1 ta! Buni qilolmasan — qoqindiqsan, to'g'rimi? Isbotla, streak'ni qutqar!",
    "🥴 Hisobotsiz kun = yo'qotilgan streak. Bugungi sen ertangi senga xiyonat qilmoqda. 1 bet, 1 tugma!",
    "🫡 Odam kitob o'qiydi, qoqindiq bahona topadi. Sen qaysi tomondasanda? Streak kutmoqda!",
    "😩 Streakin bugun halok bo'lishi mumkin. Oilangg, do'stlaring bilsa uyalmasmidin? 1 bet o'qi!",
    "🧨 BOOM — streak portlab ketmoqda! Hali vaqt bor, 1 bet bilan uni qutqar. Dangasa bo'lma!",
    "🫵 Ha, sen! Hisobot bermagansan bugun. Streakin 1-kundan boshlanishini xohlaysanmi? 1 bet yetadi!",
    "🤡 Streak nol bo'lsa? Qiziq ko'rinadi. Bugun 1 bet o'qib, \"Men qoqindiq emasman\" de — isbotla!",
    "🕙 Soat 22:00, hali ham hisobot yo'q. Streakin kuymoqda. 1 bet o'qi — shu qadar oson!",
    "🌙 Tun kirib kelmoqda, streak esa kuymoqda... Bugun 1 bet o'qib hisobot yubor, qoqindiq bo'lib qolma!",
]


@shared_task
def send_streak_warning():
    """22:00 da hisobot bermaganlarni streak kuyib ketishi haqida ogohlantiradi."""
    today = timezone.localdate()
    reported_ids = set(
        ConfirmationReport.objects.filter(date__date=today)
        .values_list("user_id", flat=True)
    )

    qs = TelegramProfile.objects.filter(
        is_registered=True, is_blocked=False,
    ).exclude(id__in=reported_ids)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    reply_markup = _cta_reply_markup()
    sent = failed = 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            text = random.choice(STREAK_WARNING_POOL)
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
    print(f"send_streak_warning: sent={sent} failed={failed}")


GENERAL_GROUP_ID = -1002237773868


def _group_chat_ids():
    """Return all group/channel IDs to broadcast to: main group + boys group + girls group."""
    import os as _os
    ids = [str(GENERAL_GROUP_ID)]
    boys = _os.environ.get("BOYS_GROUP_ID", "").strip()
    if boys and boys not in ids:
        ids.append(boys)
    girls = _os.environ.get("GIRLS_GROUP_ID", "").strip()
    if girls and girls not in ids:
        ids.append(girls)
    return ids


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

        # Award kitobcha for this unlock (×2 for premium).
        awarded_points = 0
        if points:
            try:
                awarded_points = user.update_ball(True, points)
            except Exception as e:
                print(f"award kitobcha for achievement {ach['code']} failed: {e}")
                awarded_points = points

        prem_note = " 💎 ×2!" if awarded_points > points else ""
        points_line = f"\n🪙 <b>+{awarded_points} Kitobcha</b>{prem_note}" if awarded_points else ""

        # 1) Group congrats — auto-delete after 12 hours.
        group_text = (
            "🎉 <b>Tabriklaymiz!</b>\n\n"
            f"<a href='tg://user?id={tg_id}'>{plain_name}</a> yangi yutuqni qo'lga kiritdi:\n\n"
            f"{ach['emoji']} <b>{title}</b>"
            f"{points_line}\n\n"
            "Davom etamiz! 📚🔥"
        )
        import datetime as _dt
        import os as _os
        url_send = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        # Route achievement congrats to the achiever's gender-specific group only.
        if user.gender == "male":
            _gender_group = _os.environ.get("BOYS_GROUP_ID", "").strip()
        elif user.gender == "female":
            _gender_group = _os.environ.get("GIRLS_GROUP_ID", "").strip()
        else:
            _gender_group = ""
        target_groups = [_gender_group] if _gender_group else _group_chat_ids()

        for _gid in target_groups:
            try:
                resp = requests.post(
                    url_send,
                    data={"chat_id": _gid, "text": group_text, "parse_mode": "HTML"},
                    timeout=5,
                )
                if resp.ok:
                    msg_id = resp.json().get("result", {}).get("message_id")
                    if msg_id:
                        try:
                            ScheduledMessageDeletion.objects.create(
                                chat_id=int(_gid),
                                message_id=msg_id,
                                delete_at=timezone.now() + _dt.timedelta(minutes=2),
                            )
                        except Exception:
                            pass
            except Exception as e:
                print(f"tabriklash group broadcast failed for {_gid}/{ach['code']}: {e}")

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


def _achievement_count_matches_range(count: int, tier: str) -> bool:
    """Match the achiever's total achievement count against a recipient's
    'tabriklar_range' tier. 'any' matches everything (default)."""
    if tier == "any" or not tier:
        return True
    if tier == "3-10":
        return 3 <= count <= 10
    if tier == "11-20":
        return 11 <= count <= 20
    if tier == "21-40":
        return 21 <= count <= 40
    if tier == "41+":
        return count >= 41
    return True  # Unknown tier — don't silently drop.


@shared_task
def broadcast_congrats_to_others(user_achievement_id: int, points: int):
    """For a freshly-unlocked UserAchievement, send a Tabriklash invitation
    DM to every OTHER eligible registered user. Filters by gender prefs and
    by recipient's tabriklar_range vs achiever's total achievement count."""
    from tgbot.services.achievements import find_achievement

    ua = UserAchievement.objects.filter(id=user_achievement_id).first()
    if not ua:
        return
    achiever = ua.user
    ach = find_achievement(ua.code)
    if not ach:
        return

    # Achiever's total achievements — used to decide which recipient tier
    # gets this Tabriklash DM.
    achiever_total = UserAchievement.objects.filter(user=achiever).count()

    title = ach.get("title_uz") or ach["code"]
    plain_name = escape(achiever.full_name or "Kitobxon")
    points_line = f"🪙 +{points} Kitobcha\n" if points else ""

    text = (
        f"🌟 <b>{plain_name}</b> yutuqqa erishdi!\n\n"
        f"{ach['emoji']} <b>{title}</b>\n"
        f"{points_line}\n"
        "Keling, kitobxonni tabriklaymiz! 🎉"
    )
    tabriklash_btn = {"text": "🎉 Tabriklash", "callback_data": f"congrats:{ua.id}"}
    reminder_btn = {"text": "🔔 Eslatmalarni sozlash", "callback_data": "menu:settings"}
    keyboard_basic = json.dumps({"inline_keyboard": [[tabriklash_btn]]})
    keyboard_with_reminder = json.dumps({
        "inline_keyboard": [[tabriklash_btn], [reminder_btn]]
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
            tier = getattr(recipient, "tabriklar_range", "any") or "any"
            if not _achievement_count_matches_range(achiever_total, tier):
                continue
            # Nudge: every 10th Tabriklash DM also surfaces the reminder
            # config button so users can adjust daily reminders without
            # hunting through the settings menu.
            keyboard = keyboard_with_reminder if (sent + 1) % 10 == 0 else keyboard_basic
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
    print(f"broadcast_congrats_to_others ua={user_achievement_id}: sent={sent}, achiever_total={achiever_total}")


@shared_task
def daily_top_readers_reward():
    """Kun oxirida bugungi top kitobxonlarga kitobcha mukofoti beradi.
    1-o'rin: 50, 2-o'rin: 30, 3-o'rin: 15, qolganlari: 5 tadan.
    Live readers and audio-only listeners are ranked separately."""
    today = timezone.localdate()
    rewards_by_rank = {1: 50, 2: 30, 3: 15}

    # Track 1: live book readers ranked by pages (blocked users excluded)
    live_reports = list(
        ConfirmationReport.objects.filter(
            date__date=today, is_audio=False, user__is_blocked=False,
        )
        .values('user_id')
        .annotate(total=Sum('pages_read'))
        .filter(total__gt=0)
        .order_by('-total')
    )
    live_user_ids = {r['user_id'] for r in live_reports}

    # Track 2: audio-only listeners (not already in live track) ranked by minutes
    audio_reports = list(
        ConfirmationReport.objects.filter(
            date__date=today, is_audio=True, user__is_blocked=False,
        )
        .values('user_id')
        .annotate(total=Sum('minutes_listened'))
        .filter(total__gt=0)
        .exclude(user_id__in=live_user_ids)
        .order_by('-total')
    )

    def _send_reward(rank, user_id, kitobcha, stat_line):
        try:
            user = TelegramProfile.objects.filter(id=user_id).first()
            if not user:
                return
            awarded = user.update_ball(True, kitobcha)
            prem_note = " 💎 ×2!" if awarded > kitobcha else ""
            # Rank-agnostic DM: tell the user they earned Kitobcha for today's
            # reading. The "top kitobxonlar" framing now lives only in the
            # group chart broadcast, not in user DMs.
            dm_text = (
                f"🪙 <b>Bugungi o'qish uchun mukofot!</b>\n\n"
                f"{stat_line}\n"
                f"🎁 Mukofot: <b>+{awarded} Kitobcha</b>{prem_note}\n\n"
                f"💰 Joriy balans: <b>{int(user.ball)}</b>"
            )
            send_notification(chat_id=user.telegram_id, text=dm_text)
        except Exception as e:
            print(f"daily reward failed for {user_id}: {e}")

    for rank, row in enumerate(live_reports, start=1):
        stat = f"📖 O'qigan betlaringiz: <b>{row['total'] or 0} bet</b>"
        _send_reward(rank, row['user_id'], rewards_by_rank.get(rank, 5), stat)

    for rank, row in enumerate(audio_reports, start=1):
        stat = f"🎧 Eshitgan daqiqalaringiz: <b>{row['total'] or 0} daqiqa</b>"
        _send_reward(rank, row['user_id'], rewards_by_rank.get(rank, 5), stat)


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
    (100,    "🌱", "Yosh kitobxon",  15),
    (500,    "📗", "Kitobsever",     40),
    (1000,   "🥉", "Bronza",        100),
    (2000,   "🥈", "Kumush",        200),
    (4000,   "🥇", "Oltin",         400),
    (8000,   "🏆", "Chempion",      800),
    (10000,  "💎", "Olmos",        1000),
    (20000,  "🦄", "Afsona",       2000),
    (50000,  "⭐", "Magistr",      5000),
    (100000, "👑", "Usta",        10000),
]

MILESTONES = [thr for thr, _, _, _ in LEVELS]


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
        # Below the first level threshold (100 pages) → pre-level "Yo'lboshi"
        prev_thr = 0
        next_thr = LEVELS[0][0]  # 100
        emoji = "📖"
        name = "Yo'lboshi"
    else:
        prev_thr = LEVELS[current_idx][0]
        emoji = LEVELS[current_idx][1]
        name = LEVELS[current_idx][2]
        next_thr = LEVELS[current_idx + 1][0] if current_idx + 1 < len(LEVELS) else None
    return current_idx, prev_thr, emoji, name, next_thr


def _progress_bar_text(pages: int) -> str:
    _, prev_thr, emoji, name, _ = _level_for(pages)

    # Find the nearest upcoming milestone from MILESTONES list.
    next_ms = None
    prev_ms = 0
    for m in MILESTONES:
        if pages < m:
            next_ms = m
            break
        prev_ms = m

    if next_ms is None:
        bar = "▰" * 12
        return (
            f"{emoji} <b>Daraja: {name}</b> (eng yuqori!)\n\n"
            f"{bar} 100%\n"
            f"📄 Jami: <b>{pages}</b> bet\n"
            f"🏁 Barcha marralar bosib o'tildi! 👑"
        )
    span = max(next_ms - prev_ms, 1)
    pct = min(100, int(max(0, pages - prev_ms) * 100 / span))
    filled = int(pct / 100 * 12)
    bar = "▰" * filled + "▱" * (12 - filled)
    return (
        f"{emoji} <b>Daraja: {name}</b>\n\n"
        f"{bar} {pct}%\n"
        f"📄 Sizning betlaringiz: <b>{pages}</b>\n"
        f"🎯 Keyingi marra: <b>{next_ms}</b> bet (yana {next_ms - pages} bet)"
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
                aw = user.update_ball(True, points)
                prem_note = " 💎 ×2!" if aw > points else ""
                dm = (
                    f"{emoji} <b>Yangi daraja: {name}!</b>\n\n"
                    f"📄 {thr} bet marrasini bosib o'tdingiz!\n"
                    f"🪙 <b>+{aw} Kitobcha</b>{prem_note}\n\n"
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


# ────────────────────────────────────────────────────────────────────────
# Quiz Celery tasks
# ────────────────────────────────────────────────────────────────────────

@shared_task
def broadcast_vizov_invite(session_id, quiz_title, quiz_desc, q_count, time_secs, time_label):
    """Send Vizov join-invite DM to every registered user."""
    from tgbot.models import QuizSession
    import json as _j

    text = (
        f"🏆 <b>JONLI QUIZ — Vizov!</b>\n\n"
        f"📝 <b>{quiz_title}</b>\n"
        f"{quiz_desc + chr(10) if quiz_desc else ''}"
        f"❓ {q_count} ta savol · ⏱ {time_secs} son/savol\n\n"
        f"⏰ {time_label.replace('<b>', '').replace('</b>', '')}\n\n"
        f"Qatnashish uchun quyidagi tugmani bosing 👇"
    )
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    kb = _j.dumps({
        "inline_keyboard": [[{
            "text": "🎮 Qatnashish",
            "callback_data": f"qjoin:{session_id}",
        }]]
    })
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            requests.post(
                url,
                data={"chat_id": chat_id, "text": text,
                      "parse_mode": "HTML", "reply_markup": kb},
                timeout=5,
            )
        except Exception:
            pass


@shared_task
def quiz_start_session(session_id: int):
    """Start a waiting Vizov session: send first question to all participants."""
    from tgbot.models import QuizSession, QuizParticipant, QuizQuestion, QuizOption
    import json as _j, random as _r

    session = QuizSession.objects.select_related("quiz").filter(id=session_id).first()
    if not session or session.status != "waiting":
        return

    QuizSession.objects.filter(id=session_id).update(status="active")
    session.status = "active"

    q_ids = _j.loads(session.question_order)
    if not q_ids:
        QuizSession.objects.filter(id=session_id).update(status="finished")
        return

    _quiz_send_question_to_all(session_id, 0)


@shared_task
def quiz_advance_question(session_id: int, question_idx: int):
    """Called when a question's time limit expires: tally answers, send next."""
    from tgbot.models import QuizSession
    import json as _j

    session = QuizSession.objects.filter(id=session_id).first()
    if not session or session.status != "active":
        return
    if session.current_question_idx != question_idx:
        return  # already advanced

    q_ids = _j.loads(session.question_order)
    next_idx = question_idx + 1
    if next_idx >= len(q_ids):
        quiz_finish_session(session_id)
    else:
        _quiz_send_question_to_all(session_id, next_idx)


def _quiz_send_question_to_all(session_id: int, q_idx: int):
    """Send question q_idx to every participant of the session (via DM)."""
    from tgbot.models import QuizSession, QuizParticipant, QuizQuestion, QuizOption
    import json as _j, random as _r

    session = QuizSession.objects.select_related("quiz").filter(id=session_id).first()
    if not session:
        return

    q_ids = _j.loads(session.question_order)
    if q_idx >= len(q_ids):
        quiz_finish_session(session_id)
        return

    question = QuizQuestion.objects.prefetch_related("options").filter(id=q_ids[q_idx]).first()
    if not question:
        return

    opts = list(question.options.all())
    if session.quiz.shuffle:
        _r.shuffle(opts)

    total = len(q_ids)
    text = (
        f"❓ <b>Savol {q_idx+1}/{total}</b>\n\n"
        f"{question.text}\n\n"
        f"⏱ <i>{session.quiz.time_per_question} soniya</i>"
    )
    kb_data = _j.dumps({
        "inline_keyboard": [[{
            "text": opt.text,
            "callback_data": f"qans:{session_id}:{question.id}:{opt.id}",
        }] for opt in opts]
    })

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    participants = QuizParticipant.objects.filter(session_id=session_id).select_related("user")
    for p in participants:
        try:
            requests.post(
                url,
                data={"chat_id": p.user.telegram_id, "text": text,
                      "parse_mode": "HTML", "reply_markup": kb_data},
                timeout=5,
            )
        except Exception:
            pass

    QuizSession.objects.filter(id=session_id).update(current_question_idx=q_idx)
    quiz_advance_question.apply_async(
        (session_id, q_idx),
        countdown=session.quiz.time_per_question,
    )


def quiz_finish_session(session_id: int):
    """Finalize a Vizov session and DM results to all participants."""
    from tgbot.models import QuizSession, QuizParticipant

    QuizSession.objects.filter(id=session_id).update(status="finished")
    session = QuizSession.objects.select_related("quiz").filter(id=session_id).first()
    if not session:
        return

    participants = (
        QuizParticipant.objects
        .filter(session_id=session_id)
        .select_related("user")
        .order_by("-score")
    )
    total_q = len(session.question_order.replace("[", "").replace("]", "").split(",")) if session.question_order != "[]" else 0

    lines = []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, p in enumerate(participants, 1):
        pct = int(p.score * 100 / total_q) if total_q else 0
        medal = medals.get(i, f"{i}.")
        lines.append(f"{medal} {p.user.full_name or 'Kitobxon'}: {p.score}/{total_q} ({pct}%)")

    result_text = (
        f"🏆 <b>{session.quiz.title} — Natijalar</b>\n\n"
        + "\n".join(lines) if lines else "Hech kim qatnashmadi."
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for p in participants:
        my_score = p.score
        my_pct = int(my_score * 100 / total_q) if total_q else 0
        personal = f"\n\n<b>Sizning natijangiz: {my_score}/{total_q} ({my_pct}%)</b>"
        try:
            requests.post(
                url,
                data={"chat_id": p.user.telegram_id,
                      "text": result_text + personal,
                      "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception:
            pass


@shared_task
def send_daily_personal_report():
    """23:57 — personalised end-of-day report sent to every user who reported today.
    Premium: full stats vs yesterday / 3 days / week / month / year + motivation.
    Free: ranking position, trend direction, total pages, + premium teaser."""
    import datetime as _dt
    import time as _time
    from tgbot.models import Payment as _Pay
    from django.db.models import Sum as _S

    today = timezone.localdate()
    yesterday = today - _dt.timedelta(days=1)
    d3_start = today - _dt.timedelta(days=2)
    week_start = today - _dt.timedelta(days=6)
    prev_week_s = today - _dt.timedelta(days=13)
    prev_week_e = today - _dt.timedelta(days=7)
    month_start = today - _dt.timedelta(days=29)
    prev_month_s = today - _dt.timedelta(days=59)
    prev_month_e = today - _dt.timedelta(days=30)
    year_start = _dt.date(today.year, 1, 1)
    prev_year_s = _dt.date(today.year - 1, 1, 1)
    prev_year_e = _dt.date(today.year - 1, 12, 31)

    premium_user_ids = set(
        _Pay.objects.filter(status="paid", end_date__gte=today).values_list("user_id", flat=True)
    )

    # Today's live-book reporters, ranked by pages (blocked excluded)
    today_rows = list(
        ConfirmationReport.objects
        .filter(date__date=today, is_audio=False, user__is_blocked=False)
        .values("user_id")
        .annotate(today_pages=_S("pages_read"))
        .filter(today_pages__gt=0)
        .order_by("-today_pages")
    )
    if not today_rows:
        return

    user_ids = [r["user_id"] for r in today_rows]
    total_reporters = len(user_ids)
    premium_uids_today = {uid for uid in user_ids if uid in premium_user_ids}

    def _bulk(start, end, uids=None):
        qs = ConfirmationReport.objects.filter(
            date__date__gte=start, date__date__lte=end, is_audio=False,
        )
        if uids:
            qs = qs.filter(user_id__in=uids)
        return {r["user_id"]: r["t"] or 0 for r in qs.values("user_id").annotate(t=_S("pages_read"))}

    yest_all = _bulk(yesterday, yesterday, user_ids)

    if premium_uids_today:
        d3_all = _bulk(d3_start, today, premium_uids_today)
        week_all = _bulk(week_start, today, premium_uids_today)
        pw_all = _bulk(prev_week_s, prev_week_e, premium_uids_today)
        month_all = _bulk(month_start, today, premium_uids_today)
        pm_all = _bulk(prev_month_s, prev_month_e, premium_uids_today)
        year_all = _bulk(year_start, today, premium_uids_today)
        py_all = _bulk(prev_year_s, prev_year_e, premium_uids_today)
    else:
        d3_all = week_all = pw_all = month_all = pm_all = year_all = py_all = {}

    total_at_rows = list(
        ConfirmationReport.objects.filter(is_audio=False, user_id__in=user_ids)
        .values("user_id").annotate(t=_S("pages_read"))
    )
    total_at = {r["user_id"]: r["t"] or 0 for r in total_at_rows}

    def _pct_str(old, new):
        if old == 0:
            return "▲ yangi rekord!" if new > 0 else "→ 0%"
        p = round((new - old) * 100 / old)
        if p > 0: return f"▲ +{p}%"
        if p < 0: return f"▼ {p}%"
        return "→ 0%"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    sent = 0
    for rank, row in enumerate(today_rows, start=1):
        uid = row["user_id"]
        today_p = row["today_pages"] or 0
        try:
            user = TelegramProfile.objects.filter(id=uid).first()
            if not user:
                continue

            behind = total_reporters - rank
            pct_ahead = round(behind * 100 / max(total_reporters - 1, 1))
            total_p = total_at.get(uid, 0)
            yest_p = yest_all.get(uid, 0)
            is_prem = uid in premium_user_ids

            if is_prem:
                d3_p = d3_all.get(uid, 0)
                week_p = week_all.get(uid, 0)
                pw_p = pw_all.get(uid, 0)
                month_p = month_all.get(uid, 0)
                pm_p = pm_all.get(uid, 0)
                year_p = year_all.get(uid, 0)
                py_p = py_all.get(uid, 0)

                if rank == 1:
                    motiv = "🥇 Barakalla! Bugun siz BIRINCHI bo'ldingiz! Zo'r natija!"
                elif rank <= 3:
                    motiv = f"🏅 Zo'r! Bugun TOP-3 ichida turibsiz ({rank}-o'rin)!"
                elif pct_ahead >= 75:
                    motiv = f"📈 Ajoyib! Kitobxonlarning {pct_ahead}% dan ko'p o'qidingiz!"
                elif today_p > yest_p > 0:
                    motiv = "📗 Kechagidan ko'proq o'qidingiz! O'sish davom etyapti!"
                else:
                    motiv = "📖 Har bir bet — kelajakka investitsiya. Davom eting!"

                text = (
                    f"💎 <b>Premium Hisobot — {today.strftime('%d.%m.%Y')}</b>\n\n"
                    f"✨ {motiv}\n\n"
                    f"📊 <b>Bugungi natijalar:</b>\n"
                    f"📖 Bugun o'qidingiz: <b>{today_p} bet</b>\n"
                    f"📅 Kecha: {yest_p} bet → <b>{_pct_str(yest_p, today_p)}</b>\n"
                    f"📆 Oxirgi 3 kun: <b>{d3_p} bet</b>\n"
                    f"🗓 Bu hafta: {week_p} bet (o'tgan hafta: {pw_p} bet) → <b>{_pct_str(pw_p, week_p)}</b>\n"
                    f"🗃 Bu oy: {month_p} bet (o'tgan oy: {pm_p} bet) → <b>{_pct_str(pm_p, month_p)}</b>\n"
                    f"📈 Bu yil: {year_p} bet (o'tgan yil: {py_p} bet) → <b>{_pct_str(py_p, year_p)}</b>\n\n"
                    f"📚 <b>Umumiy:</b> Jami <b>{total_p} bet</b> o'qilgan\n\n"
                    f"<i>💎 Premium a'zo sifatida bu hisobotni har kuni 23:57 da olasiz.\n"
                    f"Davom eting — har bet kelajakka investitsiya! 🚀</i>"
                )
            else:
                if today_p > yest_p > 0:
                    trend = "📈 O'sish! Kechagidan yaxshiroq"
                elif today_p < yest_p and yest_p > 0:
                    trend = "📉 Kecha ko'proq o'qigandingiz"
                else:
                    trend = "→ Barqaror sur'at"

                text = (
                    f"📊 <b>Bugungi natijangiz</b>\n\n"
                    f"📖 <b>Bugun o'qidingiz:</b> <b>{today_p} bet</b>\n"
                    f"📈 <b>Trend:</b> {trend}\n"
                    f"📚 <b>Jami o'qilgan:</b> <b>{total_p} bet</b>\n\n"
                    f"💎 <b>Premium a'zolar har kuni quyidagilarni oladi:</b>\n"
                    f"  • Bugun vs kecha, hafta, oy, yil taqqoslama (%)\n"
                    f"  • To'liq shaxsiy tahlil va motivatsion xat\n"
                    f"  • O'sish dinamikasi va batafsil tahlil\n\n"
                    f"<i>Premium obuna: menyudan 💎 Premium tugmasini bosing!</i>"
                )

            resp = requests.post(
                url,
                data={"chat_id": user.telegram_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
            if resp.ok:
                sent += 1
            elif resp.status_code == 429:
                _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception as e:  # noqa: BLE001
            print(f"send_daily_personal_report uid={uid}: {e}")
        _time.sleep(0.05)

    # ── Audio-only reporters (no live pages today) ──────────────────────────
    # These users would otherwise be skipped entirely. Send them an audio-focused
    # version of the 23:57 report.
    seen_uids = set(user_ids)
    audio_rows = list(
        ConfirmationReport.objects
        .filter(date__date=today, is_audio=True, user__is_blocked=False)
        .exclude(user_id__in=seen_uids)
        .values("user_id")
        .annotate(today_minutes=_S("minutes_listened"))
        .filter(today_minutes__gt=0)
        .order_by("-today_minutes")
    )

    if audio_rows:
        # Yesterday's audio minutes for trend
        yest_audio = {
            r["user_id"]: r["t"] or 0 for r in
            ConfirmationReport.objects
            .filter(date__date=yesterday, is_audio=True, user_id__in=[r["user_id"] for r in audio_rows])
            .values("user_id").annotate(t=_S("minutes_listened"))
        }
        total_audio_rows = list(
            ConfirmationReport.objects
            .filter(is_audio=True, user_id__in=[r["user_id"] for r in audio_rows])
            .values("user_id").annotate(t=_S("minutes_listened"))
        )
        total_audio_at = {r["user_id"]: r["t"] or 0 for r in total_audio_rows}

        for row in audio_rows:
            uid = row["user_id"]
            today_min = row["today_minutes"] or 0
            try:
                user = TelegramProfile.objects.filter(id=uid).first()
                if not user:
                    continue
                yest_min = yest_audio.get(uid, 0)
                total_min = total_audio_at.get(uid, 0)
                is_prem = uid in premium_user_ids

                if is_prem:
                    text = (
                        f"💎 <b>Premium Hisobot — {today.strftime('%d.%m.%Y')}</b>\n\n"
                        f"🎧 Bugun audio eshitdingiz — barakalla!\n\n"
                        f"🎧 Bugun: <b>{today_min} daqiqa</b>\n"
                        f"📅 Kecha: {yest_min} daqiqa → <b>{_pct_str(yest_min, today_min)}</b>\n"
                        f"📚 Jami eshitilgan: <b>{total_min} daqiqa</b>\n\n"
                        f"<i>💎 Premium a'zo sifatida bu hisobotni har kuni 23:57 da olasiz.</i>"
                    )
                else:
                    if today_min > yest_min > 0:
                        trend = "📈 O'sish! Kechagidan ko'proq"
                    elif today_min < yest_min and yest_min > 0:
                        trend = "📉 Kecha ko'proq eshitgandingiz"
                    else:
                        trend = "→ Barqaror sur'at"
                    text = (
                        f"📊 <b>Bugungi audio natijangiz</b>\n\n"
                        f"🎧 <b>Bugun:</b> {today_min} daqiqa\n"
                        f"📈 <b>Trend:</b> {trend}\n"
                        f"📚 <b>Jami eshitilgan:</b> {total_min} daqiqa\n\n"
                        f"<i>💎 Premium olib to'liq tahlil va taqqoslama oling — menyudan 💎 Premium.</i>"
                    )
                resp = requests.post(
                    url,
                    data={"chat_id": user.telegram_id, "text": text, "parse_mode": "HTML"},
                    timeout=5,
                )
                if resp.ok:
                    sent += 1
                elif resp.status_code == 429:
                    _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
            except Exception as e:  # noqa: BLE001
                print(f"send_daily_personal_report audio uid={uid}: {e}")
            _time.sleep(0.05)

    print(f"send_daily_personal_report: sent={sent}/{total_reporters}")


# ────────────────────────────────────────────────────────────────────────
# Weekly AI Report for Premium users (every Saturday evening 20:00)
# Uses Google Gemini for text + Imagen 3 for a personal report card image.
# ────────────────────────────────────────────────────────────────────────

def _generate_report_image(
    full_name: str,
    week_pages: int,
    week_audio_minutes: int,
    streak: int,
    total_pages: int,
    books_finished_week: int,
    rank_pct_ahead: int,
    new_achievement_titles: list,
) -> bytes | None:
    """
    Generate a personal report card image via Google Imagen 3.
    Returns raw PNG bytes or None on failure.
    """
    try:
        import google.generativeai as genai
        api_key = env.str("GEMINI_API_KEY", default="")
        if not api_key:
            return None
        genai.configure(api_key=api_key)
        imagen = genai.ImageGenerationModel("imagen-3.0-generate-002")

        achiev_text = ""
        if new_achievement_titles:
            achiev_text = f"Achievement badges: {', '.join(new_achievement_titles[:3])}. "

        prompt = (
            f"A beautiful personalized weekly reading report card for '{full_name}'. "
            f"Modern, clean infographic style with warm golden and deep blue colors. "
            f"Show these stats clearly: "
            f"{week_pages} pages read this week, "
            f"{week_audio_minutes} audio minutes, "
            f"{streak}-day reading streak, "
            f"{total_pages} total pages all time, "
            f"{books_finished_week} books finished this week, "
            f"top {100 - rank_pct_ahead}% reader ranking. "
            f"{achiev_text}"
            f"Include decorative book and star elements. "
            f"Text on card must be in English. No people faces. "
            f"16:9 landscape orientation, high quality, professional design."
        )
        result = imagen.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio="16:9",
            safety_filter_level="block_only_high",
        )
        if result.images:
            return result.images[0]._pil_image.tobytes("jpeg", "RGB") if hasattr(result.images[0], '_pil_image') else None
    except Exception as e:
        print(f"[weekly_ai_report] Imagen error: {e}")
    return None


def _send_weekly_report_to_user(
    user,
    week_start,
    week_end,
    premium_user_ids: set,
) -> bool:
    """Build stats, call AI, send report to one premium user. Returns True on success."""
    import datetime as _dt
    from tgbot.models import UserAchievement as _UA, BooksToRead as _BTR
    from tgbot.services.weekly_ai_report import generate_weekly_report
    from tgbot.services.achievements import compute_user_stats, _max_consecutive_days
    from django.db.models import Sum as _S, F as _F, Max as _M
    from django.utils.html import escape as _esc

    uid = user.id
    lang = user.language or "uz"

    # ── This week's stats ──────────────────────────────────────────────
    week_pages = (
        ConfirmationReport.objects
        .filter(user=user, date__date__gte=week_start, date__date__lte=week_end, is_audio=False)
        .aggregate(t=_S("pages_read"))["t"] or 0
    )
    prev_week_start = week_start - _dt.timedelta(days=7)
    prev_week_end = week_end - _dt.timedelta(days=7)
    prev_week_pages = (
        ConfirmationReport.objects
        .filter(user=user, date__date__gte=prev_week_start, date__date__lte=prev_week_end, is_audio=False)
        .aggregate(t=_S("pages_read"))["t"] or 0
    )
    week_audio = (
        ConfirmationReport.objects
        .filter(user=user, date__date__gte=week_start, date__date__lte=week_end, is_audio=True)
        .aggregate(t=_S("minutes_listened"))["t"] or 0
    )
    prev_week_audio = (
        ConfirmationReport.objects
        .filter(user=user, date__date__gte=prev_week_start, date__date__lte=prev_week_end, is_audio=True)
        .aggregate(t=_S("minutes_listened"))["t"] or 0
    )
    books_finished_week = _BTR.objects.filter(
        user=user, is_audio=False,
        current_page__gte=_F("total_pages"), total_pages__gt=0,
        updated_at__date__gte=week_start, updated_at__date__lte=week_end,
    ).count()
    total_books_finished = _BTR.objects.filter(
        user=user, is_audio=False,
        current_page__gte=_F("total_pages"), total_pages__gt=0,
    ).count()
    total_pages_all_time = (
        ConfirmationReport.objects.filter(user=user, is_audio=False)
        .aggregate(t=_S("pages_read"))["t"] or 0
    )

    # ── Streak ──────────────────────────────────────────────────────────
    streak = _max_consecutive_days(user)

    # ── Ranking this week ────────────────────────────────────────────────
    all_week_pages = list(
        ConfirmationReport.objects
        .filter(date__date__gte=week_start, date__date__lte=week_end, is_audio=False, user__is_blocked=False)
        .values("user_id").annotate(t=_S("pages_read"))
        .values_list("t", flat=True)
    )
    rank_pct_ahead = 0
    if all_week_pages and len(all_week_pages) > 1:
        behind = sum(1 for p in all_week_pages if (p or 0) < week_pages)
        rank_pct_ahead = round(behind * 100 / max(len(all_week_pages) - 1, 1))

    # ── Best day & avg ────────────────────────────────────────────────────
    from django.db.models.functions import TruncDate as _TD
    day_rows = list(
        ConfirmationReport.objects
        .filter(user=user, date__date__gte=week_start, date__date__lte=week_end, is_audio=False)
        .annotate(_d=_TD("date")).values("_d").annotate(dp=_S("pages_read"))
    )
    best_day_pages = max((r["dp"] or 0 for r in day_rows), default=0)
    avg_pages_per_day = week_pages / 7

    # ── New achievements this week ─────────────────────────────────────
    new_achievements = list(
        _UA.objects.filter(
            user=user,
            created_at__date__gte=week_start,
            created_at__date__lte=week_end,
        ).values("code")
    )
    # Map codes to achievement dicts
    from tgbot.services.achievements import find_achievement
    ach_dicts = [find_achievement(a["code"]) for a in new_achievements if find_achievement(a["code"])]

    # ── Generate AI text ──────────────────────────────────────────────
    ai_text = generate_weekly_report(
        full_name=user.full_name or user.username or "Kitobxon",
        week_pages=week_pages,
        prev_week_pages=prev_week_pages,
        week_audio_minutes=week_audio,
        prev_week_audio_minutes=prev_week_audio,
        books_finished_week=books_finished_week,
        total_books_finished=total_books_finished,
        total_pages_all_time=total_pages_all_time,
        streak=streak,
        new_achievements=ach_dicts,
        rank_pct_ahead=rank_pct_ahead,
        avg_pages_per_day_week=avg_pages_per_day,
        best_day_pages=best_day_pages,
        language=lang,
    )

    header = (
        "💎 <b>Haftalik Premium Hisobot</b> 📊" if lang != "ru"
        else "💎 <b>Еженедельный Premium Отчёт</b> 📊"
    )
    full_text = f"{header}\n\n{ai_text}"

    # ── Achievement Tabriknoma block ─────────────────────────────────
    if ach_dicts:
        if lang == "ru":
            ach_header = "\n\n🏆 <b>Ваши достижения этой недели:</b>\n"
        else:
            ach_header = "\n\n🏆 <b>Bu haftadagi yutuqlaringiz:</b>\n"
        ach_lines = []
        for ach in ach_dicts[:5]:
            pts = ach.get("points", 0)
            t = ach.get("title_ru" if lang == "ru" else "title_uz") or ach.get("title_uz", "")
            pts_str = f" <i>(+{pts} Kitobcha)</i>" if pts else ""
            ach_lines.append(f"{ach['emoji']} <b>{t}</b>{pts_str}")
        full_text += ach_header + "\n".join(ach_lines)

    # ── Try to send with Imagen 3 card image ─────────────────────────
    url_photo = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    url_msg = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    ach_titles = [
        (a.get("title_uz") or a.get("title_ru") or "")
        for a in ach_dicts
    ]
    img_bytes = _generate_report_image(
        full_name=user.full_name or "Kitobxon",
        week_pages=week_pages,
        week_audio_minutes=week_audio,
        streak=streak,
        total_pages=total_pages_all_time,
        books_finished_week=books_finished_week,
        rank_pct_ahead=rank_pct_ahead,
        new_achievement_titles=ach_titles,
    )

    try:
        if img_bytes:
            import io
            resp = requests.post(
                url_photo,
                data={"chat_id": user.telegram_id, "parse_mode": "HTML"},
                files={"photo": ("report.jpg", io.BytesIO(img_bytes), "image/jpeg")},
                timeout=15,
            )
            if resp.ok:
                # Send text as follow-up message
                requests.post(
                    url_msg,
                    data={"chat_id": user.telegram_id, "text": full_text, "parse_mode": "HTML"},
                    timeout=10,
                )
                return True
        # Fallback: text only
        resp = requests.post(
            url_msg,
            data={"chat_id": user.telegram_id, "text": full_text, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.ok
    except Exception as e:
        print(f"[weekly_ai_report] send failed uid={user.id}: {e}")
        return False


@shared_task
def send_weekly_ai_report():
    """
    Every Saturday at 20:00 Tashkent — send AI-generated weekly report
    to all active Premium users.
    Only users who reported at least once during the week are included.
    """
    import datetime as _dt
    import time as _time
    from tgbot.models import Payment as _Pay

    today = timezone.localdate()
    # Week: last 7 days (Mon–Sun or rolling 7 days ending today)
    week_end = today
    week_start = today - _dt.timedelta(days=6)

    premium_ids = set(
        _Pay.objects.filter(
            status="paid", end_date__gte=today
        ).values_list("user_id", flat=True)
    )
    if not premium_ids:
        print("[weekly_ai_report] No premium users found.")
        return

    # Only premium users who reported this week
    active_premium_user_ids = set(
        ConfirmationReport.objects.filter(
            date__date__gte=week_start,
            date__date__lte=week_end,
            user_id__in=premium_ids,
            user__is_blocked=False,
        ).values_list("user_id", flat=True).distinct()
    )

    users = list(
        TelegramProfile.objects.filter(
            id__in=active_premium_user_ids, is_registered=True, is_blocked=False
        )
    )
    print(f"[weekly_ai_report] Sending to {len(users)} premium users...")

    sent = failed = 0
    for user in users:
        try:
            ok = _send_weekly_report_to_user(
                user=user,
                week_start=week_start,
                week_end=week_end,
                premium_user_ids=premium_ids,
            )
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[weekly_ai_report] user {user.id} failed: {e}")
            failed += 1
        _time.sleep(0.15)  # Gemini + Imagen API rate limit protection

    print(f"[weekly_ai_report] done. sent={sent} failed={failed}")


# ────────────────────────────────────────────────────────────────────────
# Kitobxonlik Challenge tasks
# ────────────────────────────────────────────────────────────────────────

CHALLENGE_POOL = [
    {"emoji": "📖", "title": "50-bet Challenge",        "description": "Har kuni kamida 50 bet kitob o'qing — 3 kun davomida!",                   "condition_type": "pages_daily",     "condition_value": 50},
    {"emoji": "📗", "title": "60-bet Challenge",        "description": "Har kuni 60 bet o'qing — 3 kunlik qizg'in raqobat!",                      "condition_type": "pages_daily",     "condition_value": 60},
    {"emoji": "📘", "title": "70-bet Challenge",        "description": "Har kuni 70 bet — mutolaa sur'atini oshiring!",                            "condition_type": "pages_daily",     "condition_value": 70},
    {"emoji": "💯", "title": "100-bet Challenge",       "description": "Har kuni 100 bet o'qing — yuz betlik marafon!",                            "condition_type": "pages_daily",     "condition_value": 100},
    {"emoji": "🔥", "title": "150-bet Challenge",       "description": "Har kuni 150 bet — shiddatli mutolaa vaqti!",                              "condition_type": "pages_daily",     "condition_value": 150},
    {"emoji": "🎧", "title": "5-daqiqa Audio Challenge","description": "Har kuni kamida 5 daqiqa audiokitob eshiting!",                           "condition_type": "audio_daily",     "condition_value": 5},
    {"emoji": "🎵", "title": "10-daqiqa Audio Challenge","description": "Har kuni 10 daqiqa audiokitob — quloqlaringizga ziyofat!",               "condition_type": "audio_daily",     "condition_value": 10},
    {"emoji": "🎼", "title": "20-daqiqa Audio Challenge","description": "Har kuni 20 daqiqa audiokitob eshiting — uch kun davomida!",             "condition_type": "audio_daily",     "condition_value": 20},
    {"emoji": "👥", "title": "Taklif Challenge",        "description": "Har kuni 1 ta do'stingizni Kitob Challengega taklif qiling!",             "condition_type": "referrals_daily", "condition_value": 1},
    {"emoji": "✍️","title": "Taqriz Challenge",        "description": "Har kuni kamida 200 belgidan iborat mazmunli xulosa bilan hisobot yuboring!", "condition_type": "review_daily",  "condition_value": 200},
]


def _finalize_challenge_results(challenge_id: int):
    """Award prizes and mark challenge finished. Called before announcing next challenge."""
    from tgbot.models import Challenge, ChallengeParticipant

    challenge = Challenge.objects.filter(id=challenge_id).first()
    if not challenge:
        return

    Challenge.objects.filter(id=challenge_id).update(is_active=False)

    participants = list(
        ChallengeParticipant.objects
        .filter(challenge=challenge, reward_given=False)
        .select_related("user")
        .order_by("-days_completed", "last_completed_at", "joined_at")
    )
    if not participants:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    prize_map = {1: 200, 2: 100, 3: 50}

    # Assign ranks sequentially (sorted above)
    for rank, p in enumerate(participants, start=1):
        days = p.days_completed
        if rank <= 3 and days >= 3:
            kitobcha = prize_map[rank]
        elif days >= 3:
            kitobcha = 25
        elif days == 2:
            kitobcha = 15
        elif days == 1:
            kitobcha = 5
        else:
            kitobcha = 0

        ChallengeParticipant.objects.filter(id=p.id).update(rank=rank, reward_given=True)

        if kitobcha > 0:
            try:
                p.user.update_ball(True, kitobcha)
            except Exception as e:
                print(f"challenge reward failed uid={p.user.id}: {e}")

        if days == 0:
            continue

        place_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "🏅")
        dm = (
            f"🏆 <b>{challenge.emoji} {challenge.title} — Natija!</b>\n\n"
            f"{place_emoji} O'rningiz: <b>{rank}</b>\n"
            f"✅ Bajargan kunlar: <b>{days}/3</b>\n"
            + (f"🪙 Mukofot: <b>+{kitobcha} Kitobcha</b>" if kitobcha > 0 else "📭 Mukofot yo'q")
            + "\n\nKeyingi challengeni kuting! 🚀"
        )
        try:
            requests.post(
                url,
                data={"chat_id": p.user.telegram_id, "text": dm, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception as e:
            print(f"challenge result DM failed uid={p.user.id}: {e}")

    print(f"_finalize_challenge_results: challenge_id={challenge_id}, {len(participants)} processed")

    # Admin summary — podium + stats
    try:
        import os as _os
        admin_gid = _os.environ.get("ADMIN_GROUP_ID", "")
        if admin_gid:
            top3 = participants[:3]
            podium_lines = []
            for rank, p in enumerate(top3, 1):
                days = p.days_completed
                prize = {1: 200, 2: 100, 3: 50}.get(rank, 25)
                emoji = {1: "🥇", 2: "🥈", 3: "🥉"}[rank]
                name = (p.user.full_name or f"uid={p.user.id}")[:30]
                podium_lines.append(f"{emoji} {name} — {days}/3 kun (+{prize} Kitobcha)")
            done3 = sum(1 for p in participants if p.days_completed >= 3)
            done2 = sum(1 for p in participants if p.days_completed == 2)
            done1 = sum(1 for p in participants if p.days_completed == 1)
            admin_text = (
                f"📊 <b>Challenge yakunlandi: {challenge.emoji} {challenge.title}</b>\n\n"
                + ("\n".join(podium_lines) or "—")
                + f"\n\n👥 Jami: <b>{len(participants)}</b> ishtirokchi\n"
                f"✅ 3 kun: {done3} | 📊 2 kun: {done2} | 1 kun: {done1}"
            )
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": admin_gid, "text": admin_text, "parse_mode": "HTML"},
                timeout=5,
            )
    except Exception as e:
        print(f"challenge finalize admin notif failed: {e}")


@shared_task
def announce_challenge():
    """Every 3 days: finalize previous challenge, pick next, announce to groups + users."""
    import datetime as _dt
    import random as _rand
    import time as _time
    from tgbot.models import Challenge

    # Finalize any still-active challenge
    prev = Challenge.objects.filter(is_active=True).first()
    if prev:
        _finalize_challenge_results(prev.id)

    # Avoid repeating last 3 challenge titles
    recent = list(Challenge.objects.order_by("-created_at").values_list("title", flat=True)[:3])
    pool = [c for c in CHALLENGE_POOL if c["title"] not in recent] or CHALLENGE_POOL
    template = _rand.choice(pool)

    today = timezone.localdate()
    end_date = today + _dt.timedelta(days=2)  # 3-day challenge

    challenge = Challenge.objects.create(
        title=template["title"],
        description=template["description"],
        emoji=template["emoji"],
        condition_type=template["condition_type"],
        condition_value=template["condition_value"],
        start_date=today,
        end_date=end_date,
        is_active=True,
        announced_at=timezone.now(),
    )

    date_range = f"{today.strftime('%d.%m')} – {end_date.strftime('%d.%m.%Y')}"
    text = (
        f"🏆 <b>YANGI KITOBXONLIK CHALLENGE!</b>\n\n"
        f"{challenge.emoji} <b>{challenge.title}</b>\n\n"
        f"📋 <b>Shart:</b> {challenge.description}\n"
        f"📅 <b>Muddat:</b> {date_range} (3 kun)\n\n"
        f"🎁 <b>Mukofotlar:</b>\n"
        f"🥇 1-o'rin: <b>200 Kitobcha</b>\n"
        f"🥈 2-o'rin: <b>100 Kitobcha</b>\n"
        f"🥉 3-o'rin: <b>50 Kitobcha</b>\n"
        f"✅ 3 kun bajargan (4+): 25 Kitobcha\n"
        f"📊 2 kun: 15 Kitobcha | 1 kun: 5 Kitobcha\n\n"
        f"👇 Qatnashish uchun tugmani bosing!"
    )
    title_short = challenge.title
    if len(title_short) > 25:
        title_short = title_short[:22] + "..."
    keyboard = json.dumps({
        "inline_keyboard": [[{
            "text": f"🎮 \"{title_short}\"da qatnashaman! {challenge.emoji}",
            "callback_data": f"join_challenge:{challenge.id}",
        }]]
    })

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for group_id in _group_chat_ids():
        try:
            requests.post(
                url,
                data={"chat_id": group_id, "text": text, "parse_mode": "HTML",
                      "reply_markup": keyboard},
                timeout=10,
            )
        except Exception as e:
            print(f"challenge announce group {group_id}: {e}")

    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent = 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                      "reply_markup": keyboard},
                timeout=5,
            )
            if resp.ok:
                sent += 1
            elif resp.status_code == 429:
                _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception:
            pass
        _time.sleep(0.05)
    print(f"announce_challenge: challenge_id={challenge.id} sent={sent}")

    # Admin notification — new challenge summary
    try:
        import os as _os
        admin_gid = _os.environ.get("ADMIN_GROUP_ID", "")
        if admin_gid:
            total_users = TelegramProfile.objects.filter(is_registered=True, is_blocked=False).count()
            admin_text = (
                f"🚀 <b>Yangi Challenge e'lon qilindi!</b>\n\n"
                f"{challenge.emoji} <b>{challenge.title}</b>\n"
                f"📋 {challenge.description}\n"
                f"📅 {date_range}\n"
                f"⚙️ Shart turi: <code>{challenge.condition_type}</code> = {challenge.condition_value}\n\n"
                f"📨 Jo'natildi: <b>{sent}</b> / {total_users} foydalanuvchi"
            )
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": admin_gid, "text": admin_text, "parse_mode": "HTML"},
                timeout=5,
            )
    except Exception as e:
        print(f"challenge announce admin notif failed: {e}")


@shared_task
def daily_challenge_check():
    """23:50 — auto-verify today's condition for each challenge participant."""
    from tgbot.models import Challenge, ChallengeParticipant, ConfirmationReport, UserReferal
    from django.db.models import Sum
    from django.db.models.functions import Length

    today = timezone.localdate()
    today_str = today.isoformat()

    challenge = Challenge.objects.filter(is_active=True).first()
    if not challenge or today < challenge.start_date or today > challenge.end_date:
        return

    ctype = challenge.condition_type
    cval = challenge.condition_value

    participants = list(
        ChallengeParticipant.objects.filter(challenge=challenge).select_related("user")
    )
    updated = 0
    for p in participants:
        if today_str in (p.completed_dates or []):
            continue

        user = p.user
        verified = False

        if ctype == "pages_daily":
            pages = ConfirmationReport.objects.filter(
                user=user, date__date=today, is_audio=False
            ).aggregate(s=Sum("pages_read"))["s"] or 0
            verified = pages >= cval

        elif ctype == "audio_daily":
            minutes = ConfirmationReport.objects.filter(
                user=user, date__date=today, is_audio=True
            ).aggregate(s=Sum("minutes_listened"))["s"] or 0
            verified = minutes >= cval

        elif ctype == "referrals_daily":
            count = UserReferal.objects.filter(referrer=user, created_at__date=today).count()
            verified = count >= cval

        elif ctype == "review_daily":
            verified = ConfirmationReport.objects.filter(
                user=user, date__date=today
            ).annotate(_l=Length("conclusion")).filter(_l__gte=cval).exists()

        if verified:
            dates = list(p.completed_dates or [])
            dates.append(today_str)
            new_days = len(dates)
            last_at = timezone.now() if new_days >= 3 else p.last_completed_at
            ChallengeParticipant.objects.filter(id=p.id).update(
                completed_dates=dates,
                days_completed=new_days,
                last_completed_at=last_at,
            )
            updated += 1

    print(f"daily_challenge_check: challenge_id={challenge.id}, verified={updated}/{len(participants)}")


@shared_task
def challenge_reminder():
    """Daily at 18:00 — remind active challenge participants of today's condition."""
    from tgbot.models import Challenge, ChallengeParticipant

    today = timezone.localdate()
    challenge = Challenge.objects.filter(is_active=True).first()
    if not challenge or today < challenge.start_date or today > challenge.end_date:
        return

    today_str = today.isoformat()
    days_left = (challenge.end_date - today).days

    participants = list(
        ChallengeParticipant.objects.filter(challenge=challenge).select_related("user")
    )
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    sent = 0
    for p in participants:
        if today_str in (p.completed_dates or []):
            continue  # already done today
        try:
            text = (
                f"⏰ <b>Challenge eslatmasi!</b>\n\n"
                f"{challenge.emoji} <b>{challenge.title}</b>\n"
                f"📋 {challenge.description}\n\n"
                f"✅ Bajarilgan kunlar: {p.days_completed}/3\n"
                f"📅 Yana {days_left} kun qoldi\n\n"
                "Shartni bajargach, kabinetingizdan ✅ Bajarldim tugmasini bosing!"
            )
            kb = json.dumps({"inline_keyboard": [[
                {"text": "✅ Bajarldim!", "callback_data": f"challenge_done:{challenge.id}"}
            ]]})
            requests.post(
                url,
                data={"chat_id": p.user.telegram_id, "text": text,
                      "parse_mode": "HTML", "reply_markup": kb},
                timeout=5,
            )
            sent += 1
        except Exception as e:
            print(f"challenge_reminder failed uid={p.user.id}: {e}")

    print(f"challenge_reminder: challenge_id={challenge.id}, sent={sent}")


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


@shared_task
def send_ai_report_to_admin(admin_tg_id: int = 917456291, lang: str = "uz"):
    """
    One-off task: generate AI weekly report (Gemini text + Imagen 3 image)
    using demo data and send to admin_tg_id. Used for manual testing.
    Standalone — does not touch user DB.
    """
    import io as _io
    import os as _os
    import datetime as _dt
    import requests as _req
    import google.generativeai as _genai

    token = _os.environ.get("API_TOKEN", "")
    gemini_key = _os.environ.get("GEMINI_API_KEY", "")
    if not token:
        print("[send_ai_report_to_admin] API_TOKEN not set")
        return

    d = {
        "full_name": "Aziz Karimov",
        "week_pages": 312,
        "prev_week_pages": 245,
        "audio_minutes": 87,
        "streak": 12,
        "total_pages": 4350,
        "books_week": 1,
        "rank_pct_ahead": 78,
    }

    # 1. Gemini text
    ai_text = None
    if gemini_key:
        try:
            _genai.configure(api_key=gemini_key)
            model = _genai.GenerativeModel("gemini-2.0-flash")
            p = round((d["week_pages"] - d["prev_week_pages"]) * 100 / max(d["prev_week_pages"], 1))
            pct = f"▲ +{p}%" if p > 0 else f"▼ {p}%"
            ah, am = divmod(d["audio_minutes"], 60)
            audio_str = f"{ah} soat {am} daqiqa" if ah else f"{d['audio_minutes']} daqiqa"
            if lang == "ru":
                prompt = (
                    f"Ты тренер по чтению. Напиши {d['full_name']} персональный еженедельный отчёт. "
                    f"Стиль: тёплый, воодушевляющий. Telegram HTML (<b>,<i>). 180-250 слов. Имя 2+ раза. "
                    f"Данные: {d['week_pages']} стр ({pct}), аудио {audio_str}, "
                    f"книг {d['books_week']}, всего {d['total_pages']} стр, "
                    f"стрик {d['streak']} дней, топ {100-d['rank_pct_ahead']}%. Только текст."
                )
            else:
                prompt = (
                    f"Sen kitobxonlik trenerisisan. {d['full_name']} ga shaxsiy haftalik hisobot yoz. "
                    f"Uslub: iliq, rag'batlantiruvchan. Telegram HTML (<b>,<i>). 180-250 so'z. Ism 2+ marta. "
                    f"Ma'lumotlar: {d['week_pages']} bet ({pct}), audio {audio_str}, "
                    f"kitoblar {d['books_week']} ta, jami {d['total_pages']} bet, "
                    f"streak {d['streak']} kun, top {100-d['rank_pct_ahead']}%. Faqat matn."
                )
            resp = model.generate_content(prompt, generation_config={"temperature": 0.85, "max_output_tokens": 600})
            ai_text = resp.text.strip()
            print("[send_ai_report_to_admin] Gemini text OK")
        except Exception as e:
            print(f"[send_ai_report_to_admin] Gemini error: {e}")

    if not ai_text:
        ai_text = (
            f"Ajoyib natija, <b>{d['full_name']}</b>! Bu hafta — <b>{d['week_pages']} bet</b>. "
            f"🔥 Streak <b>{d['streak']} kun</b>. Davom eting! 🚀"
        )

    header = "💎 <b>Haftalik Premium Hisobot</b> 📊 <i>[TEST]</i>" if lang != "ru" else "💎 <b>Еженедельный Premium Отчёт</b> 📊 <i>[ТЕСТ]</i>"
    ach = (
        "\n\n🏆 <b>Bu haftadagi yutuqlar:</b>\n"
        "🔥 <b>7 kunlik streak</b> <i>(+70 Kitobcha)</i>\n"
        "📚 <b>Yuz bet</b> <i>(+20 Kitobcha)</i>"
    ) if lang != "ru" else (
        "\n\n🏆 <b>Достижения этой недели:</b>\n"
        "🔥 <b>Серия 7 дней</b> <i>(+70 Kitobcha)</i>\n"
        "📚 <b>Сто страниц</b> <i>(+20 Kitobcha)</i>"
    )
    full_text = f"{header}\n\n{ai_text}{ach}"

    # 2. Imagen 3 — branded weekly report card
    img_bytes = None
    if gemini_key:
        try:
            _genai.configure(api_key=gemini_key)
            imagen = _genai.ImageGenerationModel("imagen-3.0-generate-002")

            # Compute the date range for "this week" (last 7 days inclusive)
            week_end_d = timezone.localdate()
            week_start_d = week_end_d - _dt.timedelta(days=6)
            date_range = f"{week_start_d.strftime('%b %d')} – {week_end_d.strftime('%b %d, %Y')}"
            ah, am = divmod(d["audio_minutes"], 60)
            audio_label = f"{ah}h {am}m" if ah else f"{d['audio_minutes']}m"

            prompt_img = (
                "Minimalist luxury weekly reading certificate from 'KITOB CHALLENGE', "
                "an elite Telegram reading community. "
                "Style: clean editorial design, lots of negative space, serene and sophisticated. "
                "PALETTE: soft cream / warm ivory / pearl white background (95% of canvas), "
                "with luxury accents of deep emerald green, antique gold foil, and matte charcoal black "
                "used sparingly on key elements only. "
                "Subtle paper-grain texture, faint gold flecks for premium feel. "
                "LAYOUT (16:9 landscape, generous whitespace, perfectly balanced): "
                "TOP — a slim gold horizontal divider line. Above it: tiny minimalist open-book "
                "logo mark centered. Just below: refined serif wordmark 'KITOB CHALLENGE' in deep "
                "charcoal, letter-spaced. Tiny sans-serif tagline below: 'WEEKLY READER REPORT'. "
                f"DATE BADGE — slim outlined gold pill containing '{date_range}'. "
                f"CENTERPIECE — elegant calligraphic script: 'Presented to {d['full_name']}' "
                "(large, deep charcoal with subtle gold underline flourish). "
                "STATS — four minimalist cards in a single row, each with: a thin emerald-green "
                "icon outline at top, then a very large gold numeral, then a small uppercase "
                "label in charcoal. Cards have no heavy borders, just airy spacing: "
                f"📖  {d['week_pages']}  PAGES READ  ·  "
                f"🎧  {audio_label}  AUDIO TIME  ·  "
                f"🔥  {d['streak']}  DAY STREAK  ·  "
                f"🏆  TOP {100 - d['rank_pct_ahead']}%  READER. "
                f"FINE PRINT line below: 'All-time pages: {d['total_pages']}   |   "
                f"Books finished this week: {d['books_week']}' in small refined typography. "
                "BOTTOM — italic serif gratitude line, deep emerald: "
                "'Thank you for your dedication and unwavering perseverance.' "
                "Tiny ornamental gold flourish underneath. "
                "Corners: small minimalist gold corner-mark brackets, like a luxury card frame. "
                "All English text must be perfectly spelled, crisp typography, no garbled letters. "
                "No people, no faces. Magazine-quality minimalist luxury aesthetic, "
                "feels like a Hermès or Aesop print piece. 16:9, ultra-detailed."
            )
            result = imagen.generate_images(
                prompt=prompt_img,
                number_of_images=1,
                aspect_ratio="16:9",
                safety_filter_level="block_only_high",
            )
            if result.images:
                img = result.images[0]
                for attr in ("_pil_image", "image", "_image"):
                    pil = getattr(img, attr, None)
                    if pil is not None:
                        buf = _io.BytesIO()
                        pil.save(buf, format="JPEG", quality=90)
                        img_bytes = buf.getvalue()
                        break
                if img_bytes is None:
                    for attr in ("_image_bytes", "image_bytes", "data"):
                        raw = getattr(img, attr, None)
                        if isinstance(raw, (bytes, bytearray)):
                            img_bytes = bytes(raw)
                            break
            print(f"[send_ai_report_to_admin] Imagen: {'OK' if img_bytes else 'no bytes'}")
        except Exception as e:
            print(f"[send_ai_report_to_admin] Imagen error: {e}")

    # 3. Send
    if img_bytes:
        _req.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": admin_tg_id, "parse_mode": "HTML"},
            files={"photo": ("report.jpg", _io.BytesIO(img_bytes), "image/jpeg")},
            timeout=20,
        )
    _req.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": admin_tg_id, "text": full_text, "parse_mode": "HTML"},
        timeout=10,
    )
    print(f"[send_ai_report_to_admin] done → {admin_tg_id}")
