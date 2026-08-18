"""Kitobxonlik Challenge handlers: join, daily mark, cabinet widget, history."""
import html
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.utils import timezone

from tgbot.bot.loader import dp
from tgbot.bot.utils import aget_user


@sync_to_async
def _verify_and_mark_done(user, challenge_id, today, today_str):
    """Validate today's challenge condition and, if met, append today to the
    participant's completed_dates. Shared by the inline cabinet button and
    the new persistent '✅ Bajardim!' reply-keyboard button."""
    from tgbot.models import Challenge, ChallengeParticipant, ConfirmationReport, UserReferal
    from django.db.models import Sum
    from django.db.models.functions import Length

    challenge = Challenge.objects.filter(id=challenge_id, is_active=True).first()
    if not challenge:
        return "expired", None, 0, ""
    if today < challenge.start_date or today > challenge.end_date:
        return "expired", None, 0, ""

    participant = ChallengeParticipant.objects.filter(challenge=challenge, user=user).first()
    if not participant:
        return "not_joined", None, 0, ""
    if today_str in (participant.completed_dates or []):
        return "already_done", challenge, participant.days_completed, ""

    ctype = challenge.condition_type
    # Guard against a zero/misconfigured threshold auto-passing everyone who
    # merely joined (e.g. `pages >= 0` is always true). Require real activity.
    cval = max(int(challenge.condition_value or 0), 1)
    verified = False
    hint = ""

    if ctype == "pages_daily":
        pages = ConfirmationReport.objects.filter(
            user=user, date__date=today, is_audio=False
        ).aggregate(s=Sum("pages_read"))["s"] or 0
        verified = pages >= cval
        hint = (
            f"📖 <b>Bugungi shart:</b> kamida {cval} bet o'qish.\n"
            f"📊 <b>Hozircha:</b> {pages} bet.\n\n"
            f"<b>Qanday bajaraman?</b>\n"
            f"1) Pastdagi <b>📚 Kitob hisoboti</b> tugmasini bosing\n"
            f"2) Kitobni tanlang va bugun o'qigan betlar sonini kiriting\n"
            f"3) Hisobot yuborilgach, qaytadan <b>✅ Bajardim!</b> tugmasini bosing"
        )

    elif ctype == "audio_daily":
        minutes = ConfirmationReport.objects.filter(
            user=user, date__date=today, is_audio=True
        ).aggregate(s=Sum("minutes_listened"))["s"] or 0
        verified = minutes >= cval
        hint = (
            f"🎧 <b>Bugungi shart:</b> kamida {cval} daqiqa audiokitob eshitish.\n"
            f"📊 <b>Hozircha:</b> {minutes} daqiqa.\n\n"
            f"<b>Qanday bajaraman?</b>\n"
            f"1) <b>📚 Kitob hisoboti</b> tugmasini bosing\n"
            f"2) 🎧 Audiokitobni tanlang va bugun eshitgan daqiqalaringizni kiriting\n"
            f"3) Hisobot yuborilgach, qaytadan <b>✅ Bajardim!</b> tugmasini bosing"
        )

    elif ctype == "referrals_daily":
        count = UserReferal.objects.filter(referrer=user, created_at__date=today).count()
        verified = count >= cval
        hint = (
            f"👥 <b>Bugungi shart:</b> {cval} ta yangi do'stni taklif qilish.\n"
            f"📊 <b>Hozircha:</b> {count} ta.\n\n"
            f"<b>Qanday bajaraman?</b>\n"
            f"1) 👤 Kabinet → 🌟 Yaxshilik ulashuvchi (Referal) tugmasini bosing\n"
            f"2) Havolangizni do'stlaringizga yuboring\n"
            f"3) Ular ro'yxatdan o'tib, birinchi hisobotini yuborgach, taklif hisoblanadi\n"
            f"4) Keyin <b>✅ Bajardim!</b> tugmasini bosing"
        )

    elif ctype == "review_daily":
        verified = ConfirmationReport.objects.filter(
            user=user, date__date=today
        ).annotate(_l=Length("conclusion")).filter(_l__gte=cval).exists()
        hint = (
            f"✍️ <b>Bugungi shart:</b> {cval}+ belgidan iborat taqriz (xulosa) yozish.\n\n"
            f"<b>Qanday bajaraman?</b>\n"
            f"1) Pastdagi <b>📚 Kitob hisoboti</b> tugmasini bosing\n"
            f"2) Kitob va sahifalarni odatdagidek kiriting\n"
            f"3) Oxirgi qadamda — <b>«Xulosa»</b> bo'limida {cval}+ belgilik fikr-mulohaza yozing\n"
            f"   (Misol uchun: kitob nima haqida, qaysi joyi yoqdi, nima o'rgandingiz)\n"
            f"4) Hisobot yuborilgach, qaytadan <b>✅ Bajardim!</b> tugmasini bosing\n\n"
            f"<i>💡 200 belgi — bu taxminan 2-3 jumla.</i>"
        )

    if not verified:
        return "not_verified", challenge, participant.days_completed, hint

    dates = list(participant.completed_dates or [])
    dates.append(today_str)
    new_days = len(dates)
    last_at = timezone.now() if new_days >= 3 else participant.last_completed_at
    ChallengeParticipant.objects.filter(id=participant.id).update(
        completed_dates=dates,
        days_completed=new_days,
        last_completed_at=last_at,
    )
    return "marked", challenge, new_days, ""


@sync_to_async
def _find_active_challenge_id():
    from tgbot.models import Challenge
    ch = Challenge.objects.filter(is_active=True).first()
    return ch.id if ch else None


# Per-user dynamic label for the persistent '✅ Bajardim!' reply-keyboard
# button — embeds today's progress (N/3) plus the challenge condition
# (e.g. '50+ bet') so the user always sees their status at a glance.
@sync_to_async
def compute_bajardim_label(user, lang: str = "uz") -> str:
    from tgbot.models import Challenge, ChallengeParticipant
    base = "✅ Выполнено!" if lang == "ru" else "✅ Bajardim!"
    ch = Challenge.objects.filter(is_active=True).first()
    if not ch:
        return base

    days_completed = 0
    if user:
        p = ChallengeParticipant.objects.filter(challenge=ch, user=user).first()
        if p:
            days_completed = p.days_completed

    title_clean = ch.title
    import re
    title_clean = re.sub(r'(?i)\bchallenge\b', '', title_clean)
    title_clean = re.sub(r'\s+', ' ', title_clean).strip()

    title_short = title_clean
    if len(title_short) > 15:
        title_short = title_short[:12] + "..."

    cond_map_uz = {
        "pages_daily":     f"{ch.condition_value}+ bet",
        "audio_daily":     f"{ch.condition_value}+ daq",
        "referrals_daily": f"{ch.condition_value}+ taklif",
        "review_daily":    f"{ch.condition_value}+ xulosa",
    }
    cond_map_ru = {
        "pages_daily":     f"{ch.condition_value}+ стр",
        "audio_daily":     f"{ch.condition_value}+ мин",
        "referrals_daily": f"{ch.condition_value}+ приглашений",
        "review_daily":    f"{ch.condition_value}+ симв.",
    }
    cond = (cond_map_ru if lang == "ru" else cond_map_uz).get(ch.condition_type, "")

    parts = [base, f"· {title_short} ({days_completed}/3)"]
    if cond:
        parts.append(f"· {cond}")
    return " ".join(parts)


# ── Join ──────────────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("join_challenge:"), state="*")
async def join_challenge_handler(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user or not user.is_registered:
        await call.answer("Avval /start bosib ro'yxatdan o'ting.", show_alert=True)
        return

    challenge_id = int(call.data.split(":")[1])

    @sync_to_async
    def _join():
        from tgbot.models import Challenge, ChallengeParticipant
        challenge = Challenge.objects.filter(id=challenge_id, is_active=True).first()
        if not challenge:
            return None, "expired", [], 0
        _, created = ChallengeParticipant.objects.get_or_create(challenge=challenge, user=user)
        # Pull recent participants (excluding current user) for the
        # 'who else joined' section. Cap at 20 names; total count still shown.
        others_qs = (
            ChallengeParticipant.objects
            .filter(challenge=challenge).exclude(user=user)
            .select_related("user").order_by("-joined_at")
        )
        total_others = others_qs.count()
        recent_names = [
            (p.user.full_name or "Kitobxon") for p in others_qs[:20]
        ]
        return challenge, ("joined" if created else "already"), recent_names, total_others

    challenge, status, recent_names, total_others = await _join()

    if status == "expired":
        await call.answer("❌ Bu challenge tugadi yoki mavjud emas.", show_alert=True)
        return
    if status == "already":
        await call.answer("✅ Siz allaqachon bu challengeda qatnashyapsiz!", show_alert=True)
        return

    others_block = ""
    if total_others > 0:
        shown = ", ".join(html.escape(n) for n in recent_names)
        if total_others > len(recent_names):
            shown += f" <i>va yana {total_others - len(recent_names)} kishi</i>"
        others_block = (
            f"\n👥 <b>Siz bilan birga ({total_others + 1} kishi):</b>\n"
            f"{shown}\n"
        )
    else:
        others_block = "\n👥 Siz birinchi bo'lib qo'shildingiz — do'stlaringizni ham taklif qiling! 🚀\n"

    await call.answer("✅ Qo'shildingiz!", show_alert=False)
    await call.message.answer(
        f"🎉 <b>{challenge.emoji} {challenge.title}</b> ga muvaffaqiyatli qo'shildingiz!\n\n"
        f"📋 <b>Shart:</b> {challenge.description}\n"
        f"📅 <b>Muddat:</b> {challenge.start_date.strftime('%d.%m')} – {challenge.end_date.strftime('%d.%m.%Y')}\n"
        f"{others_block}\n"
        "Har kuni shartni bajargach, <b>Kabinetingiz</b>dan ✅ Bajarldim tugmasini bosing.\n"
        "Omad! 🚀",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ── Daily mark (manual trigger from cabinet) ──────────────────────────────

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("challenge_done:"), state="*")
async def challenge_done_handler(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing.", show_alert=True)
        return

    challenge_id = int(call.data.split(":")[1])
    today = timezone.localdate()
    status, challenge, days_done, hint = await _verify_and_mark_done(
        user, challenge_id, today, today.isoformat()
    )

    if status == "expired":
        await call.answer("❌ Bu challenge tugadi.", show_alert=True)
    elif status == "not_joined":
        await call.answer("❌ Avval challengega qo'shiling.", show_alert=True)
    elif status == "already_done":
        await call.answer(f"✅ Bugun allaqachon bajargansiz! ({days_done}/3)", show_alert=True)
    elif status == "not_verified":
        # Long HTML hint won't fit in a callback popup — send it as a message.
        await call.answer("⏳ Hali shart bajarilmagan.", show_alert=False)
        await call.message.answer(
            f"⏳ <b>Hali shart bajarilmagan</b>\n\n{hint}",
            parse_mode="HTML",
        )
    else:
        await call.answer(f"✅ {days_done}/3 kun bajarildi!", show_alert=False)
        end_msg = "🎉 Barcha 3 kun bajarildi! Natijalar e'lon qilinadi." if days_done >= 3 else f"⏳ Yana {3 - days_done} kun qoldi."
        await call.message.answer(
            f"✅ <b>Bajarildi! {days_done}/3 kun</b>\n\n{end_msg}",
            parse_mode="HTML",
        )


@dp.message_handler(
    Text(startswith=["✅ Bajardim!", "✅ Выполнено!"]),
    state="*",
)
async def challenge_done_reply_button(message: types.Message, state: FSMContext):
    """Persistent '✅ Bajardim!' reply-keyboard button — finds the currently
    active challenge and runs the same verify/mark logic as the inline button.
    Works from any state so it never gets swallowed by an in-progress flow."""
    user = await aget_user(message.from_user.id)
    if not user:
        await message.answer("Avval /start bosing.")
        return

    challenge_id = await _find_active_challenge_id()
    if not challenge_id:
        await message.answer("Hozir aktiv challenge yo'q.")
        return

    today = timezone.localdate()
    status, challenge, days_done, hint = await _verify_and_mark_done(
        user, challenge_id, today, today.isoformat()
    )

    if status == "expired":
        await message.answer("❌ Bu challenge tugadi.")
    elif status == "not_joined":
        await message.answer(
            "❌ <b>Siz bu challengega qo'shilmagansiz.</b>\n\n"
            "<b>Qatnashish uchun:</b>\n"
            "1) Pastdagi 👤 <b>Kabinet</b> tugmasini bosing\n"
            "2) «Joriy Challenge» bo'limidagi <b>✅ Qatnashaman</b> tugmasini bosing\n"
            "3) Shartni bajaring va <b>✅ Bajardim!</b> tugmasini bosing",
            parse_mode="HTML",
        )
    elif status == "already_done":
        await message.answer(
            f"✅ <b>Bugun allaqachon bajargansiz!</b> ({days_done}/3 kun)\n\n"
            f"<i>Ertaga shartni yana bajaring va shu tugmani qaytadan bosing.</i>",
            parse_mode="HTML",
        )
    elif status == "not_verified":
        await message.answer(
            f"⏳ <b>Hali shart bajarilmagan</b>\n\n{hint}",
            parse_mode="HTML",
        )
    else:
        end_msg = (
            "🎉 Barcha 3 kun bajarildi! Natijalar e'lon qilinadi."
            if days_done >= 3 else f"⏳ Yana {3 - days_done} kun qoldi."
        )
        # Refresh the persistent keyboard so the Bajardim! button label
        # reflects the new N/3 count immediately.
        from tgbot.bot.keyboards.reply import report_reply_keyboard
        lang = (user.language if user else None) or "uz"
        new_label = await compute_bajardim_label(user, lang)
        is_admin = bool(user and getattr(user, "is_admin", False))
        await message.answer(
            f"✅ <b>Bajarildi! {days_done}/3 kun</b>\n\n{end_msg}",
            parse_mode="HTML",
            reply_markup=report_reply_keyboard(lang, new_label, is_admin=is_admin),
        )


# ── Challenge history (premium) ───────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "challenge:history", state="*")
async def challenge_history_handler(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer()
        return

    @sync_to_async
    def _load():
        from tgbot.models import ChallengeParticipant
        from tgbot.services.premium import is_premium
        is_prem = is_premium(user)
        if not is_prem:
            return None, []
        parts = list(
            ChallengeParticipant.objects.filter(user=user)
            .select_related("challenge")
            .order_by("-challenge__start_date")[:20]
        )
        return is_prem, parts

    is_prem, parts = await _load()

    await call.answer()
    if not is_prem:
        await call.message.answer(
            "🔒 <b>Challenge tarixi — Premium</b>\n\n"
            "To'liq challenge tarixini ko'rish uchun Premium obuna kerak.",
            parse_mode="HTML",
        )
        return

    if not parts:
        await call.message.answer("📭 Siz hali hech qanday challengeda qatnashmagansiz.")
        return

    lines = ["📋 <b>Sizning challenge tarixingiz:</b>\n"]
    for p in parts:
        ch = p.challenge
        place = f"{p.rank}-o'rin" if p.rank else "—"
        lines.append(
            f"{ch.emoji} <b>{ch.title}</b>\n"
            f"   📅 {ch.start_date.strftime('%d.%m.%Y') if ch.start_date else '—'}\n"
            f"   ✅ {p.days_completed}/3 kun | 🏅 {place}\n"
        )

    await call.message.answer("\n".join(lines), parse_mode="HTML")


# ── Cabinet widget helpers (called from menu_router) ──────────────────────

@sync_to_async
def _load_challenge_for_cabinet(user):
    from tgbot.models import Challenge, ChallengeParticipant, Payment
    challenge = Challenge.objects.filter(is_active=True).first()
    if not challenge:
        return None, None, False
    participant = ChallengeParticipant.objects.filter(challenge=challenge, user=user).first()
    from tgbot.services.premium import is_premium
    is_prem = is_premium(user)
    return challenge, participant, is_prem


async def challenge_cabinet_block(user):
    """Returns (text_snippet, [InlineKeyboardButton, ...]) for cabinet injection."""
    challenge, participant, is_prem = await _load_challenge_for_cabinet(user)
    if not challenge:
        return "", []

    today_str = timezone.localdate().isoformat()
    days_done = participant.days_completed if participant else 0
    already_today = participant and today_str in (participant.completed_dates or [])

    text = (
        f"\n\n{challenge.emoji} <b>Joriy Challenge: {challenge.title}</b>\n"
        f"📋 {challenge.description}\n"
        f"📅 {challenge.start_date.strftime('%d.%m')} – {challenge.end_date.strftime('%d.%m.%Y')}"
    )
    if participant:
        text += f"\n✅ Bajarilgan: <b>{days_done}/3 kun</b>"
    else:
        text += "\n🔘 Qatnashmayapsiz"

    buttons = []
    if participant:
        if days_done < 3 and not already_today:
            buttons.append(InlineKeyboardButton(
                f"✅ Bugun bajarldim! ({days_done + 1}/3)",
                callback_data=f"challenge_done:{challenge.id}",
            ))
        elif already_today:
            buttons.append(InlineKeyboardButton(
                f"✔️ Bugun bajardingiz ({days_done}/3)", callback_data="noop",
            ))
        if is_prem:
            buttons.append(InlineKeyboardButton("📋 Challenge tarixi", callback_data="challenge:history"))
        else:
            buttons.append(InlineKeyboardButton("🔒 Challenge tarixi (Premium)", callback_data="menu:premium"))
    else:
        title_short = challenge.title
        if len(title_short) > 25:
            title_short = title_short[:22] + "..."
        buttons.append(InlineKeyboardButton(
            f"🎮 \"{title_short}\"da qatnashaman! {challenge.emoji}",
            callback_data=f"join_challenge:{challenge.id}",
        ))

    return text, buttons
