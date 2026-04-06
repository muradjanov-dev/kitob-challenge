from aiogram import types
from aiogram.dispatcher import FSMContext

from tgbot.bot.loader import dp
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="Qo'llov 💸", state="*")
async def donation_message_handler(message: types.Message, state: FSMContext):
    await message.answer(
        text="""Botga Kitob Challenge loyihasini qo'llab-quvvatlang! 📚
Saviyali kitobxonlarni ko'payishi uchun loyihani
~1.000 so'm/oylik bilan qo'llab-quvvatlashingiz mumkin (ixtiyoriy):

💳 9860 1766 0132 6737
📌 (N. Murodjonov)

Himmat qilsangiz ham bo'ladi! 😊
"""
    )