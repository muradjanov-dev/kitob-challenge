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

from tgbot.bot.filters import IsPrivate
from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.services.referral_boom import (
    generate_daily_reminder_schedule,
    build_welcome_text,
    boom_share_texts,
    humanize_left,
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

    from tgbot.services.referral import ReferralService
    referral_link = await ReferralService.get_referral_link(user)
    share_text = _urlquote(random.choice(boom_share_texts(user.full_name, boom.title)))
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
        "📤 Do'stlarga ulashish",
        url=f"https://t.me/share/url?url={_urlquote(referral_link)}&text={share_text}",
    ))

    if status == "already":
        # They tapped "join" again -- the toast alone doesn't show the actual
        # link anywhere they can copy/tap, so resend it as a real message
        # (not just the welcome DM, which only ever sends once). Body text
        # rotates through the same ~20-variant creative pool as the share
        # button, not a fixed line, so repeat taps don't look copy-pasted.
        await call.answer(f"✅ Siz allaqachon {boom.title}'da qatnashyapsiz!", show_alert=False)
        blurb = random.choice(boom_share_texts(user.full_name, boom.title))
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"🔗 <b>Sizning shaxsiy havolangiz:</b>\n{referral_link}\n\n"
                    f"{blurb}"
                ),
                parse_mode="HTML", disable_web_page_preview=True,
                reply_markup=kb,
            )
        except Exception as e:
            print(f"boom link resend failed uid={user.id}: {e}")
        return

    await call.answer(f"🎉 {boom.title}'ga qo'shildingiz!", show_alert=False)

    # Build the once-only welcome + rules + personal link, then DM it. The
    # full rules copy (rewards + TOP-3 prizes + link) regularly exceeds
    # Telegram's 1024-char photo-caption cap, so the image (if any) is sent
    # on its own with no caption, followed by the rules as a normal text
    # message (4096-char cap) with the share button -- caption+text used to
    # be combined into one send_photo call, which silently failed outright
    # (Message_too_long) the moment the caption crossed 1024 chars, so
    # affected users never got their rules/link DM at all.
    text = build_welcome_text(user.full_name, boom, referral_link)
    try:
        if boom.image:
            await bot.send_photo(chat_id=user.telegram_id, photo=types.InputFile(boom.image.path))
        await bot.send_message(
            chat_id=user.telegram_id, text=text,
            parse_mode="HTML", disable_web_page_preview=True,
            reply_markup=kb,
        )
        await _mark_rules_sent(user, boom_id)
    except Exception as e:
        print(f"boom welcome DM failed uid={user.id}: {e}")


@sync_to_async
def _boom_stats_for(user):
    """Rank + numbers for `user` in the currently-live boom (auto-enrolls
    them as a participant with 0 referrals if they aren't one yet, so the
    stats view always has something to show, even for someone who's never
    referred anyone). Returns (boom, rank, total_participants, referrals,
    kitobcha_earned) or None if no boom is live."""
    from tgbot.models import ReferralBoom, ReferralBoomParticipant

    boom = ReferralBoom.objects.filter(is_active=True).order_by("-created_at").first()
    if not boom:
        return None

    participant, _created = ReferralBoomParticipant.objects.get_or_create(boom=boom, user=user)
    ranked = list(
        ReferralBoomParticipant.objects.filter(boom=boom)
        .order_by("-referrals_count", "joined_at")
        .values_list("user_id", flat=True)
    )
    rank = ranked.index(user.id) + 1 if user.id in ranked else len(ranked)
    return boom, rank, len(ranked), participant.referrals_count, participant.kitobcha_earned


@dp.message_handler(IsPrivate(), regexp=r"^🌟 ", state="*")
async def boom_stats_button(message: types.Message, state: FSMContext):
    """Persistent reply-keyboard button (report_reply_keyboard) shown while a
    boom is live: full personal stats + the referral link + a rotating
    share blurb, in one tap."""
    user = await aget_user(message.from_user.id)
    if not user or not user.is_registered:
        return

    result = await _boom_stats_for(user)
    if not result:
        return
    boom, rank, total, referrals, kitobcha = result

    from tgbot.services.referral import ReferralService
    referral_link = await ReferralService.get_referral_link(user)
    days_left_str = humanize_left(boom.end_at)
    blurb = random.choice(boom_share_texts(user.full_name, boom.title))
    share_text = _urlquote(blurb)
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
        "📤 Do'stlarga ulashish",
        url=f"https://t.me/share/url?url={_urlquote(referral_link)}&text={share_text}",
    ))
    text = (
        f"🌟 <b>{boom.title}</b>\n\n"
        f"📍 O'rningiz: <b>#{rank}</b> / {total}\n"
        f"👥 Takliflaringiz: <b>{referrals}</b> ta\n"
        f"🪙 Yig'ilgan: <b>{kitobcha} Kitobcha</b>\n"
        f"⏳ Qolgan vaqt: <b>{days_left_str}</b>\n\n"
        f"🔗 <b>Sizning shaxsiy havolangiz:</b>\n{referral_link}\n\n"
        f"{blurb}"
    )
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)


@sync_to_async
def _is_admin_sync(telegram_id):
    from tgbot.bot.utils import is_admin_id_sync
    return is_admin_id_sync(telegram_id)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("boom_finalize_confirm:"), state="*")
async def boom_finalize_confirm_cb(call: types.CallbackQuery, state: FSMContext = None):
    """Admin taps 'Yakunlash' on the finalize-confirmation DM (sent once the
    boom's window has closed) -- only then does the real finalize (tallies,
    participant DMs, admin summary) actually run."""
    if not await _is_admin_sync(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    boom_id = int(call.data.split(":", 1)[1])
    await call.answer("Yakunlanmoqda…")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    from tgbot.tasks import finalize_referral_boom
    await sync_to_async(finalize_referral_boom)(boom_id, force=True)
    await call.message.answer("✅ Musobaqa yakunlandi — ishtirokchilarga yakuniy hisobot yuborildi.")
