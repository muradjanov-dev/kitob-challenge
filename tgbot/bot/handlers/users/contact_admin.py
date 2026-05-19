import os

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from tgbot.bot.filters import IsPrivate
from tgbot.bot.loader import dp, bot
from tgbot.bot.states.main import ContactAdminState, AdminReplyState
from tgbot.bot.utils import aget_user
from tgbot.bot.keyboards.reply import back_keyboard


CONTACT_BUTTON_TEXTS = ["📞 Admin bilan bog'lanish", "📞 Написать администратору"]


def _t(language, uz, ru):
    return ru if language == "ru" else uz


def _user_lang(user):
    return (user.language if user else None) or "uz"


@dp.message_handler(IsPrivate(), text=CONTACT_BUTTON_TEXTS, state="*")
async def contact_admin_entry(message: types.Message, state: FSMContext):
    await state.finish()
    user = await aget_user(message.from_user.id)
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


def _confirm_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton(
            _t(lang, "✅ Yuborish", "✅ Отправить"),
            callback_data="contact_send",
        ),
        InlineKeyboardButton(
            _t(lang, "❌ Bekor qilish", "❌ Отмена"),
            callback_data="contact_cancel",
        ),
    )


@dp.message_handler(
    IsPrivate(),
    state=ContactAdminState.message,
    content_types=types.ContentType.ANY,
)
async def contact_admin_preview(message: types.Message, state: FSMContext):
    """Step 1: capture the user's draft and show a Yuborish / Bekor preview."""
    user = await aget_user(message.from_user.id)
    lang = _user_lang(user)

    # Stash the source message so we can copy_to the admin later.
    await state.update_data(
        draft_chat_id=message.chat.id,
        draft_message_id=message.message_id,
    )
    await message.answer(
        _t(
            lang,
            "Yuqoridagi xabarni adminga yubormoqchimisiz?",
            "Отправить это сообщение администратору?",
        ),
        reply_markup=_confirm_kb(lang),
    )
    await ContactAdminState.confirm.set()


@dp.callback_query_handler(
    lambda c: c.data == "contact_cancel",
    state=ContactAdminState.confirm,
)
async def contact_admin_cancel(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    lang = _user_lang(user)
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(
        _t(lang, "❌ Bekor qilindi.", "❌ Отменено.")
    )
    await state.finish()


@dp.callback_query_handler(
    lambda c: c.data == "contact_send",
    state=ContactAdminState.confirm,
)
async def contact_admin_confirm_send(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    lang = _user_lang(user)

    data = await state.get_data()
    draft_chat_id = data.get("draft_chat_id")
    draft_message_id = data.get("draft_message_id")

    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if not draft_chat_id or not draft_message_id:
        await call.message.answer(
            _t(lang, "❌ Xabar topilmadi.", "❌ Сообщение не найдено.")
        )
        await state.finish()
        return

    admins_raw = os.environ.get("ADMINS", "")
    admin_ids = [a.strip() for a in admins_raw.split(",") if a.strip()]

    username = call.from_user.username
    full_name = (user.full_name if user else None) or call.from_user.full_name or "—"
    username_str = f"@{username}" if username else "—"

    header = (
        "📩 <b>Foydalanuvchidan xabar</b>\n\n"
        f"👤 <b>{full_name}</b>\n"
        f"🆔 <code>{call.from_user.id}</code>\n"
        f"📱 {username_str}"
    )
    reply_kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton(
            "✉️ Javob berish",
            callback_data=f"admin_reply:{call.from_user.id}",
        )
    )

    sent_count = 0
    for chat_id in admin_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=header, parse_mode="HTML")
            await bot.copy_message(
                chat_id=int(chat_id),
                from_chat_id=draft_chat_id,
                message_id=draft_message_id,
                reply_markup=reply_kb,
            )
            sent_count += 1
        except Exception as e:
            print(f"contact_admin: forward to {chat_id} failed: {e}")

    if sent_count > 0:
        if user:
            from django.db.models import F as _F
            from tgbot.models import TelegramProfile as _TP
            from asgiref.sync import sync_to_async
            await sync_to_async(_TP.objects.filter(id=user.id).update)(contact_count=_F('contact_count') + 1)
            try:
                from tgbot.tasks import check_user_achievements
                check_user_achievements.delay(user.id)
            except Exception as _e:
                print(f"contact achievements check failed: {_e}")
        await call.message.answer(
            _t(
                lang,
                "✅ Xabaringiz adminga yuborildi. Tez orada javob beramiz!",
                "✅ Ваше сообщение отправлено администратору. Скоро ответим!",
            )
        )
    else:
        await call.message.answer(
            _t(
                lang,
                "❌ Adminga yuborib bo'lmadi. Keyinroq urinib ko'ring.",
                "❌ Не удалось отправить администратору. Попробуйте позже.",
            )
        )
    await state.finish()


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
    lambda c: c.data and c.data.startswith("admin_reply:"),
    state="*",
)
async def admin_reply_start(call: types.CallbackQuery, state: FSMContext):
    # Only allow inside private chat with admin (BoundFilter IsPrivate doesn't
    # work on CallbackQuery — check manually).
    if call.message and call.message.chat.type != types.ChatType.PRIVATE:
        await call.answer()
        return
    if not _is_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    target_user_id = call.data.split(":", 1)[1]
    await state.finish()
    await state.update_data(reply_target_user_id=target_user_id, is_owner_reply=False)
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(
        f"✍️ Javobingizni yozing (foydalanuvchi: <code>{target_user_id}</code>):\n"
        f"<i>Matn, rasm, video, fayl — istalgan format</i>",
        parse_mode="HTML",
    )
    await AdminReplyState.message.set()


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("owner_reply:"),
    state="*",
)
async def owner_reply_start(call: types.CallbackQuery, state: FSMContext):
    if call.message and call.message.chat.type != types.ChatType.PRIVATE:
        await call.answer()
        return
    if not _is_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    target_user_id = call.data.split(":", 1)[1]
    await state.finish()
    await state.update_data(reply_target_user_id=target_user_id, is_owner_reply=True)
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(
        f"✍️ Loyiha asoschisi nomidan yoziladigan xabarni kiriting (foydalanuvchi: <code>{target_user_id}</code>):\n"
        f"<i>Matn, rasm, video, fayl — istalgan format</i>",
        parse_mode="HTML",
    )
    await AdminReplyState.message.set()


def _admin_reply_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Yuborish", callback_data="ar_send"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="ar_cancel"),
    )


@dp.message_handler(
    state=AdminReplyState.message,
    content_types=types.ContentType.ANY,
)
async def admin_reply_preview(message: types.Message, state: FSMContext):
    """Step 1 of admin's reply: capture draft, ask for confirmation."""
    if message.chat.type != types.ChatType.PRIVATE:
        return
    if not _is_admin(message.from_user.id):
        await state.finish()
        return

    await state.update_data(
        ar_draft_chat_id=message.chat.id,
        ar_draft_message_id=message.message_id,
    )
    data = await state.get_data()
    target_user_id = data.get("reply_target_user_id") or "—"
    is_owner = data.get("is_owner_reply", False)
    prompt = (
        f"Yuqoridagi xabarni foydalanuvchiga (<code>{target_user_id}</code>) Loyiha Asoschisi nomidan yuboraylikmi?"
        if is_owner else
        f"Yuqoridagi javobni foydalanuvchiga (<code>{target_user_id}</code>) yuboraylikmi?"
    )
    await message.answer(
        prompt,
        parse_mode="HTML",
        reply_markup=_admin_reply_confirm_kb(),
    )
    await AdminReplyState.confirm.set()


@dp.callback_query_handler(
    lambda c: c.data == "ar_cancel",
    state=AdminReplyState.confirm,
)
async def admin_reply_cancel(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer("❌ Bekor qilindi.")
    await state.finish()


@dp.callback_query_handler(
    lambda c: c.data == "ar_send",
    state=AdminReplyState.confirm,
)
async def admin_reply_confirm_send(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return

    data = await state.get_data()
    target_user_id = data.get("reply_target_user_id")
    draft_chat_id = data.get("ar_draft_chat_id")
    draft_message_id = data.get("ar_draft_message_id")
    is_owner = data.get("is_owner_reply", False)

    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if not (target_user_id and draft_chat_id and draft_message_id):
        await call.message.answer("❌ Javob ma'lumotlari topilmadi.")
        await state.finish()
        return

    target = await aget_user(int(target_user_id))
    target_lang = (target.language if target else None) or "uz"
    if is_owner:
        header = _t(
            target_lang,
            "✉️ <b>Loyiha asoschisidan xabar:</b>",
            "✉️ <b>Сообщение от владельца проекта:</b>",
        )
    else:
        header = _t(
            target_lang,
            "✉️ <b>Adminstratordan javob:</b>",
            "✉️ <b>Ответ от администратора:</b>",
        )
    try:
        await bot.send_message(
            chat_id=target_user_id, text=header, parse_mode="HTML",
        )
        await bot.copy_message(
            chat_id=int(target_user_id),
            from_chat_id=draft_chat_id,
            message_id=draft_message_id,
        )
        await call.message.answer("✅ Xabar foydalanuvchiga yuborildi.")
    except Exception as e:
        print(f"admin_reply: send to {target_user_id} failed: {e}")
        await call.message.answer(f"❌ Yuborib bo'lmadi: {e}")

    await state.finish()
