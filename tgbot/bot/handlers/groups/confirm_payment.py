import os

from aiogram import types
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher import FSMContext
from django.utils import timezone
from datetime import timedelta

from tgbot.bot.loader import dp, bot, gettext as _
from tgbot.models import Payment
from tgbot.bot.utils import get_user
from tgbot.bot.keyboards.inline import send_receipt_button
MONTHLY_PAYMENT = 50000
from tgbot.bot.consts import ADMIN_GROUP_ID


def _is_admin(telegram_id: int) -> bool:
    ids = [a.strip() for a in os.environ.get("ADMINS", "").split(",") if a.strip()]
    return str(telegram_id) in ids


def _build_premium_welcome(start_date, end_date) -> str:
    return (
        "🎉 <b>Tabriklaymiz! Premium faollashtirildi!</b>\n\n"
        f"📅 Muddati: <b>{start_date.strftime('%d.%m.%Y')}</b> — <b>{end_date.strftime('%d.%m.%Y')}</b>\n\n"
        "Sizga quyidagi imkoniyatlar ochildi:\n\n"
        "🪙 <b>×2 (KARRA KO'P) Kitobchalar!</b> 🔥 — har bir hisobot, yutuq va reyting mukofoti ikki barobar!\n"
        "📋 <b>To'liq hisobotlar tarixi</b> — qaysi kuni, qaysi kitob, qanday xulosa yozganingizni ko'ring\n"
        "📊 <b>O'sish jadvali</b> — kun / hafta / oy / yil kesimida o'sish va tushish foizini ko'ring\n"
        "💎 <b>Premium badge</b> — guruh hisobotlari va reyting ro'yxatlarida 💎 belgisi bilan ajralib turing\n\n"
        "Kabinetingizni oching va barcha imkoniyatlardan bahramand bo'ling! 🚀"
    )


@dp.callback_query_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), lambda c: "accept" in c.data)
async def confirm_payment_message_handler(call: types.CallbackQuery, state: FSMContext):
    split_data = call.data.split(":")
    user_telegram_id = split_data[1]
    photo_message_id = split_data[2]

    user = get_user(telegram_id=user_telegram_id)

    if not user:
        return

    try:
        start_date = timezone.localdate()
        end_date = timezone.localdate() + timedelta(days=30)
        Payment.objects.create(
            user=user,
            amount=MONTHLY_PAYMENT,
            start_date=start_date,
            end_date=end_date,
            status="paid"
        )

        message_to_user = _build_premium_welcome(start_date, end_date)
        data = await state.get_data()
        username_or_telegram_id = f"""<a href="https://{user.username}.t.me">@{user.username}</a>""" if user.username else user.telegram_id
        message_to_admin = f"""✅To'lov tasdiqlandi!\n👤FISH: {user.full_name}[{username_or_telegram_id}]\n🧾Qiymat: {MONTHLY_PAYMENT} UZS\n📅Davr: {start_date.strftime("%d.%m.%Y")} -> {end_date.strftime("%d.%m.%Y")}\n\n#paid #monthly"""
        if photo_message_id:
            try:
                await bot.edit_message_caption(
                    caption=message_to_admin,
                    chat_id=ADMIN_GROUP_ID,
                    message_id=int(photo_message_id),
                    reply_markup=None
                )
            except:
                await call.message.answer(message_to_admin)
        else:
            await call.message.answer(message_to_admin)

        # await call.message.delete()
        await bot.send_message(chat_id=user_telegram_id, text=message_to_user, parse_mode="HTML")

    except Exception as e:
        print(f"To'lovni tasdiqlashda xatolik: {e}")
        await call.message.answer(_("❗️ Xatolik yuz berdi, iltimos keyinroq urinib ko'ring."))


@dp.callback_query_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), lambda c: "rejection" in c.data)
async def confirm_payment_message_handler(call: types.CallbackQuery, state: FSMContext):
    split_data = call.data.split(":")
    user_telegram_id = split_data[1]
    photo_message_id = split_data[2]

    await state.update_data(photo_message_id=photo_message_id)
    await state.update_data(user_telegram_id=user_telegram_id)

    user = get_user(telegram_id=user_telegram_id)

    if not user:
        return

    send_message_text = await call.message.answer(_("❗️ To'lov chekini bekor qilish uchun, shu xabarga reply qilib sababini yozing!"))
    await state.update_data(send_message_id=send_message_text.message_id)
    await state.update_data(user_telegram_id=user_telegram_id)


@dp.message_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), content_types=types.ContentType.TEXT)
async def confirm_payment_message_handler(message: types.Message, state: FSMContext):
    if not message.reply_to_message:
        return

    state_data = await state.get_data()
    send_message_id = state_data.get("send_message_id")
    photo_message_id = state_data.get("photo_message_id")
    user_telegram_id = state_data.get("user_telegram_id")

    if not user_telegram_id or str(send_message_id) != str(message.reply_to_message.message_id):
        return

    user = get_user(telegram_id=user_telegram_id)

    await bot.send_message(
        chat_id=user_telegram_id,
        text=message.text,
        reply_markup=send_receipt_button
    )
    username_or_telegram_id = f"""<a href="https://{user.username}.t.me">@{user.username}</a>""" if user.username else user.telegram_id
    message_to_admin = _(f"""❌To'lov bekor qilindi!\n👤FISH: {user.full_name}[{username_or_telegram_id}]\n💡Sabab: {message.text}\n\n#unpaid #monthly""")

    try:
        if photo_message_id:
            await bot.edit_message_caption(
                caption=message_to_admin,
                chat_id=ADMIN_GROUP_ID,
                message_id=photo_message_id,
                reply_markup=None
            )
        else:
            await message.answer(message_to_admin)

        await bot.delete_message(chat_id=ADMIN_GROUP_ID, message_id=send_message_id)
        await message.delete()

    except Exception as e:
        print(f"Xatolik: {e}")
        await message.answer(message_to_admin)

    await message.answer(_("✅ Bekor qilish sababi foydalanuvchiga yuborildi."))


# ── Private-chat approve/reject (from admin DM notification) ─────────────────

@dp.callback_query_handler(
    ChatTypeFilter(ChatType.PRIVATE),
    lambda c: c.data and c.data.startswith("padmin_accept:"),
)
async def padmin_accept(call: types.CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    user_telegram_id = call.data.split(":", 1)[1]
    user = get_user(telegram_id=user_telegram_id)
    if not user:
        await call.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    # Prevent duplicate payments
    if Payment.objects.filter(user=user, status="paid", end_date__gte=timezone.localdate()).exists():
        await call.answer("Bu foydalanuvchida allaqachon faol obuna bor.", show_alert=True)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    start_date = timezone.localdate()
    end_date = start_date + timedelta(days=30)
    Payment.objects.create(
        user=user, amount=MONTHLY_PAYMENT,
        start_date=start_date, end_date=end_date, status="paid",
    )

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await call.answer("✅ To'lov tasdiqlandi!", show_alert=True)

    try:
        await bot.send_message(
            chat_id=user_telegram_id,
            text=_build_premium_welcome(start_date, end_date),
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"padmin_accept notify user failed: {e}")


@dp.callback_query_handler(
    ChatTypeFilter(ChatType.PRIVATE),
    lambda c: c.data and c.data.startswith("padmin_reject:"),
)
async def padmin_reject(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    user_telegram_id = call.data.split(":", 1)[1]
    await state.update_data(padmin_reject_target=user_telegram_id)

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await call.answer()
    await call.message.answer(
        f"❌ Rad etish sababi yozing (foydalanuvchi: <code>{user_telegram_id}</code>):",
        parse_mode="HTML",
    )
    from tgbot.bot.states.main import AdminReplyState as _ARS
    await _ARS.padmin_reject_reason.set()


@dp.message_handler(
    ChatTypeFilter(ChatType.PRIVATE),
    state="AdminReplyState:padmin_reject_reason",
)
async def padmin_reject_reason(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.finish()
        return

    data = await state.get_data()
    user_telegram_id = data.get("padmin_reject_target")
    await state.finish()

    try:
        await bot.send_message(
            chat_id=user_telegram_id,
            text=(
                "❌ <b>To'lovingiz rad etildi.</b>\n\n"
                f"💡 Sabab: {message.text}\n\n"
                "Iltimos, to'lovni qayta amalga oshirib, chekni yuboring."
            ),
            parse_mode="HTML",
            reply_markup=send_receipt_button,
        )
    except Exception as e:
        print(f"padmin_reject notify user failed: {e}")

    await message.answer("✅ Rad etish sababi foydalanuvchiga yuborildi.")
