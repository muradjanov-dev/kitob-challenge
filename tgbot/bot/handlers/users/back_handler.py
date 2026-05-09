from aiogram import types
from tgbot.bot.keyboards.inline import languages_markup
from tgbot.bot.keyboards.reply import back_keyboard
from tgbot.bot.states.main import AdmissionState
from tgbot.bot.loader import dp, gettext as _
from tgbot.bot.utils import get_user
from tgbot.bot.handlers.users.menu_router import send_main_menu

from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType
from aiogram.dispatcher import FSMContext
from asgiref.sync import sync_to_async
from tgbot.models import TelegramProfile


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=AdmissionState.full_name, content_types=types.ContentType.TEXT, text=_("🔙 Orqaga"))
async def back_to_language(message: types.Message, state: FSMContext):
    await message.answer(
                text='Marhamat tilni tanlang! 🇺🇿\nПожалуйста, выберите язык! 🇷🇺',
                reply_markup=languages_markup)
    await AdmissionState.language.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=AdmissionState.language, content_types=types.ContentType.TEXT)
async def language_pick_during_registration(message: types.Message, state: FSMContext):
    text = message.text
    if text == "O'zbekcha":
        lang = "uz"
    elif text == "Русский":
        lang = "ru"
    else:
        await message.answer(
            'Marhamat tilni tanlang! 🇺🇿\nПожалуйста, выберите язык! 🇷🇺',
            reply_markup=languages_markup,
        )
        return

    await sync_to_async(
        TelegramProfile.objects.filter(telegram_id=message.from_user.id).update
    )(language=lang)

    if lang == "ru":
        prompt = "Пожалуйста, введите ваше имя:"
    else:
        prompt = "Iltimos, ismingizni kiriting:"

    await message.answer(prompt, reply_markup=back_keyboard)
    await AdmissionState.full_name.set()


@dp.message_handler(text=_("❌ Bekor qilish"), content_types=types.ContentType.TEXT, state="*")
@dp.message_handler(text=_("🔙 Orqaga"), content_types=types.ContentType.TEXT, state="*")
async def back_to_main_menu(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await state.finish()
    await send_main_menu(message, user)