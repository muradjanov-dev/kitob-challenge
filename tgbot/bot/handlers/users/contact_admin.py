import os

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from tgbot.bot.filters import IsPrivate
from tgbot.bot.loader import dp, bot
from tgbot.bot.states.main import ContactAdminState, AdminReplyState
from tgbot.bot.utils import get_user
from tgbot.bot.keyboards.reply import back_keyboard


CONTACT_BUTTON_TEXTS = ["📞 Admin bilan bog'lanish", "📞 Написать администратору"]


def _t(language, uz, ru):
    return ru if language == "ru" else uz


def _user_lang(user):
    return (user.language if user else None) or "uz"


@dp.message_handler(IsPrivate(), text=CONTACT_BUTTON_TEXTS, state="*")
async def contact_admin_entry(message: types.Message, state: FSMContext):
    await state.finish()
    user = get_user(message.from_user.id)
    lang = _user_lang(user)
    await message.answer(
        _t(
            lang,
            "✉️ Adminga yubormoqchi bo'lgan xabaringizni yozing:",
            "✉️ Напишите сообщение, которое хотите отправить администратору:",
        ),
        reply_markup=back_keyboard,
    )
    await ContactAdminState.message.set()


@dp.message_handler(IsPrivate(), state=ContactAdminState.message, content_types=types.ContentTypes.TEXT)
async def contact_admin_forward(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    user = get_user(message.from_user.id)
    lang = _user_lang(user)

    # "🔙 Orqaga" is handled globally by back_handler — won't reach here.
    if not text:
        await message.answer(
            _t(lang, "Iltimos, matn yuboring.", "Пожалуйста, отправьте текст.")
        )
        return

    admins_raw = os.environ.get("ADMINS", "")
    admin_ids = [a.strip() for a in admins_raw.split(",") if a.strip()]

    username = message.from_user.username
    full_name = (user.full_name if user else None) or message.from_user.full_name or "—"
    username_str = f"@{username}" if username else "—"

    forwarded = (
        "📩 <b>Foydalanuvchidan xabar</b>\n\n"
        f"👤 <b>{full_name}</b>\n"
        f"🆔 <code>{message.from_user.id}</code>\n"
        f"📱 {username_str}\n\n"
        f"<i>Xabar:</i>\n{text}"
    )

    reply_kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton(
            "✉️ Javob berish",
            callback_data=f"admin_reply:{message.from_user.id}",
        )
    )

    sent_count = 0
    for chat_id in admin_ids:
        try:
            await bot.send_message(
                chat_id=chat_id, text=forwarded, parse_mode="HTML",
                reply_markup=reply_kb,
            )
            sent_count += 1
        except Exception as e:
            print(f"contact_admin: forward to {chat_id} failed: {e}")

    if sent_count > 0:
        await message.answer(
            _t(
                lang,
                "✅ Xabaringiz adminga yuborildi. Tez orada javob beramiz!",
                "✅ Ваше сообщение отправлено администратору. Скоро ответим!",
            )
        )
    else:
        await message.answer(
            _t(
                lang,
                "❌ Adminga yuborib bo'lmadi. Keyinroq urinib ko'ring.",
                "❌ Не удалось отправить администратору. Попробуйте позже.",
            )
        )

    await state.finish()


@dp.message_handler(IsPrivate(), state=ContactAdminState.message)
async def contact_admin_invalid(message: types.Message):
    user = get_user(message.from_user.id)
    lang = _user_lang(user)
    await message.answer(
        _t(
            lang,
            "❌ Faqat matn yuboring (rasm/fayl emas).",
            "❌ Отправьте только текст (без фото/файлов).",
        )
    )


# ──────────────────────────────────────────────────────────────────────
# Admin → User reply flow.
# Admin clicks "✉️ Javob berish" inline button on a forwarded message
# (in their private chat with the bot), enters text, bot delivers it to
# the original user as a private message.
# ──────────────────────────────────────────────────────────────────────
def _is_admin(telegram_id: int) -> bool:
    raw = os.environ.get("ADMINS", "")
    ids = [a.strip() for a in raw.split(",") if a.strip()]
    return str(telegram_id) in ids


@dp.callback_query_handler(
    IsPrivate(),
    lambda c: c.data and c.data.startswith("admin_reply:"),
    state="*",
)
async def admin_reply_start(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    target_user_id = call.data.split(":", 1)[1]
    await state.finish()
    await state.update_data(reply_target_user_id=target_user_id)
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(
        f"✍️ Javobingizni yozing (foydalanuvchi: <code>{target_user_id}</code>):",
        parse_mode="HTML",
    )
    await AdminReplyState.message.set()


@dp.message_handler(
    IsPrivate(),
    state=AdminReplyState.message,
    content_types=types.ContentType.ANY,
)
async def admin_reply_send(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.finish()
        return

    data = await state.get_data()
    target_user_id = data.get("reply_target_user_id")
    if not target_user_id:
        await message.answer("❌ Foydalanuvchi ID topilmadi.")
        await state.finish()
        return

    target = get_user(int(target_user_id))
    target_lang = (target.language if target else None) or "uz"
    header = _t(
        target_lang,
        "✉️ <b>Adminstratordan javob:</b>",
        "✉️ <b>Ответ от администратора:</b>",
    )
    try:
        await bot.send_message(
            chat_id=target_user_id, text=header, parse_mode="HTML",
        )
        await message.copy_to(chat_id=int(target_user_id))
        await message.answer("✅ Javob foydalanuvchiga yuborildi.")
    except Exception as e:
        print(f"admin_reply: send to {target_user_id} failed: {e}")
        await message.answer(f"❌ Yuborib bo'lmadi: {e}")

    await state.finish()
