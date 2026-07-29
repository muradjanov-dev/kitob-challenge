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
        "description": (
            "Tasodifiy mukofot: kichik yoki katta Kitobcha, hattoki MEGA yutuq, "
            "Omon qolish o'yiniga +1/+2 qo'shimcha jon, bonus streak-muzlatish "
            "yoki bepul Shaxsiy sertifikat — 7 xil natija bor!"
        ),
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
        "description": (
            "Keyingi \"Top kitobxonlar\" e'lonida ismingiz sponsor sifatida "
            "ko'rsatiladi. Kuniga faqat 7 ta joy bor!"
        ),
    },
}

LEADERBOARD_SPONSOR_DAILY_LIMIT = 7


def leaderboard_sponsor_slots_left_today() -> int:
    from tgbot.models import LeaderboardSponsor
    today = timezone.localdate()
    used_today = LeaderboardSponsor.objects.filter(created_at__date=today).count()
    return max(0, LEADERBOARD_SPONSOR_DAILY_LIMIT - used_today)


def log_purchase(user, item_key: str, price: int) -> None:
    """Durable audit row for a fulfilled Market purchase — StreakFreezeCoverage/
    LeaderboardSponsor/etc. only capture each item's live *effect*, so this is
    the only place spend-by-item stats can be reconstructed from later."""
    from tgbot.models import MarketPurchase
    MarketPurchase.objects.create(user=user, item_key=item_key, price=price)


def charge(user, price: int) -> bool:
    """Deduct `price` Kitobcha from `user` if affordable (or refund, when
    `price` is negative — see the Reyting sponsorligi race-loss refund).
    Atomic + row-locked so concurrent taps can't double-spend."""
    from tgbot.models import TelegramProfile, KitobchaLedger
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        if Decimal(p.ball or 0) < Decimal(price):
            return False
        p.ball = Decimal(p.ball or 0) - Decimal(price)
        p.save(update_fields=["ball"])
        KitobchaLedger.objects.create(user=p, delta=-price, reason="market_charge")
    return True


MYSTERY_PRIZES = [
    ("kitobcha_small", 32),
    ("kitobcha_big", 13),
    ("kitobcha_mega", 3),
    ("survival_life_1", 20),
    ("survival_life_2", 5),
    ("streak_freeze", 17),
    ("free_certificate", 10),
]


def resolve_mystery_box(user):
    """Apply an immediate random prize (always something — this is meant to
    feel generous, not disappointing). Returns (text, wants_certificate) —
    the bot handler sends the certificate photo itself when the flag is set,
    since certificate delivery is a Telegram API call, not a DB write."""
    from tgbot.models import TelegramProfile, KitobchaLedger
    pick = random.choices(
        [k for k, _ in MYSTERY_PRIZES],
        weights=[w for _, w in MYSTERY_PRIZES],
        k=1,
    )[0]
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        if pick == "kitobcha_small":
            amount = random.randint(50, 150)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
            return f"🪙 <b>+{amount} Kitobcha</b> yutdingiz!", False
        if pick == "kitobcha_big":
            amount = random.randint(250, 500)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
            return f"🤑 KATTA YUTUQ! <b>+{amount} Kitobcha</b>!", False
        if pick == "kitobcha_mega":
            amount = random.randint(800, 1500)
            p.ball = Decimal(p.ball or 0) + Decimal(amount)
            p.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=p, delta=amount, reason="mystery_box")
            return f"💥 MEGA YUTUQ!!! <b>+{amount} Kitobcha</b>!!! 🎉", False
        if pick == "survival_life_1":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 1
            p.save(update_fields=["bonus_survival_lives"])
            return "❤️ Keyingi <b>Omon qolish</b> o'yiningizga <b>+1 qo'shimcha jon</b>!", False
        if pick == "survival_life_2":
            p.bonus_survival_lives = (p.bonus_survival_lives or 0) + 2
            p.save(update_fields=["bonus_survival_lives"])
            return "💖 OMON! Keyingi <b>Omon qolish</b> o'yiningizga <b>+2 qo'shimcha jon</b>!", False
        if pick == "free_certificate":
            return "📜 Sizga <b>BEPUL Shaxsiy sertifikat</b> tushdi — tayyorlanmoqda!", True
        p.streak_freeze_count = (p.streak_freeze_count or 0) + 1
        p.save(update_fields=["streak_freeze_count"])
        return "🛡 Bonus <b>Streak muzlatish</b> tokeni yutdingiz!", False


def apply_streak_freeze_purchase(user) -> int:
    from tgbot.models import TelegramProfile
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=user.id)
        p.streak_freeze_count = (p.streak_freeze_count or 0) + 1
        p.save(update_fields=["streak_freeze_count"])
        return p.streak_freeze_count


def queue_leaderboard_sponsor(user) -> bool:
    """Create a LeaderboardSponsor row unless today's 5-slot scarcity cap is
    already full. Returns False (no-op, no row created) if sold out."""
    from tgbot.models import LeaderboardSponsor
    with transaction.atomic():
        today = timezone.localdate()
        used_today = LeaderboardSponsor.objects.filter(created_at__date=today).count()
        if used_today >= LEADERBOARD_SPONSOR_DAILY_LIMIT:
            return False
        LeaderboardSponsor.objects.create(user=user)
        return True


_GOLD = (212, 175, 90)
_GOLD_LIGHT = (238, 210, 140)
_CREAM = (238, 232, 214)
_NAVY_DARK = (10, 13, 24)
_NAVY_MID = (18, 23, 40)
_MUTED = (150, 155, 175)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def generate_certificate(user) -> bytes:
    """Render a shareable, premium-styled PNG certificate with the user's key
    stats: gold-on-navy, ornamental double border with corner flourishes, a
    stat-card row, and a wax-seal-style medallion. Uses Pillow's bundled
    scalable default font (no system/TTF dependency — Pillow >= 10.1's
    ImageFont.load_default(size=...)).

    Square canvas (1:1) is deliberate: users set this as their Telegram
    profile photo, and Telegram center-crops any non-square image to a
    square for the circular avatar -- a landscape certificate (the old
    1400x900) lost its outer stat cards to that crop. Square means nothing
    ever needs to be cropped."""
    from PIL import Image, ImageDraw, ImageFont
    from tgbot.services.achievements import compute_user_stats
    import os as _os

    stats = compute_user_stats(user)
    full_name = user.full_name or "Kitobxon"

    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), _NAVY_DARK)
    draw = ImageDraw.Draw(img, "RGBA")

    # Vertical gradient background (subtle — lighter in the middle band).
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)], fill=_lerp(_NAVY_DARK, _NAVY_MID, (0.5 - abs(t - 0.5)) * 2))

    # Ornamental double border, rounded, with a small gold diamond at each corner.
    margin = 36
    draw.rounded_rectangle([margin, margin, W - margin, H - margin], radius=22, outline=_GOLD, width=4)
    margin2 = margin + 14
    draw.rounded_rectangle([margin2, margin2, W - margin2, H - margin2], radius=14, outline=_GOLD, width=1)

    def diamond(cx, cy, size, color=_GOLD):
        draw.polygon([(cx, cy - size), (cx + size, cy), (cx, cy + size), (cx - size, cy)], fill=color)

    for cx_, cy_ in [(margin, margin), (W - margin, margin), (margin, H - margin), (W - margin, H - margin)]:
        diamond(cx_, cy_, 10)

    title_font = ImageFont.load_default(size=30)
    script_font = ImageFont.load_default(size=64)
    name_font = ImageFont.load_default(size=50)
    label_font = ImageFont.load_default(size=20)
    num_font = ImageFont.load_default(size=44)
    small_font = ImageFont.load_default(size=20)
    tiny_font = ImageFont.load_default(size=16)
    seal_font = ImageFont.load_default(size=40)

    def center_text(y, text, font, fill=_CREAM):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((W - w) / 2, y), text, font=font, fill=fill)
        return w

    def center_text_spaced(y, text, font, fill, letter_spacing=8):
        widths = [draw.textbbox((0, 0), ch, font=font)[2] for ch in text]
        total = sum(widths) + letter_spacing * (len(text) - 1)
        x = (W - total) / 2
        for ch, wch in zip(text, widths):
            draw.text((x, y), ch, font=font, fill=fill)
            x += wch + letter_spacing

    # Header ornament: line – diamond – line.
    top_y = 100
    diamond(W // 2, top_y, 7)
    draw.line([(W // 2 - 160, top_y), (W // 2 - 20, top_y)], fill=_GOLD, width=2)
    draw.line([(W // 2 + 20, top_y), (W // 2 + 160, top_y)], fill=_GOLD, width=2)

    center_text_spaced(130, "KITOB CHALLENGE", title_font, _GOLD)

    title = "SERTIFIKAT"
    bbox = draw.textbbox((0, 0), title, font=script_font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) / 2 + 3, 183), title, font=script_font, fill=(0, 0, 0, 90))  # soft shadow
    draw.text(((W - tw) / 2, 180), title, font=script_font, fill=_CREAM)

    draw.line([(W // 2 - 220, 270), (W // 2 + 220, 270)], fill=_GOLD, width=2)

    center_text(305, "Ushbu sertifikat quyidagi kitobxonga taqdim etiladi:", label_font, _MUTED)

    name_y = 350
    name_w = center_text(name_y, full_name, name_font, _GOLD_LIGHT)
    uy = name_y + 68
    draw.line([(W // 2 - name_w / 2 - 30, uy), (W // 2 + name_w / 2 + 30, uy)], fill=_GOLD, width=2)
    diamond(W // 2 - name_w / 2 - 40, uy, 5)
    diamond(W // 2 + name_w / 2 + 40, uy, 5)

    # Stat-card row.
    stat_items = [
        (str(stats["pages"]), "BET O'QILDI"),
        (str(stats["books_finished"]), "KITOB TUGALLANDI"),
        (str(stats["max_streak"]), "KUNLIK STREAK"),
        (str(stats["referrals"]), "TAKLIF QILINGAN"),
    ]
    n = len(stat_items)
    card_y0, card_y1 = 470, 620
    pad_outer = 90
    col_w = (W - 2 * pad_outer) / n
    for i, (num, label) in enumerate(stat_items):
        cx_ = pad_outer + col_w * i + col_w / 2
        if i > 0:
            draw.line(
                [(pad_outer + col_w * i, card_y0 + 10), (pad_outer + col_w * i, card_y1 - 10)],
                fill=(*_GOLD, 90), width=1,
            )
        num_w = draw.textbbox((0, 0), num, font=num_font)[2]
        draw.text((cx_ - num_w / 2, card_y0), num, font=num_font, fill=_GOLD_LIGHT)
        lbl_w = draw.textbbox((0, 0), label, font=small_font)[2]
        draw.text((cx_ - lbl_w / 2, card_y0 + 70), label, font=small_font, fill=_MUTED)

    # Bot link + growth hook, right-aligned in the gap between the stat row
    # and the seal (avoids the seal's ellipse/ribbon footprint below it).
    bot_username = _os.environ.get("BOT_USERNAME", "kitob_challange_bot")
    link_text = f"t.me/{bot_username}"
    hook_text = "2 000 000+ o'qilgan betlar"
    right_edge = W - margin2 - 30
    lw = draw.textbbox((0, 0), link_text, font=small_font)[2]
    draw.text((right_edge - lw, 690), link_text, font=small_font, fill=_CREAM)
    hw = draw.textbbox((0, 0), hook_text, font=tiny_font)[2]
    draw.text((right_edge - hw, 722), hook_text, font=tiny_font, fill=_GOLD_LIGHT)

    # Seal / medallion, bottom-right.
    seal_cx, seal_cy, seal_r = W - 210, H - 155, 55
    draw.ellipse([seal_cx - seal_r, seal_cy - seal_r, seal_cx + seal_r, seal_cy + seal_r], outline=_GOLD, width=3)
    draw.ellipse(
        [seal_cx - seal_r + 10, seal_cy - seal_r + 10, seal_cx + seal_r - 10, seal_cy + seal_r - 10],
        outline=_GOLD, width=1,
    )
    bbox = draw.textbbox((0, 0), "K", font=seal_font)
    sw, sh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((seal_cx - sw / 2, seal_cy - sh / 2 - bbox[1]), "K", font=seal_font, fill=_GOLD)
    draw.polygon(
        [(seal_cx - 30, seal_cy + seal_r - 5), (seal_cx - 10, seal_cy + seal_r + 40), (seal_cx - 2, seal_cy + seal_r + 10)],
        fill=_GOLD,
    )
    draw.polygon(
        [(seal_cx + 30, seal_cy + seal_r - 5), (seal_cx + 10, seal_cy + seal_r + 40), (seal_cx + 2, seal_cy + seal_r + 10)],
        fill=_GOLD,
    )

    draw.text((margin2 + 30, H - 175), "KITOB CHALLENGE", font=tiny_font, fill=_MUTED)
    draw.text((margin2 + 30, H - 150), "Rasmiy Sertifikat", font=small_font, fill=_CREAM)
    draw.text(
        (margin2 + 30, H - 100),
        f"Sana: {timezone.localdate().strftime('%d.%m.%Y')}",
        font=tiny_font, fill=_MUTED,
    )

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
