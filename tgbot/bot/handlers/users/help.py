from aiogram import types
from aiogram.dispatcher.filters.builtin import Command

from tgbot.bot.loader import dp, bot
from django.conf import settings


@dp.message_handler(Command("yordam"), state="*")
async def bot_help(message: types.Message):
    # provider_token = settings.PROVIDER_TOKEN
    # await bot.send_invoice(chat_id=631751797, title="test_title", description="test_description", provider_token=provider_token,
    #                        payload="payload", currency="UZS", prices=[{"label": "Subscription", "amount": 5000000}],
    #                        need_name=True, need_email=True, need_phone_number=True,)
    text = "Savollaringiz yoki takliflaringiz bo'lsa, ➡️ @roboteachhelp ⬅️ga murojaat qiling!"
    await message.answer(text)


