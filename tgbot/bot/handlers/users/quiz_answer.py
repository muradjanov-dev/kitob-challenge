from aiogram import types
from asgiref.sync import sync_to_async
from django.utils import timezone
from django.db.models import F

from tgbot.bot.loader import dp, bot
from tgbot.models import PollState, ContestParticipant, ContestSubmission, Question, TelegramProfile
from tgbot.bot.keyboards.reply import main_markup


from django.db import close_old_connections


@dp.poll_answer_handler()
async def handle_poll_answer(quiz_answer: types.PollAnswer):
    await sync_to_async(close_old_connections)()
    print(
        f"Received poll answer: {quiz_answer.poll_id}, User: {quiz_answer.user.id}")

    poll_id = quiz_answer.poll_id
    user_id = quiz_answer.user.id
    selected_options = quiz_answer.option_ids

    if not selected_options:
        # Retracted vote? Not supported in quiz mode usually.
        return

    # In quiz mode, single answer usually.
    selected_option = selected_options[0]

    try:
        # Fetch state
        state = await sync_to_async(PollState.objects.select_related('user', 'question', 'question__contest').get)(poll_id=poll_id)
        user = state.user
        question = state.question
        contest = question.contest

        # Verify user match (paranoid check)
        if user.telegram_id != user_id:
            return

        # Fetch Participant
        try:
            participant = await sync_to_async(ContestParticipant.objects.get)(contest=contest, user=user)
        except ContestParticipant.DoesNotExist:
            return

        if participant.is_finished:
            return

        # Check if already answered (duplicate update?)
        already = await sync_to_async(ContestSubmission.objects.filter(participant=participant, question=question).exists)()
        if already:
            return

        # Record Answer
        is_correct = (selected_option == question.correct_option)
        submission_time = timezone.now()

        # Calculate time taken
        start_time = participant.last_question_sent_at or submission_time
        time_diff = (submission_time - start_time).total_seconds()
        if time_diff < 0:
            time_diff = 0

        await sync_to_async(ContestSubmission.objects.create)(
            participant=participant,
            question=question,
            selected_option=selected_option,
            is_correct=is_correct,
            time_taken=time_diff
        )

        # Update Stats
        # Use update() for atomicity on simple fields, but we have multiple fields.
        # For strict accuracy we used F() expressions ideally, but simple increment is ok with one worker per user usually.
        participant.total_score = F('total_score') + (1 if is_correct else 0)
        participant.total_time = F('total_time') + time_diff
        participant.current_question_index = F('current_question_index') + 1
        await sync_to_async(participant.save)(update_fields=['total_score', 'total_time', 'current_question_index'])

        # Trigger Next Question
        # Ideally, we should fetch the *next* order from DB.
        next_question = await sync_to_async(
            Question.objects.filter(
                contest=contest, order__gt=question.order).order_by('order').first
        )()

        if next_question:
            # from tgbot.tasks import send_question_to_user_task
            # send_question_to_user_task.delay(
            #     user.id, contest.id, next_question.id)
            pass
        else:
            # Finish
            participant.is_finished = True
            await sync_to_async(participant.save)(update_fields=['is_finished'])
            # We need to refresh to get actual values if we want to show them, since we used F()
            await sync_to_async(participant.refresh_from_db)()

            msg = (f"🏁 <b>Konkurs yakunlandi!</b>\n\n"
                   f"👤 Ism: {participant.user.full_name}\n"
                   f"✅ To'g'ri javoblar: {participant.total_score} ta\n"
                   f"⏱ Sarflagan vaqt: {participant.total_time:.1f} soniya")

            # Restore Request Main Menu
            menu_kb = main_markup(language=user.language or "uz")

            await bot.send_message(
                chat_id=user.telegram_id,
                text=msg,
                parse_mode="HTML",
                reply_markup=menu_kb
            )

            # Check if ALL participants finished
            unfinished_count = await sync_to_async(ContestParticipant.objects.filter(
                contest=contest, is_finished=False).count)()

            if unfinished_count == 0:
                from tgbot.tasks import finish_contest_task
                finish_contest_task.delay(contest.id)

    except PollState.DoesNotExist:
        # Poll not found in our DB, maybe old or from other logic
        pass
    except Exception as e:
        print(f"Error in poll_answer: {e}")
