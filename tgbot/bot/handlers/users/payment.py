from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType, InlineKeyboardMarkup, InlineKeyboardButton

from tgbot.bot.utils import aget_user
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
PREMIUM_PRICE = 24_000   # UZS — iyun 2026 dan yangilandi (17_000 dan)
SUPER_PREMIUM_PRICE = 47_000 # UZS

# ── Premium features list shown to user ─────────────────────────────────────
PREMIUM_FEATURES_UZ = (
    "💎 <b>Premium obuna</b>\n"
    "Bir oylik obuna bilan quyidagilarni olasiz:\n\n"
    "🪙 <b>2 barobar ko'p Kitobcha</b> 🔥\n"
    "   Har bir hisobot, yutuq, challenge va referal uchun oladigan "
    "Kitobchangiz ikki barobar bo'ladi.\n\n"
    "♾️ <b>Kuniga cheksiz hisobot</b>\n"
    "   Bir kunda istagancha hisobot yuborasiz — hammasi birlashtiriladi, "
    "guruhda esa faqat bitta (eng so'nggi) hisobotingiz ko'rinadi.\n\n"
    "📊 <b>Har kuni shaxsiy hisobot</b> (23:57 da)\n"
    "   Bugun va kecha, 3 kun, hafta, oy, yil taqqoslamasi, reytingdagi "
    "o'rningiz va rag'batlantiruvchi xat.\n\n"
    "📋 <b>Hisobotlar tarixi</b>\n"
    "   Qaysi kuni qaysi kitobni o'qiganingizni to'liq ko'rasiz.\n\n"
    "📈 <b>O'sish grafigi</b>\n"
    "   Kun / hafta / oy / yil kesimida o'sishingiz foizlarda.\n\n"
    "🏆 <b>Challenge tarixi</b>\n"
    "   O'tgan barcha challenge'lardagi o'rningiz va mukofotlaringiz.\n\n"
    "💎 <b>Premium belgisi</b>\n"
    "   Guruh va reytinglarda 💎 belgisi bilan ajralib turasiz.\n\n"
    "✅ <b>Admin bilan to'g'ridan-to'g'ri aloqa</b>\n\n"
    f"💳 <b>Narxi: {PREMIUM_PRICE:,} so'm / oy</b>"
)

PREMIUM_FEATURES_RU = (
    "💎 <b>Premium подписка</b>\n"
    "За месячную подписку вы получаете:\n\n"
    "🪙 <b>В 2 раза больше Kitobcha</b> 🔥\n"
    "   Kitobcha за каждый отчёт, достижение, challenge и реферала "
    "удваивается.\n\n"
    "♾️ <b>Безлимитные отчёты в день</b>\n"
    "   Отправляйте сколько угодно отчётов в день — все объединяются, "
    "а в группе виден только один (последний).\n\n"
    "📊 <b>Личный отчёт каждый день</b> (в 23:57)\n"
    "   Сегодня и вчера, 3 дня, неделя, месяц, год, место в рейтинге "
    "и мотивирующее письмо.\n\n"
    "📋 <b>История отчётов</b>\n"
    "   Полностью видно, в какой день какую книгу вы читали.\n\n"
    "📈 <b>График роста</b>\n"
    "   Ваш рост в процентах по дням / неделям / месяцам / годам.\n\n"
    "🏆 <b>История Challenge</b>\n"
    "   Ваши места и награды во всех прошедших challenge.\n\n"
    "💎 <b>Значок Premium</b>\n"
    "   Вы выделяетесь значком 💎 в группе и рейтингах.\n\n"
    "✅ <b>Прямая связь с администратором</b>\n\n"
    f"💳 <b>Цена: {PREMIUM_PRICE:,} сум / месяц</b>"
)

SUPER_PREMIUM_FEATURES_UZ = (
    "🌟 <b>Super Premium obuna imtiyozlari:</b>\n\n"
    "Barcha <b>Premium</b> imtiyozlariga qo'shimcha ravishda:\n"
    "📚 <b>PDF orqali Quiz generatsiya</b> — har qanday PDF kitob yoki qo'llanmani AI ga yuboring, u avtomatik tarzda to'liq quiz yaratib beradi!\n"
    "✨ <b>Eng yangi AI funksiyalari</b>\n\n"
    f"💳 Narx: <b>{SUPER_PREMIUM_PRICE:,} UZS / oy</b>"
)

SUPER_PREMIUM_FEATURES_RU = (
    "🌟 <b>Преимущества Super Premium подписки:</b>\n\n"
    "В дополнение ко всем <b>Premium</b> функциям:\n"
    "📚 <b>Генерация викторин по PDF</b> — отправьте любую книгу или руководство в формате PDF нашему ИИ, и он автоматически создаст полноценную викторину!\n"
    "✨ <b>Новейшие функции ИИ</b>\n\n"
    f"💳 Цена: <b>{SUPER_PREMIUM_PRICE:,} UZS / месяц</b>"
)


def premium_features_text(language="uz", plan="premium"):
    if plan == "super":
        return SUPER_PREMIUM_FEATURES_RU if language == "ru" else SUPER_PREMIUM_FEATURES_UZ
    return PREMIUM_FEATURES_RU if language == "ru" else PREMIUM_FEATURES_UZ


def payment_info_text(language="uz", price=PREMIUM_PRICE):
    if language == "ru":
        return (
            f"💳 <b>Реквизиты для оплаты:</b>\n\n"
            f"🏦 Номер карты: <code>{CARD_NUMBER}</code>\n"
            f"👤 Владелец: <b>{CARD_OWNER}</b>\n"
            f"💰 Сумма: <b>{price:,} UZS</b>\n\n"
            "📸 После оплаты отправьте скриншот чека в этот чат."
        )
    return (
        f"💳 <b>To'lov rekvizitlari:</b>\n\n"
        f"🏦 Karta raqami: <code>{CARD_NUMBER}</code>\n"
        f"👤 Egasi: <b>{CARD_OWNER}</b>\n"
        f"💰 Summa: <b>{price:,} UZS</b>\n\n"
        "📸 To'lovdan so'ng to'lov cheki rasmini shu chatga yuboring."
    )


# ── Inline keyboards ─────────────────────────────────────────────────────────
def premium_menu_markup(language="uz"):
    if language == "ru":
        return InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("💎 Premium подписка", callback_data="buy_plan:premium"),
            InlineKeyboardButton("🌟 Super Premium подписка", callback_data="buy_plan:super"),
            InlineKeyboardButton("✅ Проверить подписку", callback_data="check_premium"),
        )
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("💎 Premium obuna", callback_data="buy_plan:premium"),
        InlineKeyboardButton("🌟 Super Premium obuna", callback_data="buy_plan:super"),
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
    user = await aget_user(telegram_id=message.from_user.id)
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
    user = await aget_user(telegram_id=call.from_user.id)
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
@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data.startswith("buy_plan:"))
async def buy_plan_callback(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(telegram_id=call.from_user.id)
    lang = user.language if user else "uz"
    
    plan = call.data.split(":")[1]
    price = SUPER_PREMIUM_PRICE if plan == "super" else PREMIUM_PRICE
    await state.update_data(payment_price=price, payment_plan=plan)

    # Must SEND a new message (not edit_text): the payment step uses a reply
    # keyboard (back_keyboard), and editMessageText only accepts inline
    # keyboards — passing a ReplyKeyboardMarkup raises InlineKeyboardExpected,
    # which silently aborted the whole "buy premium" flow.
    # Strip the inline buttons off the original menu so it can't be re-clicked.
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(
        premium_features_text(lang, plan) + "\n\n" + payment_info_text(lang, price),
        parse_mode="HTML",
        reply_markup=back_keyboard
    )
    await call.answer()
    await PaymentStates.receipt.set()


# ── Legacy: send_receipt callback (from old inline button) ───────────────────
@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: c.data == "send_receipt")
async def payment_receipt_prompt(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(telegram_id=call.from_user.id)
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
    user = await aget_user(telegram_id=message.from_user.id)
    lang = user.language if user else "uz"
    
    state_data = await state.get_data()
    price = state_data.get("payment_price", PREMIUM_PRICE)
    plan = state_data.get("payment_plan", "premium")

    username_link = (
        f'<a href="https://t.me/{user.username}">@{user.username}</a>'
        if user and user.username else str(message.from_user.id)
    )
    caption = (
        f"💳 <b>Yangi to'lov cheki! ({plan.upper()})</b>\n\n"
        f"👤 Foydalanuvchi: {user.full_name} [{username_link}]\n"
        f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
        f"💰 So'ralgan summa: <b>{price:,} UZS</b>\n\n"
        f"Botdan foydalanishga ruxsat berilsinmi?"
    )

    import os as _os
    admin_ids = [a.strip() for a in _os.environ.get("ADMINS", "").split(",") if a.strip()]

    try:
        photo_message = await bot.send_photo(
            chat_id=ADMIN_GROUP_ID,
            message_thread_id=PAYMENT_THREAD_ID,
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=await make_send_receipt_to_group_button(
                price=price,
                telegram_id=user.telegram_id,
                message_id=None
            )
        )
        # Update button with real message_id for editing later
        await bot.edit_message_reply_markup(
            chat_id=ADMIN_GROUP_ID,
            message_id=photo_message.message_id,
            reply_markup=await make_send_receipt_to_group_button(
                price=price,
                telegram_id=user.telegram_id,
                message_id=photo_message.message_id
            )
        )

        # Also DM every admin so they never miss a receipt
        dm_kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton(
                "✅ Ruxsat berish",
                callback_data=f"padmin_accept:{price}:{user.telegram_id}",
            ),
            InlineKeyboardButton(
                "❌ Rad etish",
                callback_data=f"padmin_reject:{price}:{user.telegram_id}",
            ),
        )
        for admin_id in admin_ids:
            try:
                await bot.send_photo(
                    chat_id=admin_id,
                    photo=message.photo[-1].file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=dm_kb,
                )
            except Exception as dm_err:
                print(f"payment DM to admin {admin_id} failed: {dm_err}")

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
    user = await aget_user(telegram_id=message.from_user.id)
    lang = user.language if user else "uz"

    if message.text in [_("🔙 Orqaga"), "🔙 Orqaga", "🔙 Назад"]:
        await state.finish()
        await message.answer(_("Asosiy menyu"), reply_markup=main_markup(language=lang))
        return

    if lang == "ru":
        await message.answer("📸 Пожалуйста, отправьте скриншот чека как <b>фото</b>.", parse_mode="HTML")
    else:
        await message.answer("📸 Iltimos, to'lov chekini <b>rasm</b> ko'rinishida yuboring.", parse_mode="HTML")
