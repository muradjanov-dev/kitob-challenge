"""Kitob Viktorina — answer handling."""
import asyncio
from asgiref.sync import sync_to_async
from aiogram import types
from django.utils import timezone

from tgbot.bot.loader import dp
from tgbot.bot.utils import aget_user
from tgbot.models import BookQuizRound, BookQuizAnswer, Payment, TelegramProfile


_STATS_PROMO = (
    "\n\n💎 To'liq viktorina statistikangizni ko'rish uchun Premiumga o'ting!"
)


def _is_premium(user_id: int) -> bool:
    # Sinov Premiumi ham shu eshikdan o'tadi -- tafsilot: services/premium.py
    from tgbot.services.premium import is_premium_by_id
    return is_premium_by_id(user_id)


def _process_answer(user_id: int, round_id: int, chosen_idx: int) -> str:
    """Validate + record one answer. Pure DB — no external HTTP calls."""
    quiz_round = BookQuizRound.objects.filter(id=round_id).first()
    if not quiz_round:
        return "Bu viktorina topilmadi."

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

    if quiz_round.source_user_id == user_id:
        return (f"🙂 Bu o'zingiz yuborgan xulosa — mukofot yo'q, lekin "
                f"ishtirokingiz uchun rahmat!{promo}")

    profile = TelegramProfile.objects.get(id=user_id)
    if is_correct:
        awarded = profile.update_ball(True, quiz_round.reward)
        answer.rewarded = True
        answer.save(update_fields=["rewarded"])
        prem_note = " 💎 ×2!" if awarded > quiz_round.reward else ""

        try:
            from tgbot.services.achievements import award_new_achievements
            newly = award_new_achievements(profile)
            ach_note = ""
            if newly:
                # Bug fix: this used to list the unlocked achievements without
                # ever crediting their Kitobcha — only tasks.check_user_achievements
                # did that. Award here too (×2 for premium, via update_ball).
                names = []
                for a in newly:
                    pts = a.get("points", 0)
                    aw = profile.update_ball(True, pts) if pts else 0
                    prem_note = " 💎×2" if aw > pts else ""
                    names.append(f"{a['emoji']} {a['title_uz']} (+{aw} 🪙{prem_note})" if aw else f"{a['emoji']} {a['title_uz']}")
                ach_note = "\n\n🏆 Yangi yutuq: " + ", ".join(names) + "!"
        except Exception:
            ach_note = ""

        return (f"✅ To'g'ri! «{quiz_round.correct_title}»\n\n"
                f"🪙 +{awarded} Kitobcha{prem_note}\n"
                f"💰 Balans: {int(profile.ball)}{ach_note}{promo}")
    else:
        awarded = profile.update_ball(True, quiz_round.consolation)
        answer.rewarded = True
        answer.save(update_fields=["rewarded"])
        prem_note = " 💎 ×2!" if awarded > quiz_round.consolation else ""
        return (f"❌ Noto'g'ri. To'g'ri javob: «{quiz_round.correct_title}»\n\n"
                f"🎁 Urinish uchun: +{awarded} Kitobcha{prem_note}\n"
                f"💰 Balans: {int(profile.ball)}\n"
                f"Keyingi viktorinada omad! 🍀{promo}")


def _refresh_boards_bg(quiz_round_id: int):
    """Refresh group boards in background — does not block the answer popup."""
    try:
        from tgbot.tasks import refresh_quiz_boards
        from tgbot.models import BookQuizRound as _BQR
        qr = _BQR.objects.filter(id=quiz_round_id).first()
        if qr:
            refresh_quiz_boards(qr)
    except Exception:
        pass


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

    text = await sync_to_async(_process_answer)(user.id, round_id, chosen_idx)

    # Telegram caps callback-alert text at 200 chars -- achievement unlock
    # notes can push this over, which made answerCallbackQuery raise
    # Message_too_long and crash the handler entirely. The DB write above
    # had already succeeded, so the vote was recorded but the user never
    # saw any confirmation -- looked exactly like the tap did nothing.
    if len(text) > 200:
        text = text[:197] + "..."

    # Answer popup fires immediately — board refresh runs in background.
    try:
        await call.answer(text, show_alert=True)
    except Exception as e:
        print(f"book_quiz_answer: call.answer failed uid={user.id} round={round_id}: {e}")
    asyncio.get_event_loop().run_in_executor(None, _refresh_boards_bg, round_id)
