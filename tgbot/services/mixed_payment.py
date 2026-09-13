"""Aralash to'lov: Premium narxining bir qismini Kitobcha bilan to'lash.

1 Kitobcha = 1 so'm — xayriya jamg'armasi bilan bir xil kurs (100.000
Kitobcha = 100.000 so'm). Narxning ko'pi bilan MAX_SHARE qismi Kitobcha
bilan yopiladi, qolgani kartaga to'lanadi, shuning uchun har bir aralash
to'lov baribir haqiqiy pul olib keladi.

Kitobcha chek yuborilganda yechiladi (hold), admin tasdiqlasa capture,
rad etsa refund. Holatlar PremiumKitobchaHold.status bilan himoyalangan.
"""
from django.db import transaction

from tgbot.models import KitobchaLedger, PremiumKitobchaHold, TelegramProfile

MAX_SHARE_PERCENT = 30
STEP = 100  # Kitobcha amounts are whole hundreds, like everywhere else
# Super Premium is recognised by Payment.amount >= SUPER_PREMIUM_PRICE (see
# quiz_ai.py), so a discounted cash amount would silently downgrade it.
ALLOWED_PLANS = {"premium", "premium_3mo", "premium_3day"}


def usable_kitobcha(balance: int, price: int) -> int:
    cap = price * MAX_SHARE_PERCENT // 100
    return min(int(balance or 0), cap) // STEP * STEP


def hold(user_id: int, kitobcha: int, cash_price: int, plan: str, days: int):
    """Deduct `kitobcha` and open a hold. Returns the hold, or None when the
    balance no longer covers it (spent between choosing and sending)."""
    with transaction.atomic():
        user = TelegramProfile.objects.select_for_update().get(id=user_id)
        if int(user.ball or 0) < kitobcha:
            return None
        user.ball = user.ball - kitobcha
        user.save(update_fields=["ball"])
        h = PremiumKitobchaHold.objects.create(
            user=user, kitobcha=kitobcha, cash_price=cash_price, plan=plan, days=days,
        )
        KitobchaLedger.objects.create(user=user, delta=-kitobcha, reason=f"premium_mixed:{h.id}")
        return h


def capture(hold_id: int) -> str:
    """Admin approved. Returns the status the hold was in BEFORE this call:
    'held' means this call captured it and Premium should be granted."""
    with transaction.atomic():
        h = PremiumKitobchaHold.objects.select_for_update().filter(id=hold_id).first()
        if not h:
            return "missing"
        before = h.status
        if before == PremiumKitobchaHold.STATUS_HELD:
            h.status = PremiumKitobchaHold.STATUS_CAPTURED
            h.save(update_fields=["status", "updated_at"])
        return before


def refund(hold_id: int):
    """Admin rejected. Returns the refunded hold, or None if there was nothing
    to refund (already refunded, already approved, or unknown)."""
    with transaction.atomic():
        h = PremiumKitobchaHold.objects.select_for_update().filter(id=hold_id).first()
        if not h or h.status != PremiumKitobchaHold.STATUS_HELD:
            return None
        user = TelegramProfile.objects.select_for_update().get(id=h.user_id)
        user.ball = user.ball + h.kitobcha
        user.save(update_fields=["ball"])
        KitobchaLedger.objects.create(user=user, delta=h.kitobcha, reason=f"premium_mixed_refund:{h.id}")
        h.status = PremiumKitobchaHold.STATUS_REFUNDED
        h.save(update_fields=["status", "updated_at"])
        return h


def refund_text(h) -> str:
    return (f"🪙 To'lovning Kitobcha qismi — <b>{h.kitobcha:,} Kitobcha</b> — "
            "balansingizga to'liq qaytarildi.")
