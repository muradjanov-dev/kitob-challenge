import string
import random
import requests
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from asgiref.sync import sync_to_async
from tgbot.models import UserReferal, TelegramProfile
from tgbot.bot.loader import bot
from tgbot.bot.consts import ADMIN_GROUP_ID, TECHNICAL_SUPPORT_THREAD_ID, REFERRAL_CODE_LENGTH


def _send_telegram_message(chat_id, text, thread_id=None, parse_mode="HTML"):
    """Plain HTTP send, deliberately NOT going through the aiogram `bot`
    object. process_referral() is invoked both from the bot's own event loop
    (report.py chat flow) and, via async_to_sync, from a Django sync view's
    thread-pool loop (report_views.py web flow). aiogram's Bot lazily binds
    its aiohttp ClientSession/connector to whichever loop first touches it,
    so a second, different loop touching it later intermittently blows up
    with "Timeout context manager should be used inside a task". A bare
    requests.post has no loop affinity and sidesteps that -- same fix already
    used by tgbot/tasks.py's send_message() for the same reason."""
    url = f"https://api.telegram.org/bot{settings.API_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if thread_id:
        data["message_thread_id"] = thread_id
    requests.post(url, data=data, timeout=10).raise_for_status()


class ReferralService:
    @staticmethod
    async def get_or_create_code(user: TelegramProfile) -> str:
        """
        Generates or retrieves a unique referral code for the user.
        Uses a simple random string generation strategy with collision check.
        """
        if user.referral_code:
            return user.referral_code

        chars = string.ascii_letters + string.digits

        # Wrapped in sync_to_async for DB operations inside the loop
        @sync_to_async
        def _generate_and_save():
            while True:
                code = ''.join(random.choice(chars)
                               for _ in range(REFERRAL_CODE_LENGTH))
                if not TelegramProfile.objects.filter(referral_code=code).exists():
                    user.referral_code = code
                    user.save(update_fields=['referral_code'])
                    return code

        return await _generate_and_save()

    @staticmethod
    async def get_referral_link(user: TelegramProfile) -> str:
        """
        Returns the full referral link for the user.
        """
        code = await ReferralService.get_or_create_code(user)
        bot_username = (await bot.get_me()).username
        return f"https://t.me/{bot_username}?start={code}"

    @staticmethod
    async def get_referral_count(user: TelegramProfile) -> int:
        """
        Returns the number of successful referrals for the user.
        """
        return await sync_to_async(UserReferal.objects.filter(referrer=user).count)()

    @staticmethod
    async def get_referral_list(user: TelegramProfile, limit: int = 50):
        """Names + join dates of the people this user has invited (newest
        first). Only confirmed referrals appear — UserReferal rows are created
        once the invitee submits their first report."""
        @sync_to_async
        def _fetch():
            qs = (
                UserReferal.objects
                .filter(referrer=user)
                .select_related("referred_user")
                .order_by("-created_at")
            )
            return [
                (
                    (r.referred_user.full_name if r.referred_user else None) or "Foydalanuvchi",
                    r.referred_user.telegram_id if r.referred_user else None,
                    r.created_at,
                )
                for r in qs[:limit]
            ]
        return await _fetch()

    @staticmethod
    async def process_referral(user: TelegramProfile, referral_code: str):
        """
        Validates and processes a new referral.
        Returns True if referral was created, False otherwise.
        """
        if not referral_code:
            return False

        # Only count after the invited user has fully completed registration.
        if not getattr(user, "is_registered", False):
            return False

        # Check if already referred
        is_already_referred = await sync_to_async(UserReferal.objects.filter(referred_user=user).exists)()
        if is_already_referred:
            return False

        # Get referrer
        referrer = await sync_to_async(TelegramProfile.objects.filter(referral_code=referral_code).first)()

        # Self-referral check
        if not referrer or referrer.telegram_id == user.telegram_id:
            return False

        # Create record
        await sync_to_async(UserReferal.objects.create)(
            referrer=referrer,
            referred_user=user
        )

        # Count referrals AFTER creating this one
        ref_count = await sync_to_async(
            UserReferal.objects.filter(referrer=referrer).count
        )()

        # Award rewards to referrer
        @sync_to_async
        def _award(count):
            from tgbot.models import Payment
            from django.utils import timezone as _tz

            # Growing reward: 20, 25, 30, ... (+5 per invite) until cumulative >= 1000, then flat 50
            # S(n) = 20n + 5*n*(n-1)/2; first n where S(n) >= 1000 is n=17 (S(17)=1020)
            BREAKPOINT = 17
            if count <= BREAKPOINT:
                base_kitobcha = 20 + 5 * (count - 1)
            else:
                base_kitobcha = 50
            # update_ball returns the actually-applied amount (doubled for premium).
            actually_awarded = referrer.update_ball(True, base_kitobcha)

            # Every 3rd invite = 1 day premium
            if count % 3 == 0:
                today = _tz.localdate()
                active = Payment.objects.filter(
                    user=referrer, status="paid", end_date__gte=today
                ).first()
                if active:
                    active.end_date = active.end_date + timedelta(days=1)
                    active.save(update_fields=["end_date"])
                else:
                    Payment.objects.create(
                        user=referrer,
                        amount=0,
                        start_date=today,
                        end_date=today + timedelta(days=1),
                        status="paid",
                    )
            return actually_awarded

        awarded_kitobcha = await _award(ref_count)

        # Referral BOOM bonus — only for users who joined the live boom event.
        boom_payload = await ReferralService._award_boom_bonus(referrer)

        # Notify parties
        await ReferralService._notify_admin(referrer, user, referral_code)
        await ReferralService._notify_referrer(referrer, user, ref_count, awarded_kitobcha)
        if boom_payload:
            await ReferralService._notify_boom_payout(referrer, boom_payload)

        # Re-evaluate the REFERRER's referral-milestone achievements now that
        # they've gained one. Without this, rf_5 / rf_20 / rf_50 ("o'rmon") /
        # rf_100 only unlock the next time the referrer submits their own
        # report — so an active inviter who never reads wouldn't get them.
        try:
            from tgbot.tasks import check_user_achievements
            check_user_achievements.delay(referrer.id)
        except Exception as e:
            print(f"referrer achievement check dispatch failed: {e}")

        return True

    @staticmethod
    @sync_to_async
    def _award_boom_bonus(referrer: TelegramProfile):
        """If a Referral BOOM is live, award `referrer` the tiered per-referral
        bonus -- EVERY referral during the boom's window counts, whether or not
        the referrer ever tapped "join" on the announcement; join only affects
        whether they got the welcome DM + drip reminders. Returns a dict for
        the payout DM, or None."""
        from tgbot.models import ReferralBoom, ReferralBoomParticipant
        from tgbot.services.referral_boom import generate_daily_reminder_schedule
        from django.db import transaction as _txn

        boom = ReferralBoom.objects.filter(is_active=True).order_by("-created_at").first()
        if not boom or not boom.is_live():
            return None

        with _txn.atomic():
            participant, created = (
                ReferralBoomParticipant.objects
                .select_for_update()
                .get_or_create(boom=boom, user=referrer)
            )
            if created:
                participant.reminder_schedule = generate_daily_reminder_schedule(
                    timezone.now(), boom.end_at,
                )
                participant.save(update_fields=["reminder_schedule"])

            referral_number = participant.referrals_count + 1
            base_reward = boom.reward_for(referral_number)
            # Promotional guarantee: whoever brings in at least 1 referral gets
            # topped up to 500 Kitobcha for that first one specifically (the
            # ongoing per-referral tier1 rate is lower) -- a floor, not a
            # multiplier, so it only ever raises the first referral's payout.
            if referral_number == 1:
                base_reward = max(base_reward, 500)
            # update_ball applies the premium 2× multiplier consistently with the
            # rest of the economy and returns the amount actually credited.
            awarded = referrer.update_ball(True, base_reward)

            participant.referrals_count = referral_number
            participant.kitobcha_earned = participant.kitobcha_earned + awarded
            participant.save(update_fields=["referrals_count", "kitobcha_earned"])

            referrer.refresh_from_db(fields=["ball"])
            return {
                "boom": boom,
                "referral_number": referral_number,
                "awarded": awarded,
                "total_earned": participant.kitobcha_earned,
                "balance": int(referrer.ball or 0),
            }

    @staticmethod
    async def _notify_boom_payout(referrer: TelegramProfile, payload: dict):
        try:
            from tgbot.services.referral_boom import build_payout_text
            text = build_payout_text(
                payload["boom"],
                payload["referral_number"],
                payload["awarded"],
                payload["total_earned"],
                payload["balance"],
            )
            await sync_to_async(_send_telegram_message)(referrer.telegram_id, text)
        except Exception as e:
            print(f"Failed to send boom payout DM ({referrer.telegram_id}): {e}")

    @staticmethod
    async def _notify_admin(referrer: TelegramProfile, new_user: TelegramProfile, code: str):
        try:
            notification_msg = (
                f"🆕 <b>Yangi Referal!</b>\n\n"
                f"👤 <b>Taklif qiluvchi:</b> {referrer.full_name} ({referrer.telegram_id})\n"
                f"👤 <b>Yangi a'zo:</b> {new_user.full_name} ({new_user.telegram_id})\n"
                f"🔗 <b>Kod:</b> {code}"
            )
            await sync_to_async(_send_telegram_message)(
                ADMIN_GROUP_ID, notification_msg, thread_id=TECHNICAL_SUPPORT_THREAD_ID,
            )
        except Exception as e:
            print(f"Failed to send referral notification to admin: {e}")

    @staticmethod
    async def _notify_referrer(referrer: TelegramProfile, new_user: TelegramProfile, ref_count: int = 0, awarded_kitobcha: int = 0):
        try:
            BREAKPOINT = 17
            if ref_count <= BREAKPOINT:
                base_kitobcha = 20 + 5 * (ref_count - 1)
            else:
                base_kitobcha = 50
            display_amount = awarded_kitobcha if awarded_kitobcha else base_kitobcha
            premium_note = " 💎 ×2 premium!" if awarded_kitobcha and awarded_kitobcha > base_kitobcha else ""
            reward_lines = [f"🪙 <b>+{display_amount} Kitobcha</b> qo'shildi!{premium_note}"]
            if ref_count % 3 == 0:
                reward_lines.append(f"💎 <b>+1 kun Premium</b> qo'shildi! (har 3 ta taklif)")

            referrer_notification = (
                f"🎉 <b>Yangi Referal!</b>\n\n"
                f"👤 <b>Yangi a'zo:</b> {new_user.full_name}\n"
                f"🆔 <b>ID:</b> <code>{new_user.telegram_id}</code>\n"
                f"📊 <b>Jami referallar:</b> {ref_count}\n\n"
                + "\n".join(reward_lines)
            )
            await sync_to_async(_send_telegram_message)(referrer.telegram_id, referrer_notification)
        except Exception as e:
            print(
                f"Failed to send notification to referrer ({referrer.telegram_id}): {e}")
