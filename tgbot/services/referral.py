import string
import random
from datetime import timedelta
from asgiref.sync import sync_to_async
from tgbot.models import UserReferal, TelegramProfile
from tgbot.bot.loader import bot
from tgbot.bot.consts import ADMIN_GROUP_ID, TECHNICAL_SUPPORT_THREAD_ID, REFERRAL_CODE_LENGTH


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
    async def process_referral(user: TelegramProfile, referral_code: str):
        """
        Validates and processes a new referral.
        Returns True if referral was created, False otherwise.
        """
        if not referral_code:
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

            # Base reward: 90 Kitobcha per referral
            referrer.update_ball(True, 90)

            # Milestone bonus: +500 Kitobcha on every 10th referral
            if count % 10 == 0:
                referrer.update_ball(True, 500)

            # Premium grant: +3 days on every 20th referral
            if count % 20 == 0:
                today = _tz.localdate()
                active = Payment.objects.filter(
                    user=referrer, status="paid", end_date__gte=today
                ).first()
                if active:
                    active.end_date = active.end_date + timedelta(days=3)
                    active.save(update_fields=["end_date"])
                else:
                    Payment.objects.create(
                        user=referrer,
                        amount=0,
                        start_date=today,
                        end_date=today + timedelta(days=3),
                        status="paid",
                    )

        await _award(ref_count)

        # Notify parties
        await ReferralService._notify_admin(referrer, user, referral_code)
        await ReferralService._notify_referrer(referrer, user, ref_count)

        return True

    @staticmethod
    async def _notify_admin(referrer: TelegramProfile, new_user: TelegramProfile, code: str):
        try:
            notification_msg = (
                f"🆕 <b>Yangi Referal!</b>\n\n"
                f"👤 <b>Taklif qiluvchi:</b> {referrer.full_name} ({referrer.telegram_id})\n"
                f"👤 <b>Yangi a'zo:</b> {new_user.full_name} ({new_user.telegram_id})\n"
                f"🔗 <b>Kod:</b> {code}"
            )
            await bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=notification_msg,
                message_thread_id=TECHNICAL_SUPPORT_THREAD_ID,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Failed to send referral notification to admin: {e}")

    @staticmethod
    async def _notify_referrer(referrer: TelegramProfile, new_user: TelegramProfile, ref_count: int = 0):
        try:
            reward_lines = [f"🪙 <b>+90 Kitobcha</b> qo'shildi!"]
            if ref_count % 10 == 0:
                reward_lines.append(f"🎁 <b>+500 Kitobcha</b> bonus! ({ref_count}-referral milestone)")
            if ref_count % 20 == 0:
                reward_lines.append(f"💎 <b>+3 kun Premium</b> qo'shildi! ({ref_count}-referral milestone)")

            referrer_notification = (
                f"🎉 <b>Yangi Referal!</b>\n\n"
                f"👤 <b>Yangi a'zo:</b> {new_user.full_name}\n"
                f"🆔 <b>ID:</b> <code>{new_user.telegram_id}</code>\n"
                f"📊 <b>Jami referallar:</b> {ref_count}\n\n"
                + "\n".join(reward_lines)
            )
            await bot.send_message(
                chat_id=referrer.telegram_id,
                text=referrer_notification,
                parse_mode='HTML'
            )
        except Exception as e:
            print(
                f"Failed to send notification to referrer ({referrer.telegram_id}): {e}")
