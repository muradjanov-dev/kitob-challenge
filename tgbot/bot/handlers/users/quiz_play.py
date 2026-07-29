"""Quiz play: join Vizov, solo play via deep link, answer questions."""
import asyncio
import json
import os
import random

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType, InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.db.models import F

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.models import (
    Quiz, QuizQuestion, QuizOption, QuizSession, QuizParticipant, QuizUserAnswer,
)

BOT_USERNAME = os.environ.get("BOT_USERNAME", "kitob_challange_bot")


def _solo_preview_kb(quiz) -> InlineKeyboardMarkup:
    """Preview/intro keyboard shown before the solo timer kicks off.
    Includes Share-to-Group so any user (not just admins) can share."""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(text="▶️ Boshlash", callback_data=f"qsolo:{quiz.id}"))
    kb.add(InlineKeyboardButton(
        text="📤 Guruhga ulashish",
        url=f"https://t.me/{BOT_USERNAME}?startgroup=quiz_{quiz.link_code}",
    ))
    return kb


def _preview_text(quiz, q_count: int) -> str:
    shuffle_line = "🔀 Savollar va variantlar aralashtirilib beriladi." if quiz.shuffle else ""
    creator_name = getattr(quiz.creator, "full_name", None) if quiz.creator_id else None
    credit_line = (
        f"\n\n<i>✍️ Kitob Challenge kitobxoni — {creator_name} tomonidan tuzilgan</i>"
        if creator_name else ""
    )
    return (
        f"📝 <b>{quiz.title}</b>\n\n"
        f"{quiz.description or ''}\n\n"
        f"❓ {q_count} ta savol · ⏱ {quiz.time_per_question} son/savol\n"
        f"{shuffle_line}"
        f"{credit_line}"
    )

# session_id -> running countdown task
_active_timers: dict[int, asyncio.Task] = {}


# ─── helpers ──────────────────────────────────────────────────────────────────

_OPT_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H"]


def _opt_label(idx: int) -> str:
    return _OPT_LETTERS[idx] if idx < len(_OPT_LETTERS) else str(idx + 1)


def _answer_kb(session_id: int, question_id: int, options) -> InlineKeyboardMarkup:
    # One option per row, full text on the button. Long answers may get clipped
    # by Telegram on narrow screens, but having the text on the button itself
    # is what users expect — duplicating it in the question body felt redundant.
    kb = InlineKeyboardMarkup(row_width=1)
    for i, opt in enumerate(options):
        kb.add(InlineKeyboardButton(
            text=f"{_opt_label(i)}.  {opt.text}",
            callback_data=f"qans:{session_id}:{question_id}:{opt.id}",
        ))
    return kb


def _bar(elapsed: int, total: int, width: int = 12) -> str:
    """Reading-progress timer: a book 📖 glides left→right across the track as
    time elapses. The trailing '═' is the path already 'read', the leading '─'
    is what's left. The remaining seconds (and a ⚠️ near the end) are shown."""
    remaining = max(0, total - elapsed)
    frac = min(1.0, (elapsed / total) if total else 1.0)
    pos = min(width - 1, int(round(frac * (width - 1))))
    done = "═" * pos
    left = "─" * (width - 1 - pos)
    warn = " ⚠️" if remaining <= max(1, total // 5) else ""
    return f"{done}📖{left}  {remaining}s{warn}"


def _q_text(q_idx: int, total: int, text: str, timer_str: str, options=None) -> str:
    # Show option list in the body too. Telegram may clip very long inline-
    # button labels mid-word, but the body listing is never clipped — so the
    # buttons stay tappable while the body guarantees the full text is
    # always visible. This also makes the message resilient to mid-quiz
    # redeploys (timer re-renders can't strip what they pass back in).
    import html as _html
    opt_lines = ""
    if options:
        opt_lines = "\n\n" + "\n".join(
            f"<b>{_opt_label(i)}.</b>  {_html.escape(o.text)}"
            for i, o in enumerate(options)
        )
    progress = "🟢" * (q_idx + 1) + "⚪️" * (total - q_idx - 1)
    return (
        f"🎯 <b>Savol {q_idx + 1}</b> <i>/ {total}</i>   {progress}\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{text}</b>{opt_lines}\n\n"
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
    """Returns (already_answered, is_correct, correct_text, hint, participant, session).

    For group sessions, auto-creates the participant on first answer so group
    members don't have to press Join separately.

    Also returns `session` so the caller (answer_question) doesn't need its
    own separate query for it — that used to cost a full extra DB round trip
    (plus a separate thread hop) on every single answer tap.
    """
    session = QuizSession.objects.filter(id=session_id).first()
    if not session:
        return True, False, "", "", None, None

    participant = QuizParticipant.objects.filter(session_id=session_id, user_id=user_id).first()
    if not participant:
        if session.is_group and session.status == "active":
            participant = QuizParticipant.objects.create(session_id=session_id, user_id=user_id)
        else:
            return True, False, "", "", None, session

    if QuizUserAnswer.objects.filter(participant=participant, question_id=question_id).exists():
        return True, False, "", "", participant, session

    # One query for the question + its options (was 3 separate .filter().first()
    # calls: option, question, correct_opt) — find the picked/correct option
    # in Python instead of round-tripping twice more for them.
    question = QuizQuestion.objects.prefetch_related("options").filter(id=question_id).first()
    if not question:
        return True, False, "", "", participant, session

    options = list(question.options.all())
    option = next((o for o in options if o.id == option_id), None)
    if not option:
        return True, False, "", "", participant, session
    correct_opt = next((o for o in options if o.is_correct), None)
    is_correct = option.is_correct

    QuizUserAnswer.objects.create(
        participant=participant,
        question_id=question_id,
        option=option,
        is_correct=is_correct,
    )
    if is_correct:
        QuizParticipant.objects.filter(id=participant.id).update(score=F("score") + 1)

    return (
        False,
        is_correct,
        correct_opt.text if correct_opt else "",
        question.hint or "",
        participant,
        session,
    )


# ─── Countdown timer ──────────────────────────────────────────────────────────

async def _question_timer(
    chat_id: int, session_id: int, q_idx: int, msg_id: int,
    q_text: str, total: int, kb, time_limit: int, options=None,
):
    """Edits question message at 50% and 80% elapsed; auto-advances on expiry.
    `options` is threaded so countdown re-renders keep the A/B/C/D list visible."""
    try:
        half = max(1, time_limit // 2)
        eight = max(half + 1, int(time_limit * 0.8))

        await asyncio.sleep(half)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_q_text(q_idx, total, q_text, _bar(half, time_limit), options),
                parse_mode="HTML", reply_markup=kb,
            )
        except Exception:
            pass

        await asyncio.sleep(eight - half)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_q_text(q_idx, total, q_text, _bar(eight, time_limit), options),
                parse_mode="HTML", reply_markup=kb,
            )
        except Exception:
            pass

        await asyncio.sleep(time_limit - eight)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_q_text(q_idx, total, q_text, "⌛ Vaqt tugadi!", options),
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
    """Solo-only (group has its own _group_advance). Used both by the native-
    poll timeout path (_poll_advance_after_close) and, if ever needed again,
    the legacy inline-keyboard timer — hence still takes a plain chat_id/
    session_id/q_idx rather than anything poll-specific."""
    session, next_idx = await _try_advance_session(session_id, q_idx)
    if not session:
        return
    q_ids = json.loads(session.question_order)
    if next_idx >= len(q_ids):
        await _finish_session_solo(session_id, chat_id)
    else:
        await _send_question_poll(chat_id, session_id, next_idx)


def _cancel_timer(session_id: int):
    task = _active_timers.pop(session_id, None)
    if task:
        task.cancel()


# ─── Solo play (deep link: /start quiz_CODE) ──────────────────────────────────

async def start_solo_quiz(message: types.Message, quiz_code: str):
    user = await aget_user(message.from_user.id)
    if not user or not user.is_registered:
        await message.answer("Avval /start bosib ro'yxatdan o'ting.")
        return

    @sync_to_async
    def _load():
        quiz = Quiz.objects.select_related("creator").prefetch_related("questions").filter(link_code=quiz_code).first()
        if not quiz:
            return None, 0
        return quiz, quiz.questions.count()

    quiz, q_count = await _load()
    if not quiz:
        await message.answer("❌ Quiz topilmadi.")
        return

    await message.answer(
        _preview_text(quiz, q_count),
        parse_mode="HTML",
        reply_markup=_solo_preview_kb(quiz),
    )


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qprev:"), state="*")
async def quiz_preview(call: types.CallbackQuery, state: FSMContext):
    """Preview screen used by the in-bot 'Kitob Quizlar' picker. Replaces the
    old behavior of dispatching to qsolo immediately, which started the timer
    before the user could read the question."""
    await call.answer()
    quiz_id = int(call.data.split(":")[1])

    @sync_to_async
    def _load():
        q = Quiz.objects.select_related("creator").prefetch_related("questions").filter(id=quiz_id).first()
        if not q:
            return None, 0
        return q, q.questions.count()

    quiz, q_count = await _load()
    if not quiz:
        await call.message.answer("❌ Quiz topilmadi.")
        return

    await call.message.answer(
        _preview_text(quiz, q_count),
        parse_mode="HTML",
        reply_markup=_solo_preview_kb(quiz),
    )


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qsolo:"), state="*")
async def solo_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user = await aget_user(call.from_user.id)
    quiz_id = int(call.data.split(":")[1])

    @sync_to_async
    def _create():
        quiz = Quiz.objects.select_related("creator").prefetch_related("questions").filter(id=quiz_id).first()
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

    await _send_question_poll(call.message.chat.id, session.id, 0)


# ─── Vizov join ───────────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qjoin:"), state="*")
async def vizov_join(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
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

    joined_kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton(text="✅ Qo'shildim!", callback_data="noop")
    )

    if not created:
        await call.answer(f"Siz allaqachon ro'yxatdasiz! (Jami: {count} ishtirokchi)", show_alert=True)
        try:
            if not session.is_group:
                await call.message.edit_reply_markup(reply_markup=joined_kb)
        except Exception:
            pass
        return

    await call.answer(f"✅ Ro'yxatdan o'tdingiz! Jami {count} ishtirokchi.", show_alert=True)
    try:
        if not session.is_group:
            await call.message.edit_reply_markup(reply_markup=joined_kb)
    except Exception:
        pass

    # Auto-start group quizzes the moment the 2nd participant joins — the
    # creator no longer needs to tap Boshlash. Vizov DM-broadcast sessions
    # (is_group=False) keep the original 'wait for scheduled start' behavior.
    if session.is_group and count >= 2:
        @sync_to_async
        def _flip_to_active():
            return QuizSession.objects.filter(
                id=session.id, status="waiting", is_group=True,
            ).update(status="active") > 0

        if await _flip_to_active():
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            try:
                await bot.send_message(
                    chat_id=session.chat_id,
                    text="🚀 <b>2 ishtirokchi qo'shildi — quiz boshlanmoqda!</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            await _send_group_question(session.chat_id, session.id, 0)


# ─── Answer a question ─────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qans:"), state="*")
async def answer_question(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing.", show_alert=True)
        return

    parts = call.data.split(":")
    # Guard against stale/malformed answer buttons (old quiz messages, etc.)
    if len(parts) < 4:
        await call.answer()
        return
    try:
        session_id, question_id, option_id = int(parts[1]), int(parts[2]), int(parts[3])
    except (ValueError, IndexError):
        await call.answer()
        return

    already, is_correct, correct_text, hint, participant, session = await _record_answer(
        session_id, user.id, question_id, option_id
    )
    is_group = bool(session and session.is_group)

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

    # For solo sessions: cancel timer and auto-advance immediately.
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


# ─── Send a question — native Poll (solo) ──────────────────────────────────────
#
# Phase 1 of the native-poll migration (see NATIVE_POLL_MIGRATION_PROMPT.md):
# SOLO play only, since it's the lowest-risk surface (single user, DM chat).
# Group play still uses the inline-keyboard flow below (_send_group_question /
# _group_question_timer / answer_question), completely untouched — kept as
# the safe, proven path until the poll approach has been verified in
# production. The old DM inline-keyboard path (_send_question,
# _question_timer) is also left in place, unused, as an instant rollback:
# just point solo_start/_advance_after_timeout back at _send_question if the
# poll flow needs to be reverted.
#
# Telegram draws its own countdown ring for `open_period` and reveals
# correct/incorrect to the voter natively (quiz-type poll) — no server-side
# message edits or callback-answer toasts needed, unlike the legacy flow.

POLL_CACHE_PREFIX = "quizpoll:"
POLL_REVEAL_PAUSE = 2.5  # let Telegram's native reveal animation play before the next question


async def _send_question_poll(chat_id: int, session_id: int, q_idx: int):
    @sync_to_async
    def _load():
        session = QuizSession.objects.select_related("quiz").filter(id=session_id).first()
        if not session:
            return None, None, None, 0, 0
        q_ids = json.loads(session.question_order)
        if q_idx >= len(q_ids):
            return None, None, None, len(q_ids), 0
        question = QuizQuestion.objects.prefetch_related("options").filter(id=q_ids[q_idx]).first()
        if not question:
            # Question was deleted after the session started.
            return None, None, None, len(q_ids), 0
        opts = list(question.options.all())
        if session.quiz.shuffle:
            random.shuffle(opts)
        return session, question, opts, len(q_ids), session.quiz.time_per_question

    session, question, opts, total, time_limit = await _load()
    if not session or not question:
        return

    correct_idx = next((i for i, o in enumerate(opts) if o.is_correct), 0)
    # sendPoll's `question` is plain text only (no HTML/entities) — keep the
    # progress indicator as plain characters, and hard-clip to Telegram's
    # 300-char question limit / 100-char option limit as a defensive backstop
    # (quiz_ai.py already enforces this at generation time).
    poll_question = f"❓ {q_idx + 1}/{total}  {question.text}"[:300]

    poll_msg = await bot.send_poll(
        chat_id=chat_id,
        question=poll_question,
        options=[o.text[:100] for o in opts],
        type="quiz",
        correct_option_id=correct_idx,
        is_anonymous=False,  # required — anonymous polls never fire poll_answer
        explanation=(question.hint[:200] if question.hint else None),
        open_period=max(5, min(600, time_limit)),
    )

    cache.set(
        f"{POLL_CACHE_PREFIX}{poll_msg.poll.id}",
        {
            "session_id": session_id,
            "question_id": question.id,
            "option_ids": [o.id for o in opts],
            "chat_id": chat_id,
            "q_idx": q_idx,
        },
        timeout=time_limit + 90,
    )

    _cancel_timer(session_id)
    task = asyncio.create_task(_poll_advance_after_close(chat_id, session_id, q_idx, time_limit))
    _active_timers[session_id] = task


async def _poll_advance_after_close(chat_id: int, session_id: int, q_idx: int, time_limit: int):
    """Telegram closes the poll itself once `open_period` elapses — this just
    waits a beat past that (so the native reveal has shown) then advances,
    mirroring the old timer's role without needing any message edits."""
    try:
        await asyncio.sleep(time_limit + 1)
        await _advance_after_timeout(chat_id, session_id, q_idx)
    except asyncio.CancelledError:
        pass
    finally:
        _active_timers.pop(session_id, None)


@dp.poll_answer_handler()
async def on_poll_answer(poll_answer: types.PollAnswer):
    mapping = cache.get(f"{POLL_CACHE_PREFIX}{poll_answer.poll_id}")
    if not mapping:
        return  # not one of ours, or the mapping expired
    if not poll_answer.option_ids:
        return  # user retracted their vote

    session_id = mapping["session_id"]
    question_id = mapping["question_id"]
    option_ids = mapping["option_ids"]
    chat_id = mapping["chat_id"]
    q_idx = mapping["q_idx"]

    chosen_idx = poll_answer.option_ids[0]
    if chosen_idx >= len(option_ids):
        return
    option_id = option_ids[chosen_idx]

    user = await aget_user(poll_answer.user.id)
    if not user:
        return

    already, is_correct, correct_text, hint, participant, session = await _record_answer(
        session_id, user.id, question_id, option_id
    )
    if already or not session or session.is_group:
        return  # group polls aren't wired up yet — this handler is solo-only for now

    _cancel_timer(session_id)
    await asyncio.sleep(POLL_REVEAL_PAUSE)

    q_ids = json.loads(session.question_order)
    next_idx = q_idx + 1
    if next_idx >= len(q_ids):
        await _finish_session_solo(session_id, user.telegram_id)
    else:
        await sync_to_async(QuizSession.objects.filter(id=session_id).update)(
            current_question_idx=next_idx
        )
        await _send_question_poll(chat_id, session_id, next_idx)


# ─── Send a question (DM, legacy inline-keyboard — group flow's helpers still
# reference _answer_kb, so this file stays; see notes above) ───────────────────

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
        if not question:
            # Question was deleted after the session started.
            return None, None, None, len(q_ids), 0
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
        text=_q_text(q_idx, total, question.text, initial_bar, opts),
        parse_mode="HTML",
        reply_markup=kb,
    )

    # Cancel any previous timer then start a fresh one
    _cancel_timer(session_id)
    task = asyncio.create_task(
        _question_timer(chat_id, session_id, q_idx, msg.message_id, question.text, total, kb, time_limit, opts)
    )
    _active_timers[session_id] = task


def _progress_bar(pct: int, slots: int = 10) -> str:
    filled = round(pct / 100 * slots)
    return "▰" * filled + "▱" * (slots - filled)


async def _finish_session_solo(session_id: int, chat_id: int):
    _cancel_timer(session_id)

    @sync_to_async
    def _results():
        session = QuizSession.objects.select_related("quiz").filter(id=session_id).first()
        if not session:
            return None, 0, 0, 0
        QuizSession.objects.filter(id=session_id).update(status="finished")
        participant = QuizParticipant.objects.filter(
            session_id=session_id, user__telegram_id=chat_id
        ).first()
        total = len(json.loads(session.question_order))
        score = participant.score if participant else 0
        # Every solo play of this same Quiz (via its link_code) creates its
        # own QuizSession — count distinct participants across ALL of them
        # so "necha odam qatnashgan" reflects the quiz's real reach, not just
        # this one session.
        player_count = QuizParticipant.objects.filter(session__quiz_id=session.quiz_id).count()
        return session, score, total, player_count

    session, score, total, player_count = await _results()
    if not session:
        return

    pct = int(score * 100 / total) if total else 0
    if pct == 100:
        emoji, headline, blurb = "🏆", "Mukammal!", "Bironta xatosiz — bu daraja juda kam kitobxonga nasib qiladi!"
    elif pct >= 70:
        emoji, headline, blurb = "🥇", "Zo'r natija!", "Bilimingiz tagiga yetadi. Yana bir-ikki o'qish — va siz ekspertsiz."
    elif pct >= 40:
        emoji, headline, blurb = "👍", "Yomon emas!", "Asoslar bor — endi kitobga qaytib, qiziqarli joylarini sekinroq o'qing."
    else:
        emoji, headline, blurb = "📚", "Hali oldindasiz!", "Bu — boshlanish. Kitobni qo'lga olib, mazasini totib chiqsangiz, keyingi safar yorishasiz."

    bot_link = f"https://t.me/{BOT_USERNAME}"
    bar = _progress_bar(pct)
    players_line = (
        f"👥 Bu quizni jami <b>{player_count}</b> kishi yechgan\n\n" if player_count > 1 else "\n"
    )
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"{emoji} <b>{headline}</b>\n"
            f"<i>{session.quiz.title}</i>\n\n"
            f"<code>{bar}</code>  <b>{pct}%</b>\n"
            f"✅ To'g'ri javoblar: <b>{score}/{total}</b>\n\n"
            f"<i>{blurb}</i>\n\n"
            f"{players_line}"
            f"<blockquote>🚀 Yana quiz ishlang yoki o'zingiz tuzing:\n"
            f"👉 <a href=\"{bot_link}\">Kitob Challenge bot</a>\n\n"
            f"💎 <b>Premium</b> — AI yordamida quiz tuzish, kengaytirilgan "
            f"statistikalar va boshqa imkoniyatlar</blockquote>"
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ─── Group play (deep link from group: /start quiz_CODE) ──────────────────────
#
# Flow:
#   1. User taps "📤 Guruhga ulashish" → Telegram add-to-group picker →
#      bot lands in the chosen group and receives /start quiz_<code>.
#   2. We create a QuizSession(is_group=True, status="waiting") and post a
#      Join + Boshlash message.
#   3. Creator taps Boshlash → status flips to "active"; questions are sent to
#      the group chat one by one with an asyncio timer.
#   4. Each answer is recorded in QuizUserAnswer (auto-join on first tap).
#      Per-user feedback is a short toast — the correct answer is revealed
#      only when the timer expires so wrong answerers can't leak it.
#   5. After last question, post a leaderboard in the group.


async def start_group_quiz(message: types.Message, quiz_code: str):
    """Spawn a waiting QuizSession in the current group chat."""
    user = await aget_user(message.from_user.id)
    if not user:
        await message.answer("Avval bot bilan shaxsiy /start qilib ro'yxatdan o'ting.")
        return

    @sync_to_async
    def _spawn():
        quiz = Quiz.objects.select_related("creator").prefetch_related("questions").filter(link_code=quiz_code).first()
        if not quiz:
            return None, None, 0
        q_ids = list(quiz.questions.values_list("id", flat=True))
        if not q_ids:
            return quiz, None, 0
        if quiz.shuffle:
            random.shuffle(q_ids)
        session = QuizSession.objects.create(
            quiz=quiz,
            creator=user,
            chat_id=message.chat.id,
            status="waiting",
            question_order=json.dumps(q_ids),
            is_group=True,
        )
        return quiz, session, len(q_ids)

    quiz, session, q_count = await _spawn()
    if not quiz:
        await message.answer("❌ Quiz topilmadi.")
        return
    if not session:
        await message.answer("❌ Bu quizda savollar yo'q.")
        return

    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(InlineKeyboardButton(text="✋ Qo'shilaman", callback_data=f"qjoin:{session.id}"))
    kb.row(InlineKeyboardButton(text="▶️ Boshlash", callback_data=f"qstart:{session.id}"))

    creator_name = getattr(quiz.creator, "full_name", None) if quiz.creator_id else None
    credit_line = f"<i>✍️ Kitob Challenge kitobxoni — {creator_name} tomonidan tuzilgan</i>\n\n" if creator_name else ""

    sent = await message.answer(
        f"🎮 <b>GURUH QUIZI</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"📖 <b>{quiz.title}</b>\n"
        f"{quiz.description + chr(10) + chr(10) if quiz.description else ''}"
        f"❓ {q_count} ta savol  ·  ⏱ {quiz.time_per_question} son/savol\n\n"
        f"{credit_line}"
        f"<blockquote>✋ Qatnashish uchun <b>Qo'shilaman</b>ni bosing.\n"
        f"Yaratuvchi tayyor bo'lganda <b>▶️ Boshlash</b>ni bossin.\n\n"
        f"O'yin davomida ham istalgan vaqtda qo'shilishingiz mumkin — "
        f"birinchi javob tugmasini bosish kifoya.</blockquote>",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await sync_to_async(QuizSession.objects.filter(id=session.id).update)(
        join_message_id=sent.message_id,
    )


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("qstart:"), state="*")
async def group_start(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval bot bilan /start qiling.", show_alert=True)
        return

    session_id = int(call.data.split(":")[1])

    @sync_to_async
    def _begin():
        session = QuizSession.objects.filter(id=session_id).first()
        if not session:
            return None, "missing", 0
        if not session.is_group:
            return session, "not_group", 0
        if session.creator_id != user.id and not getattr(user, "is_admin", False):
            return session, "forbidden", 0
        if session.status != "waiting":
            return session, "already", 0
        join_count = QuizParticipant.objects.filter(session_id=session_id).count()
        if join_count < 2:
            return session, "too_few", join_count
        QuizSession.objects.filter(id=session_id).update(status="active")
        return session, "ok", join_count

    session, status, join_count = await _begin()
    if status == "missing":
        await call.answer("Sessiya topilmadi.", show_alert=True)
        return
    if status == "not_group":
        await call.answer("Bu solo sessiya.", show_alert=True)
        return
    if status == "forbidden":
        await call.answer("Faqat quiz yaratuvchisi boshlay oladi.", show_alert=True)
        return
    if status == "already":
        await call.answer("Boshlangan yoki tugagan.", show_alert=True)
        return
    if status == "too_few":
        await call.answer(
            f"Quizni boshlash uchun kamida 2 ta ishtirokchi kerak.\n"
            f"Hozircha: {join_count} ta. "
            f"Yana {2 - join_count} kishi <b>✋ Qo'shilaman</b> bossin.",
            show_alert=True,
        )
        return

    await call.answer("Boshlandi! 🎮")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _send_group_question(session.chat_id, session_id, 0)


async def _send_group_question(chat_id: int, session_id: int, q_idx: int):
    """Post question q_idx to the group chat and kick off the timer."""
    @sync_to_async
    def _load():
        session = QuizSession.objects.select_related("quiz").filter(id=session_id).first()
        if not session:
            return None, None, None, 0, 0
        q_ids = json.loads(session.question_order)
        if q_idx >= len(q_ids):
            return session, None, None, len(q_ids), 0
        question = QuizQuestion.objects.prefetch_related("options").filter(id=q_ids[q_idx]).first()
        if not question:
            # Question was deleted after the session started.
            return None, None, None, len(q_ids), 0
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
        text=_q_text(q_idx, total, question.text, initial_bar, opts),
        parse_mode="HTML",
        reply_markup=kb,
    )
    await sync_to_async(QuizSession.objects.filter(id=session_id).update)(
        current_question_idx=q_idx,
    )

    _cancel_timer(session_id)
    task = asyncio.create_task(
        _group_question_timer(chat_id, session_id, q_idx, msg.message_id,
                              question.text, question.id, total, kb, time_limit, opts)
    )
    _active_timers[session_id] = task


async def _group_question_timer(
    chat_id: int, session_id: int, q_idx: int, msg_id: int,
    q_text: str, question_id: int, total: int, kb, time_limit: int, options=None,
):
    """Edits at 50% and 80%; on expiry reveals correct answer and advances."""
    try:
        half = max(1, time_limit // 2)
        eight = max(half + 1, int(time_limit * 0.8))

        await asyncio.sleep(half)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_q_text(q_idx, total, q_text, _bar(half, time_limit), options),
                parse_mode="HTML", reply_markup=kb,
            )
        except Exception:
            pass

        await asyncio.sleep(eight - half)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_q_text(q_idx, total, q_text, _bar(eight, time_limit), options),
                parse_mode="HTML", reply_markup=kb,
            )
        except Exception:
            pass

        await asyncio.sleep(time_limit - eight)

        # Reveal correct answer + per-question scoreboard.
        @sync_to_async
        def _reveal():
            correct = QuizOption.objects.filter(question_id=question_id, is_correct=True).first()
            question = QuizQuestion.objects.filter(id=question_id).first()
            participants = list(
                QuizParticipant.objects.filter(session_id=session_id)
                .select_related("user")
            )
            answered_correct = set(
                QuizUserAnswer.objects.filter(
                    participant__session_id=session_id,
                    question_id=question_id,
                    is_correct=True,
                ).values_list("participant__user__full_name", flat=True)
            )
            return correct, question, participants, answered_correct

        correct, question, participants, answered_correct = await _reveal()
        correct_text = correct.text if correct else "—"
        hint_text = (question.hint if question and question.hint else "")
        winners_line = (
            ", ".join(sorted(answered_correct)) if answered_correct else "hech kim"
        )
        reveal_text = (
            f"⏰ <b>Vaqt tugadi!</b>   <i>Savol {q_idx + 1}/{total}</i>\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"<b>{q_text}</b>\n\n"
            f"🎉 To'g'ri javob:  <b>{correct_text}</b>\n"
            f"🏅 Bilganlar:  {winners_line}"
        )
        if hint_text:
            reveal_text += f"\n\n💡 <i>{hint_text}</i>"
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=reveal_text, parse_mode="HTML", reply_markup=None,
            )
        except Exception:
            pass

        # Brief pause before next question so the reveal is readable.
        await asyncio.sleep(2)
        await _group_advance(chat_id, session_id, q_idx)

    except asyncio.CancelledError:
        pass
    finally:
        _active_timers.pop(session_id, None)


async def _group_advance(chat_id: int, session_id: int, q_idx: int):
    @sync_to_async
    def _next():
        session = QuizSession.objects.filter(id=session_id).first()
        if not session or session.status != "active":
            return None, 0
        if session.current_question_idx != q_idx:
            return None, 0
        q_ids = json.loads(session.question_order)
        next_idx = q_idx + 1
        return session, next_idx if next_idx < len(q_ids) else -1

    session, next_idx = await _next()
    if not session:
        return
    if next_idx == -1:
        await _finish_group_session(session_id, chat_id)
    else:
        await _send_group_question(chat_id, session_id, next_idx)


async def _finish_group_session(session_id: int, chat_id: int):
    _cancel_timer(session_id)

    @sync_to_async
    def _results():
        session = QuizSession.objects.select_related("quiz").filter(id=session_id).first()
        if not session:
            return None, [], 0
        QuizSession.objects.filter(id=session_id).update(status="finished")
        participants = list(
            QuizParticipant.objects.filter(session_id=session_id)
            .select_related("user")
            .order_by("-score", "joined_at")
        )
        total = len(json.loads(session.question_order))
        return session, participants, total

    session, participants, total = await _results()
    if not session:
        return

    if not participants:
        bot_link = f"https://t.me/{BOT_USERNAME}"
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🏁 <b>{session.quiz.title}</b> tugadi — hech kim qatnashmadi.\n\n"
                f"📚 Quiz ishlash juda foydali — keyingisiga qo'shiling!\n"
                f"👉 <a href=\"{bot_link}\">Kitob Challenge bot</a>"
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    winner_name = participants[0].user.full_name or "Kitobxon"
    lines = [
        "🎊 <b>Quiz yakunlandi!</b>",
        f"<i>{session.quiz.title}</i>",
        "",
        f"🏆 G'olib: <b>{winner_name}</b>",
        "",
    ]
    for i, p in enumerate(participants, 1):
        marker = medals.get(i, f"<code>{i:>2}.</code>")
        pct = int((p.score or 0) * 100 / total) if total else 0
        name = p.user.full_name or "Kitobxon"
        lines.append(f"{marker} <b>{name}</b> — {p.score}/{total} ({pct}%)")
    lines.append("")
    lines.append(f"👥 Jami ishtirokchilar: <b>{len(participants)}</b>")
    lines.append("")
    bot_link = f"https://t.me/{BOT_USERNAME}"
    lines.append(
        f"<blockquote>🚀 Yana quiz ishlang yoki o'zingiz tuzing:\n"
        f"👉 <a href=\"{bot_link}\">Kitob Challenge bot</a>\n\n"
        f"💎 <b>Premium</b> — AI yordamida quiz tuzish, kengaytirilgan "
        f"statistikalar va boshqa imkoniyatlar</blockquote>"
    )

    await bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ─── /stop — creator or admin only ─────────────────────────────────────────────

@dp.message_handler(ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)), commands=["stop"], state="*")
async def stop_group_quiz(message: types.Message, state: FSMContext = None):
    """Ends the group's current waiting/active quiz session early. Restricted
    to the session's creator or a bot admin — same permission check as
    group_start's 'Boshlash' button — so random group members can't cut off
    someone else's quiz."""
    user = await aget_user(message.from_user.id)
    if not user:
        return

    @sync_to_async
    def _find_and_stop():
        session = (
            QuizSession.objects.select_related("quiz")
            .filter(chat_id=message.chat.id, is_group=True)
            .exclude(status="finished")
            .order_by("-created_at")
            .first()
        )
        if not session:
            return None, None, [], 0
        if session.creator_id != user.id and not getattr(user, "is_admin", False):
            return session, "forbidden", [], 0

        was_active = session.status == "active"
        participants = list(
            QuizParticipant.objects.filter(session_id=session.id)
            .select_related("user").order_by("-score", "joined_at")
        ) if was_active else []
        total = len(json.loads(session.question_order))
        QuizSession.objects.filter(id=session.id).update(status="finished")
        return session, "stopped", participants, total

    session, outcome, participants, total = await _find_and_stop()
    if session is None:
        await message.answer("🔍 Bu guruhda faol quiz topilmadi.")
        return
    if outcome == "forbidden":
        await message.answer("⛔ Faqat quizni boshlagan odam yoki admin uni to'xtata oladi.")
        return

    _cancel_timer(session.id)

    if not participants:
        await message.answer(f"🛑 <b>{session.quiz.title}</b> to'xtatildi.", parse_mode="HTML")
        return

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"🛑 <b>{session.quiz.title}</b> to'xtatildi.", "", "📊 Shu paytgacha natijalar:", ""]
    for i, p in enumerate(participants, 1):
        marker = medals.get(i, f"<code>{i:>2}.</code>")
        name = p.user.full_name or "Kitobxon"
        lines.append(f"{marker} <b>{name}</b> — {p.score}/{total}")
    await message.answer("\n".join(lines), parse_mode="HTML")
