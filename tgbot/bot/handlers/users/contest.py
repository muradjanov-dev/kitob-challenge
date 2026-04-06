from tgbot.models import Contest, ContestParticipant, Question, ContestSubmission, TelegramProfile
from django.utils import timezone
from aiogram import types
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
import urllib.parse
import string
import random
from asgiref.sync import sync_to_async

from tgbot.services.referral import ReferralService
from tgbot.bot.consts import REFERRAL_THRESHOLD

from tgbot.bot.loader import dp, bot
from tgbot.bot.loader import gettext as _
from tgbot.bot.utils import get_user
from tgbot.models import TelegramProfile, UserReferal
from tgbot.bot.keyboards.reply import main_markup


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="🏆 Konkurs(Yanvar)")
async def contest_handler(message: types.Message):

    # if True:
    #     msg = (
    #         "29-yanvarda qabul ochiladi.\n\n"
    #         "Kichkina shahzoda asaridan savollar beriladi. 10+ o‘ringa sovg‘alar taqdim etiladi.\n\n"
    #         "Xurmatli Kitobxon himmatingizni oshiring 🔥"
    #     )
    #     await message.answer(msg, reply_markup=main_markup(), parse_mode=ParseMode.HTML)
    #     return

    user = get_user(message.from_user.id)
    if not user:
        return

    referral_link = await ReferralService.get_referral_link(user)
    count = await ReferralService.get_referral_count(user)

    share_text = f"\n\nAssalomu alaykum, Men ushbu bot orqali shu kungacha o‘qigan kitoblarim va betlar sonini kuzatib borolaman. 1.000.000+ bet birga kitob o‘qidik. \n\n*31-yanvar Katta musobaqa 🎁\n\n🌞 Siz ham millatni uyg‘otishda jamoaga qo‘shiling."

    encoded_msg = urllib.parse.quote(share_text)
    encoded_link = urllib.parse.quote(referral_link)
    share_url = f"tg://msg_url?url={encoded_link}&text={encoded_msg}"

    if count < REFERRAL_THRESHOLD:
        msg = (
            f"<b>🏆 Konkursda qatnashish uchun shartlar:</b>\n\n"
            f"1. Quyidagi havolani do'stlaringizga yuboring.\n"
            f"2. Ular botga start bosib ro'yxatdan o'tishlari kerak.\n"
            f"3. Konkursda qatnashish uchun kamida <b>{REFERRAL_THRESHOLD} ta</b> do'stingizni taklif qilishingiz kerak.\n\n"
            f"📊 Hozirda sizda: <b>{count} ta</b> referal bor.\n\n"
            f"🔗 <b>Sizning havolangiz:</b>\n{referral_link}"
        )

        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton(
            text="🔗 Do'stlarga ulashish", url=share_url))
        markup.add(InlineKeyboardButton(text="📋 Nusxalash",
                   callback_data="copy_referral_link"))

        await message.answer(msg, reply_markup=markup, parse_mode=ParseMode.HTML)
    else:
        markup = InlineKeyboardMarkup(row_width=1)
        # markup.add(InlineKeyboardButton(
        #     "✅ Qatnashish", callback_data="join_contest"))

        markup.add(InlineKeyboardButton(
            text="🔗 Do'stlarga ulashish", url=share_url))

        msg = (
            f"🎉 <b>Tabriklaymiz!</b>\n\n"
            f"Siz konkurs talablarini bajardingiz! Sizda <b>{count} ta</b> referal bor.\n"
            f"Konkursda g'olib bo'lish imkoniyati sizda yuqori!\n\n"
            f"🔗 <b>Sizning havolangiz:</b>\n{referral_link}\n\n"
            f"Pastdagi tugmani bosib konkursda qatnashishingizni tasdiqlang 👇"
        )
        await message.answer(msg, reply_markup=markup, parse_mode=ParseMode.HTML)


@dp.callback_query_handler(text="copy_referral_link")
async def copy_link_callback(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    if not user.referral_code:
        # Fallback if code missing (shouldn't happen here usually)
        await call.answer("Referal kod topilmadi.", show_alert=True)
        return

    link = await ReferralService.get_referral_link(user)

    await call.message.answer(f"Nusxalash uchun bosing:\n<code>{link}</code>", parse_mode='HTML')
    await call.answer("Havola yuborildi!", show_alert=False)


@dp.callback_query_handler(text="join_contest")
async def join_contest_callback(call: types.CallbackQuery):
    await call.answer("Siz muvaffaqiyatli ro'yxatdan o'tdingiz! 🎉", show_alert=True)
    await call.message.edit_reply_markup(reply_markup=None)


@dp.callback_query_handler(text_contains="quiz:")
async def submit_quiz_answer(call: types.CallbackQuery):
    # Import inside function to avoid circular import with tasks.py
    from tgbot.tasks import send_question_to_user_task, finish_contest_task

    # Data format: quiz:question_id:option_index
    try:
        _, q_id_str, opt_idx_str = call.data.split(":")
        question_id = int(q_id_str)
        option_index = int(opt_idx_str)
    except ValueError:
        await call.answer("Xatolik: ma'lumot formati noto'g'ri")
        return

    # Use sync_to_async safely
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Foydalanuvchi topilmadi.")
        return

    submission_time = timezone.now()

    # 1. Fetch needed data
    question = await sync_to_async(Question.objects.select_related('contest').get)(id=question_id)
    contest = question.contest

    # Check if user is participant
    try:
        participant = await sync_to_async(ContestParticipant.objects.get)(contest=contest, user=user)
    except ContestParticipant.DoesNotExist:
        await call.answer("Siz bu konkurs ishtirokchisi emassiz.", show_alert=True)
        return

    if participant.is_finished:
        await call.answer("Siz konkursni yakunlagansiz.", show_alert=True)
        return

    # 2. Check if already answered this question
    already_answered = await sync_to_async(ContestSubmission.objects.filter(participant=participant, question=question).exists)()
    if already_answered:
        await call.answer("Siz bu savolga javob bergansiz.", show_alert=True)
        return

    # 3. Process Answer
    is_correct = (option_index == question.correct_option)

    # Calculate time taken
    # We rely on last_question_sent_at. If null, roughly 0.
    start_time = participant.last_question_sent_at or submission_time
    time_diff = (submission_time - start_time).total_seconds()
    if time_diff < 0:
        time_diff = 0

    # Save submission
    await sync_to_async(ContestSubmission.objects.create)(
        participant=participant,
        question=question,
        selected_option=option_index,
        is_correct=is_correct,
        time_taken=time_diff
    )

    # Update Participant Score/Time/Index
    participant.total_score += 1 if is_correct else 0
    participant.total_time += time_diff
    participant.current_question_index += 1
    await sync_to_async(participant.save)(update_fields=['total_score', 'total_time', 'current_question_index'])

    # Feedback to user (edit message to show correct/incorrect)
    new_markup = InlineKeyboardMarkup()
    for idx, opt_text in enumerate(question.options):
        # Mark the selected one
        prefix = ""
        if idx == option_index:
            prefix = "✅ " if is_correct else "❌ "
        elif idx == question.correct_option and not is_correct:
            # Show correct one if wrong
            prefix = "👈 "

        # Disable buttons by changing callback_data to "ignore"
        new_markup.add(InlineKeyboardButton(
            f"{prefix}{opt_text}", callback_data="ignore"))

    await call.message.edit_text(
        f"❓ <b>{question.question}</b>\n\nJavob qabul qilindi: {question.options[option_index]}",
        reply_markup=new_markup,
        parse_mode="HTML"
    )

    # 4. Next Question
    next_question = await sync_to_async(
        Question.objects.filter(
            contest=contest, order__gt=question.order).order_by('order').first
    )()

    if next_question:
        # Send next
        # send_question_to_user_task.delay(user.id, contest.id, next_question.id)
        pass
    else:
        # Finish
        participant.is_finished = True
        await sync_to_async(participant.save)(update_fields=['is_finished'])

        msg = (f"🏁 <b>Konkurs yakunlandi!</b>\n\n"
               f"👤 Ism: {participant.user.full_name}\n"
               f"✅ To'g'ri javoblar: {participant.total_score} ta\n"
               f"⏱ Sarflagan vaqt: {participant.total_time:.1f} soniya")

        await call.message.answer(msg)
        pass


@dp.callback_query_handler(text="ignore")
async def ignore_callback(call: types.CallbackQuery):
    await call.answer()
