from aiogram.dispatcher.filters import BoundFilter
from aiogram import types


class IsPrivate(BoundFilter):
    """Bound filter that works for both Message and CallbackQuery updates.

    When applied to a callback handler, aiogram passes the CallbackQuery
    object (which has no `.chat` attribute) — falling through to the message
    inside the callback handles that case. Without this guard, every
    CallbackQuery in the system raises AttributeError because the bound
    filter is checked across handlers globally."""

    async def check(self, obj):
        if isinstance(obj, types.CallbackQuery):
            if obj.message and getattr(obj.message, "chat", None):
                return obj.message.chat.type == types.ChatType.PRIVATE
            return False
        chat = getattr(obj, "chat", None)
        if chat is None:
            return False
        return chat.type == types.ChatType.PRIVATE