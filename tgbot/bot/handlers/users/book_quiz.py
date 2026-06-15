"""Kitob Viktorina — answer handling.

The quiz message (one quote, four book buttons) is posted to the groups and
DM'd to Premium users by the `post_book_quiz` Celery task. This module handles
the button taps: it gates answering to Premium group-members, locks one answer
per user per round, and pays out the Kitobcha reward for a correct first guess.
"""
from asgiref.sync import sync_to_async
from aiogram import types
from django.utils import timezone

from tgbot.bot.loader import dp
from tgbot.bot.utils import aget_user
from tgbot.models import BookQuizRound, BookQuizAnswer, Payment, TelegramProfile


# Shown after every answer to non-Premium users — earning is free, but seeing
# the full Viktorina statistics is a Premium perk.
_STATS_PROMO = (
    "\n\n💎 To'liq viktorina statistikangizni ko'rish uchun Premiumga o'ting!"
)


def _is_premium(user_id: int) -> bool:
    return Payment.objects.filter(
        user_id=user_id, status="paid", end_date__gte=timezone.localdate()
    ).exists()


def _is_group_member(telegram_id: int) -> bool:
    """True if the user belongs to at least one configured reading group."""
    from tgbot.tasks import _group_chat_ids, _is_user_in_chat
    for chat_id in _group_chat_ids():
        if _is_user_in_chat(chat_id, telegram_id):
            return True
    return False


def _process_answer(user_id: int, telegram_id: int, round_id: int, chosen_idx: int) -> str:
    """Validate + record one answer, returning the alert text to show the user.
    Runs fully in a sync context (DB + membership network call)."""
    quiz_round = BookQuizRound.objects.filter(id=round_id).first()
    if not quiz_round:
        return "Bu viktorina topilmadi."
    if not quiz_round.is_active:
        return "⏳ Bu viktorina yopilgan. Keyingisini kuting!"

    # Answering is free for any group member — only the stats are Premium.
    if not _is_group_member(telegram_id):
        return ("📚 Javob berish uchun avval kitobxonlar guruhiga a'zo bo'ling, "
                "so'ng qaytadan urinib ko'ring.")

    if not (0 <= chosen_idx < len(quiz_round.options)):
        return "Bu variant topilmadi."

    is_correct = (chosen_idx == quiz_round.correct_index)
    is_premium = _is_premium(user_id)
    promo = "" if is_premium else _STATS_PROMO

    answer, created = BookQuizAnswer.objects.get_or_create(
        quiz_round=quiz_round, user_id=user_id,
        defaults={"chosen_index": chosen_idx, "is_correct": is_correct},
    )
    if not created:
        verdict = "to'g'ri ✅" if answer.is_correct else "noto'g'ri ❌"
        return f"Siz allaqachon javob bergansiz (javobingiz {verdict}).{promo}"

    # First answer locked in. Author of the quote can't farm their own report.
    if quiz_round.source_user_id == user_id:
        return ("🙂 Bu o'zingiz yuborgan xulosa — mukofot yo'q, lekin "
                f"ishtirokingiz uchun rahmat!{promo}")

    if not is_correct:
        return (f"❌ Noto'g'ri.\n\nTo'g'ri javob: «{quiz_round.correct_title}»\n"
                f"Keyingi viktorinada omad! 🍀{promo}")

    # Correct first guess → pay the reward. update_ball doubles it for Premium.
    profile = TelegramProfile.objects.get(id=user_id)
    awarded = profile.update_ball(True, quiz_round.reward)
    answer.is_correct = True
    answer.rewarded = True
    answer.save(update_fields=["is_correct", "rewarded"])
    prem_note = " 💎 ×2!" if awarded > quiz_round.reward else ""
    return (f"✅ To'g'ri! «{quiz_round.correct_title}»\n\n"
            f"🪙 +{awarded} Kitobcha{prem_note}\n"
            f"💰 Balans: {int(profile.ball)}{promo}")


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("bq:"))
async def book_quiz_answer(call: types.CallbackQuery):
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

    text = await sync_to_async(_process_answer)(
        user.id, call.from_user.id, round_id, chosen_idx
    )
    await call.answer(text, show_alert=True)
