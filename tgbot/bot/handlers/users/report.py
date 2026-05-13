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


# ── Book-type selection ──────────────────────────────────────────────────────

def _book_type_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(text="📖 Jonli kitob", callback_data="book_type:live"),
        InlineKeyboardButton(text="🎧 Audiokitob",  callback_data="book_type:audio"),
    )
    markup.add(
        InlineKeyboardButton(text="📖🎧 Ikkalasi ham", callback_data="book_type:both"),
    )
    return markup


async def send_book_type_menu(message_or_call, state: FSMContext):
    text = "Qanday kitob o'qidingiz / eshitdingiz?"
    markup = _book_type_markup()
    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.answer(text, reply_markup=markup)
    else:
        await message_or_call.answer(text, reply_markup=markup)
    await ReportState.book_type.set()


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("book_type:"),
    state=ReportState.book_type,
)
async def book_type_handler(call: CallbackQuery, state: FSMContext):
    book_type = call.data.split(":")[1]
    is_audio = book_type == "audio"
    is_combined = book_type == "both"
    await state.update_data(is_audio=is_audio, is_combined=is_combined)
    await call.answer()
    await ReportState.select_book.set()
    await send_book_selection_menu(call, state)


# ── Book selection ───────────────────────────────────────────────────────────

async def send_book_selection_menu(message_or_call, state: FSMContext, page=1):
    data = await state.get_data()
    selected_book_ids = data.get("selected_book_ids", [])
    user = get_user(message_or_call.from_user.id)

    books_page = await get_user_books(user, page)

    markup = InlineKeyboardMarkup(row_width=1)

    for book in books_page:
        text = book.title
        percent = 0
        if book.total_pages > 0:
            percent = int((book.current_page / book.total_pages) * 100)
        text = f"{text} ({percent}%)"
        if book.id in selected_book_ids:
            text = f"✅ {text}"
        markup.add(InlineKeyboardButton(text=text,
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
        text="➕ Yangi kitob qo'shish", callback_data="add_new_book"))

    text = _(
        "Qaysi kitobni o'qiyotganingizni tanlang (bir nechtasini tanlash mumkin):")

    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.edit_text(text, reply_markup=markup)
    else:
        await message_or_call.answer(text, reply_markup=markup)


# ── CTA inline button (from broadcast messages) ──────────────────────────────

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

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await send_book_type_menu(call, state)


# ── Reply-keyboard "📚 Kitob hisoboti" button ────────────────────────────────

@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="📚 Kitob hisoboti", state="*")
@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="📚 Отчет о книге", state="*")
async def send_daily_report_handler(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user.is_blocked:
        await message.answer(_("Siz bot tomonidan bloklangansiz."))
        return await state.finish()

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
    await send_book_type_menu(message, state)


# ── Book selection callbacks ──────────────────────────────────────────────────

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
    is_audio = data.get("is_audio", False)
    question = "Kitob jami necha daqiqa davom etadi?" if is_audio else _("Kitob jami nechi betdan iborat?")
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
    user = get_user(message.from_user.id)

    new_book = await create_new_book(user, book_title, total_pages)

    selected_book_ids = data.get("selected_book_ids", [])
    if new_book.id not in selected_book_ids:
        selected_book_ids.append(new_book.id)

    await state.update_data(selected_book_ids=selected_book_ids)
    await message.answer(_("Kitob qo'shildi va tanlandi! ✅"))

    await ReportState.select_book.set()
    await send_book_selection_menu(message, state)


# ── Per-book value entry loop (pages for live, minutes for audio) ─────────────

async def ask_next_book_pages(message, state: FSMContext):
    data = await state.get_data()
    pending_books = data.get("pending_books", [])
    is_audio = data.get("is_audio", False)
    is_combined = data.get("is_combined", False)

    if not pending_books:
        reports = data.get("book_reports", {})
        total = sum(reports.values())
        if is_audio:
            await state.update_data(minutes_listened=total, pages_read=0)
        else:
            await state.update_data(pages_read=total)
            if is_combined:
                await message.answer(
                    "🎧 Audiokitobdan bugun jami necha daqiqa eshitdingiz?",
                    reply_markup=back_keyboard,
                )
                await ReportState.audio_minutes_combined.set()
                return

        await message.answer(
            _("Kichik xulosa (bugun nima o'rgandingiz)\n\nMasalan: <i>Ilm - bu boylik</i>"),
            reply_markup=back_keyboard,
        )
        await ReportState.conclusion.set()
        return

    next_book_id = pending_books[0]
    book = await get_book_by_id(next_book_id)

    if is_audio:
        await message.answer(
            f"🎧 <b>{book.title}</b> kitobidan bugun necha daqiqa eshitdingiz?",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"📖 <b>{book.title}</b> kitobidan bugun nechi bet o'qidingiz? "
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


@dp.message_handler(state=ReportState.audio_minutes_combined)
async def process_combined_audio_minutes(message: types.Message, state: FSMContext):
    if message.text == _("🔙 Orqaga"):
        await ReportState.select_book.set()
        await send_book_selection_menu(message, state)
        return
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer(_("Iltimos, to'g'ri raqam kiriting."))
        return
    await state.update_data(minutes_listened=int(message.text))
    await message.answer(
        _("Kichik xulosa (bugun nima o'rgandingiz)\n\nMasalan: <i>Ilm - bu boylik</i>"),
        reply_markup=back_keyboard,
    )
    await ReportState.conclusion.set()


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

    user = get_user(message.from_user.id)
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
        type_label = "📖 Jonli kitob + 🎧 Audiokitob"
    elif is_audio:
        minutes_listened = data.get("minutes_listened", 0)
        value_line = f"<b>🎧 Eshitilgan vaqt:</b> {minutes_listened} daqiqa"
        type_label = "🎧 Audiokitob"
    else:
        pages_read = data.get("pages_read", 0)
        value_line = f"<b>✅O'qilgan betlar:</b> {pages_read}+ bet"
        type_label = "📖 Jonli kitob"

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

    message = call.message
    try:
        message.from_user = call.from_user
    except Exception:
        pass
    await _do_confirm_report(message, user, state)


async def _do_confirm_report(message, user, state: FSMContext):
    today = timezone.localdate()

    if await get_confirmation_report_exists(user, today):
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
    pages_read = data.get("pages_read", 0)
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

    data = await state.get_data()
    book_reports = data.get("book_reports", {})

    for bid, p_read in book_reports.items():
        try:
            book_obj = await get_book_by_id(bid)
            if book_obj:
                if not is_audio:
                    # Only update page progress for live books
                    book_obj.current_page += p_read
                    if book_obj.current_page > book_obj.total_pages:
                        book_obj.current_page = book_obj.total_pages
                    await sync_to_async(book_obj.save)()

                from tgbot.models import BookReport
                await sync_to_async(BookReport.objects.create)(
                    user=user,
                    reading_day=reading_day,
                    book=book_obj.title,
                    pages_read=p_read,
                )
        except Exception as e:
            print(f"Error updating book {bid}: {e}")

    from tgbot.models import Payment

    @sync_to_async
    def _check_premium():
        return Payment.objects.filter(
            user=user, status="paid", end_date__gte=timezone.localdate()
        ).exists()

    prem_badge = "💎 " if await _check_premium() else ""

    if is_combined:
        value_line = (
            f"<b>✅ O'qilgan betlar:</b> {pages_read}+ bet\n"
            f"<b>🎧 Eshitilgan vaqt:</b> {minutes_listened} daqiqa"
        )
        type_tag = "📖 Jonli kitob + 🎧 Audiokitob"
    elif is_audio:
        value_line = f"<b>🎧 Eshitilgan vaqt:</b> {minutes_listened} daqiqa"
        type_tag = "🎧 Audiokitob"
    else:
        value_line = f"<b>✅O'qilgan betlar:</b> {pages_read}+ bet"
        type_tag = "📖 Jonli kitob"

    report_message = (
        f"<b><a href='tg://user?id={user.telegram_id}'>{prem_badge}{user.full_name}</a></b>:\n\n"
        f"📊#kun - {reading_day}  ({report.date.strftime('%Y-%m-%d')})\n\n"
        f"<b>Tur:</b> {type_tag}\n\n"
        f"<b>Kitob nomi:</b> {book}\n\n"
        f"{value_line}\n\n"
        f"<b>💡Olingan xulosa:</b> {conclusion}\n\n"
        f"<b>Haqiqiy peshqadam 🏆</b>"
    )

    if not user:
        await state.finish()
        return

    target_chat_id = None
    target_thread_id = None

    if is_audio:
        # Audiobook reports go to B-tier thread (no page count for routing)
        routing_pages = 0
    else:
        try:
            routing_pages = int(pages_read)
        except (ValueError, TypeError):
            routing_pages = 0

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

    await state.finish()
