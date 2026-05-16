from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType

from tgbot.bot.loader import dp
from tgbot.bot.utils import aget_user
from tgbot.bot.handlers.users.menu_router import send_main_menu


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), commands=["restart"], state="*")
async def restart_command(message: types.Message, state: FSMContext):
    """Registered users: clear FSM and return to main menu.
    Unregistered users: clear FSM and prompt them to use /start."""
    await state.finish()
    user = await aget_user(message.from_user.id)
    if user and user.is_registered:
        await send_main_menu(message, user)
        return
    lang = (user.language if user else None) or "uz"
    msg = (
        "Ro'yxatdan o'tish uchun /start tugmasini bosing."
        if lang != "ru"
        else "Нажмите /start, чтобы зарегистрироваться."
    )
    await message.answer(msg)
