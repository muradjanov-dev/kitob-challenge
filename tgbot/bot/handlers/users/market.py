"""Kitob Challenge Market — bot-chat menu for the 5 Market perks defined in
tgbot/services/market.py. Pure chat UI (inline buttons), no WebApp — see
that module's docstring for why this is separate from the ShopProduct/Mini
App shop.

Private-chat only: every handler here checks it isn't running inside a
group (see _is_private / _redirect_to_private) — a group announcement's
inline button must deep-link into the bot's DM instead of firing the menu
into the group itself.
"""
import logging
from io import BytesIO

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.services import market as market_service

logger = logging.getLogger(__name__)


def _is_private(call: types.CallbackQuery) -> bool:
    return call.message.chat.type == "private"


async def _redirect_to_private(call: types.CallbackQuery):
    """A Market button was tapped inside a group — bounce the user to a DM
    with the bot instead of posting balances/purchases into the group."""
    from tgbot.tasks import _get_bot_username

    await call.answer(
        "🔒 Market faqat botning shaxsiy chatida ishlaydi!",
        show_alert=True,
    )
    username = await sync_to_async(_get_bot_username, thread_sensitive=True)()
    if username:
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
            text="🎪 Botga o'tish", url=f"https://t.me/{username}?start=market",
        ))
        try:
            await call.message.answer("👇", reply_markup=kb)
        except Exception:
            pass


def _market_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="🎒 Mening yutuq zahiram", callback_data="market:stash"))
    for key, item in market_service.ITEMS.items():
        kb.add(InlineKeyboardButton(
            text=f"{item['emoji']} {item['title']} — {item['price']} 🪙",
            callback_data=f"market:view:{key}",
        ))
    kb.add(InlineKeyboardButton(text="🛍 Do'kon mahsulotlari", callback_data="market:shop_products"))
    kb.add(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="market:home"))
    return kb


@dp.callback_query_handler(lambda c: c.data == "market:shop_products")
async def market_show_shop_products(call: types.CallbackQuery):
    """Preview of the Mini App shop's live catalog, right in the chat --
    actually buying still happens in the shop itself (atomic balance/stock
    handling, images, admin notify are already solid there; no reason to
    fork a second purchase path here). This is a discovery surface with a
    button straight into it."""
    if not _is_private(call):
        await _redirect_to_private(call)
        return
    await call.answer()

    @sync_to_async
    def _load():
        from tgbot.models import ShopProduct
        products = list(ShopProduct.objects.filter(is_active=True).order_by("sort_order", "-created_at"))
        products.sort(key=lambda p: not p.is_available)
        return products[:20]

    products = await _load()
    if not products:
        await call.message.answer("🛍 Hozircha do'konda mahsulot yo'q.")
        return

    lines = ["🛍 <b>Do'kon mahsulotlari</b>\n"]
    for p in products:
        if p.is_available:
            stock = "" if p.stock_qty is None else f" — {p.stock_qty} ta qoldi"
            lines.append(f"• <b>{p.name}</b> — {p.price_kitobcha} 🪙{stock}")
        else:
            lines.append(f"• <s>{p.name}</s> — tugadi")
    lines.append("\n👇 Sotib olish uchun do'konni oching:")

    from src.settings import WEB_DOMAIN
    from aiogram.types import WebAppInfo
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="🛍 Do'konni ochish", web_app=WebAppInfo(url=f"{WEB_DOMAIN}/shop/")))
    kb.add(InlineKeyboardButton(text="🔙 Marketga qaytish", callback_data="menu:market"))
    await call.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "market:stash")
async def market_show_stash(call: types.CallbackQuery):
    """Sirli quti'dan yig'ilgan, hali ishlatilmagan mukofotlar — har biri qanday
    ishlashini ham tushuntiradi, chunki bu tokenlar avtomatik ishlatiladi
    (foydalanuvchi alohida "faollashtirish" tugmasini bosishi shart emas)."""
    if not _is_private(call):
        await _redirect_to_private(call)
        return
    await call.answer()
    user = await aget_user(call.from_user.id)
    if not user:
        await call.message.answer("Avval /start bosing")
        return

    freeze = user.streak_freeze_count or 0
    lives = user.bonus_survival_lives or 0
    tickets = user.bonus_free_game_entries or 0
    discount = user.next_market_discount_pct or 0

    lines = ["🎒 <b>Mening yutuq zahiram</b>\n"]
    lines.append(
        f"🛡 <b>Streak muzlatish:</b> {freeze} ta\n"
        "<i>Hisobot yubormay qolib ketgan birinchi kuningizga avtomatik "
        "ishlatiladi — ketma-ketligingiz (streak) buzilmaydi. Hech narsa bosish shart emas.</i>"
    )
    lines.append(
        f"\n❤️ <b>Qo'shimcha jon (Omon qolish):</b> {lives} ta\n"
        "<i>Keyingi \"Omon qolish\" o'yiniga qo'shilganingizda avtomatik qo'shiladi.</i>"
    )
    lines.append(
        f"\n🎟 <b>Jonli o'yin bileti:</b> {tickets} ta\n"
        "<i>Har qanday jonli o'yinga (Zanjiri, Qal'a, Viktorina va h.k.) kirishda "
        "25 Kitobcha o'rniga avtomatik shu biletdan ishlatiladi.</i>"
    )
    lines.append(
        f"\n💸 <b>Market chegirmasi:</b> {discount}%\n"
        "<i>Keyingi Marketdan xarid qilganingizda narxdan avtomatik ayiriladi.</i>"
    )
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="🔙 Marketga qaytish", callback_data="menu:market"))
    await call.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "market:home")
async def market_go_home(call: types.CallbackQuery):
    from tgbot.bot.handlers.users.menu_router import send_main_menu

    await call.answer()
    user = await aget_user(call.from_user.id)
    await send_main_menu(call.message, user)


async def show_market_menu(message: types.Message, user):
    balance = int(user.ball or 0)
    text = (
        "🎪 <b>Kitob Challenge Market</b>\n\n"
        f"Balansingiz: <b>{balance} 🪙 Kitobcha</b>\n\n"
        "Kitobchalaringizni quyidagi xizmatlarga sarflashingiz mumkin — "
        "har biri haqida batafsil bilish uchun ustiga bosing:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=_market_menu_kb())


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("market:view:"))
async def market_view_item(call: types.CallbackQuery):
    if not _is_private(call):
        await _redirect_to_private(call)
        return
    await call.answer()
    key = call.data.split(":", 2)[2]
    item = market_service.ITEMS.get(key)
    if not item:
        await call.message.answer("Noma'lum xizmat.")
        return
    user = await aget_user(call.from_user.id)
    if not user:
        await call.message.answer("Avval /start bosing")
        return
    balance = int(user.ball or 0)
    text = (
        f"{item['emoji']} <b>{item['title']}</b>\n\n"
        f"{item['description']}\n\n"
        f"💰 Narxi: <b>{item['price']} Kitobcha</b>\n"
        f"💳 Balansingiz: <b>{balance} Kitobcha</b>"
    )

    sold_out = False
    if key == market_service.LEADERBOARD_SPONSOR:
        slots = await sync_to_async(
            market_service.leaderboard_sponsor_slots_left_today, thread_sensitive=True
        )()
        if slots <= 0:
            sold_out = True
            text += "\n\n🚫 <b>Bugungi 7 ta joy tugadi</b> — ertaga urinib ko'ring!"
        else:
            text += f"\n\n🔥 Bugun qolgan joy: <b>{slots}/7</b>"

    kb = InlineKeyboardMarkup(row_width=1)
    if balance >= item["price"] and not sold_out:
        kb.add(InlineKeyboardButton(text="✅ Sotib olish", callback_data=f"market:confirm:{key}"))
    kb.add(InlineKeyboardButton(text="🔙 Marketga qaytish", callback_data="menu:market"))
    await call.message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("market:confirm:"))
async def market_confirm_item(call: types.CallbackQuery):
    """One extra tap before charging — Kun qahramoni posts publicly and
    Reyting sponsorligi is queued irreversibly, so no purchase here should
    ever fire off a single accidental tap."""
    if not _is_private(call):
        await _redirect_to_private(call)
        return
    await call.answer()
    key = call.data.split(":", 2)[2]
    item = market_service.ITEMS.get(key)
    if not item:
        await call.message.answer("Noma'lum xizmat.")
        return
    text = (
        f"{item['emoji']} <b>{item['title']}</b> — <b>{item['price']} Kitobcha</b>ni "
        f"sarflashni tasdiqlaysizmi?\n\nBu amalni bekor qilib bo'lmaydi."
    )
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton(text="✅ Ha, tasdiqlayman", callback_data=f"market:buy:{key}"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"market:view:{key}"),
    )
    await call.message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("market:buy:"))
async def market_buy_item(call: types.CallbackQuery):
    if not _is_private(call):
        await _redirect_to_private(call)
        return
    key = call.data.split(":", 2)[2]
    item = market_service.ITEMS.get(key)
    if not item:
        await call.answer("Noma'lum xizmat.", show_alert=True)
        return
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer()
        await call.message.answer("Avval /start bosing")
        return

    # Scarcity cap: re-check right before charging so a last-second sellout
    # doesn't take someone's Kitobcha for nothing.
    if key == market_service.LEADERBOARD_SPONSOR:
        slots = await sync_to_async(
            market_service.leaderboard_sponsor_slots_left_today, thread_sensitive=True
        )()
        if slots <= 0:
            await call.answer("Bugungi 7 ta joy allaqachon tugagan 😔", show_alert=True)
            return

    ok = await sync_to_async(market_service.charge, thread_sensitive=True)(user, item["price"])
    if not ok:
        await call.answer("Kitobchangiz yetarli emas 😔", show_alert=True)
        return
    await call.answer("✅ Xarid muvaffaqiyatli!")

    # Logged per-branch below (not blanket here) so a Reyting sponsorligi
    # race-loss + refund is never counted as a fulfilled purchase.
    if key != market_service.LEADERBOARD_SPONSOR:
        await sync_to_async(market_service.log_purchase, thread_sensitive=True)(user, key, item["price"])

    if key == market_service.STREAK_FREEZE:
        remaining = await sync_to_async(market_service.apply_streak_freeze_purchase, thread_sensitive=True)(user)
        await call.message.answer(
            f"🛡 <b>Streak muzlatish</b> sotib olindi!\n"
            f"Endi jami <b>{remaining}</b> ta token bor — birinchi bo'sh kuningizga "
            "avtomatik ishlatiladi.",
            parse_mode="HTML",
        )

    elif key == market_service.MYSTERY_BOX:
        result, wants_certificate = await sync_to_async(
            market_service.resolve_mystery_box, thread_sensitive=True
        )(user)
        await call.message.answer(f"🎁 <b>Sirli quti ochildi!</b>\n\n{result}", parse_mode="HTML")
        if wants_certificate:
            try:
                png_bytes = await sync_to_async(market_service.generate_certificate, thread_sensitive=True)(user)
                photo = types.InputFile(BytesIO(png_bytes), filename="sertifikat.png")
                await call.message.answer_photo(photo, caption="📜 Sizning bepul sertifikatingiz!")
            except Exception:
                logger.exception("mystery_box certificate generation failed for user_id=%s", user.id)
                await call.message.answer(
                    "⚠️ Sertifikatni tayyorlashda xatolik yuz berdi. Iltimos, birozdan so'ng "
                    "\"📜 Shaxsiy sertifikat\" xizmatidan qayta urinib ko'ring yoki admin bilan bog'laning — "
                    "mukofotingiz (bepul sertifikat huquqi) yo'qolmagan."
                )

    elif key == market_service.CERTIFICATE:
        try:
            png_bytes = await sync_to_async(market_service.generate_certificate, thread_sensitive=True)(user)
            photo = types.InputFile(BytesIO(png_bytes), filename="sertifikat.png")
            await call.message.answer_photo(photo, caption="📜 Sizning shaxsiy sertifikatingiz tayyor!")
        except Exception:
            logger.exception("certificate purchase generation failed for user_id=%s", user.id)
            await sync_to_async(market_service.charge, thread_sensitive=True)(user, -item["price"])
            await call.message.answer(
                "⚠️ Sertifikatni tayyorlashda xatolik yuz berdi. Kitobchangiz qaytarildi — "
                "birozdan so'ng qayta urinib ko'ring."
            )

    elif key == market_service.DAY_HERO:
        from tgbot.tasks import _announce_targets
        text = (
            f"🌟 <b>KUN QAHRAMONI!</b> 🌟\n\n"
            f"Bugun <b>{user.full_name or 'Kitobxon'}</b> o'zini faol va g'ayratli "
            f"kitobxon sifatida ko'rsatmoqda! 🔥📚\n\n"
            f"Uni qo'llab-quvvatlang — 👏 yozing yoki tabriklang!"
        )
        targets = await sync_to_async(_announce_targets, thread_sensitive=True)()
        for chat_id, thread_id in targets:
            try:
                await bot.send_message(chat_id, text, parse_mode="HTML", message_thread_id=thread_id)
            except Exception as e:
                print(f"market day_hero announce {chat_id}: {e}")
        await call.message.answer("🌟 E'loningiz guruhga joylandi!")

    elif key == market_service.LEADERBOARD_SPONSOR:
        queued = await sync_to_async(market_service.queue_leaderboard_sponsor, thread_sensitive=True)(user)
        if queued:
            await sync_to_async(market_service.log_purchase, thread_sensitive=True)(user, key, item["price"])
            await call.message.answer(
                "🏷 Ajoyib! Keyingi \"Top kitobxonlar\" e'lonida ismingiz sponsor "
                "sifatida ko'rsatiladi."
            )
        else:
            # Lost the race against another buyer in the instant between the
            # slots check above and this insert — refund immediately.
            await sync_to_async(market_service.charge, thread_sensitive=True)(user, -item["price"])
            await call.message.answer(
                "😔 Afsuski, bugungi 7 ta joy siz tasdiqlayotgan payt tugab qoldi. "
                "Kitobchangiz qaytarildi — ertaga urinib ko'ring!"
            )
