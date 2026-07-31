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


def send_notification(chat_id, text, photo=None, reply_markup=None, thread_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if photo:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    data = {
        "chat_id": chat_id,
        "parse_mode": "HTML"
    }
    if thread_id:
        data["message_thread_id"] = thread_id

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


@shared_task
def delete_message_after_delay(chat_id, message_id):
    """Delete a Telegram message. Scheduled via apply_async(countdown=N)."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
            data={"chat_id": chat_id, "message_id": message_id},
            timeout=5,
        )
    except Exception as e:
        print(f"delete_message_after_delay failed for {chat_id}/{message_id}: {e}")




def send_message(chat_id, text, thread_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_length = 4096
    for i in range(0, len(text), max_length):
        chunk = text[i:i+max_length]

        data = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML"
        }
        if thread_id:
            data["message_thread_id"] = thread_id
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

    for _cid, _tid in _leaderboard_targets():
        send_notification(_cid, message, thread_id=_tid)


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
            message += f"{index}) <b>{badge}{name}</b>: {stat}\n\n"
    else:
        message = "📚 Bugun hisobot yuborgan foydalanuvchilar yo'q."

    for _cid, _tid in _leaderboard_targets():
        send_message(_cid, message, thread_id=_tid)


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
            message += f"{index}. <b>{badge}{full_name}</b>: {stat}\n"

    for _cid, _tid in _leaderboard_targets():
        send_message(_cid, message, thread_id=_tid)


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
    from django.core.cache import cache

    today = timezone.localdate()
    today_str = today.isoformat()
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

    # group_chat_id -> ordered list of users to check membership against this chat.
    # Dedupe by chat_id: GENERAL_GROUP_ID currently equals GIRLS_GROUP_ID, so
    # without this the shared group would receive TWO messages (gender + general).
    targets = []
    seen = set()
    if boys_chat and boys_chat not in seen:
        targets.append((boys_chat, [u for u in non_reporters if u.gender == "male"]))
        seen.add(boys_chat)
    if girls_chat and girls_chat not in seen:
        targets.append((girls_chat, [u for u in non_reporters if u.gender == "female"]))
        seen.add(girls_chat)
    if general_chat and general_chat not in seen:
        # General group: everyone (membership check below filters to real members).
        targets.append((general_chat, list(non_reporters)))
        seen.add(general_chat)

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

        # Idempotency guard: post the unread list to each group AT MOST once
        # per day, even if the task somehow runs twice (Celery redelivery on a
        # long run, a duplicate beat, or a retry). cache.add is atomic, so a
        # second run for the same chat/day is skipped. This is what actually
        # fixes the "girls group gets the list twice" report.
        if not cache.add(f"unread_posted:{chat_id}:{today_str}", 1, 60 * 60 * 20):
            print(f"users_unread_book: already posted to {chat_id} today, skipping")
            continue

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
        message += f"{index}. <b>{badge}{full_name}</b>: {stat}\n"
    total_stat = _format_top_stat(grand_pages, grand_minutes)
    message += f"\n📊 Jami: <b>{total_stat}</b>"
    sponsor = _consume_leaderboard_sponsor()
    if sponsor:
        message += f"\n\n🏷 <i>Ushbu reyting homiysi: {escape(sponsor.full_name or 'Kitobxon')}</i>"
    return message


def _consume_leaderboard_sponsor():
    """Atomically claim the oldest unused Market 'Reyting sponsorligi'
    purchase, mark it used, and return the sponsoring TelegramProfile (or
    None if no one's queued). Consumed once per call, so at most one
    broadcast gets credited per purchase."""
    from django.db import transaction
    from tgbot.models import LeaderboardSponsor
    with transaction.atomic():
        sponsor = (
            LeaderboardSponsor.objects.select_for_update()
            .filter(used_at__isnull=True)
            .order_by("created_at")
            .select_related("user")
            .first()
        )
        if not sponsor:
            return None
        sponsor.used_at = timezone.now()
        sponsor.save(update_fields=["used_at"])
        return sponsor.user


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

    group_targets = _leaderboard_targets()
    print(f"_broadcast_top_to_groups_and_users: sending to groups {group_targets}")
    for group_id, thread_id in group_targets:
        try:
            data = {
                "chat_id": group_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
                "reply_markup": keyboard,
            }
            if thread_id:
                data["message_thread_id"] = thread_id
            resp = requests.post(url, data=data, timeout=10)
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
    for _cid, _tid in _leaderboard_targets():
        send_message(_cid, msg, thread_id=_tid)


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
    # ── Referral → Premium reminders ──────────────────────────────────────
    "💎 Premiumni PULSIZ oling! Do'stlarni taklif qiling: <b>har 3 ta taklif = 1 kun Premium</b> + Kitobcha. Havolangiz: «📊 Reyting → 🌟 Referal».",
    "🎁 Yolg'iz o'qima — do'st taklif qil! Har taklif uchun Kitobcha, <b>har 3-tasiga 1 kun Premium</b> 💎. «📊 Reyting → 🌟 Referal».",
    "👥 Do'stingiz ham kitobxon bo'lsin! Referal havolangizni ulashing — sizga 🪙 Kitobcha va <b>Premium kunlari</b> sovg'a!",
    "🚀 Premium olishning eng oson yo'li — do'st taklif qilish! Har 3 do'st = 1 kun Premium. Havola «📊 Reyting → 🌟 Referal»da.",
    "💌 Kitobxon do'stingizni chaqiring — u o'qiy boshlasa, sizga bonus 🪙 + <b>har 3 taklifga 1 kun Premium</b> 💎!",
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
    import time as _t
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
                # Respect Telegram's flood limit so the rest of the batch lands.
                if resp.status_code == 429:
                    _t.sleep(resp.json().get("parameters", {}).get("retry_after", 3))
        except Exception:
            failed += 1
        _t.sleep(0.035)  # ~28 msg/s, under Telegram's ~30/s global cap
    print(f"send_random_inspiration: sent={sent} failed={failed}")


@shared_task
def send_personalized_inspiration():
    """Hourly task: send an inspiration message only to users whose
    optimal_send_hour matches the current hour (Tashkent time).

    This replaces the blunt fixed-slot broadcasts for users who have enough
    report history.  Users with NULL optimal_send_hour are skipped here —
    they continue to receive the fixed-slot send_random_inspiration messages.

    The reminder_count preference is still respected:
      0 → never send anything to this user
      1 → send at their optimal hour (evening-biased if hour >= 17)
      2 → send at optimal hour if it is <= 16 or >= 17
      3 → always send at optimal hour
    """
    current_hour = timezone.localtime().hour

    qs = TelegramProfile.objects.filter(
        is_registered=True,
        is_blocked=False,
        optimal_send_hour=current_hour,
        reminder_count__gte=1,          # user hasn't opted out entirely
    )

    if not qs.exists():
        return

    import time as _t
    text = random.choice(INSPIRATION_POOL)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    reply_markup = _cta_reply_markup()
    sent = failed = 0

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
                if resp.status_code == 429:
                    _t.sleep(resp.json().get("parameters", {}).get("retry_after", 3))
        except Exception:
            failed += 1
        _t.sleep(0.035)

    print(f"send_personalized_inspiration [hour={current_hour}]: sent={sent} failed={failed}")


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


@shared_task
def apply_streak_freezes():
    """Auto-spend one banked Market 'Streak muzlatish' token for any user who
    was active yesterday (report or an earlier freeze), holds a token, but
    still hasn't reported today. Runs at 23:58 — the last practical moment
    to still count as covering "today". See tgbot.services.market."""
    from django.db import transaction
    from tgbot.models import StreakFreezeCoverage

    today = timezone.localdate()
    yesterday = today - timezone.timedelta(days=1)

    reported_today = set(
        ConfirmationReport.objects.filter(date__date=today).values_list("user_id", flat=True)
    )
    active_yesterday = set(
        ConfirmationReport.objects.filter(date__date=yesterday).values_list("user_id", flat=True)
    ) | set(
        StreakFreezeCoverage.objects.filter(date=yesterday).values_list("user_id", flat=True)
    )

    candidates = TelegramProfile.objects.filter(streak_freeze_count__gt=0, id__in=active_yesterday).exclude(
        id__in=reported_today
    )

    applied = 0
    for user in candidates.iterator():
        with transaction.atomic():
            p = TelegramProfile.objects.select_for_update().get(id=user.id)
            if p.streak_freeze_count <= 0:
                continue
            _, created = StreakFreezeCoverage.objects.get_or_create(user=p, date=today)
            if not created:
                continue
            p.streak_freeze_count -= 1
            p.save(update_fields=["streak_freeze_count"])
            applied += 1
        try:
            send_notification(
                p.telegram_id,
                "🛡 <b>Streak muzlatish</b> avtomatik ishlatildi — bugun hisobot "
                "yubormasangiz ham, ketma-ketligingiz saqlanib qoldi!\n"
                f"Qolgan tokenlar: <b>{p.streak_freeze_count}</b>",
            )
        except Exception:
            pass
    print(f"apply_streak_freezes: applied={applied}")


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


def _category_targets(boys_thread_id, girls_thread_id):
    """(chat_id, thread_id) pairs for one forum-topic category (announcements/
    games/leaderboard): the boys + girls groups, plus any group where the bot
    has been made admin (auto-registered via my_chat_member — see
    tgbot/bot/handlers/groups/auto_register.py and the BroadcastGroup model).
    `GENERAL_GROUP_ID` is the same chat as the girls group (see its definition
    above), so there's no separate "general" target here — just these two
    fixed slots. A None thread_id falls back to the group's default topic;
    auto-registered groups always get None since we don't know their topic
    layout."""
    import os as _os
    from tgbot.models import BroadcastGroup

    out = []
    boys = _os.environ.get("BOYS_GROUP_ID", "").strip()
    if boys:
        out.append((boys, boys_thread_id))
    girls = _os.environ.get("GIRLS_GROUP_ID", "").strip()
    if girls:
        out.append((girls, girls_thread_id))

    known = {boys, girls}
    extra = (
        BroadcastGroup.objects.filter(is_active=True)
        .exclude(chat_id__in=known)
        .values_list("chat_id", flat=True)
    )
    out.extend((chat_id, None) for chat_id in extra)
    return out


def _announce_targets():
    from tgbot.bot.consts import ANNOUNCE_BOYS_THREAD_ID, ANNOUNCE_GIRLS_THREAD_ID
    return _category_targets(ANNOUNCE_BOYS_THREAD_ID, ANNOUNCE_GIRLS_THREAD_ID)


def _game_targets():
    from tgbot.bot.consts import GAMES_BOYS_THREAD_ID, GAMES_GIRLS_THREAD_ID
    return _category_targets(GAMES_BOYS_THREAD_ID, GAMES_GIRLS_THREAD_ID)


def _leaderboard_targets():
    from tgbot.bot.consts import LEADERBOARD_BOYS_THREAD_ID, LEADERBOARD_GIRLS_THREAD_ID
    return _category_targets(LEADERBOARD_BOYS_THREAD_ID, LEADERBOARD_GIRLS_THREAD_ID)


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

        # 1) Group congrats — auto-delete after 2 minutes (see countdown=120 below).
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
            except Exception as e:
                print(f"tabriklash group broadcast failed for {_gid}/{ach['code']}: {e}")
                continue
            if resp.ok:
                msg_id = resp.json().get("result", {}).get("message_id")
                if msg_id:
                    delete_message_after_delay.apply_async(
                        args=[_gid, msg_id], countdown=120
                    )

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
    a_g = (achiever.gender or "").strip().lower()
    r_g = (recipient.gender or "").strip().lower()
    sender_pref = (recipient.send_congrats_to or "any").strip().lower()
    accept_pref = (achiever.accept_congrats_from or "any").strip().lower()
    if sender_pref != "any" and sender_pref != a_g:
        print(
            f"gender_filter: SKIP recipient={recipient.id} send_pref={sender_pref!r} "
            f"achiever_gender={a_g!r} (recipient won't congrat this gender)"
        )
        return False
    if accept_pref != "any" and accept_pref != r_g:
        print(
            f"gender_filter: SKIP recipient={recipient.id} accept_pref={accept_pref!r} "
            f"recipient_gender={r_g!r} (achiever won't accept from this gender)"
        )
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

    from django.core.cache import cache
    today_str = timezone.localdate().isoformat()

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
            # Cap: at most ONE "please congratulate X" DM per recipient per day,
            # no matter how many achievements unlock across the platform. Keeps
            # the bot from spamming users with congrat invitations.
            cap_key = f"congrats_dm:{recipient.id}:{today_str}"
            if cache.get(cap_key):
                continue
            # Nudge: every 10th Tabriklash DM a given recipient receives also
            # surfaces the reminder-config button so users can adjust daily
            # reminders without hunting through the settings menu. The counter
            # is per-recipient so the button doesn't land on back-to-back
            # messages to the same user.
            recipient_dm_no = (recipient.congrats_dm_count or 0) + 1
            keyboard = keyboard_with_reminder if recipient_dm_no % 10 == 0 else keyboard_basic
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
                cache.set(cap_key, 1, 60 * 60 * 26)  # holds for the rest of the day
                TelegramProfile.objects.filter(id=recipient.id).update(
                    congrats_dm_count=recipient_dm_no
                )
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


SURVEY_PIN_HOURS = 6


@shared_task
def unpin_project_survey_pins(pairs):
    """Follow-up to broadcast_project_survey: unpin the announcement in every
    chat it was pinned in, `SURVEY_PIN_HOURS` after it went out."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/unpinChatMessage"
    ok, failed = 0, 0
    for chat_id, message_id in pairs:
        try:
            resp = requests.post(url, data={"chat_id": chat_id, "message_id": message_id}, timeout=5)
            if resp.ok:
                ok += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    print(f"unpin_project_survey_pins: unpinned={ok} failed={failed}")


@shared_task
def broadcast_project_survey():
    """Send the 'help us improve' survey announcement to every registered
    user, pin it in their private chat, and schedule an auto-unpin
    SURVEY_PIN_HOURS later (a specific message_id, not unpin_all — so we
    never touch any other pin a user already has)."""
    text = (
        "📊 <b>Loyihani yaxshilash uchun so'rovnoma!</b>\n\n"
        "Fikringiz biz uchun juda muhim — bir necha savolga javob bering va "
        "<b>500 Kitobcha</b> yutib oling! 🎁\n\n"
        "⏱ Atigi 2 daqiqa vaqtingizni oladi."
    )
    reply_markup = json.dumps({"inline_keyboard": [[
        {"text": "📊 So'rovnomada qatnashish (+500 🪙)", "callback_data": "survey_start"}
    ]]})

    send_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    pin_url = f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage"
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)

    sent, pinned, failed = 0, 0, 0
    pinned_pairs = []
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(
                send_url,
                data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": reply_markup},
                timeout=5,
            )
            if not resp.ok:
                failed += 1
                continue
            sent += 1
            message_id = resp.json()["result"]["message_id"]
            try:
                pin_resp = requests.post(
                    pin_url,
                    data={"chat_id": chat_id, "message_id": message_id, "disable_notification": True},
                    timeout=5,
                )
                if pin_resp.ok:
                    pinned += 1
                    pinned_pairs.append((chat_id, message_id))
            except Exception:
                pass
        except Exception:
            failed += 1

    if pinned_pairs:
        unpin_project_survey_pins.apply_async(args=[pinned_pairs], countdown=SURVEY_PIN_HOURS * 3600)

    print(f"broadcast_project_survey: sent={sent} pinned={pinned} failed={failed}")


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


def _format_uz_number(n: int) -> str:
    """Short Uzbek magnitude label for social-proof stats — '2 mln+',
    '540 ming+' — rounds down so the number never overstates reality."""
    if n >= 1_000_000:
        return f"{n // 1_000_000} mln+"
    if n >= 1_000:
        return f"{n // 1_000} ming+"
    return str(n)


def _referral_platform_stats() -> dict:
    """Live platform totals for the social-proof share-text variants —
    queried fresh every call (never hardcoded) so the numbers can't go
    stale. Kitobcha-given uses the same current-balance + shop-spent
    approximation as the admin "Kitobcha bo'yicha reyting" report, for
    consistency across the app."""
    from tgbot.models import ShopPurchase as _SP

    total_pages = ConfirmationReport.objects.filter(is_audio=False).aggregate(
        s=Sum("pages_read")
    )["s"] or 0
    total_readers = TelegramProfile.objects.filter(is_registered=True, is_blocked=False).count()
    balance_sum = TelegramProfile.objects.filter(is_registered=True).aggregate(
        s=Sum("ball")
    )["s"] or 0
    shop_spent = _SP.objects.aggregate(s=Sum("price_at_purchase"))["s"] or 0
    total_kitobcha = int(balance_sum) + int(shop_spent)

    return {
        "pages": _format_uz_number(int(total_pages)),
        "readers": _format_uz_number(total_readers),
        "kitobcha": _format_uz_number(total_kitobcha),
    }


def _referral_share_texts(user) -> list:
    """40 varied, personalized invite blurbs for the '📤 Referalni ulashish'
    share button — a different random one each time this message is (re)sent
    so frequent posters don't spam the same line to their contacts. The
    second half leans on live platform stats (pages read, reader count,
    Kitobcha given out) as social proof."""
    name = (user.full_name or "").strip().split(" ")[0] if user.full_name else ""
    name = name or "Kitobxon"
    stats = _referral_platform_stats()
    pages, readers, kitobcha = stats["pages"], stats["readers"], stats["kitobcha"]
    return [
        "📚 Kitob Challenge botiga qo'shil — birga o'qib, sovg'alar yutib olamiz! 🎁",
        f"👋 Salom! Men — {name}, har kuni kitob o'qiyapman va Kitobcha yig'yapman. Sen ham qo'shil! 📚🔥",
        "🔥 Har kuni o'qigan sahifang uchun mukofot olasanmi? Kitob Challenge'da — HA! Qo'shil 🎁",
        "📖 O'qish endi zerikarli emas — challenge, reyting va sovg'alar bilan! Bugun boshla 🚀",
        f"🎯 {name} seni Kitob Challenge'ga taklif qilyapti — birga o'qib, birga g'olib bo'lamiz! 🏆",
        "🎁 Kitob o'qib pul o'rniga \"Kitobcha\" yig'ish mumkinligini bilarmiding? Qo'shil, ko'r! 📚",
        "💪 O'qish odatini shakllantirish qiyinmi? Kitob Challenge yordam beradi — reyting, streak, sovg'alar! 🔥",
        "📚➡️🎁 Har bir o'qilgan bet — bir qadam mukofotga yaqinroq. Qo'shil, boshla!",
        f"✨ {name} bilan birga o'qing — kim ko'proq bet o'qisa ko'proq yutadi! 🏆📖",
        "🚀 Kitob o'qish + reyting + sovg'alar = Kitob Challenge. Bugun qo'shilib ko'r! 📚",
        "📣 Do'stim, senga bir taklifim bor: birga kitob o'qiymiz, ikkalamiz ham yutib chiqamiz! 🎁",
        "🏆 Har kuni eng ko'p o'qigan kitobxonlar orasida bo'lishni xohlaysanmi? Qo'shil! 📚🔥",
        f"📖 {name} sizni chaqiryapti: kitob o'qi, Kitobcha yig', mukofot yut. Oddiy! 🎁",
        "🎉 Kitob Challenge — o'qish + o'yin + sovg'a, hammasi bitta loyihada! Qo'shil, ko'proq bilib ol.",
        "📚 Yolg'iz o'qish zerikarli, birga o'qish — qiziq! Kitob Challenge'ga xush kelibsan 🔥",
        "🎁 Bugun ro'yxatdan o't — birinchi hisobotdan boshlab Kitobcha yig'a boshlaysan!",
        f"👥 {name} allaqachon Kitob Challenge'da faol o'qiyapti. Sen ham qo'shilasanmi? 📖🚀",
        "🔥 Streak, reyting, mukofotlar — barchasi bitta joyda. Kitob Challenge'ga xush kelibsiz! 📚",
        "📚 Kitob o'qishni o'yinga aylantirgan bot bor — Kitob Challenge. Qo'shil, o'zing ko'r! 🎁",
        "🌟 Har kuni bir necha bet o'qi, do'stlaring bilan raqobatlash, sovg'alar yut. Boshla! 🏆",
        f"📚 Kitob Challenge'da hozirgacha {pages} bet kitob o'qilgan! Shu katta oilaga sen ham qo'shil 🚀",
        f"🔥 {pages} bet o'qilgan loyihaga qo'shilmoqchimisan? Kitob Challenge seni kutmoqda! 📖",
        f"👥 {readers} ta real kitobxon Kitob Challenge'da faol o'qiyapti — sen safimizga qo'shilasanmi? 📚",
        f"🎉 {readers} kitobxon allaqachon bizning oilamizda! Sen ham shu safga qo'shil 📖✨",
        f"🪙 Kitob Challenge'da hozirgacha {kitobcha} Kitobcha berildi — sen hali ham kutyapsanmi? 😏 Qo'shil!",
        f"💰 {kitobcha} Kitobcha allaqachon o'qiganlar qo'liga tegdi. Navbat sizda! 🎁",
        f"📊 {pages} bet, {readers} kitobxon, cheksiz sovg'alar — bularning barchasi Kitob Challenge'da! Qo'shil 🚀",
        f"😲 {pages} bet o'qilgan?! Bu raqamga sen ham o'z hissangni qo'shishni xohlaysanmi? Kitob Challenge'ga marhamat!",
        f"🏆 {readers} kishi bilan bir safda o'qishni xohlaysanmi? Kitob Challenge'ga qo'shil, birga o'sing!",
        f"🎁 {kitobcha} Kitobcha allaqachon tarqatildi — sen ham o'zingnikini yig'ishni boshla!",
        f"📚 Bu loyihada {pages} bet allaqachon o'qilgan — keyingi bet sening bo'lsin! Qo'shil 🔥",
        f"🚀 {readers} kitobxon + {pages} bet = Kitob Challenge. Sen bu formulaning bir qismisan!",
        f"🤔 {kitobcha} Kitobcha berilgan bot bor ekan, siz hali qo'shilmagansiz-a? Vaqt keldi! 😄",
        f"📈 Har kuni yangi rekord: hozircha {pages} bet o'qilgan. Sen ham tarixga kirasanmi?",
        f"🌟 {readers} kishi ishonch bildirgan bot — endi navbat sizda! Kitob Challenge'ga xush kelibsiz.",
        f"😳 {kitobcha} Kitobcha tarqatilgan loyiha bor — sen hali tashqaridamisan? Qo'shil, boshla!",
        f"📖 {pages} bet o'qilgan kutubxona — bu Kitob Challenge! Sen ham sahifa qo'sh 📚",
        f"🔥 {readers} kitobxon safida sen yo'qsan hali? Vaqt boy bermay qo'shil!",
        f"🎯 {kitobcha} Kitobcha, {readers} kitobxon, {pages} bet — bularning barchasi seni kutmoqda!",
        f"😏 Sen hali ham \"keyinroq qo'shilaman\" deyapsanmi? {kitobcha} Kitobcha allaqachon tarqatib bo'lindi — boshla!",
    ]


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

    from django.conf import settings as _settings
    from urllib.parse import quote as _urlquote

    site_url = f"{_settings.WEB_DOMAIN}/"
    text = f'🌌 <a href="{site_url}">Parallel olam</a>\n\n' + _progress_bar_text(pages)

    buttons = [[{
        "text": "🌌 Parallel olam",
        "web_app": {"url": site_url},
    }]]

    bot_username = _get_bot_username()
    code = _ensure_referral_code(user) if bot_username else None
    if bot_username and code:
        ref_link = f"https://t.me/{bot_username}?start={code}"
        text += (
            "\n\n🌟 <b>Sizning referal havolangiz:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            "Havolani nusxalab kitobxonlarga ulashing — har taklif uchun Kitobcha, "
            "har 3 taklifga 1 kun Premium va boshqa sovg'alardan foydalaning! 🎁"
        )
        share_text = _urlquote(random.choice(_referral_share_texts(user)))
        buttons.append([{
            "text": "📤 Referalni ulashish",
            "url": f"https://t.me/share/url?url={_urlquote(ref_link)}&text={share_text}",
        }])

    site_button = json.dumps({"inline_keyboard": buttons})
    resp = requests.post(
        url,
        data={
            "chat_id": user.telegram_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": site_button,
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
        f"🏆 <b>JONLI QUIZ BOSHLANMOQDA!</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"📖 <b>{quiz_title}</b>\n"
        f"{quiz_desc + chr(10) + chr(10) if quiz_desc else chr(10)}"
        f"❓ {q_count} ta savol  ·  ⏱ {time_secs} son/savol\n"
        f"⏰ {time_label.replace('<b>', '').replace('</b>', '')}\n\n"
        f"<blockquote>🎮 Bilimingizni sinab ko'ring, boshqa kitobxonlar "
        f"bilan bellashing — qatnashish uchun pastdagi tugmani bosing! 👇</blockquote>"
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

    # Bugun kutubxonaga qo'shilgan (haqiqiy PDF bilan) yangi kitoblar --
    # bo'sh bo'lsa hech narsa qo'shilmaydi, faqat mavjud bo'lsa ko'rinadi.
    from tgbot.models import GlobalBook as _GB
    new_books_qs = (
        _GB.objects.filter(created_at__date=today)
        .exclude(pdf_file="").exclude(pdf_file__isnull=True)
        .order_by("title")
    )
    new_books_block = ""
    _new_books_count = new_books_qs.count()
    if _new_books_count:
        _titles = list(new_books_qs.values_list("title", flat=True)[:10])
        _lines = "\n".join(f"• {escape(t)}" for t in _titles)
        _extra = _new_books_count - len(_titles)
        _extra_line = f"\n…va yana {_extra} ta" if _extra > 0 else ""
        new_books_block = (
            f"\n\n🆕 <b>Bugun kutubxonaga qo'shilgan yangi kitoblar:</b>\n{_lines}{_extra_line}\n"
            f"🌌 Parallel olam → Kutubxona bo'limida o'qing!"
        )

    # Includes trial-Premium users (see TelegramProfile.has_active_premium) —
    # otherwise someone inside their 3-hour daily-giveaway trial window gets
    # the free-tier teaser report instead of the full Premium one they're
    # currently entitled to.
    premium_user_ids = set(
        _Pay.objects.filter(status="paid", end_date__gte=today).values_list("user_id", flat=True)
    ) | set(
        TelegramProfile.objects.filter(trial_premium_until__gte=timezone.now()).values_list("id", flat=True)
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

            text += new_books_block
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
                text += new_books_block
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
        from google import genai as new_genai
        from google.genai import types as genai_types
        import datetime as _dt2
        api_key = env.str("GEMINI_API_KEY", default="")
        if not api_key:
            return None
        client = new_genai.Client(api_key=api_key)

        week_end_d = timezone.localdate()
        week_start_d = week_end_d - _dt2.timedelta(days=6)
        date_range = f"{week_start_d.strftime('%b %d')} – {week_end_d.strftime('%b %d, %Y')}"
        ah, am = divmod(week_audio_minutes, 60)
        audio_label = f"{ah}h {am}m" if ah else f"{week_audio_minutes}m"

        prompt = (
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
            f"CENTERPIECE — elegant calligraphic script: 'Presented to {full_name}' "
            "(large, deep charcoal with subtle gold underline flourish). "
            "STATS — four minimalist cards in a single row: "
            f"📖  {week_pages}  PAGES READ  ·  "
            f"🎧  {audio_label}  AUDIO TIME  ·  "
            f"🔥  {streak}  DAY STREAK  ·  "
            f"🏆  TOP {100 - rank_pct_ahead}%  READER. "
            f"FINE PRINT line below: 'All-time pages: {total_pages}   |   "
            f"Books finished this week: {books_finished_week}'. "
            "BOTTOM — italic serif gratitude line, deep emerald: "
            "'Thank you for your dedication and unwavering perseverance.' "
            "Corners: small minimalist gold corner-mark brackets. "
            "Perfect English text, no garbled letters. No people, no faces. "
            "Hermès / Aesop print-piece aesthetic. 16:9, ultra-detailed."
        )
        result = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=genai_types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9",
                safety_filter_level="BLOCK_ONLY_HIGH",
                person_generation="DONT_ALLOW",
            ),
        )
        if result.generated_images:
            gi = result.generated_images[0]
            if hasattr(gi, "image") and gi.image is not None:
                raw = getattr(gi.image, "image_bytes", None)
                if isinstance(raw, (bytes, bytearray)):
                    return bytes(raw)
    except Exception as e:
        import traceback
        print(f"[weekly_ai_report] Imagen error: {e}")
        traceback.print_exc()
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
# Book Recommendation task — Premium only, weekly
# ────────────────────────────────────────────────────────────────────────

@shared_task
def send_book_recommendations():
    """
    Every Sunday at 21:00 Tashkent — send personalised "you might also like"
    book recommendations to all active Premium users.

    Uses item-based collaborative filtering (Jaccard similarity) over the
    full ConfirmationReport history.  The similarity index is built once
    per run and cached in-process for 6 hours.

    Only sent to Premium users who have read at least 2 distinct books
    (MIN_USER_BOOKS threshold in book_recommendations.py).
    """
    import time as _time
    from tgbot.models import Payment as _Pay
    from tgbot.services.book_recommendations import (
        build_similarity_index,
        get_recommendations,
        format_recommendations,
    )

    today = timezone.localdate()

    premium_user_ids = set(
        _Pay.objects.filter(
            status="paid", end_date__gte=today
        ).values_list("user_id", flat=True)
    )
    if not premium_user_ids:
        print("[book_recs] No premium users found.")
        return

    # Build (or refresh) the similarity index once before the loop
    index = build_similarity_index(force=True)
    if not index:
        print("[book_recs] Similarity index is empty — not enough shared books yet.")
        return

    print(f"[book_recs] Index built: {len(index)} books with similar neighbours.")

    users = list(
        TelegramProfile.objects.filter(
            id__in=premium_user_ids,
            is_registered=True,
            is_blocked=False,
        ).only("id", "telegram_id", "full_name", "language")
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    sent = skipped = failed = 0

    for user in users:
        recs = get_recommendations(user_id=user.id, top_n=3)
        if not recs:
            skipped += 1
            continue

        text = format_recommendations(
            full_name=user.full_name or "Kitobxon",
            recs=recs,
            language=user.language or "uz",
        )

        try:
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
                sent += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[book_recs] send failed uid={user.id}: {e}")
            failed += 1

        _time.sleep(0.05)

    print(f"[book_recs] done. sent={sent} skipped(no recs)={skipped} failed={failed}")


@shared_task
def send_recs_to_all_promo():
    """One-off (not on the beat schedule — fire via a single apply_async(eta=...)):
    send book recommendations to EVERY registered, non-blocked user regardless
    of Premium status or how much reading history they have. Non-Premium users
    get a CTA framing this as a Premium perk they're getting early because of
    their activity; users with too little history for personalized CF
    (get_recommendations needs 2+ distinct books) fall back to the overall
    most-read books instead of being skipped."""
    from tgbot.services.book_recommendations import (
        build_similarity_index, get_recommendations, get_popular_fallback,
    )

    today = timezone.localdate()
    premium_ids = _get_premium_tg_ids()  # returns telegram_ids, not pks — see below

    build_similarity_index(force=True)

    users = list(
        TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
        .only("id", "telegram_id", "full_name", "language")
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    sent = skipped = failed = 0

    for user in users:
        recs = get_recommendations(user_id=user.id, top_n=3)
        personalized = bool(recs)
        if not recs:
            recs = get_popular_fallback(user_id=user.id, top_n=3)
        if not recs:
            skipped += 1
            continue

        lang = user.language or "uz"
        is_premium = user.telegram_id in premium_ids
        name = user.full_name or "Kitobxon"

        if lang == "ru":
            if personalized:
                head = f"📚 <b>{name}</b>, книги, которые читают похожие на вас читатели:\n"
            else:
                head = f"📚 <b>{name}</b>, самые популярные книги среди читателей:\n"
            lines = [head]
            for i, rec in enumerate(recs, 1):
                if rec.because:
                    lines.append(f"{i}. <b>{rec.title}</b>\n   <i>Читатели «{rec.because}» также полюбили эту книгу</i>")
                else:
                    lines.append(f"{i}. <b>{rec.title}</b>")
            lines.append(
                "\n<i>Чем больше отчётов и прочитанных книг у вас будет, тем точнее "
                "станут эти рекомендации.</i>"
            )
            if not is_premium:
                lines.append(
                    "\n💎 Обычно такие рекомендации получают только <b>Premium</b>-читатели "
                    "каждую неделю — вам прислали её за вашу активность! Оформите Premium, "
                    "чтобы получать их регулярно."
                )
        else:
            if personalized:
                head = f"📚 <b>{name}</b>, sizga o'xshash kitobxonlar o'qigan kitoblar:\n"
            else:
                head = f"📚 <b>{name}</b>, kitobxonlar orasida eng mashhur kitoblar:\n"
            lines = [head]
            for i, rec in enumerate(recs, 1):
                if rec.because:
                    lines.append(f"{i}. <b>{rec.title}</b>\n   <i>«{rec.because}»ni o'qiganlar bu kitobni ham yoqtirgan</i>")
                else:
                    lines.append(f"{i}. <b>{rec.title}</b>")
            lines.append(
                "\n<i>Hisobot va o'qigan kitoblaringiz tarixi boyigan sari, bu "
                "tavsiyalar yanada aniqroq bo'lib boradi.</i>"
            )
            if not is_premium:
                lines.append(
                    "\n💎 Odatda bunday tavsiyalar har hafta faqat <b>Premium</b> "
                    "kitobxonlarga yuboriladi — sizga faolligingiz uchun maxsus jo'natdik! "
                    "Doimiy shu tavsiyalarni olish uchun Premium'ga o'ting."
                )

        text = "\n".join(lines)
        try:
            resp = requests.post(
                url, data={"chat_id": user.telegram_id, "text": text, "parse_mode": "HTML"}, timeout=5,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[recs_promo] send failed uid={user.id}: {e}")
            failed += 1

    print(f"[recs_promo] done. sent={sent} skipped(no books at all)={skipped} failed={failed}")


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
    {"emoji": "📕", "title": "30-bet Challenge",        "description": "Har kuni 30 bet — yengil start, mustahkam odat!",                          "condition_type": "pages_daily",     "condition_value": 30},
    {"emoji": "📓", "title": "40-bet Challenge",        "description": "Har kuni 40 bet o'qing — kichik qadamlar, katta natija!",                  "condition_type": "pages_daily",     "condition_value": 40},
    {"emoji": "📚", "title": "80-bet Challenge",        "description": "Har kuni 80 bet — kuchli kitobxonlar uchun sinov!",                        "condition_type": "pages_daily",     "condition_value": 80},
    {"emoji": "📦", "title": "120-bet Challenge",       "description": "Har kuni 120 bet — chinakam marafonchi bo'ling!",                          "condition_type": "pages_daily",     "condition_value": 120},
    {"emoji": "🏔", "title": "200-bet Challenge",       "description": "Har kuni 200 bet — eng jasur kitobxonlar sinovi!",                         "condition_type": "pages_daily",     "condition_value": 200},
    {"emoji": "🎙", "title": "15-daqiqa Audio Challenge","description": "Har kuni 15 daqiqa audiokitob — yo'lda ham bilim oling!",                  "condition_type": "audio_daily",     "condition_value": 15},
    {"emoji": "🎚", "title": "30-daqiqa Audio Challenge","description": "Har kuni 30 daqiqa audiokitob eshiting — uch kun davomida!",               "condition_type": "audio_daily",     "condition_value": 30},
    {"emoji": "🔊", "title": "45-daqiqa Audio Challenge","description": "Har kuni 45 daqiqa audio — quloqqa ziyofat, aqlga oziq!",                  "condition_type": "audio_daily",     "condition_value": 45},
    {"emoji": "🤝", "title": "2 Taklif Challenge",      "description": "Har kuni 2 ta do'stingizni Kitob Challengega taklif qiling!",              "condition_type": "referrals_daily", "condition_value": 2},
    {"emoji": "🌟", "title": "3 Taklif Challenge",      "description": "Har kuni 3 ta yangi do'st — jamoangizni kattalashtiring!",                 "condition_type": "referrals_daily", "condition_value": 3},
    {"emoji": "📝", "title": "300-belgi Taqriz Challenge","description": "Har kuni 300+ belgili mazmunli xulosa yozing — fikringizni ulashing!",     "condition_type": "review_daily",    "condition_value": 300},
    {"emoji": "🖋", "title": "500-belgi Taqriz Challenge","description": "Har kuni 500+ belgili to'liq taqriz — chinakam mutafakkir bo'ling!",       "condition_type": "review_daily",    "condition_value": 500},
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

    # If NOBODY completed even a single day, hand out nothing — just close the
    # challenge. Prevents rewarding people who didn't do the tasks.
    if not any(p.days_completed >= 1 for p in participants):
        ChallengeParticipant.objects.filter(
            id__in=[p.id for p in participants]
        ).update(reward_given=True)
        print(f"_finalize_challenge_results: challenge_id={challenge_id}, "
              f"no completions — no rewards given ({len(participants)} participants)")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    prize_map = {1: 200, 2: 100, 3: 50}

    # Assign ranks sequentially (sorted above)
    for rank, p in enumerate(participants, start=1):
        days = p.days_completed
        # Belt-and-suspenders: a 0-day participant never earns anything, even if
        # they happen to land in the top-3 by rank when completions are sparse.
        if days < 1:
            ChallengeParticipant.objects.filter(id=p.id).update(rank=rank, reward_given=True)
            continue
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
    """Runs daily at 00:15; only actually does anything once the active
    challenge's end_date has passed. This used to be pinned to a fixed
    day-of-month cron list (1,4,7,...,28), which drifted at every month
    boundary that isn't a multiple of 3 (e.g. a 31-day month leaves a 4-day
    gap between day 28 and day 1) — some challenges sat "finished but not
    announced" for an extra day or more. Checking end_date directly here
    ties the finalize+next-announce moment to the challenge's real lifecycle
    instead of the calendar.

    When due: finalize previous challenge (and any active boom), then either
    launch a queued Referral BOOM for this slot or pick the next pool
    challenge, and announce to groups + users."""
    import datetime as _dt
    import random as _rand
    import time as _time
    from tgbot.models import Challenge, ReferralBoom

    # Finalize any still-active challenge, but only once its window is over —
    # a challenge that started today or yesterday isn't due yet.
    prev = Challenge.objects.filter(is_active=True).first()
    if prev and prev.end_date >= timezone.localdate():
        return
    if prev:
        _finalize_challenge_results(prev.id)

    # Finalize any boom left over from the previous slot whose window has
    # actually closed (normally already finalized by boom_reminder_tick; this
    # is a safety net). Critical: only EXPIRED booms -- a bare `is_active=True`
    # filter here would finalize a still-running boom (e.g. a multi-day event)
    # every time this task fires, which previously killed a live 7-day boom
    # via the announce_first_challenge release-command tick on every deploy.
    for _b in ReferralBoom.objects.filter(is_active=True, end_at__lt=timezone.now()):
        finalize_referral_boom(_b.id)

    # A currently-live boom (any length, not just the queued 3-day slot --
    # e.g. a longer standalone event like "Yaxshilik ulashuvchi 1.0") owns
    # the featured-competition slot for its whole window: don't start a new
    # reading challenge underneath it. It'll resume automatically once the
    # boom's own finalize (above, or boom_reminder_tick) clears is_active.
    if ReferralBoom.objects.filter(is_active=True).exists():
        print("announce_challenge: a Referral BOOM is still active — skipping regular challenge rotation")
        return

    # If a boom is queued for this rotation slot, launch it INSTEAD of a normal
    # challenge. Clears the flag so the pool resumes next slot.
    queued = ReferralBoom.objects.filter(is_queued=True).order_by("created_at").first()
    if queued:
        now = timezone.now()
        ReferralBoom.objects.filter(id=queued.id).update(
            is_queued=False, is_active=True, announced_at=None,
            start_at=now, end_at=now + _dt.timedelta(days=3),
        )
        announce_referral_boom(queued.id)
        print(f"announce_challenge: launched queued Referral BOOM id={queued.id}")
        return

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
    for group_id, thread_id in _announce_targets():
        try:
            data = {"chat_id": group_id, "text": text, "parse_mode": "HTML",
                    "reply_markup": keyboard}
            if thread_id:
                data["message_thread_id"] = thread_id
            requests.post(url, data=data, timeout=10)
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
    # Never treat zero (or a misconfigured non-positive) threshold as auto-pass:
    # `pages >= 0` / `referrals >= 0` would be true for everyone who merely
    # joined, handing out Kitobcha to users who did nothing. Require real,
    # strictly-positive activity. Legit challenges (cval >= 1) are unaffected.
    cval = max(int(challenge.condition_value or 0), 1)

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

    # 2. Imagen 3 — branded weekly report card.
    # Uses google-genai SDK (not google-generativeai — that one lacks Imagen).
    img_bytes = None
    if gemini_key:
        try:
            from google import genai as _new_genai
            from google.genai import types as _genai_types
            client = _new_genai.Client(api_key=gemini_key)

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
            result = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=prompt_img,
                config=_genai_types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="16:9",
                    safety_filter_level="BLOCK_ONLY_HIGH",
                    person_generation="DONT_ALLOW",
                ),
            )
            if result.generated_images:
                gen_img = result.generated_images[0]
                # New SDK exposes raw bytes on .image.image_bytes
                if hasattr(gen_img, "image") and gen_img.image is not None:
                    raw = getattr(gen_img.image, "image_bytes", None)
                    if isinstance(raw, (bytes, bytearray)):
                        img_bytes = bytes(raw)
            print(f"[send_ai_report_to_admin] Imagen: {'OK' if img_bytes else 'no bytes'}")
        except Exception as e:
            import traceback
            print(f"[send_ai_report_to_admin] Imagen error: {e}")
            traceback.print_exc()

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


# ────────────────────────────────────────────────────────────────────────
# Referral BOOM — 3-day referral blitz.
#   launch_referral_boom  → create + announce (admin-triggered, one command)
#   boom_reminder_tick     → beat (every 5 min): drip playful reminders + finalize
#   finalize_referral_boom → deactivate + wrap-up DMs + admin summary
# ────────────────────────────────────────────────────────────────────────
def _get_bot_username():
    """Cached — the bot's username never changes, and callers like the daily
    per-user progress pin would otherwise hit Telegram's getMe once per user."""
    from django.core.cache import cache
    cached = cache.get("bot_username")
    if cached:
        return cached
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        if r.ok:
            username = r.json().get("result", {}).get("username")
            if username:
                cache.set("bot_username", username, 60 * 60 * 24)
            return username
    except Exception:
        pass
    return None


def _ensure_referral_code(user):
    """Return the user's referral code, generating+saving one if missing.
    Mirrors ReferralService.get_or_create_code but synchronous for Celery."""
    if user.referral_code:
        return user.referral_code
    import string as _s
    chars = _s.ascii_letters + _s.digits
    while True:
        code = "".join(random.choice(chars) for _ in range(8))
        if not TelegramProfile.objects.filter(referral_code=code).exists():
            user.referral_code = code
            user.save(update_fields=["referral_code"])
            return code


def _boom_join_keyboard(boom_id):
    return json.dumps({
        "inline_keyboard": [[{
            "text": "🌟 Qatnashaman!",
            "callback_data": f"join_boom:{boom_id}",
        }]]
    })


@shared_task
def launch_referral_boom(days=7, tier1_reward=150, tier1_cap=10,
                         tier2_reward=300, total_reminders=21, title=None,
                         boom_id=None):
    """Admin entrypoint: finalize any running boom AND the currently active
    reading Challenge (a boom of any length takes over the "featured
    competition" slot for its whole window — announce_challenge also won't
    start a new Challenge while a boom is active, so this keeps both sides
    of that handoff consistent instead of leaving a stale challenge running
    alongside the boom).

    With `boom_id`: activates that EXISTING row instead of creating a new
    one — this is the path for a boom prepared through the admin (custom
    title, image, tier rewards, planned_days already set on the row); only
    start_at/end_at/is_active/is_queued get overwritten here. Without it:
    creates a fresh boom from the given kwargs (the old CLI/management-
    command path). Either way, announces immediately and returns the id."""
    import datetime as _dt
    from tgbot.models import Challenge, ReferralBoom

    for b in ReferralBoom.objects.filter(is_active=True):
        finalize_referral_boom(b.id)

    prev_challenge = Challenge.objects.filter(is_active=True).first()
    if prev_challenge:
        _finalize_challenge_results(prev_challenge.id)

    now = timezone.now()
    if boom_id:
        boom = ReferralBoom.objects.filter(id=boom_id).first()
        if not boom:
            return None
        boom.start_at = now
        boom.end_at = now + _dt.timedelta(days=boom.planned_days or days)
        boom.is_active = True
        boom.is_queued = False
        boom.announced_at = None
        boom.save(update_fields=["start_at", "end_at", "is_active", "is_queued", "announced_at"])
    else:
        boom = ReferralBoom.objects.create(
            title=title or "Yaxshilik ulashuvchi",
            start_at=now,
            end_at=now + _dt.timedelta(days=days),
            tier1_reward=tier1_reward,
            tier1_cap=tier1_cap,
            tier2_reward=tier2_reward,
            total_reminders=total_reminders,
            is_active=True,
        )
    announce_referral_boom(boom.id)
    return boom.id


@shared_task
def queue_referral_boom(tier1_reward=150, tier1_cap=10, tier2_reward=300,
                        total_reminders=21, title=None):
    """Queue a Referral BOOM for the NEXT regular 3-day challenge rotation
    instead of launching now. The rotation (`announce_challenge`) picks it up,
    runs it for one slot, then resumes the normal challenge pool.
    Idempotent: updates the existing queued boom rather than stacking duplicates.
    Returns the queued boom id."""
    from tgbot.models import ReferralBoom

    now = timezone.now()
    defaults = dict(
        title=title or "Yaxshilik ulashuvchi",
        tier1_reward=tier1_reward, tier1_cap=tier1_cap, tier2_reward=tier2_reward,
        total_reminders=total_reminders,
        # Placeholder window — overwritten with real start/end when the rotation
        # actually launches it.
        start_at=now, end_at=now,
        is_active=False, is_queued=True, announced_at=None,
    )
    existing = ReferralBoom.objects.filter(is_queued=True).order_by("created_at").first()
    if existing:
        ReferralBoom.objects.filter(id=existing.id).update(**defaults)
        return existing.id
    boom = ReferralBoom.objects.create(**defaults)
    return boom.id


@shared_task
def announce_referral_boom(boom_id):
    """Broadcast the boom to all groups + every registered user with a join
    button, then send an admin summary."""
    import time as _time
    import os as _os
    from django.conf import settings as _settings
    from tgbot.models import ReferralBoom

    boom = ReferralBoom.objects.filter(id=boom_id, is_active=True).first()
    if not boom:
        return

    start_l = timezone.localtime(boom.start_at)
    end_l = timezone.localtime(boom.end_at)
    date_range = f"{start_l.strftime('%d.%m %H:%M')} – {end_l.strftime('%d.%m %H:%M')}"

    text = boom.announce_text or (
        f"💥💥💥 <b>{boom.title.upper()} BOSHLANDI!</b> 💥💥💥\n\n"
        f"⚡️ Har taklif qilgan do'stingiz uchun <b>{boom.tier1_reward} Kitobcha</b>!\n"
        f"🤯 <b>{boom.tier1_cap} tadan</b> oshsa — har biri uchun "
        f"<b>{boom.tier2_reward} Kitobcha</b>!\n\n"
        f"📅 <b>Muddat:</b> {date_range}\n\n"
        f"🎁 Yiqqan Kitobchalaringizga <b>Kitob Challenge do'koni</b>dan "
        f"qimmatbaho sovg'alar oling — qancha ko'p Kitobcha, shuncha zo'r sovg'a!\n\n"
        f"👇 Qo'shiling — shaxsiy havolangizni darhol yuboramiz!"
    )
    keyboard = _boom_join_keyboard(boom.id)
    # Photo+caption when the admin attached a banner, plain text otherwise --
    # same choice the welcome DM (referral_boom.py join handler) already
    # makes, just via the HTTP API (this task is sync) instead of aiogram.
    photo_url = f"{_settings.WEB_DOMAIN}{boom.image.url}" if boom.image else None
    send_method = "sendPhoto" if photo_url else "sendMessage"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{send_method}"

    def _payload(chat_id):
        if photo_url:
            return {"chat_id": chat_id, "photo": photo_url, "caption": text,
                     "parse_mode": "HTML", "reply_markup": keyboard}
        return {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                "reply_markup": keyboard, "disable_web_page_preview": "true"}

    for group_id, thread_id in _announce_targets():
        try:
            data = _payload(group_id)
            if thread_id:
                data["message_thread_id"] = thread_id
            requests.post(
                url,
                data=data,
                timeout=10,
            )
        except Exception as e:
            print(f"boom announce group {group_id}: {e}")

    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent = 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(url, data=_payload(chat_id), timeout=5)
            if resp.ok:
                sent += 1
            elif resp.status_code == 429:
                _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception:
            pass
        _time.sleep(0.05)

    from tgbot.models import ReferralBoom as _RB
    _RB.objects.filter(id=boom.id).update(announced_at=timezone.now())
    print(f"announce_referral_boom: boom_id={boom.id} sent={sent}")

    try:
        admin_gid = _os.environ.get("ADMIN_GROUP_ID", "")
        if admin_gid:
            total_users = qs.count()
            requests.post(
                url,
                data={
                    "chat_id": admin_gid,
                    "text": (
                        f"🚀 <b>Yaxshilik ulashuvchi e'lon qilindi!</b>\n\n"
                        f"💥 {boom.title}\n"
                        f"📅 {date_range}\n"
                        f"🪙 {boom.tier1_reward}/taklif (1-{boom.tier1_cap}), "
                        f"{boom.tier2_reward}/taklif ({boom.tier1_cap}+)\n"
                        f"⏰ Har ishtirokchiga {boom.total_reminders} ta eslatma\n\n"
                        f"📨 Jo'natildi: <b>{sent}</b> / {total_users}"
                    ),
                    "parse_mode": "HTML",
                },
                timeout=5,
            )
    except Exception as e:
        print(f"boom announce admin notif failed: {e}")


def broadcast_library_music_update():
    """One-off announcement: library background music + general 'lots of new
    stuff, go look' nudge, plus a soft teaser for the upcoming 'Yaxshilik
    ulashish' competition. Sent to every active group and every registered,
    non-blocked user's DM. Callable directly (used by the internal trigger
    view) or via Celery. Returns {"groups": N, "users": N}."""
    import time as _time
    from django.conf import settings as _settings

    site_url = f"{_settings.WEB_DOMAIN}/kutubxona/"
    bot_username = _get_bot_username() or "kitob_challange_bot"

    text_uz = (
        "🎶 <b>Kutubxonaga yangi ruh kirdi!</b>\n\n"
        "Endi kitob o'qiyotganingizda fonda asta Betxoven, Bax va Motsart "
        "jaranglaydi 🎻 — xohlasangiz bir tugma bilan o'chirib qo'yasiz.\n\n"
        "Va bu hali hammasi emas... juda ko'p yangi narsalar bor, o'zingiz "
        "kirib ko'rganingiz ma'qul 👀\n\n"
        "🤫 <i>Sir tut:</i> tez orada katta \"Yaxshilik ulashish\" musobaqasi "
        "boshlanadi. Kuzatib boring!\n\n"
        "👇 Kutubxonani hoziroq oching"
    )
    text_ru = (
        "🎶 <b>В библиотеке — новая атмосфера!</b>\n\n"
        "Теперь во время чтения тихо звучит классика — Бетховен, Бах и "
        "Моцарт 🎻 — при желании выключаете одной кнопкой.\n\n"
        "И это ещё не всё... появилось много нового, загляните сами 👀\n\n"
        "🤫 <i>По секрету:</i> совсем скоро стартует большой конкурс "
        "«Делимся добром». Следите за новостями!\n\n"
        "👇 Откройте библиотеку прямо сейчас"
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # web_app buttons only work in private chats (Telegram API restriction) --
    # groups get a plain url button into the bot instead.
    dm_keyboard = json.dumps({"inline_keyboard": [[{
        "text": "📚 Kutubxonani ochish", "web_app": {"url": site_url},
    }]]})
    group_keyboard = json.dumps({"inline_keyboard": [[{
        "text": "📚 Kutubxonani ochish", "url": f"https://t.me/{bot_username}",
    }]]})

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
            print(f"library music announce group {group_id}: {e}")

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

    print(f"broadcast_library_music_update: groups_sent={groups_sent} users_sent={users_sent}")
    return {"groups": groups_sent, "users": users_sent}


def unblock_and_apologize_false_positives():
    """One-off recovery: mark_unreachable_users' "not found" trigger (fixed
    in this same change) false-positived on a wave of mostly incomplete/
    unregistered signups, silently locking them out via bulk .update()
    (which bypasses django-auditlog, hence zero audit trail for the block
    itself). Unblocks everyone currently is_blocked=True and apologizes by
    DM where deliverable. Per-row .save() so THIS action is properly
    audited, unlike the bug it's fixing. Returns {"unblocked": N, "notified": N}."""
    import time as _time

    text_uz = (
        "🙏 <b>Uzr so'raymiz!</b>\n\n"
        "Texnik nosozlik tufayli hisobingiz vaqtincha xato ravishda "
        "cheklangan edi. Hoziroq to'liq tiklandi — botdan yana erkin "
        "foydalanishingiz mumkin.\n\n"
        "Noqulaylik uchun chin dildan uzr so'raymiz! 🙏"
    )
    text_ru = (
        "🙏 <b>Приносим извинения!</b>\n\n"
        "Из-за технического сбоя ваш аккаунт был по ошибке временно "
        "ограничен. Сейчас всё полностью восстановлено — вы снова можете "
        "свободно пользоваться ботом.\n\n"
        "Искренне просим прощения за неудобства! 🙏"
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    unblocked = 0
    notified = 0
    for profile in TelegramProfile.objects.filter(is_blocked=True):
        profile.is_blocked = False
        profile.save(update_fields=["is_blocked"])
        unblocked += 1
        try:
            text = text_ru if profile.language == "ru" else text_uz
            resp = requests.post(
                url,
                data={"chat_id": profile.telegram_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
            if resp.ok:
                notified += 1
            elif resp.status_code == 429:
                _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception:
            pass
        _time.sleep(0.05)

    print(f"unblock_and_apologize_false_positives: unblocked={unblocked} notified={notified}")
    return {"unblocked": unblocked, "notified": notified}


def retire_challenge_and_launch_boom(challenge_id=None, boom_days=7):
    """One-off transition: retire the currently-active 3-day Challenge (or
    the given one) and launch a fresh Yaxshilik ulashuvchi boom in its
    place. If the challenge being retired is a referrals_daily one, each
    participant's ALREADY-MADE referrals during the challenge's window are
    carried over as their starting boom referrals_count (+ the equivalent
    tier1 Kitobcha) -- so switching systems mid-challenge doesn't erase
    real effort already made. The challenge's own reward payout is skipped
    for transferred participants (marked reward_given=True directly) to
    avoid paying the same referrals out twice, once per system. Other
    challenge types have nothing comparable to carry over -- just retired.
    launch_referral_boom() sends the full announcement broadcast to every
    group + registered user, same as any other boom launch."""
    from tgbot.models import (
        Challenge, ChallengeParticipant, UserReferal, ReferralBoom, ReferralBoomParticipant,
    )

    challenge = (
        Challenge.objects.filter(id=challenge_id).first() if challenge_id
        else Challenge.objects.filter(is_active=True).order_by("-created_at").first()
    )
    if not challenge:
        return {"error": "no_active_challenge"}

    # Only today's referrals transfer -- not the whole (possibly multi-day)
    # challenge window -- per explicit instruction: carry over today's
    # already-made effort, nothing earlier. The new boom then keeps
    # accumulating referrals day by day on its own for its full 7-day run.
    transfers = []
    if challenge.condition_type == "referrals_daily":
        today = timezone.localdate()
        participants = list(
            ChallengeParticipant.objects.filter(challenge=challenge).select_related("user")
        )
        for p in participants:
            made = UserReferal.objects.filter(
                referrer=p.user, created_at__date=today,
            ).count()
            if made > 0:
                transfers.append((p.user, made))

    Challenge.objects.filter(id=challenge.id).update(is_active=False)
    ChallengeParticipant.objects.filter(challenge=challenge).update(reward_given=True)

    boom_id = launch_referral_boom(days=boom_days)
    boom = ReferralBoom.objects.filter(id=boom_id).first()

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    credited = 0
    for user, made in transfers:
        participant, _created = ReferralBoomParticipant.objects.get_or_create(boom=boom, user=user)
        awarded = user.update_ball(True, made * boom.tier1_reward)
        participant.referrals_count = made
        participant.kitobcha_earned = awarded
        participant.save(update_fields=["referrals_count", "kitobcha_earned"])
        credited += 1
        try:
            requests.post(
                url,
                data={
                    "chat_id": user.telegram_id,
                    "text": (
                        f"🔄 <b>«{challenge.title}» {boom.title}ga aylandi!</b>\n\n"
                        f"Siz allaqachon qilgan <b>{made}</b> ta taklifingiz yangi "
                        f"<b>{boom.title}</b> musobaqasiga o'tkazildi va "
                        f"<b>{awarded} Kitobcha</b> hisobingizga qo'shildi! 🎉\n\n"
                        f"Musobaqa endi {boom_days} kun davom etadi — davom eting!"
                    ),
                    "parse_mode": "HTML",
                },
                timeout=5,
            )
        except Exception as e:
            print(f"retire_challenge_and_launch_boom transfer DM failed uid={user.id}: {e}")

    print(f"retire_challenge_and_launch_boom: challenge_id={challenge.id} boom_id={boom_id} credited={credited}")
    return {"challenge_id": challenge.id, "boom_id": boom_id, "credited": credited}


@shared_task
def boom_reminder_tick():
    """Beat (every ~5 min): for each participant whose next scheduled reminder
    is due, send ONE playful nudge (one per tick avoids bursts). Finalizes the
    boom when the window has closed."""
    from urllib.parse import quote as _urlquote
    from tgbot.models import ReferralBoom, ReferralBoomParticipant
    from tgbot.services.referral_boom import pick_reminder, parse_iso, humanize_left, boom_share_texts

    boom = ReferralBoom.objects.filter(is_active=True).order_by("-created_at").first()
    if not boom:
        return

    now = timezone.now()
    if now > boom.end_at:
        finalize_referral_boom(boom.id)
        return
    if now < boom.start_at:
        return

    bot_username = _get_bot_username()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    participants = list(
        ReferralBoomParticipant.objects.filter(boom=boom).select_related("user")
    )
    all_counts = [pp.referrals_count for pp in participants]
    sent = 0
    for p in participants:
        schedule = p.reminder_schedule or []
        if p.reminders_sent >= len(schedule):
            continue
        due_dt = parse_iso(schedule[p.reminders_sent])
        if not due_dt or due_dt > now:
            continue

        user = p.user
        key, tmpl = pick_reminder(p.used_reminder_keys)
        code = _ensure_referral_code(user)
        link = (
            f"https://t.me/{bot_username}?start={code}"
            if bot_username and code else "Kabinet → 🌟 Referal"
        )
        ctx = {
            "referrals": p.referrals_count,
            "earned": p.kitobcha_earned,
            "balance": int(user.ball or 0),
            "left": humanize_left(boom.end_at),
            "link": link,
            "tier1": boom.tier1_reward,
            "tier2": boom.tier2_reward,
            "cap": boom.tier1_cap,
            "title": boom.title,
        }
        try:
            body = tmpl["text"].format(**ctx)
        except Exception:
            body = tmpl["text"]

        # Daily-cadence-specific addition: how many more referrals close the
        # gap to whoever's immediately ahead -- the concrete "almost there"
        # nudge a once-a-day CTA needs, since the random playful pool alone
        # doesn't always surface it.
        higher = [c for c in all_counts if c > p.referrals_count]
        if higher:
            need = min(higher) - p.referrals_count + 1
            body += (
                f"\n\n📈 Yana <b>{need} ta</b> do'st taklif qilsangiz, "
                f"sizdan oldingi kishidan o'tib ketasiz!"
            )
        else:
            body += "\n\n👑 Siz hozircha reytingda birinchisiz — mavqeingizni saqlang!"

        data = {"chat_id": user.telegram_id, "text": body,
                "parse_mode": "HTML", "disable_web_page_preview": "true"}
        if bot_username and code:
            share_text = _urlquote(random.choice(boom_share_texts(user.full_name, boom.title)))
            data["reply_markup"] = json.dumps({"inline_keyboard": [[{
                "text": "📤 Do'stlarga ulashish",
                "url": f"https://t.me/share/url?url={_urlquote(link)}&text={share_text}",
            }]]})
        try:
            requests.post(url, data=data, timeout=5)
        except Exception as e:
            print(f"boom reminder failed uid={user.id}: {e}")

        used = list(p.used_reminder_keys or [])
        used.append(key)
        # Advance the pointer even on send failure so one bad chat can't wedge
        # the whole schedule.
        ReferralBoomParticipant.objects.filter(id=p.id).update(
            reminders_sent=p.reminders_sent + 1,
            used_reminder_keys=used,
        )
        sent += 1

    if sent:
        print(f"boom_reminder_tick: boom={boom.id} sent={sent}")


@shared_task
def finalize_referral_boom(boom_id):
    """Deactivate the boom, DM each participant their final tally, and send an
    admin summary. Idempotent — the is_active guard makes it run once."""
    import os as _os
    from tgbot.models import ReferralBoom, ReferralBoomParticipant

    boom = ReferralBoom.objects.filter(id=boom_id).first()
    if not boom or not boom.is_active:
        return
    ReferralBoom.objects.filter(id=boom_id).update(is_active=False)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    participants = list(
        ReferralBoomParticipant.objects.filter(boom=boom).select_related("user")
    )
    total_referrals = 0
    total_kitobcha = 0
    for p in participants:
        total_referrals += p.referrals_count
        total_kitobcha += p.kitobcha_earned
        if p.referrals_count == 0:
            continue
        dm = (
            f"🏁 <b>{boom.title} yakunlandi!</b>\n\n"
            f"👥 Takliflaringiz: <b>{p.referrals_count}</b> ta\n"
            f"🪙 Boomdan yig'ildingiz: <b>{p.kitobcha_earned} Kitobcha</b>\n"
            f"💰 Balans: <b>{int(p.user.ball or 0)} Kitobcha</b>\n\n"
            f"🛍 Endi do'kondan sovg'angizni tanlang! Rahmat 🙌"
        )
        try:
            requests.post(
                url,
                data={"chat_id": p.user.telegram_id, "text": dm, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception as e:
            print(f"boom finalize DM failed uid={p.user.id}: {e}")

    print(f"finalize_referral_boom: boom={boom_id} participants={len(participants)} "
          f"referrals={total_referrals} kitobcha={total_kitobcha}")

    try:
        admin_gid = _os.environ.get("ADMIN_GROUP_ID", "")
        if admin_gid:
            top = sorted(participants, key=lambda x: x.referrals_count, reverse=True)[:5]
            lines = [
                f"{i}. {(p.user.full_name or 'Kitobxon')[:30]} — "
                f"{p.referrals_count} taklif / {p.kitobcha_earned} Kitobcha"
                for i, p in enumerate(top, 1) if p.referrals_count
            ]
            requests.post(
                url,
                data={
                    "chat_id": admin_gid,
                    "text": (
                        f"📊 <b>Yakunlandi: {boom.title}</b>\n\n"
                        f"👥 Ishtirokchilar: <b>{len(participants)}</b>\n"
                        f"🔗 Jami takliflar: <b>{total_referrals}</b>\n"
                        f"🪙 Jami tarqatilgan: <b>{total_kitobcha} Kitobcha</b>\n\n"
                        + ("<b>TOP:</b>\n" + "\n".join(lines) if lines else "Takliflar bo'lmadi.")
                    ),
                    "parse_mode": "HTML",
                },
                timeout=5,
            )
    except Exception as e:
        print(f"boom finalize admin notif failed: {e}")


@shared_task
def boom_daily_standings():
    """Once daily (end of day): DM every participant of the currently active
    Referral BOOM their rank + a top-5 snippet. No-ops silently if no boom
    is live. Separate from finalize_referral_boom's one-time final tally —
    this repeats every day the boom runs, to keep the competition visible."""
    from tgbot.models import ReferralBoom, ReferralBoomParticipant

    boom = ReferralBoom.objects.filter(is_active=True).order_by("-created_at").first()
    if not boom:
        return

    participants = list(
        ReferralBoomParticipant.objects.filter(boom=boom)
        .select_related("user")
        .order_by("-referrals_count", "-kitobcha_earned", "joined_at")
    )
    if not participants:
        return

    days_left = max(0, (boom.end_at - timezone.now()).days)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    sent = 0
    for rank, p in enumerate(participants, start=1):
        # Personal only -- no other participants' names/counts, just this
        # user's own numbers and how far the person directly above them is.
        if rank == 1:
            progress_line = "🏆 Siz hozircha yetakchisiz! Shu tezlikda davom eting 🔥"
        else:
            above = participants[rank - 2]
            needed = max(1, above.referrals_count - p.referrals_count + 1)
            progress_line = (
                f"🔼 Tepadagi ishtirokchidan o'tish uchun yana <b>{needed}</b> ta "
                f"taklif kerak!"
            )
        text = (
            f"📊 <b>{boom.title} — kunlik statistika</b>\n\n"
            f"📍 Sizning o'rningiz: <b>#{rank}</b> / {len(participants)}\n"
            f"👥 Takliflaringiz: <b>{p.referrals_count}</b> ta\n"
            f"🪙 Yig'ilgan: <b>{p.kitobcha_earned} Kitobcha</b>\n"
            f"⏳ Qolgan vaqt: <b>{days_left} kun</b>\n\n"
            f"{progress_line}\n\n"
            f"Yana taklif qiling — reytingda ko'tariling! 🚀"
        )
        try:
            requests.post(
                url,
                data={"chat_id": p.user.telegram_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
            sent += 1
        except Exception as e:
            print(f"boom_daily_standings DM failed uid={p.user.id}: {e}")

    print(f"boom_daily_standings: boom={boom.id} sent={sent}/{len(participants)}")


def _boom_leaderboard_block(boom, top_n=30):
    from tgbot.models import ReferralBoomParticipant

    participants = list(
        ReferralBoomParticipant.objects.filter(boom=boom, referrals_count__gt=0)
        .select_related("user")
        .order_by("-referrals_count", "joined_at")[:top_n]
    )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [
        f"{medals.get(i, f'{i}.')} {(p.user.full_name or 'Kitobxon')[:28]} — <b>{p.referrals_count}</b> ta"
        for i, p in enumerate(participants, 1)
    ]
    return "\n".join(lines) if lines else "Hali hech kim taklif qilmagan — birinchi bo'ling!"


def _broadcast_boom_update(boom, text, pin: bool = False):
    """Send `text` (photo+caption if the boom has an image, plain text
    otherwise) to every announce-group AND every registered user. When `pin`
    is set, pins the message in each group (best-effort -- the bot needs
    pin rights there; silently skipped if it doesn't have them)."""
    import time as _time
    from django.conf import settings as _settings

    photo_url = f"{_settings.WEB_DOMAIN}{boom.image.url}" if boom.image else None
    send_method = "sendPhoto" if photo_url else "sendMessage"
    send_url = f"https://api.telegram.org/bot{BOT_TOKEN}/{send_method}"
    pin_url = f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage"

    def _payload(chat_id):
        if photo_url:
            return {"chat_id": chat_id, "photo": photo_url, "caption": text, "parse_mode": "HTML"}
        return {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}

    group_sent = 0
    for group_id, thread_id in _announce_targets():
        try:
            data = _payload(group_id)
            if thread_id:
                data["message_thread_id"] = thread_id
            resp = requests.post(send_url, data=data, timeout=10)
            group_sent += 1
            if pin and resp.ok:
                msg_id = resp.json().get("result", {}).get("message_id")
                if msg_id:
                    try:
                        requests.post(
                            pin_url,
                            data={"chat_id": group_id, "message_id": msg_id,
                                  "disable_notification": "true"},
                            timeout=5,
                        )
                    except Exception:
                        pass
        except Exception as e:
            print(f"_broadcast_boom_update group {group_id}: {e}")

    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    user_sent = 0
    for chat_id in qs.values_list("telegram_id", flat=True).iterator():
        try:
            resp = requests.post(send_url, data=_payload(chat_id), timeout=5)
            if resp.ok:
                user_sent += 1
            elif resp.status_code == 429:
                _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception:
            pass
        _time.sleep(0.05)

    return group_sent, user_sent


@shared_task
def boom_recovery_announcement():
    """One-off (2026-07-31): apologize for this morning's brief interruption
    (a deploy-time bug force-finalized the boom for ~4 hours before the fix
    shipped) and re-announce the still-running competition -- WITH the boom's
    banner image, pinned in every group -- alongside a public TOP-30
    leaderboard, everywhere. Not on any schedule; call once by hand after the
    fix + DB recovery land."""
    from tgbot.models import ReferralBoom

    boom = ReferralBoom.objects.filter(is_active=True).order_by("-created_at").first()
    if not boom:
        print("boom_recovery_announcement: no active boom")
        return

    leaderboard = _boom_leaderboard_block(boom)
    days_left = max(0, (boom.end_at - timezone.now()).days)

    text = (
        f"🙏 <b>Kechirasiz!</b> Bugun qisqa texnik nosozlik tufayli «{boom.title}» "
        f"musobaqasi bir muddat to'xtab qoldi — buni darhol tuzatdik va musobaqa "
        f"xuddi to'xtamagandek davom etmoqda. Shu vaqt ichida qilgan "
        f"takliflaringiz ham to'liq hisobga olindi, hech narsa yo'qolmadi! 🎉\n\n"
        f"🏆 <b>TOP-30 — musobaqa boshlangandan beri:</b>\n{leaderboard}\n\n"
        f"⏳ Musobaqa hali <b>{days_left} kun</b> davom etadi — bu ulgurish uchun "
        f"juda katta imkoniyat! Do'stlaringizni taklif qilishda davom eting, "
        f"reytingda yuqoriga ko'tariling va qimmatbaho sovg'alarga ega bo'ling! 🎁"
    )
    group_sent, user_sent = _broadcast_boom_update(boom, text, pin=True)
    print(f"boom_recovery_announcement: boom={boom.id} groups={group_sent} users={user_sent}")


@shared_task
def boom_public_daily_update():
    """Once daily: public TOP-30 leaderboard + days-left reminder, posted to
    every group and DMed to every registered user. Distinct from
    boom_daily_standings (personal-only, no other names) -- this is the
    openly-public version the competition also wants. No-ops if no boom
    is live."""
    from tgbot.models import ReferralBoom

    boom = ReferralBoom.objects.filter(is_active=True).order_by("-created_at").first()
    if not boom:
        return

    leaderboard = _boom_leaderboard_block(boom)
    days_left = max(0, (boom.end_at - timezone.now()).days)
    text = (
        f"📊 <b>{boom.title} — kunlik statistika</b>\n\n"
        f"🏆 <b>TOP-30:</b>\n{leaderboard}\n\n"
        f"⏳ Musobaqa hali <b>{days_left} kun</b> davom etadi — ulgurish uchun "
        f"vaqt bor! Do'stlaringizni taklif qiling, reytingda ko'tariling va "
        f"sovg'alarga ega bo'ling! 🎁"
    )
    group_sent, user_sent = _broadcast_boom_update(boom, text, pin=False)
    print(f"boom_public_daily_update: boom={boom.id} groups={group_sent} users={user_sent}")


# ────────────────────────────────────────────────────────────────────────
# Reader title nominations — community "titles" across 5 categories over the
# last 30 days. Admin-triggered broadcast to all groups + every user, with a
# "send report" CTA so others are nudged to compete for a title.
# ────────────────────────────────────────────────────────────────────────
@shared_task
def announce_reader_titles():
    import datetime as _dt
    import time as _time
    from zoneinfo import ZoneInfo
    from django.db.models import Count, Sum
    from django.db.models.functions import ExtractHour, Length

    TASHKENT = ZoneInfo("Asia/Tashkent")
    since = timezone.now() - _dt.timedelta(days=30)
    base = ConfirmationReport.objects.filter(date__gte=since, user__is_blocked=False)

    def _name(uid):
        u = TelegramProfile.objects.filter(id=uid).first()
        return escape((u.full_name if u else None) or "Kitobxon")

    def _top_hours(hours):
        return (
            base.annotate(h=ExtractHour("date", tzinfo=TASHKENT))
            .filter(h__in=hours).values("user_id")
            .annotate(c=Count("id")).order_by("-c").first()
        )

    def _top_audio():
        return (
            base.filter(is_audio=True).values("user_id")
            .annotate(t=Sum("minutes_listened")).filter(t__gt=0)
            .order_by("-t").first()
        )

    def _top_reviews():
        return (
            base.annotate(_l=Length("conclusion")).filter(_l__gte=200)
            .values("user_id").annotate(c=Count("id")).order_by("-c").first()
        )

    def _top_giver():
        from tgbot.models import Congratulation
        row = (
            Congratulation.objects
            .filter(created_at__gte=since, congratulator__is_blocked=False)
            .values("congratulator_id").annotate(c=Count("id")).order_by("-c").first()
        )
        return {"user_id": row["congratulator_id"], "c": row["c"]} if row else None

    def _top_receiver():
        from tgbot.models import Congratulation
        row = (
            Congratulation.objects
            .filter(created_at__gte=since)
            .values("achievement__user_id").annotate(c=Count("id")).order_by("-c").first()
        )
        return {"user_id": row["achievement__user_id"], "c": row["c"]} if row else None

    def _top_streak():
        """Longest unbroken run of consecutive report-days, across all time."""
        from collections import defaultdict
        from django.db.models.functions import TruncDate
        rows = (
            ConfirmationReport.objects.filter(user__is_blocked=False)
            .annotate(d=TruncDate("date")).values_list("user_id", "d").distinct()
        )
        days = defaultdict(set)
        for uid, d in rows:
            if d:
                days[uid].add(d)
        best_uid, best = None, 0
        for uid, dset in days.items():
            sd = sorted(dset)
            cur = longest = 1
            for i in range(1, len(sd)):
                if (sd[i] - sd[i - 1]).days == 1:
                    cur += 1
                    longest = max(longest, cur)
                else:
                    cur = 1
            if longest > best:
                best, best_uid = longest, uid
        return {"user_id": best_uid, "c": best} if best_uid else None

    night    = _top_hours([22, 23, 0, 1, 2, 3, 4])       # 22:00–04:59
    morning  = _top_hours([5, 6, 7, 8, 9])               # 05:00–09:59
    day      = _top_hours([10, 11, 12, 13, 14, 15, 16, 17])  # 10:00–17:59
    audio    = _top_audio()
    reviews  = _top_reviews()
    giver    = _top_giver()
    receiver = _top_receiver()
    streak   = _top_streak()

    lines = [
        "🏅 <b>KITOBXON NOMINATSIYALARI</b>\n<i>(oxirgi 30 kun natijalari)</i>\n",
        "<i>Quyidagi g'oliblar har bir toifada eng faol bo'lgan kitobxonlardir. "
        "Ularni bitta tugma bilan tabriklashingiz mumkin 👇</i>\n",
    ]
    # Collect winners for the single shared "Tabriklash" button.
    # Each entry: {"k": category_key, "t": winner_telegram_id}.
    winners = []

    def _add(key, emoji, title, desc, row, unit, statkey="c"):
        if row:
            uid = row["user_id"]
            lines.append(
                f"{emoji} <b>{title}</b>\n"
                f"   <i>{desc}</i>\n"
                f"   🏆 {_name(uid)} — <b>{row[statkey]} {unit}</b>"
            )
            w = TelegramProfile.objects.filter(id=uid).first()
            if w and w.telegram_id:
                winners.append({"k": key, "t": w.telegram_id})
        else:
            lines.append(f"{emoji} <b>{title}</b>\n   <i>{desc}</i>\n   — hali nomzod yo'q —")

    _add("night",    "🌙", "Tungi kitobxon",        "Tunda (22:00–05:00) eng ko'p hisobot yuborgan", night,    "ta hisobot")
    _add("morning",  "🌅", "Saharxez kitobxon",     "Saharda (05:00–10:00) eng faol — erta turar", morning,  "ta hisobot")
    _add("day",      "☀️", "Kunduzgi kitobxon",     "Kunduzi (10:00–18:00) eng ko'p o'qigan",       day,      "ta hisobot")
    _add("audio",    "🎧", "Audio shaydosi",        "Eng ko'p audiokitob tinglagan",                audio,    "daqiqa", statkey="t")
    _add("review",   "✍️", "So'z ustasi",           "Eng ko'p mazmunli xulosa (200+ belgi) yozgan", reviews,  "ta xulosa")
    _add("giver",    "🤝", "Sahiy tabriklovchi",    "Boshqalarni eng ko'p tabriklagan sahiy inson", giver,    "ta tabrik")
    _add("receiver", "🎁", "Eng ko'p tabriklangan", "Yutuqlari uchun eng ko'p tabrik olgan",        receiver, "ta tabrik")
    _add("streak",   "🔥", "Eng intizomli",         "Eng uzoq uzluksiz (har kuni) o'qigan — intizom timsoli", streak, "kun streak")
    lines.append("\n📚 Siz ham hisobot yuboring va o'z nominatsiyangizni egallang! 🔥")
    text = "\n".join(lines)

    # Persist the winners so the single shared button can DM all of them.
    from tgbot.models import ReaderTitleAnnouncement
    ann = ReaderTitleAnnouncement.objects.create(winners=winners)

    # Single 🎉 Tabriklash button (congratulates every winner) + report CTA.
    kb_rows = []
    if winners:
        kb_rows.append([{
            "text": "🎉 G'oliblarni tabriklash",
            "callback_data": f"rtc_all:{ann.id}",
        }])
    kb_rows.append([{"text": "📚 Hisobot jo'natish", "callback_data": "cta_send_report"}])
    keyboard = json.dumps({"inline_keyboard": kb_rows})
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for group_id, thread_id in _leaderboard_targets():
        try:
            data = {"chat_id": group_id, "text": text, "parse_mode": "HTML",
                    "reply_markup": keyboard}
            if thread_id:
                data["message_thread_id"] = thread_id
            resp = requests.post(url, data=data, timeout=10)
            if not resp.ok:
                print(f"reader_titles group {group_id} FAILED: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"reader_titles group {group_id}: {e}")

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
    print(f"announce_reader_titles: sent={sent}")
    return sent


# ────────────────────────────────────────────────────────────────────────
# Founder's gift — grant every registered user a short Premium window and
# announce it everywhere. Premium badge + 2x Kitobcha etc. apply automatically
# since they key off an active paid Payment.
# ────────────────────────────────────────────────────────────────────────
@shared_task
def grant_everyone_premium(days=1, announce=True):
    import datetime as _dt
    import time as _time
    from tgbot.models import Payment

    today = timezone.localdate()
    end = today + _dt.timedelta(days=days)

    user_ids = list(
        TelegramProfile.objects
        .filter(is_registered=True, is_blocked=False)
        .values_list("id", flat=True)
    )
    rows = [
        Payment(user_id=uid, amount=0, start_date=today, end_date=end, status="paid")
        for uid in user_ids
    ]
    Payment.objects.bulk_create(rows, batch_size=500)
    granted = len(rows)
    print(f"grant_everyone_premium: granted={granted} end={end}")

    if not announce:
        return granted

    text = (
        "🎁 <b>LOYIHA ASOSCHISIDAN SOVG'A!</b> 🎁\n\n"
        "Barcha kitobxonlarga <b>24 soatlik 💎 Premium</b> sovg'a qilindi! 🔥\n\n"
        "Shu 24 soat ichida sizda:\n"
        "🪙 <b>2 barobar ko'p Kitobcha</b> — har bir hisobot, yutuq va referal uchun\n"
        "♾️ <b>Kuniga cheksiz hisobot</b>\n"
        "📊 <b>Kunlik shaxsiy hisobot</b> va 📈 <b>o'sish grafigi</b>\n"
        "🏆 <b>Challenge tarixi</b>\n"
        "💎 <b>Premium belgisi</b> — reyting va guruhlarda ajralib turasiz\n\n"
        "Imkoniyatdan unumli foydalaning — ko'proq o'qing, ko'proq yutuqqa erishing! 📚🚀"
    )
    keyboard = _cta_reply_markup()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for group_id, thread_id in _announce_targets():
        try:
            data = {"chat_id": group_id, "text": text, "parse_mode": "HTML",
                    "reply_markup": keyboard}
            if thread_id:
                data["message_thread_id"] = thread_id
            resp = requests.post(url, data=data, timeout=10)
            if not resp.ok:
                print(f"founder gift group {group_id} FAILED: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"founder gift group {group_id}: {e}")

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
    print(f"grant_everyone_premium: announced sent={sent}")
    return granted


# ────────────────────────────────────────────────────────────────────────
# Kitob Viktorina — twice-daily "guess the book" quiz + its promo reminders.
# ────────────────────────────────────────────────────────────────────────
def _viktorina_join_keyboard():
    """Inline keyboard for the promo: a deep-link into /start so users can
    upgrade to Premium, plus the group invite when one is configured."""
    from tgbot.models import RequiredGroup

    rows = []
    invite = (
        RequiredGroup.objects
        .exclude(invite_link__isnull=True).exclude(invite_link__exact="")
        .values_list("invite_link", flat=True)
        .first()
    )
    if invite:
        rows.append([{"text": "📚 Guruhga qo'shilish", "url": invite}])
    username = _get_bot_username()
    if username:
        rows.append([{"text": "💎 Premium / Botni ochish", "url": f"https://t.me/{username}?start=viktorina"}])
    return json.dumps({"inline_keyboard": rows}) if rows else None


def _broadcast_quiz_round(quiz_round):
    """Post an already-built Viktorina round to every reading group only.
    Shared by the scheduled task and the admin button. The Viktorina is
    group-only by design — it is NOT DM'd to users."""
    from tgbot.services.book_quiz import build_quiz_text, quiz_keyboard

    text = build_quiz_text(quiz_round)
    keyboard = quiz_keyboard(quiz_round)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # 1) Groups — everyone sees it; any group-member can answer (Premium = ×2).
    #    Remember each posted copy so the live right/wrong board can edit them.
    posted = []
    for group_id, thread_id in _game_targets():
        try:
            data = {"chat_id": group_id, "text": text, "parse_mode": "HTML",
                    "reply_markup": keyboard, "disable_web_page_preview": "true"}
            if thread_id:
                data["message_thread_id"] = thread_id
            resp = requests.post(url, data=data, timeout=10)
            if resp.ok:
                mid = resp.json().get("result", {}).get("message_id")
                if mid:
                    posted.append({"chat_id": str(group_id), "message_id": mid})
        except Exception as e:
            print(f"post_book_quiz group {group_id}: {e}")
    if posted:
        quiz_round.group_messages = posted
        quiz_round.save(update_fields=["group_messages"])

    # Group-only by design: the Viktorina is no longer DM'd to users — it lives
    # in the reading groups, not in the bot's private chats.
    print(f"post_book_quiz: round #{quiz_round.id} posted to {len(posted)} group(s)")


def refresh_quiz_boards(quiz_round):
    """Edit every posted group copy of the quiz to show the live right/wrong
    board. Called after each answer. Best-effort: ignores rate-limit / unchanged
    errors so a busy round never breaks answering.

    IMPORTANT: `reply_markup` MUST be re-sent on every edit. editMessageText
    does NOT preserve a previous keyboard when the param is omitted — Telegram
    clears it — a prior attempt at "just don't touch it" briefly shipped and
    removed the A/B/C/D buttons from every posted quiz entirely (worse than
    the double-tap issue it was meant to fix). See on-going investigation for
    the actual double-tap cause; do not remove reply_markup again."""
    from tgbot.services.book_quiz import build_quiz_text_with_board, quiz_keyboard

    msgs = quiz_round.group_messages or []
    if not msgs:
        return
    text = build_quiz_text_with_board(quiz_round)
    keyboard = quiz_keyboard(quiz_round)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    for m in msgs:
        try:
            requests.post(
                url,
                data={
                    "chat_id": m["chat_id"], "message_id": m["message_id"],
                    "text": text, "parse_mode": "HTML",
                    "reply_markup": keyboard, "disable_web_page_preview": "true",
                },
                timeout=8,
            )
        except Exception:
            pass


@shared_task
def post_book_quiz():
    """Build one fresh Viktorina round and broadcast it. Skips silently when
    there isn't enough material to build a quote."""
    from tgbot.services.book_quiz import build_quiz_round

    quiz_round = build_quiz_round()
    if not quiz_round:
        print("post_book_quiz: no quiz could be built (not enough conclusions yet)")
        return
    _broadcast_quiz_round(quiz_round)


@shared_task
def send_viktorina_promo():
    """Promote the Viktorina to everyone: once a day for the first 10 days after
    launch, then only on a random ~40% of days. Each send pulls a fresh creative
    message (jokes / mood-lifters / reading nudges) from the pool."""
    from tgbot.models import BookQuizPromoState
    from tgbot.services.book_quiz import pick_promo_text

    state = BookQuizPromoState.get_solo()
    today = timezone.localdate()
    if state.launched_on is None:
        state.launched_on = today
        state.save(update_fields=["launched_on"])

    if state.last_sent_on == today:
        return  # never twice in one day

    day_index = (today - state.launched_on).days  # 0 on launch day
    if day_index < 10:
        should_send = True
    else:
        should_send = random.random() < 0.4
    if not should_send:
        return

    base_text = pick_promo_text()
    keyboard = _viktorina_join_keyboard()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data_extra = {"reply_markup": keyboard} if keyboard else {}

    def _nearest_achievement_nudge(user_obj) -> str:
        """Return a motivational line about the closest not-yet-unlocked achievement."""
        try:
            from tgbot.services.achievements import compute_user_stats, ACHIEVEMENTS_RAW
            from tgbot.models import UserAchievement as _UA

            stats = compute_user_stats(user_obj)
            awarded = set(_UA.objects.filter(user=user_obj).values_list("code", flat=True))

            # Map stat field → human label for the nudge message.
            _FIELD_LABELS = {
                "reports":         ("hisobot",       "hisobot yubor"),
                "pages":           ("bet",            "bet o'qi"),
                "books_finished":  ("kitob",          "kitob tugatish"),
                "max_streak":      ("kunlik streak",  "kun ketma-ket o'qi"),
                "long_conclusions":("xulosa",         "uzun xulosa yoz"),
                "referrals":       ("do'st",          "do'st taklif qil"),
                "audio_minutes":   ("daqiqa audio",   "daqiqa audio tinla"),
                "max_day_pages":   ("bet/kun",        "bir kunda o'qi"),
                "quizzes_played":  ("quiz",           "quizda qatnash"),
                "quiz_correct":    ("to'g'ri javob",  "viktorinada to'g'ri javob ber"),
            }

            best_ach = None
            best_left = None

            for ach in ACHIEVEMENTS_RAW:
                if ach["code"] in awarded:
                    continue
                cond = ach.get("cond")
                if cond is None:
                    continue
                # Find which stat field this achievement targets and its threshold.
                # _at_least returns a lambda; inspect via closure if possible,
                # otherwise fall back to a brute-force gap scan.
                try:
                    cell = cond.__closure__
                    if cell and len(cell) >= 2:
                        field = cell[0].cell_contents
                        target = cell[1].cell_contents
                        if isinstance(field, str) and isinstance(target, (int, float)):
                            current = stats.get(field, 0)
                            if current < target:
                                left = target - current
                                if best_left is None or left < best_left:
                                    best_left = left
                                    best_ach = (ach, field, target, left)
                except Exception:
                    pass

            if not best_ach:
                return ""

            ach, field, target, left = best_ach
            _unit, _action = _FIELD_LABELS.get(field, (field, field))
            emoji = ach["emoji"]
            title = ach["title_uz"]
            return (
                f"\n\n🎯 <b>Eng yaqin yutuqqa {left} ta {_unit} qoldi!</b>\n"
                f"{emoji} <b>{title}</b>\n"
                f"💪 {left} ta {_action} — va yutuq seniki! 🏆"
            )
        except Exception:
            return ""

    import time as _time
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    sent = failed = 0
    for user_obj in qs.iterator():
        nudge = _nearest_achievement_nudge(user_obj)
        text = base_text + nudge
        try:
            resp = requests.post(
                url,
                data={"chat_id": user_obj.telegram_id, "text": text,
                      "parse_mode": "HTML", **data_extra},
                timeout=5,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
                if resp.status_code == 429:
                    _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception:
            failed += 1
        _time.sleep(0.05)

    state.last_sent_on = today
    state.save(update_fields=["last_sent_on"])
    print(f"send_viktorina_promo: day_index={day_index} sent={sent} failed={failed}")


@shared_task
def recompute_optimal_send_hours():
    """Weekly task: refresh optimal_send_hour for all users.

    Delegates to the compute_optimal_send_hours management command so the
    exact same logic is used whether you run it manually or via beat.
    """
    from django.core.management import call_command
    call_command("compute_optimal_send_hours", verbosity=1)


@shared_task
def send_premium_upsell():
    """
    Every 2 days (see src/celery_app.py schedule) — send a personalised
    Premium upsell message to free users who score >= 40 on the conversion
    predictor.

    Each message references the user's own strongest reading signal
    (streak length, avg pages, total reports, long conclusions, current
    Kitobcha balance) so it reads like an observation, not a broadcast ad —
    format_upsell_message also rotates the phrasing randomly so a
    persistent free user doesn't see an identical message every time.

    Only the top 200 scoring free users are contacted per run to keep the
    volume manageable and avoid spamming low-signal users.
    """
    import time as _time
    from tgbot.services.premium_conversion import (
        get_top_candidates,
        format_upsell_message,
    )

    candidates = get_top_candidates(limit=200, min_score=40)
    if not candidates:
        print("[premium_upsell] No eligible candidates found.")
        return

    print(f"[premium_upsell] Sending to {len(candidates)} candidates...")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    reply_markup = json.dumps({"inline_keyboard": [[
        {"text": "💎 Premium olish", "callback_data": "menu:premium"},
    ]]})
    sent = skipped = failed = 0

    for result in candidates:
        text = format_upsell_message(result, language=result.language)
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": result.telegram_id,
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
                if resp.status_code == 429:
                    _time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
        except Exception as e:
            print(f"[premium_upsell] send failed uid={result.user_id}: {e}")
            failed += 1
        _time.sleep(0.05)

    print(f"[premium_upsell] done. sent={sent} skipped={skipped} failed={failed}")


def _premium_expiry_reminder_text(name: str, language: str) -> str:
    """Funny, retention-focused nudge — randomized so a user renewing more
    than once doesn't see the same line twice in a row."""
    if language == "ru":
        variants = [
            f"😱 <b>{name}</b>, через 3 дня ваш Premium исчезнет — как Золушка в полночь, "
            f"только вместо кареты вы теряете 2× Kitobcha.",
            f"⏳ <b>{name}</b>, обратный отсчёт начался: 3 дня до конца Premium. "
            f"AI-отчёт по субботам будет по вам скучать.",
            f"🥲 <b>{name}</b>, ваш Premium уходит через 3 дня — тихо, без прощания, "
            f"как сосед, который переезжает ночью.",
            f"🔔 Напоминание от будущего вас: <b>{name}</b>, продлите Premium сейчас, "
            f"чтобы не терять 2× Kitobcha за каждый отчёт с этой субботы.",
            f"📉 <b>{name}</b>, через 3 дня графики роста, история отчётов и 2× награды "
            f"снова станут для вас заблокированными. Пока не поздно — продлите!",
        ]
    else:
        variants = [
            f"😱 <b>{name}</b>, 3 kundan keyin Premiumingiz g'oyib bo'ladi — soat 12 dagi "
            f"Zolushka kabi, faqat karetangiz emas, 2× Kitobchangiz yo'qoladi.",
            f"⏳ <b>{name}</b>, hisob boshlandi: Premiumga 3 kun qoldi. Shanba kunlari "
            f"keladigan AI hisobot sizni sog'inib qoladi.",
            f"🥲 <b>{name}</b>, Premiumingiz 3 kundan keyin jimgina ketadi — xayrlashmasdan, "
            f"tunda ko'chib ketayotgan qo'shni kabi.",
            f"🔔 Kelajakdagi o'zingizdan eslatma: <b>{name}</b>, hozir uzaytiring — shanbadan "
            f"boshlab har bir hisobot uchun 2× Kitobchani yo'qotmang.",
            f"📉 <b>{name}</b>, 3 kundan so'ng o'sish grafigi, hisobotlar tarixi va 2× "
            f"mukofotlar yana qulflanadi. Hali kech emas — uzaytiring!",
            f"🚨 <b>{name}</b>, Premiumingiz 3 kunlik marraga yetdi — bu marafonni "
            f"tugatib qo'ymang, bir tugma bosish qoldi.",
            f"💔 <b>{name}</b>, 3 kundan keyin Premium sizni tark etadi. Ajralishni "
            f"to'xtatishning yagona yo'li bor: uzaytirish tugmasi.",
        ]
    return random.choice(variants)


@shared_task
def send_premium_expiry_reminders():
    """Daily (19:00 Tashkent) — DM every paying user whose CURRENT Premium
    (their latest paid Payment.end_date, since renewals write a new row
    rather than editing the old one — see Payment.grant_or_extend) lapses in
    exactly 3 days. A funny, retention-focused nudge with a one-tap renew
    button, since losing 2x Kitobcha / AI report / growth charts is a real
    downgrade most users won't notice coming until it's already gone."""
    import datetime as _dt
    from django.db.models import Max
    from tgbot.models import Payment as _Pay

    today = timezone.localdate()
    target = today + _dt.timedelta(days=3)

    latest_ends = (
        _Pay.objects.filter(status="paid")
        .values("user_id")
        .annotate(latest_end=Max("end_date"))
    )
    user_ids = [row["user_id"] for row in latest_ends if row["latest_end"] == target]
    if not user_ids:
        print("[premium_expiry_reminder] No users expiring in 3 days.")
        return

    users = TelegramProfile.objects.filter(
        id__in=user_ids, is_registered=True, is_blocked=False,
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    reply_markup = json.dumps({"inline_keyboard": [[
        {"text": "🔥 Premiumni uzaytirish", "callback_data": "menu:premium"},
    ]]})
    sent = failed = 0
    for user in users:
        text = _premium_expiry_reminder_text(user.full_name or "Kitobxon", user.language or "uz")
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": user.telegram_id, "text": text,
                    "parse_mode": "HTML", "reply_markup": reply_markup,
                },
                timeout=5,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[premium_expiry_reminder] send failed uid={user.id}: {e}")
            failed += 1

    print(f"[premium_expiry_reminder] done. sent={sent} failed={failed}")


# ── Daily trial Premium giveaway — 10 random users get 3 free hours ──────────
TRIAL_PREMIUM_HOURS = 3
TRIAL_PREMIUM_DAILY_COUNT = 10


def _trial_premium_intro_text() -> str:
    return (
        f"🎉 <b>Tabriklaymiz! Sizga {TRIAL_PREMIUM_HOURS} soatlik BEPUL Premium sovg'a qilindi!</b>\n\n"
        f"⏳ Amal qilish muddati: <b>{TRIAL_PREMIUM_HOURS} soat</b>\n\n"
        "Shu vaqt ichida sizga quyidagi imkoniyatlar ochiq:\n\n"
        "🪙 <b>×2 (ikki barobar) Kitobcha!</b> 🔥 — har bir hisobot, yutuq va referal mukofoti ikki barobar!\n"
        "♾️ <b>Cheksiz kunlik hisobotlar</b> — bir necha marotaba hisobot yuboring, barchasi avtomatik jamlanadi!\n"
        "💎 <b>Premium belgisi</b> — guruhdagi hisobotingizda 💎 belgisi bilan ajralib turasiz\n\n"
        "Yoqdimi? Muddat tugagach buni doimiy saqlab qolishning 2 ta yo'li bo'ladi — kuting! 🚀"
    )


def _trial_premium_expiry_markup() -> str:
    keyboard = {
        "inline_keyboard": [[
            {"text": "💎 Premium xarid qilish", "callback_data": "buy_plan:premium"},
            {"text": "🎁 Referal havolamni olish", "callback_data": "referral:link"},
        ]]
    }
    return json.dumps(keyboard)


@shared_task
def grant_daily_trial_premium():
    """Daily (12:00 Tashkent): randomly grant TRIAL_PREMIUM_DAILY_COUNT users a
    TRIAL_PREMIUM_HOURS-long trial Premium — see TelegramProfile.trial_premium_until
    / has_active_premium(). Introduces them to Premium's features, then schedules
    expire_trial_premium to DM the buy/referral upsell once it ends.

    Skips users who already have real Premium or are already mid-trial.
    """
    import datetime as _dt

    now = timezone.now()
    today = timezone.localdate()
    eligible_ids = list(
        TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
        .exclude(payments__status="paid", payments__end_date__gte=today)
        .exclude(trial_premium_until__gte=now)
        .values_list("id", flat=True)
        .distinct()
    )
    if not eligible_ids:
        print("grant_daily_trial_premium: no eligible users")
        return

    chosen = random.sample(eligible_ids, min(TRIAL_PREMIUM_DAILY_COUNT, len(eligible_ids)))
    until = now + _dt.timedelta(hours=TRIAL_PREMIUM_HOURS)
    text = _trial_premium_intro_text()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    sent = 0
    for uid in chosen:
        try:
            profile = TelegramProfile.objects.filter(id=uid).only("telegram_id").first()
            if not profile:
                continue
            TelegramProfile.objects.filter(id=uid).update(trial_premium_until=until)
            requests.post(
                url,
                data={"chat_id": profile.telegram_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
            expire_trial_premium.apply_async(args=[uid], countdown=TRIAL_PREMIUM_HOURS * 3600)
            sent += 1
        except Exception as e:
            print(f"grant_daily_trial_premium user {uid}: {e}")
    print(f"grant_daily_trial_premium: granted to {sent}/{len(chosen)} users")


@shared_task
def expire_trial_premium(user_id):
    """Fires TRIAL_PREMIUM_HOURS after grant_daily_trial_premium for one user.
    If they haven't bought real Premium in the meantime, DM the upsell: buy
    1-month Premium, or get their referral link (3 invites = 1 free day)."""
    from tgbot.models import Payment as _Pay

    profile = TelegramProfile.objects.filter(id=user_id).first()
    if not profile:
        return

    is_real_premium = _Pay.objects.filter(
        user=profile, status="paid", end_date__gte=timezone.localdate()
    ).exists()
    if not is_real_premium:
        text = (
            f"⌛ <b>{TRIAL_PREMIUM_HOURS} soatlik BEPUL Premium tajribangiz tugadi.</b>\n\n"
            "Yoqdimi? 🪙 ×2 Kitobcha, ♾️ cheksiz hisobot va 💎 belgisini "
            "doimiy saqlab qolishning 2 ta yo'li bor:\n\n"
            "💳 1 oylik Premium sotib oling, yoki\n"
            "🎁 Har 3 ta taklif qilingan do'stingiz uchun — 1 kun BEPUL Premium!"
        )
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": profile.telegram_id, "text": text, "parse_mode": "HTML",
                    "reply_markup": _trial_premium_expiry_markup(),
                },
                timeout=5,
            )
        except Exception as e:
            print(f"expire_trial_premium DM failed for {user_id}: {e}")

    # Clear the flag either way (tidy state; has_active_premium() already
    # treats a past timestamp as inactive so this isn't strictly required).
    TelegramProfile.objects.filter(id=user_id).update(trial_premium_until=None)


AI_QUIZ_TRIAL_DAILY_COUNT = 3
AI_QUIZ_TRIAL_HOURS = 1


@shared_task
def grant_daily_ai_quiz_trial():
    """Daily: randomly grant AI_QUIZ_TRIAL_DAILY_COUNT non-Premium users a
    1-hour window where they can use the 🤖 AI quiz-creation feature (normally
    Premium-only — see quiz_admin.py's 'ai' action gate and
    TelegramProfile.trial_ai_quiz_until). A taste of the feature, timed to
    expire and nudge a Premium upsell."""
    import datetime as _dt

    now = timezone.now()
    today = timezone.localdate()
    eligible_ids = list(
        TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
        .exclude(payments__status="paid", payments__end_date__gte=today)
        .exclude(trial_ai_quiz_until__gte=now)
        .values_list("id", flat=True)
        .distinct()
    )
    if not eligible_ids:
        print("grant_daily_ai_quiz_trial: no eligible users")
        return

    chosen = random.sample(eligible_ids, min(AI_QUIZ_TRIAL_DAILY_COUNT, len(eligible_ids)))
    until = now + _dt.timedelta(hours=AI_QUIZ_TRIAL_HOURS)
    text = (
        "🎁 <b>Tabriklaymiz! Sizga maxsus sovg'a!</b>\n\n"
        f"Keyingi <b>{AI_QUIZ_TRIAL_HOURS} soat</b> davomida 🤖 <b>AI yordamida quiz "
        "yaratish</b> — odatda faqat Premium'da mavjud bo'lgan funksiya — siz uchun ham ochiq!\n\n"
        "Matn, rasm yoki PDF yuboring — AI o'zi savollar tuzib beradi. "
        "Asosiy menyu → 📝 Kitob Quiz → 🤖 AI yordamida Quiz yaratish.\n\n"
        "⏳ Imkoniyat 1 soatdan keyin tugaydi — hoziroq sinab ko'ring!"
    )
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    sent = 0
    for uid in chosen:
        try:
            profile = TelegramProfile.objects.filter(id=uid).only("telegram_id").first()
            if not profile:
                continue
            TelegramProfile.objects.filter(id=uid).update(trial_ai_quiz_until=until)
            requests.post(
                url,
                data={"chat_id": profile.telegram_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
            expire_ai_quiz_trial.apply_async(args=[uid], countdown=AI_QUIZ_TRIAL_HOURS * 3600)
            sent += 1
        except Exception as e:
            print(f"grant_daily_ai_quiz_trial user {uid}: {e}")
    print(f"grant_daily_ai_quiz_trial: granted to {sent}/{len(chosen)} users")


@shared_task
def expire_ai_quiz_trial(user_id):
    """Fires AI_QUIZ_TRIAL_HOURS after grant_daily_ai_quiz_trial for one user.
    If they haven't bought real Premium in the meantime, DM a quick upsell."""
    from tgbot.models import Payment as _Pay

    profile = TelegramProfile.objects.filter(id=user_id).first()
    if not profile:
        return

    is_real_premium = _Pay.objects.filter(
        user=profile, status="paid", end_date__gte=timezone.localdate()
    ).exists()
    if not is_real_premium:
        text = (
            "⌛ <b>AI quiz yaratish sovg'angiz tugadi.</b>\n\n"
            "Yoqdimi? 💎 Premium bilan istalgan vaqt AI yordamida quiz yaratishingiz mumkin — "
            "shu bilan birga ×2 Kitobcha va boshqa imkoniyatlar ham ochiladi!"
        )
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": profile.telegram_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception as e:
            print(f"expire_ai_quiz_trial DM failed for {user_id}: {e}")

    TelegramProfile.objects.filter(id=user_id).update(trial_ai_quiz_until=None)


@shared_task
def announce_top_game_players():
    """Celebratory announcement of the 5 users who joined the most live games
    today, across every game type. Fires the moment the evening GameSequence
    completes (see _advance_game_sequence) so it lands right after tonight's
    games actually finish; also runs as a 23:00 fallback (beat schedule) in
    case that event-driven trigger doesn't fire for any reason — guarded by a
    same-day cache flag so it only ever posts once."""
    from collections import Counter
    from django.core.cache import cache
    from tgbot.models import (
        ChainScore, FeudScore, CastleHit, EmojiScore,
        WisdomScore, DetectiveScore, SurvivalPlayer, QuizScore, TelegramProfile,
    )

    today = timezone.localdate()
    cache_key = f"top_game_players_announced:{today}"
    try:
        if cache.get(cache_key):
            print("announce_top_game_players: already announced today, skipping")
            return
    except Exception:
        pass
    counts = Counter()

    def _tally(qs):
        for uid in qs.filter(game__starts_at__date=today).values_list("user_id", flat=True):
            counts[uid] += 1

    _tally(ChainScore.objects.all())
    _tally(FeudScore.objects.all())
    _tally(EmojiScore.objects.all())
    _tally(WisdomScore.objects.all())
    _tally(DetectiveScore.objects.all())
    _tally(SurvivalPlayer.objects.all())
    _tally(QuizScore.objects.all())
    # CastleHit has no per-user-per-game "joined" row, so dedupe (user, game) pairs.
    for uid, _gid in set(
        CastleHit.objects.filter(game__starts_at__date=today).values_list("user_id", "game_id")
    ):
        counts[uid] += 1

    if not counts:
        print("announce_top_game_players: no game activity today")
        return

    top = counts.most_common(5)
    users = {u.id: u for u in TelegramProfile.objects.filter(id__in=[uid for uid, _ in top])}
    medals = ["🥇", "🥈", "🥉", "🏅", "🎖"]
    lines = [
        "🎉🏆 <b>TANTANALI E'LON — BUGUNGI O'YINLAR YAKUNI!</b> 🏆🎉\n",
        "Bugungi barcha jonli o'yinlarda eng faol bo'lgan <b>5 ta Kitobxon</b>:\n",
    ]
    shown = 0
    for i, (uid, cnt) in enumerate(top):
        u = users.get(uid)
        if not u:
            continue
        lines.append(f"{medals[i]} <b>{escape(u.full_name or 'Kitobxon')}</b> — {cnt} ta o'yinda qatnashdi!")
        shown += 1
    if not shown:
        return
    lines.append("\n👏 Barchangizni tabriklaymiz! Ertaga ham 10:00 va 22:00 dagi o'yinlarda faol bo'ling — navbatdagi tantanali e'londa sizning ismingiz bo'lsin! 🔥📚")
    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for group_id, thread_id in _game_targets():
        try:
            data = {"chat_id": group_id, "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": "true"}
            if thread_id:
                data["message_thread_id"] = thread_id
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            print(f"announce_top_game_players group {group_id}: {e}")
    print(f"announce_top_game_players: top5={top}")
    try:
        cache.set(cache_key, True, 60 * 60 * 6)
    except Exception:
        pass


@shared_task
def send_admin_daily_report():
    """
    23:55 every day — send a full platform summary to every admin in settings.ADMINS.

    Covers:
      • Today's activity: reporters, pages, audio minutes, new users
      • Premium: active count, new subscriptions today
      • Retention: streak warnings sent, quiz answers today
      • Shop & conversion: pending purchases, premium upsell score distribution
      • Week-over-week reporter count comparison
    """
    import datetime as _dt
    from django.conf import settings as _settings
    from django.db.models import Count as _Count, Sum as _Sum
    from tgbot.models import Payment as _Pay, ShopPurchase as _SP, KitobchaLedger as _KL

    today = timezone.localdate()
    yesterday = today - _dt.timedelta(days=7)  # same weekday last week

    # ── Today's reading activity ──────────────────────────────────────────────
    today_reports = ConfirmationReport.objects.filter(date__date=today, user__is_blocked=False)
    reporter_count = today_reports.values("user_id").distinct().count()
    pages_today = today_reports.filter(is_audio=False).aggregate(s=_Sum("pages_read"))["s"] or 0
    audio_min_today = today_reports.filter(is_audio=True).aggregate(s=_Sum("minutes_listened"))["s"] or 0

    # Week-over-week: same weekday last week
    same_day_last_week = today - _dt.timedelta(days=7)
    reporters_last_week = (
        ConfirmationReport.objects
        .filter(date__date=same_day_last_week, user__is_blocked=False)
        .values("user_id").distinct().count()
    )
    wow_diff = reporter_count - reporters_last_week
    wow_str = f"▲ +{wow_diff}" if wow_diff > 0 else (f"▼ {wow_diff}" if wow_diff < 0 else "→ 0")

    # ── User base ─────────────────────────────────────────────────────────────
    total_users = TelegramProfile.objects.filter(is_registered=True, is_blocked=False).count()
    new_users_today = TelegramProfile.objects.filter(
        created_at__date=today, is_registered=True
    ).count()

    # ── Premium ───────────────────────────────────────────────────────────────
    active_premium = _Pay.objects.filter(status="paid", end_date__gte=today).count()
    new_premium_today = _Pay.objects.filter(status="paid", start_date=today).count()

    # ── Shop ──────────────────────────────────────────────────────────────────
    pending_purchases = _SP.objects.filter(status=_SP.STATUS_PENDING).count()
    purchases_today = _SP.objects.filter(created_at__date=today).count()

    # ── Viktorina (twice-daily "guess the book" — separate from the Quiz
    # system below) ─────────────────────────────────────────────────────────
    from tgbot.models import BookQuizAnswer as _BQA
    quiz_answers_today = _BQA.objects.filter(created_at__date=today).count()
    quiz_correct_today = _BQA.objects.filter(created_at__date=today, is_correct=True).count()

    # ── Quiz (user/AI-created custom quizzes — Kitob Quiz bo'limi) ───────────
    from tgbot.models import Quiz as _Q, QuizUserAnswer as _QUA
    quiz_takers_today = _QUA.objects.filter(
        answered_at__date=today
    ).values("participant__user_id").distinct().count()
    quizzes_created_today = _Q.objects.filter(created_at__date=today).count()

    # ── Kitobcha ledger (only tracks changes since the ledger shipped) ─────────
    kitobcha_earned_today = _KL.objects.filter(
        created_at__date=today, delta__gt=0
    ).aggregate(s=_Sum("delta"))["s"] or 0
    kitobcha_spent_today = -(
        _KL.objects.filter(created_at__date=today, delta__lt=0).aggregate(s=_Sum("delta"))["s"] or 0
    )

    # ── Build message ─────────────────────────────────────────────────────────
    text = (
        f"📋 <b>Admin kunlik hisobot — {today.strftime('%d.%m.%Y')}</b>\n\n"

        f"📚 <b>Bugungi o'qish:</b>\n"
        f"  👥 Hisobot berdi: <b>{reporter_count}</b> ta foydalanuvchi "
        f"(o'tgan hafta xuddi shu kun: {reporters_last_week}, {wow_str})\n"
        f"  📖 Jami betlar: <b>{pages_today:,}</b>\n"
        f"  🎧 Audio: <b>{audio_min_today}</b> daqiqa\n\n"

        f"👤 <b>Foydalanuvchilar:</b>\n"
        f"  Jami faol: <b>{total_users:,}</b>\n"
        f"  Bugun yangi: <b>{new_users_today}</b>\n\n"

        f"💎 <b>Premium:</b>\n"
        f"  Hozir faol: <b>{active_premium}</b>\n"
        f"  Bugun yangi obuna: <b>{new_premium_today}</b>\n\n"

        f"🏪 <b>Do'kon:</b>\n"
        f"  Bugun xarid: <b>{purchases_today}</b>\n"
        f"  Kutilayotgan (pending): <b>{pending_purchases}</b>\n\n"

        f"🧠 <b>Viktorina:</b>\n"
        f"  Bugun javoblar: <b>{quiz_answers_today}</b> "
        f"(to'g'ri: {quiz_correct_today})\n\n"

        f"🎯 <b>Quiz testlar:</b>\n"
        f"  Bugun yechganlar: <b>{quiz_takers_today}</b> kishi\n"
        f"  Bugun yaratilgan testlar: <b>{quizzes_created_today}</b>\n\n"

        f"🪙 <b>Kitobcha:</b>\n"
        f"  Bugun qabul qilindi: <b>+{kitobcha_earned_today:,}</b>\n"
        f"  Bugun ishlatildi: <b>-{kitobcha_spent_today:,}</b>\n\n"

        f"<i>Ushbu hisobot har kuni 23:55 da avtomatik yuboriladi.</i>"
    )

    admin_ids = getattr(_settings, "ADMINS", [])
    if not admin_ids:
        print("[admin_daily_report] No ADMINS configured in settings.")
        return

    reply_markup = json.dumps({"inline_keyboard": [[
        {"text": "📅 Kecha", "callback_data": "admin_report:yesterday"},
        {"text": "🗓 O'tgan hafta", "callback_data": "admin_report:week"},
        {"text": "📆 O'tgan oy", "callback_data": "admin_report:month"},
    ]]})

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for admin_id in admin_ids:
        try:
            requests.post(
                url,
                data={"chat_id": admin_id, "text": text, "parse_mode": "HTML", "reply_markup": reply_markup},
                timeout=5,
            )
        except Exception as e:
            print(f"[admin_daily_report] failed to send to {admin_id}: {e}")

    print(f"[admin_daily_report] sent to {len(admin_ids)} admins")


def _admin_period_bounds(period: str):
    """Returns (start_date, end_date, title) for a period-report button tap.
    Ranges are inclusive and end the day before today (today's numbers are
    still incomplete and already covered by the main daily report)."""
    import datetime as _dt
    today = timezone.localdate()
    if period == "yesterday":
        start = end = today - _dt.timedelta(days=1)
        title = f"Kechagi hisobot — {start.strftime('%d.%m.%Y')}"
    elif period == "week":
        end = today - _dt.timedelta(days=1)
        start = end - _dt.timedelta(days=6)
        title = f"O'tgan hafta hisoboti — {start.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}"
    elif period == "month":
        end = today - _dt.timedelta(days=1)
        start = end - _dt.timedelta(days=29)
        title = f"O'tgan oy hisoboti — {start.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}"
    else:
        raise ValueError(f"unknown admin report period: {period}")
    return start, end, title


def build_admin_period_report_text(period: str) -> str:
    """Same categories as send_admin_daily_report's snapshot, aggregated over
    a past day/week/month instead of "today" — powers the inline period
    buttons on the daily admin report."""
    from django.db.models import Sum as _Sum
    from tgbot.models import Payment as _Pay, ShopPurchase as _SP, KitobchaLedger as _KL, BookQuizAnswer as _BQA

    start, end, title = _admin_period_bounds(period)

    reports = ConfirmationReport.objects.filter(date__date__range=(start, end), user__is_blocked=False)
    reporter_count = reports.values("user_id").distinct().count()
    pages = reports.filter(is_audio=False).aggregate(s=_Sum("pages_read"))["s"] or 0
    audio_min = reports.filter(is_audio=True).aggregate(s=_Sum("minutes_listened"))["s"] or 0

    new_users = TelegramProfile.objects.filter(
        created_at__date__range=(start, end), is_registered=True
    ).count()
    new_premium = _Pay.objects.filter(status="paid", start_date__range=(start, end)).count()
    purchases = _SP.objects.filter(created_at__date__range=(start, end)).count()
    quiz_answers = _BQA.objects.filter(created_at__date__range=(start, end)).count()

    earned = _KL.objects.filter(created_at__date__range=(start, end), delta__gt=0).aggregate(s=_Sum("delta"))["s"] or 0
    spent = -(
        _KL.objects.filter(created_at__date__range=(start, end), delta__lt=0).aggregate(s=_Sum("delta"))["s"] or 0
    )

    return (
        f"📋 <b>{title}</b>\n\n"
        f"📚 <b>O'qish:</b>\n"
        f"  👥 Hisobot berdi: <b>{reporter_count}</b> ta foydalanuvchi\n"
        f"  📖 Jami betlar: <b>{pages:,}</b>\n"
        f"  🎧 Audio: <b>{audio_min}</b> daqiqa\n\n"
        f"👤 <b>Yangi foydalanuvchilar:</b> <b>{new_users}</b>\n\n"
        f"💎 <b>Yangi Premium obunalar:</b> <b>{new_premium}</b>\n\n"
        f"🪙 <b>Kitobcha:</b>\n"
        f"  Qabul qilindi: <b>+{earned:,}</b>\n"
        f"  Ishlatildi: <b>-{spent:,}</b>\n\n"
        f"🏪 <b>Do'kon xaridlari:</b> <b>{purchases}</b>\n\n"
        f"🧠 <b>Viktorina javoblari:</b> <b>{quiz_answers}</b>"
    )


# ────────────────────────────────────────────────────────────────────────
# Kitob Zanjiri — live twice-a-week "book chain" game on the website.
# ────────────────────────────────────────────────────────────────────────
@shared_task
def start_chain_game():
    """Create a fresh live Kitob Zanjiri and announce it to the reading groups
    with a button that opens the game Mini App (via /start zanjir)."""
    from tgbot.services.chain_game import (
        create_scheduled_game, finalize_due_games, DEFAULT_DURATION_MIN, LEAD_SECONDS,
    )

    # Close out any previous game that never got finalized, then open a new one
    # with a short lobby so players who just saw this post can get ready.
    finalize_due_games()
    game = create_scheduled_game()

    username = _get_bot_username()
    rows = []
    if username:
        rows.append([{"text": "🎮 O'yinga kirish", "url": f"https://t.me/{username}?start=zanjir"}])
    keyboard = json.dumps({"inline_keyboard": rows}) if rows else None

    text = (
        "🔗 <b>KITOB ZANJIRI!</b>\n\n"
        f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring va "
        "tayyor turing!\n"
        f"⏱ O'yin {DEFAULT_DURATION_MIN} daqiqa davom etadi.\n\n"
        "📖 Kitob nomidan tushib qolgan <b>1 yoki 2 ta harfni</b> birinchi bo'lib "
        "topgan ochko oladi — va zanjir darhol yangi kitobga o'tadi!\n\n"
        "💰 <b>Kirish: 25 Kitobcha.</b>\n"
        "🏆 Ochko olganlar mukofot oladi (1/2/3-o'rin: <b>300/200/100 🪙</b>); "
        "bekorchi kirish haqini yo'qotadi.\n"
        "👇 Hoziroq kiring:"
    )
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for group_id, thread_id in _game_targets():
        data = {"chat_id": group_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": "true"}
        if keyboard:
            data["reply_markup"] = keyboard
        if thread_id:
            data["message_thread_id"] = thread_id
        try:
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            print(f"start_chain_game group {group_id}: {e}")
    print(f"start_chain_game: game #{game.id} live until {game.ends_at}")
    return game


@shared_task
def chain_game_tick():
    """Finish + reward any Kitob Zanjiri whose time is up; announce results to
    groups and DM the winners who earned Kitobcha. Runs every minute (cheap;
    does nothing when there's no expired live game)."""
    from tgbot.services.chain_game import finalize_due_games

    results = finalize_due_games()
    if not results:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    medals = ["🥇", "🥈", "🥉"]
    for game, summary in results:
        winners = summary.get("winners", [])
        lines = [
            "🏁 <b>Kitob Zanjiri yakunlandi!</b>\n",
            f"📖 Topilgan kitoblar: <b>{summary.get('links', 0)}</b> · "
            f"Qatnashchilar: <b>{summary.get('players', 0)}</b>\n",
        ]
        scorers = [w for w in winners if (w.get("points") or 0) > 0]
        if scorers:
            for i, w in enumerate(scorers[:5]):
                m = medals[i] if i < 3 else f"{i + 1}."
                rew = f" (+{w['reward']} 🪙)" if w.get("reward") else ""
                lines.append(f"{m} {escape(w['name'])} — <b>{w['points']}</b> ochko{rew}")
            lines.append("\n💰 Kirish 25 🪙 · faqat ochko olganlar mukofot oldi. O'ynaganingiz uchun rahmat! 📚")
        else:
            lines.append("Bu safar hech kim ochko olmadi 😔")
        text = "\n".join(lines)
        for group_id, thread_id in _game_targets():
            try:
                data = {
                    "chat_id": group_id, "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                }
                if thread_id:
                    data["message_thread_id"] = thread_id
                requests.post(url, data=data, timeout=10)
            except Exception as e:
                print(f"chain_game_tick group {group_id}: {e}")

        for w in winners:
            if not w.get("reward"):
                continue
            try:
                requests.post(url, data={
                    "chat_id": w["telegram_id"],
                    "text": (
                        f"🎉 Kitob Zanjirida <b>{w['rank']}-o'rin</b>!\n"
                        f"🪙 <b>+{w['reward']} Kitobcha</b> qo'shildi.\n"
                        f"Ballaringiz: {w['points']} · Topilgan kitoblar: {w['links']}"
                    ),
                    "parse_mode": "HTML",
                }, timeout=8)
            except Exception:
                pass
        print(f"chain_game_tick: finalized game #{game.id}, {len(winners)} scorers")
        _advance_game_sequence("chain", game.id)


# ────────────────────────────────────────────────────────────────────────
# Ko'pchilik nima dedi? (Feud) + Bilim Qal'asi (Castle) — start & finalize.
# ────────────────────────────────────────────────────────────────────────
def _announce_game(text, start_param):
    username = _get_bot_username()
    rows = []
    if username:
        rows.append([{"text": "🎮 O'yinga kirish", "url": f"https://t.me/{username}?start={start_param}"}])
    keyboard = json.dumps({"inline_keyboard": rows}) if rows else None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for group_id, thread_id in _game_targets():
        data = {"chat_id": group_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": "true"}
        if keyboard:
            data["reply_markup"] = keyboard
        if thread_id:
            data["message_thread_id"] = thread_id
        try:
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            print(f"_announce_game {group_id}: {e}")


@shared_task
def start_feud_game():
    from tgbot.services.feud_game import create_scheduled_feud, finalize_due_games, LEAD_SECONDS
    finalize_due_games()
    game = create_scheduled_feud()
    text = (
        "🗣 <b>KO'PCHILIK NIMA DEDI?</b>\n\n"
        f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
        "Har savolga javob bering — <b>ko'pchilik bilan mos</b> javob ko'p ochko beradi!\n\n"
        "💰 <b>Kirish: 25 Kitobcha.</b>\n"
        "🏆 G'oliblar ko'p Kitobcha, qatnashgan hamma <b>+30 🪙</b>.\n👇 Kiring:"
    )
    _announce_game(text, "kopchilik")
    print(f"start_feud_game: game #{game.id}")
    return game


@shared_task
def start_castle_game():
    from tgbot.services.castle_game import create_scheduled_castle, finalize_due_games, LEAD_SECONDS
    finalize_due_games()
    game = create_scheduled_castle()
    text = (
        "🏰 <b>BILIM QAL'ASI</b> — jamoaviy jang!\n\n"
        f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
        "Birgalikda savollarga javob bering, har to'g'ri javob <b>bossni uradi</b>. "
        "Uni yenging — hammamiz Kitobcha yutamiz!\n\n"
        "💰 <b>Kirish: 25 Kitobcha.</b>\n👇 Kiring:"
    )
    _announce_game(text, "qala")
    print(f"start_castle_game: game #{game.id}")
    return game


@shared_task
def start_emoji_game():
    from tgbot.services.emoji_game import create_scheduled_emoji, finalize_due_games, LEAD_SECONDS
    finalize_due_games()
    game = create_scheduled_emoji()
    text = (
        "🎬 <b>EMOJI KITOB</b> — emojidan kitobni top!\n\n"
        f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
        "Emojilarga qarab, 4 variantdan to'g'ri kitobni eng tez tanlang. "
        "To'g'ri javob — ochko!\n\n"
        "💰 <b>Kirish: 25 Kitobcha.</b>\n"
        "🏆 G'oliblar ko'p Kitobcha oladi.\n👇 Kiring:"
    )
    _announce_game(text, "emoji")
    print(f"start_emoji_game: game #{game.id}")
    return game


@shared_task
def start_wisdom_game():
    from tgbot.services.wisdom_game import create_scheduled_wisdom, finalize_due_games, LEAD_SECONDS, ENTRY_FEE
    finalize_due_games()
    game = create_scheduled_wisdom()
    text = (
        "☪️ <b>HIKMAT XAZINASI</b> — kim aytgan?\n\n"
        f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
        "Hikmatli gap ko'rsatiladi — qaysi olim yoki ulamo aytganini toping. "
        "Ketma-ket to'g'ri javoblar ochkoni oshiradi (x1→x2→x3)!\n\n"
        f"💰 <b>Kirish: {ENTRY_FEE} Kitobcha.</b>\n"
        "🏆 G'oliblar ko'p Kitobcha oladi.\n👇 Kiring:"
    )
    _announce_game(text, "hikmat")
    print(f"start_wisdom_game: game #{game.id}")
    return game


@shared_task
def start_detective_game():
    from tgbot.services.detective_game import create_scheduled_detective, finalize_due_games, LEAD_SECONDS, ENTRY_FEE
    finalize_due_games()
    game = create_scheduled_detective()
    text = (
        "📖 <b>KITOB DETEKTIVI</b> — maxfiy kitobni top!\n\n"
        f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
        "Har raundda maxfiy kitob asta-sekin ipuchlari orqali ochiladi. "
        "Birinchi to'g'ri topgan g'olib — qancha erta, shuncha ko'p ochko!\n\n"
        f"💰 <b>Kirish: {ENTRY_FEE} Kitobcha.</b>\n"
        "🏆 G'oliblar ko'p Kitobcha oladi.\n👇 Kiring:"
    )
    _announce_game(text, "detektiv")
    print(f"start_detective_game: game #{game.id}")
    return game


@shared_task
def start_survival_game():
    from tgbot.services.survival_game import create_scheduled_survival, finalize_due_games, LEAD_SECONDS, ENTRY_FEE
    finalize_due_games()
    game = create_scheduled_survival()
    text = (
        "💀 <b>OMON QOLISH</b> — elimination o'yin!\n\n"
        f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
        "Har savolga javob bering — noto'g'ri yoki javobsiz qolsangiz jon yo'qotasiz "
        "(3 jon). Oxirigacha omon qolganlar jackpotni bo'lishadi!\n\n"
        f"💰 <b>Kirish: {ENTRY_FEE} Kitobcha.</b>\n👇 Kiring:"
    )
    _announce_game(text, "omon-qolish")
    print(f"start_survival_game: game #{game.id}")
    return game


def _start_quiz_flavor(flavor):
    from tgbot.services.quiz_game import create_scheduled_quiz, finalize_due_games, LEAD_SECONDS, ENTRY_FEES
    finalize_due_games(flavor)
    game = create_scheduled_quiz(flavor)
    texts = {
        "twofacts": (
            "🎭 <b>IKKI HAQIQAT, BIR YOLG'ON</b>\n\n"
            f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
            "3 ta gapdan qaysi biri yolg'on ekanini tez toping!\n\n"
            f"💰 <b>Kirish: {ENTRY_FEES['twofacts']} Kitobcha.</b>\n👇 Kiring:"
        ),
        "impostor": (
            "🃏 <b>KIM YOLG'ONCHI?</b>\n\n"
            f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
            "3 haqiqiy va 1 soxta juftlik orasidan soxtasini toping!\n\n"
            f"💰 <b>Kirish: {ENTRY_FEES['impostor']} Kitobcha.</b>\n👇 Kiring:"
        ),
        "connection": (
            "🧩 <b>YASHIRIN BOG'LANISH</b>\n\n"
            f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
            "4 ta narsani bog'lovchi yashirin mavzuni toping!\n\n"
            f"💰 <b>Kirish: {ENTRY_FEES['connection']} Kitobcha.</b>\n👇 Kiring:"
        ),
        "teams": (
            "👥 <b>JAMOA JANGI</b> — ikki jamoa bo'lib jang!\n\n"
            f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
            "Kirganlaringiz avtomatik ikki jamoaga bo'linadi. Jamoangiz ko'proq "
            "to'g'ri javob bersa — jamoa jackpotni bo'lishadi!\n\n"
            f"💰 <b>Kirish: {ENTRY_FEES['teams']} Kitobcha.</b>\n👇 Kiring:"
        ),
        "timeline": (
            "🕰️ <b>VAQT MASHINASI</b>\n\n"
            f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
            "Kitob yoki mutafakkir qaysi asrga tegishli ekanini toping!\n\n"
            f"💰 <b>Kirish: {ENTRY_FEES['timeline']} Kitobcha.</b>\n👇 Kiring:"
        ),
        "matchbook": (
            "🎯 <b>MUALLIF-ASAR MOSLASHTIRISH</b>\n\n"
            f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
            "Muallifga tegishli haqiqiy asarni 4 variantdan tez toping!\n\n"
            f"💰 <b>Kirish: {ENTRY_FEES['matchbook']} Kitobcha.</b>\n👇 Kiring:"
        ),
        "reverse": (
            "🔄 <b>TESKARI VIKTORINA</b>\n\n"
            f"⏳ <b>{LEAD_SECONDS} soniyadan keyin</b> boshlanadi — hozir kiring!\n"
            "Javob avval ko'rsatiladi — qaysi savolga mos kelishini toping!\n\n"
            f"💰 <b>Kirish: {ENTRY_FEES['reverse']} Kitobcha.</b>\n👇 Kiring:"
        ),
    }
    deep_link_params = {
        "twofacts": "ikki-haqiqat", "impostor": "kim-yolgonchi",
        "connection": "bog-lanish", "teams": "jamoa-jangi",
        "timeline": "vaqt-mashinasi", "matchbook": "muallif-asar",
        "reverse": "teskari-viktorina",
    }
    _announce_game(texts[flavor], deep_link_params[flavor])
    print(f"start_quiz_{flavor}: game #{game.id}")
    return game


@shared_task
def start_quiz_twofacts_game():
    return _start_quiz_flavor("twofacts")


@shared_task
def start_quiz_impostor_game():
    return _start_quiz_flavor("impostor")


@shared_task
def start_quiz_connection_game():
    return _start_quiz_flavor("connection")


@shared_task
def start_quiz_teams_game():
    return _start_quiz_flavor("teams")


@shared_task
def start_quiz_timeline_game():
    return _start_quiz_flavor("timeline")


@shared_task
def start_quiz_matchbook_game():
    return _start_quiz_flavor("matchbook")


@shared_task
def start_quiz_reverse_game():
    return _start_quiz_flavor("reverse")


# Maps a game-type slug to the task that starts it (each returns the created
# game instance). Shared by start_game_sequence and _advance_game_sequence to
# run the daily 10:00/22:00 slot: 3 different types, back to back, no repeats.
_GAME_STARTERS = {
    "chain": start_chain_game,
    "feud": start_feud_game,
    "castle": start_castle_game,
    "emoji": start_emoji_game,
    "wisdom": start_wisdom_game,
    "detective": start_detective_game,
    "survival": start_survival_game,
    "twofacts": start_quiz_twofacts_game,
    "impostor": start_quiz_impostor_game,
    "connection": start_quiz_connection_game,
    "teams": start_quiz_teams_game,
    "timeline": start_quiz_timeline_game,
    "matchbook": start_quiz_matchbook_game,
    "reverse": start_quiz_reverse_game,
}


# The 10 games built today (2026-07-22) — used to source tonight's special
# 5-game bonus lineup so it showcases only the new content.
NEW_GAME_TYPES = [
    "wisdom", "detective", "survival", "twofacts", "impostor", "connection", "teams",
    "timeline", "matchbook", "reverse",
]


@shared_task
def start_game_sequence(slot, count=3, pool=None):
    """Kick off today's `slot` ('morning' 10:00 or 'evening' 22:00) sequence:
    pick `count` of the live games at random from `pool` (no repeats) and
    start the first one. The rest are chained on as each prior game finishes
    — see `_advance_game_sequence`, called from chain_game_tick/games_finalize_tick.

    `count` defaults to 3 and `pool` defaults to every live game type (the
    regular daily rotation); a bigger one-off event (see
    start_special_evening_event) can request more from a narrower pool."""
    from tgbot.models import GameSequence

    pool = pool or GameSequence.GAME_TYPES
    today = timezone.localdate()
    count = min(count, len(pool))
    seq, created = GameSequence.objects.get_or_create(
        slot=slot, date=today,
        defaults={"game_types": random.sample(pool, count)},
    )
    if not created:
        print(f"start_game_sequence: {slot}/{today} already started, skipping")
        return

    first_type = seq.game_types[0]
    game = _GAME_STARTERS[first_type]()
    seq.current_game_type = first_type
    seq.current_game_id = game.id
    seq.save(update_fields=["current_game_type", "current_game_id", "updated_at"])
    print(f"start_game_sequence: {slot} sequence {seq.game_types}, starting {first_type} #{game.id}")


@shared_task
def start_special_evening_event(count=5, bonus_count=2):
    """One-off bonus night: announce it to the groups, then immediately kick
    off the evening GameSequence with `count` games (all drawn from
    NEW_GAME_TYPES, today's new content) instead of the usual 3 from the full
    pool. The first `count - bonus_count` are the "standard" slots, the last
    `bonus_count` are announced as bonus.

    Scheduled via apply_async(eta=...) a few seconds before 22:00 so it wins
    the GameSequence.get_or_create race against the regular beat-triggered
    start_game_sequence('evening') call at 22:00:00 sharp (whichever creates
    the row first "wins"; the other becomes a harmless no-op)."""
    text = (
        f"🎉 <b>BUGUN KECHQURUN MAXSUS O'YIN TUNI!</b>\n\n"
        f"Bugun 22:00 da odatdagi 3 ta o'rniga <b>{count} ta YANGI o'yin</b> ketma-ket "
        f"o'tkaziladi — oxirgi <b>{bonus_count} tasi BONUS o'yin</b>! 🎁\n\n"
        "Barchasida qatnashib, ko'proq Kitobcha va sovg'alar yutib oling! 👇"
    )
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for group_id, thread_id in _game_targets():
        try:
            data = {"chat_id": group_id, "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": "true"}
            if thread_id:
                data["message_thread_id"] = thread_id
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            print(f"start_special_evening_event announce {group_id}: {e}")
    start_game_sequence("evening", count=count, pool=NEW_GAME_TYPES)


def _advance_game_sequence(game_type, game_id):
    """If `game_id` (of `game_type`) was the current step of a live daily
    sequence, start the next game type in line — or mark the sequence
    completed once all 3 have run."""
    from tgbot.models import GameSequence

    seq = GameSequence.objects.filter(
        completed=False, current_game_type=game_type, current_game_id=game_id,
    ).first()
    if not seq:
        return

    next_index = seq.current_index + 1
    if next_index >= len(seq.game_types):
        seq.completed = True
        seq.current_index = next_index
        seq.save(update_fields=["completed", "current_index", "updated_at"])
        print(f"_advance_game_sequence: {seq.slot}/{seq.date} sequence complete")
        if seq.slot == GameSequence.SLOT_EVENING:
            # Celebratory top-5 announcement right after tonight's games wrap
            # up, instead of only waiting for the fixed 23:00 fallback slot.
            announce_top_game_players()
        return

    next_type = seq.game_types[next_index]
    game = _GAME_STARTERS[next_type]()
    seq.current_index = next_index
    seq.current_game_type = next_type
    seq.current_game_id = game.id
    seq.save(update_fields=[
        "current_index", "current_game_type", "current_game_id", "updated_at",
    ])
    print(f"_advance_game_sequence: {seq.slot}/{seq.date} advancing to {next_type} #{game.id}")


@shared_task
def games_finalize_tick():
    """Finish + reward any Ko'pchilik / Qal'a game whose time is up; announce
    results to groups and DM winners. Runs every minute (cheap no-op)."""
    from tgbot.services import feud_game, castle_game
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    medals = ["🥇", "🥈", "🥉"]

    for game, summary in feud_game.finalize_due_games():
        winners = summary.get("winners", [])
        lines = ["🗣 <b>Ko'pchilik nima dedi? — yakun!</b>\n"]
        if winners:
            for i, w in enumerate(winners[:5]):
                m = medals[i] if i < 3 else f"{i + 1}."
                rew = f" (+{w['reward']} 🪙)" if w.get("reward") else ""
                # Flag Premium's 2x boost so e.g. a Premium 2nd place earning
                # more Kitobcha than a non-Premium 1st doesn't read as a bug.
                badge = " 💎" if w.get("boosted") else ""
                lines.append(f"{m} {escape(w['name'])}{badge} — <b>{w['points']}</b> ochko{rew}")
            lines.append("\n🎁 Qatnashgan hammaga <b>+30 🪙</b>!")
        else:
            lines.append("Bu safar hech kim qatnashmadi 😔")
        text = "\n".join(lines)
        for gid, tid in _game_targets():
            try:
                data = {"chat_id": gid, "text": text, "parse_mode": "HTML",
                        "disable_web_page_preview": "true"}
                if tid:
                    data["message_thread_id"] = tid
                requests.post(url, data=data, timeout=10)
            except Exception:
                pass
        for w in winners:
            if not w.get("reward"):
                continue
            try:
                requests.post(url, data={"chat_id": w["telegram_id"],
                    "text": f"🗣 Ko'pchilik nima dedi? — <b>{w['rank']}-o'rin</b>!\n"
                            f"🪙 <b>+{w['reward']} Kitobcha</b> · Ball: {w['points']}",
                    "parse_mode": "HTML"}, timeout=8)
            except Exception:
                pass
        _advance_game_sequence("feud", game.id)

    for game, summary in castle_game.finalize_due_games():
        victory = summary.get("victory")
        winners = summary.get("winners", [])
        head = ("🎉 <b>Bilim Qal'asi — G'ALABA!</b>" if victory
                else "🛡 <b>Bilim Qal'asi — boss omon qoldi</b>")
        lines = [head,
                 f"\n⚔️ Qatnashchilar: <b>{summary.get('players', 0)}</b> · "
                 f"Hissa qo'shganlar: <b>{summary.get('contributors', 0)}</b>"]
        for i, w in enumerate(winners[:5]):
            badge = " 💎" if w.get("boosted") else ""
            lines.append(f"{i + 1}. {escape(w['name'])}{badge} — {w['correct']} ✓ (+{w['reward']} 🪙)")
        text = "\n".join(lines)
        for gid, tid in _game_targets():
            try:
                data = {"chat_id": gid, "text": text, "parse_mode": "HTML",
                        "disable_web_page_preview": "true"}
                if tid:
                    data["message_thread_id"] = tid
                requests.post(url, data=data, timeout=10)
            except Exception:
                pass
        for w in winners:
            if not w.get("reward"):
                continue
            try:
                requests.post(url, data={"chat_id": w["telegram_id"],
                    "text": f"🏰 Bilim Qal'asi: <b>+{w['reward']} Kitobcha</b>! "
                            f"To'g'ri javoblar: {w['correct']}",
                    "parse_mode": "HTML"}, timeout=8)
            except Exception:
                pass
        _advance_game_sequence("castle", game.id)

    from tgbot.services import emoji_game
    for game, summary in emoji_game.finalize_due_games():
        winners = summary.get("winners", [])
        lines = ["🎬 <b>Emoji Kitob — yakun!</b>\n"]
        if winners:
            for i, w in enumerate(winners[:5]):
                m = medals[i] if i < 3 else f"{i + 1}."
                rew = f" (+{w['reward']} 🪙)" if w.get("reward") else ""
                badge = " 💎" if w.get("boosted") else ""
                lines.append(f"{m} {escape(w['name'])}{badge} — <b>{w['points']}</b> ochko{rew}")
        else:
            lines.append("Bu safar hech kim ochko olmadi 😔")
        text = "\n".join(lines)
        for gid, tid in _game_targets():
            try:
                data = {"chat_id": gid, "text": text, "parse_mode": "HTML",
                        "disable_web_page_preview": "true"}
                if tid:
                    data["message_thread_id"] = tid
                requests.post(url, data=data, timeout=10)
            except Exception:
                pass
        for w in winners:
            if not w.get("reward"):
                continue
            try:
                requests.post(url, data={"chat_id": w["telegram_id"],
                    "text": f"🎬 Emoji Kitob — <b>{w['rank']}-o'rin</b>!\n"
                            f"🪙 <b>+{w['reward']} Kitobcha</b> · Ball: {w['points']}",
                    "parse_mode": "HTML"}, timeout=8)
            except Exception:
                pass
        _advance_game_sequence("emoji", game.id)

    _finalize_wisdom()
    _finalize_detective()
    _finalize_survival()
    for flavor in ("twofacts", "impostor", "connection", "teams",
                   "timeline", "matchbook", "reverse"):
        _finalize_quiz_flavor(flavor)


def _broadcast_and_dm(header_lines, winners, dm_text_fn):
    """Post `header_lines` to every group, then DM each rewarded winner via
    `dm_text_fn(winner) -> str`. Shared by the new games' finalize announcements."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    text = "\n".join(header_lines)
    for gid, tid in _game_targets():
        try:
            data = {"chat_id": gid, "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": "true"}
            if tid:
                data["message_thread_id"] = tid
            requests.post(url, data=data, timeout=10)
        except Exception:
            pass
    for w in winners:
        if not w.get("reward"):
            continue
        try:
            requests.post(url, data={"chat_id": w["telegram_id"], "text": dm_text_fn(w),
                                     "parse_mode": "HTML"}, timeout=8)
        except Exception:
            pass


def _finalize_wisdom():
    from tgbot.services import wisdom_game
    medals = ["🥇", "🥈", "🥉"]
    for game, summary in wisdom_game.finalize_due_games():
        winners = summary.get("winners", [])
        lines = ["☪️ <b>Hikmat Xazinasi — yakun!</b>\n"]
        if winners:
            for i, w in enumerate(winners[:5]):
                m = medals[i] if i < 3 else f"{i + 1}."
                rew = f" (+{w['reward']} 🪙)" if w.get("reward") else ""
                streak_note = f" · eng uzun ketma-ket: {w['best_streak']}" if w.get("best_streak") else ""
                lines.append(f"{m} {escape(w['name'])} — <b>{w['points']}</b> ochko{rew}{streak_note}")
        else:
            lines.append("Bu safar hech kim ochko olmadi 😔")
        _broadcast_and_dm(lines, winners, lambda w: (
            f"☪️ Hikmat Xazinasi — <b>{w['rank']}-o'rin</b>!\n"
            f"🪙 <b>+{w['reward']} Kitobcha</b> · Ball: {w['points']}"
        ))
        _advance_game_sequence("wisdom", game.id)


def _finalize_detective():
    from tgbot.services import detective_game
    medals = ["🥇", "🥈", "🥉"]
    for game, summary in detective_game.finalize_due_games():
        winners = summary.get("winners", [])
        lines = [f"📖 <b>Kitob Detektivi — yakun!</b>\n\n🔍 Topilgan kitoblar: <b>{summary.get('solved', 0)}</b>"]
        if winners:
            for i, w in enumerate(winners[:5]):
                m = medals[i] if i < 3 else f"{i + 1}."
                rew = f" (+{w['reward']} 🪙)" if w.get("reward") else ""
                lines.append(f"{m} {escape(w['name'])} — <b>{w['points']}</b> ochko ({w['solved_count']} topgan){rew}")
        else:
            lines.append("Bu safar hech kim topa olmadi 😔")
        _broadcast_and_dm(lines, winners, lambda w: (
            f"📖 Kitob Detektivi — <b>{w['rank']}-o'rin</b>!\n"
            f"🪙 <b>+{w['reward']} Kitobcha</b> · Ball: {w['points']}"
        ))
        _advance_game_sequence("detective", game.id)


def _finalize_survival():
    from tgbot.services import survival_game
    for game, summary in survival_game.finalize_due_games():
        winners = summary.get("winners", [])
        survivors = summary.get("survivors", 0)
        head = (f"💀 <b>Omon qolish — yakun!</b>\n\n🏆 Omon qolganlar: <b>{survivors}</b> / {summary.get('players', 0)}"
                if survivors else "💀 <b>Omon qolish — yakun!</b>\n\n☠️ Hamma chetlatildi — eng ko'p to'g'ri javob berganlar g'olib!")
        lines = [head]
        for w in winners[:5]:
            tag = "✅" if w.get("survived") else "🎖"
            lines.append(f"{tag} {escape(w['name'])} — {w['correct']} to'g'ri (+{w['reward']} 🪙)")
        _broadcast_and_dm(lines, winners, lambda w: (
            f"💀 Omon qolish — {'omon qoldingiz!' if w.get('survived') else 'yaxshi harakat!'}\n"
            f"🪙 <b>+{w['reward']} Kitobcha</b> · To'g'ri javoblar: {w['correct']}"
        ))
        _advance_game_sequence("survival", game.id)


def _finalize_quiz_flavor(flavor):
    from tgbot.services import quiz_game
    medals = ["🥇", "🥈", "🥉"]
    titles = {"twofacts": "Ikki haqiqat, bir yolg'on", "impostor": "Kim yolg'onchi?",
              "connection": "Yashirin bog'lanish", "teams": "Jamoa Jangi",
              "timeline": "Vaqt Mashinasi", "matchbook": "Muallif-Asar Moslashtirish",
              "reverse": "Teskari Viktorina"}
    emojis = {"twofacts": "🎭", "impostor": "🃏", "connection": "🧩", "teams": "👥",
              "timeline": "🕰️", "matchbook": "🎯", "reverse": "🔄"}
    for game, summary in quiz_game.finalize_due_games(flavor):
        winners = summary.get("winners", [])
        emoji_, title = emojis[flavor], titles[flavor]
        if flavor == "teams":
            ap, bp = summary.get("team_a_points", 0), summary.get("team_b_points", 0)
            if summary.get("tie"):
                lines = [f"{emoji_} <b>{title} — durrang!</b>\n\n🔵 Jamoa A: {ap} · 🔴 Jamoa B: {bp}"]
            else:
                wt = "A" if summary.get("winning_team") == "a" else "B"
                lines = [f"{emoji_} <b>{title} — Jamoa {wt} g'olib!</b>\n\n🔵 Jamoa A: {ap} · 🔴 Jamoa B: {bp}"]
            for w in winners[:8]:
                tag = "🔵" if w.get("team") == "a" else "🔴"
                rew = f" (+{w['reward']} 🪙)" if w.get("reward") else ""
                lines.append(f"{tag} {escape(w['name'])} — {w['points']} ochko{rew}")
        else:
            lines = [f"{emoji_} <b>{title} — yakun!</b>\n"]
            if winners:
                for i, w in enumerate(winners[:5]):
                    m = medals[i] if i < 3 else f"{i + 1}."
                    rew = f" (+{w['reward']} 🪙)" if w.get("reward") else ""
                    lines.append(f"{m} {escape(w['name'])} — <b>{w['points']}</b> ochko{rew}")
            else:
                lines.append("Bu safar hech kim ochko olmadi 😔")
        _broadcast_and_dm(lines, winners, lambda w: (
            f"{emoji_} {title} — <b>+{w['reward']} Kitobcha</b>! Ball: {w['points']}"
        ))
        _advance_game_sequence(flavor, game.id)
