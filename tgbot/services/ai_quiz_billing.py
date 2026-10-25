"""Who pays for an AI quiz, and how much.

Free: Premium readers and AI-quiz trial holders inside their daily allowance
(6 a day on Super Premium, otherwise 1), and a non-Premium reader's one
lifetime free try. Everyone else -- Premium readers past their allowance
included -- pays AI_QUIZ_PRICE Kitobcha per quiz.

The charge is taken before the OpenAI call and refunded if generation fails.
It used to be taken afterwards through update_ball(True, -3000), which never
checked the balance (readers could go negative) and wrote two ledger rows
for one charge.
"""
from django.core.cache import cache
from django.utils import timezone

AI_QUIZ_PRICE = 3000

FREE = "free"            # inside the Premium / trial daily allowance
FREE_TRY = "free_try"    # the one lifetime try of a non-Premium reader
PAID = "paid"            # AI_QUIZ_PRICE Kitobcha


def _usage_key(user) -> str:
    return f"ai_quiz_limit_{user.id}"


def daily_cap(user) -> int:
    from tgbot.bot.handlers.users.payment import SUPER_PREMIUM_PRICE
    from tgbot.models import Payment
    p = (Payment.objects.filter(user=user, status="paid", end_date__gte=timezone.localdate())
         .order_by("-end_date").first())
    return 6 if (p and p.amount >= SUPER_PREMIUM_PRICE) else 1


def plan(user) -> str:
    """How the reader's NEXT AI quiz is paid for."""
    from tgbot.services.premium import is_premium
    has_trial = bool(user.trial_ai_quiz_until and user.trial_ai_quiz_until >= timezone.now())
    if is_premium(user) or has_trial:
        if int(cache.get(_usage_key(user), 0) or 0) < daily_cap(user):
            return FREE
        return PAID
    if not user.free_ai_quiz_used:
        return FREE_TRY
    return PAID


def can_start(user) -> bool:
    return plan(user) != PAID or int(user.ball or 0) >= AI_QUIZ_PRICE


def charge(user) -> bool:
    from tgbot.services.game_jokers import charge as _charge
    return _charge(user, AI_QUIZ_PRICE, "ai_quiz_creation")


def refund(user) -> None:
    from tgbot.services.game_jokers import refund as _refund
    _refund(user, AI_QUIZ_PRICE, "ai_quiz_refund")


def note_used(user, how: str) -> None:
    """Record a successful generation against the allowance it used."""
    from tgbot.models import TelegramProfile
    if how == FREE:
        key = _usage_key(user)
        if not cache.add(key, 1, timeout=86400):  # window starts at first use
            cache.incr(key)
    elif how == FREE_TRY:
        TelegramProfile.objects.filter(id=user.id).update(free_ai_quiz_used=True)
