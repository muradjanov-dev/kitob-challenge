from aiogram.utils.markdown import hlink
from tgbot.bot.keyboards.reply import admin_keyboard, confirm_markup, main_markup, yes_or_no_markup, back_keyboard
from aiogram.dispatcher.filters import Text
from tgbot.bot import dp
from tgbot.models import TelegramProfile, BookReport
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
        await message.answer("Iltimos, faqat 'Ha' yoki 'Yo‘q' yozing.", reply_markup=yes_or_no_markup())
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


@dp.message_handler(IsPrivate(), Text(contains="‍👩‍👦‍👦 Barcha foydalanuvchilar"))
async def all_users(message: types.Message):
    all_users_qs = TelegramProfile.objects.all().order_by('id')
    total_users_count = all_users_qs.count()
    registered_count = all_users_qs.filter(is_registered=True).count()
    unregistered_count = total_users_count - registered_count

    response = (
        "👨‍👩‍👦‍👦 <b>Barcha foydalanuvchilar</b>\n\n"
        f"📊 Jami: <b>{total_users_count}</b>\n"
        f"✅ Ro'yxatdan to'liq o'tgan: <b>{registered_count}</b>\n"
        f"🚫 Ro'yxatdan to'liq o'tmagan: <b>{unregistered_count}</b>\n\n"
        "<i>Belgilar:</i>\n"
        "✅ — registratsiyani to'liq tugatgan (ism, jins, hudud, yosh tanlagan)\n"
        "🚫 — boshlagan-u tugatmagan, yoki /restart bosgan\n"
        "-----------------------------------------------\n"
        "<code>ID  |  User</code>\n"
        "-----------------------------------------------\n"
    )

    for user in all_users_qs:
        user_id = user.telegram_id
        if user.full_name:
            mention = hlink(user.full_name, f"tg://user?id={user_id}")
        elif user.username:
            mention = hlink("@" + user.username, f"tg://user?id={user_id}")
        else:
            mention = hlink("Ism qo'yilmagan", f"tg://user?id={user_id}")

        flag = "✅" if user.is_registered else "🚫"
        response += f"{user.id}  |  {mention} {flag}\n"

    # Telegram message limit is 4096 — split if needed.
    MAX = 4000
    if len(response) <= MAX:
        await message.answer(response, parse_mode="HTML")
    else:
        chunk = ""
        for line in response.split("\n"):
            if len(chunk) + len(line) + 1 > MAX:
                await message.answer(chunk, parse_mode="HTML")
                chunk = ""
            chunk += line + "\n"
        if chunk:
            await message.answer(chunk, parse_mode="HTML")


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
        await reminders_menu(msg, state)
    elif action == "poll_new":
        from tgbot.bot.handlers.users.polls_admin import poll_admin_start
        await poll_admin_start(msg, state)
    elif action == "poll_results":
        from tgbot.bot.handlers.users.polls_admin import poll_results_list
        await poll_results_list(msg, state)
    else:
        await msg.answer("Noma'lum amal.")
