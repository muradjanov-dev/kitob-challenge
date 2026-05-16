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
from tgbot.bot.utils import aget_user

from tgbot.bot.consts import (
    BOYS_GROUP_ID, GIRLS_GROUP_ID,
    B_BOYS_THREAD_ID, B_GIRLS_THREAD_ID,
    D_BOYS_THREAD_ID, D_GIRLS_THREAD_ID,
    C_BOYS_THREAD_ID, C_GIRLS_THREAD_ID,
    E_BOYS_THREAD_ID, E_GIRLS_THREAD_ID
)


@sync_to_async
def get_user_books(user, page=1):
    from django.db.models import Case, When, IntegerField, Value, F
    books_list = BooksToRead.objects.filter(user=user).annotate(
        sort_order=Case(
            When(current_page=0, then=Value(1)),                                        # not started → middle
            When(total_pages__gt=0, current_page__gte=F('total_pages'), then=Value(2)), # finished → bottom
            default=Value(0),                                                           # active → top
            output_field=IntegerField(),
        )
    ).order_by('sort_order', '-created_at')
    paginator = Paginator(books_list, 10)
    return paginator.get_page(page)


@sync_to_async
def create_new_book(user, title, total_pages, is_audio=False):
    return BooksToRead.objects.create(user=user, title=title, total_pages=total_pages, is_audio=is_audio)


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
def _is_premium_user(user):
    from tgbot.models import Payment
    return Payment.objects.filter(
        user=user, status="paid", end_date__gte=timezone.localdate()
    ).exists()


@sync_to_async
def _today_reports_qs(user, today):
    return list(
        ConfirmationReport.objects
        .filter(user=user, date__date=today)
        .order_by("date")
    )


@sync_to_async
def create_confirmation_report(
    user, pages_read, date, conclusion, book_ids,
    book_title=None, is_audio=False, minutes_listened=None
):
    report = ConfirmationReport.objects.create(
        user=user,
        pages_read=pages_read,
        date=date,
        conclusion=conclusion,
        book=(book_title or "")[:255] or None,
        is_audio=is_audio,
        minutes_listened=minutes_listened,
    )
    if book_ids:
        report.books.set(book_ids)
    return report


# ── Book selection ───────────────────────────────────────────────────────────

async def send_book_selection_menu(message_or_call, state: FSMContext, page=1):
    data = await state.get_data()
    selected_book_ids = data.get("selected_book_ids", [])
    user = await aget_user(message_or_call.from_user.id)

    books_page = await get_user_books(user, page)

    markup = InlineKeyboardMarkup(row_width=1)

    for book in books_page:
        type_icon = "🎧" if book.is_audio else "📖"
        percent = 0
        if book.total_pages > 0:
            percent = int((book.current_page / book.total_pages) * 100)
        label = f"{type_icon} {book.title} ({percent}%)"
        if book.id in selected_book_ids:
            label = f"✅ {label}"
        markup.add(InlineKeyboardButton(text=label,
                   callback_data=f"select_book:{book.id}:{page}"))

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

    if selected_book_ids:
        markup.add(InlineKeyboardButton(text=_("⚡️ Davom etish"),
                   callback_data="confirm_selection"))

    markup.add(InlineKeyboardButton(
        text="➕ 📖 / 🎧 Yangi kitob qo'shish", callback_data="add_new_book"))

    text = _(
        "Qaysi kitobni o'qiyotganingizni tanlang (bir nechtasini tanlash mumkin) "
        "/ Yoki yangi kitob qo'shing (📖 Qog'oz / 🎧 Audio):")

    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.edit_text(text, reply_markup=markup)
    else:
        await message_or_call.answer(text, reply_markup=markup)


# ── CTA inline button (from broadcast messages) ──────────────────────────────

async def _compute_reading_day(user, today):
    """If user already has a report today, keep today's reading_day; else N+1."""
    from django.db.models.functions import TruncDate

    @sync_to_async
    def _q():
        distinct_days = (
            ConfirmationReport.objects
            .filter(user=user)
            .annotate(_d=TruncDate("date"))
            .values("_d")
            .distinct()
            .count()
        )
        has_today = ConfirmationReport.objects.filter(user=user, date__date=today).exists()
        return distinct_days, has_today

    distinct_days, has_today = await _q()
    return distinct_days if has_today else distinct_days + 1


@dp.callback_query_handler(lambda c: c.data == "cta_send_report", state="*")
async def cta_send_report_handler(call: CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing", show_alert=True)
        return
    if user.is_blocked:
        await call.answer(_("Siz bot tomonidan bloklangansiz."), show_alert=True)
        return

    today = timezone.localdate()
    already_today = await get_confirmation_report_exists(user, today)
    if already_today and not await _is_premium_user(user):
        await call.answer(
            _("Siz bugungi kun uchun allaqachon hisobotingizni yubordingiz. 💎 Premium foydalanuvchilar kuniga bir nechta hisobot yubora oladi."),
            show_alert=True,
        )
        return

    await call.answer()
    await state.finish()

    reading_day = await _compute_reading_day(user, today)
    await state.update_data(reading_day=reading_day, selected_book_ids=[])

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await ReportState.select_book.set()
    await send_book_selection_menu(call, state)


# ── Reply-keyboard "📚 Kitob hisoboti" button ────────────────────────────────

@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="📚 Kitob hisoboti", state="*")
@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="📚 Отчет о книге", state="*")
async def send_daily_report_handler(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    if user.is_blocked:
        await message.answer(_("Siz bot tomonidan bloklangansiz."))
        return await state.finish()

    today = timezone.localdate()
    already_today = await get_confirmation_report_exists(user, today)
    if already_today and not await _is_premium_user(user):
        await message.answer(
            _("Siz bugungi kun uchun allaqachon hisobotingizni yubordingiz.\n\n💎 Premium foydalanuvchilar kuniga bir necha marotaba hisobot yubora oladi — barcha hisobotlar avtomatik jamlanadi va guruhdagi xabar yangilanadi."),
        )
        return await state.finish()

    reading_day = await _compute_reading_day(user, today)
    await state.update_data(reading_day=reading_day, selected_book_ids=[])
    await ReportState.select_book.set()
    await send_book_selection_menu(message, state)


# ── Book selection callbacks ──────────────────────────────────────────────────

@dp.callback_query_handler(state=ReportState.select_book)
async def book_selection_handler(call: CallbackQuery, state: FSMContext):
    if call.data == "add_new_book":
        type_kb = InlineKeyboardMarkup(row_width=2)
        type_kb.add(
            InlineKeyboardButton("📖 Oddiy kitob", callback_data="add_book_type:live"),
            InlineKeyboardButton("🎧 Audiokitob",  callback_data="add_book_type:audio"),
        )
        await call.message.edit_text("Qo'shmoqchi bo'lgan kitob turini tanlang:", reply_markup=type_kb)
        await call.answer()

    elif call.data.startswith("add_book_type:"):
        is_audio_new = call.data.split(":")[1] == "audio"
        await state.update_data(new_book_is_audio=is_audio_new)
        await call.message.delete()
        await call.message.answer(_("Kitob nomini kiriting?"), reply_markup=back_keyboard)
        await ReportState.enter_book_name.set()
        await call.answer()

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

        await state.update_data(pending_books=list(selected_book_ids), book_reports={})
        await ask_next_book_pages(call.message, state)

    elif call.data == "noop":
        await call.answer()


@dp.message_handler(state=ReportState.enter_book_name)
async def process_new_book_name(message: types.Message, state: FSMContext):
    if message.text == _("🔙 Orqaga"):
        await ReportState.select_book.set()
        await send_book_selection_menu(message, state)
        return

    book_title = message.text.strip()
    if len(book_title) > 120:
        await message.answer(_("Iltimos, kitobni nomi uzun bo'lmasin!"))
        return

    await state.update_data(new_book_title=book_title)
    data = await state.get_data()
    new_book_is_audio = data.get("new_book_is_audio", False)
    question = "Kitob jami necha daqiqa davom etadi?" if new_book_is_audio else _("Kitob jami nechi betdan iborat?")
    await message.answer(question, reply_markup=back_keyboard)
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
    new_book_is_audio = data.get("new_book_is_audio", False)
    user = await aget_user(message.from_user.id)

    # Smart default: if user picked "Oddiy kitob" but the title obviously
    # says audiobook, auto-flip — prevents the most common add-flow mistake.
    title_l = (book_title or "").lower()
    audio_keywords = ("audio", "аудио", "audiokitob", "audiobook")
    if not new_book_is_audio and any(kw in title_l for kw in audio_keywords):
        new_book_is_audio = True

    new_book = await create_new_book(user, book_title, total_pages, is_audio=new_book_is_audio)

    selected_book_ids = data.get("selected_book_ids", [])
    if new_book.id not in selected_book_ids:
        selected_book_ids.append(new_book.id)

    await state.update_data(selected_book_ids=selected_book_ids)
    type_icon = "🎧" if new_book_is_audio else "📖"
    type_label = "Audiokitob" if new_book_is_audio else "Oddiy kitob"
    await message.answer(
        f"{type_icon} <b>{book_title}</b> ({type_label}) qo'shildi va tanlandi! ✅",
        parse_mode="HTML",
    )

    await ReportState.select_book.set()
    await send_book_selection_menu(message, state)


# ── Per-book value entry loop (pages for live, minutes for audio) ─────────────

async def ask_next_book_pages(message, state: FSMContext):
    data = await state.get_data()
    pending_books = data.get("pending_books", [])

    if not pending_books:
        # Loop done — compute live/audio totals from each book's own is_audio flag
        book_reports = data.get("book_reports", {})
        live_pages = 0
        audio_minutes = 0
        for bid, val in book_reports.items():
            b = await get_book_by_id(int(bid))
            if b and b.is_audio:
                audio_minutes += val
            else:
                live_pages += val

        is_combined = live_pages > 0 and audio_minutes > 0
        is_audio = live_pages == 0 and audio_minutes > 0
        await state.update_data(
            pages_read=live_pages,
            minutes_listened=audio_minutes if audio_minutes > 0 else None,
            is_audio=is_audio,
            is_combined=is_combined,
        )
        await message.answer(
            _("Kichik xulosa (bugun nima o'rgandingiz)\n\nMasalan: <i>Ilm - bu boylik</i>"),
            reply_markup=back_keyboard,
        )
        await ReportState.conclusion.set()
        return

    next_book_id = pending_books[0]
    book = await get_book_by_id(next_book_id)

    # Self-heal misclassified audiobooks: if a book has 0 progress and its title
    # clearly says it's an audiobook, flip is_audio=True silently. This rescues
    # cases where the user picked the wrong type on the add screen.
    if book and not book.is_audio and book.current_page == 0:
        title_l = (book.title or "").lower()
        audio_keywords = ("audio", "аудио", "audiokitob", "audiobook")
        if any(kw in title_l for kw in audio_keywords):
            book.is_audio = True
            await sync_to_async(book.save)(update_fields=["is_audio"])

    if book.is_audio:
        unit = "daqiqa"
        await message.answer(
            f"🎧 <b>{book.title}</b> — bugun necha daqiqa eshitdingiz?\n"
            f"(Jami: {book.total_pages} {unit}, Hozirda: {book.current_page}-{unit})",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"📖 <b>{book.title}</b> — bugun nechi bet o'qidingiz?\n"
            f"(Jami: {book.total_pages} bet, Hozirda: {book.current_page}-bet)",
            parse_mode="HTML",
        )
    await ReportState.enter_pages_loop.set()


@dp.message_handler(state=ReportState.enter_pages_loop)
async def process_loop_pages(message: types.Message, state: FSMContext):
    if message.text == _("🔙 Orqaga"):
        await ReportState.select_book.set()
        await send_book_selection_menu(message, state)
        return

    value_str = message.text
    if not value_str.isdigit() or int(value_str) <= 0:
        await message.answer(_("Iltimos, to'g'ri raqam kiriting."))
        return

    value = int(value_str)

    data = await state.get_data()
    pending_books = data.get("pending_books", [])
    reports = data.get("book_reports", {})

    current_book_id = pending_books.pop(0)
    reports[current_book_id] = value

    await state.update_data(pending_books=pending_books, book_reports=reports)
    await ask_next_book_pages(message, state)


@dp.message_handler(state=ReportState.pages_read)
async def legacy_process_pages_read(message: types.Message, state: FSMContext):
    pass


# ── Conclusion ───────────────────────────────────────────────────────────────

@dp.message_handler(state=ReportState.conclusion)
async def spent_time_handler(message: types.Message, state: FSMContext):
    conclusion = message.text

    if conclusion.isdigit():
        await message.answer(_("Iltimos, xulosa matnini kiriting."), reply_markup=back_keyboard)
        return

    if len(conclusion) > 400:
        await message.answer(
            _("Iltimos, xulosa matnini 400 ta belgidan uzun bo'lmasin!"),
            reply_markup=back_keyboard,
        )
        return

    await state.update_data(conclusion=conclusion)

    user = await aget_user(message.from_user.id)
    today = timezone.localdate()

    data = await state.get_data()
    reading_day = data['reading_day']
    is_audio = data.get("is_audio", False)

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

    is_combined = data.get("is_combined", False)
    if is_combined:
        pages_read = data.get("pages_read", 0)
        minutes_listened = data.get("minutes_listened", 0)
        value_line = (
            f"<b>✅ O'qilgan betlar:</b> {pages_read}+ bet\n"
            f"<b>🎧 Eshitilgan vaqt:</b> {minutes_listened} daqiqa"
        )
        type_label = "📖 Kitob + 🎧 Audiokitob"
    elif is_audio:
        minutes_listened = data.get("minutes_listened", 0)
        value_line = f"<b>🎧 Eshitilgan vaqt:</b> {minutes_listened} daqiqa"
        type_label = "🎧 Audiokitob"
    else:
        pages_read = data.get("pages_read", 0)
        value_line = f"<b>✅O'qilgan betlar:</b> {pages_read}+ bet"
        type_label = "📖 Kitob"

    confirmation_message = (
        f"<b><a href='tg://user?id={user.telegram_id}'>{user.full_name}</a></b>:\n\n"
        f"📊#kun - {reading_day}  ({today})\n\n"
        f"<b>Tur:</b> {type_label}\n\n"
        f"<b>Kitob nomi:</b> {book}\n\n"
        f"{value_line}\n\n"
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


# ── Confirm / cancel report ───────────────────────────────────────────────────

@dp.callback_query_handler(
    lambda c: c.data in ("report:confirm", "report:cancel"),
    state=ReportState.confirm_report,
)
async def confirm_report_callback(call: CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
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

    message = call.message
    try:
        message.from_user = call.from_user
    except Exception:
        pass
    await _do_confirm_report(message, user, state)


async def _do_confirm_report(message, user, state: FSMContext):
    today = timezone.localdate()
    is_premium = await _is_premium_user(user)
    prior_reports = await _today_reports_qs(user, today)
    is_aggregating = bool(prior_reports) and is_premium

    if prior_reports and not is_premium:
        await message.answer(
            _("Siz bugungi kun uchun allaqachon hisobotingizni yubordingiz."),
            reply_markup=main_markup(),
        )
        await state.finish()
        return

    data = await state.get_data()
    reading_day = data.get("reading_day")
    book = data.get("book_title")
    is_audio = data.get("is_audio", False)
    is_combined = data.get("is_combined", False)
    pages_read = data.get("pages_read", 0) or 0
    minutes_listened = data.get("minutes_listened")
    conclusion = data.get("conclusion")
    book_ids = data.get("selected_book_ids")

    datetime_now = timezone.now()

    report = await create_confirmation_report(
        user=user,
        pages_read=pages_read,
        date=datetime_now,
        conclusion=conclusion,
        book_ids=book_ids,
        book_title=book,
        is_audio=is_audio,
        minutes_listened=minutes_listened,
    )

    if is_combined and minutes_listened:
        await create_confirmation_report(
            user=user,
            pages_read=0,
            date=datetime_now,
            conclusion=conclusion,
            book_ids=book_ids,
            book_title=book,
            is_audio=True,
            minutes_listened=minutes_listened,
        )

    book_reports = (await state.get_data()).get("book_reports", {})
    for bid, value in book_reports.items():
        try:
            book_obj = await get_book_by_id(bid)
            if book_obj:
                book_obj.current_page += value
                if book_obj.total_pages > 0 and book_obj.current_page > book_obj.total_pages:
                    book_obj.current_page = book_obj.total_pages
                await sync_to_async(book_obj.save)()

                from tgbot.models import BookReport
                await sync_to_async(BookReport.objects.create)(
                    user=user,
                    reading_day=reading_day,
                    book=book_obj.title,
                    pages_read=value,
                )
        except Exception as e:
            print(f"Error updating book {bid}: {e}")

    prem_badge = "💎 " if is_premium else ""

    # Refresh today's report list (now includes the row we just created) to
    # compute cumulative totals for the aggregated group message.
    todays = await _today_reports_qs(user, today)
    total_pages = sum((r.pages_read or 0) for r in todays if not r.is_audio)
    total_minutes = sum((r.minutes_listened or 0) for r in todays if r.is_audio)
    has_pages = total_pages > 0
    has_audio = total_minutes > 0

    if has_pages and has_audio:
        value_line = (
            f"<b>✅ O'qilgan betlar:</b> {total_pages}+ bet\n"
            f"<b>🎧 Eshitilgan vaqt:</b> {total_minutes} daqiqa"
        )
        type_tag = "📖 Kitob + 🎧 Audiokitob"
    elif has_audio:
        value_line = f"<b>🎧 Eshitilgan vaqt:</b> {total_minutes} daqiqa"
        type_tag = "🎧 Audiokitob"
    else:
        value_line = f"<b>✅O'qilgan betlar:</b> {total_pages}+ bet"
        type_tag = "📖 Kitob"

    aggregate_note = ""
    if is_aggregating:
        n = len(todays)
        aggregate_note = f"\n\n<i>💎 {n} ta hisobot jamlandi</i>"

    report_message = (
        f"<b><a href='tg://user?id={user.telegram_id}'>{prem_badge}{user.full_name}</a></b>:\n\n"
        f"📊#kun - {reading_day}  ({report.date.strftime('%Y-%m-%d')})\n\n"
        f"<b>Tur:</b> {type_tag}\n\n"
        f"<b>Kitob nomi:</b> {book}\n\n"
        f"{value_line}\n\n"
        f"<b>💡Olingan xulosa:</b> {conclusion}\n\n"
        f"<b>Haqiqiy peshqadam 🏆</b>"
        f"{aggregate_note}"
    )

    if not user:
        await state.finish()
        return

    # Routing — by cumulative pages (audio-only days route to B-tier).
    routing_pages = total_pages if has_pages else 0
    if user.gender == "male":
        target_chat_id = BOYS_GROUP_ID
        if routing_pages <= 50:
            target_thread_id = B_BOYS_THREAD_ID
        elif routing_pages <= 100:
            target_thread_id = D_BOYS_THREAD_ID
        elif routing_pages <= 500:
            target_thread_id = C_BOYS_THREAD_ID
        else:
            target_thread_id = E_BOYS_THREAD_ID
    else:
        target_chat_id = GIRLS_GROUP_ID
        if routing_pages <= 50:
            target_thread_id = B_GIRLS_THREAD_ID
        elif routing_pages <= 100:
            target_thread_id = D_GIRLS_THREAD_ID
        elif routing_pages <= 500:
            target_thread_id = C_GIRLS_THREAD_ID
        else:
            target_thread_id = E_GIRLS_THREAD_ID

    # Delete prior group messages for today (premium aggregation).
    if is_aggregating:
        seen = set()
        for prev in prior_reports:
            key = (prev.group_chat_id, prev.group_message_id)
            if not prev.group_chat_id or not prev.group_message_id or key in seen:
                continue
            seen.add(key)
            try:
                await bot.delete_message(
                    chat_id=prev.group_chat_id, message_id=prev.group_message_id,
                )
            except Exception as e:
                print(f"delete prior aggregated msg failed (chat={prev.group_chat_id}, msg={prev.group_message_id}): {e}")
        # Clear references on prior rows so we don't re-attempt deletion.
        await sync_to_async(
            ConfirmationReport.objects.filter(user=user, date__date=today).exclude(id=report.id).update
        )(group_chat_id=None, group_message_id=None, group_thread_id=None)

    sent_msg = None
    if target_chat_id:
        try:
            sent_msg = await bot.send_message(
                chat_id=target_chat_id,
                message_thread_id=target_thread_id,
                text=report_message,
                parse_mode='HTML',
            )
        except Exception as e:
            print(
                f"Error sending report to group {target_chat_id} thread {target_thread_id}: {e}")

    if sent_msg:
        await sync_to_async(
            ConfirmationReport.objects.filter(id=report.id).update
        )(
            group_chat_id=target_chat_id,
            group_message_id=sent_msg.message_id,
            group_thread_id=target_thread_id,
            reading_day=reading_day,
        )

    lang = user.language or "uz"
    if is_aggregating:
        done_text = (
            "Hisobotingiz jamlandi va guruhdagi xabar yangilandi. 💎"
            if lang != "ru" else
            "Отчёт суммирован и групповое сообщение обновлено. 💎"
        )
    else:
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

    # Kitobcha only on first report of the day — subsequent premium submissions
    # update the aggregation but don't farm rewards.
    # Race-safe: use the smallest id of today's rows; only that one gets the
    # award. If two concurrent submissions both insert, only the earlier-id
    # row triggers the reward.
    first_today_id = todays[0].id if todays else None
    if first_today_id == report.id:
        try:
            awarded = await sync_to_async(user.update_ball)(True, 25)
            premium_note = " 💎 ×2 premium!" if awarded > 25 else ""
            await message.answer(
                f"🪙 +{awarded} Kitobcha qo'shildi!{premium_note} Joriy balans: <b>{int(user.ball)}</b>",
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"award kitobcha for report failed: {e}")

    try:
        from tgbot.tasks import check_user_achievements
        check_user_achievements.delay(user.id)
    except Exception as e:
        print(f"check_user_achievements dispatch failed: {e}")

    # Deferred referral: count the referral only after the invited user's
    # FIRST ConfirmationReport. Avoids fake referrals that join but never read.
    @sync_to_async
    def _consume_pending_ref():
        from tgbot.models import TelegramProfile as _TP
        # Re-fetch the user to read latest pending_referral_code (might have
        # changed since handler entry).
        fresh = _TP.objects.filter(id=user.id).first()
        if not fresh or not fresh.pending_referral_code:
            return None
        # Only on first ever report — ConfirmationReport.count() == 1 (the row
        # we just inserted; combined audio adds a second is_audio=True row, so
        # check by ordering by id ascending and matching our id).
        is_first_ever = (
            ConfirmationReport.objects
            .filter(user=fresh)
            .order_by("id")
            .first()
            .id == report.id
        )
        if not is_first_ever:
            return None
        code = fresh.pending_referral_code
        # Clear immediately to prevent double-counting on concurrent triggers.
        _TP.objects.filter(id=fresh.id).update(pending_referral_code=None)
        return code

    pending_code = await _consume_pending_ref()
    if pending_code:
        try:
            from tgbot.services.referral import ReferralService
            await ReferralService.process_referral(user, pending_code)
        except Exception as e:
            print(f"deferred referral processing failed: {e}")

    await state.finish()
