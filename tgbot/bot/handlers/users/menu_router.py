"""
Central inline-menu callback router.

Every main-menu inline button has callback_data `menu:<action>`. This module
dispatches each action to the appropriate logic. Existing reply-keyboard text
handlers are kept as fallback for older clients with stale keyboards.
"""
from aiogram import types
from aiogram.dispatcher import FSMContext
from asgiref.sync import sync_to_async
from django.utils import timezone
from django.db.models import Count, Avg, Sum, F
from django.db.models.functions import ExtractWeekDay, ExtractHour, Length, TruncDate
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from tgbot.bot.loader import dp
from tgbot.bot.utils import get_user
from tgbot.bot.keyboards.reply import (
    main_markup_for_user, admin_keyboard, back_keyboard, report_reply_keyboard,
)
from tgbot.bot.keyboards.inline import languages_markup
from tgbot.bot.states.main import (
    ContactAdminState, ChangeLanguageState, ReportState,
)
from tgbot.models import (
    BookReport, ConfirmationReport, BooksToRead, Payment,
)


def _t(lang, uz, ru):
    return ru if lang == "ru" else uz


def _user_lang(user):
    return (user.language if user else None) or "uz"


# ──────────────────────────────────────────────────────────────────────────
# Public helper: send the main menu (used by /start, back_handler, etc).
# Sends two messages: one to clear stale reply keyboard, one with inline kb.
# ──────────────────────────────────────────────────────────────────────────
async def send_main_menu(message: types.Message, user, header_text=None):
    lang = _user_lang(user)
    header = header_text or _t(lang, "🏠 Asosiy menyu", "🏠 Главное меню")
    sub = _t(lang, "Quyidagilardan birini tanlang:", "Выберите одно из ниже:")
    # Persistent reply kb with the big "Kitob hisoboti" button.
    try:
        await message.answer(header, reply_markup=report_reply_keyboard(lang))
    except Exception:
        pass
    await message.answer(sub, reply_markup=main_markup_for_user(user))


# ──────────────────────────────────────────────────────────────────────────
# /menu command + 🏠 Bosh menyu reply-keyboard button — summon the menu
# from anywhere. Persistent reply kb means user is never stuck.
# ──────────────────────────────────────────────────────────────────────────
HOME_BUTTON_TEXTS = ["🏠 Bosh menyu", "🏠 Главное меню", "🏠 Asosiy menyu"]


@dp.message_handler(commands=["menu"], state="*")
async def menu_command(message: types.Message, state: FSMContext):
    await state.finish()
    user = get_user(message.from_user.id)
    await send_main_menu(message, user)


@dp.message_handler(
    lambda m: m.text in HOME_BUTTON_TEXTS,
    state="*",
)
async def home_button_handler(message: types.Message, state: FSMContext):
    await state.finish()
    user = get_user(message.from_user.id)
    await send_main_menu(message, user)


# ──────────────────────────────────────────────────────────────────────────
# Router: dispatches callback_data starting with "menu:".
# ──────────────────────────────────────────────────────────────────────────
@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("menu:"),
    state="*",
)
async def main_menu_router(call: types.CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]
    user = get_user(call.from_user.id)
    lang = _user_lang(user)

    if action == "report":
        await _menu_report(call, user, state)
    elif action == "cabinet":
        await _menu_cabinet(call, user, state)
    elif action == "premium":
        await _menu_premium(call, user, state)
    elif action == "achievements":
        await _menu_achievements(call, user, state)
    elif action == "contact":
        await _menu_contact(call, user, state)
    elif action == "language":
        await _menu_language(call, user, state)
    elif action == "admin":
        await _menu_admin(call, user, state)
    else:
        await call.answer(_t(lang, "Noma'lum amal", "Неизвестное действие"))


# ──────────────────────────────────────────────────────────────────────────
# Report (book selection) — opens fresh book picker for the user.
# ──────────────────────────────────────────────────────────────────────────
async def _menu_report(call, user, state: FSMContext):
    lang = _user_lang(user)
    await call.answer()
    if not user:
        await call.message.answer(_t(lang, "Avval /start bosing", "Сначала /start"))
        return
    if user.is_blocked:
        await call.message.answer(
            _t(lang, "Siz bot tomonidan bloklangansiz.", "Вы заблокированы ботом.")
        )
        return

    today = timezone.localdate()
    already = await sync_to_async(
        lambda: ConfirmationReport.objects.filter(user=user, date__date=today).exists()
    )()
    if already:
        await call.message.answer(
            _t(
                lang,
                "Siz bugungi kun uchun allaqachon hisobotingizni yubordingiz.",
                "Вы уже отправили сегодняшний отчёт.",
            )
        )
        return

    distinct_days = await sync_to_async(
        lambda: ConfirmationReport.objects
            .filter(user=user)
            .annotate(_d=TruncDate("date"))
            .values("_d")
            .distinct()
            .count()
    )()
    reading_day = distinct_days + 1

    await state.finish()
    await state.update_data(reading_day=reading_day, selected_book_ids=[])
    await ReportState.select_book.set()

    books = await sync_to_async(list)(
        BooksToRead.objects.filter(user=user).order_by("-created_at")[:10]
    )
    markup = InlineKeyboardMarkup(row_width=1)
    for book in books:
        percent = 0
        if book.total_pages > 0:
            percent = int((book.current_page / book.total_pages) * 100)
        markup.add(InlineKeyboardButton(
            text=f"{book.title} ({percent}%)",
            callback_data=f"select_book:{book.id}:1",
        ))
    markup.add(InlineKeyboardButton(
        text=_t(lang, "➕ Yangi kitob qo'shish", "➕ Добавить книгу"),
        callback_data="add_new_book",
    ))

    await call.message.answer(
        _t(
            lang,
            "Qaysi kitobni o'qiyotganingizni tanlang (bir nechtasini tanlash mumkin):",
            "Выберите книгу (можно несколько):",
        ),
        reply_markup=markup,
    )


# ──────────────────────────────────────────────────────────────────────────
# Cabinet — replicates show_user_cabinet from cabinet.py.
# ──────────────────────────────────────────────────────────────────────────
async def _menu_cabinet(call, user, state: FSMContext):
    from tgbot.bot.handlers.users.cabinet import generate_calendar_markup

    await call.answer()
    if not user:
        await call.message.answer("Siz ro'yxatdan o'tmagansiz.")
        return

    user_id = call.from_user.id

    def _stats():
        completed_books_count = BooksToRead.objects.filter(
            user=user, current_page__gte=F("total_pages"), total_pages__gt=0
        ).count()
        total_pages_read = BookReport.objects.filter(user=user).aggregate(
            total=Sum("pages_read")
        )["total"] or 0
        avg_pages_per_day = BookReport.objects.filter(user=user).aggregate(
            avg=Avg("pages_read")
        )["avg"] or 0

        weekday_stats = list(
            BookReport.objects.filter(user=user)
            .annotate(weekday=ExtractWeekDay("created_at"))
            .values("weekday").annotate(count=Count("id")).order_by("-count")
        )
        hour_stats = list(
            BookReport.objects.filter(user=user)
            .annotate(hour=ExtractHour("created_at"))
            .values("hour").annotate(count=Count("id")).order_by("-count")
        )
        top_conclusions = list(
            ConfirmationReport.objects.filter(user=user)
            .annotate(length=Length("conclusion"))
            .order_by("-length")[:3]
        )
        return (completed_books_count, total_pages_read, avg_pages_per_day,
                weekday_stats, hour_stats, top_conclusions)

    (completed_books_count, total_pages_read, avg_pages_per_day,
     weekday_stats, hour_stats, top_conclusions) = await sync_to_async(_stats)()

    active_days_map = {
        1: "Yakshanba", 2: "Dushanba", 3: "Seshanba", 4: "Chorshanba",
        5: "Payshanba", 6: "Juma", 7: "Shanba",
    }
    most_active_day = "Ma'lumot yo'q"
    if weekday_stats:
        most_active_day = active_days_map.get(weekday_stats[0]["weekday"], "Noma'lum")

    active_hour = "Ma'lumot yo'q"
    if hour_stats:
        h = hour_stats[0]["hour"]
        active_hour = f"{h:02d}:00-{h+1:02d}:00 oralig'ida"

    conclusion_text = ""
    if top_conclusions:
        conclusion_text = "\n\n✍️ <b>Eng mazmunli xulosalaringiz:</b>\n"
        for i, report in enumerate(top_conclusions, 1):
            book_title = report.book if report.book else "Noma'lum kitob"
            conclusion_text += f"{i}. <i>{book_title}</i> ({report.pages_read} bet)\n"

    response_text = (
        f"👤 <b>Sizning shaxsiy kabinetingiz</b>\n\n"
        f"📚 <b>O'qilgan kitoblar:</b> {completed_books_count} ta\n"
        f"📄 <b>Jami o'qilgan sahifalar:</b> {total_pages_read}\n"
        f"⚡️ <b>O'rtacha kunlik o'qish:</b> {int(avg_pages_per_day)} bet\n"
        f"📅 <b>Eng faol kuningiz:</b> {most_active_day}\n"
        f"⏰ <b>Sevimli vaqtingiz:</b> {active_hour}\n"
        f"{conclusion_text}"
        f"\n<i>Ma'lumotlar avtomatik yangilanib boradi.</i>"
    )

    now = timezone.now()
    calendar_markup = await sync_to_async(generate_calendar_markup)(
        user_id, now.year, now.month
    )
    await call.message.answer(response_text, parse_mode="HTML",
                              reply_markup=calendar_markup)


# ──────────────────────────────────────────────────────────────────────────
# Premium — replicates payment.premium_menu_handler.
# ──────────────────────────────────────────────────────────────────────────
async def _menu_premium(call, user, state: FSMContext):
    from tgbot.bot.handlers.users.payment import (
        premium_features_text, premium_menu_markup,
    )

    await call.answer()
    await state.finish()
    lang = _user_lang(user)

    active = await sync_to_async(
        lambda: Payment.objects.filter(
            user=user, status="paid", end_date__gte=timezone.localdate()
        ).first() if user else None
    )()

    if active:
        if lang == "ru":
            text = (
                f"✅ <b>У вас активная подписка!</b>\n\n"
                f"📅 Действует до: <b>{active.end_date.strftime('%d.%m.%Y')}</b>"
            )
        else:
            text = (
                f"✅ <b>Sizda faol obuna mavjud!</b>\n\n"
                f"📅 Amal qilish muddati: <b>{active.end_date.strftime('%d.%m.%Y')}</b>"
            )
        await call.message.answer(text, parse_mode="HTML")
        return

    await call.message.answer(
        premium_features_text(lang),
        parse_mode="HTML",
        reply_markup=premium_menu_markup(lang),
    )


# ──────────────────────────────────────────────────────────────────────────
# Contact admin — same flow as text-button entry.
# ──────────────────────────────────────────────────────────────────────────
async def _menu_contact(call, user, state: FSMContext):
    await call.answer()
    await state.finish()
    lang = _user_lang(user)
    await call.message.answer(
        _t(
            lang,
            "✉️ Adminga yubormoqchi bo'lgan xabaringizni yozing:",
            "✉️ Напишите сообщение, которое хотите отправить администратору:",
        ),
        reply_markup=back_keyboard,
    )
    await ContactAdminState.message.set()


# ──────────────────────────────────────────────────────────────────────────
# Language switch.
# ──────────────────────────────────────────────────────────────────────────
async def _menu_language(call, user, state: FSMContext):
    await call.answer()
    lang = _user_lang(user)
    text = _t(lang, "Tilni o'zgartiring", "Измените язык")
    await call.message.answer(text, reply_markup=languages_markup)
    await ChangeLanguageState.language_change.set()


# ──────────────────────────────────────────────────────────────────────────
# Achievements list (Yutuqlarim).
# ──────────────────────────────────────────────────────────────────────────
async def _menu_achievements(call, user, state: FSMContext):
    from tgbot.services.achievements import list_user_achievements

    await call.answer()
    if not user:
        await call.message.answer(
            _t(_user_lang(user), "Avval /start bosing", "Сначала /start"),
        )
        return
    lang = _user_lang(user)
    items = await sync_to_async(list_user_achievements)(user)

    unlocked_count = sum(1 for it in items if it["unlocked"])
    total = len(items)

    header = _t(
        lang,
        f"🏆 <b>Yutuqlarim</b> ({unlocked_count}/{total})\n\n",
        f"🏆 <b>Мои достижения</b> ({unlocked_count}/{total})\n\n",
    )

    lines_unlocked, lines_locked = [], []
    for it in items:
        title = it["title_ru"] if lang == "ru" else it["title_uz"]
        if it["unlocked"]:
            lines_unlocked.append(f"{it['emoji']} <b>{title}</b>")
        else:
            lines_locked.append(f"🔒 {it['emoji']} <i>{title}</i>")

    body_parts = []
    if lines_unlocked:
        body_parts.append(_t(lang, "<b>Qo'lga kiritilgan:</b>\n", "<b>Получено:</b>\n"))
        body_parts.append("\n".join(lines_unlocked))
    if lines_locked:
        if body_parts:
            body_parts.append("\n\n")
        body_parts.append(_t(lang, "<b>Hali olinmagan:</b>\n", "<b>Ещё не открыто:</b>\n"))
        body_parts.append("\n".join(lines_locked))

    text = header + "".join(body_parts)
    # Telegram caps message at 4096 chars — split if needed.
    MAX = 4000
    if len(text) <= MAX:
        await call.message.answer(text, parse_mode="HTML")
    else:
        chunk = ""
        for line in text.split("\n"):
            if len(chunk) + len(line) + 1 > MAX:
                await call.message.answer(chunk, parse_mode="HTML")
                chunk = ""
            chunk += line + "\n"
        if chunk:
            await call.message.answer(chunk, parse_mode="HTML")


# ──────────────────────────────────────────────────────────────────────────
# Admin panel.
# ──────────────────────────────────────────────────────────────────────────
async def _menu_admin(call, user, state: FSMContext):
    lang = _user_lang(user)
    if not (user and user.is_admin):
        await call.answer(
            _t(lang, "Siz admin emassiz!", "Вы не админ!"), show_alert=True
        )
        return
    await call.answer()
    await state.finish()
    await call.message.answer(
        _t(lang, "Menudan birini tanlang:", "Выберите одно из меню:"),
        reply_markup=admin_keyboard,
    )
