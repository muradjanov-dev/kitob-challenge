"""One-off 'help us improve the project' survey — 5 questions, 500 Kitobcha
reward on completion. Every answer is DMed to admins live as it arrives.
Broadcast + the 6h pin/auto-unpin are handled by tgbot.tasks.broadcast_project_survey."""
import os
from html import escape

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType, InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.db import transaction

from tgbot.bot.loader import dp
from tgbot.bot.utils import aget_user
from tgbot.bot.states.main import ProjectSurveyState
from tgbot.models import ProjectSurveyResponse, TelegramProfile

Q1_OPTIONS = [("0-1", "🌱 0-1 yil"), ("1-3", "📘 1-3 yil"), ("3-5", "📗 3-5 yil"), ("6+", "📚 6+ yil")]
Q3_OPTIONS = [("1-5", "1-5 ta"), ("5-10", "5-10 ta"), ("10-20", "10-20 ta"), ("20-30", "20-30 ta"), ("30+", "30+ ta")]
SURVEY_REWARD = 500


def _admin_ids():
    return [a.strip() for a in os.environ.get("ADMINS", "").split(",") if a.strip()]


async def _notify_admins(text: str):
    from tgbot.bot.loader import bot
    for admin_id in _admin_ids():
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
        except Exception as e:
            print(f"survey admin notify failed for {admin_id}: {e}")


@sync_to_async
def _get_or_create_response(user_id):
    obj, _created = ProjectSurveyResponse.objects.get_or_create(user_id=user_id)
    return obj


@sync_to_async
def _save_field(resp_id, field, value):
    ProjectSurveyResponse.objects.filter(id=resp_id).update(**{field: value})


@sync_to_async
def _complete_and_reward(resp_id, user_id, rating):
    with transaction.atomic():
        resp = ProjectSurveyResponse.objects.select_for_update().get(id=resp_id)
        if resp.completed:
            return 0
        user = TelegramProfile.objects.select_for_update().get(id=user_id)
        awarded = user.update_ball(True, SURVEY_REWARD)
        resp.rating = rating
        resp.completed = True
        resp.rewarded = True
        resp.save(update_fields=["rating", "completed", "rewarded", "updated_at"])
        return awarded


def _q1_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    for value, label in Q1_OPTIONS:
        kb.insert(InlineKeyboardButton(label, callback_data=f"svy1:{value}"))
    return kb


def _q3_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    for value, label in Q3_OPTIONS:
        kb.add(InlineKeyboardButton(label, callback_data=f"svy3:{value}"))
    return kb


def _q5_kb():
    kb = InlineKeyboardMarkup(row_width=5)
    for n in range(1, 11):
        kb.insert(InlineKeyboardButton(str(n), callback_data=f"svy5:{n}"))
    return kb


async def _send_q1(message):
    await message.answer(
        "1️⃣ <b>Necha yildan beri kitobxonsiz?</b>",
        parse_mode="HTML", reply_markup=_q1_kb(),
    )


async def _send_q2(message, state: FSMContext):
    await message.answer(
        "2️⃣ <b>Kitob Challenge loyihasida yaqin 3 oy ichida qanday yangiliklarni "
        "ko'rishni istaysiz?</b>\n\nFikringizni matn ko'rinishida yozing:",
        parse_mode="HTML",
    )
    await ProjectSurveyState.q2_wishes.set()


async def _send_q3(message):
    await message.answer(
        "3️⃣ <b>1 yilda o'rtacha nechta kitob o'qiysiz?</b>",
        parse_mode="HTML", reply_markup=_q3_kb(),
    )


async def _send_q4(message, state: FSMContext):
    await message.answer(
        "4️⃣ <b>O'zbekiston va O'rta Osiyoda kitobxonlikni rivojlantirish uchun "
        "qanday takliflaringiz bor?</b>\n\n"
        "Istalgan formatda javob bering — matn, ovozli xabar, video yoki rasm "
        "ko'rinishida ham yuborishingiz mumkin:",
        parse_mode="HTML",
    )
    await ProjectSurveyState.q4_suggestions.set()


async def _send_q5(message):
    await message.answer(
        "5️⃣ <b>Kitob Challenge loyihasini 1 dan 10 gacha baholay olasizmi?</b>\n"
        "(1 — yomon, 10 — a'lo)",
        parse_mode="HTML", reply_markup=_q5_kb(),
    )


async def _resume(message, resp, state: FSMContext):
    if resp.years_reading is None:
        await _send_q1(message)
    elif resp.wishes_text is None:
        await _send_q2(message, state)
    elif resp.books_per_year is None:
        await _send_q3(message)
    elif resp.suggestions_text is None:
        await _send_q4(message, state)
    else:
        await _send_q5(message)


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data == "survey_start", state="*")
async def survey_start(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    user = await aget_user(telegram_id=call.from_user.id)
    if not user:
        await call.answer("Avval botga /start bosing.", show_alert=True)
        return
    resp = await _get_or_create_response(user.id)
    if resp.completed:
        await call.answer("✅ Siz allaqachon so'rovnomada qatnashgansiz. Rahmat! 🙏", show_alert=True)
        return
    await call.answer()
    await _resume(call.message, resp, state)


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data.startswith("svy1:"), state="*")
async def survey_q1(call: types.CallbackQuery, state: FSMContext):
    value = call.data.split(":", 1)[1]
    user = await aget_user(telegram_id=call.from_user.id)
    if not user:
        await call.answer()
        return
    resp = await _get_or_create_response(user.id)
    if resp.completed:
        await call.answer("Siz allaqachon qatnashgansiz.", show_alert=True)
        return
    await _save_field(resp.id, "years_reading", value)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer("✅")
    await _notify_admins(
        f"📊 <b>So'rovnoma</b> — {escape(user.full_name or str(user.telegram_id))}\n"
        f"1) Necha yildan beri kitobxon: <b>{value}</b>"
    )
    await _send_q2(call.message, state)


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=ProjectSurveyState.q2_wishes,
                     content_types=types.ContentType.TEXT)
async def survey_q2_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Iltimos, matn ko'rinishida javob yozing.")
        return
    user = await aget_user(telegram_id=message.from_user.id)
    resp = await _get_or_create_response(user.id)
    await _save_field(resp.id, "wishes_text", text)
    await state.finish()
    await _notify_admins(
        f"📊 <b>So'rovnoma</b> — {escape(user.full_name or str(user.telegram_id))}\n"
        f"2) Istaklar: {escape(text)}"
    )
    await _send_q3(message)


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=ProjectSurveyState.q2_wishes)
async def survey_q2_wrong_content(message: types.Message, state: FSMContext):
    await message.answer("✍️ Iltimos, javobingizni matn ko'rinishida yozing.")


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data.startswith("svy3:"), state="*")
async def survey_q3(call: types.CallbackQuery, state: FSMContext):
    value = call.data.split(":", 1)[1]
    user = await aget_user(telegram_id=call.from_user.id)
    if not user:
        await call.answer()
        return
    resp = await _get_or_create_response(user.id)
    if resp.completed:
        await call.answer("Siz allaqachon qatnashgansiz.", show_alert=True)
        return
    await _save_field(resp.id, "books_per_year", value)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer("✅")
    await _notify_admins(
        f"📊 <b>So'rovnoma</b> — {escape(user.full_name or str(user.telegram_id))}\n"
        f"3) Yiliga o'qiladigan kitoblar: <b>{value}</b>"
    )
    await _send_q4(call.message, state)


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=ProjectSurveyState.q4_suggestions,
                     content_types=types.ContentType.ANY)
async def survey_q4_any(message: types.Message, state: FSMContext):
    user = await aget_user(telegram_id=message.from_user.id)
    resp = await _get_or_create_response(user.id)
    text = (message.text or message.caption or "").strip()
    await _save_field(resp.id, "suggestions_text", text or f"[{message.content_type}]")
    await _save_field(resp.id, "suggestions_content_type", message.content_type)
    await state.finish()

    await _notify_admins(
        f"📊 <b>So'rovnoma</b> — {escape(user.full_name or str(user.telegram_id))}\n"
        f"4) Takliflar ({message.content_type}):"
        + (f" {escape(text)}" if text and message.content_type == "text" else " ⬇️ quyida")
    )
    for admin_id in _admin_ids():
        try:
            await message.forward(admin_id)
        except Exception as e:
            print(f"survey q4 forward to admin {admin_id} failed: {e}")

    await _send_q5(message)


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data.startswith("svy5:"), state="*")
async def survey_q5(call: types.CallbackQuery, state: FSMContext):
    rating = int(call.data.split(":", 1)[1])
    user = await aget_user(telegram_id=call.from_user.id)
    if not user:
        await call.answer()
        return
    resp = await _get_or_create_response(user.id)
    if resp.completed:
        await call.answer("Siz allaqachon qatnashgansiz.", show_alert=True)
        return

    awarded = await _complete_and_reward(resp.id, user.id, rating)

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer("✅ Rahmat!")
    await _notify_admins(
        f"📊 <b>So'rovnoma</b> — {escape(user.full_name or str(user.telegram_id))}\n"
        f"5) Baho: <b>{rating}/10</b>\n\n✅ <b>YAKUNLANDI</b> (+{awarded} 🪙)"
    )
    await call.message.answer(
        "🎉 <b>Rahmat!</b> So'rovnomada qatnashganingiz uchun "
        f"<b>+{awarded} Kitobcha</b> hisobingizga qo'shildi!",
        parse_mode="HTML",
    )
