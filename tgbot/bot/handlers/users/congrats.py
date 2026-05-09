"""Tabriklash inline-button flow.

When a user clicks 🎉 Tabriklash on a broadcast DM (sent by
broadcast_congrats_to_others), this module:

    1. Records a Congratulation row (idempotent — one per user/event).
    2. Sends an ephemeral 1-minute message back to the clicker with the
       count of people who congratulated BEFORE them.
    3. Sends a 12-hour-TTL DM to the achiever ("kim sizni tabrikladi").
    4. Disables the Tabriklash button on the clicker's message.
"""
from aiogram import types
from aiogram.dispatcher import FSMContext
from asgiref.sync import sync_to_async
from django.utils import timezone
from html import escape

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import get_user
from tgbot.models import (
    UserAchievement, Congratulation, ScheduledMessageDeletion,
    TelegramProfile,
)


@sync_to_async
def _record_congrats(ua_id: int, congratulator_id: int):
    """Returns (created, count_before, achiever_telegram_id, achiever_full_name,
    achievement_code)."""
    ua = UserAchievement.objects.filter(id=ua_id).select_related("user").first()
    if not ua:
        return False, 0, None, None, None
    obj, created = Congratulation.objects.get_or_create(
        achievement=ua, congratulator_id=congratulator_id,
    )
    count = Congratulation.objects.filter(achievement=ua).count()
    count_before = max(count - 1, 0) if created else count
    return (
        created, count_before,
        ua.user.telegram_id, ua.user.full_name or "Kitobxon",
        ua.code,
    )


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

    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing", show_alert=True)
        return

    created, count_before, achiever_tg_id, achiever_name, ach_code = (
        await _record_congrats(ua_id, user.id)
    )
    if achiever_tg_id is None:
        await call.answer("❌ Yutuq topilmadi", show_alert=True)
        return

    if not created:
        await call.answer("Siz allaqachon tabrikladingiz 🙂", show_alert=True)
        return

    # 1) Ephemeral 1-min count message to the clicker.
    try:
        ephemeral_text = (
            f"🎉 <b>Rahmat! Siz tabrikladingiz.</b>\n\n"
            f"Sizdan oldin <b>{count_before}</b> kishi tabriklagan.\n\n"
            "<i>Bu xabar 1 daqiqadan keyin avtomatik o'chiriladi.</i>"
        )
        sent = await bot.send_message(
            chat_id=user.telegram_id, text=ephemeral_text, parse_mode="HTML",
        )
        try:
            await sync_to_async(ScheduledMessageDeletion.objects.create)(
                chat_id=user.telegram_id,
                message_id=sent.message_id,
                delete_at=timezone.now() + timezone.timedelta(minutes=1),
            )
        except Exception as e:
            print(f"congrats: ephemeral schedule failed: {e}")
    except Exception as e:
        print(f"congrats: ephemeral send failed: {e}")

    # 2) 12-hour TTL DM to the achiever.
    try:
        from tgbot.services.achievements import find_achievement
        ach = find_achievement(ach_code) or {}
        title = ach.get("title_uz") or ach_code
        emoji = ach.get("emoji", "🏆")
        congratulator_name = escape(user.full_name or user.username or "Kitobxon")
        achiever_text = (
            f"🎉 <b>Sizni tabrikladilar!</b>\n\n"
            f"<b>{congratulator_name}</b> sizni "
            f"<b>{emoji} {title}</b> yutug'ingiz bilan tabrikladi.\n\n"
            "Davom etamiz! 🚀\n\n"
            "<i>Bu xabar 12 soatdan keyin avtomatik o'chiriladi.</i>"
        )
        sent2 = await bot.send_message(
            chat_id=achiever_tg_id, text=achiever_text, parse_mode="HTML",
        )
        try:
            await sync_to_async(ScheduledMessageDeletion.objects.create)(
                chat_id=achiever_tg_id,
                message_id=sent2.message_id,
                delete_at=timezone.now() + timezone.timedelta(hours=12),
            )
        except Exception as e:
            print(f"congrats: achiever schedule failed: {e}")
    except Exception as e:
        print(f"congrats: achiever DM failed: {e}")

    # 3) Disable the button on the broadcast DM so user can't click twice.
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await call.answer("✅ Tabriklash yuborildi!")
