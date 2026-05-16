from datetime import datetime
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType

from tgbot.bot.utils import aget_user
from tgbot.bot.states.main import SendMessageInBot
from tgbot.bot.loader import dp, bot, gettext as _
from tgbot.bot.keyboards.reply import main_markup, back_keyboard
from tgbot.bot.keyboards.inline import send_message_type, send_answer_to_question
from tgbot.bot.consts import ADMIN_GROUP_ID, MESSAGE_THREAD_ID, TECHNICAL_SUPPORT_THREAD_ID


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="📞 Напишите администратору", state="*")
@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="📞 Adminga bilan bog'lanish", state="*")
async def send_message_from_bot_handler(message: types.Message, state: FSMContext):
    await message.answer(_("📨 Xabaringiz mazmunini quyidan tanlang:"), reply_markup=send_message_type)
    await SendMessageInBot.content.set()


@dp.callback_query_handler(state=SendMessageInBot.content)
async def send_message_from_bot_handler(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(telegram_id=call.from_user.id)
    content = call.data
    if content == "cancel":
        await call.message.answer(_("Asosiy oyna"), reply_markup=main_markup(language=user.language))
        await state.finish()
        await call.message.delete()
        return

    await state.update_data(content=call.data)
    await call.message.answer(_("✍️ Yaxshi, quyida xabaringizni kiriting\n\nXabar rasm, video, fayl, ovozli xabar ko'rinishda bo'lishi mumkin!"), reply_markup=back_keyboard)
    await SendMessageInBot.message.set()
    await call.message.delete()


@dp.message_handler(state=SendMessageInBot.message, content_types=types.ContentType.ANY)
async def send_message_from_bot_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    content = data.get("content")
    user = await aget_user(telegram_id=message.from_user.id)

    thread_id = MESSAGE_THREAD_ID
    if content == "technical":
        thread_id = TECHNICAL_SUPPORT_THREAD_ID

    try:
        username_or_telegram_id = f"""<a href="https://{user.username}.t.me">@{user.username}</a>""" if user.username else user.telegram_id
        text = _(
            f"Xabar yuboruvchi: {user.full_name}[{username_or_telegram_id}]")

        user_message = await message.forward(chat_id=ADMIN_GROUP_ID, message_thread_id=thread_id)
        reply_button = await send_answer_to_question(user.telegram_id)

        await user_message.reply(text=text, reply_markup=reply_button, disable_web_page_preview=True)

        await message.reply(_("✅ Xabaringiz muvaffaqiyatli yuborildi!\n\nTez orada sizga javob beramiz."), reply_markup=main_markup(language=user.language))

    except Exception as e:
        print(f"Xabarni jo‘natishda xatolik yuz berdi: {e}")
        await message.reply(_(f"❌ Xabarni jo‘natishda xatolik yuz berdi!\nBirozdan keyin qayta urinib ko‘ring."))
    await state.finish()
