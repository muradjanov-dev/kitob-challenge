from aiogram import types
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import get_user
from tgbot.bot.consts import ADMIN_GROUP_ID


@dp.message_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), commands="create_topics")
async def create_topic(message: types.Message):
    if str(message.from_user.id) != str(1603330179):
        return

    data = await bot.create_forum_topic(chat_id=ADMIN_GROUP_ID, name="To'lov")
    await message.answer(f"Topic nomi: {data.name}\nTopic id: {data.message_thread_id}")

    data = await bot.create_forum_topic(chat_id=ADMIN_GROUP_ID, name="Xabarlar")
    await message.answer(f"Topic nomi: {data.name}\nTopic id: {data.message_thread_id}")

    data = await bot.create_forum_topic(chat_id=ADMIN_GROUP_ID, name="Texnik nosozliklar")
    await message.answer(f"Topic nomi: {data.name}\nTopic id: {data.message_thread_id}")
