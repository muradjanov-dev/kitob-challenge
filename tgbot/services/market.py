"""Kitob Challenge Market — bot-chat purchasable perks.

Distinct from the ShopProduct catalog (admin-curated physical/Premium prizes,
bought through the Mini App, still gated to admins for testing — see
tgbot/shop_views.py). These 5 items are small, code-defined mechanics that
give Kitobcha somewhere fun and low-friction to go, entirely inside the chat
— no WebApp, no admin hand-off (except where noted).
"""
import random
from decimal import Decimal
from io import BytesIO

from django.db import transaction
from django.utils import timezone

STREAK_FREEZE = "streak_freeze"
MYSTERY_BOX = "mystery_box"
CERTIFICATE = "certificate"
DAY_HERO = "day_hero"
LEADERBOARD_SPONSOR = "leaderboard_sponsor"

ITEMS = {
    STREAK_FREEZE: {
        "emoji": "🛡",
        "title": "Streak muzlatish",
        "price": 750,
        "description": (
            "Bir kun hisobot yubormay qolib ketsangiz ham, ketma-ketligingiz "
            "(streak) buzilmaydi — birinchi bo'sh kuningizga avtomatik ishlatiladi."
        ),
    },
    MYSTERY_BOX: {
        "emoji": "🎁",
        "title": "Sirli quti",
        "price": 200,
        "description": "Tasodifiy mukofot: Kitobcha, Omon qolish o'yiniga qo'shimcha jon yoki bonus streak-muzlatish.",
    },
    CERTIFICATE: {
        "emoji": "📜",
        "title": "Shaxsiy sertifikat",
        "price": 150,
        "description": "O'z statistikangiz (bet, kitob, streak) bilan chiroyli rasm-sertifikat — darhol yuboriladi.",
    },
    DAY_HERO: {
        "emoji": "🌟",
        "title": "Kun qahramoni",
        "price": 500,
        "description": "Siz haqingizda tantanali e'lon guruhning E'lonlar bo'limiga darhol joylanadi.",
    },
    LEADERBOARD_SPONSOR: {
        "emoji": "🏷",
        "title": "Reyting sponsorligi",
        "price": 300,
        "description": "Keyingi \"Top kitobxonlar\" e'lonida ismingiz sponsor sifatida ko'rsatiladi.",
    },
}


def charge(user, price: int) -> bool:
    """Deduct `price` Kitobcha from `user` if affordable. Atomic + row-locked
    so concurrent taps can't double-spend."""
    from tgbot.models import TelegramProfile
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        if Decimal(p.ball or 0) < Decimal(price):
            return False
        p.ball = Decimal(p.ball or 0) - Decimal(price)
        p.save(update_fields=["ball"])
    return True


def resolve_mystery_box(user) -> str:
    """Apply an immediate random prize (always something — this is meant to
    feel generous, not disappointing) and return the user-facing result line."""
    from tgbot.models import TelegramProfile
    pick = random.choices(
        ["kitobcha_small", "kitobcha_big", "survival_life", "streak_freeze"],
        weights=[40, 15, 25, 20],
        k=1,
    )[0]
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        if pick == "kitobcha_small":
            amount = random.randint(50, 150)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            return f"🪙 <b>+{amount} Kitobcha</b> yutdingiz!"
        if pick == "kitobcha_big":
            amount = random.randint(250, 500)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            return f"🤑 KATTA YUTUQ! <b>+{amount} Kitobcha</b>!"
        if pick == "survival_life":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 1
            p.save(update_fields=["bonus_survival_lives"])
            return "❤️ Keyingi <b>Omon qolish</b> o'yiningizga <b>+1 qo'shimcha jon</b>!"
        p.streak_freeze_count = (p.streak_freeze_count or 0) + 1
        p.save(update_fields=["streak_freeze_count"])
        return "🛡 Bonus <b>Streak muzlatish</b> tokeni yutdingiz!"


def apply_streak_freeze_purchase(user) -> int:
    from tgbot.models import TelegramProfile
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        p.streak_freeze_count = (p.streak_freeze_count or 0) + 1
        p.save(update_fields=["streak_freeze_count"])
        return p.streak_freeze_count


def queue_leaderboard_sponsor(user) -> None:
    from tgbot.models import LeaderboardSponsor
    LeaderboardSponsor.objects.create(user=user)


def generate_certificate(user) -> bytes:
    """Render a shareable PNG certificate with the user's key stats. Uses
    Pillow's bundled scalable default font (no system/TTF dependency —
    Pillow >= 10.1's ImageFont.load_default(size=...))."""
    from PIL import Image, ImageDraw, ImageFont
    from tgbot.services.achievements import compute_user_stats

    stats = compute_user_stats(user)
    W, H = 1200, 800
    img = Image.new("RGB", (W, H), color=(20, 24, 38))
    draw = ImageDraw.Draw(img)

    draw.rectangle([20, 20, W - 20, H - 20], outline=(255, 200, 60), width=6)
    draw.rectangle([40, 40, W - 40, H - 40], outline=(255, 200, 60), width=2)

    title_font = ImageFont.load_default(size=52)
    name_font = ImageFont.load_default(size=44)
    stat_font = ImageFont.load_default(size=32)
    small_font = ImageFont.load_default(size=22)

    def center_text(y, text, font, fill=(255, 255, 255)):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((W - w) / 2, y), text, font=font, fill=fill)

    center_text(90, "KITOB CHALLENGE", title_font, (255, 200, 60))
    center_text(160, "SERTIFIKAT", title_font, (255, 255, 255))
    center_text(280, user.full_name or "Kitobxon", name_font, (255, 200, 60))

    rows = [
        f"{stats['pages']} bet o'qildi",
        f"{stats['books_finished']} ta kitob tugallandi",
        f"Eng uzun streak: {stats['max_streak']} kun",
        f"{stats['referrals']} ta do'st taklif qilindi",
    ]
    y = 380
    for text in rows:
        center_text(y, text, stat_font, (230, 230, 230))
        y += 60

    center_text(H - 90, timezone.localdate().strftime("%d.%m.%Y"), small_font, (150, 150, 150))

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
