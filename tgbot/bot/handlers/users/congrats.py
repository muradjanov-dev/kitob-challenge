"""Tabriklash inline-button flow.

When a user clicks 🎉 Tabriklash on a broadcast DM:
    1. Records a Congratulation row (idempotent — one per user/event).
    2. Updates the button on the clicker's message to show live count.
    3. Shows a brief inspiring toast to the clicker (auto-disappears ~3 s).
    4. Deletes the congrats message from the clicker's DM after 1 minute
       (keeps the DM clean — user already saw it).
"""
import asyncio
import random

from aiogram import types
from aiogram.dispatcher import FSMContext
from asgiref.sync import sync_to_async

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.models import UserAchievement, Congratulation


_CONGRATS_TOASTS = [
    "Tabrikladingiz! 🎉",
    "Yana bir kitobxonga ilhom berdingiz! ✨",
    "Qo'llab-quvvatladingiz! 💪",
    "Bir tabrik — mingta kuch! Kitobxonni ruhlantirdingiz 🌟",
    "Hamjihatlik — gala kuchi! Rahmat sizga! ⚡",
    "Sizning tabrigingiz ularni oldinga undaydi! 🚀",
    "Barakalla! Birga o'samiz! 🌱",
    "Sizning qo'llab-quvvatlashingiz bebaho! 🏆",
    "Bir so'z — katta motivatsiya! 🔥",
    "Kitobxonlar bir-birini ko'taradi! 📚",
]


@sync_to_async
def _record_congrats(ua_id: int, congratulator_id: int):
    """Returns (created, count_total, achiever_telegram_id)."""
    ua = UserAchievement.objects.filter(id=ua_id).select_related("user").first()
    if not ua:
        return False, 0, None
    _, created = Congratulation.objects.get_or_create(
        achievement=ua, congratulator_id=congratulator_id,
    )
    count = Congratulation.objects.filter(achievement=ua).count()
    return created, count, ua.user.telegram_id


async def _delete_message_after(chat_id: int, message_id: int, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


# ── Reader-title nomination congrats (rtc:<winner_tg_id>:<category_key>) ──────
_RT_NOMINATIONS = {
    "night":    ("🌙", "Tungi kitobxon"),
    "morning":  ("🌅", "Saharxez kitobxon"),
    "day":      ("☀️", "Kunduzgi kitobxon"),
    "audio":    ("🎧", "Audio shaydosi"),
    "review":   ("✍️", "So'z ustasi"),
    "giver":    ("🤝", "Sahiy tabriklovchi"),
    "receiver": ("🎁", "Eng ko'p tabriklangan"),
    "streak":   ("🔥", "Eng intizomli"),
}


@sync_to_async
def _claim_congrats_all(ann_id: int, congratulator_tg: int):
    """Register this congratulator on the announcement (idempotent). Returns
    (status, winners) where status is 'ok' | 'already' | 'missing'. winners is a
    list of {"k","t"} excluding the congratulator themselves."""
    from tgbot.models import ReaderTitleAnnouncement
    ann = ReaderTitleAnnouncement.objects.filter(id=ann_id).first()
    if not ann:
        return "missing", []
    congratulators = list(ann.congratulators or [])
    if congratulator_tg in congratulators:
        return "already", []
    congratulators.append(congratulator_tg)
    ReaderTitleAnnouncement.objects.filter(id=ann_id).update(congratulators=congratulators)
    winners = [w for w in (ann.winners or []) if w.get("t") != congratulator_tg]
    return "ok", winners


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("rtc_all:"),
    state="*",
)
async def reader_title_congrats_all(call: types.CallbackQuery, state: FSMContext):
    """Single 'Tabriklash' button on the nominations post — DM every winner that
    this user congratulated them for their nomination."""
    parts = call.data.split(":")
    if len(parts) < 2:
        await call.answer()
        return
    try:
        ann_id = int(parts[1])
    except ValueError:
        await call.answer()
        return

    congratulator = await aget_user(call.from_user.id)
    cong_tg = congratulator.telegram_id if congratulator else call.from_user.id
    status, winners = await _claim_congrats_all(ann_id, cong_tg)

    if status == "missing":
        await call.answer("Bu e'lon eskirgan.", show_alert=True)
        return
    if status == "already":
        await call.answer("Siz allaqachon g'oliblarni tabrikladingiz 🙂", show_alert=True)
        return

    cong_name = (congratulator.full_name if congratulator else None) or "Kitobxon"
    sent = 0
    for w in winners:
        emoji, nom = _RT_NOMINATIONS.get(w.get("k"), ("🏅", "Nominatsiya"))
        try:
            await bot.send_message(
                w["t"],
                f"🎉 <b>{cong_name}</b> sizni «{emoji} {nom}» nominatsiyangiz bilan "
                f"tabrikladi!\n\nTabriklaymiz, davom eting! 📚🔥",
                parse_mode="HTML",
            )
            sent += 1
        except Exception as e:
            print(f"rtc_all DM to {w.get('t')} failed: {e}")

    await call.answer(f"✅ {sent} ta g'olibni tabrikladingiz! 🎉", show_alert=False)


# Back-compat: older nomination posts used a per-winner button (rtc:<tg>:<key>).
@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("rtc:"),
    state="*",
)
async def reader_title_congrats(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer()
        return
    try:
        winner_tg = int(parts[1])
    except ValueError:
        await call.answer()
        return
    key = parts[2]
    emoji, nom = _RT_NOMINATIONS.get(key, ("🏅", "Nominatsiya"))

    congratulator = await aget_user(call.from_user.id)
    if congratulator and str(congratulator.telegram_id) == str(winner_tg):
        await call.answer("O'zingizni tabriklay olmaysiz 🙂", show_alert=True)
        return

    cong_name = (congratulator.full_name if congratulator else None) or "Kitobxon"
    try:
        await bot.send_message(
            winner_tg,
            f"🎉 <b>{cong_name}</b> sizni «{emoji} {nom}» nominatsiyangiz bilan "
            f"tabrikladi!\n\nTabriklar, davom eting! 📚🔥",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"reader_title_congrats DM to {winner_tg} failed: {e}")

    await call.answer(f"✅ {nom} g'olibini tabrikladingiz! 🎉", show_alert=False)


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("congrats:"),
    state="*",
)
async def congrats_handler(call: types.CallbackQuery, state: FSMContext):
    if call.message and call.message.chat.type != types.ChatType.PRIVATE:
        await call.answer()
        return

    try:
        ua_id = int(call.data.split(":", 1)[1])
    except Exception:
        await call.answer()
        return

    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing", show_alert=True)
        return

    created, count_total, achiever_tg_id = await _record_congrats(ua_id, user.id)

    if achiever_tg_id is None:
        await call.answer("❌ Yutuq topilmadi", show_alert=True)
        return

    if not created:
        await call.answer(
            f"Siz allaqachon tabrikladingiz 🙂  (Jami: {count_total} ta tabriklash)",
            show_alert=True,
        )
        return

    # Update button to show live congrats count.
    try:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        new_kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton(
                text=f"🎉 Tabriklash ({count_total})",
                callback_data=f"congrats:{ua_id}",
            )
        )
        await call.message.edit_reply_markup(reply_markup=new_kb)
    except Exception:
        pass

    # Brief inspiring toast (auto-disappears in ~3 s, no modal).
    await call.answer(random.choice(_CONGRATS_TOASTS))

    # Delete the congrats DM 1 minute after clicking — keeps chat clean.
    asyncio.create_task(
        _delete_message_after(call.message.chat.id, call.message.message_id, delay=60)
    )
