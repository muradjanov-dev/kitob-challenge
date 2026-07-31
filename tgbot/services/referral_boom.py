"""Referral BOOM — pure helpers shared by the async bot handlers and the sync
Celery tasks: reminder-schedule generation, copy builders, and the pool of
playful, never-the-same reminder templates.

Kept dependency-light (only stdlib + Django timezone) so it imports cleanly
from both the aiogram side and the Celery side.
"""
import random
from datetime import datetime, time, timedelta

from django.utils import timezone


# ── Reminder scheduling ──────────────────────────────────────────────────────
# Reminders are spread randomly across the boom window but kept inside waking
# hours (Tashkent local) so nobody gets pinged at 04:00.
DAY_START_HOUR = 8
DAY_END_HOUR = 22  # last reminder fires before this hour


def generate_reminder_schedule(now, end_at, count, day_start=DAY_START_HOUR, day_end=DAY_END_HOUR):
    """Return an ascending list of ISO datetime strings — `count` reminder
    fire-times randomly distributed across (now, end_at], each nudged into
    [day_start, day_end) local hours. Returns [] if the window is empty."""
    span = (end_at - now).total_seconds()
    if span <= 0 or count <= 0:
        return []

    fires = []
    for _ in range(count):
        dt = now + timedelta(seconds=random.uniform(0, span))
        local = timezone.localtime(dt)
        if local.hour < day_start:
            local = local.replace(hour=day_start, minute=random.randint(0, 59), second=0, microsecond=0)
        elif local.hour >= day_end:
            local = local.replace(hour=day_end - 1, minute=random.randint(0, 59), second=0, microsecond=0)
        fires.append(local)

    fires.sort()
    # A daytime nudge can shove a pick slightly before `now`; drop those so we
    # don't dump a burst the instant someone joins. Keep at least one if all fell.
    future = [d for d in fires if d > now]
    fires = future or fires
    return [d.isoformat() for d in fires]


def generate_daily_reminder_schedule(start_at, end_at, day_start=DAY_START_HOUR, day_end=DAY_END_HOUR):
    """One reminder per calendar day (Tashkent-local) across [start_at, end_at),
    each at a random time within [day_start, day_end) hours. Unlike
    generate_reminder_schedule (a fixed count spread randomly across the
    *whole* window, which can cluster several reminders on one day and skip
    another), this guarantees a steady one-a-day cadence -- the shape a
    single daily CTA competition wants. Skips the join day entirely if
    fewer than 2 hours remain before day_end that day."""
    local_start = timezone.localtime(start_at)
    local_end = timezone.localtime(end_at)
    fires = []
    day = local_start.date()
    while day <= local_end.date():
        day_end_dt = timezone.make_aware(datetime.combine(day, time(day_end, 0)))
        if day == local_start.date() and (day_end_dt - local_start).total_seconds() < 2 * 3600:
            day += timedelta(days=1)
            continue
        fire = timezone.make_aware(
            datetime.combine(day, time(random.randint(day_start, day_end - 1), random.randint(0, 59)))
        )
        if local_start < fire < local_end:
            fires.append(fire)
        day += timedelta(days=1)
    fires.sort()
    return [d.isoformat() for d in fires]


def parse_iso(s: str):
    """Parse an ISO string back to an aware datetime (tolerant of 'Z')."""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ── Reward / progress text fragments ─────────────────────────────────────────
def hours_left(end_at) -> int:
    secs = (end_at - timezone.now()).total_seconds()
    return max(0, int(secs // 3600))


def humanize_left(end_at) -> str:
    """e.g. '2 kun 5 soat' / '7 soat' / 'oxirgi daqiqalar'."""
    h = hours_left(end_at)
    if h <= 0:
        return "oxirgi daqiqalar"
    days, rem = divmod(h, 24)
    parts = []
    if days:
        parts.append(f"{days} kun")
    if rem:
        parts.append(f"{rem} soat")
    return " ".join(parts) or "1 soatdan kam"


# ── Welcome / rules DM (sent exactly once on join) ───────────────────────────
def build_welcome_text(full_name: str, boom, referral_link: str) -> str:
    name = full_name or "Kitobxon"
    # Was hardcoded to "3 kun" -- wrong for any boom of a different length
    # (e.g. a 7-day standalone event). Derive it from the actual window.
    days = max(1, round((boom.end_at - boom.start_at).total_seconds() / 86400))
    return (
        f"🎉 <b>Tabriklaymiz, {name}!</b>\n"
        f"Siz <b>{boom.title}</b> ga qo'shildingiz! 🚀\n\n"
        f"💥 <b>QOIDALAR (faqat 1 marta yuboriladi):</b>\n"
        f"• Har bir taklif qilgan yangi do'stingiz uchun "
        f"<b>{boom.tier1_reward} Kitobcha</b> olasiz!\n"
        f"• <b>{boom.tier1_cap} tadan</b> ko'p do'st taklif qilsangiz — "
        f"har biri uchun <b>{boom.tier2_reward} Kitobcha</b>! 🤯\n"
        f"• Do'stingiz ro'yxatdan o'tib, birinchi hisobotini yuborgach taklif hisoblanadi.\n"
        f"• Hech bo'lmasa <b>1 ta</b> kitobxon taklif qilganlarga ham "
        f"<b>500 Kitobcha</b> kafolatlanadi!\n"
        f"• Bu musobaqa faqat <b>{days} kun</b> davom etadi — vaqt ketmoqda! ⏳\n\n"
        f"🏆 <b>Musobaqa oxirida ENG KO'P do'st taklif qilgan TOP-3 kitobxonga:</b>\n"
        f"🥇 1-o'rin: 1 oylik Kitob Challenge Premium + \"Iymon\" kitobi + "
        f"<b>10.000 Kitobcha</b>!\n"
        f"🥈 2-o'rin: \"Dunyoni tebratgan 7 buyuk\" kitobi + <b>5.000 Kitobcha</b>!\n"
        f"🥉 3-o'rin: 3 oylik Kitob Challenge Premium + kitob sovg'a + "
        f"<b>2.500 Kitobcha</b>!\n\n"
        f"🔗 <b>Sizning shaxsiy havolangiz:</b>\n{referral_link}\n\n"
        f"📲 Havolani do'stlaringizga, guruhlaringizga tashlang.\n"
        f"🛍 Yiqqan Kitobchalaringizga <b>Kitob Challenge do'koni</b>dan "
        f"qimmatbaho sovg'alar oling — qancha ko'p Kitobcha, shuncha zo'r sovg'a!\n\n"
        f"Omad! G'alaba siznikidir 💪🔥"
    )


# ── Creative, varied share-button texts (competition-flavored, distinct from
# tasks.py's evergreen _referral_share_texts pool) ───────────────────────────
def boom_share_texts(full_name: str, boom_title: str) -> list:
    """~20 varied, punchy invite blurbs for the boom's own share button --
    urgency/competition framed (time-limited, ranking, tiered reward), unlike
    the general always-on referral share pool. A different random one each
    time the button is (re)built so repeat shares don't look copy-pasted."""
    name = (full_name or "").strip().split(" ")[0] if full_name else ""
    name = name or "Kitobxon"
    return [
        f"🔥 {name} bilan birga «{boom_title}» musobaqasida qatnashamizmi? Bir necha kun qoldi, qo'shil!",
        f"🏆 {boom_title} boshlandi — do'stlarni taklif qilib, reytingda ko'tarilaylik! Sen ham qo'shil 👇",
        f"⏳ Vaqt kam qoldi! {boom_title} musobaqasida men allaqachon qatnashyapman — sen ham qo'shil, birga g'alaba qilamiz!",
        f"👋 {name} seni «{boom_title}» musobaqasiga taklif qilyapti — o'qish + do'stlik + sovg'alar, hammasi bitta joyda!",
        f"🚀 Kitob Challenge'da yangi musobaqa — «{boom_title}»! Qo'shil, birga reytingda ko'tarilamiz.",
        f"🎯 {boom_title}: kim ko'proq do'st taklif qilsa, shuncha ko'p Kitobcha yutadi. Men boshladim — sen-chi?",
        f"💥 Musobaqa qizidi! «{boom_title}»ga qo'shilib, {name} bilan bellashamizmi?",
        f"📣 Do'stim, {boom_title} musobaqasi ketyapti — bir necha kunda tugaydi. Hoziroq qo'shil!",
        f"🎁 {boom_title} davomida qo'shilganlar sovg'alarga yaqinroq. {name} allaqachon ichida — sen ham kir!",
        f"😏 {name}dan chaqiriq: «{boom_title}» musobaqasida meni yenga olasanmi? Qo'shil, sinab ko'r!",
        f"🏁 Marra yaqin — «{boom_title}» tugashiga sanoqli kun qoldi. Sen ham safga qo'shil!",
        f"🌟 Kitob Challenge'dagi eng qizg'in musobaqa — «{boom_title}». {name} bilan birga qatnashamiz!",
        f"🤝 {name} bilan birga o'qib, birga taklif qilib, «{boom_title}»da ko'proq yutamiz. Qo'shil!",
        f"📈 Reytingda yuqoriga chiqishni xohlaysanmi? «{boom_title}» musobaqasi aynan shu imkoniyat!",
        f"🎉 {boom_title} — Kitob Challenge'ning eng qiziqarli musobaqasi hozir davom etmoqda. Sen ham bo'l!",
        f"💪 {name} musobaqada faol — sen ortda qolma! «{boom_title}»ga hoziroq qo'shil.",
        f"🔗 Bitta havola — «{boom_title}» musobaqasiga kirish darvozasi. {name} seni kutmoqda!",
        f"⚡️ Tezroq qo'shilsang, ko'proq vaqting bor! «{boom_title}» hali davom etyapti.",
        f"🥇 Kim g'olib bo'ladi? «{boom_title}»da {name} bilan raqobatlashib ko'r!",
        f"📚 O'qish qiziqarli, lekin musobaqa — battar qiziqarli! «{boom_title}»ga {name} bilan qo'shil.",
    ]


# ── Per-referral payout DM (sent each time a boom referral lands) ─────────────
def build_payout_text(boom, referral_number: int, awarded: int, total_earned: int, balance: int) -> str:
    if referral_number <= boom.tier1_cap:
        to_tier2 = boom.tier1_cap - referral_number
        tier_line = (
            f"🔥 Yana <b>{to_tier2} ta</b> do'st — keyin har biri uchun "
            f"<b>{boom.tier2_reward} Kitobcha</b>!"
            if to_tier2 > 0 else
            f"🤯 Keyingi do'stdan boshlab har biri <b>{boom.tier2_reward} Kitobcha</b>!"
        )
    else:
        tier_line = f"💎 Siz <b>2x darajadasiz</b> — har taklif <b>{boom.tier2_reward} Kitobcha</b>!"

    return (
        f"🎉 <b>Tabriklaymiz! +{awarded} Kitobcha!</b>\n\n"
        f"👥 {boom.title} davomidagi takliflaringiz: <b>{referral_number}</b> ta\n"
        f"🪙 {boom.title}dan yig'ildi: <b>{total_earned} Kitobcha</b>\n"
        f"💰 Umumiy balans: <b>{balance} Kitobcha</b>\n\n"
        f"{tier_line}\n"
        f"🛍 Do'kondan sovg'a olishni unutmang!"
    )


# ── The playful reminder pool ────────────────────────────────────────────────
# Each entry has a stable `key` (so we never repeat copy for one user) and a
# `text` template. Available format fields:
#   {referrals} {earned} {balance} {left} {link} {tier1} {tier2} {cap} {title}
# Tone is deliberately all over the place — memes, FOMO, drama, jokes — so the
# 21 nudges never feel like the same robotic system notification.
BOOM_REMINDER_POOL = [
    {"key": "fomo_clock", "text": (
        "⏰ <i>Tik-tak, tik-tak...</i>\n"
        "{title} tugashiga <b>{left}</b> qoldi! Har do'st = <b>{tier1} Kitobcha</b> 💸\n"
        "🔗 {link}"
    )},
    {"key": "meme_money", "text": (
        "💸💸💸 Pul yog'moqda... yo'q, <b>Kitobcha</b> yog'moqda!\n"
        "Hozir balansingiz: <b>{balance} Kitobcha</b>. Yana ko'paytiramizmi? 😎\n"
        "🔗 {link}"
    )},
    {"key": "friend_text", "text": (
        "👀 Eyy, do'stim! Bittagina havola tashlasang <b>{tier1} Kitobcha</b> tushadi-ku...\n"
        "Nimani kutyapsan? 😅\n🔗 {link}"
    )},
    {"key": "drama", "text": (
        "🎬 <b>Dramatik eslatma:</b>\n"
        "Bir kuni kelib \"{title}'da nega ko'proq qatnashmadim\" demaslik uchun —\n"
        "ayni damda havola tashla! ⏳ {left} qoldi.\n🔗 {link}"
    )},
    {"key": "scoreboard", "text": (
        "📊 Hisob-kitob:\n"
        "👥 Takliflar: <b>{referrals}</b> | 🪙 Yig'ilgan: <b>{earned} Kitobcha</b>\n"
        "Rekordni yangilaymizmi? 🚀\n🔗 {link}"
    )},
    {"key": "tier2_dream", "text": (
        "🤯 Sirni aytaymi? <b>{cap} tadan</b> oshgach har do'st <b>{tier2} Kitobcha</b>!\n"
        "Ya'ni 2 baravar. Maqsad — {cap}+! 💪\n🔗 {link}"
    )},
    {"key": "coffee", "text": (
        "☕️ Qahva ichayotgan bo'lsangiz — bir qultum orasida havola tashlang.\n"
        "Do'st qo'shildi = <b>{tier1} Kitobcha</b> cho'ntakda 😏\n🔗 {link}"
    )},
    {"key": "book_pun", "text": (
        "📚 Kitob \"sahifama-sahifa\", {title} esa \"do'stma-do'st\" yutuq beradi!\n"
        "Keyingi bobni yozaylik 👇\n🔗 {link}"
    )},
    {"key": "leaderboard_tease", "text": (
        "🏆 Kimdir hozir do'st taklif qilib <b>{tier2} Kitobcha</b> yig'yapti...\n"
        "Siz orqada qolib ketmang! 🔗 {link}"
    )},
    {"key": "shop_window", "text": (
        "🛍 Do'kon vitrinasiga qarab qo'ydingizmi? Sovg'alar sizni kutyapti!\n"
        "Balansingiz <b>{balance} Kitobcha</b> — yana to'ldiramiz 🤝\n🔗 {link}"
    )},
    {"key": "rocket", "text": (
        "🚀 3...2...1... <b>Uchdik!</b>\n"
        "Bitta havola = <b>{tier1} Kitobcha</b>. Uchirdikmi? 🔗 {link}"
    )},
    {"key": "gentle", "text": (
        "🌿 Shoshilmang, lekin... {title} tugashiga <b>{left}</b> qoldi.\n"
        "Bittagina do'st taklif qilsangiz ham yaxshi-ku 🙂\n🔗 {link}"
    )},
    {"key": "challenge_you", "text": (
        "😼 Spor boylashamizmi? Bugun kamida 1 ta do'st taklif qila olmaysiz!\n"
        "...yoki qila olasizmi? 😏 <b>{tier1} Kitobcha</b> tikilgan!\n🔗 {link}"
    )},
    {"key": "math", "text": (
        "🧮 Oddiy matematika:\n"
        "5 do'st × <b>{tier1}</b> = ko'p Kitobcha. 15 do'st-chi? 🤑\n🔗 {link}"
    )},
    {"key": "story", "text": (
        "📖 \"Bir bor ekan, bir yo'q ekan, bir kitobxon havola tashlabdi...\"\n"
        "Davomini siz yozing 👇 <b>{tier1} Kitobcha</b> sizni kutyapti.\n🔗 {link}"
    )},
    {"key": "alarm", "text": (
        "🚨 <b>Diqqat!</b> Bu oddiy eslatma emas — bu imkoniyat!\n"
        "{title} <b>{left}</b> dan keyin yopiladi. 🔗 {link}"
    )},
    {"key": "proud", "text": (
        "🥹 Allaqachon <b>{referrals}</b> ta do'st va <b>{earned} Kitobcha</b>!\n"
        "Davom etsangiz sovg'alar yanada zo'rlashadi 🎁\n🔗 {link}"
    )},
    {"key": "secret", "text": (
        "🤫 Faqat sizga aytaman: hozir havola tashlaganlar eng ko'p yutyapti.\n"
        "<b>{tier1} Kitobcha</b> — bittagina do'st uchun. 🔗 {link}"
    )},
    {"key": "fire", "text": (
        "🔥🔥🔥 {title} hali ham qizg'in davom etmoqda!\n"
        "Har taklif <b>{tier1} Kitobcha</b>, {cap}+ da esa <b>{tier2}</b>! 🔗 {link}"
    )},
    {"key": "missed_call", "text": (
        "📞 <i>1 ta o'tkazib yuborilgan imkoniyat</i>\n"
        "Qo'ng'iroqni emas — havolani qaytaring 😄 🔗 {link}"
    )},
    {"key": "gift_focus", "text": (
        "🎁 Do'kondagi eng zo'r sovg'a kimga? Ko'p Kitobcha yig'ganga!\n"
        "Hozir <b>{balance} Kitobcha</b>. Maqsad sari 💪 🔗 {link}"
    )},
    {"key": "team", "text": (
        "🤝 Do'stingizni ham kitobxonlar safiga qo'shing — ham savob, ham "
        "<b>{tier1} Kitobcha</b>!\n🔗 {link}"
    )},
    {"key": "last_push", "text": (
        "🏁 Marra yaqin! {title} tugashiga <b>{left}</b>.\n"
        "Oxirgi zarba — yana bir do'st! <b>{tier1} Kitobcha</b> 🔗 {link}"
    )},
    {"key": "wink", "text": (
        "😉 Pssst... havola hali ham ishlayapti. Sinab ko'rasizmi?\n"
        "<b>{tier1} Kitobcha</b> bir bosishda. 🔗 {link}"
    )},
]


def pick_reminder(used_keys):
    """Pick a template not in used_keys. When the pool is exhausted, recycle.
    Returns (key, template_dict)."""
    used = set(used_keys or [])
    fresh = [t for t in BOOM_REMINDER_POOL if t["key"] not in used]
    pool = fresh or BOOM_REMINDER_POOL
    choice = random.choice(pool)
    return choice["key"], choice
