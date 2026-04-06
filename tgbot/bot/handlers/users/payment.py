from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType

from tgbot.bot.utils import get_user
from tgbot.bot.states.main import PaymentStates
from tgbot.bot.loader import dp, bot, gettext as _
from tgbot.bot.keyboards.reply import main_markup
from tgbot.bot.keyboards.inline import make_send_receipt_to_group_button
from tgbot.bot.consts import ADMIN_GROUP_ID, PAYMENT_THREAD_ID

@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: "send_receipt" in c.data)
async def payment_message_handler(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer(_("👇🏻 Yaxshi, quyida to'lov chekini rasm ko'rinishida yuborishingiz mumkin:"))
    await PaymentStates.receipt.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), content_types=types.ContentType.PHOTO, state=PaymentStates.receipt)
async def payment_message_handler(message: types.Message, state: FSMContext):
    user = get_user(telegram_id=message.from_user.id)
    caption = f"""{user.full_name}[<a href="https://t.me/{user.username}">@{user.username}</a>] to'lov chekini yubordi, botdan foydalanishga ruxsat berilsinmi?"""
    try:
        # photo_message = await bot.send_photo(
        #     chat_id=ADMIN_GROUP_ID,
        #     photo=message.photo[-1].file_id,
        #     caption=caption,
        #     reply_markup=await make_send_receipt_to_group_button(telegram_id=user.telegram_id)
        # )
        # photo_message_id = photo_message.message_id

        photo_message = await bot.send_photo(
            chat_id=ADMIN_GROUP_ID,
            message_thread_id=PAYMENT_THREAD_ID,
            photo=message.photo[-1].file_id,
            caption=caption,
            reply_markup=await make_send_receipt_to_group_button(
                telegram_id=user.telegram_id,
                message_id=None
            )
        )

        reply_markup = await make_send_receipt_to_group_button(
            telegram_id=user.telegram_id,
            message_id=photo_message.message_id
        )

        await bot.edit_message_reply_markup(
            chat_id=ADMIN_GROUP_ID,
            message_id=photo_message.message_id,
            reply_markup=reply_markup
        )

        text = _(
            "✅ Yuborilgan to'lov cheki tekshirish jarayonida, tez orada sizga xabar beraman!")
    except Exception as e:
        print(f"Kvitansiya yuborishda xatolik: {e}")
        text = _(
            "❗️ To'lov chekini yuborish paytida xatolik sodir bo'ldi, birozdan keyin qayta urinib ko'ring!")

    await message.answer(text, reply_markup=main_markup(language=user.language))
    await state.finish()
