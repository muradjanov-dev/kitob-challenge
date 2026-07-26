"""Shop admin — manage ShopProduct rows directly from the bot.

Wizard flow for ➕ Mahsulot qo'shish:
  name → description (or /skip) → image (or /skip) → price → stock (or
  /unlimited) → confirm. /bekor at any step aborts.

List view shows up to 20 most recent products with quick toggle/delete
actions. For deep editing (long descriptions, fine-tuning sort order),
the Django admin URL is still the right place — the bot UI is for the
common case of dropping in new prizes fast.
"""
import io
import re

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.utils import timezone

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.bot.states.main import ShopProductCreateState, ShopProductEditState
from tgbot.models import ShopProduct


def _is_admin(user) -> bool:
    return bool(user and getattr(user, "is_admin", False))


def _shop_admin_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data="shopadm:add"))
    kb.add(InlineKeyboardButton("📋 Mahsulotlar ro'yxati", callback_data="shopadm:list:0"))
    kb.add(InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="menu:admin"))
    return kb


# ──────────────────────────────────────────────────────────────────────────
# Entry: admin panel → 🛒 Do'kon boshqaruvi
#
# Wired into admin_panel.admin_inline_router (the central admin:* router),
# NOT as its own @dp handler — aiogram dispatches the first matching
# handler, and the router's broader startswith("admin:") filter would
# always win, sending users to its "Noma'lum amal." fallback.
# ──────────────────────────────────────────────────────────────────────────
async def shop_admin_menu(message: types.Message, user):
    """Show the shop admin menu. `user` is the TelegramProfile of the caller;
    is_admin is already enforced by the router."""
    await message.answer(
        "🛒 <b>Do'kon boshqaruvi</b>\n\n"
        "Bot orqali mahsulot qo'shish, ko'rish va o'chirish mumkin. "
        "Murakkab tahrirlar uchun Django admin paneldan foydalaning.",
        parse_mode="HTML",
        reply_markup=_shop_admin_menu_kb(),
    )


# ──────────────────────────────────────────────────────────────────────────
# Add product wizard
# ──────────────────────────────────────────────────────────────────────────
async def _wizard_abort_text(message: types.Message, state: FSMContext, text: str):
    await state.finish()
    await message.answer(text, reply_markup=_shop_admin_menu_kb())


_WIZARD_STATES = [
    ShopProductCreateState.name,
    ShopProductCreateState.description,
    ShopProductCreateState.image,
    ShopProductCreateState.price,
    ShopProductCreateState.stock,
]


@dp.callback_query_handler(lambda c: c.data == "shopadm:add", state="*")
async def shopadm_add_start(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    await call.answer()
    await ShopProductCreateState.name.set()
    await call.message.answer(
        "1️⃣ <b>Mahsulot nomini yuboring</b>\n\n"
        "Masalan: <code>Sertifikat 50 000 so'm</code>\n\n"
        "Bekor qilish: /bekor",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["bekor"], state=_WIZARD_STATES)
async def shopadm_cancel(message: types.Message, state: FSMContext):
    await _wizard_abort_text(message, state, "❌ Bekor qilindi.")


@dp.message_handler(state=ShopProductCreateState.name, content_types=types.ContentTypes.TEXT)
async def shopadm_get_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Nom juda qisqa. Qaytadan yuboring (yoki /bekor).")
        return
    if len(name) > 120:
        await message.answer(f"Nom 120 belgidan oshmasligi kerak (hozir {len(name)}). Qaytadan.")
        return
    await state.update_data(name=name)
    await ShopProductCreateState.description.set()
    await message.answer(
        "2️⃣ <b>Tavsifni yuboring</b>\n\n"
        "Bu sotib olish oynasida ko'rinadi. O'tkazib yuborish: /skip",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["skip"], state=ShopProductCreateState.description)
async def shopadm_skip_description(message: types.Message, state: FSMContext):
    await state.update_data(description="")
    await _ask_image(message, state)


@dp.message_handler(state=ShopProductCreateState.description, content_types=types.ContentTypes.TEXT)
async def shopadm_get_description(message: types.Message, state: FSMContext):
    desc = (message.text or "").strip()
    if len(desc) > 2000:
        await message.answer(f"Tavsif 2000 belgidan oshmasligi kerak (hozir {len(desc)}). Qaytadan.")
        return
    await state.update_data(description=desc)
    await _ask_image(message, state)


async def _ask_image(message: types.Message, state: FSMContext):
    await ShopProductCreateState.image.set()
    await message.answer(
        "3️⃣ <b>Rasm yuboring</b>\n\n"
        "Mahsulot kartochkasi uchun rasm. O'tkazib yuborish: /skip",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["skip"], state=ShopProductCreateState.image)
async def shopadm_skip_image(message: types.Message, state: FSMContext):
    await state.update_data(image_file_id=None)
    await _ask_price(message, state)


@dp.message_handler(state=ShopProductCreateState.image, content_types=types.ContentTypes.PHOTO)
async def shopadm_get_image(message: types.Message, state: FSMContext):
    # Biggest photo size = last entry. Store the file_id; we resolve to bytes
    # at commit time so a user who restarts the wizard doesn't accumulate
    # half-downloaded files on disk.
    photo = message.photo[-1]
    await state.update_data(image_file_id=photo.file_id)
    await _ask_price(message, state)


@dp.message_handler(state=ShopProductCreateState.image)
async def shopadm_image_invalid(message: types.Message, state: FSMContext):
    await message.answer("Iltimos rasm yuboring yoki /skip.")


async def _ask_price(message: types.Message, state: FSMContext):
    await ShopProductCreateState.price.set()
    await message.answer(
        "4️⃣ <b>Narxni Kitobchada yuboring</b>\n\n"
        "Faqat raqam, masalan: <code>250</code>",
        parse_mode="HTML",
    )


@dp.message_handler(state=ShopProductCreateState.price, content_types=types.ContentTypes.TEXT)
async def shopadm_get_price(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Faqat musbat butun son. Qaytadan yuboring (yoki /bekor).")
        return
    price = int(raw)
    if price < 1 or price > 10_000_000:
        await message.answer("Narx 1 va 10 000 000 oralig'ida bo'lishi kerak. Qaytadan.")
        return
    await state.update_data(price=price)
    await ShopProductCreateState.stock.set()
    await message.answer(
        "5️⃣ <b>Zaxira sonini yuboring</b>\n\n"
        "Cheksiz uchun: /unlimited\n"
        "Yoki raqam, masalan: <code>10</code>",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["unlimited"], state=ShopProductCreateState.stock)
async def shopadm_stock_unlimited(message: types.Message, state: FSMContext):
    await state.update_data(stock=None)
    await _show_preview(message, state)


@dp.message_handler(state=ShopProductCreateState.stock, content_types=types.ContentTypes.TEXT)
async def shopadm_get_stock(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Faqat musbat butun son yoki /unlimited.")
        return
    stock = int(raw)
    if stock < 0 or stock > 1_000_000:
        await message.answer("Son 0 va 1 000 000 oralig'ida bo'lishi kerak.")
        return
    await state.update_data(stock=stock)
    await _show_preview(message, state)


async def _show_preview(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name = data.get("name", "")
    desc = data.get("description", "") or "—"
    price = data.get("price", 0)
    stock = data.get("stock")
    stock_label = "Cheksiz" if stock is None else str(stock)
    has_img = "Ha" if data.get("image_file_id") else "Yo'q"
    text = (
        "📋 <b>Mahsulotni tasdiqlang</b>\n\n"
        f"<b>Nomi:</b> {_escape(name)}\n"
        f"<b>Tavsif:</b> {_escape(desc)}\n"
        f"<b>Rasm:</b> {has_img}\n"
        f"<b>Narx:</b> {price} Kitobcha\n"
        f"<b>Zaxira:</b> {stock_label}"
    )
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("✅ Saqlash", callback_data="shopadm:save"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="shopadm:cancel"),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@sync_to_async
def _create_product_sync(name, description, price, stock):
    return ShopProduct.objects.create(
        name=name,
        description=description or "",
        price_kitobcha=price,
        stock_qty=stock,
        is_active=True,
    )


@sync_to_async
def _attach_image_sync(product: ShopProduct, filename: str, blob: bytes):
    product.image.save(filename, ContentFile(blob), save=True)


@dp.callback_query_handler(lambda c: c.data == "shopadm:save", state=ShopProductCreateState.states)
async def shopadm_save(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data.get("name") or ""
    description = data.get("description") or ""
    price = int(data.get("price") or 0)
    stock = data.get("stock")
    file_id = data.get("image_file_id")
    if not name or price < 1:
        await call.answer("Maydonlar to'liq emas — qaytadan boshlang.", show_alert=True)
        await state.finish()
        return

    await call.answer("Saqlanmoqda…")
    product = await _create_product_sync(name, description, price, stock)

    if file_id:
        try:
            buf: io.BytesIO = await bot.download_file_by_id(file_id)
            buf.seek(0)
            ts = int(timezone.now().timestamp())
            await _attach_image_sync(product, f"shop_{product.id}_{ts}.jpg", buf.read())
        except Exception as e:
            print(f"shop_admin: image attach failed for product {product.id}: {e}")
            await call.message.answer("⚠️ Rasm yuklashda xatolik (mahsulot rasmsiz saqlandi).")

    await state.finish()
    stock_label = "cheksiz" if product.stock_qty is None else str(product.stock_qty)
    await call.message.answer(
        "✅ <b>Mahsulot qo'shildi!</b>\n\n"
        f"<b>{_escape(product.name)}</b>\n"
        f"💰 {product.price_kitobcha} Kitobcha • 📦 {stock_label}",
        parse_mode="HTML",
        reply_markup=_shop_admin_menu_kb(),
    )

    await _announce_new_product_to_groups(product)


async def _announce_new_product_to_groups(product: ShopProduct):
    """New shop items are announced to the groups, not DMed to individual
    users — the shop is visible to everyone there and a group post is the
    natural "look what's new" moment."""
    from tgbot.tasks import _announce_targets
    from tgbot.bot.loader import bot as _bot

    desc = (product.description or "").strip()
    desc_line = f"\n{_escape(desc)}\n" if desc else ""
    stock_label = "cheksiz" if product.stock_qty is None else str(product.stock_qty)
    text = (
        "🛍 <b>Do'konga yangi mahsulot qo'shildi!</b>\n\n"
        f"<b>{_escape(product.name)}</b>\n"
        f"{desc_line}\n"
        f"💰 <b>{product.price_kitobcha} Kitobcha</b> • 📦 {stock_label}\n\n"
        "Sotib olish uchun: «🛒 Do'kon» bo'limiga o'ting!"
    )

    for gid, tid in _announce_targets():
        try:
            if product.image:
                await _bot.send_photo(
                    gid, types.InputFile(product.image.path),
                    caption=text, parse_mode="HTML", message_thread_id=tid,
                )
            else:
                await _bot.send_message(gid, text, parse_mode="HTML",
                                         disable_web_page_preview=True, message_thread_id=tid)
        except Exception as e:
            print(f"shop_admin: new product group announce to {gid} failed: {e}")


@dp.callback_query_handler(lambda c: c.data == "shopadm:cancel", state=ShopProductCreateState.states)
async def shopadm_cancel_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.finish()
    await call.message.answer("❌ Bekor qilindi.", reply_markup=_shop_admin_menu_kb())


# ──────────────────────────────────────────────────────────────────────────
# List products with quick actions (toggle active / delete)
# ──────────────────────────────────────────────────────────────────────────
@sync_to_async
def _list_products_sync(limit=20):
    return list(
        ShopProduct.objects
        .order_by("sort_order", "-created_at")
        .values("id", "name", "price_kitobcha", "stock_qty", "is_active")[:limit]
    )


def _list_kb(rows) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=3)
    if not rows:
        kb.row(InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data="shopadm:add"))
        kb.row(InlineKeyboardButton("🔙 Orqaga", callback_data="admin:shop"))
        return kb
    for r in rows:
        status_icon = "✅" if r["is_active"] else "⏸"
        stock = "∞" if r["stock_qty"] is None else r["stock_qty"]
        title = f"{status_icon} {r['name'][:24]} • {r['price_kitobcha']}🪙 • {stock}📦"
        kb.row(InlineKeyboardButton(title, callback_data=f"shopadm:view:{r['id']}"))
    kb.row(
        InlineKeyboardButton("➕ Qo'shish", callback_data="shopadm:add"),
        InlineKeyboardButton("🔙 Orqaga", callback_data="admin:shop"),
    )
    return kb


@dp.callback_query_handler(lambda c: c.data.startswith("shopadm:list:"), state="*")
async def shopadm_list(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    await call.answer()
    rows = await _list_products_sync()
    if not rows:
        await call.message.answer(
            "📋 Mahsulotlar yo'q.\n\nBirinchi mahsulotni qo'shing:",
            reply_markup=_list_kb(rows),
        )
        return
    await call.message.answer(
        f"📋 <b>Mahsulotlar</b> ({len(rows)} ta)\n\n"
        "Birini tanlang — boshqarish tugmalari ochiladi:",
        parse_mode="HTML",
        reply_markup=_list_kb(rows),
    )


@sync_to_async
def _get_product_sync(pid: int):
    return ShopProduct.objects.filter(id=pid).first()


def _product_card_kb(p: ShopProduct) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    toggle_label = "⏸ O'chirish" if p.is_active else "▶️ Yoqish"
    kb.row(
        InlineKeyboardButton("🖼 Rasmni yangilash", callback_data=f"shopadm:editimg:{p.id}"),
    )
    kb.row(
        InlineKeyboardButton(toggle_label, callback_data=f"shopadm:toggle:{p.id}"),
        InlineKeyboardButton("🗑 O'chirish", callback_data=f"shopadm:delete:{p.id}"),
    )
    kb.row(InlineKeyboardButton("📋 Ro'yxatga qaytish", callback_data="shopadm:list:0"))
    return kb


@dp.callback_query_handler(lambda c: c.data.startswith("shopadm:view:"), state="*")
async def shopadm_view(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    pid = int(call.data.split(":")[-1])
    p = await _get_product_sync(pid)
    if not p:
        await call.answer("Topilmadi", show_alert=True)
        return
    await call.answer()
    stock_label = "Cheksiz" if p.stock_qty is None else str(p.stock_qty)
    status = "✅ Aktiv" if p.is_active else "⏸ Nofaol"
    text = (
        f"🛒 <b>{_escape(p.name)}</b>\n\n"
        f"{_escape(p.description) if p.description else '—'}\n\n"
        f"💰 Narx: <b>{p.price_kitobcha} Kitobcha</b>\n"
        f"📦 Zaxira: <b>{stock_label}</b>\n"
        f"⚙️ Holat: {status}"
    )
    await call.message.answer(text, parse_mode="HTML", reply_markup=_product_card_kb(p))


@sync_to_async
def _toggle_product_sync(pid: int) -> bool | None:
    p = ShopProduct.objects.filter(id=pid).first()
    if not p:
        return None
    p.is_active = not p.is_active
    p.save(update_fields=["is_active"])
    return p.is_active


@dp.callback_query_handler(lambda c: c.data.startswith("shopadm:toggle:"), state="*")
async def shopadm_toggle(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    pid = int(call.data.split(":")[-1])
    now_active = await _toggle_product_sync(pid)
    if now_active is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    await call.answer("✅ Yoqildi" if now_active else "⏸ O'chirildi")
    # Refresh the card.
    p = await _get_product_sync(pid)
    if p:
        stock_label = "Cheksiz" if p.stock_qty is None else str(p.stock_qty)
        status = "✅ Aktiv" if p.is_active else "⏸ Nofaol"
        try:
            await call.message.edit_text(
                f"🛒 <b>{_escape(p.name)}</b>\n\n"
                f"{_escape(p.description) if p.description else '—'}\n\n"
                f"💰 Narx: <b>{p.price_kitobcha} Kitobcha</b>\n"
                f"📦 Zaxira: <b>{stock_label}</b>\n"
                f"⚙️ Holat: {status}",
                parse_mode="HTML",
                reply_markup=_product_card_kb(p),
            )
        except Exception:
            pass


@dp.callback_query_handler(lambda c: c.data.startswith("shopadm:delete:"), state="*")
async def shopadm_delete_confirm(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    pid = int(call.data.split(":")[-1])
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"shopadm:delete_yes:{pid}"),
        InlineKeyboardButton("❌ Bekor", callback_data=f"shopadm:view:{pid}"),
    )
    await call.answer()
    await call.message.answer(
        "🗑 <b>Haqiqatan o'chirilsinmi?</b>\n\n"
        "Eski xaridlar saqlanib qoladi (faqat mahsulot kartochkasi o'chadi).",
        parse_mode="HTML",
        reply_markup=kb,
    )


@sync_to_async
def _delete_product_sync(pid: int) -> bool:
    p = ShopProduct.objects.filter(id=pid).first()
    if not p:
        return False
    p.delete()
    return True


@dp.callback_query_handler(lambda c: c.data.startswith("shopadm:delete_yes:"), state="*")
async def shopadm_delete_yes(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    pid = int(call.data.split(":")[-1])
    ok = await _delete_product_sync(pid)
    await call.answer("🗑 O'chirildi" if ok else "Topilmadi", show_alert=True)
    rows = await _list_products_sync()
    await call.message.answer(
        f"📋 <b>Mahsulotlar</b> ({len(rows)} ta)" if rows else "📋 Mahsulotlar yo'q.",
        parse_mode="HTML",
        reply_markup=_list_kb(rows),
    )


# ──────────────────────────────────────────────────────────────────────────
# Edit-image flow — replace an existing product's image without rebuilding
# the whole row. Single-state FSM: tap button → send photo → done.
# ──────────────────────────────────────────────────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("shopadm:editimg:"), state="*")
async def shopadm_editimg_start(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    pid = int(call.data.split(":")[-1])
    p = await _get_product_sync(pid)
    if not p:
        await call.answer("Mahsulot topilmadi", show_alert=True)
        return
    await call.answer()
    await ShopProductEditState.image.set()
    await state.update_data(edit_product_id=pid)
    await call.message.answer(
        f"🖼 <b>{_escape(p.name)}</b> uchun yangi rasm yuboring.\n\n"
        "Bekor qilish: /bekor",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["bekor"], state=ShopProductEditState.image)
async def shopadm_editimg_cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ Bekor qilindi.", reply_markup=_shop_admin_menu_kb())


@dp.message_handler(state=ShopProductEditState.image, content_types=types.ContentTypes.PHOTO)
async def shopadm_editimg_get(message: types.Message, state: FSMContext):
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if not pid:
        await state.finish()
        await message.answer("Xatolik: mahsulot ID yo'q. Qaytadan urinib ko'ring.")
        return
    p = await _get_product_sync(pid)
    if not p:
        await state.finish()
        await message.answer("Mahsulot topilmadi.")
        return
    photo = message.photo[-1]
    try:
        buf: io.BytesIO = await bot.download_file_by_id(photo.file_id)
        buf.seek(0)
        ts = int(timezone.now().timestamp())
        await _attach_image_sync(p, f"shop_{p.id}_{ts}.jpg", buf.read())
    except Exception as e:
        print(f"shop_admin: editimg attach failed for product {pid}: {e}")
        await state.finish()
        await message.answer("⚠️ Rasm yuklashda xatolik.")
        return
    await state.finish()
    p = await _get_product_sync(pid)  # refresh after save
    await message.answer(
        f"✅ <b>{_escape(p.name)}</b> rasmi yangilandi!\n\n"
        "Mini App'ni qayta oching — yangi rasm ko'rinadi.",
        parse_mode="HTML",
        reply_markup=_shop_admin_menu_kb(),
    )


@dp.message_handler(state=ShopProductEditState.image)
async def shopadm_editimg_invalid(message: types.Message, state: FSMContext):
    await message.answer("Iltimos rasm yuboring yoki /bekor.")


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
_HTML_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}


def _escape(s: str) -> str:
    return re.sub(r"[&<>\"']", lambda m: _HTML_ESCAPE[m.group(0)], s or "")
