"""Last resort for buttons no handler takes (2026-11-21).

A button from an old message whose feature changed or whose step is over
used to spin forever with no reply. Imported last (handlers/__init__.py), so
every real handler -- private, group or channel -- comes first.
"""
from aiogram import types

from tgbot.bot.loader import dp


@dp.callback_query_handler(state="*")
async def unknown_button(call: types.CallbackQuery):
    print(f"unhandled callback: {call.data!r} from {call.from_user.id}")
    try:
        await call.answer("⌛️ Bu tugma eskirgan yoki endi ishlamaydi. /menu orqali qaytadan boshlang.",
                          show_alert=True)
    except Exception:
        pass
