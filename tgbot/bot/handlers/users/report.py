import random
import asyncio
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from django.db.models import Sum
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
def create_new_book(user, title, total_pages, is_audio=False, global_book_id=None):
    from tgbot.models import GlobalBook, normalize_uzbek_text
    gbook = None
    if global_book_id:
        try:
            gbook = GlobalBook.objects.get(id=global_book_id)
        except GlobalBook.DoesNotExist:
            pass

    if not gbook:
        normalized = normalize_uzbek_text(title)
        gbook = GlobalBook.objects.filter(normalized_title=normalized).first()
        if not gbook:
            gbook = GlobalBook.objects.filter(title__iexact=title.strip()).first()
            if not gbook:
                try:
                    gbook = GlobalBook.objects.create(title=title.strip())
                except Exception:
                    gbook = GlobalBook.objects.filter(normalized_title=normalized).first()

    return BooksToRead.objects.create(
        user=user,
        global_book=gbook,
        title=gbook.title if gbook else title,
        total_pages=total_pages,
        is_audio=is_audio
    )


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
        .prefetch_related("books")
        .order_by("date")
    )


def _format_conclusions_block(reports):
    """Build a quote-blockquote with all today's conclusions, attributing each
    to its book(s) only when ambiguous (multiple distinct books across reports).
    Returns empty string if no non-empty conclusions exist.
    """
    items = []
    all_titles = set()
    for r in reports:
        text = (r.conclusion or "").strip()
        if not text:
            continue
        titles = [b.title for b in r.books.all() if b.title] or ([r.book] if r.book else [])
        titles = [t for t in titles if t]
        all_titles.update(titles)
        items.append((titles, text))

    if not items:
        return ""

    # If everything came from the same single book, no need to label each one.
    show_label = len(all_titles) > 1

    seen = set()
    lines = []
    for titles, text in items:
        key = (tuple(titles), text)
        if key in seen:
            continue
        seen.add(key)
        if show_label and titles:
            label = ", ".join(titles)
            lines.append(f"<b>{label}:</b> {text}")
        else:
            lines.append(text)

    body = "\n\n".join(lines)
    return (
        "<b>💡 Olingan xulosalar:</b>\n"
        f"<blockquote expandable>{body}</blockquote>"
    )


MOTIVATIONS = [
    "Kitob — tafakkur qanotidir. ✨",
    "Har bir o'qilgan sahifa — kelajakka qadam! 🚀",
    "Bilim — eng kuchli qurol. Uni egallashdan to'xtamang! 💡",
    "Kitob o'qish orqali dunyoni o'zgartira olasiz. 🌍",
    "Bugun kitobxon, ertaga yetakchi! 🏆",
    "Muvaffaqiyat kaliti — tinimsiz izlanishda. 🔑",
    "Har bir sahifada yangi dunyo yashirin. 🗺",
    "O'qish — ongni charxlaydi. 🧠",
    "Bilim bilan yo'lingiz doim yorug' bo'ladi. 🌟",
    "Katta natijalar kichik qadamlardan boshlanadi! 💪",
    "Ziyolilik sari yana bir odim. Olg'a! ⚡️",
    "Kitob sizga eng yaxshi do'st va maslahatgo'ydir. 🤝",
    "O'rganishdan hech qachon charchamang. 📚",
    "Har kunlik mutolaa — buyuklik poydevori. 🏛",
    "Bilim — zanglamas boylik. 💎",
    "Kitob o'qish — kelajak sarmoyasidir. 📈",
    "Mutolaa ongni erkin qiladi. 🕊",
    "Ilm bilan yuksaklikka erishasiz. 🏔",
    "O'qish orqali tasavvuringiz cheksiz bo'ladi. 🌌",
    "Siz o'qigan kitoblar kelajagingizni belgilaydi. 🔮",
    "Har bir muvaffaqiyatli inson — ashaddiy kitobxondir. 😎",
    "Bilim oling, u sizni yuksaltiradi. 🧗",
    "Kitoblar sizga hayot yo'llarini ochadi. 🛤",
    "Ziyoda bilim — ziyoda kuchdir! 🔥",
    "Kunlik o'qish odati sizni yengilmas qiladi. 🛡",
    "Mutolaa — qalb va ruh ozuqasi. 🍃",
    "Har bir sahifa — donolik sari yo'l. 🎓",
    "Kitob o'qish orqali o'zligingizni toping. 🧩",
    "O'qigan inson har qanday to'siqni yengadi. 🚧",
    "Bilim — zulmatdagi nurdir. 🕯",
    "Siz o'qiyotgan har bir sahifa zoe ketmaydi. 💎",
    "Buyuk maqsadlar tomon olg'a! 🎯",
    "Kitob o'qing va dunyoqarashingizni kengaytiring. 🔭",
    "Bilimdonlik — haqiqiy go'zallikdir. 🌸",
    "O'rganishda davom eting, chegara yo'q! ♾",
    "Mutolaa — fikrlar sayohati. ✈️",
    "Kitob ko'ngil ko'zgusidir. 🪞",
    "Har bir kitob — yangi hayot. 🐣",
    "Bilim sizni barcha eshiklarni ochishga qodir qiladi. 🚪",
    "Kitob bilan o'tgan vaqt — eng unumli vaqtdir. ⏰",
    "Dunyoni o'qish orqali zabt eting! 👑",
    "Kitob — eng sodiq hamroh. 🧭",
    "O'qishdan to'xtagan inson fikrlashdan ham to'xtaydi. 🚦",
    "Ilm o'rganish — eng oliy ibodat. 🙏",
    "Bilim yuksalishning yagona yo'lidir. 📈",
    "Har kuni bir sahifa o'qish ham katta g'alaba. 🏅",
    "Kitoblar sizga maqsadlaringiz sari kuch beradi. 🔋",
    "Aqlingizni kitob bilan oziqlantiring. 🍎",
    "Bilim — hayot chirog'idir. 💡",
    "Mutolaa bilan har kuningiz mazmunli bo'lsin! ✨"
]


@sync_to_async
def _today_books_with_type(user, today):
    """Deduplicated [(title, is_audio), ...] across all today's reports' M2M books."""
    seen = {}
    qs = (
        ConfirmationReport.objects
        .filter(user=user, date__date=today)
        .prefetch_related("books")
    )
    for r in qs:
        for b in r.books.all():
            if b.id not in seen:
                seen[b.id] = (b.title, b.is_audio)
    return list(seen.values())


@sync_to_async
def _get_today_books_aggregated(user, today):
    from tgbot.models import BookReport, BooksToRead
    reports = BookReport.objects.filter(user=user, created_at__date=today)
    book_sums = {}
    for r in reports:
        book_sums[r.book] = book_sums.get(r.book, 0) + r.pages_read

    books_with_type = []
    for title, total_val in book_sums.items():
        b_obj = BooksToRead.objects.filter(user=user, title=title).first()
        is_audio = b_obj.is_audio if b_obj else False
        books_with_type.append((title, is_audio, total_val))
    return books_with_type


def _format_books_block(books_with_type, fallback_title=None):
    """Render a block of read books:
    O'qilgan kitoblar:

    🎧 O'tkan kunlar: 1 daqiqa
    📖 Nemo: 12+ bet

    Jami: 📖 12+ bet · 🎧 1 daqiqa
    """
    if not books_with_type:
        if fallback_title:
            return f"<b>O'qilgan kitoblar:</b>\n\n📄 {fallback_title}"
        return "<b>O'qilgan kitoblar:</b>\n\nTanlanmagan"

    lines = []
    total_pages = 0
    total_minutes = 0
    book_count = 0
    audio_count = 0
    live_count = 0
    has_quantities = False

    for item in books_with_type:
        if len(item) == 3:
            title, is_audio, val = item
            icon = "🎧" if is_audio else "📖"
            unit = "daqiqa" if is_audio else "bet"
            plus = "" if is_audio else "+"
            lines.append(f"{icon} {title}: {val}{plus} {unit}")
            has_quantities = True
            book_count += 1
            if is_audio:
                total_minutes += val or 0
                audio_count += 1
            else:
                total_pages += val or 0
                live_count += 1
        else:
            title, is_audio = item
            icon = "🎧" if is_audio else "📖"
            lines.append(f"{icon} {title}")
            book_count += 1
            if is_audio:
                audio_count += 1
            else:
                live_count += 1

    body = "\n".join(lines)
    # Show a totals footer only when there are multiple books AND we have quantities
    if has_quantities and book_count > 1 and (live_count > 0 or audio_count > 0):
        totals = []
        if live_count > 0:
            totals.append(f"📖 {total_pages}+ bet")
        if audio_count > 0:
            totals.append(f"🎧 {total_minutes} daqiqa")
        body += "\n\n<b>Jami:</b> " + " · ".join(totals)

    return "<b>O'qilgan kitoblar:</b>\n\n" + body


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
        # Row with book selector button only, no settings button to clean up selection UI
        markup.add(
            InlineKeyboardButton(text=label, callback_data=f"select_book:{book.id}:{page}")
        )

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
    # If tapped inside a group/channel, the report flow can't run there — open
    # the bot's private chat instead. answerCallbackQuery's url is allowed to be
    # the bot's own deep link, which opens the DM and sends /start report.
    if call.message and getattr(call.message.chat, "type", "private") != "private":
        try:
            bot_username = (await call.bot.get_me()).username
            await call.answer(url=f"https://t.me/{bot_username}?start=report")
        except Exception:
            await call.answer("Hisobot yuborish uchun botga shaxsiy yozing 👇", show_alert=True)
        return

    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing", show_alert=True)
        return
    if user.is_blocked:
        await call.answer(
            _("Hisobingiz cheklangan. Admin bilan bog'lanish tugmasi orqali murojaat qiling."),
            show_alert=True,
        )
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
        await message.answer(
            "🚫 <b>Sizning hisobingiz cheklangan.</b>\n\n"
            "Hisobot yubora olmaysiz. <b>📞 Admin bilan bog'lanish</b> "
            "tugmasi orqali murojaat qiling.",
            parse_mode="HTML",
        )
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
        type_kb.add(
            InlineKeyboardButton("🔙 Orqaga", callback_data="add_book_back")
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

    elif call.data == "add_book_back":
        await send_book_selection_menu(call, state)
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

    from tgbot.models import GlobalBook, normalize_uzbek_text

    normalized_query = normalize_uzbek_text(book_title)

    matches = await sync_to_async(list)(
        GlobalBook.objects.filter(normalized_title__icontains=normalized_query)[:5]
    )

    if not matches:
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("➕ Shu nomda yangi kitob qo'shish", callback_data="create_global_book"),
            InlineKeyboardButton("🔙 Orqaga", callback_data="add_book_back"),
        )
        text = (
            f"❌ <b>Bunday kitob hali yo'q ekan</b>\n\n"
            f"<b>«{book_title}»</b> nomli kitob bazamizda topilmadi.\n\n"
            f"Siz uni birinchi bo'lib qo'shishingiz mumkin — "
            f"keyingi boshqa foydalanuvchilar qidirganda ham ko'rinadi! 📚"
        )
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        kb = InlineKeyboardMarkup(row_width=1)
        for gbook in matches:
            kb.add(InlineKeyboardButton(f"📖 {gbook.title}", callback_data=f"select_global_book:{gbook.id}"))
        kb.add(
            InlineKeyboardButton("➕ Boshqa kitob qo'shish (ro'yxatda yo'q)", callback_data="create_global_book"),
            InlineKeyboardButton("🔙 Orqaga", callback_data="add_book_back"),
        )
        text = (
            f"✅ <b>Quyidagi kitoblar topildi:</b>\n\n"
            f"Siz qidirayotgan kitobni tanlang.\n"
            f"Agar ro'yxatda yo'q bo'lsa — «➕ Boshqa kitob qo'shish»ni bosing:"
        )
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query_handler(
    lambda c: c.data == "create_global_book"
    or c.data == "add_book_back"
    or c.data.startswith("select_global_book:"),
    state=ReportState.enter_book_name,
)
async def process_global_book_choice(call: CallbackQuery, state: FSMContext):
    await call.answer()

    # Back → return to book selection menu
    if call.data == "add_book_back":
        try:
            await call.message.delete()
        except Exception:
            pass
        await ReportState.select_book.set()
        await send_book_selection_menu(call.message, state)
        return

    if call.data == "create_global_book":
        await state.update_data(global_book_id=None)
    else:
        global_book_id = int(call.data.split(":")[1])
        await state.update_data(global_book_id=global_book_id)

        from tgbot.models import GlobalBook
        gbook = await sync_to_async(GlobalBook.objects.filter(id=global_book_id).first)()
        if gbook:
            await state.update_data(new_book_title=gbook.title)

    data = await state.get_data()
    new_book_is_audio = data.get("new_book_is_audio", False)
    question = "Kitob jami necha daqiqa davom etadi?" if new_book_is_audio else _("Kitob jami nechi betdan iborat?")

    try:
        await call.message.delete()
    except Exception:
        pass

    await call.message.answer(question, reply_markup=back_keyboard)
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
    global_book_id = data.get("global_book_id")
    user = await aget_user(message.from_user.id)

    # Smart default: if user picked "Oddiy kitob" but the title obviously
    # says audiobook, auto-flip — prevents the most common add-flow mistake.
    title_l = (book_title or "").lower()
    audio_keywords = ("audio", "аудио", "audiokitob", "audiobook")
    if not new_book_is_audio and any(kw in title_l for kw in audio_keywords):
        new_book_is_audio = True

    new_book = await create_new_book(
        user,
        book_title,
        total_pages,
        is_audio=new_book_is_audio,
        global_book_id=global_book_id
    )

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


@dp.message_handler(state=ReportState.edit_book_title)
async def process_edit_book_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    book_id = data.get("edit_book_id")
    page = data.get("edit_book_page", 1)
    source = data.get("edit_book_source", "")

    if message.text == _("🔙 Orqaga"):
        if source == "cab":
            await send_cabinet_books_management(message, state, page)
        else:
            await ReportState.select_book.set()
            await send_book_selection_menu(message, state, page)
        return

    new_title = message.text.strip()
    if len(new_title) > 120:
        await message.answer(_("Iltimos, kitobni nomi uzun bo'lmasin!"))
        return

    book = await get_book_by_id(book_id)
    if book:
        book.title = new_title
        await sync_to_async(book.save)()
        await message.answer("Kitob nomi muvaffaqiyatli o'zgartirildi! ✅")

    if source == "cab":
        await send_cabinet_books_management(message, state, page)
    else:
        await ReportState.select_book.set()
        await send_book_selection_menu(message, state, page)


@dp.message_handler(state=ReportState.edit_book_pages)
async def process_edit_book_pages(message: types.Message, state: FSMContext):
    data = await state.get_data()
    book_id = data.get("edit_book_id")
    page = data.get("edit_book_page", 1)
    source = data.get("edit_book_source", "")

    if message.text == _("🔙 Orqaga"):
        if source == "cab":
            await send_cabinet_books_management(message, state, page)
        else:
            await ReportState.select_book.set()
            await send_book_selection_menu(message, state, page)
        return

    pages_str = message.text
    if not pages_str.isdigit() or int(pages_str) <= 0:
        await message.answer(_("Iltimos, to'g'ri son kiriting."))
        return

    total_pages = int(pages_str)
    book = await get_book_by_id(book_id)
    if book:
        book.total_pages = total_pages
        if book.current_page > total_pages:
            book.current_page = total_pages
        await sync_to_async(book.save)()
        await message.answer("Kitob sahifalar/daqiqalar soni muvaffaqiyatli yangilandi! ✅")

    if source == "cab":
        await send_cabinet_books_management(message, state, page)
    else:
        await ReportState.select_book.set()
        await send_book_selection_menu(message, state, page)


# ── Cabinet Book Management UI & Callback Handlers ───────────────────────────

async def send_cabinet_books_management(message_or_call, state: FSMContext, page=1):
    user = await aget_user(message_or_call.from_user.id)
    books_page = await get_user_books(user, page)

    markup = InlineKeyboardMarkup(row_width=1)

    for book in books_page:
        type_icon = "🎧" if book.is_audio else "📖"
        percent = 0
        if book.total_pages > 0:
            percent = int((book.current_page / book.total_pages) * 100)
        label = f"{type_icon} {book.title} ({percent}%)"
        markup.add(
            InlineKeyboardButton(text=label, callback_data=f"manage_book:{book.id}:{page}:cab")
        )

    nav_buttons = []
    if books_page.has_previous():
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"cab_books_page:{books_page.previous_page_number()}"))
    nav_buttons.append(InlineKeyboardButton(
        text=f"{page}/{books_page.paginator.num_pages}", callback_data="noop"))
    if books_page.has_next():
        nav_buttons.append(InlineKeyboardButton(
            text="➡️", callback_data=f"cab_books_page:{books_page.next_page_number()}"))
    if nav_buttons:
        markup.row(*nav_buttons)

    # Localized text and back buttons
    lang = (user.language if user else "uz") or "uz"
    if lang == "ru":
        back_label = "🔙 Вернуться в настройки"
        text = "⚙️ <b>Управление книгами:</b>\n\nВыберите книгу для редактирования или удаления:"
    else:
        back_label = "🔙 Sozlamalarga qaytish"
        text = "⚙️ <b>Kitoblarni boshqarish:</b>\n\nTahrirlash yoki o'chirish uchun kitobni tanlang:"

    markup.add(InlineKeyboardButton(text=back_label, callback_data="cab:back_to_settings"))

    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message_or_call.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.callback_query_handler(lambda c: c.data.startswith("cab:manage_books"), state="*")
async def cab_manage_books_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 1
    await send_cabinet_books_management(call, state, page)


@dp.callback_query_handler(lambda c: c.data.startswith("cab_books_page:"), state="*")
async def cab_books_page_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    page = int(call.data.split(":")[1])
    await send_cabinet_books_management(call, state, page)


@dp.callback_query_handler(lambda c: c.data == "cab:back_to_settings", state="*")
async def back_to_settings_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user = await aget_user(call.from_user.id)
    try:
        await call.message.delete()
    except Exception:
        pass
    from tgbot.bot.handlers.users.menu_router import _menu_settings
    await _menu_settings(call, user, state)


# ── State-Agnostic Book Management Callbacks ────────────────────────────

@dp.callback_query_handler(lambda c: c.data.startswith("manage_book:"), state="*")
async def process_manage_book(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    book_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1
    source = parts[3] if len(parts) > 3 else ""

    book = await get_book_by_id(book_id)
    if not book:
        await call.answer("Kitob topilmadi.", show_alert=True)
        return

    await call.answer()
    type_label = "Audiokitob" if book.is_audio else "Oddiy kitob"
    type_icon = "🎧" if book.is_audio else "📖"
    unit = "daqiqa" if book.is_audio else "bet"
    percent = 0
    if book.total_pages > 0:
        percent = int((book.current_page / book.total_pages) * 100)

    text = (
        f"⚙️ <b>Kitobni boshqarish:</b> \"{book.title}\"\n\n"
        f"Turi: {type_icon} {type_label}\n"
        f"Jami: {book.total_pages} {unit}\n"
        f"O'qilgan/eshitilgan: {book.current_page} {unit} ({percent}%)\n\n"
        f"Tuzatmoqchi bo'lsangiz quyidagi amallardan birini tanlang:"
    )

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("✏️ Nomini o'zgartirish", callback_data=f"edit_book_title_btn:{book.id}:{page}:{source}"),
        InlineKeyboardButton("📄 Jami bet/daqiqasini o'zgartirish", callback_data=f"edit_book_pages_btn:{book.id}:{page}:{source}"),
        InlineKeyboardButton("🗑 Kitobni o'chirib tashlash", callback_data=f"delete_book_confirm_btn:{book.id}:{page}:{source}"),
        InlineKeyboardButton("🔙 Orqaga", callback_data=f"cab_books_page:{page}" if source == "cab" else f"books_page:{page}")
    )

    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query_handler(lambda c: c.data.startswith("edit_book_title_btn:"), state="*")
async def process_edit_book_title_btn(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    book_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1
    source = parts[3] if len(parts) > 3 else ""

    book = await get_book_by_id(book_id)
    if not book:
        await call.answer("Kitob topilmadi.", show_alert=True)
        return

    await call.answer()
    await state.update_data(edit_book_id=book_id, edit_book_page=page, edit_book_source=source)
    await ReportState.edit_book_title.set()

    await call.message.delete()
    await call.message.answer(
        f"\"{book.title}\" kitobi uchun yangi nom kiriting:",
        reply_markup=back_keyboard
    )


@dp.callback_query_handler(lambda c: c.data.startswith("edit_book_pages_btn:"), state="*")
async def process_edit_book_pages_btn(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    book_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1
    source = parts[3] if len(parts) > 3 else ""

    book = await get_book_by_id(book_id)
    if not book:
        await call.answer("Kitob topilmadi.", show_alert=True)
        return

    await call.answer()
    await state.update_data(edit_book_id=book_id, edit_book_page=page, edit_book_source=source)
    await ReportState.edit_book_pages.set()

    await call.message.delete()
    unit = "daqiqa" if book.is_audio else "bet"
    await call.message.answer(
        f"\"{book.title}\" kitobining jami {unit}lar sonini kiriting:",
        reply_markup=back_keyboard
    )


@dp.callback_query_handler(lambda c: c.data.startswith("delete_book_confirm_btn:"), state="*")
async def process_delete_book_confirm_btn(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    book_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1
    source = parts[3] if len(parts) > 3 else ""

    book = await get_book_by_id(book_id)
    if not book:
        await call.answer("Kitob topilmadi.", show_alert=True)
        return

    await call.answer()
    text = f"⚠️ Haqiqatdan ham \"{book.title}\" kitobini o'chirib tashlamoqchimisiz?\n\nBu amalni ortga qaytarib bo'lmaydi!"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🗑 Ha, o'chirish", callback_data=f"delete_book_yes:{book.id}:{page}:{source}"),
        InlineKeyboardButton("❌ Yo'q", callback_data=f"manage_book:{book.id}:{page}:{source}")
    )
    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith("delete_book_yes:"), state="*")
async def process_delete_book_yes_btn(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    book_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1
    source = parts[3] if len(parts) > 3 else ""

    book = await get_book_by_id(book_id)
    if book:
        data = await state.get_data()
        selected_book_ids = data.get("selected_book_ids", [])
        if book_id in selected_book_ids:
            selected_book_ids.remove(book_id)
            await state.update_data(selected_book_ids=selected_book_ids)

        await sync_to_async(book.delete)()
        await call.answer("Kitob o'chirildi.", show_alert=True)
    else:
        await call.answer("Kitob topilmadi.", show_alert=True)

    if source == "cab":
        await send_cabinet_books_management(call, state, page)
    else:
        await send_book_selection_menu(call, state, page)


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


MAX_PAGES_PER_DAY = 1000
MAX_AUDIO_MINUTES_PER_DAY = 600  # 10 hours/day cap


@sync_to_async
def _today_committed_totals(user, today):
    """Pages and audio minutes already saved to ConfirmationReport today.
    Used for the daily cap check on each new per-book value entry."""
    pages = (
        ConfirmationReport.objects
        .filter(user=user, date__date=today, is_audio=False)
        .aggregate(s=Sum("pages_read"))["s"] or 0
    )
    minutes = (
        ConfirmationReport.objects
        .filter(user=user, date__date=today, is_audio=True)
        .aggregate(s=Sum("minutes_listened"))["s"] or 0
    )
    return pages, minutes


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

    current_book_id = pending_books[0]
    current_book = await get_book_by_id(current_book_id)

    # Daily caps: include both already-confirmed reports submitted earlier
    # today (e.g. Premium aggregation) AND values entered so far in this
    # same in-progress submission.
    user = await aget_user(message.from_user.id)
    today = timezone.localdate()
    committed_pages, committed_audio = await _today_committed_totals(user, today)

    pending_pages = 0
    pending_audio = 0
    for bid, v in reports.items():
        b = await get_book_by_id(int(bid))
        if not b:
            continue
        if b.is_audio:
            pending_audio += v
        else:
            pending_pages += v

    if current_book and current_book.is_audio:
        used = committed_audio + pending_audio
        if used + value > MAX_AUDIO_MINUTES_PER_DAY:
            remaining = max(0, MAX_AUDIO_MINUTES_PER_DAY - used)
            await message.answer(
                f"❌ Kuniga maksimal eshitish vaqti: <b>{MAX_AUDIO_MINUTES_PER_DAY} daqiqa (10 soat)</b>.\n\n"
                f"Bugun jami eshitganingiz: <b>{used} daqiqa</b>.\n"
                f"Iltimos, <b>{remaining}</b> daqiqadan ko'p bo'lmagan qiymat kiriting.",
                parse_mode="HTML",
            )
            return
    else:
        used = committed_pages + pending_pages
        if used + value > MAX_PAGES_PER_DAY:
            remaining = max(0, MAX_PAGES_PER_DAY - used)
            await message.answer(
                f"❌ Kuniga maksimal o'qish: <b>{MAX_PAGES_PER_DAY} bet</b>.\n\n"
                f"Bugun jami o'qiganingiz: <b>{used} bet</b>.\n"
                f"Iltimos, <b>{remaining}</b> betdan ko'p bo'lmagan qiymat kiriting.",
                parse_mode="HTML",
            )
            return

    pending_books.pop(0)
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

    # Cap raised 400 → 1000 so review/taqriz challenges (which require 200+
    # chars) have real headroom instead of a tight 200–400 window.
    if len(conclusion) > 1000:
        await message.answer(
            _("Iltimos, xulosa matnini 1000 ta belgidan uzun bo'lmasin!"),
            reply_markup=back_keyboard,
        )
        return

    await state.update_data(conclusion=conclusion)

    user = await aget_user(message.from_user.id)
    today = timezone.localdate()

    data = await state.get_data()
    # Fall back to 1 if the FSM lost reading_day (e.g. partial state after a
    # restart) so the report flow can't crash with KeyError here.
    reading_day = data.get('reading_day') or 1
    is_audio = data.get("is_audio", False)

    book = data.get('book_title')
    book_reports = data.get("book_reports", {})
    books_with_type = []
    if book_reports:
        titles = []
        for bid in book_reports.keys():
            b_obj = await get_book_by_id(bid)
            if b_obj:
                titles.append(b_obj.title)
                books_with_type.append((b_obj.title, b_obj.is_audio))
        if not book:
            book = ", ".join(titles)
            await state.update_data(book_title=book)
    if not book:
        book = "Tanlanmagan"

    if book_reports:
        books_block = _format_books_block(books_with_type, fallback_title=book)
    else:
        pages_read = data.get("pages_read", 0) or 0
        minutes_listened = data.get("minutes_listened", 0) or 0
        is_audio = data.get("is_audio", False)
        is_combined = data.get("is_combined", False)
        if is_combined:
            books_block = f"<b>O'qilgan kitoblar:</b>\n\n📖 {book} ({pages_read}+ bet)\n🎧 {book} ({minutes_listened} daqiqa)"
        elif is_audio:
            books_block = f"<b>O'qilgan kitoblar:</b>\n\n🎧 {book} ({minutes_listened} daqiqa)"
        else:
            books_block = f"<b>O'qilgan kitoblar:</b>\n\n📖 {book} ({pages_read}+ bet)"

    motivation = random.choice(MOTIVATIONS)
    await state.update_data(motivation=motivation)

    confirmation_message = (
        f"<b><a href='tg://user?id={user.telegram_id}'>{user.full_name}</a></b>:\n\n"
        f"📊#kun - {reading_day}  ({today})\n\n"
        f"{books_block}\n\n"
        f"<b>💡Olingan xulosa:</b> {conclusion}\n\n"
        f"<b>{motivation}</b>\n\n"
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
                    global_book=book_obj.global_book,
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

    today_books = await _get_today_books_aggregated(user, today)
    if today_books:
        books_block = _format_books_block(today_books, fallback_title=book)
    else:
        if has_pages and has_audio:
            books_block = f"<b>O'qilgan kitoblar:</b>\n\n📖 {book} ({total_pages}+ bet)\n🎧 {book} ({total_minutes} daqiqa)"
        elif has_audio:
            books_block = f"<b>O'qilgan kitoblar:</b>\n\n🎧 {book} ({total_minutes} daqiqa)"
        else:
            books_block = f"<b>O'qilgan kitoblar:</b>\n\n📖 {book} ({total_pages}+ bet)"

    aggregate_note = ""
    if is_aggregating:
        n = len(todays)
        aggregate_note = f"\n\n<i>💎 {n} ta hisobot jamlandi</i>"

    motivation = data.get("motivation") or random.choice(MOTIVATIONS)

    conclusions_block = _format_conclusions_block(todays)
    if not conclusions_block and conclusion:
        conclusions_block = (
            "<b>💡 Olingan xulosa:</b>\n"
            f"<blockquote expandable>{conclusion}</blockquote>"
        )

    report_message = (
        f"<b><a href='tg://user?id={user.telegram_id}'>{prem_badge}{user.full_name}</a></b>:\n\n"
        f"📊#kun - {reading_day}  ({report.date.strftime('%Y-%m-%d')})\n\n"
        f"{books_block}\n\n"
        f"{conclusions_block}\n\n"
        f"<b>{motivation}</b>"
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

    # Premium aggregation: edit the existing group message in-place (no delete
    # permission needed). Fall back to delete+send if the edit fails.
    final_group_chat_id = target_chat_id
    final_group_message_id = None
    final_group_thread_id = target_thread_id
    edited_in_place = False

    if is_aggregating:
        latest_with_msg = next(
            (p for p in reversed(prior_reports) if p.group_chat_id and p.group_message_id),
            None,
        )
        if latest_with_msg and latest_with_msg.group_chat_id == target_chat_id:
            try:
                await bot.edit_message_text(
                    chat_id=latest_with_msg.group_chat_id,
                    message_id=latest_with_msg.group_message_id,
                    text=report_message,
                    parse_mode='HTML',
                )
                final_group_chat_id = latest_with_msg.group_chat_id
                final_group_message_id = latest_with_msg.group_message_id
                final_group_thread_id = latest_with_msg.group_thread_id
                edited_in_place = True
            except Exception as e:
                print(f"edit_group_msg failed, falling back to delete+send: {e}")

        if not edited_in_place:
            # Fallback: delete all prior group messages then send a fresh one.
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

        # Clear group-message references on all prior reports.
        await sync_to_async(
            ConfirmationReport.objects.filter(user=user, date__date=today).exclude(id=report.id).update
        )(group_chat_id=None, group_message_id=None, group_thread_id=None)

    if not edited_in_place and target_chat_id:
        try:
            sent_msg = await bot.send_message(
                chat_id=target_chat_id,
                message_thread_id=target_thread_id,
                text=report_message,
                parse_mode='HTML',
            )
            final_group_message_id = sent_msg.message_id
        except Exception as e:
            print(f"Error sending report to group {target_chat_id} thread {target_thread_id}: {e}")
    else:
        sent_msg = None

    if final_group_message_id:
        await sync_to_async(
            ConfirmationReport.objects.filter(id=report.id).update
        )(
            group_chat_id=final_group_chat_id,
            group_message_id=final_group_message_id,
            group_thread_id=final_group_thread_id,
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
    if final_group_message_id:
        chat_id_str = str(final_group_chat_id).lstrip("-")
        if chat_id_str.startswith("100"):
            chat_id_str = chat_id_str[3:]
        link = f"https://t.me/c/{chat_id_str}/{final_group_message_id}"
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
