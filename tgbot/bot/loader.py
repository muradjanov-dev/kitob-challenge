import os
from src.settings import API_TOKEN, REDIS_HOST, REDIS_PORT, REDIS_DB
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from django.conf import settings
from .middlewares.localization import Localization

# Ensure locale directory exists so i18n doesn't crash on fresh deployments
os.makedirs(settings.LOCALES_DIR, exist_ok=True)

bot = Bot(token=API_TOKEN, parse_mode=types.ParseMode.HTML)

# FSM state must persist across gunicorn workers + bg threads.
# Redis is shared; in-memory is per-process and loses state on every other request.
try:
    from aiogram.contrib.fsm_storage.redis import RedisStorage2
    _redis_password = os.environ.get("REDIS_PASSWORD") or None
    storage = RedisStorage2(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=_redis_password,
        prefix="fsm",
    )
except Exception as _e:
    print(f"RedisStorage2 init failed, falling back to MemoryStorage: {_e}")
    storage = MemoryStorage()

dp = Dispatcher(bot, storage=storage)

# Setup i18n middleware
i18n = Localization(settings.I18N_DOMAIN, settings.LOCALES_DIR)
dp.middleware.setup(i18n)

# Alias for gettext method
gettext = i18n.lazy_gettext

from aiogram import types, Dispatcher
from aiogram.dispatcher import DEFAULT_RATE_LIMIT
from aiogram.dispatcher.handler import CancelHandler, current_handler
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.utils.exceptions import Throttled


class ThrottlingMiddleware(BaseMiddleware):
    """
    Simple middleware
    """

    def __init__(self, limit=DEFAULT_RATE_LIMIT, key_prefix='antiflood_'):
        self.rate_limit = limit
        self.prefix = key_prefix
        super(ThrottlingMiddleware, self).__init__()

    async def on_process_message(self, message: types.Message, data: dict):
        handler = current_handler.get()
        dispatcher = Dispatcher.get_current()
        if handler:
            limit = getattr(handler, "throttling_rate_limit", self.rate_limit)
            key = getattr(handler, "throttling_key", f"{self.prefix}_{handler.__name__}")
        else:
            limit = self.rate_limit
            key = f"{self.prefix}_message"
        try:
            await dispatcher.throttle(key, rate=limit)
        except Throttled as t:
            await self.message_throttled(message, t)
            raise CancelHandler()

    async def message_throttled(self, message: types.Message, throttled: Throttled):
        if throttled.exceeded_count <= 2:
            await message.reply("Too many requests!")


dp.middleware.setup(ThrottlingMiddleware())

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.middlewares import BaseMiddleware
from utils.subscription import get_result
from tgbot.bot.keyboards.inline import get_check_button


class BigBrother(BaseMiddleware):
    async def on_pre_process_update(self, update: types.Update, data: dict):
        if update.message:
            user = update.message.from_user.id
            if update.message.text in ['/start', ]:
                return
        elif update.callback_query:
            user = update.callback_query.from_user.id
            if update.callback_query.data in ['check_subs', ]:
                return
        else:
            return

        final_status, chat_ids = await get_result(user_id=user)
        reply_markup = await get_check_button(chat_ids)
        if not final_status:
            if reply_markup:
                await update.message.answer(
                    gettext(f"Quyidagi kanallarga obuna bo'lishingiz kerak, pastdagi tugmalar ustiga bosing ⬇️\n\n"
                  f"Вам необходимо подписаться на следующие каналы, нажмите на кнопки ниже ⬇️\n\n"
                  f"You must subscribe to the following channels, click on the buttons below ⬇️"),
                    reply_markup=reply_markup, disable_web_page_preview=True)
            
            raise CancelHandler()


dp.middleware.setup(BigBrother())

# NOTE: a GroupMessageFilter middleware used to live here (added 2026-06-15,
# commit b4eae1d), deleting any group message from a user who had ANY active
# FSM state in their private chat with the bot -- meant to stop "mid-flow
# private input typed in a group" from misfiring a DM handler. That scenario
# doesn't actually happen: aiogram scopes FSM state per (chat_id, user_id),
# so a group message (chat_id = the group's id) can never match a handler
# state-filtered against the user's private chat state (chat_id = user_id).
# The middleware was silently deleting real, unrelated group messages from
# any user who simply had an unfinished flow anywhere in the bot (report,
# quiz creation, admin panel, ...) -- removed 2026-08-03 after user reports
# of messages vanishing in the group.
