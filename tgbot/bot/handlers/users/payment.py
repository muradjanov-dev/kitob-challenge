from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType, InlineKeyboardMarkup, InlineKeyboardButton

from tgbot.bot.utils import get_user
from tgbot.bot.states.main import PaymentStates
from tgbot.bot.loader import dp, bot, gettext as _
from tgbot.bot.keyboards.reply import main_markup, back_keyboard
from tgbot.bot.keyboards.inline import make_send_receipt_to_group_button
from tgbot.bot.consts import ADMIN_GROUP_ID, PAYMENT_THREAD_ID
from tgbot.models import Payment
from django.utils import timezone

# ── Card & pricing config ────────────────────────────────────────────────────
CARD_NUMBER = "5614 6830 0539 3277"
CARD_OWNER  = "N. Murodjonov"
MONTHLY_PRICE = 17_000   # UZS

# ── Premium features list shown to user ─────────────────────────────────────
PREMIUM_FEATURES_UZ = (
    "💎 <b>Premium obuna imtiyozlari:</b>\n\n"
    "✅ Kunlik kitob hisobotlarini cheksiz yuborish\n"
    "✅ Haftalik va oylik reyting jadvallarida qatnashish\n"
    "✅ Maxsus premium badge va unvon\n"
    "✅ Admin bilan bevosita aloqa\n\n"
    f"💳 Narx: <b>{MONTHLY_PRICE:,} UZS / oy</b>"
)

PREMIUM_FEATURES_RU = (
    "💎 <b>Преимущества Premium подписки:</b>\n\n"
    "✅ Неограниченная отправка ежедневных отчётов о книгах\n"
    "✅ Участие в еженедельных и ежемесячных рейтингах\n"
    "✅ Специальный Premium значок и звание\n"
    "✅ Прямая связь с администратором\n\n"
    f"💳 Цена: <b>{MONTHLY_PRICE:,} UZS / месяц</b>"
)


def premium_features_text(language="uz"):
    return PREMIUM_FEATURES_RU if language == "ru" else PREMIUM_FEATURES_UZ


def payment_info_text(language="uz"):
    if language == "ru":
        return (
            f"💳 <b>Реквизиты для оплаты:</b>\n\n"
            f"🏦 Номер карты: <code>{CARD_NUMBER}</code>\n"
            f"👤 Владелец: <b>{CARD_OWNER}</b>\n"
            f"💰 Сумма: <b>{MONTHLY_PRICE:,} UZS</b>\n\n"
            "📸 После оплаты отправьте скриншот чека в этот чат."
        )
    return (
        f"💳 <b>To'lov rekvizitlari:</b>\n\n"
        f"🏦 Karta raqami: <code>{CARD_NUMBER}</code>\n"
        f"👤 Egasi: <b>{CARD_OWNER}</b>\n"
        f"💰 Summa: <b>{MONTHLY_PRICE:,} UZS</b>\n\n"
        "📸 To'lovdan so'ng to'lov cheki rasmini shu chatga yuboring."
    )


# ── Inline keyboards ─────────────────────────────────────────────────────────
def premium_menu_markup(language="uz"):
    if language == "ru":
        return InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("💎 Оформить подписку", callback_data="buy_premium"),
            InlineKeyboardButton("✅ Проверить подписку", callback_data="check_premium"),
        )
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("💎 Obuna sotib olish", callback_data="buy_premium"),
        InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_premium"),
    )


# ── Entry: show premium info ─────────────────────────────────────────────────
@dp.message_handler(
    ChatTypeFilter(ChatType.PRIVATE),
    text=["💎 Premium", "💎 Подписка", "💎 Premium obuna"],
    state="*"
)
async def premium_menu_handler(message: types.Message, state: FSMContext):
    await state.finish()
    user = get_user(telegram_id=message.from_user.id)
    lang = user.language if user else "uz"

    # Check existing active subscription
    active = Payment.objects.filter(
        user=user, status="paid", end_date__gte=timezone.localdate()
    ).first() if user else None

    if active:
        if lang == "ru":
            text = (
                f"✅ <b>У вас активная подписка!</b>\n\n"
                f"📅 Действует до: <b>{active.end_date.strftime('%d.%m.%Y')}</b>"
            )
        else:
            text = (
                f"✅ <b>Sizda faol obuna mavjud!</b>\n\n"
                f"📅 Amal qilish muddati: <b>{active.end_date.strftime('%d.%m.%Y')}</b>"
            )
        await message.answer(text, parse_mode="HTML",
                             reply_markup=main_markup(language=lang))
        return

    await message.answer(
        premium_features_text(lang),
        parse_mode="HTML",
        reply_markup=premium_menu_markup(lang)
    )


# ── Check subscription via inline button ─────────────────────────────────────
@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data == "check_premium")
async def check_premium_callback(call: types.CallbackQuery):
    user = get_user(telegram_id=call.from_user.id)
    lang = user.language if user else "uz"

    active = Payment.objects.filter(
        user=user, status="paid", end_date__gte=timezone.localdate()
    ).first() if user else None

    if active:
        if lang == "ru":
            text = f"✅ <b>Подписка активна</b> до {active.end_date.strftime('%d.%m.%Y')}"
        else:
            text = f"✅ <b>Obuna faol</b> — {active.end_date.strftime('%d.%m.%Y')} gacha"
    else:
        if lang == "ru":
            text = "❌ <b>Активной подписки нет.</b>"
        else:
            text = "❌ <b>Faol obuna yo'q.</b>"

    await call.answer(text, show_alert=True)


# ── Buy: show card info ───────────────────────────────────────────────────────
@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data == "buy_premium")
async def buy_premium_callback(call: types.CallbackQuery, state: FSMContext):
    user = get_user(telegram_id=call.from_user.id)
    lang = user.language if user else "uz"

    await call.message.answer(
        payment_info_text(lang),
        parse_mode="HTML",
        reply_markup=back_keyboard
    )
    await call.answer()
    await PaymentStates.receipt.set()


# ── Legacy: send_receipt callback (from old inline button) ───────────────────
@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data == "send_receipt")
async def payment_receipt_prompt(call: types.CallbackQuery, state: FSMContext):
    user = get_user(telegram_id=call.from_user.id)
    lang = user.language if user else "uz"
    await call.message.answer(
        payment_info_text(lang),
        parse_mode="HTML",
        reply_markup=back_keyboard
    )
    await call.answer()
    await PaymentStates.receipt.set()


# ── Receive screenshot ────────────────────────────────────────────────────────
@dp.message_handler(
    ChatTypeFilter(ChatType.PRIVATE),
    content_types=types.ContentType.PHOTO,
    state=PaymentStates.receipt
)
async def payment_receipt_photo_handler(message: types.Message, state: FSMContext):
    user = get_user(telegram_id=message.from_user.id)
    lang = user.language if user else "uz"

    username_link = (
        f'<a href="https://t.me/{user.username}">@{user.username}</a>'
        if user and user.username else str(message.from_user.id)
    )
    caption = (
        f"💳 <b>Yangi to'lov cheki!</b>\n\n"
        f"👤 Foydalanuvchi: {user.full_name} [{username_link}]\n"
        f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
        f"💰 So'ralgan summa: <b>{MONTHLY_PRICE:,} UZS</b>\n\n"
        f"Botdan foydalanishga ruxsat berilsinmi?"
    )

    try:
        photo_message = await bot.send_photo(
            chat_id=ADMIN_GROUP_ID,
            message_thread_id=PAYMENT_THREAD_ID,
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=await make_send_receipt_to_group_button(
                telegram_id=user.telegram_id,
                message_id=None
            )
        )
        # Update button with real message_id for editing later
        await bot.edit_message_reply_markup(
            chat_id=ADMIN_GROUP_ID,
            message_id=photo_message.message_id,
            reply_markup=await make_send_receipt_to_group_button(
                telegram_id=user.telegram_id,
                message_id=photo_message.message_id
            )
        )

        if lang == "ru":
            text = "✅ Ваш чек отправлен на проверку. Мы уведомим вас в ближайшее время!"
        else:
            text = "✅ To'lov chekingiz tekshirish uchun yuborildi. Tez orada xabar beramiz!"

    except Exception as e:
        print(f"Kvitansiya yuborishda xatolik: {e}")
        if lang == "ru":
            text = "❗️ Ошибка при отправке чека. Попробуйте позже."
        else:
            text = "❗️ Chekni yuborishda xatolik. Keyinroq urinib ko'ring."

    await message.answer(text, reply_markup=main_markup(language=lang))
    await state.finish()


# ── Wrong content type in receipt state ─────────────────────────────────────
@dp.message_handler(
    ChatTypeFilter(ChatType.PRIVATE),
    state=PaymentStates.receipt
)
async def payment_wrong_content(message: types.Message, state: FSMContext):
    user = get_user(telegram_id=message.from_user.id)
    lang = user.language if user else "uz"

    if message.text in [_("🔙 Orqaga"), "🔙 Orqaga", "🔙 Назад"]:
        await state.finish()
        await message.answer(_("Asosiy menyu"), reply_markup=main_markup(language=lang))
        return

    if lang == "ru":
        await message.answer("📸 Пожалуйста, отправьте скриншот чека как <b>фото</b>.", parse_mode="HTML")
    else:
        await message.answer("📸 Iltimos, to'lov chekini <b>rasm</b> ko'rinishida yuboring.", parse_mode="HTML")
