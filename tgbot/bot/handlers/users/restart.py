from aiogram import types
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType

from tgbot.bot.loader import dp
from tgbot.bot.loader import gettext as _
from tgbot.bot.utils import get_user


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), commands=["restart"], state="*")
async def unregister_command(message: types.Message):
    user = get_user(message.from_user.id)
    if user.is_registered:
        user.is_registered = False
        user.save()
        await message.answer(_("Qaytadan ro‘yxatdan o‘tish uchun /start tugmasini bosing."))
    else:
        await message.answer(_("Siz ro‘yxatdan o‘tish uchun /start tugmasini bosing"))
