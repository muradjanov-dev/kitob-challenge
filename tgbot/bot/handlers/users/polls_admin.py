from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async

from tgbot.bot.filters import IsPrivate
from tgbot.bot.keyboards.reply import admin_keyboard, back_keyboard
from tgbot.bot.loader import dp
from tgbot.bot.states.main import PollAdminState
from tgbot.bot.utils import aget_user
from tgbot.models import BotPoll, BotPollVote, TelegramProfile


def _is_admin(user) -> bool:
    return bool(user and user.is_admin)


def _confirm_kb():
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Yuborish", callback_data="poll_send"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="poll_cancel"),
    )


def _results_refresh_kb(poll_id: int):
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🔄 Yangilash", callback_data=f"poll_refresh:{poll_id}")
    )


def _vote_kb(poll: BotPoll):
    kb = InlineKeyboardMarkup(row_width=1)
    for idx, opt in enumerate(poll.options):
        kb.add(InlineKeyboardButton(opt, callback_data=f"poll_vote:{poll.id}:{idx}"))
    return kb


@dp.message_handler(IsPrivate(), Text("📊 So'rovnoma"), state="*")
async def poll_admin_start(message: types.Message, state: FSMContext, _admin_id=None):
    actor_id = _admin_id or message.from_user.id
    user = await aget_user(actor_id)
    if not _is_admin(user):
        await message.answer("Siz admin emassiz!")
        return
    await state.finish()
    await message.answer(
        "📊 <b>Yangi so'rovnoma</b>\n\n"
        "1️⃣ Avval savolni yuboring:",
        parse_mode="HTML",
        reply_markup=back_keyboard,
    )
    await PollAdminState.question.set()


@dp.message_handler(IsPrivate(), state=PollAdminState.question)
async def poll_question_received(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Savol bo'sh bo'lmasligi kerak. Qaytadan yuboring:")
        return
    if len(text) > 1000:
        await message.answer("Savol 1000 belgidan oshmasligi kerak.")
        return
    await state.update_data(question=text)
    await message.answer(
        "2️⃣ Variantlarni har birini yangi qatordan yuboring (kamida 2 ta, ko'pi bilan 10 ta):",
        reply_markup=back_keyboard,
    )
    await PollAdminState.options.set()


@dp.message_handler(IsPrivate(), state=PollAdminState.options)
async def poll_options_received(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    options = [line.strip() for line in raw.split("\n") if line.strip()]
    if len(options) < 2:
        await message.answer("Kamida 2 ta variant kerak. Qaytadan yuboring:")
        return
    if len(options) > 10:
        await message.answer("Ko'pi bilan 10 ta variant. Qaytadan yuboring:")
        return
    if any(len(o) > 100 for o in options):
        await message.answer("Har bir variant 100 belgidan kam bo'lsin.")
        return
    await state.update_data(options=options)

    data = await state.get_data()
    preview = (
        f"📊 <b>So'rovnoma:</b>\n\n"
        f"<b>{data['question']}</b>\n\n"
        + "\n".join(f"  • {o}" for o in options)
        + "\n\nBarcha foydalanuvchilarga yuborilsinmi?"
    )
    await message.answer(preview, parse_mode="HTML", reply_markup=_confirm_kb())
    await PollAdminState.confirm.set()


@dp.callback_query_handler(lambda c: c.data == "poll_cancel", state=PollAdminState.confirm)
async def poll_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await call.answer("Bekor qilindi")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer("So'rovnoma bekor qilindi.", reply_markup=admin_keyboard)


@dp.callback_query_handler(lambda c: c.data == "poll_send", state=PollAdminState.confirm)
async def poll_send(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    data = await state.get_data()
    creator = await sync_to_async(
        lambda: TelegramProfile.objects.filter(telegram_id=call.from_user.id).first()
    )()
    poll = await sync_to_async(BotPoll.objects.create)(
        question=data["question"],
        options=data["options"],
        is_active=True,
        created_by=creator,
    )
    await state.finish()
    await call.answer("Yuborilmoqda...")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(
        f"✅ So'rovnoma <code>#{poll.id}</code> yaratildi va yuborilmoqda.",
        parse_mode="HTML",
        reply_markup=admin_keyboard,
    )

    # Trigger broadcast in Celery so we don't block the admin's chat
    from tgbot.tasks import broadcast_poll
    broadcast_poll.delay(poll.id)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("poll_vote:"))
async def poll_vote(call: types.CallbackQuery):
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer()
        return
    poll_id, opt_idx = int(parts[1]), int(parts[2])

    poll = await sync_to_async(
        lambda: BotPoll.objects.filter(id=poll_id).first()
    )()
    if not poll or not poll.is_active:
        await call.answer("So'rovnoma yopilgan", show_alert=True)
        return
    if opt_idx >= len(poll.options):
        await call.answer("Variant topilmadi", show_alert=True)
        return

    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start yuboring", show_alert=True)
        return

    def _vote():
        obj, created = BotPollVote.objects.update_or_create(
            poll=poll, user=user, defaults={"option_index": opt_idx}
        )
        return created, obj.option_index

    created, idx = await sync_to_async(_vote)()

    chosen = poll.options[idx]
    if created:
        await call.answer(f"✅ Ovozingiz: {chosen}", show_alert=False)
    else:
        await call.answer(f"O'zgartirildi: {chosen}", show_alert=False)


@dp.message_handler(IsPrivate(), Text("📊 So'rovnoma natijalari"), state="*")
async def poll_results_list(message: types.Message, state: FSMContext, _admin_id=None):
    actor_id = _admin_id or message.from_user.id
    user = await aget_user(actor_id)
    if not _is_admin(user):
        await message.answer("Siz admin emassiz!")
        return
    await state.finish()

    polls = await sync_to_async(list)(
        BotPoll.objects.all().order_by("-created_at")[:5]
    )
    if not polls:
        await message.answer("Hech qanday so'rovnoma yo'q.")
        return

    lines = ["📊 <b>So'nggi so'rovnomalar</b>\n"]
    kb = InlineKeyboardMarkup(row_width=1)
    for p in polls:
        active = "✅" if p.is_active else "⏸"
        lines.append(f"{active} #{p.id}: {p.question[:60]}")
        kb.add(InlineKeyboardButton(f"📊 #{p.id} natijalar", callback_data=f"poll_refresh:{p.id}"))
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("poll_refresh:"))
async def poll_refresh(call: types.CallbackQuery):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    poll_id = int(call.data.split(":", 1)[1])

    def _stats():
        p = BotPoll.objects.filter(id=poll_id).first()
        if not p:
            return None
        votes = BotPollVote.objects.filter(poll=p)
        total = votes.count()
        counts = {i: 0 for i in range(len(p.options))}
        for v in votes.values_list("option_index", flat=True):
            counts[v] = counts.get(v, 0) + 1
        return p, total, counts

    res = await sync_to_async(_stats)()
    if not res:
        await call.answer("Topilmadi", show_alert=True)
        return
    poll, total, counts = res

    lines = [
        f"📊 <b>So'rovnoma #{poll.id}</b>",
        f"<i>{poll.question}</i>",
        f"\n👥 Jami ovozlar: <b>{total}</b>\n",
    ]
    for i, opt in enumerate(poll.options):
        c = counts.get(i, 0)
        pct = (c / total * 100) if total else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        lines.append(f"  {opt}\n  <code>{bar}</code> {c} ({pct:.0f}%)")

    text = "\n".join(lines)
    await call.answer("Yangilandi")
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=_results_refresh_kb(poll.id))
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=_results_refresh_kb(poll.id))
