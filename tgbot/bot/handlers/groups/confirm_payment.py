from aiogram import types
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType
from aiogram.dispatcher import FSMContext
from django.utils import timezone
from datetime import timedelta

from tgbot.bot.loader import dp, bot, gettext as _
from tgbot.models import Payment
from tgbot.bot.utils import get_user
from tgbot.bot.keyboards.inline import send_receipt_button
from tgbot.bot.handlers.users.habit_notification import MONTHLY_PAYMENT
from tgbot.bot.consts import ADMIN_GROUP_ID


@dp.callback_query_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), lambda c: "accept" in c.data)
async def confirm_payment_message_handler(call: types.CallbackQuery, state: FSMContext):
    split_data = call.data.split(":")
    user_telegram_id = split_data[1]
    photo_message_id = split_data[2]

    user = get_user(telegram_id=user_telegram_id)

    if not user:
        return

    try:
        start_date = timezone.localdate()
        end_date = timezone.localdate() + timedelta(days=30)
        Payment.objects.create(
            user=user,
            amount=MONTHLY_PAYMENT,
            start_date=start_date,
            end_date=end_date,
            status="paid"
        )

        message_to_user = _(
            "Tabriklaymiz! 🎉 \n\n"
            "Siz 1 oylik to‘lovni muvaffaqiyatli amalga oshirdingiz. "
            "Endi botdan bemalol 1 oy davomida foydalanishingiz mumkin."
        )
        data = await state.get_data()
        username_or_telegram_id = f"""<a href="https://{user.username}.t.me">@{user.username}</a>""" if user.username else user.telegram_id
        message_to_admin = f"""✅To'lov tasdiqlandi!\n👤FISH: {user.full_name}[{username_or_telegram_id}]\n🧾Qiymat: {MONTHLY_PAYMENT} UZS\n📅Davr: {start_date.strftime("%d.%m.%Y")} -> {end_date.strftime("%d.%m.%Y")}\n\n#paid #monthly"""
        if photo_message_id:
            try:
                await bot.edit_message_caption(
                    caption=message_to_admin,
                    chat_id=ADMIN_GROUP_ID,
                    message_id=int(photo_message_id),
                    reply_markup=None
                )
            except:
                await call.message.answer(message_to_admin)
        else:
            await call.message.answer(message_to_admin)

        # await call.message.delete()
        await bot.send_message(chat_id=user_telegram_id, text=message_to_user)

    except Exception as e:
        print(f"To'lovni tasdiqlashda xatolik: {e}")
        await call.message.answer(_("❗️ Xatolik yuz berdi, iltimos keyinroq urinib ko'ring."))


@dp.callback_query_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), lambda c: "rejection" in c.data)
async def confirm_payment_message_handler(call: types.CallbackQuery, state: FSMContext):
    split_data = call.data.split(":")
    user_telegram_id = split_data[1]
    photo_message_id = split_data[2]

    await state.update_data(photo_message_id=photo_message_id)
    await state.update_data(user_telegram_id=user_telegram_id)

    user = get_user(telegram_id=user_telegram_id)

    if not user:
        return

    send_message_text = await call.message.answer(_("❗️ To'lov chekini bekor qilish uchun, shu xabarga reply qilib sababini yozing!"))
    await state.update_data(send_message_id=send_message_text.message_id)
    await state.update_data(user_telegram_id=user_telegram_id)


@dp.message_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), content_types=types.ContentType.TEXT)
async def confirm_payment_message_handler(message: types.Message, state: FSMContext):
    if not message.reply_to_message:
        return

    state_data = await state.get_data()
    send_message_id = state_data.get("send_message_id")
    photo_message_id = state_data.get("photo_message_id")
    user_telegram_id = state_data.get("user_telegram_id")

    if not user_telegram_id or str(send_message_id) != str(message.reply_to_message.message_id):
        return

    user = get_user(telegram_id=user_telegram_id)

    await bot.send_message(
        chat_id=user_telegram_id,
        text=message.text,
        reply_markup=send_receipt_button
    )
    username_or_telegram_id = f"""<a href="https://{user.username}.t.me">@{user.username}</a>""" if user.username else user.telegram_id
    message_to_admin = _(f"""❌To'lov bekor qilindi!\n👤FISH: {user.full_name}[{username_or_telegram_id}]\n💡Sabab: {message.text}\n\n#unpaid #monthly""")

    try:
        if photo_message_id:
            await bot.edit_message_caption(
                caption=message_to_admin,
                chat_id=ADMIN_GROUP_ID,
                message_id=photo_message_id,
                reply_markup=None
            )
        else:
            await message.answer(message_to_admin)

        await bot.delete_message(chat_id=ADMIN_GROUP_ID, message_id=send_message_id)
        await message.delete()

    except Exception as e:
        print(f"Xatolik: {e}")
        await message.answer(message_to_admin)

    await message.answer(_("✅ Bekor qilish sababi foydalanuvchiga yuborildi."))
