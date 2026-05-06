import os

from aiogram import types
from aiogram.dispatcher import FSMContext

from tgbot.bot.filters import IsPrivate
from tgbot.bot.loader import dp, bot
from tgbot.bot.states.main import ContactAdminState
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

    sent_count = 0
    for chat_id in admin_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=forwarded, parse_mode="HTML")
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
