from django.db.models import Count, Avg, Max, Min, Sum, F, ExpressionWrapper, DurationField
from django.db.models.functions import ExtractWeekDay, ExtractHour, Length
from django.utils import timezone
import datetime
import calendar

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher.filters import Text

from tgbot.bot.loader import dp
from tgbot.models import TelegramProfile, BookReport, ConfirmationReport, BooksToRead


def generate_calendar_markup(user_id, year, month):
    markup = InlineKeyboardMarkup(row_width=7)

    # Month and Year Header
    month_names_uz = [
        "", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
        "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"
    ]
    markup.row(InlineKeyboardButton(
        text=f"{month_names_uz[month]} {year}", callback_data="ignore"))

    # Weekdays Header
    weekdays_uz = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
    markup.row(*[InlineKeyboardButton(text=day, callback_data="ignore")
               for day in weekdays_uz])

    # Calendar Days
    month_calendar = calendar.monthcalendar(year, month)

    # Fetch user reports for this month
    reports = ConfirmationReport.objects.filter(
        user__telegram_id=user_id,
        date__year=year,
        date__month=month
    ).values_list('date__day', flat=True)

    reported_days = set(reports)

    for week in month_calendar:
        row_buttons = []
        for day in week:
            if day == 0:
                row_buttons.append(InlineKeyboardButton(
                    text=" ", callback_data="ignore"))
            else:
                text = str(day)
                cb = "ignore"
                if day in reported_days:
                    text += " ✅"
                    cb = f"cal_day:{year}-{month:02d}-{day:02d}"
                row_buttons.append(InlineKeyboardButton(text=text, callback_data=cb))
        markup.row(*row_buttons)

    return markup


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("cal_day:"), state="*")
async def calendar_day_detail(call: types.CallbackQuery):
    """Show what the user read on a specific day — title + pages + conclusion."""
    try:
        date_str = call.data.split(":", 1)[1]
        year, month, day = (int(x) for x in date_str.split("-"))
    except Exception:
        await call.answer()
        return

    user_id = call.from_user.id
    reports = ConfirmationReport.objects.filter(
        user__telegram_id=user_id,
        date__year=year, date__month=month, date__day=day,
    ).prefetch_related("books")
    reports_list = list(reports)
    if not reports_list:
        await call.answer("Bu kunda hisobot yo'q", show_alert=True)
        return

    lines = [f"📅 <b>{day:02d}.{month:02d}.{year}</b>\n"]
    for r in reports_list:
        title = (r.book or "").strip()
        if not title:
            m2m_titles = list(r.books.values_list("title", flat=True))
            title = ", ".join(m2m_titles) if m2m_titles else "—"
        conclusion = (r.conclusion or "").strip()
        lines.append(
            f"📖 <b>Kitob:</b> {title}\n"
            f"📄 <b>Betlar:</b> {r.pages_read}\n"
            f"💡 <b>Xulosa:</b> {conclusion or '—'}"
        )
    await call.answer()
    await call.message.answer("\n\n".join(lines), parse_mode="HTML")


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("cab:history"), state="*")
async def cabinet_history(call: types.CallbackQuery):
    """Premium: paginated list of all reports — date, book, pages, conclusion."""
    from tgbot.models import Payment
    from django.utils import timezone as _tz

    user_id = call.from_user.id
    is_prem = Payment.objects.filter(
        user__telegram_id=user_id,
        status="paid",
        end_date__gte=_tz.localdate(),
    ).exists()
    if not is_prem:
        await call.answer("Bu imkoniyat faqat Premium foydalanuvchilar uchun. 💎", show_alert=True)
        return

    parts = call.data.split(":")
    try:
        page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        page = 0

    per_page = 10
    offset = page * per_page

    reports = list(
        ConfirmationReport.objects.filter(user__telegram_id=user_id)
        .prefetch_related("books")
        .order_by("-date")[offset : offset + per_page + 1]
    )

    has_more = len(reports) > per_page
    reports = reports[:per_page]

    if not reports:
        await call.answer("Hisobotlar yo'q", show_alert=True)
        return

    lines = [f"📋 <b>Hisobotlaringiz tarixi</b> (sahifa {page + 1}):\n"]
    for r in reports:
        date_str = r.date.strftime("%d.%m.%Y")
        title = (r.book or "").strip()
        if not title:
            m2m_titles = list(r.books.values_list("title", flat=True))
            title = ", ".join(m2m_titles) if m2m_titles else "—"
        conclusion = (r.conclusion or "").strip()
        entry = (
            f"📅 <b>{date_str}</b> — {title}\n"
            f"📄 {r.pages_read} bet"
        )
        if conclusion:
            short = conclusion[:120] + ("…" if len(conclusion) > 120 else "")
            entry += f"\n💡 {short}"
        lines.append(entry)

    text = "\n\n".join(lines)

    kb = InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"cab:history:{page - 1}"))
    if has_more:
        nav.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"cab:history:{page + 1}"))
    if nav:
        kb.row(*nav)

    await call.answer()
    await call.message.answer(text, parse_mode="HTML", reply_markup=kb if nav else None)


@dp.callback_query_handler(lambda c: c.data == "ignore", state="*")
async def calendar_ignore(call: types.CallbackQuery):
    await call.answer()


@dp.message_handler(Text(equals=["👤 Kabinet", "👤 Cabinet", "👤 Кабинет"]), state="*")
async def show_user_cabinet(message: types.Message, state=None):
    if state is not None:
        try:
            await state.finish()
        except Exception:
            pass
    user_id = message.from_user.id

    # Get user profile
    try:
        user = TelegramProfile.objects.get(telegram_id=user_id)
    except TelegramProfile.DoesNotExist:
        await message.answer("Siz ro'yxatdan o'tmagansiz.")
        return

    # 1. Total books and pages read
    # We count completed books from ConfirmationReport or BooksToRead where current_page >= total_pages
    completed_books_count = BooksToRead.objects.filter(
        user=user,
        current_page__gte=F('total_pages'),
        total_pages__gt=0
    ).count()

    # Read totals from ConfirmationReport (it has is_audio/minutes_listened);
    # BookReport pools audio minutes into pages_read so summing it conflates
    # the two units. Pages are page-based reports; audio minutes are tracked
    # separately and shown on their own line.
    total_pages_read = ConfirmationReport.objects.filter(
        user=user, is_audio=False
    ).aggregate(total=Sum('pages_read'))['total'] or 0

    total_audio_minutes = ConfirmationReport.objects.filter(
        user=user, is_audio=True
    ).aggregate(total=Sum('minutes_listened'))['total'] or 0

    # 2. Reading speed — separate averages for pages vs audio. Average is per
    # report (≈ per active day for non-premium users who submit one daily).
    avg_pages_per_day = ConfirmationReport.objects.filter(
        user=user, is_audio=False
    ).aggregate(avg=Avg('pages_read'))['avg'] or 0

    avg_audio_per_day = ConfirmationReport.objects.filter(
        user=user, is_audio=True
    ).aggregate(avg=Avg('minutes_listened'))['avg'] or 0

    # 3. Active days (Most frequent weekdays)
    # 1=Sunday, 2=Monday, ..., 7=Saturday
    weekday_stats = BookReport.objects.filter(user=user).annotate(
        weekday=ExtractWeekDay('created_at')
    ).values('weekday').annotate(count=Count('id')).order_by('-count')

    active_days_map = {
        1: "Yakshanba", 2: "Dushanba", 3: "Seshanba", 4: "Chorshanba",
        5: "Payshanba", 6: "Juma", 7: "Shanba"
    }

    most_active_day = "Ma'lumot yo'q"
    if weekday_stats:
        top_day = weekday_stats[0]['weekday']
        most_active_day = active_days_map.get(top_day, "Noma'lum")

    # 4. Report time (Most frequent hour)
    hour_stats = BookReport.objects.filter(user=user).annotate(
        hour=ExtractHour('created_at')
    ).values('hour').annotate(count=Count('id')).order_by('-count')

    active_hour = "Ma'lumot yo'q"
    if hour_stats:
        top_hour = hour_stats[0]['hour']
        active_hour = f"{top_hour:02d}:00-{top_hour+1:02d}:00 oralig'ida"

    conclusion_text = ""

    # 6. Ranking — % ahead/behind by total pages read.
    rank_text = ""
    pages_to_overtake_text = ""
    try:
        all_user_pages = list(
            ConfirmationReport.objects
            .values('user_id')
            .annotate(total=Sum('pages_read'))
            .values_list('total', flat=True)
        )
        # Include users with zero pages so ranking reflects whole population.
        active_user_ids = {row[0] for row in ConfirmationReport.objects.values_list('user_id').distinct()}
        zero_count = max(
            TelegramProfile.objects.filter(is_registered=True).count() - len(active_user_ids),
            0,
        )
        all_user_pages.extend([0] * zero_count)
        total_users = len(all_user_pages)
        my_pages = total_pages_read or 0

        if total_users > 1:
            behind_me = sum(1 for p in all_user_pages if (p or 0) < my_pages)
            ahead_of_me = sum(1 for p in all_user_pages if (p or 0) > my_pages)
            pct_ahead = round(behind_me * 100 / max(total_users - 1, 1))
            pct_behind = round(ahead_of_me * 100 / max(total_users - 1, 1))
            rank_text = (
                f"\n📈 <b>Sizdan orqada:</b> {pct_ahead}% kitobxonlar\n"
                f"📉 <b>Sizdan oldinda:</b> {pct_behind}% kitobxonlar\n"
            )
            pages_above = sorted([p or 0 for p in all_user_pages if (p or 0) > my_pages])
            if pages_above:
                next_pages = pages_above[0]
                diff = next_pages - my_pages + 1
                pages_to_overtake_text = (
                    f"🎯 Yana <b>{diff}</b> bet o'qisangiz, keyingi kitobxondan o'tib ketasiz!\n"
                )
    except Exception as e:
        print(f"cabinet ranking calc failed: {e}")

    kitobcha_balance = int(user.ball or 0)

    audio_total_line = (
        f"🎧 <b>Eshitilgan audiokitoblar:</b> {total_audio_minutes} daqiqa\n"
        if total_audio_minutes else ""
    )
    audio_avg_line = (
        f"🎧 <b>O'rtacha kunlik eshitish:</b> {int(avg_audio_per_day)} daqiqa\n"
        if avg_audio_per_day else ""
    )

    # Construct the message
    response_text = (
        f"👤 <b>Sizning shaxsiy kabinetingiz</b>\n\n"
        f"🪙 <b>Kitobcha balansi:</b> {kitobcha_balance}\n"
        f"📚 <b>O'qilgan kitoblar:</b> {completed_books_count} ta\n"
        f"📄 <b>Jami o'qilgan sahifalar:</b> {total_pages_read}\n"
        f"{audio_total_line}"
        f"⚡️ <b>O'rtacha kunlik o'qish:</b> {int(avg_pages_per_day)} bet\n"
        f"{audio_avg_line}"
        f"📅 <b>Eng faol kuningiz:</b> {most_active_day}\n"
        f"⏰ <b>Sevimli vaqtingiz:</b> {active_hour}\n"
        f"{rank_text}"
        f"{pages_to_overtake_text}"
        f"{conclusion_text}"
        f"\n<i>Ma'lumotlar avtomatik yangilanib boradi.</i>"
    )

    # Calendar
    now = timezone.now()
    calendar_markup = generate_calendar_markup(user_id, now.year, now.month)

    await message.answer(response_text, parse_mode="HTML", reply_markup=calendar_markup)
