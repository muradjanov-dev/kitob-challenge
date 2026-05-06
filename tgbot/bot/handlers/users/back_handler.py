from aiogram import types
from tgbot.bot.keyboards.inline import languages_markup
from tgbot.bot.states.main import AdmissionState
from tgbot.bot.loader import dp, gettext as _
from tgbot.bot.utils import get_user
from tgbot.bot.handlers.users.menu_router import send_main_menu

from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType
from aiogram.dispatcher import FSMContext


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=AdmissionState.full_name, content_types=types.ContentType.TEXT, text=_("🔙 Orqaga"))
async def back_to_language(message: types.Message):
    await message.answer(
                text='Marhamat tilni tanlang! 🇺🇿\nПожалуйста, выберите язык! 🇷🇺',
                reply_markup=languages_markup)
    await AdmissionState.language.set()


@dp.message_handler(text=_("❌ Bekor qilish"), content_types=types.ContentType.TEXT, state="*")
@dp.message_handler(text=_("🔙 Orqaga"), content_types=types.ContentType.TEXT, state="*")
async def back_to_main_menu(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await state.finish()
    await send_main_menu(message, user)