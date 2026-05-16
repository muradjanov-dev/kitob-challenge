from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async

from tgbot.bot.filters import IsPrivate
from tgbot.bot.keyboards.reply import back_keyboard
from tgbot.bot.loader import dp
from tgbot.bot.states.main import ReminderState
from tgbot.bot.utils import aget_user
from tgbot.models import ScheduledReminder, TelegramProfile


def _is_admin(user) -> bool:
    return bool(user and user.is_admin)


async def _build_reminders_view():
    """Build (text, keyboard) for the admin reminders panel.
    Each reminder gets its own row with toggle and delete buttons."""
    rems = await sync_to_async(list)(
        ScheduledReminder.objects.all().order_by("hour", "minute")
    )

    if not rems:
        text = "📋 <b>Eslatmalar</b>\n\nHozircha hech qanday eslatma yo'q."
    else:
        lines = [
            "📋 <b>Eslatmalar</b>\n",
            f"<i>Jami: {len(rems)} ta · ✅ faol · ⏸ to'xtatilgan</i>\n",
        ]
        for r in rems:
            status = "✅" if r.is_active else "⏸"
            preview = (r.text or "").replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:77] + "…"
            lines.append(
                f"{status} <b>{r.hour:02d}:{r.minute:02d}</b> · #{r.id}\n"
                f"   <i>{preview}</i>"
            )
        text = "\n".join(lines)

    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(InlineKeyboardButton("➕ Yangi qo'shish", callback_data="rem_add"))
    for r in rems:
        toggle_label = "⏸ To'xtatish" if r.is_active else "▶️ Yoqish"
        kb.row(
            InlineKeyboardButton(
                f"#{r.id} {r.hour:02d}:{r.minute:02d}",
                callback_data="noop",
            ),
            InlineKeyboardButton(toggle_label, callback_data=f"rem_toggle:{r.id}"),
            InlineKeyboardButton("🗑", callback_data=f"rem_del:{r.id}"),
        )
    return text, kb


@dp.message_handler(IsPrivate(), Text("📋 Eslatmalar"), state="*")
async def reminders_menu(message: types.Message, state: FSMContext, _admin_id=None):
    actor_id = _admin_id or message.from_user.id
    user = await aget_user(actor_id)
    if not _is_admin(user):
        await message.answer("Siz admin emassiz!")
        return
    await state.finish()
    text, kb = await _build_reminders_view()
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "rem_add", state="*")
async def reminder_add_start(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    await call.message.answer(
        "✏️ Eslatma matnini yuboring.\n\n"
        "<i>Eslatma poolga qo'shiladi — sistema har kuni "
        "<b>09:00</b> va <b>21:00</b> da poolda mavjud bo'lgan eslatmalardan "
        "tasodifiy birini userlarga yuboradi.</i>",
        parse_mode="HTML",
        reply_markup=back_keyboard,
    )
    await ReminderState.text.set()


@dp.message_handler(IsPrivate(), state=ReminderState.text)
async def reminder_text_received(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Matn bo'sh bo'lmasligi kerak. Qaytadan yuboring:")
        return
    if len(text) > 4000:
        await message.answer("Matn 4000 belgidan oshmasligi kerak. Qisqartiring:")
        return

    creator = await sync_to_async(
        lambda: TelegramProfile.objects.filter(telegram_id=message.from_user.id).first()
    )()
    # hour/minute are kept as zeros (legacy field) — broadcast time is now
    # fixed at 09:00 and 21:00 via celery beat, not per-reminder.
    await sync_to_async(ScheduledReminder.objects.create)(
        text=text, hour=0, minute=0, is_active=True, created_by=creator
    )
    await state.finish()

    await message.answer("✅ Eslatma poolga qo'shildi.")
    list_text, kb = await _build_reminders_view()
    await message.answer(list_text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("rem_del:"))
async def reminder_delete(call: types.CallbackQuery):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    rid = int(call.data.split(":", 1)[1])
    deleted, _ = await sync_to_async(
        ScheduledReminder.objects.filter(id=rid).delete
    )()
    await call.answer("O'chirildi" if deleted else "Topilmadi")
    text, kb = await _build_reminders_view()
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("rem_toggle:"))
async def reminder_toggle(call: types.CallbackQuery):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    rid = int(call.data.split(":", 1)[1])

    def _toggle():
        r = ScheduledReminder.objects.filter(id=rid).first()
        if r:
            r.is_active = not r.is_active
            r.save(update_fields=["is_active"])
            return r.is_active
        return None

    new_state = await sync_to_async(_toggle)()
    if new_state is None:
        await call.answer("Topilmadi")
    else:
        await call.answer("Faollashtirildi" if new_state else "To'xtatildi")
    text, kb = await _build_reminders_view()
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass
