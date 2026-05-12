"""Quiz play: join Vizov, solo play via deep link, answer questions."""
import asyncio
import json
import random

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import get_user
from tgbot.models import (
    Quiz, QuizQuestion, QuizOption, QuizSession, QuizParticipant, QuizUserAnswer,
)

# session_id -> running countdown task
_active_timers: dict[int, asyncio.Task] = {}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _answer_kb(session_id: int, question_id: int, options) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    for opt in options:
        kb.add(InlineKeyboardButton(
            text=opt.text,
            callback_data=f"qans:{session_id}:{question_id}:{opt.id}",
        ))
    return kb


def _bar(elapsed: int, total: int, width: int = 10) -> str:
    remaining = max(0, total - elapsed)
    filled = round(remaining / total * width) if total else 0
    warn = " ⚠️" if remaining <= max(1, total // 5) else ""
    return f"{'▓' * filled}{'░' * (width - filled)} {remaining}s{warn}"


def _q_text(q_idx: int, total: int, text: str, timer_str: str) -> str:
    return (
        f"❓ <b>Savol {q_idx + 1}/{total}</b>\n\n"
        f"{text}\n\n"
        f"⏱ {timer_str}"
    )


@sync_to_async
def _get_session_data(session_id: int):
    session = QuizSession.objects.select_related("quiz").filter(id=session_id).first()
    if not session:
        return None, None, None
    q_ids = json.loads(session.question_order)
    idx = session.current_question_idx
    if idx >= len(q_ids):
        return session, None, None
    question = QuizQuestion.objects.prefetch_related("options").filter(id=q_ids[idx]).first()
    return session, question, q_ids


@sync_to_async
def _record_answer(session_id: int, user_id: int, question_id: int, option_id: int):
    """Returns (already_answered, is_correct, correct_text, hint, participant)."""
    session = QuizSession.objects.filter(id=session_id).first()
    if not session:
        return True, False, "", "", None

    participant = QuizParticipant.objects.filter(session_id=session_id, user_id=user_id).first()
    if not participant:
        return True, False, "", "", None

    if QuizUserAnswer.objects.filter(participant=participant, question_id=question_id).exists():
        return True, False, "", "", participant

    option = QuizOption.objects.filter(id=option_id).first()
    if not option:
        return True, False, "", "", participant

    question = QuizQuestion.objects.filter(id=question_id).first()
    correct_opt = QuizOption.objects.filter(question_id=question_id, is_correct=True).first()
    is_correct = option.is_correct

    QuizUserAnswer.objects.create(
        participant=participant,
        question_id=question_id,
        option=option,
        is_correct=is_correct,
    )
    if is_correct:
        QuizParticipant.objects.filter(id=participant.id).update(score=participant.score + 1)

    return (
        False,
        is_correct,
        correct_opt.text if correct_opt else "",
        question.hint if question else "",
        participant,
    )


# ─── Countdown timer ──────────────────────────────────────────────────────────

async def _question_timer(
    chat_id: int, session_id: int, q_idx: int, msg_id: int,
    q_text: str, total: int, kb, time_limit: int,
):
    """Edits question message at 50% and 80% elapsed; auto-advances on expiry."""
    try:
        half = max(1, time_limit // 2)
        eight = max(half + 1, int(time_limit * 0.8))

        await asyncio.sleep(half)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_q_text(q_idx, total, q_text, _bar(half, time_limit)),
                parse_mode="HTML", reply_markup=kb,
            )
        except Exception:
            pass

        await asyncio.sleep(eight - half)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_q_text(q_idx, total, q_text, _bar(eight, time_limit)),
                parse_mode="HTML", reply_markup=kb,
            )
        except Exception:
            pass

        await asyncio.sleep(time_limit - eight)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_q_text(q_idx, total, q_text, "⌛ Vaqt tugadi!"),
                parse_mode="HTML", reply_markup=None,
            )
        except Exception:
            pass

        await _advance_after_timeout(chat_id, session_id, q_idx)

    except asyncio.CancelledError:
        pass
    finally:
        _active_timers.pop(session_id, None)


@sync_to_async
def _try_advance_session(session_id: int, q_idx: int):
    """Atomically advances if still on q_idx; returns (session, next_idx) or (None, 0)."""
    session = QuizSession.objects.filter(id=session_id).first()
    if not session or session.current_question_idx != q_idx:
        return None, 0
    next_idx = q_idx + 1
    QuizSession.objects.filter(id=session_id).update(current_question_idx=next_idx)
    return session, next_idx


async def _advance_after_timeout(chat_id: int, session_id: int, q_idx: int):
    session, next_idx = await _try_advance_session(session_id, q_idx)
    if not session:
        return
    q_ids = json.loads(session.question_order)
    if next_idx >= len(q_ids):
        await _finish_session_solo(session_id, chat_id)
    else:
        await _send_question(chat_id, session_id, next_idx)


def _cancel_timer(session_id: int):
    task = _active_timers.pop(session_id, None)
    if task:
        task.cancel()


# ─── Solo play (deep link: /start quiz_CODE) ──────────────────────────────────

async def start_solo_quiz(message: types.Message, quiz_code: str):
    user = get_user(message.from_user.id)
    if not user or not user.is_registered:
        await message.answer("Avval /start bosib ro'yxatdan o'ting.")
        return

    @sync_to_async
    def _load():
        quiz = Quiz.objects.prefetch_related("questions").filter(link_code=quiz_code).first()
        if not quiz:
            return None, 0
        return quiz, quiz.questions.count()

    quiz, q_count = await _load()
    if not quiz:
        await message.answer("❌ Quiz topilmadi.")
        return

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text="▶️ Boshlash", callback_data=f"qsolo:{quiz.id}"))
    await message.answer(
        f"📝 <b>{quiz.title}</b>\n\n"
        f"{quiz.description or ''}\n\n"
        f"❓ {q_count} ta savol · ⏱ {quiz.time_per_question} son/savol\n"
        f"{'🔀 Savollar va variantlar aralashtirilib beriladi.' if quiz.shuffle else ''}",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qsolo:"), state="*")
async def solo_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user = get_user(call.from_user.id)
    quiz_id = int(call.data.split(":")[1])

    @sync_to_async
    def _create():
        quiz = Quiz.objects.prefetch_related("questions").filter(id=quiz_id).first()
        if not quiz:
            return None, None
        q_ids = list(quiz.questions.values_list("id", flat=True))
        if quiz.shuffle:
            random.shuffle(q_ids)
        session = QuizSession.objects.create(
            quiz=quiz,
            creator=user,
            chat_id=user.telegram_id,
            status="active",
            question_order=json.dumps(q_ids),
            is_group=False,
        )
        participant = QuizParticipant.objects.create(session=session, user=user)
        return session, participant

    session, participant = await _create()
    if not session:
        await call.message.answer("❌ Quiz topilmadi.")
        return

    await _send_question(call.message.chat.id, session.id, 0)


# ─── Vizov join ───────────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qjoin:"), state="*")
async def vizov_join(call: types.CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    if not user or not user.is_registered:
        await call.answer("Avval /start bosib ro'yxatdan o'ting.", show_alert=True)
        return

    session_id = int(call.data.split(":")[1])

    @sync_to_async
    def _join():
        session = QuizSession.objects.filter(id=session_id).first()
        if not session or session.status != "waiting":
            return None, False
        _, created = QuizParticipant.objects.get_or_create(
            session=session, user_id=user.id
        )
        count = session.participants.count()
        return session, created, count

    result = await _join()
    if result[0] is None:
        await call.answer("Bu Vizov allaqachon boshlangan yoki tugagan.", show_alert=True)
        return
    session, created, count = result

    if not created:
        await call.answer(f"Siz allaqachon ro'yxatdasiz! (Jami: {count} ishtirokchi)", show_alert=True)
        return

    await call.answer(f"✅ Ro'yxatdan o'tdingiz! Jami {count} ishtirokchi.", show_alert=True)


# ─── Answer a question ─────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qans:"), state="*")
async def answer_question(call: types.CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing.", show_alert=True)
        return

    parts = call.data.split(":")
    session_id, question_id, option_id = int(parts[1]), int(parts[2]), int(parts[3])

    already, is_correct, correct_text, hint, participant = await _record_answer(
        session_id, user.id, question_id, option_id
    )

    if already:
        await call.answer("Siz allaqachon javob berdingiz!", show_alert=True)
        return

    if is_correct:
        await call.answer("✅ To'g'ri!", show_alert=True)
    else:
        msg = f"❌ Noto'g'ri!\n✅ To'g'ri javob: {correct_text}"
        if hint:
            msg += f"\n\n💡 {hint}"
        await call.answer(msg, show_alert=True)

    # For solo sessions: cancel timer and auto-advance
    session = await sync_to_async(QuizSession.objects.filter(id=session_id).first)()
    if session and not session.is_group:
        _cancel_timer(session_id)

        q_ids = json.loads(session.question_order)
        next_idx = session.current_question_idx + 1

        if next_idx >= len(q_ids):
            await _finish_session_solo(session_id, user.telegram_id)
        else:
            await sync_to_async(QuizSession.objects.filter(id=session_id).update)(
                current_question_idx=next_idx
            )
            await _send_question(user.telegram_id, session_id, next_idx)


# ─── Send a question (DM) ──────────────────────────────────────────────────────

async def _send_question(chat_id: int, session_id: int, q_idx: int):
    @sync_to_async
    def _load():
        session = QuizSession.objects.select_related("quiz").filter(id=session_id).first()
        if not session:
            return None, None, None, 0, 0
        q_ids = json.loads(session.question_order)
        if q_idx >= len(q_ids):
            return None, None, None, len(q_ids), 0
        question = QuizQuestion.objects.prefetch_related("options").filter(id=q_ids[q_idx]).first()
        opts = list(question.options.all())
        if session.quiz.shuffle:
            random.shuffle(opts)
        return session, question, opts, len(q_ids), session.quiz.time_per_question

    session, question, opts, total, time_limit = await _load()
    if not session or not question:
        return

    kb = _answer_kb(session_id, question.id, opts)
    initial_bar = _bar(0, time_limit)
    msg = await bot.send_message(
        chat_id=chat_id,
        text=_q_text(q_idx, total, question.text, initial_bar),
        parse_mode="HTML",
        reply_markup=kb,
    )

    # Cancel any previous timer then start a fresh one
    _cancel_timer(session_id)
    task = asyncio.create_task(
        _question_timer(chat_id, session_id, q_idx, msg.message_id, question.text, total, kb, time_limit)
    )
    _active_timers[session_id] = task


async def _finish_session_solo(session_id: int, chat_id: int):
    _cancel_timer(session_id)

    @sync_to_async
    def _results():
        session = QuizSession.objects.filter(id=session_id).first()
        if not session:
            return None, 0, 0
        QuizSession.objects.filter(id=session_id).update(status="finished")
        participant = QuizParticipant.objects.filter(
            session_id=session_id, user__telegram_id=chat_id
        ).first()
        total = len(json.loads(session.question_order))
        score = participant.score if participant else 0
        return session, score, total

    session, score, total = await _results()
    if not session:
        return

    pct = int(score * 100 / total) if total else 0
    if pct == 100:
        emoji = "🏆"
    elif pct >= 70:
        emoji = "🥇"
    elif pct >= 40:
        emoji = "👍"
    else:
        emoji = "📚"

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"{emoji} <b>Natija</b>\n\n"
            f"📝 {session.quiz.title}\n\n"
            f"✅ To'g'ri: <b>{score}/{total}</b> ({pct}%)\n\n"
            + ("Ajoyib natija! 🎉" if pct == 100 else
               "Yaxshi ishlading! Ko'proq o'qi. 💪" if pct >= 70 else
               "Kitobni qayta o'qib chiq! 📖")
        ),
        parse_mode="HTML",
    )
