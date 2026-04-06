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
                if day in reported_days:
                    text += " ✅"
                row_buttons.append(InlineKeyboardButton(
                    text=text, callback_data="ignore"))
        markup.row(*row_buttons)

    return markup


@dp.message_handler(Text(equals=["👤 Kabinet", "👤 Cabinet", "👤 Кабинет"]))
async def show_user_cabinet(message: types.Message):
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

    total_pages_read = BookReport.objects.filter(
        user=user).aggregate(total=Sum('pages_read'))['total'] or 0

    # 2. Reading speed (Average pages per day)
    # We can calculate this from BookReport by averaging pages_read
    avg_pages_per_day = BookReport.objects.filter(
        user=user).aggregate(avg=Avg('pages_read'))['avg'] or 0

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

    # 5. Top conclusions (Longest texts in ConfirmationReport)
    top_conclusions = ConfirmationReport.objects.filter(user=user).annotate(
        length=Length('conclusion')
    ).order_by('-length')[:3]

    conclusion_text = ""
    if top_conclusions:
        conclusion_text = "\n\n✍️ <b>Eng mazmunli xulosalaringiz:</b>\n"
        for i, report in enumerate(top_conclusions, 1):
            book_title = report.book if report.book else "Noma'lum kitob"
            conclusion_text += f"{i}. <i>{book_title}</i> ({report.pages_read} bet)\n"

    # Construct the message
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

    # Calendar
    now = timezone.now()
    calendar_markup = generate_calendar_markup(user_id, now.year, now.month)

    await message.answer(response_text, parse_mode="HTML", reply_markup=calendar_markup)
