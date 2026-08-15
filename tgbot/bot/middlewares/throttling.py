from aiogram import types, Dispatcher
try:
    from aiogram.dispatcher import DEFAULT_RATE_LIMIT
except (ImportError, ModuleNotFoundError):
    DEFAULT_RATE_LIMIT = 0.1

try:
    from aiogram.dispatcher.handler import CancelHandler, current_handler
except (ImportError, ModuleNotFoundError):
    class CancelHandler(Exception):
        pass
    class _CurrentHandler:
        def get(self):
            return None
    current_handler = _CurrentHandler()

try:
    from aiogram.dispatcher.middlewares import BaseMiddleware
except (ImportError, ModuleNotFoundError):
    try:
        from aiogram import BaseMiddleware
    except Exception:
        class BaseMiddleware:
            pass

try:
    from aiogram.utils.exceptions import Throttled
except (ImportError, ModuleNotFoundError):
    try:
        from aiogram.exceptions import TelegramBadRequest as Throttled
    except Exception:
        class Throttled(Exception):
            pass


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
