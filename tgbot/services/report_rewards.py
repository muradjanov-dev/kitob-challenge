"""Rewards for readers who keep reporting (owner, 2026-11-11).

- Ketma-ketlik mukofoti: every STREAK_STEP days in a row (10, 20, 30...) the
  reader gets STREAK_PREMIUM_DAYS of Premium, the moment the report that completes the
  step comes in (signal on ConfirmationReport -> reward_report_streak task).
  Freeze-covered days count, as everywhere else (ops_fixes.current_streak).
- Kunning sovg'asi: once a day the project gives GIFT_PREMIUM_DAYS of Premium to one
  reader, drawn from those who reported on at least GIFT_MIN_DAYS of the last
  GIFT_WINDOW days; told by DM and announced in the groups. Not a lottery
  (owner, 2026-11-11: "qimor bo'lmasin"): nobody pays or stakes anything for
  it -- no ticket, no Kitobcha, no fee -- and nobody loses anything; it is a
  gift from the project's own funds to its steady readers.

Both are gifts (never refunded) and each is paid at most once: the note of the
WalletTransaction is the marker, checked under the profile's row lock.
"""
import datetime
import secrets

from django.db import transaction
from django.utils import timezone

STREAK_STEP = 10
# Owner, 2026-11-22: reports are free and wallets became Premium, so both
# rewards are Premium days now (Payment.grant_or_extend, added after any
# Premium already held). The WalletTransaction row stays as the once-only
# marker, with delta 0.
STREAK_PREMIUM_DAYS = 5
GIFT_PREMIUM_DAYS = 7
GIFT_MIN_DAYS = 3
GIFT_WINDOW = 7


def _uz(d) -> str:
    from tgbot.services.wallet import uz_date
    return uz_date(d)


def _som(v) -> str:
    return f"{int(v or 0):,}".replace(",", " ")


def _first_name(p) -> str:
    from tgbot.services.announce_style import name
    return name(((p.full_name or "").split() or ["Kitobxon"])[0])


def streak_note(streak: int, day) -> str:
    return f"{streak} kun ketma-ket ({day:%d.%m.%Y})"


def _grant_days(p, days: int, kind: str, note: str):
    """Marker row + Premium days, under the caller's row lock."""
    from tgbot.models import Payment, WalletTransaction
    WalletTransaction.objects.create(user=p, kind=kind, delta=0,
                                     balance_after=int(p.wallet_balance or 0), note=note[:120])
    return Payment.grant_or_extend(p, days, amount=0)


def reward_streak(user_id: int, day=None) -> int:
    """Give the streak reward if today's report completed a STREAK_STEP; the
    Premium days given (0 when nothing is due or it was given already)."""
    from tgbot.models import ConfirmationReport, TelegramProfile, WalletTransaction
    from tgbot.services import ops_fixes

    day = day or timezone.localdate()
    if not ConfirmationReport.objects.filter(user_id=user_id, date__date=day).exists():
        return 0
    streak = ops_fixes.current_streak(user_id)
    if streak <= 0 or streak % STREAK_STEP:
        return 0
    note = streak_note(streak, day)
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user_id)
        if WalletTransaction.objects.filter(user=p, kind=WalletTransaction.KIND_STREAK, note=note).exists():
            return 0
        pay = _grant_days(p, STREAK_PREMIUM_DAYS, WalletTransaction.KIND_STREAK, note)
    if not p.is_blocked:
        _dm(p.telegram_id, streak_text(p, streak, pay.end_date))
    return STREAK_PREMIUM_DAYS


def streak_text(p, streak: int, until=None) -> str:
    from tgbot.services.announce_style import quote_block
    return (
        f"🔥 <b>{streak} kun ketma-ket!</b>\n\n"
        f"{_first_name(p)}, Siz {streak} kundan beri bir kun ham to'xtamay hisobot yuboryapsiz — "
        f"bunday intizom kamdan-kam odamga nasib qiladi.\n\n"
        f"🎁 Mukofot: <b>{STREAK_PREMIUM_DAYS} kunlik Premium</b>"
        + (f" — <b>{_uz(until)}gacha</b> faol" if until else "") + ".\n"
        "💎 Kitobcha ×2, VIP arena va boshqa imtiyozlar.\n\n"
        f"{quote_block('steady', timezone.localdate())}\n\n"
        f"Keyingi mukofot — <b>{streak + STREAK_STEP}-kunda</b>. Zanjirni uzmang! 📚"
    )


# ── Kunning sovg'asi ─────────────────────────────────────────────────────────

def gift_note(day) -> str:
    return f"Kunning sovg'asi {day:%d.%m.%Y}"


def gift_pool(day=None) -> list:
    """Profile ids that may win on `day`: GIFT_MIN_DAYS report days within
    the GIFT_WINDOW days ending on `day`."""
    from django.db.models import Count
    from django.db.models.functions import TruncDate
    from tgbot.models import ConfirmationReport

    day = day or timezone.localdate()
    since = day - datetime.timedelta(days=GIFT_WINDOW - 1)
    rows = (ConfirmationReport.objects
            .filter(date__date__gte=since, date__date__lte=day,
                    user__is_registered=True, user__is_blocked=False, user__is_admin=False)
            .annotate(d=TruncDate("date")).values("user_id")
            .annotate(days=Count("d", distinct=True)).filter(days__gte=GIFT_MIN_DAYS))
    return sorted(r["user_id"] for r in rows)


def draw_daily_gift(day=None, apply=True) -> dict:
    """Pick and pay `day`'s winner. Idempotent: a day that already has its
    winner returns that winner and pays nothing."""
    from tgbot.models import TelegramProfile, WalletTransaction

    day = day or timezone.localdate()
    note = gift_note(day)
    done = WalletTransaction.objects.filter(kind=WalletTransaction.KIND_DAILY_GIFT, note=note).first()
    if done:
        return {"ok": True, "already": True, "winner_id": done.user_id}
    pool = gift_pool(day)
    if not pool:
        return {"ok": False, "error": "empty_pool"}
    if not apply:
        return {"ok": True, "pool": len(pool)}
    winner_id = secrets.SystemRandom().choice(pool)
    with transaction.atomic():
        # Lock the winner and re-check the day under the lock: two runs racing
        # each see "no winner yet", only the first to hold a lock pays.
        p = TelegramProfile.objects.select_for_update().get(id=winner_id)
        if WalletTransaction.objects.select_for_update().filter(
                kind=WalletTransaction.KIND_DAILY_GIFT, note=note).exists():
            return {"ok": True, "already": True}
        pay = _grant_days(p, GIFT_PREMIUM_DAYS, WalletTransaction.KIND_DAILY_GIFT, note)
    _dm(p.telegram_id, gift_dm_text(p, pay.end_date))
    return {"ok": True, "winner_id": p.id, "telegram_id": p.telegram_id, "name": p.full_name,
            "pool": len(pool), "group_text": gift_group_text(p, day)}


def gift_dm_text(p, until=None) -> str:
    return (
        f"🎁 <b>{_first_name(p)}, bugungi loyiha sovg'asi — Sizga!</b>\n\n"
        f"Hisobotlaringizdagi sabr va muntazamlik uchun Kitob Challenge'dan kichik tashakkur: "
        f"<b>{GIFT_PREMIUM_DAYS} kunlik Premium</b>"
        + (f" — <b>{_uz(until)}gacha</b> faol" if until else "") + ". 🎉\n"
        "💎 Kitobcha ×2, VIP arena va boshqa imtiyozlar.\n\n"
        "O'qishda davom eting — har bir sahifa Sizni o'zingizga yana bir qadam yaqinlashtiradi. 📚"
    )


def gift_group_text(p, day) -> str:
    from tgbot.services.announce_style import name, quote_block
    return (
        "🎁 <b>Kunning sovg'asi</b>\n\n"
        f"{quote_block('gift', day)}\n\n"
        f"Bugun loyiha sovg'asi — <b>{name(p.full_name)}</b>ga: "
        f"<b>{GIFT_PREMIUM_DAYS} kunlik Premium</b>! 🎉\n\n"
        f"Har kuni bitta muntazam kitobxon shunday sovg'a oladi — hech qanday to'lov va ishtirok badalisiz. "
        f"Sharti bitta: oxirgi {GIFT_WINDOW} kunda kamida <b>{GIFT_MIN_DAYS} kun</b> hisobot yuborgan bo'lish.\n"
        "📖 Ertangi sovg'a egasi — balki Siz?"
    )


def _dm(chat_id, text) -> bool:
    import os

    import requests
    try:
        return requests.post(
            f"https://api.telegram.org/bot{os.environ.get('API_TOKEN', '')}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"},
            timeout=8).ok
    except Exception as e:
        print(f"report_rewards DM {chat_id}: {e}")
        return False


# Every new report asks for the streak check once its transaction commits.
from django.db.models.signals import post_save  # noqa: E402


def _on_report(sender, instance, created, **kwargs):
    if not created or not instance.user_id:
        return
    uid = instance.user_id

    def _go():
        try:
            from tgbot.tasks import reward_report_streak
            reward_report_streak.delay(uid)
        except Exception as e:
            print(f"report_rewards: streak check for {uid} not queued: {e}")
    transaction.on_commit(_go)


def connect():
    from tgbot.models import ConfirmationReport
    post_save.connect(_on_report, sender=ConfirmationReport, dispatch_uid="report_rewards_streak")
