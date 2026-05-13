from aiogram.utils.markdown import hlink
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from django.utils import timezone
from tgbot.bot.keyboards.reply import admin_keyboard, confirm_markup, main_markup, yes_or_no_markup, back_keyboard
from aiogram.dispatcher.filters import Text
from tgbot.bot import dp
from tgbot.models import TelegramProfile, BookReport, ConfirmationReport, BooksToRead, UserAchievement
from aiogram import types
from aiogram.dispatcher import FSMContext
from tgbot.bot.states.main import StatisticState, NotificationState
from tgbot.bot.filters import IsPrivate
from tgbot.bot.utils import get_user
from tgbot.bot.loader import gettext as _


@dp.message_handler(IsPrivate(), commands=["admin"], state="*")
@dp.message_handler(IsPrivate(), Text(equals=["👑 Admin panel", "👑 Админ панель"]), state="*")
async def admin_commands(message: types.Message, state: FSMContext = None):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user and user.is_admin:
        if state is not None:
            try:
                await state.finish()
            except Exception:
                pass
        await message.answer("Menudan birini tanlang:", reply_markup=admin_keyboard)
    else:
        await message.answer("Siz admin emassiz!")


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


def _build_user_detail(user_id: int) -> str:
    """Returns full HTML detail for a single TelegramProfile (admin view)."""
    from django.db.models import Count, Avg, Sum, F
    from django.db.models.functions import ExtractWeekDay, ExtractHour, TruncDate

    user = TelegramProfile.objects.filter(id=user_id).first()
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
        "u18": "<18", "18_25": "18–25", "26_35": "26–35", "36p": "36+",
    }.get(user.age_range or "", "—")

    username_str = f"@{user.username}" if user.username else "—"
    full_name = user.full_name or "—"
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
        f"👤 <b>{full_name}</b>\n"
        f"🆔 <code>{user.telegram_id}</code> · DB id: {user.id}\n"
        f"📱 {username_str}\n"
        f"🌐 Til: {(user.language or '—').upper()}\n"
        f"🚻 Jins: {gender_label}\n"
        f"🗺 Hudud: {region_name}\n"
        f"🎂 Yosh: {age_label}\n"
        f"📅 A'zo bo'lgan: {days_since_join} kun oldin\n"
        f"{reg_status}{(' · ' + blocked) if blocked else ''}{(' · ' + admin_flag) if admin_flag else ''}\n\n"
        f"🪙 <b>Kitobcha balansi:</b> {int(user.ball or 0)}\n"
        f"📚 Hisobotlar: <b>{reports_count}</b>\n"
        f"📄 Jami betlar: <b>{total_pages}</b>\n"
        f"⚡️ O'rtacha: <b>{int(avg_pages)} bet/hisobot</b>\n"
        f"📅 Faol kunlar (uniq): <b>{distinct_days}</b>\n"
        f"📖 Tugatgan kitoblar: <b>{completed_books}</b>\n"
        f"📕 O'qilayotgan: <b>{in_progress_books}</b>\n"
        f"🗓 Eng faol kun: <b>{most_active_day}</b>\n"
        f"⏰ Eng faol vaqt: <b>{active_hour}</b>"
        f"{ach_text}"
    )


@dp.message_handler(IsPrivate(), Text(contains="‍👩‍👦‍👦 Barcha foydalanuvchilar"))
async def all_users(message: types.Message):
    text, markup = _build_users_overview(page=1)
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("adm_userp:"), state="*")
async def adm_user_page(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
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


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("adm_userd:"), state="*")
async def adm_user_detail(call: types.CallbackQuery):
    actor = get_user(call.from_user.id)
    if not (actor and actor.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    target_id = int(call.data.split(":", 1)[1])
    text = _build_user_detail(target_id)
    back_kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("⬅️ Ro'yxatga qaytish", callback_data="adm_userp:1")
    )
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=back_kb)
    await call.answer()


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
    user = get_user(call.from_user.id)
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
        await all_users(msg)
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
            "daily":    (today,                              today, "Bugun 🔥 Top kitobxonlar",    20),
            "3days":    (today - _dt.timedelta(days=2),     today, "3 kunlik Top kitobxonlar",    20),
            "weekly":   (today - _dt.timedelta(days=6),     today, "Bu hafta 🏆 Top kitobxonlar", 30),
            "monthly":  (today - _dt.timedelta(days=29),    today, "Bu oy 📅 Top kitobxonlar",    30),
            "3monthly": (today - _dt.timedelta(days=89),    today, "3 oylik 📊 Top kitobxonlar",  40),
            "yearly":   (today - _dt.timedelta(days=364),   today, "Yillik 🏅 Top kitobxonlar",   60),
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
                GENERAL_GROUP_ID = -1002237773868
                general_thread = __import__('os').environ.get("MESSAGE_THREAD_ID")
                general_thread = int(general_thread) if general_thread else None

                for group_id, thread_id in [
                    (GENERAL_GROUP_ID, general_thread),
                    (int(BOYS_GROUP_ID), None),
                    (int(GIRLS_GROUP_ID), None),
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
    else:
        await msg.answer("Noma'lum amal.")
