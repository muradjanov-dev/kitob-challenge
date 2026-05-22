"""Quiz admin: create, list, edit, delete, launch Vizov."""
import os
import json

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.bot.states.main import QuizCreateState, QuizEditState, QuizBattleState
from tgbot.models import Quiz, QuizQuestion, QuizOption, QuizSession, TelegramProfile

BOT_USERNAME = os.environ.get("BOT_USERNAME", "kitob_challange_bot")

# ─── helpers ──────────────────────────────────────────────────────────────────

def _is_admin(user) -> bool:
    return bool(user and getattr(user, "is_admin", False))


@sync_to_async
def _is_active_premium(user) -> bool:
    """Active Premium subscription right now."""
    from django.utils import timezone as _tz
    from tgbot.models import Payment
    if not user:
        return False
    return Payment.objects.filter(
        user=user, status="paid", end_date__gte=_tz.localdate(),
    ).exists()


async def _can_manage_quizzes(user) -> bool:
    """Either an admin or an active Premium subscriber. Each quiz handler
    additionally filters by creator=user, so a Premium user can only see
    and edit their own quizzes."""
    if _is_admin(user):
        return True
    return await _is_active_premium(user)


def _quiz_link(code: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=quiz_{code}"


def _quiz_list_kb(quizzes) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    for q in quizzes:
        kb.add(InlineKeyboardButton(
            text=f"📝 {q.title} ({q.questions.count()} savol)",
            callback_data=f"qz:v:{q.id}",
        ))
    kb.add(InlineKeyboardButton(text="➕ Yangi quiz", callback_data="qz:new"))
    kb.add(InlineKeyboardButton(text="🤖 AI yordamida yaratish (Premium)", callback_data="qz:ai"))
    return kb


def _quiz_view_kb(quiz) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    shuffle_label = "🔀 Shuffle: ✅" if quiz.shuffle else "🔀 Shuffle: ❌"
    kb.row(
        InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"qz:e:{quiz.id}"),
        InlineKeyboardButton(text=shuffle_label, callback_data=f"qz:sh:{quiz.id}"),
    )
    kb.row(InlineKeyboardButton(text="🏆 Vizov yaratish", callback_data=f"qz:viz:{quiz.id}"))
    # Share to a group: Telegram's ?startgroup flow lets the user pick a group
    # to add the bot to (or reuse an existing membership); the bot then receives
    # /start quiz_<code> from that group and spins up a group session.
    kb.row(InlineKeyboardButton(
        text="📤 Guruhga ulashish",
        url=f"https://t.me/{BOT_USERNAME}?startgroup=quiz_{quiz.link_code}",
    ))
    kb.row(InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"qz:del:{quiz.id}"))
    kb.row(InlineKeyboardButton(text="« Orqaga", callback_data="qz:ls"))
    return kb


def _quiz_edit_kb(quiz_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton(text="✏️ Nomini o'zgartirish", callback_data=f"qz:et:{quiz_id}"),
        InlineKeyboardButton(text="📝 Tavsifini o'zgartirish", callback_data=f"qz:ed:{quiz_id}"),
        InlineKeyboardButton(text="⏱ Vaqtini o'zgartirish", callback_data=f"qz:em:{quiz_id}"),
        InlineKeyboardButton(text="❓ Savollarni tahrirlash", callback_data=f"qz:eqs:{quiz_id}"),
        InlineKeyboardButton(text="« Orqaga", callback_data=f"qz:v:{quiz_id}"),
    )
    return kb


async def _quiz_view_text(quiz) -> str:
    q_count = await sync_to_async(quiz.questions.count)()
    link = _quiz_link(quiz.link_code)
    return (
        f"📝 <b>{quiz.title}</b>\n\n"
        f"📖 {quiz.description or '—'}\n\n"
        f"❓ Savollar: <b>{q_count}</b>\n"
        f"⏱ Har savol: <b>{quiz.time_per_question} soniya</b>\n"
        f"🔀 Shuffle: {'✅' if quiz.shuffle else '❌'}\n\n"
        f"🔗 Link:\n<code>{link}</code>"
    )


async def _safe_edit_or_send(call, text, reply_markup=None):
    """edit_text the current message, falling back to a fresh message if
    Telegram rejects the edit (too old, identical content, has media, etc).
    Prevents 'nothing happens' silent failures in the edit flow."""
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:
        try:
            await call.message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as e:
            print(f"_safe_edit_or_send failed: {e}")


async def _render_question_view(call, q_id: int):
    """Question detail card with full edit controls: per-option text edit,
    correct-answer radio, question-text edit, hint edit, delete."""
    @sync_to_async
    def _load(qid):
        q = QuizQuestion.objects.select_related("quiz").get(id=qid)
        return q, list(q.options.all().order_by("order"))

    q, opts = await _load(q_id)
    await _safe_edit_or_send(
        call, _question_view_body(q, opts), _question_view_markup(q, opts),
    )


# ─── entry point: "📝 Quizlar" from admin panel ───────────────────────────────

async def show_quiz_list(message: types.Message, user):
    quizzes = await sync_to_async(list)(
        Quiz.objects.filter(creator=user).prefetch_related("questions")
    )
    if not quizzes:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(text="➕ Yangi quiz yaratish", callback_data="qz:new"))
        kb.add(InlineKeyboardButton(text="🤖 AI yordamida yaratish (Premium)", callback_data="qz:ai"))
        await message.answer(
            "📭 Hali quiz yo'q. Birinchisini yarating!",
            reply_markup=kb,
        )
        return
    await message.answer(
        f"📋 Sizning quizlaringiz ({len(quizzes)} ta):",
        reply_markup=_quiz_list_kb(quizzes),
    )


# ─── inline router ─────────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qz:"), state="*")
async def quiz_admin_router(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not await _can_manage_quizzes(user):
        await call.answer(
            "Quiz yaratish va boshqarish — admin yoki 💎 Premium foydalanuvchilar uchun.",
            show_alert=True,
        )
        return

    parts = call.data.split(":")
    action = parts[1]

    # Vizov (live broadcast to every registered user) stays admin-only — it's
    # a high-volume action that non-admin Premium users shouldn't trigger.
    if action == "viz" and not _is_admin(user):
        await call.answer("Vizov yuborish faqat adminlar uchun.", show_alert=True)
        return

    # List
    if action == "ls":
        await call.answer()
        quizzes = await sync_to_async(list)(
            Quiz.objects.filter(creator=user).prefetch_related("questions")
        )
        if not quizzes:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton(text="➕ Yangi quiz", callback_data="qz:new"))
            kb.add(InlineKeyboardButton(text="🤖 AI yordamida yaratish (Premium)", callback_data="qz:ai"))
            await call.message.edit_text("📭 Hali quiz yo'q.", reply_markup=kb)
            return
        try:
            await call.message.edit_text(
                f"📋 Quizlaringiz ({len(quizzes)} ta):",
                reply_markup=_quiz_list_kb(quizzes),
            )
        except Exception:
            pass

    # New quiz — start creation
    elif action == "new":
        await call.answer()
        await state.finish()
        await call.message.answer("📝 Quiz nomini kiriting:")
        await QuizCreateState.title.set()

    # AI quiz — start creation
    elif action == "ai":
        from django.utils import timezone
        from tgbot.models import Payment
        from tgbot.bot.states.main import AIQuizCreateState
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        is_premium = await sync_to_async(
            Payment.objects.filter(user=user, status="paid", end_date__gte=timezone.localdate()).exists
        )()
        if not is_premium:
            await call.answer("Bu funksiya faqat Premium foydalanuvchilar uchun! ⭐", show_alert=True)
            return
            
        await call.answer()
        await state.finish()
        
        kb = InlineKeyboardMarkup(row_width=5)
        kb.add(
            InlineKeyboardButton("5", callback_data="aiqz_q:5"),
            InlineKeyboardButton("10", callback_data="aiqz_q:10"),
            InlineKeyboardButton("15", callback_data="aiqz_q:15"),
            InlineKeyboardButton("20", callback_data="aiqz_q:20"),
            InlineKeyboardButton("25", callback_data="aiqz_q:25"),
        )
        await call.message.answer(
            "🤖 <b>AI yordamida Quiz yaratish</b>\n\n"
            "Nechta savol bo'lishini xohlaysiz? Quyidagi tugmalardan birini tanlang:",
            parse_mode="HTML",
            reply_markup=kb
        )
        await AIQuizCreateState.question_count.set()

    # View
    elif action == "v" and len(parts) > 2:
        await call.answer()
        quiz = await sync_to_async(Quiz.objects.filter(id=parts[2]).first)()
        if not quiz or quiz.creator_id != user.id:
            await call.answer("Topilmadi", show_alert=True)
            return
        text = await _quiz_view_text(quiz)
        try:
            await call.message.edit_text(text, parse_mode="HTML",
                                          reply_markup=_quiz_view_kb(quiz))
        except Exception:
            await call.message.answer(text, parse_mode="HTML",
                                       reply_markup=_quiz_view_kb(quiz))

    # Edit menu
    elif action == "e" and len(parts) > 2:
        await call.answer()
        quiz_id = int(parts[2])
        await _safe_edit_or_send(
            call, "✏️ Nimani o'zgartirmoqchisiz?", _quiz_edit_kb(quiz_id),
        )

    # Edit title
    elif action == "et" and len(parts) > 2:
        await call.answer()
        await state.update_data(edit_quiz_id=int(parts[2]), edit_field="title")
        await call.message.answer("Yangi nomni kiriting:")
        await QuizEditState.title.set()

    # Edit description
    elif action == "ed" and len(parts) > 2:
        await call.answer()
        await state.update_data(edit_quiz_id=int(parts[2]), edit_field="description")
        await call.message.answer("Yangi tavsifni kiriting:")
        await QuizEditState.description.set()

    # Edit time
    elif action == "em" and len(parts) > 2:
        await call.answer()
        await state.update_data(edit_quiz_id=int(parts[2]), edit_field="time")
        await call.message.answer("Har savol necha soniya bo'lsin? (masalan: 30):")
        await QuizEditState.time.set()

    # Edit Questions List
    elif action == "eqs" and len(parts) > 2:
        await call.answer()
        quiz_id = int(parts[2])
        questions = await sync_to_async(list)(QuizQuestion.objects.filter(quiz_id=quiz_id).order_by('order'))
        kb = InlineKeyboardMarkup(row_width=1)
        for q in questions:
            kb.add(InlineKeyboardButton(text=f"❓ {q.text[:30]}...", callback_data=f"qz:qv:{q.id}"))
        kb.add(InlineKeyboardButton(text="« Orqaga", callback_data=f"qz:e:{quiz_id}"))
        await _safe_edit_or_send(call, "✏️ Qaysi savolni tahrirlaysiz?", kb)

    # Question View
    elif action == "qv" and len(parts) > 2:
        await call.answer()
        q_id = int(parts[2])
        await _render_question_view(call, q_id)

    # Edit Question Text
    elif action == "qt" and len(parts) > 2:
        await call.answer()
        q_id = int(parts[2])
        await state.update_data(edit_q_id=q_id)
        await call.message.answer("Yangi savol matnini kiriting:")
        await QuizEditState.edit_q_text.set()

    # Edit Question Hint
    elif action == "qh" and len(parts) > 2:
        await call.answer()
        q_id = int(parts[2])
        await state.update_data(edit_q_id=q_id)
        await call.message.answer(
            "Yangi maslahatni (hint) kiriting.\n"
            "<i>(Maslahatni o'chirish uchun «—» yuboring.)</i>",
            parse_mode="HTML",
        )
        await QuizEditState.edit_q_hint.set()

    # Edit an Option's text
    elif action == "optt" and len(parts) > 2:
        await call.answer()
        opt_id = int(parts[2])
        await state.update_data(edit_opt_id=opt_id)
        await call.message.answer("Variant uchun yangi matn kiriting:")
        await QuizEditState.edit_q_opts.set()

    # Mark an Option as the correct answer (radio: clears siblings)
    elif action == "optc" and len(parts) > 2:
        opt_id = int(parts[2])

        @sync_to_async
        def _set_correct():
            opt = QuizOption.objects.select_related("question").get(id=opt_id)
            QuizOption.objects.filter(question_id=opt.question_id).update(is_correct=False)
            QuizOption.objects.filter(id=opt_id).update(is_correct=True)
            return opt.question_id

        q_id = await _set_correct()
        await call.answer("✅ To'g'ri javob belgilandi")
        await _render_question_view(call, q_id)

    # Delete Question
    elif action == "qdel" and len(parts) > 2:
        q_id = int(parts[2])
        q = await sync_to_async(QuizQuestion.objects.select_related('quiz').get)(id=q_id)
        quiz_id = q.quiz_id
        await sync_to_async(q.delete)()
        await call.answer("Savol o'chirildi ✅")
        
        questions = await sync_to_async(list)(QuizQuestion.objects.filter(quiz_id=quiz_id).order_by('order'))
        kb = InlineKeyboardMarkup(row_width=1)
        for q_item in questions:
            kb.add(InlineKeyboardButton(text=f"❓ {q_item.text[:30]}...", callback_data=f"qz:qv:{q_item.id}"))
        kb.add(InlineKeyboardButton(text="« Orqaga", callback_data=f"qz:e:{quiz_id}"))
        await _safe_edit_or_send(call, "✏️ Qaysi savolni tahrirlaysiz?", kb)

    # Toggle shuffle
    elif action == "sh" and len(parts) > 2:
        quiz = await sync_to_async(Quiz.objects.filter(id=parts[2]).first)()
        if not quiz or quiz.creator_id != user.id:
            await call.answer("Topilmadi", show_alert=True)
            return
        new_val = not quiz.shuffle
        await sync_to_async(Quiz.objects.filter(id=quiz.id).update)(shuffle=new_val)
        quiz.shuffle = new_val
        await call.answer("🔀 Shuffle " + ("yoqildi ✅" if new_val else "o'chirildi ❌"))
        text = await _quiz_view_text(quiz)
        try:
            await call.message.edit_text(text, parse_mode="HTML",
                                          reply_markup=_quiz_view_kb(quiz))
        except Exception:
            pass

    # Delete confirm
    elif action == "del" and len(parts) > 2:
        await call.answer()
        kb = InlineKeyboardMarkup(row_width=2)
        kb.row(
            InlineKeyboardButton(text="⚠️ Ha, o'chirish", callback_data=f"qz:dc:{parts[2]}"),
            InlineKeyboardButton(text="❌ Bekor", callback_data=f"qz:v:{parts[2]}"),
        )
        await call.message.edit_text(
            "🗑 Quizni o'chirishni tasdiqlaysizmi?\n<i>Barcha savollar ham o'chiriladi.</i>",
            parse_mode="HTML",
            reply_markup=kb,
        )

    # Delete confirmed
    elif action == "dc" and len(parts) > 2:
        quiz = await sync_to_async(Quiz.objects.filter(id=parts[2]).first)()
        if not quiz or quiz.creator_id != user.id:
            await call.answer("Topilmadi", show_alert=True)
            return
        await sync_to_async(quiz.delete)()
        await call.answer("✅ O'chirildi")
        quizzes = await sync_to_async(list)(
            Quiz.objects.filter(creator=user).prefetch_related("questions")
        )
        if not quizzes:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton(text="➕ Yangi quiz", callback_data="qz:new"))
            await call.message.edit_text("📭 Hali quiz yo'q.", reply_markup=kb)
        else:
            await call.message.edit_text(
                f"📋 Quizlaringiz ({len(quizzes)} ta):",
                reply_markup=_quiz_list_kb(quizzes),
            )

    # Vizov (live battle) setup
    elif action == "viz" and len(parts) > 2:
        await call.answer()
        quiz = await sync_to_async(Quiz.objects.filter(id=parts[2]).first)()
        if not quiz or quiz.creator_id != user.id:
            await call.answer("Topilmadi", show_alert=True)
            return
        q_count = await sync_to_async(quiz.questions.count)()
        if q_count == 0:
            await call.answer("Quiz bo'sh — avval savol qo'shing!", show_alert=True)
            return
        await state.update_data(vizov_quiz_id=quiz.id)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(text="⚡ Hozir boshlash", callback_data="qzviz:now"))
        await call.message.answer(
            f"🏆 <b>Vizov: {quiz.title}</b>\n\n"
            "Boshlanish vaqtini kiriting (masalan: <code>14:30</code>)\n"
            "yoki hozir boshlash uchun tugmani bosing:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        await QuizBattleState.start_time.set()

    else:
        await call.answer()


# ─── Creation flow ─────────────────────────────────────────────────────────────

@dp.message_handler(state=QuizCreateState.title)
async def qz_got_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    if not title:
        await message.answer("Nom bo'sh bo'lmasligi kerak.")
        return
    await state.update_data(qz_title=title)
    await message.answer("📖 Quiz tavsifini kiriting (yoki — yuboring):")
    await QuizCreateState.description.set()


@dp.message_handler(state=QuizCreateState.description)
async def qz_got_desc(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    data = await state.get_data()
    desc = message.text.strip() if message.text.strip() != "—" else ""

    @sync_to_async
    def _save():
        return Quiz.objects.create(
            creator=user,
            title=data["qz_title"],
            description=desc,
        )

    quiz = await _save()
    await state.update_data(qz_id=quiz.id, q_count=0)
    await message.answer(
        f"✅ Quiz yaratildi.\n\n"
        f"Endi <b>1-savolni</b> kiriting:",
        parse_mode="HTML",
    )
    await QuizCreateState.q_text.set()


@dp.message_handler(state=QuizCreateState.q_text)
async def qz_got_q_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("Savol matni bo'sh bo'lmasligi kerak.")
        return
    await state.update_data(cur_q_text=text, cur_opts=[], cur_correct=None)
    await message.answer(
        f"<b>1-variant</b> matnini kiriting:",
        parse_mode="HTML",
    )
    await QuizCreateState.q_options.set()


@dp.message_handler(state=QuizCreateState.q_options)
async def qz_got_option(message: types.Message, state: FSMContext):
    data = await state.get_data()
    opts: list = data.get("cur_opts", [])

    if len(opts) >= 5:
        await message.answer("Maksimal 5 ta variant. Yuqoridagi tugmalardan birini bosing.")
        return

    opts.append(message.text.strip())
    await state.update_data(cur_opts=opts)

    # Show current options list + action buttons
    opts_text = "\n".join(f"{'ABCDE'[i]}) {o}" for i, o in enumerate(opts))
    kb = InlineKeyboardMarkup(row_width=1)
    if len(opts) < 5:
        kb.add(InlineKeyboardButton(
            text=f"➕ {len(opts)+1}-variant qo'shish", callback_data="qzc:more"
        ))
    if len(opts) >= 2:
        kb.add(InlineKeyboardButton(
            text="✅ To'g'ri javobni belgilang", callback_data="qzc:pick"
        ))

    await message.answer(
        f"<b>Variantlar:</b>\n{opts_text}",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query_handler(lambda c: c.data == "qzc:more", state=QuizCreateState.q_options)
async def qzc_add_more(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    n = len(data.get("cur_opts", [])) + 1
    await call.message.answer(f"<b>{n}-variant</b> matnini kiriting:", parse_mode="HTML")


@dp.callback_query_handler(lambda c: c.data == "qzc:pick", state=QuizCreateState.q_options)
async def qzc_pick_correct(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    opts = data.get("cur_opts", [])
    kb = InlineKeyboardMarkup(row_width=1)
    for i, opt in enumerate(opts):
        kb.add(InlineKeyboardButton(
            text=f"{'ABCDE'[i]}) {opt}",
            callback_data=f"qzc:co:{i}",
        ))
    await call.message.answer(
        "✅ To'g'ri javobni tanlang:",
        reply_markup=kb,
    )


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qzc:co:"), state=QuizCreateState.q_options)
async def qzc_correct_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    idx = int(call.data.split(":")[2])
    await state.update_data(cur_correct=idx)
    await call.message.answer(
        "💡 Hint kiriting (javob topilmasa ko'rsatiladi):"
    )
    await QuizCreateState.q_hint.set()


@dp.message_handler(state=QuizCreateState.q_hint)
async def qz_got_hint(message: types.Message, state: FSMContext):
    hint = message.text.strip()
    data = await state.get_data()

    @sync_to_async
    def _save_question():
        q = QuizQuestion.objects.create(
            quiz_id=data["qz_id"],
            text=data["cur_q_text"],
            hint=hint,
            order=data.get("q_count", 0),
        )
        for i, opt_text in enumerate(data["cur_opts"]):
            QuizOption.objects.create(
                question=q,
                text=opt_text,
                is_correct=(i == data["cur_correct"]),
                order=i,
            )
        return q

    await _save_question()
    q_count = data.get("q_count", 0) + 1
    await state.update_data(q_count=q_count, cur_opts=[], cur_q_text=None, cur_correct=None)

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton(text=f"➕ {q_count+1}-savol qo'shish", callback_data="qzc:nq"),
        InlineKeyboardButton(text="✅ Tayyor", callback_data="qzc:done"),
    )
    await message.answer(
        f"✅ <b>{q_count}-savol</b> saqlandi.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query_handler(lambda c: c.data == "qzc:nq", state=QuizCreateState.q_hint)
async def qzc_next_question(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    n = data.get("q_count", 0) + 1
    await call.message.answer(f"<b>{n}-savol</b> matnini kiriting:", parse_mode="HTML")
    await QuizCreateState.q_text.set()


@dp.callback_query_handler(lambda c: c.data == "qzc:done", state=QuizCreateState.q_hint)
async def qzc_done_questions(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("⏱ Har bir savol necha soniyalik bo'lsin? (masalan: 30):")
    await QuizCreateState.time_limit.set()


@dp.message_handler(state=QuizCreateState.time_limit)
async def qz_got_time(message: types.Message, state: FSMContext):
    try:
        secs = int(message.text.strip())
        if secs < 5 or secs > 300:
            raise ValueError
    except ValueError:
        await message.answer("Iltimos, 5–300 orasidagi sonni kiriting.")
        return

    data = await state.get_data()
    quiz = await sync_to_async(Quiz.objects.filter(id=data["qz_id"]).first)()
    if not quiz:
        await message.answer("Xatolik.")
        await state.finish()
        return

    await sync_to_async(Quiz.objects.filter(id=quiz.id).update)(time_per_question=secs)
    quiz.time_per_question = secs
    await state.finish()

    link = _quiz_link(quiz.link_code)
    q_count = await sync_to_async(quiz.questions.count)()
    await message.answer(
        f"🎉 <b>Quiz tayyor!</b>\n\n"
        f"📝 <b>{quiz.title}</b>\n"
        f"❓ {q_count} ta savol · ⏱ {secs} soniya\n\n"
        f"🔗 Link:\n<code>{link}</code>\n\n"
        f"Link orqali solo yechish yoki Vizov uchun quyidagi tugmani bosing:",
        parse_mode="HTML",
        reply_markup=_quiz_view_kb(quiz),
    )


# ─── Edit flow ─────────────────────────────────────────────────────────────────

@dp.message_handler(state=QuizEditState.title)
async def qze_got_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await sync_to_async(Quiz.objects.filter(id=data["edit_quiz_id"]).update)(title=message.text.strip())
    await state.finish()
    await message.answer("✅ Nom yangilandi.")


@dp.message_handler(state=QuizEditState.description)
async def qze_got_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    desc = message.text.strip() if message.text.strip() != "—" else ""
    await sync_to_async(Quiz.objects.filter(id=data["edit_quiz_id"]).update)(description=desc)
    await state.finish()
    await message.answer("✅ Tavsif yangilandi.")


@dp.message_handler(state=QuizEditState.time)
async def qze_got_time(message: types.Message, state: FSMContext):
    try:
        secs = int(message.text.strip())
        if secs < 5 or secs > 300:
            raise ValueError
    except ValueError:
        await message.answer("5–300 orasidagi son kiriting.")
        return
    data = await state.get_data()
    await sync_to_async(Quiz.objects.filter(id=data["edit_quiz_id"]).update)(time_per_question=secs)
    await state.finish()
    await message.answer(f"✅ Vaqt {secs} soniyaga yangilandi.")

def _question_view_markup(q, opts):
    kb = InlineKeyboardMarkup(row_width=2)
    for i, opt in enumerate(opts):
        letter = "ABCDE"[i] if i < 5 else "-"
        correct_label = "✅ To'g'ri" if opt.is_correct else "⚪️ To'g'ri deb belgilash"
        kb.row(
            InlineKeyboardButton(text=f"✏️ {letter} matni", callback_data=f"qz:optt:{opt.id}"),
            InlineKeyboardButton(text=correct_label, callback_data=f"qz:optc:{opt.id}"),
        )
    kb.row(InlineKeyboardButton(text="✏️ Savol matni", callback_data=f"qz:qt:{q.id}"))
    kb.row(InlineKeyboardButton(text="💡 Maslahatni o'zgartirish", callback_data=f"qz:qh:{q.id}"))
    kb.row(InlineKeyboardButton(text="🗑 Savolni o'chirish", callback_data=f"qz:qdel:{q.id}"))
    kb.row(InlineKeyboardButton(text="« Orqaga", callback_data=f"qz:eqs:{q.quiz_id}"))
    return kb


def _question_view_body(q, opts):
    text = f"❓ <b>{q.text}</b>\n\n"
    if q.hint:
        text += f"💡 Maslahat: <i>{q.hint}</i>\n\n"
    text += "Variantlar (✅ = to'g'ri javob):\n"
    for i, opt in enumerate(opts):
        mark = "✅" if opt.is_correct else "▫️"
        text += f"{mark} {'ABCDE'[i] if i < 5 else '-'}) {opt.text}\n"
    return text


@dp.message_handler(state=QuizEditState.edit_q_text)
async def qze_got_q_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    q_id = data.get("edit_q_id")
    await sync_to_async(QuizQuestion.objects.filter(id=q_id).update)(text=message.text.strip())

    @sync_to_async
    def _load(qid):
        q = QuizQuestion.objects.select_related("quiz").get(id=qid)
        return q, list(q.options.all().order_by("order"))

    q, opts = await _load(q_id)
    await state.finish()
    await message.answer(
        "✅ Savol matni yangilandi.\n\n" + _question_view_body(q, opts),
        parse_mode="HTML",
        reply_markup=_question_view_markup(q, opts),
    )


@dp.message_handler(state=QuizEditState.edit_q_hint)
async def qze_got_q_hint(message: types.Message, state: FSMContext):
    data = await state.get_data()
    q_id = data.get("edit_q_id")
    hint = message.text.strip()
    if hint == "—":
        hint = ""
    await sync_to_async(QuizQuestion.objects.filter(id=q_id).update)(hint=hint)

    @sync_to_async
    def _load(qid):
        q = QuizQuestion.objects.select_related("quiz").get(id=qid)
        return q, list(q.options.all().order_by("order"))

    q, opts = await _load(q_id)
    await state.finish()
    await message.answer(
        "✅ Maslahat yangilandi.\n\n" + _question_view_body(q, opts),
        parse_mode="HTML",
        reply_markup=_question_view_markup(q, opts),
    )


@dp.message_handler(state=QuizEditState.edit_q_opts)
async def qze_got_opt_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    opt_id = data.get("edit_opt_id")
    new_text = message.text.strip()[:500]

    @sync_to_async
    def _update_and_load(oid, txt):
        QuizOption.objects.filter(id=oid).update(text=txt)
        opt = QuizOption.objects.select_related("question__quiz").get(id=oid)
        q = opt.question
        return q, list(q.options.all().order_by("order"))

    q, opts = await _update_and_load(opt_id, new_text)
    await state.finish()
    await message.answer(
        "✅ Variant yangilandi.\n\n" + _question_view_body(q, opts),
        parse_mode="HTML",
        reply_markup=_question_view_markup(q, opts),
    )


# ─── Vizov scheduling ─────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "qzviz:now", state=QuizBattleState.start_time)
async def vizov_now(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    await state.finish()
    await _launch_vizov(call.message, data["vizov_quiz_id"], None, call.from_user.id)


@dp.message_handler(state=QuizBattleState.start_time)
async def vizov_scheduled(message: types.Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    await state.finish()

    # Parse HH:MM
    try:
        h, m = map(int, text.split(":"))
        now = __import__('django.utils.timezone', fromlist=['timezone']).timezone.now()
        # Use Django timezone module properly
        from django.utils import timezone as tz
        today = tz.localtime(tz.now())
        from datetime import datetime as _dt
        start_dt = today.replace(hour=h, minute=m, second=0, microsecond=0)
        if start_dt <= today:
            # next day
            from datetime import timedelta
            start_dt += timedelta(days=1)
    except Exception:
        await message.answer("Noto'g'ri format. HH:MM ko'rinishida kiriting (masalan: 14:30).")
        await QuizBattleState.start_time.set()
        await state.update_data(**data)
        return

    await _launch_vizov(message, data["vizov_quiz_id"], start_dt, message.from_user.id)


async def _launch_vizov(msg, quiz_id: int, start_dt, creator_tg_id: int):
    from django.utils import timezone as tz

    creator = await aget_user(creator_tg_id)

    @sync_to_async
    def _create_session():
        quiz = Quiz.objects.get(id=quiz_id)
        import random, json as _j
        qs = list(quiz.questions.values_list("id", flat=True))
        if quiz.shuffle:
            random.shuffle(qs)
        session = QuizSession.objects.create(
            quiz=quiz,
            creator=creator,
            chat_id=creator.telegram_id,
            status='waiting',
            scheduled_start=start_dt,
            question_order=_j.dumps(qs),
            is_group=False,
        )
        return session, quiz

    session, quiz = await _create_session()

    time_label = (
        "hozir boshlanadi ⚡"
        if start_dt is None
        else f"boshlanadi: <b>{start_dt.strftime('%H:%M')}</b>"
    )

    join_kb = InlineKeyboardMarkup()
    join_kb.add(InlineKeyboardButton(
        text="🎮 Qatnashish",
        callback_data=f"qjoin:{session.id}",
    ))

    # Broadcast join invite to all registered users
    from tgbot.tasks import broadcast_vizov_invite
    broadcast_vizov_invite.delay(
        session_id=session.id,
        quiz_title=quiz.title,
        quiz_desc=quiz.description,
        q_count=quiz.questions.count(),
        time_secs=quiz.time_per_question,
        time_label=time_label,
    )

    await msg.answer(
        f"✅ Vizov yaratildi!\n\n"
        f"<b>{quiz.title}</b> — barcha foydalanuvchilarga taklif yuborilmoqda...\n\n"
        f"⏰ {time_label.replace('<b>', '').replace('</b>', '')}\n\n"
        f"Siz ham ishtirok etishingiz mumkin 👇",
        parse_mode="HTML",
        reply_markup=join_kb,
    )

    if start_dt is None:
        from tgbot.tasks import quiz_start_session
        quiz_start_session.apply_async((session.id,), countdown=30)
    else:
        from django.utils import timezone as tz
        delay = max(0, int((start_dt - tz.now()).total_seconds()))
        from tgbot.tasks import quiz_start_session
        quiz_start_session.apply_async((session.id,), countdown=delay)
