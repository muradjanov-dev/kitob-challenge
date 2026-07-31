"""Referral BOOM — join flow. Clicking the announcement button enrolls the
user, then the bot DMs their personal referral link + rules exactly once and
seeds the playful reminder schedule for the rest of the window."""
import random
from urllib.parse import quote as _urlquote

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.utils import timezone

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.services.referral_boom import (
    generate_daily_reminder_schedule,
    build_welcome_text,
    boom_share_texts,
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

    schedule = generate_daily_reminder_schedule(timezone.now(), boom.end_at)
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
        await call.answer("❌ Bu musobaqa tugagan yoki mavjud emas.", show_alert=True)
        return
    if status == "already":
        await call.answer(f"✅ Siz allaqachon {boom.title}'da qatnashyapsiz! Havolangizni ulashing 🔗", show_alert=True)
        return

    await call.answer(f"🎉 {boom.title}'ga qo'shildingiz!", show_alert=False)

    # Build the once-only welcome + rules + personal link, then DM it. If the
    # boom has an image configured, it's sent as a photo with this same text
    # as the caption (Telegram's 1024-char caption cap — the rules copy is
    # short enough in practice to fit; a caption that somehow doesn't would
    # just fail the send, logged below, same as any other delivery error).
    from tgbot.services.referral import ReferralService
    referral_link = await ReferralService.get_referral_link(user)
    text = build_welcome_text(user.full_name, boom, referral_link)
    share_text = _urlquote(random.choice(boom_share_texts(user.full_name, boom.title)))
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
        "📤 Do'stlarga ulashish",
        url=f"https://t.me/share/url?url={_urlquote(referral_link)}&text={share_text}",
    ))
    try:
        if boom.image:
            await bot.send_photo(
                chat_id=user.telegram_id, photo=types.InputFile(boom.image.path),
                caption=text, parse_mode="HTML", reply_markup=kb,
            )
        else:
            await bot.send_message(
                chat_id=user.telegram_id, text=text,
                parse_mode="HTML", disable_web_page_preview=True,
                reply_markup=kb,
            )
        await _mark_rules_sent(user, boom_id)
    except Exception as e:
        print(f"boom welcome DM failed uid={user.id}: {e}")
