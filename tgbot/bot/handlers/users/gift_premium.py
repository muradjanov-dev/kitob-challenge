from html import escape

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType, InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async

from tgbot.bot.loader import dp
from tgbot.bot.utils import aget_user
from tgbot.bot.states.main import GiftPremiumStates, PaymentStates
from tgbot.bot.keyboards.reply import back_keyboard
from tgbot.models import TelegramProfile
from tgbot.bot.handlers.users.payment import (
    PLAN_PRICES, PLAN_DAYS, premium_features_text, payment_info_text,
)

PAGE_SIZE = 15

GIFT_PLAN_LABELS = {
    "premium": "💎 Premium — 1 oy",
    "premium_3mo": "💎 Premium — 3 oy",
    "super": "🌟 Super Premium — 1 oy",
}


def _gift_plan_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    for key, label in GIFT_PLAN_LABELS.items():
        price = PLAN_PRICES[key]
        kb.add(InlineKeyboardButton(f"{label} ({price:,} so'm)", callback_data=f"gift_plan:{key}"))
    kb.add(InlineKeyboardButton("🔙 Bekor qilish", callback_data="gift_cancel"))
    return kb


def _method_kb():
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🆔 Telegram ID orqali", callback_data="gift_method:tid"),
        InlineKeyboardButton("📋 Ro'yxatdan tanlash", callback_data="gift_method:list:0"),
        InlineKeyboardButton("🔙 Bekor qilish", callback_data="gift_cancel"),
    )


def _anon_kb():
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("😎 Anonim", callback_data="gift_anon:1"),
        InlineKeyboardButton("🙋 Ismim ko'rinsin", callback_data="gift_anon:0"),
    )


def _list_nav_kb(page: int, total: int):
    kb = InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"gift_method:list:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"gift_method:list:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton("🔙 Bekor qilish", callback_data="gift_cancel"))
    return kb


@sync_to_async
def _registered_users(exclude_id):
    qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return list(qs.order_by("full_name").values("id", "telegram_id", "full_name"))


@sync_to_async
def _profile_by_id(pk):
    return TelegramProfile.objects.filter(id=pk).first()


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data == "gift_premium_start", state="*")
async def gift_premium_start(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await call.answer()
    await call.message.answer(
        "🎁 <b>Do'stingizga Premium sovg'a qiling!</b>\n\nQaysi tarifni sovg'a qilmoqchisiz?",
        parse_mode="HTML", reply_markup=_gift_plan_kb(),
    )


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data == "gift_cancel", state="*")
async def gift_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await call.answer("Bekor qilindi.")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data.startswith("gift_plan:"), state="*")
async def gift_choose_plan(call: types.CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    if key not in GIFT_PLAN_LABELS:
        await call.answer("Noma'lum tarif.", show_alert=True)
        return
    await state.update_data(
        gift_plan_key=key, gift_price=PLAN_PRICES[key], gift_days=PLAN_DAYS[key],
    )
    await call.answer()
    await call.message.answer(
        f"Tanladingiz: <b>{GIFT_PLAN_LABELS[key]}</b>\n\nEndi kimga sovg'a qilmoqchisiz?",
        parse_mode="HTML", reply_markup=_method_kb(),
    )


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data == "gift_method:tid", state="*")
async def gift_method_tid(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer(
        "🆔 <b>Qabul qiluvchining Telegram ID raqamini kiriting.</b>\n\n"
        "ID'ni qanday topish mumkin?\n"
        "1️⃣ Do'stingiz @userinfobot ga /start yozsin — bot unga ID'sini beradi\n"
        "2️⃣ Yoki orqaga qaytib \"📋 Ro'yxatdan tanlash\"dan foydalaning — ID kerak emas\n\n"
        "Raqamni yuboring (masalan: <code>123456789</code>):",
        parse_mode="HTML",
    )
    await GiftPremiumStates.enter_telegram_id.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=GiftPremiumStates.enter_telegram_id)
async def gift_receive_telegram_id(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❗️ Faqat raqam kiriting (Telegram ID).")
        return

    buyer = await aget_user(telegram_id=message.from_user.id)
    recipient = await aget_user(telegram_id=int(text))
    if not recipient or not recipient.is_registered:
        await message.answer("❗️ Bu ID bilan ro'yxatdan o'tgan foydalanuvchi topilmadi. Qayta urinib ko'ring.")
        return
    if buyer and recipient.id == buyer.id:
        await message.answer("❗️ O'zingizga sovg'a qila olmaysiz 😊 Oddiy \"💎 Premium\" tugmasidan foydalaning.")
        return

    await state.update_data(
        gift_recipient_tid=recipient.telegram_id,
        gift_recipient_name=recipient.full_name or "Kitobxon",
    )
    await message.answer(
        f"✅ Qabul qiluvchi: <b>{escape(recipient.full_name or 'Kitobxon')}</b>\n\n"
        "Sovg'ani <b>anonim</b> yuborasizmi yoki ismingiz ko'rinsinmi?",
        parse_mode="HTML", reply_markup=_anon_kb(),
    )


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data.startswith("gift_method:list:"), state="*")
async def gift_method_list(call: types.CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[2])
    buyer = await aget_user(telegram_id=call.from_user.id)
    rows = await _registered_users(buyer.id if buyer else None)
    if not rows:
        await call.answer("Ro'yxat bo'sh.", show_alert=True)
        return

    await state.update_data(gift_list_rows=rows, gift_list_page=page)
    start = page * PAGE_SIZE
    page_rows = rows[start:start + PAGE_SIZE]
    lines = [f"{start + i + 1}. {escape(r['full_name'] or 'Kitobxon')}" for i, r in enumerate(page_rows)]
    text = (
        f"📋 <b>Ro'yxat</b> ({start + 1}-{start + len(page_rows)} / {len(rows)}):\n\n"
        + "\n".join(lines)
        + "\n\nKerakli kishining RAQAMINI yozib yuboring:"
    )
    await call.answer()
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=_list_nav_kb(page, len(rows)))
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=_list_nav_kb(page, len(rows)))
    await GiftPremiumStates.choose_from_list.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=GiftPremiumStates.choose_from_list)
async def gift_pick_number(message: types.Message, state: FSMContext):
    data = await state.get_data()
    rows = data.get("gift_list_rows") or []
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❗️ Faqat ro'yxatdagi raqamni kiriting.")
        return

    idx = int(text) - 1
    if idx < 0 or idx >= len(rows):
        await message.answer("❗️ Noto'g'ri raqam, qayta urinib ko'ring.")
        return

    picked = rows[idx]
    buyer = await aget_user(telegram_id=message.from_user.id)
    if buyer and picked["id"] == buyer.id:
        await message.answer("❗️ O'zingizga sovg'a qila olmaysiz 😊 Oddiy \"💎 Premium\" tugmasidan foydalaning.")
        return

    await state.update_data(
        gift_recipient_tid=picked["telegram_id"],
        gift_recipient_name=picked["full_name"] or "Kitobxon",
    )
    await message.answer(
        f"✅ Qabul qiluvchi: <b>{escape(picked['full_name'] or 'Kitobxon')}</b>\n\n"
        "Sovg'ani <b>anonim</b> yuborasizmi yoki ismingiz ko'rinsinmi?",
        parse_mode="HTML", reply_markup=_anon_kb(),
    )


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data.startswith("gift_anon:"), state="*")
async def gift_choose_anonymity(call: types.CallbackQuery, state: FSMContext):
    anonymous = call.data.split(":", 1)[1] == "1"
    data = await state.get_data()
    plan_key = data.get("gift_plan_key")
    price = data.get("gift_price")
    days = data.get("gift_days")
    recipient_name = data.get("gift_recipient_name", "Kitobxon")

    if not (plan_key and price and days and data.get("gift_recipient_tid")):
        await call.answer("Sessiya eskirgan, qaytadan boshlang.", show_alert=True)
        await state.finish()
        return

    await state.update_data(
        is_gift=True,
        gift_anonymous=anonymous,
        payment_price=price,
        payment_plan=plan_key,
        payment_plan_days=days,
    )

    user = await aget_user(telegram_id=call.from_user.id)
    lang = user.language if user else "uz"

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer()
    await call.message.answer(
        f"🎁 <b>{escape(recipient_name)}</b> uchun sovg'a: <b>{GIFT_PLAN_LABELS[plan_key]}</b>\n"
        f"👤 Ko'rinishi: {'Anonim' if anonymous else 'Ismingiz bilan'}\n\n"
        + payment_info_text(lang, price),
        parse_mode="HTML", reply_markup=back_keyboard,
    )
    await PaymentStates.receipt.set()
