from aiogram.utils.markdown import hlink
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from django.utils import timezone
from asgiref.sync import sync_to_async
from tgbot.bot.keyboards.reply import admin_keyboard, confirm_markup, main_markup, yes_or_no_markup, back_keyboard
from aiogram.dispatcher.filters import Text
from tgbot.bot import dp
from tgbot.models import TelegramProfile, BookReport, ConfirmationReport, BooksToRead, UserAchievement
from aiogram import types
from aiogram.dispatcher import FSMContext
from tgbot.bot.states.main import StatisticState, NotificationState, AdminUserBrowse
from tgbot.bot.filters import IsPrivate
from tgbot.bot.utils import aget_user
from tgbot.bot.loader import gettext as _, bot


@dp.message_handler(IsPrivate(), commands=["admin"], state="*")
@dp.message_handler(IsPrivate(), Text(equals=["👑 Admin panel", "👑 Админ панель"]), state="*")
async def admin_commands(message: types.Message, state: FSMContext = None):
    telegram_id = message.from_user.id
    user = await aget_user(telegram_id)
    if user and user.is_admin:
        if state is not None:
            try:
                await state.finish()
            except Exception:
                pass
        await message.answer("Menudan birini tanlang:", reply_markup=admin_keyboard)
    else:
        await message.answer("Siz admin emassiz!")


async def _launch_chain_game(target_message):
    """Start a live Kitob Zanjiri now (inline, so it works even if the
    celery_worker image is stale) and reply with a button to open the game."""
    from asgiref.sync import sync_to_async
    from aiogram.types import WebAppInfo
    from src.settings import WEB_DOMAIN

    await target_message.answer("🔗 Kitob Zanjiri boshlanmoqda…")
    try:
        from tgbot.tasks import start_chain_game
        await sync_to_async(start_chain_game)()
    except Exception as e:
        import traceback
        print(f"[admin start_zanjir] {e}\n{traceback.format_exc()}")
        await target_message.answer(f"❌ Xatolik: <code>{e}</code>", parse_mode="HTML")
        return
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
        "🔗 O'yinni ochish", web_app=WebAppInfo(url=f"{WEB_DOMAIN}/zanjir/"),
    ))
    await target_message.answer(
        "✅ <b>Kitob Zanjiri e'lon qilindi!</b> 30 soniyadan keyin boshlanadi. "
        "Guruhlarga e'lon yuborildi.",
        parse_mode="HTML", reply_markup=kb,
    )


@dp.message_handler(IsPrivate(), commands=["zanjir"], state="*")
async def admin_zanjir_command(message: types.Message, state: FSMContext = None):
    user = await aget_user(message.from_user.id)
    if not (user and user.is_admin):
        await message.answer("Siz admin emassiz!")
        return
    if state is not None:
        try:
            await state.finish()
        except Exception:
            pass
    await _launch_chain_game(message)


@dp.callback_query_handler(IsPrivate(), lambda c: c.data == "admin:start_zanjir", state="*")
async def admin_start_zanjir_cb(call: types.CallbackQuery, state: FSMContext = None):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    await call.answer("Boshlanmoqda…")
    await _launch_chain_game(call.message)


async def _launch_game(target_message, start_task, web_path, title):
    """Generic: run a game's start task inline and reply with an open button."""
    from asgiref.sync import sync_to_async
    from aiogram.types import WebAppInfo
    from src.settings import WEB_DOMAIN

    await target_message.answer(f"{title} boshlanmoqda…")
    try:
        await sync_to_async(start_task)()
    except Exception as e:
        import traceback
        print(f"[admin start {title}] {e}\n{traceback.format_exc()}")
        await target_message.answer(f"❌ Xatolik: <code>{e}</code>", parse_mode="HTML")
        return
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
        "🎮 O'yinni ochish", web_app=WebAppInfo(url=f"{WEB_DOMAIN}{web_path}"),
    ))
    await target_message.answer(
        f"✅ <b>{title}</b> e'lon qilindi! 30 soniyadan keyin boshlanadi. "
        "Guruhlarga e'lon yuborildi.",
        parse_mode="HTML", reply_markup=kb,
    )


@dp.message_handler(IsPrivate(), commands=["kopchilik"], state="*")
async def admin_kopchilik_command(message: types.Message, state: FSMContext = None):
    user = await aget_user(message.from_user.id)
    if not (user and user.is_admin):
        await message.answer("Siz admin emassiz!")
        return
    if state is not None:
        try:
            await state.finish()
        except Exception:
            pass
    from tgbot.tasks import start_feud_game
    await _launch_game(message, start_feud_game, "/kopchilik/", "Ko'pchilik nima dedi?")


@dp.message_handler(IsPrivate(), commands=["qala"], state="*")
async def admin_qala_command(message: types.Message, state: FSMContext = None):
    user = await aget_user(message.from_user.id)
    if not (user and user.is_admin):
        await message.answer("Siz admin emassiz!")
        return
    if state is not None:
        try:
            await state.finish()
        except Exception:
            pass
    from tgbot.tasks import start_castle_game
    await _launch_game(message, start_castle_game, "/qala/", "Bilim Qal'asi")


@dp.message_handler(IsPrivate(), commands=["jami"], state="*")
async def admin_total_pages(message: types.Message, state: FSMContext = None):
    """One command: announce the platform-wide total pages read (and a few more
    milestones) to every reading group."""
    from asgiref.sync import sync_to_async
    user = await aget_user(message.from_user.id)
    if not (user and user.is_admin):
        await message.answer("Siz admin emassiz!")
        return

    @sync_to_async
    def _stats():
        from django.db.models import Sum, Count, F
        from tgbot.models import TelegramProfile, ConfirmationReport, BooksToRead
        pages = ConfirmationReport.objects.filter(is_audio=False).aggregate(
            s=Sum("pages_read"))["s"] or 0
        audio = ConfirmationReport.objects.filter(is_audio=True).aggregate(
            s=Sum("pages_read"))["s"] or 0
        readers = TelegramProfile.objects.filter(is_registered=True).count()
        finished = BooksToRead.objects.filter(
            total_pages__gt=0, current_page__gte=F("total_pages")).count()
        reports = ConfirmationReport.objects.count()
        return pages, audio, readers, finished, reports

    pages, audio, readers, finished, reports = await _stats()

    def fmt(n):
        return f"{int(n or 0):,}".replace(",", " ")

    text = (
        "📚 <b>KITOB CHALLENGE — UMUMIY NATIJA</b>\n\n"
        "Bugungi kunga qadar hamjamiyatimiz birgalikda:\n"
        f"📖 <b>{fmt(pages)} bet</b> o'qidi!\n"
        f"🎧 <b>{fmt(audio)} daqiqa</b> audiokitob tingladi!\n\n"
        f"👥 {fmt(readers)} kitobxon\n"
        f"✅ {fmt(finished)} kitob tugatildi\n"
        f"📝 {fmt(reports)} ta hisobot yuborildi\n\n"
        "Bu — BIZNING umumiy natijamiz! 🔥 O'qishda davom etamiz 📚"
    )

    from tgbot.tasks import _group_chat_ids
    from tgbot.bot.loader import bot as _bot
    sent = 0
    for gid in _group_chat_ids():
        try:
            await _bot.send_message(gid, text, parse_mode="HTML",
                                    disable_web_page_preview=True)
            sent += 1
        except Exception as e:
            print(f"admin /jami group {gid}: {e}")
    await message.answer(f"✅ {sent} guruhga e'lon yuborildi.\n\n{text}", parse_mode="HTML")


@dp.callback_query_handler(IsPrivate(), lambda c: c.data == "admin:start_feud", state="*")
async def admin_start_feud_cb(call: types.CallbackQuery, state: FSMContext = None):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    await call.answer("Boshlanmoqda…")
    from tgbot.tasks import start_feud_game
    await _launch_game(call.message, start_feud_game, "/kopchilik/", "Ko'pchilik nima dedi?")


@dp.callback_query_handler(IsPrivate(), lambda c: c.data == "admin:start_castle", state="*")
async def admin_start_castle_cb(call: types.CallbackQuery, state: FSMContext = None):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    await call.answer("Boshlanmoqda…")
    from tgbot.tasks import start_castle_game
    await _launch_game(call.message, start_castle_game, "/qala/", "Bilim Qal'asi")


@dp.message_handler(IsPrivate(), commands=["emoji"], state="*")
async def admin_emoji_command(message: types.Message, state: FSMContext = None):
    user = await aget_user(message.from_user.id)
    if not (user and user.is_admin):
        await message.answer("Siz admin emassiz!")
        return
    if state is not None:
        try:
            await state.finish()
        except Exception:
            pass
    from tgbot.tasks import start_emoji_game
    await _launch_game(message, start_emoji_game, "/emoji/", "Emoji Kitob")


@dp.callback_query_handler(IsPrivate(), lambda c: c.data == "admin:start_emoji", state="*")
async def admin_start_emoji_cb(call: types.CallbackQuery, state: FSMContext = None):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    await call.answer("Boshlanmoqda…")
    from tgbot.tasks import start_emoji_game
    await _launch_game(call.message, start_emoji_game, "/emoji/", "Emoji Kitob")


# ── All 14 games — one submenu, manual start for any of them ────────────────
# (key, title, web_path, tasks.py function name). Covers the original 4 (which
# also still have their own direct top-level buttons above) plus all 10 games
# built 2026-07-22, so every live game has a manual-start button in one place.
_GAMES_MENU = [
    ("chain", "🔗 Kitob Zanjiri", "/zanjir/", "start_chain_game"),
    ("feud", "🗣 Ko'pchilik nima dedi?", "/kopchilik/", "start_feud_game"),
    ("castle", "🏰 Bilim Qal'asi", "/qala/", "start_castle_game"),
    ("emoji", "🎬 Emoji Kitob", "/emoji/", "start_emoji_game"),
    ("wisdom", "☪️ Hikmat Xazinasi", "/hikmat/", "start_wisdom_game"),
    ("detective", "📖 Kitob Detektivi", "/detektiv/", "start_detective_game"),
    ("survival", "💀 Omon qolish", "/omon-qolish/", "start_survival_game"),
    ("twofacts", "🎭 Ikki haqiqat, bir yolg'on", "/ikki-haqiqat/", "start_quiz_twofacts_game"),
    ("impostor", "🃏 Kim yolg'onchi?", "/kim-yolgonchi/", "start_quiz_impostor_game"),
    ("connection", "🧩 Yashirin bog'lanish", "/bog-lanish/", "start_quiz_connection_game"),
    ("teams", "👥 Jamoa Jangi", "/jamoa-jangi/", "start_quiz_teams_game"),
    ("timeline", "🕰️ Vaqt Mashinasi", "/vaqt-mashinasi/", "start_quiz_timeline_game"),
    ("matchbook", "🎯 Muallif-Asar Moslashtirish", "/muallif-asar/", "start_quiz_matchbook_game"),
    ("reverse", "🔄 Teskari Viktorina", "/teskari-viktorina/", "start_quiz_reverse_game"),
]
_GAMES_MENU_BY_KEY = {key: (title, path, task_name) for key, title, path, task_name in _GAMES_MENU}


def _games_admin_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    for key, title, _path, _task_name in _GAMES_MENU:
        kb.insert(InlineKeyboardButton(title, callback_data=f"adm_game:{key}"))
    kb.row(InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="menu:admin"))
    return kb


def _create_game_silent(key):
    """Create a live game instance for `key` WITHOUT any group announcement —
    used by the admin's silent test-play button. Mirrors what each start_*_game
    task does internally, minus the `_announce_game()` broadcast."""
    if key == "chain":
        from tgbot.services.chain_game import create_scheduled_game, finalize_due_games
        finalize_due_games()
        return create_scheduled_game()
    if key == "feud":
        from tgbot.services.feud_game import create_scheduled_feud, finalize_due_games
        finalize_due_games()
        return create_scheduled_feud()
    if key == "castle":
        from tgbot.services.castle_game import create_scheduled_castle, finalize_due_games
        finalize_due_games()
        return create_scheduled_castle()
    if key == "emoji":
        from tgbot.services.emoji_game import create_scheduled_emoji, finalize_due_games
        finalize_due_games()
        return create_scheduled_emoji()
    if key == "wisdom":
        from tgbot.services.wisdom_game import create_scheduled_wisdom, finalize_due_games
        finalize_due_games()
        return create_scheduled_wisdom()
    if key == "detective":
        from tgbot.services.detective_game import create_scheduled_detective, finalize_due_games
        finalize_due_games()
        return create_scheduled_detective()
    if key == "survival":
        from tgbot.services.survival_game import create_scheduled_survival, finalize_due_games
        finalize_due_games()
        return create_scheduled_survival()
    # The 7 Bilim O'yini flavors all share one engine.
    from tgbot.services.quiz_game import create_scheduled_quiz, finalize_due_games
    finalize_due_games(key)
    return create_scheduled_quiz(key)


async def _launch_game_silent(target_message, key, web_path, title):
    """Create a live game for admin-only testing — no group announcement, no
    public deep link. Only the admin who tapped the button gets an open
    button in their own DM."""
    await target_message.answer(f"🧪 {title} sinov rejimida yaratilmoqda… (guruhga e'lon qilinmaydi)")
    try:
        await sync_to_async(_create_game_silent)(key)
    except Exception as e:
        import traceback
        print(f"[admin test {title}] {e}\n{traceback.format_exc()}")
        await target_message.answer(f"❌ Xatolik: <code>{e}</code>", parse_mode="HTML")
        return
    from aiogram.types import WebAppInfo
    from src.settings import WEB_DOMAIN
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
        "🧪 O'yinni sinab ko'rish", web_app=WebAppInfo(url=f"{WEB_DOMAIN}{web_path}"),
    ))
    await target_message.answer(
        f"✅ <b>{title}</b> sinov o'yini tayyor — bu faqat sizga ko'rinadi, guruhga hech narsa "
        "yuborilmadi. 30 soniyadan keyin boshlanadi.",
        parse_mode="HTML", reply_markup=kb,
    )


def _games_test_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    for key, title, _path, _task_name in _GAMES_MENU:
        kb.insert(InlineKeyboardButton(title, callback_data=f"adm_test:{key}"))
    kb.row(InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="menu:admin"))
    return kb


@dp.callback_query_handler(IsPrivate(), lambda c: c.data == "admin:games_test_menu", state="*")
async def admin_games_test_menu_cb(call: types.CallbackQuery, state: FSMContext = None):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    await call.message.answer(
        "🧪 <b>Qaysi o'yinni jimgina sinab ko'ramiz?</b>\n\n"
        "Bu yerda tanlangan o'yin FAQAT sizga ochiladi — guruhga hech qanday e'lon yuborilmaydi.",
        parse_mode="HTML", reply_markup=_games_test_menu_kb(),
    )


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("adm_test:"), state="*")
async def admin_test_any_game_cb(call: types.CallbackQuery, state: FSMContext = None):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    key = call.data.split(":", 1)[1]
    entry = _GAMES_MENU_BY_KEY.get(key)
    if not entry:
        await call.answer("Noma'lum o'yin.", show_alert=True)
        return
    title, web_path, _task_name = entry
    await call.answer("Sinov rejimida yaratilmoqda…")
    await _launch_game_silent(call.message, key, web_path, title)


@dp.callback_query_handler(IsPrivate(), lambda c: c.data == "admin:games_menu", state="*")
async def admin_games_menu_cb(call: types.CallbackQuery, state: FSMContext = None):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    await call.message.answer(
        "🎮 <b>Qaysi o'yinni hozir boshlaymiz?</b>\n\n"
        "Bosilgan o'yin darhol e'lon qilinadi va 30 soniyadan keyin boshlanadi.",
        parse_mode="HTML", reply_markup=_games_admin_menu_kb(),
    )


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("adm_game:"), state="*")
async def admin_start_any_game_cb(call: types.CallbackQuery, state: FSMContext = None):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    key = call.data.split(":", 1)[1]
    entry = _GAMES_MENU_BY_KEY.get(key)
    if not entry:
        await call.answer("Noma'lum o'yin.", show_alert=True)
        return
    title, web_path, task_name = entry
    await call.answer("Boshlanmoqda…")
    import tgbot.tasks as _tasks
    start_task = getattr(_tasks, task_name)
    await _launch_game(call.message, start_task, web_path, title)


@dp.message_handler(IsPrivate(), commands=["fix_referrals"], state="*")
async def admin_fix_referrals(message: types.Message, state: FSMContext = None):
    """Admin-only backfill: process every referral that got stuck 'pending'
    (invited user registered + already reported, but was never counted due to
    the old first-report-only bug). Idempotent — process_referral skips anyone
    already referred."""
    from asgiref.sync import sync_to_async
    from tgbot.models import TelegramProfile, ConfirmationReport, UserReferal
    from tgbot.services.referral import ReferralService

    user = await aget_user(message.from_user.id)
    if not (user and user.is_admin):
        await message.answer("Siz admin emassiz!")
        return
    await message.answer("🔧 Referal backfill boshlandi…")

    @sync_to_async
    def _stuck():
        out = []
        qs = (
            TelegramProfile.objects
            .filter(is_registered=True)
            .exclude(pending_referral_code__isnull=True)
            .exclude(pending_referral_code__exact="")
        )
        for p in qs:
            if not ConfirmationReport.objects.filter(user=p).exists():
                continue  # hasn't read yet — leave pending (fires on next report)
            if UserReferal.objects.filter(referred_user=p).exists():
                continue  # already counted
            out.append((p.id, p.pending_referral_code))
        return out

    stuck = await _stuck()
    done = failed = 0
    for pid, code in stuck:
        try:
            p = await sync_to_async(TelegramProfile.objects.get)(id=pid)
            await sync_to_async(
                TelegramProfile.objects.filter(id=pid).update
            )(pending_referral_code=None)
            if await ReferralService.process_referral(p, code):
                done += 1
        except Exception as e:
            failed += 1
            print(f"fix_referrals {pid}: {e}")

    await message.answer(
        f"✅ Backfill tugadi.\nTopilgan (o'qigan, hisoblanmagan): <b>{len(stuck)}</b>\n"
        f"Hisoblandi: <b>{done}</b>\nXato: <b>{failed}</b>",
        parse_mode="HTML",
    )


@dp.message_handler(IsPrivate(), commands=["test_weekly_report"], state="*")
async def test_weekly_report_handler(message: types.Message, state: FSMContext = None):
    """Admin-only: trigger AI-generated weekly report card to self.
    Usage: /test_weekly_report   (default uz)
           /test_weekly_report ru

    Runs the task inline (in bot process thread) so it works even if the
    celery_worker service is on a stale image without the task registered.
    """
    import asyncio
    user = await aget_user(message.from_user.id)
    if not (user and user.is_admin):
        await message.answer("Siz admin emassiz!")
        return

    args = (message.get_args() or "").strip().lower()
    lang = "ru" if args == "ru" else "uz"

    await message.answer(
        "⏳ AI report generatsiya qilinmoqda...\n"
        "🎨 Imagen 3 + 💎 Gemini 2.0 Flash\n"
        "20-40 soniyada rasm va matn keladi."
    )

    from tgbot.tasks import send_ai_report_to_admin
    # Run sync task in a thread to keep bot loop responsive.
    # .run() invokes the underlying function directly, bypassing Celery's
    # broker — so it works even when celery_worker is on a stale image.
    asyncio.create_task(asyncio.to_thread(
        send_ai_report_to_admin.run, message.from_user.id, lang
    ))


@dp.message_handler(IsPrivate(), text="✉️ Habar yuborish")
async def send_notification_text_handler(message: types.Message):
    await message.answer("Habarni tektini yuboring.", reply_markup=types.ReplyKeyboardRemove())
    await NotificationState.get_text.set()


@dp.message_handler(IsPrivate(), state=NotificationState.get_text, content_types=types.ContentType.TEXT)
async def check_text_for_notification_handler(message: types.Message, state: FSMContext):
    notification_message = message.html_text
    await state.update_data(notification_message=notification_message)
    await message.answer("Rasm yuborasizmi?", reply_markup=yes_or_no_markup())
    await NotificationState.is_picture.set()


@dp.message_handler(IsPrivate(), state=NotificationState.get_text)
async def invalid_text_handler(message: types.Message):
    await message.answer("❌ Iltimos, faqat matn yuboring. Rasm, video yoki boshqa fayllar qabul qilinmaydi.")


@dp.message_handler(
    IsPrivate(),
    content_types=[
        types.ContentType.DOCUMENT,
        types.ContentType.VIDEO,
        types.ContentType.AUDIO
    ],
    state=NotificationState.get_text)
async def reject_document_handler(message: types.Message):
    await message.answer("❌ Iltimos, faqatgina matn yuboring. Boshqa formatlar qabul qilinmaydi.")


@dp.message_handler(IsPrivate(), state=NotificationState.is_picture)
async def check_picture_for_notification_handler(message: types.Message, state: FSMContext):
    text = message.text.lower()
    if text in [_("ha"), "ha"]:
        await message.answer("Rasmni yuboring.", reply_markup=types.ReplyKeyboardRemove())
        await NotificationState.get_picture.set()
    elif text in [_("yo'q"), "yo'q"]:
        data = await state.get_data()
        notification_message = data.get("notification_message")

        await message.answer(f"📢 *Siz yubormoqchi bo'lgan habar:*\n\n{notification_message}", parse_mode="HTML")
        await message.answer("Habar tasdiqlansinmi?", reply_markup=confirm_markup())
        await NotificationState.confirm_text.set()
    else:
        await message.answer("Iltimos, faqat 'Ha' yoki 'Yo'q' yozing.", reply_markup=yes_or_no_markup())
        return


@dp.message_handler(IsPrivate(), content_types=types.ContentType.PHOTO, state=NotificationState.get_picture)
async def check_picture_for_notification_handler(message: types.Message, state: FSMContext):
    photo = message.photo[-1].file_id
    await state.update_data(photo=photo)

    data = await state.get_data()
    notification_message = data.get("notification_message")

    await message.answer_photo(photo=photo, caption=f"📢 *Siz yubormoqchi bo'lgan habar:*\n\n{notification_message}", parse_mode="HTML")
    await message.answer("Habar tasdiqlansinmi?", reply_markup=confirm_markup())
    await NotificationState.confirm_text.set()


@dp.message_handler(IsPrivate(), state=NotificationState.get_picture)
async def invalid_picture_handler(message: types.Message):
    if not message.photo:
        await message.answer("❌ Iltimos, faqatgina rasm yuboring.")
        return


@dp.message_handler(
    IsPrivate(),
    content_types=[
        types.ContentType.DOCUMENT,
        types.ContentType.VIDEO,
        types.ContentType.AUDIO
    ],
    state=NotificationState.get_picture)
async def reject_invalid_content_handler(message: types.Message):
    await message.answer("❌ Iltimos, faqatgina rasm yuboring. Boshqa formatlar qabul qilinmaydi.")


@dp.message_handler(IsPrivate(), state=NotificationState.confirm_text)
async def confirm_and_send_notification_handler(message: types.Message, state: FSMContext):
    from tgbot.tasks import send_notification_with_celery, send_notification

    data = await state.get_data()
    notification_message = data.get("notification_message")
    photo = data.get("photo", None)
    if message.text.lower() != _("tasdiqlash"):
        await message.answer(_("Bekor qilindi."), reply_markup=main_markup())
        return await state.finish()

    users = TelegramProfile.objects.filter(is_blocked=False, is_registered=True)

    for user in users:
        send_notification_with_celery.delay(user.telegram_id, notification_message, photo),

    await message.answer(f"Habar {users.count()} foydalanuvchiga yuborildi.", reply_markup=main_markup())
    await state.finish()


@dp.message_handler(IsPrivate(), Text("✅ Ro'yhatdan o'tganlar"))
async def registered_lists(message: types.Message):
    reg_users = TelegramProfile.objects.filter(is_registered=True).order_by('id')
    reg_users_count = reg_users.count()

    response = f"Ro'yhatdan o'tgan userlar soni: {reg_users_count}\n"
    response += "-----------------------------------------------\n"
    response += "ID  |  User\n"
    response += "-----------------------------------------------\n"

    for user in reg_users:
        user_id = user.telegram_id
        if user.full_name:
            mention = hlink(user.full_name, f"tg://user?id={user_id}")
        else:
            mention = "Ism qo'ymagan"
        response += f"{user.id}  |  {mention}\n"

    await message.answer(response, parse_mode="HTML")


@dp.message_handler(IsPrivate(), Text("❌ Ro'yhatdan o'tmaganlar"))
async def unregistered_lists(message: types.Message):
    unreg_users = TelegramProfile.objects.filter(is_registered=False).order_by('id')
    unreg_users_count = unreg_users.count()

    response = f"Ro'yhatdan o'tmagan userlar soni: {unreg_users_count}\n"
    response += "-----------------------------------------------\n"
    response += "ID  |  User\n"
    response += "-----------------------------------------------\n"

    for user in unreg_users:
        user_id = user.telegram_id
        if user.full_name:
            mention = hlink(user.full_name, f"tg://user?id={user_id}")
        elif user.username:
            mention = hlink("@" + user.username, f"tg://user?id={user_id}")
        else:
            mention = hlink("Ism qo'yilmagan", f"tg://user?id={user_id}")

        response += f"{user.id}  |  {mention}\n"

    await message.answer(response, parse_mode="HTML")


USERS_PER_PAGE = 50


def _users_page_markup(page: int, total_pages: int, page_users):
    """Inline kb: per-user 'detail' buttons + page navigation."""
    kb = InlineKeyboardMarkup(row_width=2)
    for u in page_users:
        flag = "✅" if u.is_registered else "🚫"
        label = u.full_name or (("@" + u.username) if u.username else "Ism yo'q")
        if len(label) > 30:
            label = label[:28] + "…"
        kb.insert(
            InlineKeyboardButton(
                text=f"{flag} {u.id} · {label}",
                callback_data=f"adm_userd:{u.id}",
            )
        )
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"adm_userp:{page - 1}"
        ))
    nav.append(InlineKeyboardButton(
        text=f"{page}/{total_pages}", callback_data="noop"
    ))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            text="➡️", callback_data=f"adm_userp:{page + 1}"
        ))
    if nav:
        kb.row(*nav)
    return kb


def _build_users_overview(page: int):
    """Returns (text, markup) for the all-users overview page."""
    qs = TelegramProfile.objects.all().order_by("id")
    total = qs.count()
    registered = qs.filter(is_registered=True).count()
    unregistered = total - registered
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(1, min(page, total_pages))

    offset = (page - 1) * USERS_PER_PAGE
    page_users = list(qs[offset:offset + USERS_PER_PAGE])

    text = (
        "👨‍👩‍👦‍👦 <b>Barcha foydalanuvchilar</b>\n\n"
        f"📊 Jami: <b>{total}</b>\n"
        f"✅ Ro'yxatdan to'liq o'tgan: <b>{registered}</b>\n"
        f"🚫 Ro'yxatdan to'liq o'tmagan: <b>{unregistered}</b>\n\n"
        f"📄 Sahifa: <b>{page}/{total_pages}</b> · {USERS_PER_PAGE} tadan\n\n"
        "<i>Tugmalar:</i>\n"
        "Foydalanuvchini bosing — batafsil ma'lumot ko'rinadi\n"
        "✅ ro'yxatdan o'tgan · 🚫 o'tmagan"
    )
    markup = _users_page_markup(page, total_pages, page_users)
    return text, markup


def _format_books_section(user) -> str:
    """Finished + in-progress book lists with titles, for the admin detail card.
    Audio books are flagged; long lists are capped with a '+N more' tail."""
    from django.db.models import F
    from django.utils.html import escape

    CAP = 20

    finished = list(
        BooksToRead.objects.filter(
            user=user, current_page__gte=F("total_pages"), total_pages__gt=0
        ).order_by("title").values("title", "is_audio")
    )
    in_progress = list(
        BooksToRead.objects.filter(
            user=user, current_page__lt=F("total_pages"), total_pages__gt=0
        ).order_by("title").values("title", "current_page", "total_pages", "is_audio")
    )

    def _unit(is_audio):
        return "daq" if is_audio else "bet"

    section = ""
    if finished:
        lines = []
        for b in finished[:CAP]:
            tag = " 🎧" if b["is_audio"] else ""
            lines.append(f"  ✅ {escape(b['title'])}{tag}")
        if len(finished) > CAP:
            lines.append(f"  …va yana {len(finished) - CAP} ta")
        section += (
            f"\n\n📖 <b>Tugatgan kitoblar ({len(finished)}):</b>\n" + "\n".join(lines)
        )
    if in_progress:
        lines = []
        for b in in_progress[:CAP]:
            tag = " 🎧" if b["is_audio"] else ""
            lines.append(
                f"  📕 {escape(b['title'])}{tag} — {b['current_page']}/{b['total_pages']} {_unit(b['is_audio'])}"
            )
        if len(in_progress) > CAP:
            lines.append(f"  …va yana {len(in_progress) - CAP} ta")
        section += (
            f"\n\n📕 <b>Tugatilmagan kitoblar ({len(in_progress)}):</b>\n" + "\n".join(lines)
        )
    if not finished and not in_progress:
        section += "\n\n📚 <i>Kitoblar ro'yxati bo'sh.</i>"
    return section


_BOT_USERNAME = None


async def _ensure_bot_username():
    """Cache the bot's @username once — needed to build t.me deep links inside
    the (sync) profile-card text builder."""
    global _BOT_USERNAME
    if _BOT_USERNAME is None:
        try:
            from tgbot.bot.loader import bot
            _BOT_USERNAME = (await bot.get_me()).username or ""
        except Exception:
            _BOT_USERNAME = ""
    return _BOT_USERNAME


def _build_user_detail(user_id: int) -> str:
    """Returns full HTML detail for a single TelegramProfile (admin view)."""
    from django.db.models import Count, Avg, Sum, F
    from django.db.models.functions import ExtractWeekDay, ExtractHour, TruncDate

    user = TelegramProfile.objects.select_related('region').filter(id=user_id).first()
    if not user:
        return "❌ Foydalanuvchi topilmadi."

    total_pages = (
        BookReport.objects.filter(user=user).aggregate(s=Sum("pages_read"))["s"] or 0
    )
    avg_pages = (
        BookReport.objects.filter(user=user).aggregate(a=Avg("pages_read"))["a"] or 0
    )
    completed_books = BooksToRead.objects.filter(
        user=user, current_page__gte=F("total_pages"), total_pages__gt=0
    ).count()
    in_progress_books = BooksToRead.objects.filter(
        user=user, current_page__lt=F("total_pages"), total_pages__gt=0
    ).count()

    distinct_days = (
        ConfirmationReport.objects.filter(user=user)
        .annotate(_d=TruncDate("date"))
        .values("_d").distinct().count()
    )
    reports_count = ConfirmationReport.objects.filter(user=user).count()

    weekday_stats = list(
        BookReport.objects.filter(user=user)
        .annotate(weekday=ExtractWeekDay("created_at"))
        .values("weekday").annotate(c=Count("id")).order_by("-c")
    )
    hour_stats = list(
        BookReport.objects.filter(user=user)
        .annotate(hour=ExtractHour("created_at"))
        .values("hour").annotate(c=Count("id")).order_by("-c")
    )

    weekday_map = {
        1: "Yakshanba", 2: "Dushanba", 3: "Seshanba", 4: "Chorshanba",
        5: "Payshanba", 6: "Juma", 7: "Shanba",
    }
    most_active_day = (
        weekday_map.get(weekday_stats[0]["weekday"], "—") if weekday_stats else "—"
    )
    if hour_stats:
        h = hour_stats[0]["hour"]
        active_hour = f"{h:02d}:00–{h+1:02d}:00"
    else:
        active_hour = "—"

    achievements = list(
        UserAchievement.objects.filter(user=user).values_list("code", flat=True)
    )
    ach_count = len(achievements)

    region_name = user.region.name if user.region else "—"
    gender_label = {"male": "Erkak", "female": "Ayol"}.get(user.gender or "", "—")
    age_label = {
        "u18": "&lt;18", "18_25": "18–25", "26_35": "26–35", "36p": "36+",
    }.get(user.age_range or "", "—")

    from tgbot.models import Payment as _Payment
    prem_payment = (
        _Payment.objects
        .filter(user=user, status="paid", end_date__gte=timezone.localdate())
        .order_by("-end_date").first()
    )
    premium_line = (
        f"💎 <b>Premium:</b> faol — {prem_payment.end_date.strftime('%d.%m.%Y')} gacha"
        if prem_payment else "💎 <b>Premium:</b> yo'q"
    )

    from django.utils.html import escape as _esc
    username_str = f"@{user.username}" if user.username else "—"
    full_name = user.full_name or "—"
    # Tapping the name (or the explicit link) opens the user's Telegram profile
    # — works even when they have no @username, since it goes by numeric id.
    name_link = f'<a href="tg://user?id={user.telegram_id}">{_esc(full_name)}</a>'
    # Prominent one-tap actions right under the name: "Yozish" (opens the owner
    # message-relay via a deep link — reliable, no @username needed) and
    # "Profil" (native Telegram profile).
    _profile_a = f'<a href="tg://user?id={user.telegram_id}">🔗 Profil</a>'
    if _BOT_USERNAME:
        _write_a = f'<a href="https://t.me/{_BOT_USERNAME}?start=msg_{user.telegram_id}">✍️ YOZISH</a>'
        action_line = f"{_write_a}   ·   {_profile_a}\n"
    else:
        action_line = f"{_profile_a}\n"
    reg_status = "✅ Ro'yxatdan to'liq o'tgan" if user.is_registered else "🚫 Tugatmagan"
    blocked = "🚫 Bloklangan" if user.is_blocked else ""
    admin_flag = "👑 Admin" if user.is_admin else ""
    days_since_join = (timezone.now() - user.created_at).days if user.created_at else 0

    ach_text = ""
    if achievements:
        from tgbot.services.achievements import find_achievement
        items = []
        for code in achievements:
            ach = find_achievement(code)
            if ach:
                items.append(f"{ach['emoji']} {ach['title_uz']}")
        ach_text = "\n\n🏆 <b>Yutuqlar (" + str(ach_count) + "):</b>\n" + "\n".join(items)

    return (
        f"👤 <b>{name_link}</b>\n"
        f"{action_line}"
        f"🆔 <code>{user.telegram_id}</code> · DB id: {user.id}\n"
        f"📱 {username_str}\n"
        f"🌐 Til: {(user.language or '—').upper()}\n"
        f"🚻 Jins: {gender_label}\n"
        f"🗺 Hudud: {region_name}\n"
        f"🎂 Yosh: {age_label}\n"
        f"📅 A'zo bo'lgan: {days_since_join} kun oldin\n"
        f"{reg_status}{(' · ' + blocked) if blocked else ''}{(' · ' + admin_flag) if admin_flag else ''}\n\n"
        f"🪙 <b>Kitobcha balansi:</b> {int(user.ball or 0)}\n"
        f"{premium_line}\n"
        f"📚 Hisobotlar: <b>{reports_count}</b>\n"
        f"📄 Jami betlar: <b>{total_pages}</b>\n"
        f"⚡️ O'rtacha: <b>{int(avg_pages)} bet/hisobot</b>\n"
        f"📅 Faol kunlar (uniq): <b>{distinct_days}</b>\n"
        f"📖 Tugatgan kitoblar: <b>{completed_books}</b>\n"
        f"📕 O'qilayotgan: <b>{in_progress_books}</b>\n"
        f"🗓 Eng faol kun: <b>{most_active_day}</b>\n"
        f"⏰ Eng faol vaqt: <b>{active_hour}</b>"
        f"{_format_books_section(user)}"
        f"{ach_text}"
    )


USERS_LIST_PER_PAGE = 100


def _active_users_qs():
    """Users shown in the admin list: everyone who hasn't blocked the bot.
    Registered/active users come first (then unregistered), with a stable id
    tiebreak so ordinal numbers stay reproducible across pages."""
    return TelegramProfile.objects.filter(is_blocked=False).order_by("-is_registered", "id")


def _user_by_ordinal(n: int):
    """Resolve the 1-based ordinal shown in the list back to a TelegramProfile."""
    if n < 1:
        return None
    rows = list(_active_users_qs()[n - 1:n])
    return rows[0] if rows else None


def _build_users_numbered(page: int):
    """(text, markup, total_pages) for the numbered, blocked-excluded users list.
    Ordinals are global: page 2 continues from where page 1 stopped."""
    from tgbot.models import Payment
    from django.utils.html import escape

    qs = _active_users_qs()
    total = qs.count()
    total_pages = max(1, (total + USERS_LIST_PER_PAGE - 1) // USERS_LIST_PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * USERS_LIST_PER_PAGE
    page_users = list(qs[offset:offset + USERS_LIST_PER_PAGE])

    page_ids = [u.id for u in page_users]
    prem_ids = set(
        Payment.objects.filter(
            user_id__in=page_ids, status="paid", end_date__gte=timezone.localdate()
        ).values_list("user_id", flat=True)
    )

    # Render each user as a compact cell, then pack two cells per line so a
    # 100-user page stays scrollable. Registered users come first (queryset
    # order); unregistered (🚫) land at the end.
    def _cell(i, u):
        name = escape(u.full_name or (("@" + u.username) if u.username else "Ism yo'q"))
        if len(name) > 18:
            name = name[:17] + "…"
        badges = ""
        if u.id in prem_ids:
            badges += "💎"
        if u.is_admin:
            badges += "👑"
        if not u.is_registered:
            badges += "🚫"
        return f"<b>{i}.</b> {name}{(' ' + badges) if badges else ''}"

    cells = [_cell(offset + idx + 1, u) for idx, u in enumerate(page_users)]
    body = []
    for j in range(0, len(cells), 2):
        pair = cells[j:j + 2]
        body.append("   ".join(pair))

    text = (
        "👨‍👩‍👦‍👦 <b>Foydalanuvchilar ro'yxati</b>\n"
        f"📊 Jami (bloklanmagan): <b>{total}</b> · 📄 Sahifa <b>{page}/{total_pages}</b>\n"
        "<i>Avval faol/ro'yxatdan o'tganlar · 🚫 o'tmaganlar oxirida</i>\n\n"
        + "\n".join(body)
        + "\n\n🔢 Ko'rish: <b>raqamini</b> yuboring yoki <code>/u 661</code>"
          "\n🔍 Qidirish: <code>/find ism</code>"
    )

    kb = InlineKeyboardMarkup(row_width=3)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"adm_ulist:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"adm_ulist:{page + 1}"))
    kb.row(*nav)
    return text, kb, total_pages


@dp.message_handler(IsPrivate(), Text(contains="Foydalanuvchilar ro'yxati"))
async def all_users(message: types.Message, state: FSMContext = None):
    text, markup, _tp = _build_users_numbered(page=1)
    if state is not None:
        await state.set_state(AdminUserBrowse.listing.state)
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("adm_ulist:"), state="*")
async def adm_users_list_page(call: types.CallbackQuery, state: FSMContext):
    actor = await aget_user(call.from_user.id)
    if not (actor and actor.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    page = int(call.data.split(":", 1)[1])
    text, markup, _tp = await sync_to_async(_build_users_numbered)(page)
    await state.set_state(AdminUserBrowse.listing.state)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=markup)
    await call.answer()


@dp.message_handler(IsPrivate(), state=AdminUserBrowse.listing, regexp=r"^\s*\d+\s*$")
async def admin_userlist_pick(message: types.Message, state: FSMContext):
    actor = await aget_user(message.from_user.id)
    if not (actor and actor.is_admin):
        await state.finish()
        return
    n = int(message.text.strip())
    target = await sync_to_async(_user_by_ordinal)(n)
    if not target:
        await message.answer("❌ Bunday raqamli foydalanuvchi yo'q. Boshqa raqam yuboring.")
        return
    text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(target.id)
    await message.answer(
        text, parse_mode="HTML",
        reply_markup=_user_detail_markup(target_user, is_premium),
    )


@dp.message_handler(IsPrivate(), state=AdminUserBrowse.listing)
async def admin_userlist_text(message: types.Message, state: FSMContext):
    # In the list, a non-numeric text is treated as a search query (the digit
    # handler above caught the numbers). Stays in listing mode so the admin can
    # keep browsing/searching freely.
    actor = await aget_user(message.from_user.id)
    if not (actor and actor.is_admin):
        await state.finish()
        return
    await _do_user_search(message, (message.text or "").strip())


def _search_users(query: str, limit: int = 20):
    """Find users by name / username / phone / id.

    Numeric queries match telegram_id / db-id / phone exactly first. Name
    queries use a fuzzy, transliteration-aware match: the query and every
    stored name are normalized (Cyrillic→Latin, apostrophes stripped) so
    "Maryam" finds "Марям"/"Maryamoy"/"Mariam". Results are ranked by closeness
    and the nearest ones are always returned even on typos. Blocked users are
    included so admins can find and unblock them."""
    from django.db.models import Q
    import difflib
    from tgbot.models import normalize_uzbek_text

    q = (query or "").strip()
    if not q:
        return []

    digits = q.lstrip("+").replace(" ", "").replace("-", "")
    if digits.isdigit():
        exact = list(
            TelegramProfile.objects.filter(
                Q(telegram_id=int(digits)) | Q(id=int(digits))
            )[:limit]
        )
        if exact:
            return exact
        phone_hits = list(
            TelegramProfile.objects.filter(phone_number__icontains=digits)[:limit]
        )
        if phone_hits:
            return phone_hits

    # 1) Reliable DB substring match (case-insensitive) — always catches the
    #    obvious hits, e.g. "maryam" → "Maryam", "Maryamoy", "Maryam Karimova".
    db_hits = list(
        TelegramProfile.objects.filter(
            Q(full_name__icontains=q)
            | Q(username__icontains=q)
            | Q(phone_number__icontains=q)
        ).order_by("-is_registered", "id")[:limit]
    )
    seen = {u.id for u in db_hits}

    # 2) Fuzzy / transliteration pass for typos and Cyrillic spellings that a
    #    raw substring can't catch (e.g. "maryam" → "Марям", "Mariam").
    norm_q = normalize_uzbek_text(q)
    scored = []  # (score, id)
    if norm_q and len(db_hits) < limit:
        rows = (
            TelegramProfile.objects.exclude(id__in=seen)
            .values_list("id", "full_name", "username")
        )
        for uid, full_name, username in rows.iterator():
            norm_name = normalize_uzbek_text(full_name or username or "")
            if not norm_name:
                continue
            tokens = norm_name.split()
            if (norm_q == norm_name or norm_q in tokens
                    or any(t.startswith(norm_q) for t in tokens)
                    or norm_name.startswith(norm_q)):
                score = 1.0
            elif len(norm_q) >= 3 and norm_q in norm_name:
                score = 0.9
            else:
                best = difflib.SequenceMatcher(None, norm_q, norm_name).ratio()
                for tok in tokens:
                    best = max(best, difflib.SequenceMatcher(None, norm_q, tok).ratio())
                if best < 0.6:           # near-similar yes, junk no
                    continue
                score = best
            scored.append((score, uid))
        scored.sort(key=lambda x: x[0], reverse=True)

    remaining = max(0, limit - len(db_hits))
    fuzzy_ids = [uid for _s, uid in scored[:remaining]]
    by_id = {u.id: u for u in TelegramProfile.objects.filter(id__in=fuzzy_ids)}
    fuzzy_users = [by_id[i] for i in fuzzy_ids if i in by_id]
    return db_hits + fuzzy_users


async def _do_user_search(message: types.Message, query: str):
    """Run a user search and render results. Shared by the list-mode text path,
    the searching state, and the /find command — so search works no matter how
    the admin got here (and even if FSM state was lost)."""
    from django.utils.html import escape as _escape

    if not query:
        await message.answer("Ism, username, telefon yoki ID yuboring.")
        return

    results = await sync_to_async(_search_users)(query)

    if not results:
        await message.answer(f"🔍 «{_escape(query)}» bo'yicha hech narsa topilmadi.")
        return

    if len(results) == 1:
        u = results[0]
        text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(u.id)
        await message.answer(
            text, parse_mode="HTML",
            reply_markup=_user_detail_markup(target_user, is_premium),
        )
        return

    kb = InlineKeyboardMarkup(row_width=1)
    lines = [f"🔍 «{_escape(query)}» — <b>{len(results)}</b> ta natija:\n"]
    for u in results:
        name = u.full_name or (("@" + u.username) if u.username else "Ism yo'q")
        flag = "🚫" if u.is_blocked else ("✅" if u.is_registered else "·")
        lines.append(f"{flag} {_escape(name)} — <code>{u.telegram_id}</code>")
        label = f"{name}"[:40]
        kb.add(InlineKeyboardButton(f"👤 {label}", callback_data=f"adm_userd:{u.id}"))
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@dp.message_handler(IsPrivate(), commands=["find", "qidir"], state="*")
async def admin_find_command(message: types.Message, state: FSMContext = None):
    """Bulletproof search that works in ANY state: /find <name|phone|id>."""
    actor = await aget_user(message.from_user.id)
    if not (actor and actor.is_admin):
        await message.answer("Siz admin emassiz!")
        return
    await _do_user_search(message, (message.get_args() or "").strip())


@dp.message_handler(IsPrivate(), commands=["u", "user"], state="*")
async def admin_user_by_number_command(message: types.Message, state: FSMContext = None):
    """Bulletproof view-by-number that works in ANY state: /u <ro'yxat raqami>."""
    actor = await aget_user(message.from_user.id)
    if not (actor and actor.is_admin):
        await message.answer("Siz admin emassiz!")
        return
    arg = (message.get_args() or "").strip()
    if not arg.isdigit():
        await message.answer("Foydalanish: <code>/u 661</code> (ro'yxatdagi tartib raqami).",
                             parse_mode="HTML")
        return
    target = await sync_to_async(_user_by_ordinal)(int(arg))
    if not target:
        await message.answer("❌ Bunday raqamli foydalanuvchi yo'q.")
        return
    text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(target.id)
    await message.answer(text, parse_mode="HTML",
                         reply_markup=_user_detail_markup(target_user, is_premium))


@dp.message_handler(IsPrivate(), state=AdminUserBrowse.searching)
async def admin_user_search_query(message: types.Message, state: FSMContext):
    actor = await aget_user(message.from_user.id)
    if not (actor and actor.is_admin):
        await state.finish()
        return
    # Switch to listing mode so further plain numbers/names keep working even if
    # this message landed on a worker that had lost the 'searching' state.
    await state.set_state(AdminUserBrowse.listing.state)
    await _do_user_search(message, (message.text or "").strip())


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("adm_userp:"), state="*")
async def adm_user_page(call: types.CallbackQuery):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    page = int(call.data.split(":", 1)[1])
    text, markup = _build_users_overview(page=page)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=markup)
    await call.answer()


def _is_user_premium(user) -> bool:
    """True if the user has an active paid subscription today."""
    from tgbot.models import Payment
    return Payment.objects.filter(
        user=user, status="paid", end_date__gte=timezone.localdate()
    ).exists()


def _user_detail_markup(target_user, is_premium: bool) -> InlineKeyboardMarkup:
    """Shared admin detail-card keyboard: contact, premium toggle, block toggle,
    and back. Used by the detail view and both toggle handlers so the buttons
    never diverge."""
    kb = InlineKeyboardMarkup(row_width=1)
    if target_user and target_user.telegram_id:
        kb.add(InlineKeyboardButton(
            "✉️ Xabar yozish (Loyiha asoschisidan)",
            callback_data=f"owner_reply:{target_user.telegram_id}",
        ))
        # Premium grant / revoke — admin-only. Grant buttons always show, even
        # if the user is already Premium: a grant here EXTENDS their current
        # end date rather than replacing it (2 days left + 30 = 32 days).
        kb.row(
            InlineKeyboardButton(
                "💎 +1 oy",
                callback_data=f"adm_prem_toggle:{target_user.id}:1:30",
            ),
            InlineKeyboardButton(
                "💎 +3 oy",
                callback_data=f"adm_prem_toggle:{target_user.id}:1:90",
            ),
        )
        if is_premium:
            kb.add(InlineKeyboardButton(
                "❌ Premiumni o'chirish",
                callback_data=f"adm_prem_toggle:{target_user.id}:0",
            ))
        # Block / Unblock toggle — admin-only control over user access.
        if target_user.is_blocked:
            kb.add(InlineKeyboardButton(
                "✅ Blokdan chiqarish",
                callback_data=f"adm_block_toggle:{target_user.id}:0",
            ))
        else:
            kb.add(InlineKeyboardButton(
                "🚫 Bloklash",
                callback_data=f"adm_block_toggle:{target_user.id}:1",
            ))
    kb.add(InlineKeyboardButton(
        "⬅️ Ro'yxatga qaytish", callback_data="adm_ulist:1",
    ))
    return kb


def _detail_text_user_premium(target_id: int):
    """Sync helper: returns (text, target_user, is_premium) in one DB round."""
    text = _build_user_detail(target_id)
    target_user = TelegramProfile.objects.filter(id=target_id).first()
    is_premium = _is_user_premium(target_user) if target_user else False
    return text, target_user, is_premium


async def open_profile_card_by_tid(message, telegram_id: int):
    """Render the admin profile card for a user by telegram_id and send it.
    Used by the /start prof_<telegram_id> deep link so any name that links to
    this profile opens the full card (with the message-relay button)."""
    def _fetch(tid):
        u = TelegramProfile.objects.filter(telegram_id=tid).first()
        if not u:
            return None
        return _build_user_detail(u.id), u, _is_user_premium(u)

    await _ensure_bot_username()
    data = await sync_to_async(_fetch)(telegram_id)
    if not data:
        await message.answer("❌ Bunday foydalanuvchi topilmadi.")
        return
    text, target_user, is_premium = data
    await message.answer(
        text, parse_mode="HTML",
        reply_markup=_user_detail_markup(target_user, is_premium),
        disable_web_page_preview=True,
    )


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("adm_userd:"), state="*")
async def adm_user_detail(call: types.CallbackQuery):
    await call.answer()
    try:
        actor = await aget_user(call.from_user.id)
        if not (actor and actor.is_admin):
            await call.message.answer("⛔ Admin emas")
            return
        raw = call.data.split(":", 1)[1]
        target_id = int(raw)
        await _ensure_bot_username()
        text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(target_id)
        back_kb = _user_detail_markup(target_user, is_premium)
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
        except Exception:
            await call.message.answer(text, parse_mode="HTML", reply_markup=back_kb)
    except Exception as e:
        import traceback
        print(f"[adm_user_detail] CRASH id={call.data}: {e}\n{traceback.format_exc()}")
        await call.message.answer(f"❌ Xatolik:\n<code>{e}</code>", parse_mode="HTML")


@dp.callback_query_handler(
    IsPrivate(),
    lambda c: c.data and c.data.startswith("adm_block_toggle:"),
    state="*",
)
async def adm_block_toggle(call: types.CallbackQuery):
    """Toggle a user's is_blocked flag. Notifies the target so they aren't
    silently locked out, and re-renders the detail card."""
    actor = await aget_user(call.from_user.id)
    if not (actor and actor.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer()
        return
    target_id = int(parts[1])
    block = parts[2] == "1"

    target_user = await sync_to_async(
        TelegramProfile.objects.filter(id=target_id).first
    )()
    if not target_user:
        await call.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    if target_user.is_admin and block:
        await call.answer("Adminni bloklash mumkin emas.", show_alert=True)
        return

    await sync_to_async(
        TelegramProfile.objects.filter(id=target_id).update
    )(is_blocked=block)

    # Inform the affected user so they understand why the bot stopped responding.
    try:
        if block:
            await bot.send_message(
                target_user.telegram_id,
                "🚫 <b>Sizning hisobingiz cheklangan.</b>\n\n"
                "Bot funksiyalaridan foydalana olmaysiz.\n"
                "Sabab yoki blokdan chiqarish bo'yicha "
                "<b>📞 Admin bilan bog'lanish</b> tugmasi orqali murojaat qilishingiz mumkin.",
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                target_user.telegram_id,
                "✅ <b>Sizning hisobingiz qayta tiklandi.</b>\n\n"
                "Botning barcha funksiyalari yana ochildi. Marhamat!",
                parse_mode="HTML",
            )
    except Exception as e:
        print(f"block-toggle notify failed for {target_user.telegram_id}: {e}")

    await call.answer(
        "🚫 Bloklandi" if block else "✅ Blokdan chiqarildi",
        show_alert=False,
    )

    # Re-render the detail card so the button flips immediately.
    text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(target_id)
    back_kb = _user_detail_markup(target_user, is_premium)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
    except Exception:
        pass


@dp.callback_query_handler(
    IsPrivate(),
    lambda c: c.data and c.data.startswith("adm_prem_toggle:"),
    state="*",
)
async def adm_prem_toggle(call: types.CallbackQuery):
    """Grant or revoke Premium for any user from the admin user-detail card.
    Grant = a paid Payment for the chosen number of days (extends an existing
    active one instead of resetting it). Revoke = expire every active paid
    Payment. Notifies the target and re-renders."""
    actor = await aget_user(call.from_user.id)
    if not (actor and actor.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer()
        return
    target_id = int(parts[1])
    grant = parts[2] == "1"
    days = int(parts[3]) if grant and len(parts) > 3 else 30

    @sync_to_async
    def _apply():
        from datetime import timedelta
        from tgbot.models import Payment
        target = TelegramProfile.objects.filter(id=target_id).first()
        if not target:
            return None, None
        today = timezone.localdate()
        if grant:
            payment = Payment.grant_or_extend(target, days, amount=0)
            return target, payment.end_date
        else:
            Payment.objects.filter(
                user=target, status="paid", end_date__gte=today
            ).update(end_date=today - timedelta(days=1))
            return target, None

    target_user, new_until = await _apply()
    if not target_user:
        await call.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    # Notify the affected user.
    try:
        if grant:
            await bot.send_message(
                target_user.telegram_id,
                "💎 <b>Sizga Premium obuna faollashtirildi!</b>\n\n"
                f"📅 Amal qilish muddati: <b>{new_until.strftime('%d.%m.%Y')}</b> gacha\n\n"
                "Barcha Premium imtiyozlardan bahramand bo'ling! 🔥",
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                target_user.telegram_id,
                "💎 <b>Premium obunangiz to'xtatildi.</b>\n\n"
                "Qayta faollashtirish uchun «💎 Premium obuna» bo'limiga o'ting.",
                parse_mode="HTML",
            )
    except Exception as e:
        print(f"prem-toggle notify failed for {target_user.telegram_id}: {e}")

    await call.answer(
        "💎 Premium berildi (30 kun)" if grant else "❌ Premium o'chirildi",
        show_alert=False,
    )

    # Re-render the detail card so the button flips immediately.
    text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(target_id)
    back_kb = _user_detail_markup(target_user, is_premium)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
    except Exception:
        pass


@dp.callback_query_handler(IsPrivate(), lambda c: c.data == "noop", state="*")
async def adm_noop(call: types.CallbackQuery):
    await call.answer()


@dp.message_handler(IsPrivate(), Text("📊 Statistikani ko'rish"))
async def show_global_statistics(message: types.Message):
    from django.db.models import Sum, Count, F
    from django.db.models.functions import TruncDate
    from django.utils import timezone
    from tgbot.models import ConfirmationReport, BooksToRead

    today = timezone.localdate()

    total_users = TelegramProfile.objects.count()
    registered = TelegramProfile.objects.filter(is_registered=True).count()
    active_today_users = (
        ConfirmationReport.objects
        .annotate(_d=TruncDate("date"))
        .filter(_d=today)
        .values("user").distinct().count()
    )
    total_pages_today = (
        ConfirmationReport.objects
        .annotate(_d=TruncDate("date"))
        .filter(_d=today)
        .aggregate(s=Sum("pages_read"))["s"] or 0
    )
    total_pages_alltime = (
        ConfirmationReport.objects.aggregate(s=Sum("pages_read"))["s"] or 0
    )
    total_book_reports = ConfirmationReport.objects.count()

    in_progress = BooksToRead.objects.filter(
        current_page__lt=F("total_pages"), total_pages__gt=0
    )
    titles = list(
        in_progress.values_list("title", flat=True).distinct()[:30]
    )
    in_progress_count = in_progress.count()

    lines = [
        "📊 <b>Umumiy statistika</b>",
        "",
        f"👥 Foydalanuvchilar: <b>{total_users}</b> (ro'yxatdan o'tgan: {registered})",
        f"📖 Bugun hisobot yuborgan: <b>{active_today_users}</b>",
        f"📄 Bugun o'qilgan jami betlar: <b>{total_pages_today}</b>",
        f"📚 Jami hisobotlar: <b>{total_book_reports}</b>",
        f"📈 Hammavaqt o'qilgan jami betlar: <b>{total_pages_alltime}</b>",
        f"📕 Hozir o'qilayotgan kitoblar: <b>{in_progress_count}</b>",
    ]
    if titles:
        lines.append("")
        lines.append("<b>Kitoblar ro'yxati:</b>")
        for t in titles:
            lines.append(f"  • {t}")
        if in_progress_count > len(titles):
            lines.append(f"  … va yana {in_progress_count - len(titles)} ta")

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message_handler(IsPrivate(), Text("👤 Foydalanuvchi izlash"))
async def get_book_info_start(message: types.Message):
    await message.answer("Iltimos, foydalanuvchi ID'sini kiriting:", reply_markup=types.ReplyKeyboardRemove())
    await StatisticState.input_user_id.set()


@dp.message_handler(IsPrivate(), state=StatisticState.input_user_id)
async def input_user_id(message: types.Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("Iltimos, faqatgina foydalanuvchi ID'sini kiriting:")
        await StatisticState.input_user_id.set()
        return
    user_id = message.text.strip()

    try:
        user = TelegramProfile.objects.get(id=user_id)
        user_topic_id = user.group.title if user.group else None
        user_tg_id = user.telegram_id
        book_report = BookReport.objects.filter(user=user).first()

        if book_report:
            touch_user = hlink(user.full_name, f"tg://user?id={user_tg_id}")
            response = (

                f"Foydalanuvchi: {touch_user}\n"
                f"O'qilgan kitobi: {book_report.book}\n"
                f"Nechi kunda o'qigani: {book_report.reading_day}\n"
                f"O'qilgan sahifalar soni: {book_report.pages_read}\n"
                f"Guruhi: {user_topic_id}"
            )
        else:
            if user.full_name:
                mention = hlink(user.full_name, f"tg://user?id={user_tg_id}")
            elif user.username:
                mention = hlink("@" + user.username, f"tg://user?id={user_tg_id}")
            else:
                mention = hlink("Ism qo'yilmagan", f"tg://user?id={user_tg_id}")
            response = f"{mention} hech qanday kitob o'qimagan!"

        await message.answer(response)
    except TelegramProfile.DoesNotExist:
        await message.answer("Foydalanuvchi topilmadi. Iltimos, to'g'ri ID kiriting.")

    await state.finish()


# ──────────────────────────────────────────────────────────────────────────
# Inline admin keyboard router. Each callback_data is `admin:<action>`.
# Existing reply-keyboard text handlers are kept as fallback above.
# ──────────────────────────────────────────────────────────────────────────
@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("admin:"),
    state="*",
)
async def admin_inline_router(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    action = call.data.split(":", 1)[1]
    await call.answer()

    # Bypass reply-keyboard. Mutate from_user so any inner permission checks
    # see the actual user.
    msg = call.message
    try:
        msg.from_user = call.from_user
    except Exception:
        pass

    admin_id = call.from_user.id
    if action == "registered":
        await registered_lists(msg)
    elif action == "unregistered":
        await unregistered_lists(msg)
    elif action == "all_users":
        await all_users(msg, state)
    elif action == "user_search":
        await state.set_state(AdminUserBrowse.listing.state)
        await call.message.answer(
            "🔍 <b>Foydalanuvchi qidirish</b>\n\n"
            "Ism, username, telefon yoki ID yuboring — eng yaqin mosliklar chiqadi.\n"
            "Yoki istalgan paytda: <code>/find ism</code>\n"
            "Ro'yxatdan tartib raqamini yuborsangiz — o'sha foydalanuvchi ochiladi.",
            parse_mode="HTML",
        )
    elif action == "stats":
        await show_global_statistics(msg)
    elif action == "notify":
        await send_notification_text_handler(msg)
    elif action == "reminders":
        from tgbot.bot.handlers.users.reminders import reminders_menu
        await reminders_menu(msg, state, _admin_id=admin_id)
    elif action == "poll_new":
        from tgbot.bot.handlers.users.polls_admin import poll_admin_start
        await poll_admin_start(msg, state, _admin_id=admin_id)
    elif action == "poll_results":
        from tgbot.bot.handlers.users.polls_admin import poll_results_list
        await poll_results_list(msg, state, _admin_id=admin_id)
    elif action == "book_quiz":
        # Build one fresh Viktorina round now and broadcast it. Build runs
        # synchronously so the admin gets immediate feedback (incl. the
        # "not enough material" case); the broadcast is fired in the background
        # on THIS process so it doesn't depend on a separate worker deploy.
        import asyncio
        from asgiref.sync import sync_to_async
        from tgbot.services.book_quiz import build_quiz_round
        from tgbot.tasks import _broadcast_quiz_round

        quiz_round = await sync_to_async(build_quiz_round)()
        if not quiz_round:
            await call.message.answer(
                "⚠️ Hozircha yetarli xulosa yo'q — viktorina qurib bo'lmadi.\n"
                "Foydalanuvchilar ko'proq xulosa yuborgach qayta urinib ko'ring."
            )
        else:
            asyncio.get_event_loop().run_in_executor(
                None, lambda: _broadcast_quiz_round(quiz_round)
            )
            await call.message.answer(
                f"✅ Yangi viktorina yuborilmoqda!\n\n"
                f"📖 To'g'ri javob: <b>{quiz_round.correct_title}</b>\n"
                f"<i>Guruhlar va barcha foydalanuvchilarga tarqatilyapti…</i>",
                parse_mode="HTML",
            )
    elif action == "reader_titles":
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(
            "✅ Hammaga e'lon qilish", callback_data="admin:reader_titles_go",
        ))
        await call.message.answer(
            "🏅 <b>Kitobxon nominatsiyalari</b> (oxirgi 30 kun) — 8 ta toifa:\n"
            "🌙 Tungi · 🌅 Saharxez · ☀️ Kunduzgi · 🎧 Audio · ✍️ So'z ustasi · "
            "🤝 Sahiy tabriklovchi · 🎁 Eng ko'p tabriklangan · 🔥 Eng intizomli\n\n"
            "Barcha guruhlar va foydalanuvchilarga yuborilsinmi?",
            parse_mode="HTML",
            reply_markup=kb,
        )
    elif action == "reader_titles_go":
        # Run on THIS (web) process in a background thread rather than dispatching
        # to the celery worker — admin one-off broadcasts shouldn't depend on a
        # separate worker deploy. Fire-and-forget so the handler returns at once.
        import asyncio
        from tgbot.tasks import announce_reader_titles
        asyncio.get_event_loop().run_in_executor(None, announce_reader_titles)
        await call.message.answer(
            "✅ Kitobxon nominatsiyalari e'lon qilinmoqda — barcha guruh va "
            "foydalanuvchilarga yuborilyapti! 🏅"
        )
    elif action == "founder_gift":
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(
            "✅ Ha, hammaga 24h Premium berish", callback_data="admin:founder_gift_go",
        ))
        await call.message.answer(
            "🎁 <b>Loyiha asoschisidan sovg'a</b>\n\n"
            "Barcha ro'yxatdan o'tgan foydalanuvchilarga <b>24 soatlik 💎 Premium</b> "
            "beriladi va hamma joyda (guruhlar + shaxsiy) e'lon qilinadi.\n\n"
            "Davom etamizmi?",
            parse_mode="HTML",
            reply_markup=kb,
        )
    elif action == "founder_gift_go":
        # Run on THIS (web) process in a background thread (see note above).
        import asyncio
        from tgbot.tasks import grant_everyone_premium
        asyncio.get_event_loop().run_in_executor(
            None, lambda: grant_everyone_premium(days=1, announce=True)
        )
        await call.message.answer(
            "✅ Sovg'a ulashilmoqda — barchaga 24 soatlik 💎 Premium berilib, "
            "e'lon qilinyapti! 🎁🔥\n\n"
            "<i>E'lon barcha guruhlar va foydalanuvchilarga yuborilmoqda — "
            "bir-ikki daqiqada yakunlanadi.</i>",
            parse_mode="HTML",
        )
    elif action == "project_survey":
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(
            "✅ Ha, hammaga yuborish", callback_data="admin:project_survey_go",
        ))
        await call.message.answer(
            "📊 <b>Loyihani yaxshilash so'rovnomasi</b>\n\n"
            "5 ta savol (kitobxonlik staji, 3 oylik istaklar, yiliga o'qiladigan "
            "kitoblar soni, takliflar — istalgan formatda, va 1-10 baho). "
            "Qatnashganlarga <b>500 Kitobcha</b> beriladi, har bir javob sizga "
            "shaxsan DM orqali kelib turadi.\n\n"
            "Barcha ro'yxatdan o'tgan foydalanuvchilarga yuborilib, 6 soatga pin "
            "qilinadi. Davom etamizmi?",
            parse_mode="HTML",
            reply_markup=kb,
        )
    elif action == "project_survey_go":
        from tgbot.tasks import broadcast_project_survey
        broadcast_project_survey.delay()
        await call.message.answer(
            "✅ So'rovnoma barcha foydalanuvchilarga yuborilmoqda va 6 soatga pin "
            "qilinadi. Har bir javob sizga shaxsan kelib turadi. 📊"
        )
    elif action == "top_readers":
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📅 Bugun",    callback_data="admin:top_readers:daily"),
            InlineKeyboardButton("📅 3 kun",    callback_data="admin:top_readers:3days"),
            InlineKeyboardButton("📅 Hafta",    callback_data="admin:top_readers:weekly"),
            InlineKeyboardButton("📅 Oy",       callback_data="admin:top_readers:monthly"),
            InlineKeyboardButton("📅 3 oy",     callback_data="admin:top_readers:3monthly"),
            InlineKeyboardButton("📅 Yil",      callback_data="admin:top_readers:yearly"),
        )
        await call.message.answer(
            "📊 Qaysi davr uchun yuborish?",
            reply_markup=kb,
        )
    elif action.startswith("top_readers:"):
        import datetime as _dt
        import json as _json
        from asgiref.sync import sync_to_async
        from tgbot.tasks import _build_top_readers_message, _toplist_congrats_keyboard
        from tgbot.bot.loader import bot
        from tgbot.bot.consts import BOYS_GROUP_ID, GIRLS_GROUP_ID

        period_key = action.split(":", 1)[1]
        from django.utils import timezone as _tz
        today = _tz.localdate()
        period_cfg = {
            "daily":    (today,                              today, "Bugun 🔥",        20),
            "3days":    (today - _dt.timedelta(days=2),     today, "Oxirgi 3 kunda",  20),
            "weekly":   (today - _dt.timedelta(days=6),     today, "Bu hafta 🏆",     25),
            "monthly":  (today - _dt.timedelta(days=29),    today, "Bu oy 📅",        30),
            "3monthly": (today - _dt.timedelta(days=89),    today, "3 oylik 📊",      40),
            "yearly":   (today - _dt.timedelta(days=364),   today, "Yillik 🏅",       60),
        }
        if period_key not in period_cfg:
            await call.message.answer("Noma'lum davr.")
        else:
            start_date, end_date, label, limit = period_cfg[period_key]
            msg_text = await sync_to_async(_build_top_readers_message)(start_date, end_date, label, limit=limit)
            if not msg_text:
                await call.message.answer("❌ Bu davr uchun ma'lumot yo'q.")
            else:
                date_str = end_date.strftime("%Y%m%d")
                keyboard_json = _toplist_congrats_keyboard(period_key, date_str)
                kb_data = _json.loads(keyboard_json)
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                congrats_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"])
                     for btn in row]
                    for row in kb_data["inline_keyboard"]
                ])

                # ── 1. Groups: sent immediately via bot (reliable, no Celery) ──
                # Note: the historical "GENERAL_GROUP_ID" IS the girls group
                # (same chat id) — there's no separate third group, just these two.
                from tgbot.bot.consts import LEADERBOARD_BOYS_THREAD_ID, LEADERBOARD_GIRLS_THREAD_ID

                for group_id, thread_id in [
                    (int(BOYS_GROUP_ID), LEADERBOARD_BOYS_THREAD_ID),
                    (int(GIRLS_GROUP_ID), LEADERBOARD_GIRLS_THREAD_ID),
                ]:
                    try:
                        await bot.send_message(
                            chat_id=group_id,
                            text=msg_text,
                            parse_mode="HTML",
                            reply_markup=congrats_kb,
                            message_thread_id=thread_id,
                            disable_web_page_preview=True,
                        )
                    except Exception as e:
                        print(f"group send {group_id} failed: {e}")

                await call.message.answer("✅ Guruhga yuborildi.")
    elif action == "quizzes":
        from tgbot.bot.handlers.users.quiz_admin import show_quiz_list
        await show_quiz_list(call.message, user)
    elif action == "kitobcha_top":
        await _send_kitobcha_top(call.message)
    elif action == "shop":
        from tgbot.bot.handlers.users.shop_admin import shop_admin_menu
        await shop_admin_menu(call.message, user)
    elif action == "library":
        from tgbot.bot.handlers.users.library_admin import library_admin_menu
        await library_admin_menu(call.message, user)
    else:
        await msg.answer("Noma'lum amal.")


async def _send_kitobcha_top(message):
    """Admin-only ranking of EVERY user by Kitobcha (ball) balance (chunked —
    doesn't fit in one Telegram message), plus aggregate stats: current grand
    total, shop spend/transaction count, and an estimated lifetime total ever
    granted. There's no award ledger, so "lifetime given" is reconstructed as
    current balances + shop spend (spent Kitobcha was still given to the user
    before they spent it; game entry fees are just redistributed among users
    and already counted in current balances, so they're not added again)."""
    from asgiref.sync import sync_to_async
    from django.db.models import Sum
    from django.utils.html import escape as _esc
    from tgbot.models import TelegramProfile, ShopPurchase

    @sync_to_async
    def _load():
        qs = TelegramProfile.objects.filter(is_registered=True, ball__gt=0)
        rows = list(qs.order_by("-ball", "id").values_list("telegram_id", "full_name", "ball"))
        grand_total = qs.aggregate(s=Sum("ball"))["s"] or 0
        purchase_count = ShopPurchase.objects.count()
        spent_total = ShopPurchase.objects.aggregate(s=Sum("price_at_purchase"))["s"] or 0
        return rows, grand_total, purchase_count, spent_total

    rows, grand_total, purchase_count, spent_total = await _load()
    if not rows:
        await message.answer("🪙 Hozircha hech kimda Kitobcha yo'q.")
        return

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    header = f"🪙 <b>Kitobcha bo'yicha reyting — barcha {len(rows)} foydalanuvchi:</b>\n\n"
    chunks = []
    current = header
    for i, (tg_id, name, ball) in enumerate(rows, 1):
        marker = medals.get(i, f"{i}.")
        nm = _esc(name or "Kitobxon")
        line = f"{marker} <a href='tg://user?id={tg_id}'>{nm}</a>: <b>{int(ball or 0)}</b> 🪙\n"
        if len(current) + len(line) > 3500:
            chunks.append(current)
            current = line
        else:
            current += line
    chunks.append(current)

    for chunk in chunks:
        await message.answer(chunk, parse_mode="HTML", disable_web_page_preview=True)

    lifetime_total = int(grand_total) + int(spent_total)
    summary = (
        "📊 <b>Umumiy statistika</b>\n\n"
        f"💰 Joriy balanslar yig'indisi: <b>{int(grand_total)}</b> 🪙\n"
        f"🛒 Do'kondan sarflangan: <b>{int(spent_total)}</b> 🪙 ({purchase_count} ta tranzaksiya)\n"
        f"🏆 Shu kungacha jami berilgan (taxminiy): <b>{lifetime_total}</b> 🪙\n\n"
        "<i>Eslatma: alohida tranzaksiya jurnali yo'q, shuning uchun \"jami berilgan\" "
        "joriy balans + do'kondan sarflangan miqdor asosida hisoblangan. O'yinlarga "
        "kirish haqi kabi foydalanuvchilar orasida qayta taqsimlangan mablag'lar "
        "allaqachon joriy balansda hisobga olingan, shuning uchun qayta qo'shilmadi.</i>"
    )
    await message.answer(summary, parse_mode="HTML")


def _is_report_admin(telegram_id: int) -> bool:
    from django.conf import settings as _settings
    return str(telegram_id) in [str(a).strip() for a in _settings.ADMINS]


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("admin_report:"), state="*")
async def admin_period_report_cb(call: types.CallbackQuery):
    """Kecha / o'tgan hafta / o'tgan oy buttons on the 23:55 admin daily report."""
    if not _is_report_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    await call.answer("Hisoblanmoqda…")
    period = call.data.split(":", 1)[1]
    from tgbot.tasks import build_admin_period_report_text
    text = await sync_to_async(build_admin_period_report_text, thread_sensitive=True)(period)
    await call.message.answer(text, parse_mode="HTML")
