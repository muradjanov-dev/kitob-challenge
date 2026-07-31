"""Kitob Muqovasi — answer handling. Mirrors book_quiz.py's structure."""
import asyncio
from asgiref.sync import sync_to_async
from aiogram import types
from django.utils import timezone

from tgbot.bot.loader import dp
from tgbot.bot.utils import aget_user
from tgbot.models import BookCoverRound, BookCoverAnswer, Payment, TelegramProfile


_STATS_PROMO = (
    "\n\n💎 To'liq statistikangizni ko'rish uchun Premiumga o'ting!"
)


def _is_premium(user_id: int) -> bool:
    return Payment.objects.filter(
        user_id=user_id, status="paid", end_date__gte=timezone.localdate()
    ).exists()


def _process_answer(user_id: int, round_id: int, chosen_idx: int) -> str:
    """Validate + record one answer. Pure DB — no external HTTP calls."""
    cover_round = BookCoverRound.objects.filter(id=round_id).first()
    if not cover_round:
        return "Bu o'yin topilmadi."

    if not (0 <= chosen_idx < len(cover_round.options)):
        return "Bu variant topilmadi."

    is_correct = (chosen_idx == cover_round.correct_index)
    is_premium = _is_premium(user_id)
    promo = "" if is_premium else _STATS_PROMO

    answer, created = BookCoverAnswer.objects.get_or_create(
        cover_round=cover_round, user_id=user_id,
        defaults={"chosen_index": chosen_idx, "is_correct": is_correct},
    )
    if not created:
        verdict = "to'g'ri ✅" if answer.is_correct else "noto'g'ri ❌"
        return f"Siz allaqachon javob bergansiz (javobingiz {verdict})."

    profile = TelegramProfile.objects.get(id=user_id)
    if is_correct:
        awarded = profile.update_ball(True, cover_round.reward)
        answer.rewarded = True
        answer.save(update_fields=["rewarded"])
        prem_note = " 💎×2!" if awarded > cover_round.reward else ""
        return (f"✅ To'g'ri! «{cover_round.book.title}»\n"
                f"🪙 +{awarded} Kitobcha{prem_note}\n"
                f"💰 Balans: {int(profile.ball)}{promo}")
    else:
        awarded = profile.update_ball(True, cover_round.consolation)
        answer.rewarded = True
        answer.save(update_fields=["rewarded"])
        prem_note = " 💎×2!" if awarded > cover_round.consolation else ""
        return (f"❌ Noto'g'ri. To'g'ri javob: «{cover_round.book.title}»\n"
                f"🎁 Urinish uchun: +{awarded} Kitobcha{prem_note}\n"
                f"💰 Balans: {int(profile.ball)}{promo}")


def _refresh_boards_bg(cover_round_id: int):
    """Refresh group boards in background — does not block the answer popup."""
    try:
        from tgbot.tasks import refresh_cover_boards
        from tgbot.models import BookCoverRound as _BCR
        cr = _BCR.objects.filter(id=cover_round_id).first()
        if cr:
            refresh_cover_boards(cr)
    except Exception:
        pass


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("bc:"))
async def book_cover_answer(call: types.CallbackQuery):
    parts = (call.data or "").split(":")
    if len(parts) != 3:
        await call.answer()
        return
    try:
        round_id, chosen_idx = int(parts[1]), int(parts[2])
    except ValueError:
        await call.answer()
        return

    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval botda /start bosing.", show_alert=True)
        return

    text = await sync_to_async(_process_answer)(user.id, round_id, chosen_idx)

    # Telegram caps callback-alert text at 200 chars (see the same fix in
    # book_quiz.py, which is where this bug was first found in production --
    # a too-long answer() call raises Message_too_long and crashes the
    # handler, so the vote gets recorded but the user never sees it).
    if len(text) > 200:
        text = text[:197] + "..."

    try:
        await call.answer(text, show_alert=True)
    except Exception as e:
        print(f"book_cover_answer: call.answer failed uid={user.id} round={round_id}: {e}")
    asyncio.get_event_loop().run_in_executor(None, _refresh_boards_bg, round_id)
