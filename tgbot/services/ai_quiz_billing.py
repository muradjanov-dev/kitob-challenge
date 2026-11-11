"""Who pays for an AI quiz, and how much.

Free: Premium readers / members and AI-quiz trial holders inside their daily
allowance (6 a day on Super Premium, otherwise 1), and a non-member's one
lifetime free try. Everyone else pays per question (owner, 2026-11-11):
PRICE_PER_QUESTION so'm from the wallet OR the same number of Kitobcha --
the reader picks. One question costs the project about 10-27 so'm of model
time, so 100 covers it several times over.

The charge is taken before the model call and refunded if generation fails;
questions the model did not deliver are refunded too.
"""
from django.core.cache import cache
from django.utils import timezone

PRICE_PER_QUESTION = 100          # so'm or Kitobcha, the reader's choice
MIN_QUESTIONS = 5                 # the smallest quiz on offer
SOM, KITOBCHA = "som", "kitobcha"
# Kept for old call sites and texts: the price of the smallest quiz.
AI_QUIZ_PRICE = PRICE_PER_QUESTION * MIN_QUESTIONS

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


def price_for(q_count) -> int:
    return int(q_count) * PRICE_PER_QUESTION


def balances(user) -> dict:
    return {SOM: int(getattr(user, "wallet_balance", 0) or 0), KITOBCHA: int(user.ball or 0)}


def can_afford(user, amount, currency=None) -> bool:
    b = balances(user)
    return b[currency] >= amount if currency else max(b.values()) >= amount


def can_start(user) -> bool:
    return plan(user) != PAID or can_afford(user, price_for(MIN_QUESTIONS))


def price_text(amount=None) -> str:
    if amount is None:
        return f"savoliga {PRICE_PER_QUESTION} so'm yoki {PRICE_PER_QUESTION} Kitobcha"
    return f"{amount:,} so'm yoki {amount:,} Kitobcha".replace(",", " ")


def unit(currency) -> str:
    return "so'm" if currency == SOM else "Kitobcha"


def charge(user, amount: int, currency: str = KITOBCHA) -> bool:
    """Take `amount` from the wallet (so'm) or the Kitobcha balance."""
    if currency == SOM:
        from django.db import transaction
        from tgbot.models import TelegramProfile, WalletTransaction
        from tgbot.services import wallet
        with transaction.atomic():
            p = TelegramProfile.objects.select_for_update().get(id=user.id)
            row = wallet.spend_locked(p, amount, WalletTransaction.KIND_SHOP, "AI quiz")
        if row:
            user.wallet_balance = p.wallet_balance
        return bool(row)
    from tgbot.services.game_jokers import charge as _charge
    return _charge(user, amount, "ai_quiz_creation")


def refund(user, amount: int, currency: str = KITOBCHA) -> None:
    if amount <= 0:
        return
    if currency == SOM:
        from django.db import transaction
        from tgbot.models import TelegramProfile, WalletTransaction
        from tgbot.services import wallet
        with transaction.atomic():
            p = TelegramProfile.objects.select_for_update().get(id=user.id)
            wallet.credit_locked(p, amount, WalletTransaction.KIND_SHOP_REFUND, "AI quiz qaytimi")
        user.wallet_balance = p.wallet_balance
        return
    from tgbot.services.game_jokers import refund as _refund
    _refund(user, amount, "ai_quiz_refund")


def note_used(user, how: str) -> None:
    """Record a successful generation against the allowance it used."""
    from tgbot.models import TelegramProfile
    if how == FREE:
        key = _usage_key(user)
        if not cache.add(key, 1, timeout=86400):  # window starts at first use
            cache.incr(key)
    elif how == FREE_TRY:
        TelegramProfile.objects.filter(id=user.id).update(free_ai_quiz_used=True)
