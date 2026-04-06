from aiogram import types
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType
from aiogram.dispatcher import FSMContext

from tgbot.bot.loader import dp, bot, gettext as _
from tgbot.models import Payment
from tgbot.bot.utils import get_user
from tgbot.bot.keyboards.reply import main_markup
from tgbot.bot.handlers.users.habit_notification import MONTHLY_PAYMENT
from tgbot.bot.consts import ADMIN_GROUP_ID
from tgbot.bot.states.main import AnswerMessageState


@dp.callback_query_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), lambda c: "send_answer" in c.data)
async def send_answer_to_user(call: types.CallbackQuery, state: FSMContext):
    split_data = call.data.split(":")
    user_telegram_id = split_data[1]
    await call.message.edit_reply_markup(reply_markup=None)

    user = get_user(telegram_id=user_telegram_id)

    if not user:
        return

    await state.update_data(user_telegram_id=user_telegram_id)
    await call.message.answer(_("✍️ Javobingizni kiriting:"))
    await AnswerMessageState.message.set()


@dp.message_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), content_types=types.ContentType.ANY, state=AnswerMessageState.message)
async def confirm_payment_message_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_telegram_id = data.get("user_telegram_id")
    user = get_user(telegram_id=user_telegram_id)
    try:
        username_or_telegram_id = f"""<a href="https://{user.username}.t.me">@{user.username}</a>""" if user.username else user.telegram_id
        await message.copy_to(chat_id=user.telegram_id, reply_markup=main_markup(user.language))
        await message.answer(f"✅ Xabar {user.full_name}[{username_or_telegram_id}]'ga muvaffaqiyatli yuborildi!", disable_web_page_preview=True)
    except Exception as e:
        print(f"guruhdan userga xabarni yuborishda xatolik yuz berdi: {e}")
        await message.answer(_("❌ Xabarni yuborishda xatolik yuz berdi!"))
    await state.finish()
