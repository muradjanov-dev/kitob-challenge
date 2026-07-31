"""Referral BOOM launch wizard — single guided flow from the admin panel:
announcement text → banner image → confirm, then hands off to
tasks.launch_referral_boom (Celery) for the actual mass broadcast.

Previously this required the CLI-only `launch_referral_boom` management
command; this gives admins a Telegram-native path to the same thing.
"""
import io

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.utils import timezone

from tgbot.bot.loader import dp, bot
from tgbot.bot.states.main import BoomLaunchState

BOOM_TITLE = "Yaxshilik ulashuvchi 1.0"
BOOM_DAYS = 7


def _esc(s: str) -> str:
    import re
    _MAP = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}
    return re.sub(r"[&<>\"']", lambda m: _MAP[m.group(0)], s or "")


@sync_to_async
def _active_boom_exists() -> bool:
    from tgbot.models import ReferralBoom
    return ReferralBoom.objects.filter(is_active=True).exists()


@sync_to_async
def _load_boom_stats():
    """Live snapshot of the current (or, if none is running, the most
    recently finished) Yaxshilik ulashuvchi round: participant count,
    totals, and a TOP-10 by referrals -- admin-only view, unlike the
    personal-only daily DM participants get. Also rolls up LIFETIME totals
    across every past round (not just this one) -- when this round ends
    and a new one starts, the new round's participants/totals accumulate
    into this cumulative figure rather than the picture resetting to only
    whatever round happens to be active right now."""
    from tgbot.models import ReferralBoom, ReferralBoomParticipant

    boom = ReferralBoom.objects.filter(is_active=True).order_by("-created_at").first()
    is_live = bool(boom)
    if not boom:
        boom = ReferralBoom.objects.order_by("-created_at").first()
    if not boom:
        return None

    participants = list(
        ReferralBoomParticipant.objects.filter(boom=boom)
        .select_related("user")
        .order_by("-referrals_count", "-kitobcha_earned", "joined_at")
    )
    total_referrals = sum(p.referrals_count for p in participants)
    total_kitobcha = sum(p.kitobcha_earned for p in participants)

    all_participants = ReferralBoomParticipant.objects.all()
    lifetime = {
        "rounds": ReferralBoom.objects.count(),
        "participants": all_participants.values("user_id").distinct().count(),
        "referrals": sum(all_participants.values_list("referrals_count", flat=True)),
        "kitobcha": sum(all_participants.values_list("kitobcha_earned", flat=True)),
    }
    return {
        "boom": boom, "is_live": is_live, "participants": participants,
        "total_referrals": total_referrals, "total_kitobcha": total_kitobcha,
        "lifetime": lifetime,
    }


async def boom_stats_menu(message: types.Message, user):
    """Admin panel section: monitor the Yaxshilik ulashuvchi competition's
    live standings -- participant count, total referrals/Kitobcha
    distributed, and a TOP-10 leaderboard."""
    data = await _load_boom_stats()
    if not data:
        await message.answer(
            "🌟 <b>Yaxshilik ulashuvchi</b>\n\nHozircha hech qanday musobaqa "
            "o'tkazilmagan.",
            parse_mode="HTML",
        )
        return

    boom = data["boom"]
    participants = data["participants"]
    now = timezone.now()
    status = "🟢 Faol" if data["is_live"] else "⚪️ Yakunlangan"

    if data["is_live"]:
        left = boom.end_at - now
        secs = max(0, int(left.total_seconds()))
        time_line = f"⏳ Qolgan vaqt: <b>{secs // 86400} kun {(secs % 86400) // 3600} soat</b>"
    else:
        time_line = f"🏁 Yakunlangan: <b>{timezone.localtime(boom.end_at).strftime('%d.%m.%Y %H:%M')}</b>"

    lines = [
        f"🌟 <b>{_esc(boom.title)}</b> — {status}",
        f"📅 {timezone.localtime(boom.start_at).strftime('%d.%m %H:%M')} – "
        f"{timezone.localtime(boom.end_at).strftime('%d.%m %H:%M')}",
        time_line,
        "",
        f"👥 Ishtirokchilar: <b>{len(participants)}</b>",
        f"🔗 Jami takliflar: <b>{data['total_referrals']}</b>",
        f"🪙 Jami tarqatilgan: <b>{data['total_kitobcha']} Kitobcha</b>",
        "",
        f"📈 <b>Barcha davrlar (jami):</b> {data['lifetime']['rounds']} ta davr",
        f"👥 Jami ishtirokchilar: <b>{data['lifetime']['participants']}</b>",
        f"🔗 Jami takliflar: <b>{data['lifetime']['referrals']}</b>",
        f"🪙 Jami tarqatilgan: <b>{data['lifetime']['kitobcha']} Kitobcha</b>",
        "",
        "🏆 <b>Joriy davr TOP-10:</b>",
    ]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    top = [p for p in participants if p.referrals_count][:10]
    if top:
        for i, p in enumerate(top, 1):
            name = _esc(p.user.full_name or "Kitobxon")
            lines.append(f"{medals.get(i, f'{i}.')} {name} — {p.referrals_count} ta ({p.kitobcha_earned} 🪙)")
    else:
        lines.append("Hali hech kim taklif qilmadi.")

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🔄 Yangilash", callback_data="admin:boom_stats"))
    if data["is_live"]:
        kb.add(InlineKeyboardButton("🚀 Yangi musobaqa boshlash", callback_data="admin:boom"))
    kb.add(InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="menu:admin"))
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


async def boom_admin_menu(message: types.Message, user, state: FSMContext = None):
    if await _active_boom_exists():
        await message.answer(
            "⚠️ Hozir allaqachon faol musobaqa bor.\n\n"
            "Yangisini boshlasangiz, joriysi avtomatik yakunlanadi. Davom etasizmi?",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("✅ Ha, yangisini boshlayman", callback_data="boomadm:start_anyway"),
                InlineKeyboardButton("❌ Bekor", callback_data="boomadm:cancel"),
            ),
        )
        return
    await _ask_text(message)


async def _ask_text(message: types.Message):
    await BoomLaunchState.text.set()
    await message.answer(
        f"🌟 <b>{BOOM_TITLE}</b> — {BOOM_DAYS} kunlik musobaqa\n\n"
        "1️⃣ <b>E'lon matnini yuboring</b>\n\n"
        "Bu matn barcha guruhlarga va har bir foydalanuvchiga DM qilinadi.\n"
        "Standart (avtomatik) matn uchun: /skip",
        parse_mode="HTML",
    )


@dp.callback_query_handler(lambda c: c.data == "boomadm:start_anyway", state="*")
async def boomadm_start_anyway(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await _ask_text(call.message)


@dp.callback_query_handler(lambda c: c.data == "boomadm:cancel", state="*")
async def boomadm_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.answer("Bekor qilindi")
    await state.finish()


@dp.message_handler(commands=["skip"], state=BoomLaunchState.text)
async def boomadm_skip_text(message: types.Message, state: FSMContext):
    await state.update_data(announce_text=None)
    await _ask_image(message)


@dp.message_handler(state=BoomLaunchState.text, content_types=types.ContentTypes.TEXT)
async def boomadm_get_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if len(text) > 3500:
        await message.answer("Matn juda uzun (Telegram caption/xabar chegarasi). Qisqartiring.")
        return
    await state.update_data(announce_text=text)
    await _ask_image(message)


async def _ask_image(message: types.Message):
    await BoomLaunchState.image.set()
    await message.answer(
        "2️⃣ <b>Banner rasmini yuboring</b>\n\nRasmsiz yuborish uchun: /skip",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["skip"], state=BoomLaunchState.image)
async def boomadm_skip_image(message: types.Message, state: FSMContext):
    await state.update_data(image_file_id=None)
    await _show_preview(message, state)


@dp.message_handler(state=BoomLaunchState.image, content_types=types.ContentTypes.PHOTO)
async def boomadm_get_image(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    await state.update_data(image_file_id=photo.file_id)
    await _show_preview(message, state)


@dp.message_handler(state=BoomLaunchState.image)
async def boomadm_image_invalid(message: types.Message):
    await message.answer("Iltimos rasm yuboring yoki /skip.")


async def _show_preview(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("announce_text")
    has_image = bool(data.get("image_file_id"))
    preview = text or "<i>(standart avtomatik matn ishlatiladi)</i>"
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(f"🚀 {BOOM_DAYS} kunlik musobaqani boshlash", callback_data="boomadm:confirm"))
    kb.add(InlineKeyboardButton("❌ Bekor qilish", callback_data="boomadm:cancel"))
    await message.answer(
        f"3️⃣ <b>Ko'rib chiqing</b>\n\n"
        f"🖼 Rasm: {'✅ biriktirildi' if has_image else 'yo‘q'}\n\n"
        f"{preview}\n\n"
        "Tayyor bo'lsa — boshlaymiz. Bu barcha guruhlarga va har bir "
        "foydalanuvchiga darhol yuboriladi.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@sync_to_async
def _create_boom_sync(announce_text, image_file_bytes):
    from tgbot.models import ReferralBoom

    boom = ReferralBoom.objects.create(
        title=BOOM_TITLE,
        announce_text=announce_text or "",
        planned_days=BOOM_DAYS,
    )
    if image_file_bytes:
        ts = int(timezone.now().timestamp())
        boom.image.save(f"boom_{boom.id}_{ts}.jpg", ContentFile(image_file_bytes), save=True)
    return boom.id


@dp.callback_query_handler(lambda c: c.data == "boomadm:confirm", state=BoomLaunchState.image)
async def boomadm_confirm(call: types.CallbackQuery, state: FSMContext):
    await call.answer("Ishga tushirilmoqda…")
    data = await state.get_data()
    announce_text = data.get("announce_text")
    image_file_id = data.get("image_file_id")

    image_bytes = None
    if image_file_id:
        try:
            buf: io.BytesIO = await bot.download_file_by_id(image_file_id)
            buf.seek(0)
            image_bytes = buf.read()
        except Exception as e:
            print(f"boom_admin: image download failed: {e}")

    boom_id = await _create_boom_sync(announce_text, image_bytes)
    await state.finish()

    from tgbot.tasks import launch_referral_boom
    launch_referral_boom.delay(boom_id=boom_id, days=BOOM_DAYS)

    await call.message.answer(
        f"✅ <b>{BOOM_TITLE}</b> ishga tushirilmoqda!\n\n"
        "Barcha guruhlar va foydalanuvchilarga e'lon fonda yuborilmoqda — "
        "bir necha daqiqa davom etishi mumkin.",
        parse_mode="HTML",
    )
