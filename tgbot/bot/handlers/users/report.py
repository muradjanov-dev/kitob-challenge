import asyncio
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from django.utils import timezone
from asgiref.sync import sync_to_async
from django.core.paginator import Paginator

from tgbot.models import ConfirmationReport, BooksToRead
from tgbot.bot.keyboards.reply import main_markup, back_keyboard
from tgbot.bot.loader import dp, bot
from tgbot.bot.loader import gettext as _
from tgbot.bot.states.main import ReportState
from tgbot.bot.utils import get_user

from tgbot.bot.consts import (
    BOYS_GROUP_ID, GIRLS_GROUP_ID,
    B_BOYS_THREAD_ID, B_GIRLS_THREAD_ID,
    D_BOYS_THREAD_ID, D_GIRLS_THREAD_ID,
    C_BOYS_THREAD_ID, C_GIRLS_THREAD_ID,
    E_BOYS_THREAD_ID, E_GIRLS_THREAD_ID
)


@sync_to_async
def get_user_books(user, page=1):
    books_list = BooksToRead.objects.filter(user=user).order_by('-created_at')
    paginator = Paginator(books_list, 10)
    return paginator.get_page(page)


@sync_to_async
def create_new_book(user, title, total_pages):
    return BooksToRead.objects.create(user=user, title=title, total_pages=total_pages)


@sync_to_async
def get_book_by_id(book_id):
    try:
        return BooksToRead.objects.get(id=book_id)
    except BooksToRead.DoesNotExist:
        return None


@sync_to_async
def get_confirmation_report_exists(user, date):
    return ConfirmationReport.objects.filter(user=user, date__date=date).exists()


@sync_to_async
def create_confirmation_report(user, pages_read, date, conclusion, book_ids):
    report = ConfirmationReport.objects.create(
        user=user,
        pages_read=pages_read,
        date=date,
        conclusion=conclusion
    )
    if book_ids:
        report.books.set(book_ids)
    return report


async def send_book_selection_menu(message_or_call, state: FSMContext, page=1):
    data = await state.get_data()
    selected_book_ids = data.get("selected_book_ids", [])
    user = get_user(message_or_call.from_user.id)

    books_page = await get_user_books(user, page)

    markup = InlineKeyboardMarkup(row_width=1)

    # Add books buttons with toggle status
    for book in books_page:
        text = book.title
        # Calculate percentage
        percent = 0
        if book.total_pages > 0:
            percent = int((book.current_page / book.total_pages) * 100)

        text = f"{text} ({percent}%)"

        if book.id in selected_book_ids:
            text = f"✅ {text}"

        # Pass page number in callback to stay on same page after toggle
        markup.add(InlineKeyboardButton(text=text,
                   callback_data=f"select_book:{book.id}:{page}"))

    # Pagination buttons
    nav_buttons = []
    if books_page.has_previous():
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"books_page:{books_page.previous_page_number()}"))

    nav_buttons.append(InlineKeyboardButton(
        text=f"{page}/{books_page.paginator.num_pages}", callback_data="noop"))

    if books_page.has_next():
        nav_buttons.append(InlineKeyboardButton(
            text="➡️", callback_data=f"books_page:{books_page.next_page_number()}"))

    markup.row(*nav_buttons)

    # Continue button (only if books are selected)
    if selected_book_ids:
        markup.add(InlineKeyboardButton(text=_("⚡️ Davom etish"),
                   callback_data="confirm_selection"))

    # Add "Add Book" button
    markup.add(InlineKeyboardButton(
        text="➕ Yangi kitob qo'shish", callback_data="add_new_book"))

    text = _(
        "Qaysi kitobni o'qiyotganingizni tanlang (bir nechtasini tanlash mumkin):")

    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.edit_text(text, reply_markup=markup)
    else:
        await message_or_call.answer(text, reply_markup=markup)


@dp.callback_query_handler(lambda c: c.data == "cta_send_report", state="*")
async def cta_send_report_handler(call: CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing", show_alert=True)
        return
    if user.is_blocked:
        await call.answer(_("Siz bot tomonidan bloklangansiz."), show_alert=True)
        return

    today = timezone.localdate()
    if await get_confirmation_report_exists(user, today):
        await call.answer(
            _("Siz bugungi kun uchun allaqachon hisobotingizni yubordingiz."),
            show_alert=True,
        )
        return

    await call.answer()
    await state.finish()

    from django.db.models.functions import TruncDate
    distinct_days = await sync_to_async(
        lambda: ConfirmationReport.objects
            .filter(user=user)
            .annotate(_d=TruncDate("date"))
            .values("_d")
            .distinct()
            .count()
    )()
    reading_day = distinct_days + 1
    await state.update_data(reading_day=reading_day, selected_book_ids=[])
    await ReportState.select_book.set()

    # Remove the inline CTA on the broadcast so the user can't double-tap.
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Build & send a fresh book-selection menu. We can't reuse
    # send_book_selection_menu directly because call.message.from_user is the
    # bot, not the user.
    books_page = await get_user_books(user, 1)
    markup = InlineKeyboardMarkup(row_width=1)
    for book in books_page:
        text = book.title
        percent = 0
        if book.total_pages > 0:
            percent = int((book.current_page / book.total_pages) * 100)
        text = f"{text} ({percent}%)"
        markup.add(InlineKeyboardButton(
            text=text, callback_data=f"select_book:{book.id}:1"))
    nav_buttons = []
    if books_page.has_previous():
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"books_page:{books_page.previous_page_number()}"))
    nav_buttons.append(InlineKeyboardButton(
        text=f"1/{books_page.paginator.num_pages}", callback_data="noop"))
    if books_page.has_next():
        nav_buttons.append(InlineKeyboardButton(
            text="➡️", callback_data=f"books_page:{books_page.next_page_number()}"))
    markup.row(*nav_buttons)
    markup.add(InlineKeyboardButton(
        text="➕ Yangi kitob qo'shish", callback_data="add_new_book"))

    await call.message.answer(
        _("Qaysi kitobni o'qiyotganingizni tanlang (bir nechtasini tanlash mumkin):"),
        reply_markup=markup,
    )


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="📚 Kitob hisoboti", state="*")
@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="📚 Отчет о книге", state="*")
async def send_daily_report_handler(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user.is_blocked:
        await message.answer(_("Siz bot tomonidan bloklangansiz."))
        return await state.finish()

    # Reading day = (distinct calendar dates already reported by this user) + 1
    from django.db.models.functions import TruncDate
    distinct_days = await sync_to_async(
        lambda: ConfirmationReport.objects
            .filter(user=user)
            .annotate(_d=TruncDate("date"))
            .values("_d")
            .distinct()
            .count()
    )()
    reading_day = distinct_days + 1
    await state.update_data(reading_day=reading_day)
    await ReportState.select_book.set()
    await send_book_selection_menu(message, state)


@dp.callback_query_handler(state=ReportState.select_book)
async def book_selection_handler(call: CallbackQuery, state: FSMContext):
    if call.data == "add_new_book":
        await call.message.delete()
        await call.message.answer(_("Kitob nomini kiriting?"), reply_markup=back_keyboard)
        await ReportState.enter_book_name.set()

    elif call.data.startswith("books_page:"):
        page = int(call.data.split(":")[1])
        await send_book_selection_menu(call, state, page)

    elif call.data.startswith("select_book:"):
        parts = call.data.split(":")
        book_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 1

        data = await state.get_data()
        selected_book_ids = data.get("selected_book_ids", [])

        if book_id in selected_book_ids:
            selected_book_ids.remove(book_id)
        else:
            selected_book_ids.append(book_id)

        await state.update_data(selected_book_ids=selected_book_ids)
        await send_book_selection_menu(call, state, page)

    elif call.data == "confirm_selection":
        data = await state.get_data()
        selected_book_ids = data.get("selected_book_ids", [])

        if not selected_book_ids:
            await call.answer(_("Kamida bitta kitob tanlang!"), show_alert=True)
            return

        # Initialize loop
        await state.update_data(pending_books=list(selected_book_ids), book_reports={})
        await ask_next_book_pages(call.message, state)

    elif call.data == "noop":
        await call.answer()


@dp.message_handler(state=ReportState.enter_book_name)
async def process_new_book_name(message: types.Message, state: FSMContext):
    if message.text == _("🔙 Orqaga"):
        await ReportState.select_book.set()
        await send_book_selection_menu(message, state)  # Go back to menu
        return

    book_title = message.text.strip()
    if len(book_title) > 120:
        await message.answer(_("Iltimos, kitobni nomi uzun bo'lmasin!"))
        return

    await state.update_data(new_book_title=book_title)

    await message.answer(_("Kitob jami nechi betdan iborat?"), reply_markup=back_keyboard)
    await ReportState.enter_book_pages.set()


@dp.message_handler(state=ReportState.enter_book_pages)
async def process_new_book_pages(message: types.Message, state: FSMContext):
    if message.text == _("🔙 Orqaga"):
        await message.answer(_("Kitob nomini kiriting?"), reply_markup=back_keyboard)
        await ReportState.enter_book_name.set()
        return

    pages = message.text
    if not pages.isdigit() or int(pages) <= 0:
        await message.answer(_("Iltimos, to'g'ri son kiriting."))
        return

    total_pages = int(pages)
    data = await state.get_data()
    book_title = data.get("new_book_title")
    user = get_user(message.from_user.id)

    # Save new book
    new_book = await create_new_book(user, book_title, total_pages)

    # Add new book to selection
    selected_book_ids = data.get("selected_book_ids", [])
    if new_book.id not in selected_book_ids:
        selected_book_ids.append(new_book.id)

    await state.update_data(selected_book_ids=selected_book_ids)

    await message.answer(_("Kitob qo'shildi va tanlandi! ✅"))

    # Return to selection menu
    await ReportState.select_book.set()
    await send_book_selection_menu(message, state)


async def ask_next_book_pages(message, state: FSMContext):
    data = await state.get_data()
    pending_books = data.get("pending_books", [])

    if not pending_books:
        # All books processed
        reports = data.get("book_reports", {})
        total_pages = sum(reports.values())
        await state.update_data(pages_read=total_pages)

        await message.answer(_("Kichik xulosa (bugun nima o'rgandingiz)\n\nMasalan: <i>Ilm - bu boylik</i>"), reply_markup=back_keyboard)
        await ReportState.conclusion.set()
        return

    next_book_id = pending_books[0]
    book = await get_book_by_id(next_book_id)

    await message.answer(f"📖 <b>{book.title}</b> kitobidan bugun nechi bet o'qidingiz? (Jami: {book.total_pages} bet, Hozirda: {book.current_page}-bet)", parse_mode="HTML")
    await ReportState.enter_pages_loop.set()


@dp.message_handler(state=ReportState.enter_pages_loop)
async def process_loop_pages(message: types.Message, state: FSMContext):
    if message.text == _("🔙 Orqaga"):
        await ReportState.select_book.set()
        await send_book_selection_menu(message, state)
        return

    pages_read_str = message.text
    if not pages_read_str.isdigit() or int(pages_read_str) <= 0:
        await message.answer(_("Iltimos, to'g'ri raqam kiriting."))
        return

    pages_read = int(pages_read_str)

    data = await state.get_data()
    pending_books = data.get("pending_books", [])
    reports = data.get("book_reports", {})

    current_book_id = pending_books.pop(0)  # Remove current
    reports[current_book_id] = pages_read

    await state.update_data(pending_books=pending_books, book_reports=reports)

    await ask_next_book_pages(message, state)


# The old handler is effectively replaced but kept if we need strict mapping.
# We remove it or repurpose it? The plan removes it implicitly by not linking to it.
# I will overwrite it to avoid conflicts.
@dp.message_handler(state=ReportState.pages_read)
async def legacy_process_pages_read(message: types.Message, state: FSMContext):
    # Backward compatibility or dead code
    pass


@dp.message_handler(state=ReportState.conclusion)
async def spent_time_handler(message: types.Message, state: FSMContext):
    conclusion = message.text

    if conclusion.isdigit():
        await message.answer(_("Iltimos, xulosa matnini kiriting."), reply_markup=back_keyboard)
        return

    if len(conclusion) > 400:
        await message.answer(_("Iltimos, xulosa matnini 400 ta belgidan uzun bo'lmasin!"), reply_markup=back_keyboard)
        return

    await state.update_data(conclusion=conclusion)

    user = get_user(message.from_user.id)
    today = timezone.localdate()

    data = await state.get_data()
    reading_day = data['reading_day']
    book = data.get('book_title')

    if not book:
        book_reports = data.get("book_reports", {})
        if book_reports:
            titles = []
            for bid in book_reports.keys():
                b_obj = await get_book_by_id(bid)
                if b_obj:
                    titles.append(b_obj.title)
            book = ", ".join(titles)
            await state.update_data(book_title=book)
        else:
            book = "Tanlanmagan"

    pages_read = data['pages_read']

    confirmation_message = (
        f"<b><a href='tg://user?id={user.telegram_id}'>{user.full_name}</a></b>:\n\n"
        f"📊#kun - {reading_day}  ({today})\n\n"
        f"<b>Kitob nomi:</b> {book}\n\n"
        f"<b>✅O‘qilgan betlar:</b> {pages_read}+ bet\n\n"
        f"<b>💡Olingan xulosa:</b> {conclusion}\n\n"
        f"<b>Haqiqiy peshqadam 🏆</b>\n\n"
        "Tasdiqlaysizmi?"
    )

    confirm_kb = InlineKeyboardMarkup(row_width=2)
    confirm_kb.add(
        InlineKeyboardButton("✅ Tasdiqlash", callback_data="report:confirm"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="report:cancel"),
    )
    await message.answer(confirmation_message, reply_markup=confirm_kb, parse_mode='HTML')
    await ReportState.confirm_report.set()

    # Timeout logic optional/as per original


@dp.callback_query_handler(
    lambda c: c.data in ("report:confirm", "report:cancel"),
    state=ReportState.confirm_report,
)
async def confirm_report_callback(call: CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if call.data == "report:cancel":
        lang = (user.language if user else None) or "uz"
        await call.message.answer(
            "Bekor qilindi." if lang != "ru" else "Отменено.",
            reply_markup=main_markup(language=lang),
        )
        await state.finish()
        return

    # Re-use the existing implementation by faking a message-style call.
    message = call.message
    try:
        message.from_user = call.from_user
    except Exception:
        pass
    await _do_confirm_report(message, user, state)


async def _do_confirm_report(message, user, state: FSMContext):
    today = timezone.localdate()

    # Check exists
    if await get_confirmation_report_exists(user, today):
        await message.answer(_("Siz bugungi kun uchun allaqachon hisobotingizni yubordingiz."), reply_markup=main_markup())
        await state.finish()
        return

    data = await state.get_data()
    reading_day = data.get("reading_day")
    book = data.get("book_title")
    pages_read = data.get("pages_read")
    conclusion = data.get("conclusion")
    book_ids = data.get("selected_book_ids")

    datetime_now = timezone.now()

    # Create report with M2M
    report = await create_confirmation_report(
        user=user,
        pages_read=pages_read,
        date=datetime_now,
        conclusion=conclusion,
        book_ids=book_ids
    )

    # Process individual book updates
    data = await state.get_data()
    book_reports = data.get("book_reports", {})

    for bid, p_read in book_reports.items():
        try:
            # Update BooksToRead current_page
            book_obj = await get_book_by_id(bid)
            if book_obj:
                book_obj.current_page += p_read
                # Cap at total? Maybe not strict validation to rely on trust, or valid
                if book_obj.current_page > book_obj.total_pages:
                    book_obj.current_page = book_obj.total_pages
                await sync_to_async(book_obj.save)()

                # Create individual BookReport log
                from tgbot.models import BookReport
                await sync_to_async(BookReport.objects.create)(
                    user=user,
                    reading_day=reading_day,
                    book=book_obj.title,
                    pages_read=p_read
                )
        except Exception as e:
            print(f"Error updating book {bid}: {e}")

    report_message = (
        f"<b><a href='tg://user?id={user.telegram_id}'>{user.full_name}</a></b>:\n\n"
        f"📊#kun - {reading_day}  ({report.date.strftime('%Y-%m-%d')})\n\n"
        f"<b>Kitob nomi:</b> {book}\n\n"
        f"<b>✅O‘qilgan betlar:</b> {pages_read}+ bet\n\n"
        f"<b>💡Olingan xulosa:</b> {conclusion}\n\n"
        f"<b>Haqiqiy peshqadam 🏆</b>"
    )

    if not user:
        await state.finish()
        return

    target_chat_id = None
    target_thread_id = None

    try:
        pages = int(pages_read)
    except (ValueError, TypeError):
        pages = 0

    if user.gender == "male":
        target_chat_id = BOYS_GROUP_ID
        if pages <= 50:
            target_thread_id = B_BOYS_THREAD_ID
        elif pages <= 100:
            target_thread_id = D_BOYS_THREAD_ID
        elif pages <= 500:
            target_thread_id = C_BOYS_THREAD_ID
        else:
            target_thread_id = E_BOYS_THREAD_ID
    else:
        target_chat_id = GIRLS_GROUP_ID
        if pages <= 50:
            target_thread_id = B_GIRLS_THREAD_ID
        elif pages <= 100:
            target_thread_id = D_GIRLS_THREAD_ID
        elif pages <= 500:
            target_thread_id = C_GIRLS_THREAD_ID
        else:
            target_thread_id = E_GIRLS_THREAD_ID

    sent_msg = None
    if target_chat_id:
        try:
            sent_msg = await bot.send_message(
                chat_id=target_chat_id,
                message_thread_id=target_thread_id,
                text=report_message,
                parse_mode='HTML'
            )
        except Exception as e:
            print(
                f"Error sending report to group {target_chat_id} thread {target_thread_id}: {e}")

    lang = user.language or "uz"
    done_text = "Ваш отчёт отправлен." if lang == "ru" else "Hisobotingiz yuborildi."
    if sent_msg:
        chat_id_str = str(target_chat_id).lstrip("-")
        if chat_id_str.startswith("100"):
            chat_id_str = chat_id_str[3:]
        link = f"https://t.me/c/{chat_id_str}/{sent_msg.message_id}"
        link_label = "📨 Открыть отчёт" if lang == "ru" else "📨 Hisobotni ko'rish"
        confirmation_text = f'{done_text}\n\n<a href="{link}">{link_label}</a>'
    else:
        confirmation_text = done_text

    await message.answer(
        confirmation_text,
        reply_markup=main_markup(language=lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # Award 25 kitobcha for the submitted report.
    try:
        await sync_to_async(user.update_ball)(True, 25)
        await message.answer(
            f"🪙 +25 Kitobcha qo'shildi! Joriy balans: <b>{int(user.ball)}</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"award kitobcha for report failed: {e}")

    # Trigger achievement evaluation + Tabriklash broadcast (fire-and-forget).
    try:
        from tgbot.tasks import check_user_achievements
        check_user_achievements.delay(user.id)
    except Exception as e:
        print(f"check_user_achievements dispatch failed: {e}")

    await state.finish()
