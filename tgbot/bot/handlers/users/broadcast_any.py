"""Admin: send ANY message to every reader (owner, 2026-11-11: "istalgan
forward qilingan xabarni, istalgan file turini va istalgan videoni ham
yuborish mumkin bo'lsin").

The admin sends or forwards one message -- text, photo, video, file, voice,
audio, sticker, an album -- to the bot. The bot shows it back exactly as
readers will get it and asks how to send it:
  📋 Nusxa   -- copyMessage: looks as if the bot wrote it (no "forwarded from")
  ↪️ Forward -- forwardMessage: keeps the original author / channel header
A Celery task (tasks.broadcast_any_message) then sends it to every reachable
reader, and reports the counts back to the admin when done. The original
must stay in the admin's chat until then -- it is copied from there.
"""
import asyncio

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tgbot.bot.filters import IsPrivate
from tgbot.bot.loader import bot, dp
from tgbot.bot.states.main import BroadcastAnyState
from tgbot.bot.utils import aget_user

ALBUM_WAIT_SECONDS = 1.5


async def start(message: types.Message, state: FSMContext):
    await state.finish()
    await BroadcastAnyState.message.set()
    await message.answer(
        "📢 <b>Hammaga xabar</b>\n\n"
        "Yubormoqchi bo'lgan xabarni shu yerga yuboring yoki <b>forward</b> qiling — "
        "matn, rasm, video, fayl, ovozli xabar, audio, albom: istalgani.\n\n"
        "Keyingi qadamda xabar qanday ko'rinishini ko'rasiz va tasdiqlaysiz.\n"
        "Bekor qilish: /bekor",
        parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove(),
    )


@dp.message_handler(IsPrivate(), commands=["bekor"], state=BroadcastAnyState.states)
async def cancel(message: types.Message, state: FSMContext):
    await state.finish()
    from tgbot.bot.keyboards.reply import main_markup
    await message.answer("❌ Bekor qilindi.", reply_markup=main_markup())


def _choice_kb(forwarded: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📋 Nusxa sifatida yuborish (manbasiz)", callback_data="bcany:copy"))
    if forwarded:
        kb.add(InlineKeyboardButton("↪️ Forward qilish (manba ko'rinadi)", callback_data="bcany:forward"))
    kb.add(InlineKeyboardButton("❌ Bekor qilish", callback_data="bcany:cancel"))
    return kb


@dp.message_handler(IsPrivate(), state=BroadcastAnyState.message, content_types=types.ContentTypes.ANY)
async def got_message(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    if not user or not user.is_admin:
        await state.finish()
        return
    forwarded = bool(message.forward_date)
    if message.media_group_id:
        # An album arrives as several messages; collect them, answer once.
        data = await state.get_data()
        ids = list(data.get("ids") or []) if data.get("group") == message.media_group_id else []
        first = not ids
        ids.append(message.message_id)
        await state.update_data(ids=sorted(ids), group=message.media_group_id, forwarded=forwarded)
        if not first:
            return
        await asyncio.sleep(ALBUM_WAIT_SECONDS)
    else:
        await state.update_data(ids=[message.message_id], group=None, forwarded=forwarded)

    data = await state.get_data()
    ids = data["ids"]
    await message.answer("👇 Kitobxonlar xabarni aynan shunday ko'radi:")
    try:
        if len(ids) > 1:
            await bot.request("copyMessages", {"chat_id": message.chat.id, "from_chat_id": message.chat.id,
                                               "message_ids": __import__("json").dumps(ids)})
        else:
            await bot.copy_message(message.chat.id, message.chat.id, ids[0])
    except Exception as e:
        await message.answer(f"⚠️ Ko'rsatib bo'lmadi: {e}")
    count = await _reachable_count()
    await BroadcastAnyState.confirm.set()
    await message.answer(
        f"📨 Qabul qiluvchilar: <b>{count}</b> kitobxon (botni bloklamaganlar).\n"
        f"{'🖼 Albom: ' + str(len(ids)) + ' ta' + chr(10) if len(ids) > 1 else ''}"
        "Qanday yuboramiz?",
        parse_mode="HTML", reply_markup=_choice_kb(data.get("forwarded")),
    )


async def _reachable_count() -> int:
    from asgiref.sync import sync_to_async
    from tgbot.models import TelegramProfile
    return await sync_to_async(
        lambda: TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
        .values("telegram_id").distinct().count())()


@dp.callback_query_handler(lambda c: c.data.startswith("bcany:"), state=BroadcastAnyState.confirm)
async def decide(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user or not user.is_admin:
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    mode = call.data.split(":", 1)[1]
    data = await state.get_data()
    await state.finish()
    try:
        await call.message.edit_reply_markup(None)
    except Exception:
        pass
    if mode == "cancel" or not data.get("ids"):
        await call.answer("Bekor qilindi")
        await call.message.answer("❌ Bekor qilindi.")
        return
    from tgbot.tasks import broadcast_any_message
    broadcast_any_message.delay(call.message.chat.id, data["ids"], mode, call.from_user.id)
    await call.answer("Yuborish boshlandi")
    await call.message.answer(
        "🚀 <b>Yuborish boshlandi.</b> Tugagach natijani shu yerga yozaman.\n"
        "<i>Asl xabarni yuborish tugaguncha o'chirmang — u shu chatdan nusxalanadi.</i>",
        parse_mode="HTML",
    )
