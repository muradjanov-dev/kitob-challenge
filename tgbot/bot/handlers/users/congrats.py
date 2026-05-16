"""Tabriklash inline-button flow.

When a user clicks 🎉 Tabriklash on a broadcast DM:
    1. Records a Congratulation row (idempotent — one per user/event).
    2. Updates the button on the clicker's message to show live count.
    3. Shows a brief inspiring toast to the clicker (auto-disappears ~3 s).
    4. Deletes the congrats message from the clicker's DM after 1 minute
       (keeps the DM clean — user already saw it).
"""
import asyncio
import random

from aiogram import types
from aiogram.dispatcher import FSMContext
from asgiref.sync import sync_to_async

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.models import UserAchievement, Congratulation


_CONGRATS_TOASTS = [
    "Tabrikladingiz! 🎉",
    "Yana bir kitobxonga ilhom berdingiz! ✨",
    "Qo'llab-quvvatladingiz! 💪",
    "Bir tabrik — mingta kuch! Kitobxonni ruhlantirdingiz 🌟",
    "Hamjihatlik — gala kuchi! Rahmat sizga! ⚡",
    "Sizning tabrigingiz ularni oldinga undaydi! 🚀",
    "Barakalla! Birga o'samiz! 🌱",
    "Sizning qo'llab-quvvatlashingiz bebaho! 🏆",
    "Bir so'z — katta motivatsiya! 🔥",
    "Kitobxonlar bir-birini ko'taradi! 📚",
]


@sync_to_async
def _record_congrats(ua_id: int, congratulator_id: int):
    """Returns (created, count_total, achiever_telegram_id)."""
    ua = UserAchievement.objects.filter(id=ua_id).select_related("user").first()
    if not ua:
        return False, 0, None
    _, created = Congratulation.objects.get_or_create(
        achievement=ua, congratulator_id=congratulator_id,
    )
    count = Congratulation.objects.filter(achievement=ua).count()
    return created, count, ua.user.telegram_id


async def _delete_message_after(chat_id: int, message_id: int, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("congrats:"),
    state="*",
)
async def congrats_handler(call: types.CallbackQuery, state: FSMContext):
    if call.message and call.message.chat.type != types.ChatType.PRIVATE:
        await call.answer()
        return

    try:
        ua_id = int(call.data.split(":", 1)[1])
    except Exception:
        await call.answer()
        return

    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing", show_alert=True)
        return

    created, count_total, achiever_tg_id = await _record_congrats(ua_id, user.id)

    if achiever_tg_id is None:
        await call.answer("❌ Yutuq topilmadi", show_alert=True)
        return

    if not created:
        await call.answer(
            f"Siz allaqachon tabrikladingiz 🙂  (Jami: {count_total} ta tabriklash)",
            show_alert=True,
        )
        return

    # Update button to show live congrats count.
    try:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        new_kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton(
                text=f"🎉 Tabriklash ({count_total})",
                callback_data=f"congrats:{ua_id}",
            )
        )
        await call.message.edit_reply_markup(reply_markup=new_kb)
    except Exception:
        pass

    # Brief inspiring toast (auto-disappears in ~3 s, no modal).
    await call.answer(random.choice(_CONGRATS_TOASTS))

    # Delete the congrats DM 1 minute after clicking — keeps chat clean.
    asyncio.create_task(
        _delete_message_after(call.message.chat.id, call.message.message_id, delay=60)
    )
