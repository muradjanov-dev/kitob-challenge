"""One entry point for every "you won Premium" path in the bot.

Why this exists
---------------
Premium is checked two different ways across the codebase:

  * `Payment.objects.filter(status="paid", end_date__gte=today)` — the real
    gate, used in ~30 places (handlers, tasks, views, admin panel);
  * `TelegramProfile.trial_premium_until` — a lightweight timestamp read by
    `has_active_premium()`, which only ~8 of those places actually call.

Prize code that set *only* `trial_premium_until` therefore told the winner
"💎 3 soatlik BEPUL Premium faollashtirildi!" while nearly every Premium
feature kept answering "you are not Premium". `grant_premium()` writes both:
the exact hour-accurate window AND a real paid `Payment` row that covers it,
so a won Premium behaves like a bought one no matter which check runs.

Day granularity: `Payment.end_date` is a `DateField`, so an hours-sized prize
is rounded *up* to cover the calendar day its window ends on. Winners may get
a few extra hours; they never get less than what the prize promised.

Not used by `tasks.grant_daily_trial_premium` on purpose — that giveaway is a
teaser whose advertised perks are exactly the trial-aware ones, and turning it
into a real paid grant would give away a full day 10x every day.
"""
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone


# ── Scarcity limits for *won* Premium ────────────────────────────────────
#
# Every free prize path funnels through grant_premium(), and only those: a real
# purchase (handlers/groups/confirm_payment.py), a Kitobcha shop redemption
# (shop_views.py) and a manual admin grant (admin_panel.py) all call
# Payment.grant_or_extend() directly and are deliberately NOT limited here.
#
# Before these limits, Premium had effectively stopped being something anyone
# needed to buy: over the 30 days to 2026-09-01 the bot handed out 1736 Premium
# grants, 1728 of them free and 8 paid, and one reader had stacked 23 free
# grants into a 27-day balance without ever paying. The VIP arena alone gave
# 1 day + 12h + 6h *every evening* -- about 52 Premium-days a month, almost all
# of it to the same handful of top players.
FREE_PREMIUM_MAX_HOURS = 24      # a single prize can never exceed one day
FREE_PREMIUM_COOLDOWN_DAYS = 7   # ...and one per user per week, at most


def free_premium_blocked_reason(user) -> str | None:
    """Why `user` cannot be given free Premium right now, or None if they can.

    Two rules, both aimed at spreading a scarce prize across many readers
    instead of letting the same few farm it:

    1. Already Premium (paid or won) -- an extra day is worth nothing to
       someone who already has one, and stacking is what produced the 27-day
       balances. They get the prize's fallback reward instead.
    2. Won free Premium within the last FREE_PREMIUM_COOLDOWN_DAYS.
    """
    from datetime import timedelta
    from tgbot.models import Payment

    if not user:
        return "no_user"
    if user.has_active_premium():
        return "already_premium"
    if Payment.objects.filter(
        user=user, status="paid", end_date__gte=timezone.localdate(),
    ).exists():
        return "already_premium"

    recent = Payment.objects.filter(
        user=user, amount=0,
        created_at__gte=timezone.now() - timedelta(days=FREE_PREMIUM_COOLDOWN_DAYS),
    ).exists()
    return "cooldown" if recent else None


def grant_premium(user, *, days: int = 0, hours: int = 0) -> object:
    """Grant `days`/`hours` of real, fully-functional Premium to `user`.

    Always EXTENDS whatever the user already has (see Payment.grant_or_extend)
    instead of resetting it. Returns the new trial-window end datetime, or
    **None** when the scarcity limits above refused the grant -- callers must
    check for None and offer their fallback reward rather than announcing a
    Premium the winner did not receive.
    """
    from tgbot.models import Payment

    days = int(days or 0)
    hours = int(hours or 0)
    if days <= 0 and hours <= 0:
        return getattr(user, "trial_premium_until", None)

    reason = free_premium_blocked_reason(user)
    if reason:
        print(f"grant_premium: refused for user={getattr(user, 'id', None)} ({reason})")
        return None

    # Clamp before anything is written -- a 3-day prize becomes one day.
    total_hours = min(days * 24 + hours, FREE_PREMIUM_MAX_HOURS)
    days, hours = divmod(total_hours, 24)

    now = timezone.now()

    # 1. Hour-accurate window — what the prize literally promised.
    until = max(user.trial_premium_until or now, now) + timedelta(days=days, hours=hours)
    user.trial_premium_until = until
    user.save(update_fields=["trial_premium_until"])

    # 2. A real paid row, so every `end_date__gte=today` gate sees it too.
    #
    # Whole days are added on top of any running subscription, never merged
    # into it: 2 days left + a 3-day prize = 5 days (see Payment.grant_or_extend).
    if days > 0:
        Payment.grant_or_extend(user, days, amount=0)

    # An hours-sized prize has no whole day to add, so it only guarantees the
    # paid row reaches the calendar day its window ends on — rounding up rather
    # than down, so the winner is never short-changed by DateField granularity.
    if hours > 0:
        today = timezone.localdate()
        target = timezone.localdate(until)
        current_end = Payment.objects.filter(
            user=user, status="paid", end_date__gte=today,
        ).aggregate(Max("end_date"))["end_date__max"]
        if current_end is None:
            # 0 days still writes end_date=today, which satisfies
            # end_date__gte=today for the remainder of the day.
            Payment.grant_or_extend(user, max((target - today).days, 0), amount=0)
        elif target > current_end:
            Payment.grant_or_extend(user, (target - current_end).days, amount=0)
        # else: already covered by a longer subscription — nothing to add.

    return until


def premium_left_text(user) -> str:
    """Short human-readable remaining-Premium string, for confirmation DMs."""
    from tgbot.models import Payment

    today = timezone.localdate()
    end = Payment.objects.filter(
        user=user, status="paid", end_date__gte=today,
    ).aggregate(Max("end_date"))["end_date__max"]
    if not end:
        until = getattr(user, "trial_premium_until", None)
        if until and until >= timezone.now():
            hrs = max(1, int((until - timezone.now()).total_seconds() // 3600))
            return f"{hrs} soat"
        return "—"
    return f"{(end - today).days + 1} kun ({end.strftime('%d.%m.%Y')} gacha)"


# ─────────────────────────────────────────────────────────────────────────
# Bitta yagona darvoza
#
# Premium ilgari ikki xil tekshirilardi: ~30 joyda to'g'ridan-to'g'ri
# `Payment(status="paid", end_date__gte=today)`, atigi ~8 joyda esa trialni
# ham biladigan `has_active_premium()`. Natijada sinov Premiumi olgan odam
# "3 soatlik BEPUL Premium" degan xabarni oladi-yu, deyarli har bir
# imtiyozda "Premium kerak" devoriga urilardi -- ya'ni sinov Premiumning
# qanchalik yaxshiligini emas, ishlamasligini ko'rsatardi.
#
# Quyidagilar hamma imtiyoz eshiklari uchun yagona javob beradi. Hisobot va
# statistikada ATAYLAB ishlatilmaydi: u yerda "nechta odam pul to'lagan"
# degan savolga javob kerak, sinovdagilar bu raqamni shishirmasligi lozim.
# ─────────────────────────────────────────────────────────────────────────

def is_premium(user) -> bool:
    """Imtiyoz eshigi: pullik obuna YOKI faol sinov oynasi."""
    if not user:
        return False
    return bool(user.has_active_premium())


def is_premium_by_id(profile_id) -> bool:
    """TelegramProfile birlamchi kaliti bo'yicha."""
    from tgbot.models import TelegramProfile
    p = TelegramProfile.objects.filter(id=profile_id).only(
        "id", "trial_premium_until").first()
    return is_premium(p)


def is_premium_by_telegram_id(telegram_id) -> bool:
    """Telegram ID bo'yicha (handlerlarda ko'pincha faqat shu bo'ladi)."""
    from tgbot.models import TelegramProfile
    p = TelegramProfile.objects.filter(telegram_id=telegram_id).only(
        "id", "trial_premium_until").first()
    return is_premium(p)


def active_premium_user_ids() -> set:
    """Hozir Premium hisoblanadigan barcha TelegramProfile id lari."""
    from tgbot.models import Payment, TelegramProfile
    ids = set(
        Payment.objects.filter(
            status="paid", end_date__gte=timezone.localdate(),
        ).values_list("user_id", flat=True)
    )
    ids |= set(
        TelegramProfile.objects.filter(
            trial_premium_until__gte=timezone.now(),
        ).values_list("id", flat=True)
    )
    return ids


def active_premium_telegram_ids() -> set:
    """Xuddi shu ro'yxat, lekin telegram_id lar bilan."""
    from tgbot.models import Payment, TelegramProfile
    ids = set(
        Payment.objects.filter(
            status="paid", end_date__gte=timezone.localdate(),
        ).values_list("user__telegram_id", flat=True)
    )
    ids |= set(
        TelegramProfile.objects.filter(
            trial_premium_until__gte=timezone.now(),
        ).values_list("telegram_id", flat=True)
    )
    return ids
