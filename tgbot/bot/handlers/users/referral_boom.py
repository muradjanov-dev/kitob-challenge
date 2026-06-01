"""Referral BOOM — join flow. Clicking the announcement button enrolls the
user, then the bot DMs their personal referral link + rules exactly once and
seeds the playful reminder schedule for the rest of the window."""
from aiogram import types
from aiogram.dispatcher import FSMContext
from asgiref.sync import sync_to_async
from django.utils import timezone

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.services.referral_boom import (
    generate_reminder_schedule,
    build_welcome_text,
)

# NB: ReferralService is imported lazily inside the handler — importing it at
# module level creates a circular import (referral.py → bot.loader → handlers).


@sync_to_async
def _join_boom(user, boom_id):
    """get_or_create the participant. Returns (boom, status) where status is one
    of 'expired' | 'already' | 'joined'. On 'joined' the reminder schedule is
    seeded (welcome DM is sent by the caller, then rules_sent flipped)."""
    from tgbot.models import ReferralBoom, ReferralBoomParticipant

    boom = ReferralBoom.objects.filter(id=boom_id, is_active=True).first()
    if not boom or not boom.is_live():
        return None, "expired"

    participant, created = ReferralBoomParticipant.objects.get_or_create(
        boom=boom, user=user,
    )
    if not created:
        return boom, "already"

    schedule = generate_reminder_schedule(
        timezone.now(), boom.end_at, boom.total_reminders,
    )
    participant.reminder_schedule = schedule
    participant.save(update_fields=["reminder_schedule"])
    return boom, "joined"


@sync_to_async
def _mark_rules_sent(user, boom_id):
    from tgbot.models import ReferralBoomParticipant
    ReferralBoomParticipant.objects.filter(
        boom_id=boom_id, user=user,
    ).update(rules_sent=True)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("join_boom:"), state="*")
async def join_boom_handler(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user or not user.is_registered:
        await call.answer("Avval /start bosib ro'yxatdan o'ting.", show_alert=True)
        return

    boom_id = int(call.data.split(":")[1])
    boom, status = await _join_boom(user, boom_id)

    if status == "expired":
        await call.answer("❌ Bu BOOM tugagan yoki mavjud emas.", show_alert=True)
        return
    if status == "already":
        await call.answer("✅ Siz allaqachon BOOM'da qatnashyapsiz! Havolangizni ulashing 🔗", show_alert=True)
        return

    await call.answer("🎉 BOOM'ga qo'shildingiz!", show_alert=False)

    # Build the once-only welcome + rules + personal link, then DM it.
    from tgbot.services.referral import ReferralService
    referral_link = await ReferralService.get_referral_link(user)
    text = build_welcome_text(user.full_name, boom, referral_link)
    try:
        await bot.send_message(
            chat_id=user.telegram_id, text=text,
            parse_mode="HTML", disable_web_page_preview=True,
        )
        await _mark_rules_sent(user, boom_id)
    except Exception as e:
        print(f"boom welcome DM failed uid={user.id}: {e}")
