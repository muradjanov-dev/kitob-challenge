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


@dp.message_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), commands="topicid")
async def topic_id(message: types.Message):
    """Debug helper: send /topicid inside any topic to see its chat_id and
    message_thread_id, so they can be wired up as env vars for group routing.
    Deliberately open to anyone — it only echoes public IDs, nothing sensitive."""
    await message.answer(
        f"Chat id: <code>{message.chat.id}</code>\n"
        f"Topic (thread) id: <code>{message.message_thread_id}</code>",
        parse_mode="HTML",
    )
