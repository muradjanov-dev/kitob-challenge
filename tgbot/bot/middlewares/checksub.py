import logging
from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.middlewares import BaseMiddleware
from utils.subscription import get_result
from tgbot.bot.keyboards.inline import get_check_button
from tgbot.bot.loader import gettext as _


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
        logging.info(user)
        if not final_status:
            await update.message.answer(
                _(f"Quyidagi kanallarga obuna bo'lishingiz kerak, pastdagi tugmalar ustiga bosing ⬇️\n\n"
                  f"Вам необходимо подписаться на следующие каналы, нажмите на кнопки ниже ⬇️\n\n"
                  f"You must subscribe to the following channels, click on the buttons below ⬇️"),
                reply_markup=reply_markup, disable_web_page_preview=True)
            raise CancelHandler()
