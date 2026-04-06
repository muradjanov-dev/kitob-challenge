from aiogram import types
from aiogram.dispatcher.filters.builtin import Text
from tgbot.bot.loader import dp
from tgbot.bot.loader import gettext as _
from utils.subscription import get_result
from tgbot.bot.keyboards.inline import get_check_button


@dp.callback_query_handler(text="check_subs")
async def check_subscription(call: types.CallbackQuery):
    await call.answer()

    user_id = call.from_user.id
    final_status, chat_ids = await get_result(user_id)

    if not final_status:
        # Not subscribed yet
        reply_markup = await get_check_button(chat_ids)
        await call.answer(_("Hali hamma kanallarga obuna bo'lmadingiz ❌"), show_alert=True)
        try:
            # Update buttons (maybe list changed or just to refresh)
            await call.message.edit_reply_markup(reply_markup=reply_markup)
        except Exception:
            pass
    else:
        # Subscribed!
        await call.answer(_("Obuna tasdiqlandi! ✅"), show_alert=True)
        await call.message.delete()
        await call.message.answer(
            _("Obuna tasdiqlandi! ✅\n\nBotdan foydalanish uchun /start tugmasini bosing.")
        )
