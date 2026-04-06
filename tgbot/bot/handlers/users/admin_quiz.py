import json
import os
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from asgiref.sync import sync_to_async
from django.db.models import Count, Max

from tgbot.bot.loader import dp, bot
from tgbot.bot.filters import IsPrivate
from tgbot.bot.states.main import QuizUploadState
from tgbot.models import Contest, Question
from tgbot.bot.utils import get_user
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


@dp.message_handler(IsPrivate(), Text("📥 Viktorina yuklash"))
async def start_quiz_upload(message: types.Message):
    user = get_user(message.from_user.id)
    if not user or not user.is_admin:
        await message.answer("Sizga bu amalni bajarish ruxsat etilmagan.")
        return

    contests = await sync_to_async(list)(
        Contest.objects.filter(is_active=True).annotate(
            q_count=Count('questions'))
    )
    if not contests:
        contests = await sync_to_async(list)(
            Contest.objects.all().annotate(
                q_count=Count('questions')).order_by('-id')[:10]
        )

    if not contests:
        await message.answer("Hozircha hech qanday konkurs mavjud emas. Avval admin paneldan konkurs yarating.")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for contest in contests:
        markup.add(InlineKeyboardButton(
            text=f"{contest.name} ({contest.q_count} ta savol)",
            callback_data=f"select_contest:{contest.id}"
        ))

    markup.add(InlineKeyboardButton(text="❌ Bekor qilish",
               callback_data="cancel_quiz_upload"))

    await message.answer("Qaysi konkurs uchun viktorina yuklamoqchisiz? Tanlang:", reply_markup=markup)
    await QuizUploadState.select_contest.set()


@dp.callback_query_handler(text="cancel_quiz_upload", state="*")
async def cancel_upload(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await call.message.edit_text("Amal bekor qilindi.")
    await call.answer()


@dp.callback_query_handler(state=QuizUploadState.select_contest)
async def contest_selected(call: types.CallbackQuery, state: FSMContext):
    if not call.data.startswith("select_contest:"):
        await call.answer("Tanlov noto'g'ri")
        return

    contest_id = int(call.data.split(":")[1])
    await state.update_data(contest_id=contest_id)

    contest = await sync_to_async(Contest.objects.get)(id=contest_id)
    questions_count = await sync_to_async(contest.questions.count)()

    if questions_count > 0:
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(
                text="🗑 Barchasini o'chirish va yangi yuklash", callback_data="action:overwrite"),
            InlineKeyboardButton(text="➕ Davomidan qo'shish",
                                 callback_data="action:append"),
            InlineKeyboardButton(text="❌ Bekor qilish",
                                 callback_data="cancel_quiz_upload")
        )
        await call.message.edit_text(
            f"Tanlangan konkurs: <b>{contest.name}</b>\nBu konkursda {questions_count} ta savol mavjud. Nima qilamiz?",
            reply_markup=markup,
            parse_mode="HTML"
        )
        await QuizUploadState.choose_action.set()
    else:
        # No questions, direct to upload, default to append (create new)
        await state.update_data(action="append")
        await ask_for_file(call.message, contest.name)


@dp.callback_query_handler(state=QuizUploadState.choose_action)
async def action_chosen(call: types.CallbackQuery, state: FSMContext):
    action = call.data.split(":")[1]
    await state.update_data(action=action)

    data = await state.get_data()
    contest_id = data.get("contest_id")
    contest = await sync_to_async(Contest.objects.get)(id=contest_id)

    await ask_for_file(call.message, contest.name)


async def ask_for_file(message, contest_name):
    try:
        if os.path.exists("sample_questions.json"):
            sample_file = types.InputFile("sample_questions.json")
            caption = (
                f"Konkurs: <b>{contest_name}</b>\n\n"
                f"Iltimos, savollar bo'lgan <b>.json</b> faylni yuklang.\n"
                f"Namuna fayl yuqorida keltirilgan."
            )
            await message.answer_document(sample_file, caption=caption, parse_mode="HTML")
        else:
            await message.answer(
                f"Konkurs: <b>{contest_name}</b>\n\nIltimos, savollar bo'lgan <b>.json</b> faylni yuklang.",
                parse_mode="HTML"
            )
    except:
        await message.answer(
            f"Konkurs: <b>{contest_name}</b>\n\nIltimos, savollar bo'lgan <b>.json</b> faylni yuklang.",
            parse_mode="HTML"
        )

    await QuizUploadState.upload_file.set()


@dp.message_handler(content_types=types.ContentType.DOCUMENT, state=QuizUploadState.upload_file)
async def file_uploaded(message: types.Message, state: FSMContext):
    document = message.document

    if not document.file_name.endswith('.json'):
        await message.answer("Iltimos, faqat .json formatidagi faylni yuklang.")
        return

    msg = await message.answer("Fayl yuklanmoqda va tekshirilmoqda... ⏳")

    data = await state.get_data()
    contest_id = data.get("contest_id")
    action = data.get("action")

    file_info = await bot.get_file(document.file_id)
    file_path = file_info.file_path

    destination = f"/tmp/{document.file_name}"
    await bot.download_file(file_path, destination)

    try:
        with open(destination, 'r', encoding='utf-8') as f:
            questions_data = json.load(f)

        if not isinstance(questions_data, list):
            await msg.edit_text("JSON fayl tarkibi ro'yxat (list) ko'rinishida bo'lishi kerak.")
            if os.path.exists(destination):
                os.remove(destination)
            return

        contest = await sync_to_async(Contest.objects.get)(id=contest_id)

        @sync_to_async
        def process_db_operations():
            start_order = 1
            if action == 'overwrite':
                contest.questions.all().delete()
            elif action == 'append':
                max_order = contest.questions.aggregate(Max('order'))[
                    'order__max']
                if max_order:
                    start_order = max_order + 1

            created_count = 0
            for i, q_data in enumerate(questions_data, start=start_order):
                Question.objects.create(
                    contest=contest,
                    question=q_data.get('question'),
                    options=q_data.get('options', []),
                    correct_option=q_data.get('correct_option', 0),
                    explanation=q_data.get('explanation', ''),
                    order=i
                )
                created_count += 1
            return created_count

        count = await process_db_operations()

        await msg.edit_text(f"✅ <b>Muvaffaqiyatli!</b>\n\nBaza yangilandi.\nQo'shilgan savollar soni: {count} ta.", parse_mode="HTML")
        await state.finish()

    except json.JSONDecodeError:
        await msg.edit_text("Fayl noto'g'ri JSON formatida.")
    except Exception as e:
        await msg.edit_text(f"Xatolik yuz berdi: {str(e)}")
    finally:
        if os.path.exists(destination):
            os.remove(destination)
