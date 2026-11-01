"""👛 Hamyon — balance, top-ups and their admin approval (services/wallet.py).

Reached from the main menu (the Premium button becomes "👛 Hamyon" at the
launch), /hamyon, the /start hamyon deep link, and the top-up buttons shown
when a report is refused for lack of money. A receipt goes to the payments
thread and to every admin's DM, like the Premium receipts did; the wallet is
credited by wallet.approve_topup, which only the first approve click passes.
"""
from asgiref.sync import sync_to_async
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tgbot.bot.consts import ADMIN_GROUP_ID, PAYMENT_THREAD_ID
from tgbot.bot.keyboards.reply import back_keyboard, main_markup
from tgbot.bot.loader import bot, dp
from tgbot.bot.states.main import WalletStates
from tgbot.bot.utils import aget_admin_ids, aget_is_admin, aget_user
from tgbot.services import wallet

WALLET_LABELS = ("👛 Hamyon", "👛 Кошелёк")


def _som(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _lang(user) -> str:
    return (getattr(user, "language", None) or "uz") if user else "uz"


def wallet_text(user) -> str:
    bal, ball = int(user.wallet_balance or 0), int(user.ball or 0)
    back = wallet.refundable(user)
    pot = int(getattr(user, "cashback_balance", 0) or 0)
    if _lang(user) == "ru":
        refund_line = (f"💸 Можно вернуть: <b>{_som(back)} сум</b> — неизрасходованные оплаченные деньги "
                       "(бонусы проекта не возвращаются). Напишите через «📞 Связь с админом».\n\n" if back else "")
    else:
        refund_line = (f"💸 Qaytarib olish mumkin: <b>{_som(back)} so'm</b> — to'lagan pulingizning ishlatilmagan "
                       "qismi (loyiha bonuslari qaytarilmaydi). «📞 Admin bilan bog'lanish» orqali yozing.\n\n"
                       if back else "")
    paid = wallet.paid_on(user)
    days = wallet.days_left(user)
    max_k = wallet.DAY_FEE * wallet.KITOBCHA_SHARE_PCT // 100
    if _lang(user) == "ru":
        today = (f"✅ Сегодня уже оплачено. Следующий отчёт: {_som(wallet.report_price(user))} сум." if paid else
                 f"⏳ С первого отчёта сегодня спишется {_som(wallet.DAY_FEE)} сум.")
        kit = "используются" if user.wallet_use_kitobcha else "не используются"
        until = wallet.member_until(user)
        if until:
            perks = (f"💎 Привилегии активны до <b>{until:%d.%m}</b>: 2× Kitobcha, VIP-арена, следующие "
                     f"отчёты дня по {_som(wallet.EXTRA_FEE_MEMBER)} сум. Новое пополнение от {_som(wallet.MEMBER_MIN)} сум продлит их.\n\n")
        elif wallet.legacy_premium(user):
            perks = "💎 Привилегии Premium активны до конца его срока.\n\n"
        else:
            perks = (f"💎 Пополнение за один раз от <b>{_som(wallet.MEMBER_MIN)} сум</b> даёт привилегии на "
                     f"1 день за каждые {_som(wallet.DAY_FEE)} сум: 2× Kitobcha, VIP-арена, следующие отчёты дня по {_som(wallet.EXTRA_FEE_MEMBER)} сум.\n\n")
        return (
            "👛 <b>Ваш кошелёк</b>\n\n"
            f"💰 Баланс: <b>{_som(bal)} сум</b>\n"
            f"🪙 Kitobcha: <b>{_som(ball)}</b> (для оплаты {kit})\n"
            f"📅 Хватит ещё на <b>{days}</b> дн. отчётов\n"
            f"{today}\n\n"
            f"ℹ️ Каждый отчёт стоит <b>{_som(wallet.DAY_FEE)} сум</b>, отправлять можно сколько угодно раз в день. "
            f"До {wallet.KITOBCHA_SHARE_PCT}% цены можно оплатить Kitobcha.\n"
            f"{perks}"
            f"📚 Книжная копилка: <b>{_som(pot)} / {_som(wallet.CASHBACK_PAYOUT)} сум</b> — {wallet.CASHBACK_PCT}% "
            f"кешбэк с каждого пополнения; на {_som(wallet.CASHBACK_PAYOUT)} всё переходит в кошелёк.\n\n"
            f"{refund_line}"
            "Выберите сумму пополнения 👇"
        )
    today = (f"✅ Bugungi hisobot to'langan. Keyingi hisobot: {_som(wallet.report_price(user))} so'm." if paid else
             f"⏳ Bugun birinchi hisobotda {_som(wallet.DAY_FEE)} so'm yechiladi.")
    kit = "ishlatiladi" if user.wallet_use_kitobcha else "ishlatilmaydi"
    until = wallet.member_until(user)
    if until:
        perks = (f"💎 Imtiyozlaringiz <b>{wallet.uz_date(until)}gacha</b> faol: 2× Kitobcha, VIP arena, "
                 f"kunning keyingi hisobotlari {_som(wallet.EXTRA_FEE_MEMBER)} so'mdan. Yana {_som(wallet.MEMBER_MIN)} so'm va undan ko'p to'ldirsangiz, "
                 "muddat uzayadi.\n\n")
    elif wallet.legacy_premium(user):
        perks = "💎 Premium imtiyozlaringiz muddati tugaguncha faol.\n\n"
    else:
        perks = (f"💎 Bir martada <b>{_som(wallet.MEMBER_MIN)} so'm</b> va undan ko'p to'ldirsangiz — har "
                 f"{_som(wallet.DAY_FEE)} so'm uchun 1 kunlik imtiyoz: 2× Kitobcha, VIP arena, kunning keyingi "
                 f"hisobotlari {_som(wallet.EXTRA_FEE_MEMBER)} so'mdan.\n\n")
    return (
        "👛 <b>Hamyoningiz</b>\n\n"
        f"💰 Balans: <b>{_som(bal)} so'm</b>\n"
        f"🪙 Kitobcha: <b>{_som(ball)}</b> (to'lovda {kit})\n"
        f"📅 Yana <b>{days}</b> kunlik hisobotga yetadi\n"
        f"{today}\n\n"
        f"ℹ️ Har bir hisobot <b>{_som(wallet.DAY_FEE)} so'm</b>, bir kunda istalgancha yuborish mumkin. "
        f"Narxning {wallet.KITOBCHA_SHARE_PCT}% gachasini Kitobcha bilan to'lash mumkin.\n"
        f"{perks}"
        f"📚 Kitob hamyonchasi: <b>{_som(pot)} / {_som(wallet.CASHBACK_PAYOUT)} so'm</b> — har to'ldirishdan "
        f"{wallet.CASHBACK_PCT}% keshbek; {_som(wallet.CASHBACK_PAYOUT)} ga yetganda hammasi asosiy hamyonga o'tadi.\n\n"
        f"{refund_line}"
        "To'ldirish uchun summani tanlang 👇"
    )


def topup_kb(user) -> InlineKeyboardMarkup:
    ru = _lang(user) == "ru"
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(*[InlineKeyboardButton(f"➕ {_som(a)}", callback_data=f"wallet:topup:{a}")
             for a in wallet.TOPUP_PRESETS])
    kb.add(InlineKeyboardButton("✍️ Другая сумма" if ru else "✍️ Boshqa miqdor", callback_data="wallet:custom"))
    return kb


def wallet_kb(user) -> InlineKeyboardMarkup:
    ru = _lang(user) == "ru"
    kb = topup_kb(user)
    on = user.wallet_use_kitobcha
    if ru:
        label = "🪙 Оплата Kitobcha: " + ("✅ вкл" if on else "⛔️ выкл")
    else:
        label = "🪙 Kitobcha bilan to'lash: " + ("✅ yoqilgan" if on else "⛔️ o'chirilgan")
    kb.row(InlineKeyboardButton(label, callback_data="wallet:kitobcha"))
    kb.row(InlineKeyboardButton("📜 История" if ru else "📜 Tarix", callback_data="wallet:history"))
    kb.row(InlineKeyboardButton("🪙 Что делать с Kitobcha?" if ru else "🪙 Kitobcha bilan nima qilaman?",
                                callback_data="kuse:menu"))
    return kb


def insufficient_text(user) -> str:
    cash, kit = wallet.fee_split(user)
    bal = int(user.wallet_balance or 0)
    if _lang(user) == "ru":
        note = f" (+{kit} Kitobcha)" if kit else ""
        return (
            "👛 <b>На балансе кошелька недостаточно средств</b>\n\n"
            f"Для сегодняшнего отчёта нужно {_som(cash)} сум{note}, на балансе — {_som(bal)} сум.\n\n"
            f"Пополните кошелёк — {_som(wallet.DAY_FEE)} сум = 1 день отчётов 👇"
        )
    note = f" (+{kit} Kitobcha)" if kit else ""
    return (
        "👛 <b>Hamyoningizda mablag' yetarli emas</b>\n\n"
        f"Bugungi hisobot uchun {_som(cash)} so'm{note} kerak, hamyoningizda — {_som(bal)} so'm.\n\n"
        f"Hamyonni to'ldiring — {_som(wallet.DAY_FEE)} so'm = 1 kunlik hisobot 👇"
    )


def charged_text(user, res) -> str:
    if not res.get("ok"):
        return ""
    parts = [f"{_som(res['cash'])} so'm"] + ([f"{res['kitobcha']} Kitobcha"] if res.get("kitobcha") else [])
    if _lang(user) == "ru":
        parts = [f"{_som(res['cash'])} сум"] + ([f"{res['kitobcha']} Kitobcha"] if res.get("kitobcha") else [])
        what = "За этот отчёт" if res.get("extra") else "За сегодняшний день"
        return f"👛 {what} списано: {' + '.join(parts)}. Остаток: <b>{_som(res['balance'])} сум</b>."
    what = "Bu hisobot uchun" if res.get("extra") else "Bugungi kun uchun"
    return f"👛 {what} yechildi: {' + '.join(parts)}. Qoldiq: <b>{_som(res['balance'])} so'm</b>."


async def show_wallet(message: types.Message, user) -> None:
    await sync_to_async(wallet.ensure_launch_credit)(user)
    text = await sync_to_async(wallet_text)(user)
    await message.answer(text, parse_mode="HTML", reply_markup=wallet_kb(user))


def fee_confirm_text(user) -> str:
    cash, kit = wallet.fee_split(user)
    bal, ball = int(user.wallet_balance or 0), int(user.ball or 0)
    n = wallet.fees_today(user)
    member = wallet.is_member(user)
    if _lang(user) == "ru":
        part = f"<b>{_som(cash)} сум</b>" + (f" + <b>{kit} Kitobcha</b>" if kit else "")
        which = "за сегодня" if n == 0 else f"за {n + 1}-й отчёт сегодня"
        hint = ("" if n == 0 or member else
                f"\n💡 Пополнение за один раз от {_som(wallet.MEMBER_MIN)} сум — и следующие отчёты дня "
                f"будут по {_som(wallet.EXTRA_FEE_MEMBER)} сум.\n")
        return (
            "💳 <b>Оплата отчёта</b>\n\n"
            f"Когда отчёт будет принят, {which} спишется {part}.\n"
            f"👛 В кошельке: <b>{_som(bal)} сум</b> · 🪙 <b>{_som(ball)}</b> Kitobcha\n{hint}\n"
            "Продолжаем? 😊"
        )
    part = f"<b>{_som(cash)} so'm</b>" + (f" + <b>{kit} Kitobcha</b>" if kit else "")
    which = "bugungi kun uchun" if n == 0 else f"bugungi {n + 1}-hisobotingiz uchun"
    hint = ("" if n == 0 or member else
            f"\n💡 Bir martada {_som(wallet.MEMBER_MIN)} so'm va undan ko'p to'ldirsangiz, kunning keyingi "
            f"hisobotlari atigi {_som(wallet.EXTRA_FEE_MEMBER)} so'm bo'ladi.\n")
    return (
        "💳 <b>Hisobot uchun to'lov</b>\n\n"
        f"Hisobotingiz qabul qilinganda {which} {part} yechiladi.\n"
        f"👛 Hamyoningizda: <b>{_som(bal)} so'm</b> · 🪙 <b>{_som(ball)}</b> Kitobcha\n{hint}\n"
        "Davom etamizmi? 😊"
    )


def fee_confirm_kb(user) -> InlineKeyboardMarkup:
    ru = _lang(user) == "ru"
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Да, продолжить" if ru else "✅ Ha, davom etamiz", callback_data="wallet:feeok"),
        InlineKeyboardButton("❌ Нет" if ru else "❌ Yo'q", callback_data="wallet:feeno"),
    )


async def report_allowed(message: types.Message, user) -> bool:
    """Gate for every report entry point: True when the reader may start a
    report (wallet not launched yet, today already paid, or it can be paid
    and the reader said yes to the fee -- asked once a day, before anything
    is taken; the fee itself is taken when the report is saved)."""
    if not user or not wallet.launched(user):
        return True
    await sync_to_async(wallet.ensure_launch_credit)(user)
    if not await sync_to_async(wallet.can_report)(user):
        await message.answer(insufficient_text(user), parse_mode="HTML", reply_markup=topup_kb(user))
        return False
    if await sync_to_async(wallet.fee_confirmed)(user):
        return True
    await message.answer(fee_confirm_text(user), parse_mode="HTML", reply_markup=fee_confirm_kb(user))
    return False


# ── Entry points ────────────────────────────────────────────────────────────

@dp.message_handler(commands=["hamyon", "wallet"], state="*")
@dp.message_handler(lambda m: m.chat.type == "private" and m.text in WALLET_LABELS, state="*")
async def wallet_command(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        return
    user = await aget_user(message.from_user.id)
    if not user:
        await message.answer("Avval /start bosing.")
        return
    await state.finish()
    if not wallet.launched(user):
        await message.answer(
            "👛 Hamyon <b>1-noyabrdan</b> ishga tushadi. Kuting — tez orada! 🚀"
            if _lang(user) != "ru" else "👛 Кошелёк заработает <b>с 1 ноября</b>. Скоро! 🚀",
            parse_mode="HTML",
        )
        return
    await show_wallet(message, user)


@dp.callback_query_handler(lambda c: c.data == "wallet:open", state="*")
async def wallet_open(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user = await aget_user(call.from_user.id)
    if user and wallet.launched(user):
        await state.finish()
        await show_wallet(call.message, user)


@dp.callback_query_handler(lambda c: c.data == "wallet:feeok", state="*")
async def wallet_fee_ok(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user or not wallet.launched(user):
        await call.answer()
        return
    await sync_to_async(wallet.confirm_fee)(user)
    await call.answer("✅")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    from tgbot.bot.handlers.users.report import start_report_flow
    await start_report_flow(call, state, user)


@dp.callback_query_handler(lambda c: c.data == "wallet:feeno", state="*")
async def wallet_fee_no(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    await call.answer()
    await state.finish()
    try:
        await call.message.edit_text(
            "👌 Отменено — ничего не списано." if _lang(user) == "ru"
            else "👌 Bekor qilindi — hech narsa yechilmadi. Istalgan payt qaytishingiz mumkin 📖"
        )
    except Exception:
        pass


@dp.callback_query_handler(lambda c: c.data == "wallet:kitobcha", state="*")
async def wallet_toggle_kitobcha(call: types.CallbackQuery):
    from tgbot.models import TelegramProfile
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer()
        return
    user.wallet_use_kitobcha = not user.wallet_use_kitobcha
    await sync_to_async(TelegramProfile.objects.filter(id=user.id).update)(
        wallet_use_kitobcha=user.wallet_use_kitobcha)
    await call.answer("✅")
    try:
        await call.message.edit_text(await sync_to_async(wallet_text)(user), parse_mode="HTML",
                                     reply_markup=wallet_kb(user))
    except Exception:
        pass


@dp.callback_query_handler(lambda c: c.data == "wallet:history", state="*")
async def wallet_history(call: types.CallbackQuery):
    from tgbot.models import WalletTransaction
    user = await aget_user(call.from_user.id)
    await call.answer()
    if not user:
        return
    rows = await sync_to_async(list)(WalletTransaction.objects.filter(user=user).order_by("-created_at")[:12])
    ru = _lang(user) == "ru"
    names = dict(WalletTransaction.KIND_CHOICES)
    if not rows:
        await call.message.answer("📜 Пока нет операций." if ru else "📜 Hozircha amallar yo'q.")
        return
    from django.utils import timezone
    lines = ["📜 <b>Последние операции</b>\n" if ru else "📜 <b>So'nggi amallar</b>\n"]
    for r in rows:
        when = timezone.localtime(r.created_at).strftime("%d.%m %H:%M")
        kit = f" + {r.kitobcha} 🪙" if r.kitobcha else ""
        lines.append(f"{when} · {names.get(r.kind, r.kind)}: <b>{r.delta:+,}</b>{kit}".replace(",", " "))
    await call.message.answer("\n".join(lines), parse_mode="HTML")


# ── Top-up: amount -> card details -> receipt ──────────────────────────────

async def _ask_receipt(message: types.Message, user, amount: int, state: FSMContext):
    from tgbot.bot.handlers.users.payment import CARD_NUMBER, CARD_OWNER
    await state.update_data(wallet_topup_amount=amount)
    await WalletStates.receipt.set()
    if _lang(user) == "ru":
        text = (
            f"💳 <b>Пополнение кошелька на {_som(amount)} сум</b>\n\n"
            f"🏦 Номер карты: <code>{CARD_NUMBER}</code>\n"
            f"👤 Владелец: <b>{CARD_OWNER}</b>\n"
            f"💰 Сумма: <b>{_som(amount)} сум</b>\n\n"
            "📸 После оплаты отправьте сюда фото чека. Как только админ подтвердит, сумма поступит в кошелёк."
        )
    else:
        text = (
            f"💳 <b>Hamyonni {_som(amount)} so'mga to'ldirish</b>\n\n"
            f"🏦 Karta raqami: <code>{CARD_NUMBER}</code>\n"
            f"👤 Egasi: <b>{CARD_OWNER}</b>\n"
            f"💰 Summa: <b>{_som(amount)} so'm</b>\n\n"
            "📸 To'lovdan so'ng chek rasmini shu chatga yuboring. Admin tasdiqlashi bilan summa hamyoningizga tushadi."
        )
    await message.answer(text, parse_mode="HTML", reply_markup=back_keyboard)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("wallet:topup:"), state="*")
async def wallet_topup_preset(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user = await aget_user(call.from_user.id)
    if not user or not wallet.launched(user):
        return
    if call.message.chat.type != "private":
        return
    amount = int(call.data.rsplit(":", 1)[1])
    if amount < wallet.MIN_TOPUP or amount > wallet.MAX_TOPUP:
        return
    await state.finish()
    await _ask_receipt(call.message, user, amount, state)


@dp.callback_query_handler(lambda c: c.data == "wallet:custom", state="*")
async def wallet_topup_custom(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user = await aget_user(call.from_user.id)
    if not user or not wallet.launched(user) or call.message.chat.type != "private":
        return
    await state.finish()
    await WalletStates.amount.set()
    await call.message.answer(
        f"✍️ Сумму пополнения напишите цифрами (от {_som(wallet.MIN_TOPUP)} сум):"
        if _lang(user) == "ru" else
        f"✍️ To'ldirmoqchi bo'lgan summani raqamda yozing ({_som(wallet.MIN_TOPUP)} so'mdan):",
        reply_markup=back_keyboard,
    )


def _is_back(text) -> bool:
    return (text or "") in ("🔙 Orqaga", "🔙 Назад", "⬅️ Orqaga")


@dp.message_handler(state=WalletStates.amount, content_types=types.ContentType.ANY)
async def wallet_topup_amount(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    if _is_back(message.text):
        await state.finish()
        await message.answer("🏠", reply_markup=main_markup(language=_lang(user)))
        return
    amount = wallet.parse_amount(message.text or "")
    if not amount:
        await message.answer(
            f"❗️ {_som(wallet.MIN_TOPUP)} — {_som(wallet.MAX_TOPUP)} сум, только цифры."
            if _lang(user) == "ru" else
            f"❗️ {_som(wallet.MIN_TOPUP)} — {_som(wallet.MAX_TOPUP)} so'm oralig'ida, faqat raqam yozing."
        )
        return
    await _ask_receipt(message, user, amount, state)


@dp.message_handler(state=WalletStates.receipt, content_types=types.ContentType.PHOTO)
async def wallet_receipt_photo(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    amount = int((await state.get_data()).get("wallet_topup_amount") or 0)
    await state.finish()
    if not user or amount < wallet.MIN_TOPUP:
        await message.answer("❗️ Sessiya eskirgan, /hamyon dan qaytadan boshlang.")
        return
    photo = message.photo[-1].file_id
    topup = await sync_to_async(wallet.create_topup)(user, amount, photo)

    link = f'<a href="https://t.me/{user.username}">@{user.username}</a>' if user.username else str(user.telegram_id)
    caption = (
        f"👛 <b>Hamyonni to'ldirish #{topup.id}</b>\n\n"
        f"👤 {user.full_name} [{link}]\n"
        f"🆔 <code>{user.telegram_id}</code>\n"
        f"💰 Summa: <b>{_som(amount)} so'm</b>\n"
        f"💼 Hozirgi balans: {_som(user.wallet_balance)} so'm"
    )
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"wtop_ok:{topup.id}"),
        InlineKeyboardButton("❌ Rad etish", callback_data=f"wtop_no:{topup.id}"),
    )
    sent = 0
    try:
        await bot.send_photo(chat_id=ADMIN_GROUP_ID, message_thread_id=PAYMENT_THREAD_ID, photo=photo,
                             caption=caption, parse_mode="HTML", reply_markup=kb)
        sent += 1
    except Exception as e:
        print(f"wallet topup #{topup.id} group post failed: {e}")
    for admin_id in await aget_admin_ids():
        try:
            await bot.send_photo(chat_id=admin_id, photo=photo, caption=caption, parse_mode="HTML", reply_markup=kb)
            sent += 1
        except Exception as e:
            print(f"wallet topup #{topup.id} DM to {admin_id} failed: {e}")
    ru = _lang(user) == "ru"
    if sent:
        text = (f"✅ Чек отправлен на проверку. После подтверждения в кошелёк поступит {_som(amount)} сум."
                if ru else
                f"✅ Chekingiz tekshirishga yuborildi. Tasdiqlangach hamyoningizga {_som(amount)} so'm tushadi.")
    else:
        text = "❗️ Ошибка при отправке чека. Попробуйте позже." if ru else "❗️ Chekni yuborishda xatolik. Keyinroq urinib ko'ring."
    await message.answer(text, reply_markup=main_markup(language=_lang(user)))


@dp.message_handler(state=WalletStates.receipt, content_types=types.ContentType.ANY)
async def wallet_receipt_other(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    if _is_back(message.text):
        await state.finish()
        await message.answer("🏠", reply_markup=main_markup(language=_lang(user)))
        return
    await message.answer(
        "📸 Пожалуйста, отправьте чек как <b>фото</b>." if _lang(user) == "ru"
        else "📸 Iltimos, to'lov chekini <b>rasm</b> ko'rinishida yuboring.",
        parse_mode="HTML",
    )


# ── Admin decision ─────────────────────────────────────────────────────────

async def _mark_reviewed(call: types.CallbackQuery, note: str) -> None:
    try:
        caption = (call.message.caption or "") + f"\n\n{note}"
        await call.message.edit_caption(caption=caption[:1024], parse_mode="HTML", reply_markup=None)
    except Exception:
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("wtop_ok:"), state="*")
async def wallet_topup_approve(call: types.CallbackQuery):
    if not await aget_is_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    admin = await aget_user(call.from_user.id)
    topup_id = int(call.data.split(":", 1)[1])
    topup, credited = await sync_to_async(wallet.approve_topup)(topup_id, admin)
    if not topup:
        await call.answer("Topilmadi.", show_alert=True)
        return
    if not credited:
        await call.answer(f"Bu chek allaqachon ko'rib chiqilgan ({topup.get_status_display()}).", show_alert=True)
        await _mark_reviewed(call, f"ℹ️ Avvalroq: {topup.get_status_display()}")
        return
    await call.answer("✅ Tasdiqlandi")
    who = (admin.full_name if admin else None) or call.from_user.full_name
    await _mark_reviewed(call, f"✅ Tasdiqlandi — {who}. Yangi balans: {_som(topup.user.wallet_balance)} so'm")
    user = topup.user
    days = await sync_to_async(wallet.days_left)(user)
    ru = _lang(user) == "ru"
    until = wallet.member_until(user) if wallet.member_days_for(topup.amount) else None
    if until:
        perks = (f"💎 Привилегии активны до <b>{until:%d.%m}</b>: 2× Kitobcha, VIP-арена, следующие отчёты дня "
                 f"по {_som(wallet.EXTRA_FEE_MEMBER)} сум.\n\n"
                 if ru else
                 f"💎 Imtiyozlaringiz <b>{wallet.uz_date(until)}gacha</b> faol: 2× Kitobcha, VIP arena, "
                 f"kunning keyingi hisobotlari {_som(wallet.EXTRA_FEE_MEMBER)} so'mdan.\n\n")
    else:
        perks = ""
    cb = getattr(topup, "cashback", None) or {}
    if cb.get("paid_out"):
        perks += (f"🎉 Книжная копилка дошла до {_som(wallet.CASHBACK_PAYOUT)} сум — <b>{_som(cb['paid_out'])} сум</b> "
                  "переведено в кошелёк!\n\n" if ru else
                  f"🎉 Kitob hamyonchangiz {_som(wallet.CASHBACK_PAYOUT)} so'mga yetdi — <b>{_som(cb['paid_out'])} so'm</b> "
                  "asosiy hamyonga o'tkazildi!\n\n")
    elif cb.get("added"):
        perks += (f"📚 В копилку: <b>+{_som(cb['added'])} сум</b> кешбэка — всего {_som(cb['pot'])} / "
                  f"{_som(wallet.CASHBACK_PAYOUT)}.\n\n" if ru else
                  f"📚 Kitob hamyonchangizga <b>+{_som(cb['added'])} so'm</b> keshbek — jami {_som(cb['pot'])} / "
                  f"{_som(wallet.CASHBACK_PAYOUT)} so'm.\n\n")
    text = (
        f"✅ <b>Кошелёк пополнен!</b>\n\n➕ {_som(topup.amount)} сум\n"
        f"💰 Баланс: <b>{_som(user.wallet_balance)} сум</b> (≈ {days} дн. отчётов)\n\n{perks}Читайте дальше! 📚"
        if ru else
        f"✅ <b>Hamyoningiz to'ldirildi!</b>\n\n➕ {_som(topup.amount)} so'm\n"
        f"💰 Balans: <b>{_som(user.wallet_balance)} so'm</b> (≈ {days} kunlik hisobot)\n\n{perks}Kitob o'qishda davom eting! 📚"
    )
    try:
        await bot.send_message(user.telegram_id, text, parse_mode="HTML")
    except Exception as e:
        print(f"wallet topup #{topup.id} approve notify failed: {e}")
    # A top-up counts towards the prem_1/3/6 membership achievements.
    try:
        from tgbot.tasks import check_user_achievements
        check_user_achievements.delay(user.id)
    except Exception as e:
        print(f"wallet topup #{topup.id} achievement check failed: {e}")


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("wtop_no:"), state="*")
async def wallet_topup_reject_start(call: types.CallbackQuery, state: FSMContext):
    if not await aget_is_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    topup_id = int(call.data.split(":", 1)[1])
    await call.answer()
    await state.update_data(wallet_reject_topup=topup_id,
                            wallet_reject_msg=(call.message.chat.id, call.message.message_id))
    await WalletStates.reject_reason.set()
    await call.message.answer(f"❌ #{topup_id} chekni rad etish sababini yozing (shu chatga):")


@dp.message_handler(state=WalletStates.reject_reason, content_types=types.ContentType.TEXT)
async def wallet_topup_reject_reason(message: types.Message, state: FSMContext):
    if not await aget_is_admin(message.from_user.id):
        await state.finish()
        return
    data = await state.get_data()
    await state.finish()
    topup_id = data.get("wallet_reject_topup")
    admin = await aget_user(message.from_user.id)
    topup, done = await sync_to_async(wallet.reject_topup)(topup_id, admin, message.text)
    if not topup:
        await message.answer("Topilmadi.")
        return
    if not done:
        await message.answer(f"Bu chek allaqachon ko'rib chiqilgan ({topup.get_status_display()}).")
        return
    chat_msg = data.get("wallet_reject_msg")
    if chat_msg:
        try:
            await bot.edit_message_reply_markup(chat_id=chat_msg[0], message_id=chat_msg[1], reply_markup=None)
        except Exception:
            pass
    user = topup.user
    ru = _lang(user) == "ru"
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("👛 Кошелёк" if ru else "👛 Hamyon", callback_data="wallet:open"))
    try:
        await bot.send_message(
            user.telegram_id,
            (f"❌ <b>Чек отклонён.</b>\n\n💡 Причина: {message.text}\n\nОплатите заново и отправьте чек."
             if ru else
             f"❌ <b>To'lov cheki rad etildi.</b>\n\n💡 Sabab: {message.text}\n\nIltimos, qayta to'lab, chekni yuboring."),
            parse_mode="HTML", reply_markup=kb,
        )
    except Exception as e:
        print(f"wallet topup #{topup.id} reject notify failed: {e}")
    await message.answer("✅ Rad etildi, sabab foydalanuvchiga yuborildi.")
