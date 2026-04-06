import asyncio
import random
import requests
import environ
import json
from aiogram.types import ReplyKeyboardRemove
from tgbot.bot.keyboards.reply import main_markup

from celery import shared_task

from tgbot.models import DailyMessage, ConfirmationReport, TelegramProfile, Group
from tgbot.models import Contest, ContestParticipant, Question, ContestSubmission

from django.utils import timezone
from django.db.models import Sum, Q, Window, F, Count
from django.db.models.functions.window import Rank
from asgiref.sync import sync_to_async
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


# --- CONTEST TASKS ---

@shared_task
def notify_contest_participants(contest_id):
    """
    Notifies eligible users for a specific upcoming contest.
    This task is scheduled via ETA from the Contest model.
    """
    try:
        contest = Contest.objects.get(id=contest_id)
    except Contest.DoesNotExist:
        print(f"Contest {contest_id} not found for notification.")
        return

    # Validation: Ensure contest is still pending/active
    if contest.is_finished:
        print(
            f"Contest {contest.name} is already finished. Skipping notification.")
        return

    if contest.is_notified:
        print(f"Contest {contest.name} already notified. Skipping.")
        return

    print(f"Notifying for contest: {contest.name}")
    contest.is_notified = True
    contest.save(update_fields=['is_notified'])

    # Filter users with referrals >= req_referrals
    eligible_users = TelegramProfile.objects.annotate(
        referral_count=Count('referrals')
    ).filter(
        referral_count__gte=contest.req_referrals,
        is_blocked=False,
        is_registered=True
    )

    print(f"Found {eligible_users.count()} eligible users for {contest.name}")

    # Determine message based on time remaining roughly
    # Since we schedule it exactly when we want, we can just say "Starting soon"
    # or calculate difference if needed. For now, assuming standard message.
    msg = f"🔔 <b>Diqqat!</b>\n\n'{contest.name}' konkursi TEZ ORADA boshlanadi! Tayyor turing!"

    # Fan-out notifications
    remove_kb = ReplyKeyboardRemove().to_python()
    for user in eligible_users:
        send_notification_with_celery.delay(
            user.telegram_id, msg, reply_markup=remove_kb)


@shared_task(name='tgbot.tasks.notify_upcoming_contests')
def notify_upcoming_contests_shim(*args, **kwargs):
    """
    Shim for legacy task name 'notify_upcoming_contests' that might still be in the queue.
    This task does nothing but acknowledge the message to prevent worker errors.
    """
    print("Legacy task `tgbot.tasks.notify_upcoming_contests` received and ignored.")


@shared_task
def broadcast_description_task(contest_id):
    """
    Broadcasts the contest description to all participants.
    """
    try:
        contest = Contest.objects.get(id=contest_id)
        participants = ContestParticipant.objects.filter(
            contest=contest).select_related('user')

        msg = f"ℹ️ <b>Konkurs haqida:</b>\n\n{contest.description}"

        for participant in participants:
            send_notification_with_celery.delay(
                participant.user.telegram_id, msg)
    except Contest.DoesNotExist:
        pass


@shared_task
def broadcast_message_task(contest_id, message_text):
    """
    Generic task to broadcast a text message to all contest participants.
    Useful for countdowns (3..2..1) and announcements.
    """
    try:
        # We fetch participants even for countdowns to ensure we target the right audience.
        # Ideally, for countdowns before contest starts, we might need a broader audience,
        # but logically countdown happens AFTER registration closes or just before start.
        # Assuming participants are created at start_contest_task.
        participants = ContestParticipant.objects.filter(
            contest_id=contest_id).select_related('user')

        for participant in participants:
            send_notification_with_celery.delay(
                participant.user.telegram_id, message_text)

    except Exception as e:
        print(f"Error in broadcast_message_task for contest {contest_id}: {e}")


@shared_task
def broadcast_question_task(contest_id, question_id):
    """
    Fan-out task: Fetches all participants and schedules a sending task for EACH user.
    This runs at the specific scheduled time for the question.
    """
    try:
        # Verify contest is still active/valid if needed
        contest = Contest.objects.get(id=contest_id)
        if contest.is_finished:
            return

        participants = ContestParticipant.objects.filter(contest=contest)

        # Optimization: Only apply heavy COUNT/JOIN if there is a referral requirement
        if contest.req_referrals > 0:
            participants = participants.annotate(
                referral_count=Count('user__referrals')
            ).filter(
                referral_count__gte=contest.req_referrals
            )

        participants = participants.select_related(
            'user').only('user__id', 'user__telegram_id')

        # OPTIMIZATION: Fetch question data ONCE
        question = Question.objects.get(id=question_id)
        question_data = {
            "id": question.id,
            "question": question.question,
            "options": question.options,
            "correct_option": question.correct_option,
            "explanation": question.explanation
        }

        for participant in participants:
            # Fire and forget - the worker queue will handle the load
            # Passing telegram_id and question_data explicitly to avoid DB lookups in the worker
            send_question_to_user_optimized.delay(
                participant.user.id, participant.user.telegram_id, contest.id, question_data)

    except Exception as e:
        print(
            f"Error in broadcast_question_task for contest {contest_id}, question {question_id}: {e}")


@shared_task
def start_contest_by_id(contest_id):
    """
    Starts a specific contest by its ID.
    Scheduled via celery beat or eta.
    """
    asyncio.run(_start_single_contest(contest_id))


@shared_task
def start_contest_task():
    """
    Legacy task - removed from schedule but kept for backward compatibility if needed.
    """
    pass


async def _start_single_contest(contest_id):
    contest = await sync_to_async(Contest.objects.get)(id=contest_id)

    # 1. Fetch Questions
    questions = await sync_to_async(list)(Question.objects.filter(contest=contest).order_by('order'))
    if not questions:
        print(f"Contest {contest.name} has no questions. Not starting.")
        return

    # CLEANUP: Remove data from previous runs (PollState, Participants, Submissions)
    # This allows re-starting a contest and re-testing.
    from tgbot.models import PollState
    await sync_to_async(PollState.objects.filter(question__contest=contest).delete)()
    await sync_to_async(ContestParticipant.objects.filter(contest=contest).delete)()

    # 2. Mark Started
    contest.is_started = True
    await sync_to_async(contest.save)(update_fields=['is_started'])

    # 3. Create Participants (Snapshot of eligible users)
    eligible_users_qs = TelegramProfile.objects.annotate(
        referral_count=Count('referrals')
    ).filter(referral_count__gte=contest.req_referrals, is_blocked=False, is_registered=True)

    eligible_users = await sync_to_async(list)(eligible_users_qs)

    if not eligible_users:
        print(f"Contest {contest.name} has no eligible users.")
        return

    # Bulk create participants
    # We use sync logic wrapped or just run it via sync_to_async
    existing_uids = await sync_to_async(lambda: list(ContestParticipant.objects.filter(contest=contest).values_list('user_id', flat=True)))()

    new_participants = []
    for user in eligible_users:
        if user.id not in existing_uids:
            new_participants.append(
                ContestParticipant(contest=contest, user=user))

    if new_participants:
        await sync_to_async(ContestParticipant.objects.bulk_create)(new_participants, ignore_conflicts=True)

    # 4. Global Scheduler Logic
    # We schedule everything relative to NOW.

    # Countdown: 3, 2, 1, GO!
    broadcast_message_task.apply_async((contest.id, "3️⃣"), countdown=0)
    broadcast_message_task.apply_async((contest.id, "2️⃣"), countdown=1)
    broadcast_message_task.apply_async((contest.id, "1️⃣"), countdown=2)
    broadcast_message_task.apply_async(
        (contest.id, "🚀 Boshladik!"), countdown=3)

    initial_delay = 5
    question_interval = 40

    # Schedule ALL questions with fixed interval
    for index, question in enumerate(questions):
        delay = initial_delay + (index * question_interval)
        broadcast_question_task.apply_async(
            (contest.id, question.id), countdown=delay)

    # Schedule Finish Task as a fallback/safety measure.
    # We assume max possible time = questions * 45s (40s + 5s buffer) + initial delay
    max_duration = initial_delay + (len(questions) * question_interval) + 60
    finish_contest_task.apply_async((contest.id,), countdown=max_duration)


@shared_task
def send_question_to_user_task(user_db_id, contest_id, question_id):
    """
    Legacy task kept for backward compatibility or direct calls.
    Ideally, use send_question_to_user_optimized.
    """
    asyncio.run(_send_question_async(user_db_id, contest_id, question_id))


@shared_task
def send_question_to_user_optimized(user_db_id, user_telegram_id, contest_id, question_data):
    """
    Optimized version that takes prepared data to minimize DB lookups.
    """
    asyncio.run(_send_question_optimized_async(
        user_db_id, user_telegram_id, contest_id, question_data))


async def _send_question_optimized_async(user_db_id, user_telegram_id, contest_id, question_data):
    try:
        # print(f"DEBUG: Processing question {question_data['id']} for user {user_db_id}")

        # Idempotency check: Don't send if already sent
        # We still need to check this, unfortunately, or trust the scheduler.
        # For 1000 users, checking existence is fast (index scan).
        from tgbot.models import PollState

        # Optimization: We could cache this check too if needed, but DB is reliable source of truth.
        if await sync_to_async(PollState.objects.filter(user_id=user_db_id, question_id=question_data['id']).exists)():
            return

        # No need to fetch User object or Question object! We have IDs and Data.

        # Verify participant still exists/active?
        # For high performance, we might skip this if we trust the broadcast list.
        # But if we must:
        # participant = await sync_to_async(ContestParticipant.objects.get)(contest_id=contest_id, user_id=user_db_id)

        # We'll skip fetching Participant for the 'message sending' part to speed it up.
        # We can update `last_question_sent_at` in background or bulk later if analytics need it.
        # For strict correctness, let's just do a direct update which is faster than get+save.
        await sync_to_async(ContestParticipant.objects.filter(contest_id=contest_id, user_id=user_db_id).update)(last_question_sent_at=timezone.now())

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPoll"
        import json
        data = {
            "chat_id": user_telegram_id,
            "question": question_data['question'],
            "options": json.dumps(question_data['options']),
            "type": "quiz",
            "correct_option_id": question_data['correct_option'],
            "is_anonymous": False,
            "explanation": question_data['explanation'],
            "open_period": 40,  # Native countdown
            "parse_mode": "HTML"
        }

        response = requests.post(url, data=data)
        res_data = response.json()

        if res_data.get("ok"):
            poll_id = res_data["result"]["poll"]["id"]

            # We need User instance for ForeignKey.
            # Django allows setting ID directly usually: poll.user_id = user_db_id
            # But standard create() kwargs expects instance for FK?
            # Actually, `user_id` argument works for `create` if the field is `user`.

            await sync_to_async(PollState.objects.create)(
                poll_id=poll_id,
                user_id=user_db_id,  # Optimization: set FK by ID directly
                # Optimization: set FK by ID directly
                question_id=question_data['id']
            )

            # Schedule timeout check
            check_question_timeout_task.apply_async(
                (user_db_id, contest_id, question_data['id']), countdown=41
            )
        else:
            print(f"Failed to send poll optimized: {res_data}")

    except Exception as e:
        print(
            f"Error sending question optimized {question_data.get('id')} to user {user_db_id}: {e}")


@shared_task
def check_question_timeout_task(user_db_id, contest_id, question_id, user_telegram_id=None):
    """
    Optimized timeout checker.
    """
    asyncio.run(_check_question_timeout_async(
        user_db_id, contest_id, question_id, user_telegram_id))


async def _send_question_async(user_db_id, contest_id, question_id):
    try:
        print(
            f"DEBUG: Processing question {question_id} for user {user_db_id} in contest {contest_id}")
        # Idempotency check: Don't send if already sent
        from tgbot.models import PollState
        if await sync_to_async(PollState.objects.filter(user_id=user_db_id, question_id=question_id).exists)():
            print(
                f"DEBUG: PollState exists for user {user_db_id}, question {question_id}. Skipping.")
            return

        user = await sync_to_async(TelegramProfile.objects.get)(id=user_db_id)
        question = await sync_to_async(Question.objects.get)(id=question_id)

        try:
            participant = await sync_to_async(ContestParticipant.objects.get)(contest_id=contest_id, user_id=user_db_id)
        except ContestParticipant.DoesNotExist:
            print(
                f"DEBUG: ContestParticipant not found for user {user_db_id}, contest {contest_id}")
            return

        # Update last sent time for precision timing calculation later if needed
        participant.last_question_sent_at = timezone.now()
        await sync_to_async(participant.save)(update_fields=['last_question_sent_at'])

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPoll"
        import json
        data = {
            "chat_id": user.telegram_id,
            "question": question.question,
            "options": json.dumps(question.options),
            "type": "quiz",
            "correct_option_id": question.correct_option,
            "is_anonymous": False,
            "explanation": question.explanation,
            "open_period": 40,  # Native countdown
            "parse_mode": "HTML"
        }
        response = requests.post(url, data=data)
        res_data = response.json()

        if res_data.get("ok"):
            poll_id = res_data["result"]["poll"]["id"]
            from tgbot.models import PollState
            await sync_to_async(PollState.objects.create)(
                poll_id=poll_id,
                user=user,
                question=question
            )

            # Schedule timeout check in 41 seconds (40s + 1s buffer)
            check_question_timeout_task.apply_async(
                (user_db_id, contest_id, question_id), countdown=41
            )
        else:
            print(f"Failed to send poll: {res_data}")

    except Exception as e:
        print(
            f"Error sending question {question_id} to user {user_db_id}: {e}")


async def _check_question_timeout_async(user_db_id, contest_id, question_id, user_telegram_id=None):
    try:
        # 1. Check if user already answered
        from tgbot.models import ContestSubmission
        # Optimized existence check
        has_answered = await sync_to_async(ContestSubmission.objects.filter(
            participant__user_id=user_db_id,
            participant__contest_id=contest_id,
            question_id=question_id
        ).exists)()

        if has_answered:
            # User answered in time, nothing to do.
            return

        # 2. Timeout!
        print(f"User {user_db_id} timed out on question {question_id}")

        # Proceed to next question logic
        question = await sync_to_async(Question.objects.get)(id=question_id)

        # Determine next question
        next_question = await sync_to_async(
            Question.objects.filter(
                contest_id=contest_id, order__gt=question.order).order_by('order').first
        )()

        if next_question:
            # Global scheduler handles next question sending.
            pass
        else:
            # Finish for user
            try:
                participant = await sync_to_async(ContestParticipant.objects.get)(contest_id=contest_id, user_id=user_db_id)
                participant.is_finished = True
                await sync_to_async(participant.save)(update_fields=['is_finished'])

                # Send individual result
                score = participant.total_score
                time_s = participant.total_time
                msg = (f"🏁 <b>Konkurs yakunlandi!</b>\n\n"
                       f"👤 Ism: {participant.user.full_name}\n"
                       f"✅ To'g'ri javoblar: {score} ta\n"
                       f"⏱ Sarflagan vaqt: {time_s:.1f} soniya")

                # Check if ALL participants finished
                unfinished_count = await sync_to_async(ContestParticipant.objects.filter(
                    contest_id=contest_id, is_finished=False).count)()

                if unfinished_count == 0:
                    finish_contest_task.delay(contest_id)

                # Restore Request Main Menu
                menu_kb = main_markup(
                    language=participant.user.language or "uz").to_python()

                send_notification.delay(
                    participant.user.telegram_id, msg, reply_markup=menu_kb)

            except Exception as e:
                print(
                    f"Error finishing contest for user {user_db_id} on timeout: {e}")

    except Exception as e:
        print(f"Error in timeout check for user {user_db_id}: {e}")


@shared_task
def finish_contest_task(contest_id):
    asyncio.run(_finish_contest(contest_id))


async def _finish_contest(contest_id):
    contest = await sync_to_async(Contest.objects.get)(id=contest_id)
    if contest.is_finished:
        return

    contest.is_finished = True
    await sync_to_async(contest.save)(update_fields=['is_finished'])

    # Broadcast results
    broadcast_contest_results.delay(contest_id)
    send_contest_report_to_admins.delay(contest_id)


@shared_task
def broadcast_contest_results(contest_id):
    # This task is now simpler, as we don't send global rankings to everyone.
    # Maybe just a "Thank you" message if desired, or nothing as implemented below.
    # Users get their individual results when they finish.
    pass


@shared_task
def send_contest_report_to_admins(contest_id):
    asyncio.run(_send_contest_report_to_admins_async(contest_id))


async def _send_contest_report_to_admins_async(contest_id):
    from tgbot.bot.consts import ADMIN_GROUP_ID, TECHNICAL_SUPPORT_THREAD_ID

    contest = await sync_to_async(Contest.objects.get)(id=contest_id)

    # 1. Fetch Data
    participants_qs = ContestParticipant.objects.filter(contest=contest).select_related('user').annotate(
        rank=Window(
            expression=Rank(),
            order_by=[F('total_score').desc(), F('total_time').asc()]
        )
    ).order_by('rank')

    participants = await sync_to_async(list)(participants_qs)

    if not participants:
        return

    # 2. Build Message
    header_title = f"🏁 <b>{contest.name}</b> yakunlandi. Natijalar ro'yxati:\n\n"

    # Table Header
    # Columns: Rank(3) | Name(20) | Score(5) | Time(7)
    table_header = "N   | Ism Familiya         | T.JAV | VAQT\n"
    table_header += "----------------------------------------------\n"

    chunk_size = 3500  # Safe limit for HTML
    message_parts = []

    current_body = ""

    for p in participants:
        user_name = p.user.full_name or str(p.user.telegram_id)
        if not user_name or user_name == 'None':
            user_name = str(p.user.telegram_id)

        # Truncate name to 20 chars
        if len(user_name) > 19:
            user_name = user_name[:18] + ".."

        rank = str(p.rank) + "."
        score = str(p.total_score)
        time_s = f"{p.total_time:.1f}s"

        # Format Line: Rank<4 | Name<20 | Score>5 | Time>7
        line = f"{rank:<4}| {user_name:<20} | {score:^5} | {time_s:>7}\n"

        if len(header_title) + len(table_header) + len(current_body) + len(line) + 20 > chunk_size:
            # Check if this is the first part (needs header_title)
            if not message_parts:
                full_msg = header_title + \
                    f"<pre>{table_header}{current_body}</pre>"
            else:
                full_msg = f"<pre>{table_header}{current_body}</pre>"

            message_parts.append(full_msg)
            current_body = line
        else:
            current_body += line

    # Append absolute last part
    if current_body:
        if not message_parts:
            full_msg = header_title + \
                f"<pre>{table_header}{current_body}</pre>"
        else:
            full_msg = f"<pre>{table_header}{current_body}</pre>"
        message_parts.append(full_msg)

    # 3. Send
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for part in message_parts:
        data = {
            "chat_id": ADMIN_GROUP_ID,
            "message_thread_id": TECHNICAL_SUPPORT_THREAD_ID,
            "text": part,
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, json=data)
        except Exception as e:
            print(f"Error sending admin report: {e}")
