
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

import os
from html import escape
from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.bot.keyboards.reply import (
    main_markup_for_user, admin_keyboard, back_keyboard, report_reply_keyboard,
)
from tgbot.bot.keyboards.inline import languages_markup
from tgbot.bot.states.main import (
    ContactAdminState, ChangeLanguageState, ReportState, ConfirmDeleteState,
)
from tgbot.models import (
    BookReport, ConfirmationReport, BooksToRead, Payment, TelegramProfile,
)


def _t(lang, uz, ru):
    return ru if lang == "ru" else uz


def _user_lang(user):
    return (user.language if user else None) or "uz"


async def _notify_admins(text: str):
    admins_raw = os.environ.get("ADMINS", "")
    for raw in admins_raw.split(","):
        chat_id = raw.strip()
        if not chat_id:
            continue
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            print(f"admin notify failed for {chat_id}: {e}")


# ──────────────────────────────────────────────────────────────────────────
# Public helper: send the main menu (used by /start, back_handler, etc).
# Sends two messages: one to clear stale reply keyboard, one with inline kb.
# ──────────────────────────────────────────────────────────────────────────
async def send_main_menu(message: types.Message, user, header_text=None):
    lang = _user_lang(user)
    header = header_text or _t(lang, "🏠 Asosiy menyu", "🏠 Главное меню")
    sub = _t(lang, "Quyidagilardan birini tanlang:", "Выберите одно из ниже:")
    # Compute the dynamic '✅ Bajardim!' label embedding today's challenge
    # progress + condition. Wrapped in try/except so any DB hiccup falls back
    # to the static label rather than blanking the whole menu render.
    bajardim_label = None
    if user:
        try:
            from tgbot.bot.handlers.users.challenge import compute_bajardim_label
            bajardim_label = await compute_bajardim_label(user, lang)
        except Exception as e:
            print(f"compute_bajardim_label failed: {e}")
    is_admin = bool(user and getattr(user, "is_admin", False))
    try:
        await message.answer(
            header,
            reply_markup=report_reply_keyboard(lang, bajardim_label, is_admin=is_admin),
        )
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
    user = await aget_user(message.from_user.id)
    await send_main_menu(message, user)


@dp.message_handler(
    lambda m: m.text in HOME_BUTTON_TEXTS,
    state="*",
)
async def home_button_handler(message: types.Message, state: FSMContext):
    await state.finish()
    user = await aget_user(message.from_user.id)
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
    user = await aget_user(call.from_user.id)
    lang = _user_lang(user)

    # Blocked users can ONLY reach the "contact admin" path so they can
    # appeal. Everything else short-circuits with a clear message.
    if user and user.is_blocked and action != "contact":
        await call.answer()
        await call.message.answer(
            _t(
                lang,
                "🚫 <b>Sizning hisobingiz cheklangan.</b>\n\n"
                "Bot funksiyalaridan foydalana olmaysiz.\n"
                "Sabab yoki blokdan chiqarish bo'yicha <b>📞 Admin bilan bog'lanish</b> "
                "tugmasi orqali murojaat qiling.",
                "🚫 <b>Ваш аккаунт ограничен.</b>\n\n"
                "Функции бота недоступны.\n"
                "Чтобы узнать причину или попросить разблокировку — нажмите "
                "<b>📞 Написать администратору</b>.",
            ),
            parse_mode="HTML",
        )
        return

    if action == "report":
        await _menu_report(call, user, state)
    elif action == "cabinet":
        await _menu_cabinet(call, user, state)
    elif action == "premium":
        await _menu_premium(call, user, state)
    elif action == "achievements":
        await _menu_achievements(call, user, state)
    elif action == "reyting":
        await _menu_reyting(call, user, state)
    elif action == "contact":
        await _menu_contact(call, user, state)
    elif action == "language":
        await _menu_language(call, user, state)
    elif action == "settings":
        await _menu_settings(call, user, state)
    elif action == "how":
        await _menu_how_it_works(call, user, state)
    elif action == "admin":
        await _menu_admin(call, user, state)
    elif action == "quiz":
        await _menu_quiz(call, user, state)
    elif action == "shop":
        await _menu_shop(call, user, state)
    elif action == "market":
        from tgbot.bot.handlers.users.market import show_market_menu, _is_private, _redirect_to_private
        if not _is_private(call):
            await _redirect_to_private(call)
            return
        await call.answer()
        if not user:
            await call.message.answer(_t(lang, "Avval /start bosing", "Сначала /start"))
            return
        await show_market_menu(call.message, user)
    else:
        await call.answer(_t(lang, "Noma'lum amal", "Неизвестное действие"))


async def _menu_shop(call, user, _state: FSMContext):
    """Kitob Challenge Shop — placeholder while the shop is being built."""
    lang = _user_lang(user)
    await call.answer(
        _t(lang, "🛒 Tez kunda!", "🛒 Скоро!"),
        show_alert=True,
    )
    await call.message.answer(
        _t(
            lang,
            (
                "🛒 <b>Kitob Challenge Shop</b>\n\n"
                "🚧 Tez kunda!\n\n"
                "Bu yerda Kitobchalaringizni kitoblar, mukofotlar va "
                "boshqa narsalarga almashtirishingiz mumkin bo'ladi. "
                "Kuting — yaqinda ochilamiz! 🚀"
            ),
            (
                "🛒 <b>Магазин Kitob Challenge</b>\n\n"
                "🚧 Скоро!\n\n"
                "Здесь вы сможете обменивать ваши Kitobcha на книги, "
                "награды и многое другое. Совсем скоро откроемся! 🚀"
            ),
        ),
        parse_mode="HTML",
    )


# ──────────────────────────────────────────────────────────────────────────
# Report (book selection) — opens fresh book picker for the user.
# ──────────────────────────────────────────────────────────────────────────
async def _menu_report(call, user, state: FSMContext):
    from tgbot.bot.handlers.users.report import send_book_selection_menu

    lang = _user_lang(user)
    await call.answer()
    if not user:
        await call.message.answer(_t(lang, "Avval /start bosing", "Сначала /start"))
        return
    if user.is_blocked:
        await call.message.answer(
            _t(
                lang,
                "🚫 <b>Sizning hisobingiz cheklangan.</b>\n\n"
                "Hisobot yubora olmaysiz. <b>📞 Admin bilan bog'lanish</b> "
                "tugmasi orqali murojaat qiling.",
                "🚫 <b>Ваш аккаунт ограничен.</b>\n\n"
                "Отправка отчётов недоступна. Нажмите "
                "<b>📞 Написать администратору</b> для обращения.",
            ),
            parse_mode="HTML",
        )
        return

    today = timezone.localdate()
    already, is_prem = await sync_to_async(
        lambda: (
            ConfirmationReport.objects.filter(user=user, date__date=today).exists(),
            Payment.objects.filter(
                user=user, status="paid", end_date__gte=today
            ).exists(),
        )
    )()
    if already and not is_prem:
        await call.message.answer(
            _t(
                lang,
                "Siz bugungi kun uchun allaqachon hisobotingizni yubordingiz.\n\n"
                "💎 Premium foydalanuvchilar kuniga bir necha marotaba hisobot yubora oladi — "
                "barcha hisobotlar avtomatik jamlanadi va guruhdagi xabar yangilanadi.",
                "Вы уже отправили сегодняшний отчёт.\n\n"
                "💎 Premium пользователи могут отправлять несколько отчётов в день — все суммируются автоматически.",
            )
        )
        return

    # reading_day is the count of distinct reading days the user already has.
    # If they reported today already (premium), keep that count; else add 1.
    distinct_days = await sync_to_async(
        lambda: ConfirmationReport.objects
            .filter(user=user)
            .annotate(_d=TruncDate("date"))
            .values("_d")
            .distinct()
            .count()
    )()
    reading_day = distinct_days if already else distinct_days + 1

    await state.finish()
    await state.update_data(reading_day=reading_day, selected_book_ids=[])
    await ReportState.select_book.set()
    await send_book_selection_menu(call, state)


# ──────────────────────────────────────────────────────────────────────────
# Premium helper.
# ──────────────────────────────────────────────────────────────────────────
def _is_premium_user(user) -> bool:
    if not user:
        return False
    return Payment.objects.filter(
        user=user, status="paid", end_date__gte=timezone.localdate()
    ).exists()


def _premium_growth_section(user) -> str:
    """Compute reading growth stats for premium users. Returns formatted text block."""
    import datetime as _dt
    import calendar as _cal

    today = timezone.localdate()
    yesterday = today - _dt.timedelta(days=1)
    week_start = today - _dt.timedelta(days=today.weekday())
    prev_week_start = week_start - _dt.timedelta(weeks=1)
    prev_week_end = week_start - _dt.timedelta(days=1)
    this_month_start = today.replace(day=1)
    if today.month == 1:
        prev_month_year, prev_month = today.year - 1, 12
    else:
        prev_month_year, prev_month = today.year, today.month - 1
    prev_month_days = _cal.monthrange(prev_month_year, prev_month)[1]
    prev_month_start = _dt.date(prev_month_year, prev_month, 1)
    prev_month_end = _dt.date(prev_month_year, prev_month, prev_month_days)

    def _p(start, end):
        return (
            ConfirmationReport.objects
            .filter(user=user, date__date__gte=start, date__date__lte=end)
            .aggregate(s=Sum("pages_read"))["s"] or 0
        )

    today_p = _p(today, today)
    yest_p = _p(yesterday, yesterday)
    week_p = _p(week_start, today)
    prev_week_p = _p(prev_week_start, prev_week_end)
    month_p = _p(this_month_start, today)
    prev_month_p = _p(prev_month_start, prev_month_end)
    year_p = _p(today.replace(month=1, day=1), today)
    prev_year_p = _p(_dt.date(today.year - 1, 1, 1), _dt.date(today.year - 1, 12, 31))

    # Current calendar week (Monday to Sunday) for the bar chart.
    # Accumulates progress through the week and resets on Monday.
    monday = today - _dt.timedelta(days=today.weekday())
    week_dates = [monday + _dt.timedelta(days=i) for i in range(7)]
    daily = [_p(d, d) for d in week_dates]
    day_labels = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]

    BAR = " ▂▃▄▅▆▇█"  # Ascending blocks
    max_d = max(daily) if daily else 0
    bar_chars = []
    for d in daily:
        if max_d > 0 and d > 0:
            idx = min(7, max(1, round(d / max_d * 7)))
            bar_chars.append(BAR[idx])
        else:
            bar_chars.append(".")  # baseline dot is universally supported and clear!

    # Align cells nicely with CELL=4 centering:
    bar_str = "".join(f"{c:^4}" for c in bar_chars).rstrip()
    label_str = "".join(f"{d:^4}" for d in day_labels).rstrip()
    pages_str = "".join(f"{p:^4}" for p in daily).rstrip()

    def _pct(old, new):
        if old == 0:
            return "▲ ∞%" if new > 0 else "→ 0%"
        p = round((new - old) * 100 / old)
        if p > 0:
            return f"▲ +{p}%"
        if p < 0:
            return f"▼ {p}%"
        return "→ 0%"

    return (
        "\n\n🤍 <b>O'sish jadvalingiz</b> (Maxsus, Sizniki):\n\n"
        f"📅 <b>Bugun</b> ({today_p} bet) vs Kecha ({yest_p} bet): <b>{_pct(yest_p, today_p)}</b>\n"
        f"📆 <b>Bu hafta</b> ({week_p} bet) vs O'tgan hafta ({prev_week_p} bet): <b>{_pct(prev_week_p, week_p)}</b>\n"
        f"🗓 <b>Bu oy</b> ({month_p} bet) vs O'tgan oy ({prev_month_p} bet): <b>{_pct(prev_month_p, month_p)}</b>\n"
        f"📈 <b>Bu yil</b> ({year_p} bet) vs O'tgan yil ({prev_year_p} bet): <b>{_pct(prev_year_p, year_p)}</b>\n\n"
        f"<b>Haftalik kitobxonlik jadvali (betlarda):</b>\n"
        f"<code>{bar_str}</code>\n"
        f"<code>{label_str}</code>\n"
        f"<code>{pages_str}</code>"
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
            user=user, is_audio=False, current_page__gte=F("total_pages"), total_pages__gt=0
        ).count()
        completed_audio_count = BooksToRead.objects.filter(
            user=user, is_audio=True, current_page__gte=F("total_pages"), total_pages__gt=0
        ).count()
        total_pages_read = ConfirmationReport.objects.filter(
            user=user, is_audio=False
        ).aggregate(total=Sum("pages_read"))["total"] or 0
        avg_pages_per_day = ConfirmationReport.objects.filter(
            user=user, is_audio=False
        ).aggregate(avg=Avg("pages_read"))["avg"] or 0

        audio_reports_qs = ConfirmationReport.objects.filter(user=user, is_audio=True)
        audio_reports_count = audio_reports_qs.count()
        total_audio_minutes = audio_reports_qs.aggregate(
            total=Sum("minutes_listened")
        )["total"] or 0
        avg_audio_per_day = audio_reports_qs.aggregate(
            avg=Avg("minutes_listened")
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
        # M2M titles for fallback when ConfirmationReport.book CharField is empty.
        conclusion_titles = {}
        for r in top_conclusions:
            titles = list(r.books.values_list("title", flat=True))
            if titles:
                conclusion_titles[r.id] = ", ".join(titles)

        # Ranking — ahead/behind percentages. Exclude blocked users so
        # cheaters don't poison the percentile computation.
        all_user_pages = list(
            ConfirmationReport.objects
            .filter(user__is_blocked=False, is_audio=False)
            .values("user_id")
            .annotate(total=Sum("pages_read"))
            .values_list("total", flat=True)
        )
        active_user_count = ConfirmationReport.objects.filter(
            user__is_blocked=False, is_audio=False
        ).values_list("user_id").distinct().count()
        registered_total = TelegramProfile.objects.filter(
            is_registered=True, is_blocked=False,
        ).count()
        zero_count = max(registered_total - active_user_count, 0)
        all_user_pages.extend([0] * zero_count)

        return (completed_books_count, completed_audio_count,
                total_pages_read, avg_pages_per_day,
                audio_reports_count, total_audio_minutes, avg_audio_per_day,
                weekday_stats, hour_stats, top_conclusions, conclusion_titles,
                all_user_pages)

    (completed_books_count, completed_audio_count,
     total_pages_read, avg_pages_per_day,
     audio_reports_count, total_audio_minutes, avg_audio_per_day,
     weekday_stats, hour_stats, top_conclusions, conclusion_titles,
     all_user_pages) = await sync_to_async(_stats)()

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

    # Ranking text.
    rank_text = ""
    overtake_text = ""
    my_pages = total_pages_read or 0
    total_users = len(all_user_pages)
    if total_users > 1:
        behind = sum(1 for p in all_user_pages if (p or 0) < my_pages)
        ahead = sum(1 for p in all_user_pages if (p or 0) > my_pages)
        denom = max(total_users - 1, 1)
        pct_ahead = round(behind * 100 / denom)
        pct_behind = round(ahead * 100 / denom)
        rank_text = (
            f"\n📈 <b>Sizdan orqada:</b> {pct_ahead}% kitobxonlar\n"
            f"📉 <b>Sizdan oldinda:</b> {pct_behind}% kitobxonlar\n"
        )
        higher = sorted([p or 0 for p in all_user_pages if (p or 0) > my_pages])
        if higher:
            diff = higher[0] - my_pages + 1
            overtake_text = (
                f"🎯 Yana <b>{diff}</b> bet o'qisangiz, keyingi kitobxondan o'tib ketasiz!\n"
            )

    kitobcha_balance = int(user.ball or 0)

    # Audio section — show if any audio reports exist
    audio_section = ""
    if completed_audio_count or audio_reports_count or total_audio_minutes:
        audio_books_line = f"🎧 <b>Eshitilgan kitoblar:</b> {completed_audio_count} ta\n" if completed_audio_count else ""
        audio_report_count_line = f"📋 <b>Audio hisobotlar soni:</b> {audio_reports_count} ta\n" if audio_reports_count else ""
        if total_audio_minutes:
            audio_total_line = f"⏱ <b>Jami eshitilgan:</b> {total_audio_minutes} daqiqa\n"
        elif audio_reports_count:
            audio_total_line = f"⏱ <b>Jami eshitilgan:</b> — daqiqa (ma'lumot saqlanmagan)\n"
        else:
            audio_total_line = ""
        audio_avg_line = f"🎧 <b>O'rtacha kunlik eshitish:</b> {int(avg_audio_per_day)} daqiqa\n" if avg_audio_per_day else ""
        audio_section = (
            f"\n🎧 <b>— Audio kitoblar —</b>\n"
            f"{audio_books_line}"
            f"{audio_report_count_line}"
            f"{audio_total_line}"
            f"{audio_avg_line}"
        )

    # Premium-only: growth chart
    is_prem = await sync_to_async(_is_premium_user)(user)
    premium_section = ""
    if is_prem:
        premium_section = await sync_to_async(_premium_growth_section)(user)
    else:
        premium_section = (
            "\n\n🔒 <b>Faqat Premium foydalanuvchilar uchun:</b>\n\n"
            "📋 <b>To'liq hisobotlar tarixi</b> — qaysi kuni, qaysi kitob, qanday xulosa "
            "yozganingizni ko'ring\n\n"
            "📊 <b>O'sish jadvali</b> — kun / hafta / oy / yil kesimida o'sish yoki "
            "tushish foizini va grafigini ko'ring\n\n"
            "💎 <i>Premium olib, o'qish tarixingizni va o'sishingizni kuzating!</i>"
        )

    prem_badge = "💎 " if is_prem else ""
    # Challenge widget
    from tgbot.bot.handlers.users.challenge import challenge_cabinet_block
    challenge_text, challenge_btns = await challenge_cabinet_block(user)

    response_text = (
        f"👤 <b>{prem_badge}Sizning shaxsiy kabinetingiz</b>\n\n"
        f"🪙 <b>Kitobcha balansi:</b> {kitobcha_balance}\n"
        f"\n📖 <b>— O'qilgan kitoblar —</b>\n"
        f"📚 <b>Tugallangan kitoblar:</b> {completed_books_count} ta\n"
        f"📄 <b>Jami o'qilgan sahifalar:</b> {total_pages_read} bet\n"
        f"⚡️ <b>O'rtacha kunlik o'qish:</b> {int(avg_pages_per_day)} bet\n"
        f"{audio_section}"
        f"\n📅 <b>Eng faol kuningiz:</b> {most_active_day}\n"
        f"⏰ <b>Sevimli vaqtingiz:</b> {active_hour}\n"
        f"{rank_text}"
        f"{overtake_text}"
        f"{conclusion_text}"
        f"{challenge_text}"
        f"{premium_section}"
        f"\n\n<i>Ma'lumotlar avtomatik yangilanib boradi.</i>"
    )

    show_cal = bool(user and getattr(user, "show_calendar", False))
    if show_cal:
        now = timezone.now()
        calendar_markup = await sync_to_async(generate_calendar_markup)(
            user_id, now.year, now.month
        )
        calendar_markup.row(
            InlineKeyboardButton(
                "📅 Streak kalendarni yashirish",
                callback_data="cab:cal_toggle",
            )
        )
        calendar_markup.row(InlineKeyboardButton(
            "🏆 Yutuqlarim", callback_data="menu:achievements",
        ))
        if is_prem:
            calendar_markup.row(
                InlineKeyboardButton("📋 Hisobotlar tarixi", callback_data="cab:history:0")
            )
        else:
            calendar_markup.row(
                InlineKeyboardButton("🔒 Hisobotlar tarixi (Premium)", callback_data="menu:premium")
            )
            calendar_markup.row(
                InlineKeyboardButton("🔒 O'sish jadvali (Premium)", callback_data="menu:premium")
            )
        calendar_markup.row(InlineKeyboardButton(
            "🌟 Yaxshilik ulashuvchi (Referal)", callback_data="referral:link",
        ))
        for btn in challenge_btns:
            calendar_markup.row(btn)
        await call.message.answer(response_text, parse_mode="HTML",
                                  reply_markup=calendar_markup)
    else:
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(
            "📅 Streak kalendarni ko'rsatish",
            callback_data="cab:cal_toggle",
        ))
        kb.add(InlineKeyboardButton(
            "🏆 Yutuqlarim", callback_data="menu:achievements",
        ))
        if is_prem:
            kb.add(InlineKeyboardButton("📋 Hisobotlar tarixi", callback_data="cab:history:0"))
        else:
            kb.add(InlineKeyboardButton("🔒 Hisobotlar tarixi (Premium)", callback_data="menu:premium"))
            kb.add(InlineKeyboardButton("🔒 O'sish jadvali (Premium)", callback_data="menu:premium"))
        kb.add(InlineKeyboardButton(
            "🌟 Yaxshilik ulashuvchi (Referal)", callback_data="referral:link",
        ))
        for btn in challenge_btns:
            kb.row(btn)
        await call.message.answer(response_text, parse_mode="HTML",
                                  reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "cab:cal_toggle", state="*")
async def cabinet_toggle_calendar(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing", show_alert=True)
        return
    new_val = not bool(getattr(user, "show_calendar", False))
    await sync_to_async(
        TelegramProfile.objects.filter(id=user.id).update
    )(show_calendar=new_val)
    user.show_calendar = new_val
    await call.answer(
        "✅ Kalendar yoqildi" if new_val else "⚪️ Kalendar o'chirildi"
    )
    # Re-render cabinet with updated state.
    await _menu_cabinet(call, user, state)


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

    # Always a plain upsell — buy/extend/gift — with no "you already have
    # Premium" framing that stops short of the menu. A purchase now extends
    # remaining time (Payment.grant_or_extend), so active users should see
    # the same offer as everyone else.
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
# How it works — bot features explanation.
# ──────────────────────────────────────────────────────────────────────────
_HOW_IT_WORKS_UZ = (
    "❓ <b>Bot qanday ishlaydi? (Qo'rqmang — juda oson!)</b>\n\n"
    "Salom, bo'lajak super-kitobxon! 🦸 Bu yerda kitob o'qish — qiziqarli "
    "o'yinga aylanadi. Mana sirlar:\n\n"

    "📚 <b>1. Har kuni o'qing va hisobot bering</b>\n"
    "   «📚 Kitob hisoboti» → nechta bet o'qidingiz → qaysi kitob → bitta xulosa.\n"
    "   Hatto <b>1 bet</b> ham hisoblanadi 😉 (lekin botni aldash yaramaydi — "
    "biz kuzatib turibmiz 👀).\n\n"

    "🪙 <b>2. Kitobcha to'plang</b>\n"
    "   O'qigan va yutuq olgan sayin hamyoningizga 🪙 <b>Kitobcha</b> tushadi.\n"
    "   Ularni <b>🎪 Market</b> bo'limida sarflang: streak muzlatish, sirli "
    "quti, shaxsiy sertifikat va boshqa qiziqarli narsalar bor! 😌\n\n"

    "📊 <b>3. Reytingda jang qiling</b>\n"
    "   Kunlik, haftalik, oylik, yillik top. Qo'shningizni ortda qoldiring — "
    "u ham sizni quvib yetmoqchi 🏃💨\n\n"

    "🏆 <b>4. 100 dan ortiq yutuq yig'ing</b>\n"
    "   «Yigirma bet», «Kunlik marafon», «Birinchi kitob»... Kolleksioner bo'ling!\n\n"

    "🎮 <b>5. JONLI O'YINLAR — eng qizig'i!</b>\n"
    "   Har kuni <b>10:00</b> va <b>22:00</b> da saytda 3 tasodifiy o'yin ketma-ket:\n"
    "   🔗 <b>Kitob Zanjiri</b>, 🗣 <b>Ko'pchilik nima dedi?</b>, 🏰 <b>Bilim Qal'asi</b>, "
    "🎬 <b>Emoji Kitob</b>, ☪️ <b>Hikmat Xazinasi</b>, 📖 <b>Kitob Detektivi</b>, "
    "💀 <b>Omon qolish</b>, 👥 <b>Jamoa Jangi</b> va yana boshqalari!\n"
    "   🧩 <b>Kitob Viktorina</b> — 08:30, 14:00, 21:00 (guruhda)\n"
    "   G'oliblarga Kitobcha, qatnashganga sovg'a. Yutqazsangiz ham... baribir sovg'a 🎁\n\n"

    "📈 <b>6. Darajangizni oshiring</b>\n"
    "   100 → 500 → 1000 → ... bet. Har bosqichda yangi daraja + mukofot. Level up! 🆙\n\n"

    "👥 <b>7. Do'st taklif qiling</b>\n"
    "   Havolangizni yuboring → do'st qo'shilib o'qiy boshlasa → sizga bonus 🪙.\n"
    "   Yolg'iz o'qigandan birga qiziqroq-da! 😄\n\n"

    "⚙️ <b>8. Sozlamalar</b>\n"
    "   Eslatmalar, til, tabrik filtrlari — hammasini o'zingizga moslang.\n\n"

    "Xullas: <b>O'qing → Yozing → O'ynang → Yuting!</b> 📚🎮🏆\n"
    "Qani, bugungi birinchi hisobotni yuboramizmi? 👇"
)

_HOW_IT_WORKS_RU = (
    "❓ <b>Как работает бот? (Не бойтесь — всё очень просто!)</b>\n\n"
    "Привет, будущий супер-читатель! 🦸 Здесь чтение книг превращается в "
    "увлекательную игру. Вот секреты:\n\n"

    "📚 <b>1. Читайте и отправляйте отчёт каждый день</b>\n"
    "   «Отчёт о книге» → сколько страниц прочитали → какая книга → один вывод.\n"
    "   Даже <b>1 страница</b> засчитывается 😉 (но обманывать бота не стоит — "
    "мы следим 👀).\n\n"

    "🪙 <b>2. Копите Kitobcha</b>\n"
    "   За каждое достижение и прочитанные страницы вам начисляется 🪙 "
    "<b>Kitobcha</b>.\n"
    "   Тратьте их в <b>🎪 Market</b>: заморозка серии, сюрприз-бокс, "
    "сертификат и другое! 😌\n\n"

    "📊 <b>3. Соревнуйтесь в рейтинге</b>\n"
    "   Ежедневные, еженедельные, ежемесячные и годовые топы. Обгоните "
    "соседа — он тоже пытается вас догнать 🏃💨\n\n"

    "🏆 <b>4. Собирайте 100+ достижений</b>\n"
    "   «Двадцать страниц», «Дневной марафон», «Первая книга»... Станьте "
    "коллекционером!\n\n"

    "🎮 <b>5. ЖИВЫЕ ИГРЫ — самое интересное!</b>\n"
    "   Каждый день в <b>10:00</b> и <b>22:00</b> на сайте проходят 3 "
    "случайные игры подряд:\n"
    "   🔗 <b>Kitob Zanjiri</b>, 🗣 <b>Ko'pchilik nima dedi?</b>, 🏰 <b>Bilim "
    "Qal'asi</b>, 🎬 <b>Emoji Kitob</b>, ☪️ <b>Hikmat Xazinasi</b>, 📖 "
    "<b>Kitob Detektivi</b>, 💀 <b>Omon qolish</b>, 👥 <b>Jamoa Jangi</b> и "
    "другие!\n"
    "   🧩 <b>Kitob Viktorina</b> — 08:30, 14:00, 21:00 (в группе)\n"
    "   Победителям — Kitobcha, участникам — подарок. Даже если проиграли... "
    "всё равно подарок 🎁\n\n"

    "📈 <b>6. Повышайте уровень</b>\n"
    "   100 → 500 → 1000 → ... страниц. На каждом этапе новый уровень + "
    "награда. Level up! 🆙\n\n"

    "👥 <b>7. Приглашайте друзей</b>\n"
    "   Отправьте свою ссылку → друг присоединится и начнёт читать → вам "
    "бонус 🪙.\n"
    "   Читать вместе веселее, чем в одиночку! 😄\n\n"

    "⚙️ <b>8. Настройки</b>\n"
    "   Напоминания, язык, фильтры поздравлений — настройте всё под себя.\n\n"

    "Итак: <b>Читайте → Пишите → Играйте → Побеждайте!</b> 📚🎮🏆\n"
    "Отправим ваш первый отчёт прямо сейчас? 👇"
)


def _how_it_works_kb(lang: str) -> InlineKeyboardMarkup:
    if lang == "ru":
        rows = [
            ("📚 Отчёт",       "cta_send_report"),
            ("👤 Кабинет",     "menu:cabinet"),
            ("🏆 Достижения",  "menu:achievements"),
            ("📊 Рейтинг",     "menu:reyting"),
            ("💎 Подписка",    "menu:premium"),
            ("⚙️ Настройки",  "menu:settings"),
        ]
    else:
        rows = [
            ("📚 Hisobot",      "cta_send_report"),
            ("👤 Kabinet",      "menu:cabinet"),
            ("🏆 Yutuqlar",     "menu:achievements"),
            ("📊 Reyting",      "menu:reyting"),
            ("💎 Premium",      "menu:premium"),
            ("⚙️ Sozlamalar",  "menu:settings"),
        ]
    kb = InlineKeyboardMarkup(row_width=2)
    for label, cb in rows:
        kb.insert(InlineKeyboardButton(text=label, callback_data=cb))
    return kb


async def _show_how_it_works(message, user):
    lang = _user_lang(user)
    text = _HOW_IT_WORKS_RU if lang == "ru" else _HOW_IT_WORKS_UZ
    await message.answer(text, parse_mode="HTML", reply_markup=_how_it_works_kb(lang))


async def _menu_how_it_works(call, user, _state: FSMContext):
    await call.answer()
    await _show_how_it_works(call.message, user)


# ──────────────────────────────────────────────────────────────────────────
# Reyting — top readers for 5 periods, user-selectable via inline buttons.
# ──────────────────────────────────────────────────────────────────────────
_VALID_PERIODS = ("today", "week", "month", "3months", "yearly", "referral", "top_books", "finished_books")


def _reyting_kb(lang: str, active: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    periods = [
        ("today",    _t(lang, "Bugun",      "Сегодня")),
        ("week",     _t(lang, "Bu hafta",   "Эта неделя")),
        ("month",    _t(lang, "Bu oy",      "Этот месяц")),
        ("3months",  _t(lang, "3 oy",       "3 месяца")),
        ("yearly",   _t(lang, "Yillik",     "Годовой")),
        ("referral", _t(lang, "🌟 Ulashuvchi (Referal)", "🌟 Улашувчи (Реферал)")),
    ]
    kb = InlineKeyboardMarkup(row_width=2)
    btns = []
    for code, label in periods:
        marker = "●" if code == active else "○"
        btns.append(InlineKeyboardButton(
            text=f"{marker} {label}",
            callback_data=f"reyting:{code}",
        ))
    kb.add(*btns)
    if active == "referral":
        kb.row(InlineKeyboardButton(
            text=_t(lang, "📤 Mening havolam", "📤 Моя ссылка"),
            callback_data="referral:link",
        ))
    if is_admin:
        marker = "●" if active == "top_books" else "○"
        kb.row(InlineKeyboardButton(
            text=_t(lang, f"{marker} 📚 Eng ko'p o'qilgan kitoblar", f"{marker} 📚 Самые читаемые книги"),
            callback_data="reyting:top_books",
        ))
        marker_f = "●" if active == "finished_books" else "○"
        kb.row(InlineKeyboardButton(
            text=_t(lang, f"{marker_f} ✅ Eng ko'p tugatilgan kitoblar", f"{marker_f} ✅ Самые завершённые книги"),
            callback_data="reyting:finished_books",
        ))
    return kb


@sync_to_async
def _top_readers_text(period: str, lang: str) -> str:
    import datetime as _dt
    end = timezone.localdate()
    if period == "today":
        start = end
        label = _t(lang, "Bugun", "Сегодня")
        limit = 20
    elif period == "week":
        start = end - _dt.timedelta(days=6)
        label = _t(lang, "Bu hafta", "Эта неделя")
        limit = 20
    elif period == "month":
        start = end - _dt.timedelta(days=29)
        label = _t(lang, "Bu oy", "Этот месяц")
        limit = 30
    elif period == "3months":
        start = end - _dt.timedelta(days=89)
        label = _t(lang, "3 oy", "3 месяца")
        limit = 40
    else:  # yearly
        start = end - _dt.timedelta(days=364)
        label = _t(lang, "Yillik", "Годовой")
        limit = 60

    from django.db.models import Sum

    try:
        # Live book readers — ranked by pages. Blocked users (e.g. cheaters)
        # are excluded from leaderboards.
        live_rows = list(
            ConfirmationReport.objects
            .filter(
                date__date__gte=start, date__date__lte=end,
                is_audio=False, user__is_blocked=False,
            )
            .values("user__telegram_id", "user__full_name")
            .annotate(total=Sum("pages_read"))
            .order_by("-total")[:limit]
        )

        # Audiobook listeners — ranked by minutes
        audio_rows = list(
            ConfirmationReport.objects
            .filter(
                date__date__gte=start, date__date__lte=end,
                is_audio=True, user__is_blocked=False,
            )
            .values("user__telegram_id", "user__full_name")
            .annotate(total=Sum("minutes_listened"))
            .filter(total__gt=0)
            .order_by("-total")[:limit]
        )
    except Exception:
        # Migration 0051 not yet applied — is_audio column missing.
        # Reset the DB connection and fall back to the original single-list query.
        from django.db import connection
        try:
            connection.close()
        except Exception:
            pass
        live_rows = list(
            ConfirmationReport.objects
            .filter(
                date__date__gte=start, date__date__lte=end,
                user__is_blocked=False,
            )
            .values("user__telegram_id", "user__full_name")
            .annotate(total=Sum("pages_read"))
            .order_by("-total")[:limit]
        )
        audio_rows = []

    if not live_rows and not audio_rows:
        return _t(lang, "📭 Hali ma'lumot yo'q.", "📭 Данных пока нет.")

    header = _t(
        lang,
        f"📊 <b>Top kitobxonlar — {label}</b>\n\n",
        f"📊 <b>Топ читателей — {label}</b>\n\n",
    )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    parts = [header]

    # ── Kitob section ──
    if live_rows:
        parts.append(_t(lang, "📖 <b>Kitob:</b>\n", "📖 <b>Обычные книги:</b>\n"))
        grand_live = sum(r["total"] or 0 for r in live_rows)
        lines = []
        for i, r in enumerate(live_rows, 1):
            name = escape(r["user__full_name"] or "Kitobxon")
            tg_id = r["user__telegram_id"]
            pages = r["total"] or 0
            medal = medals.get(i, f"{i}.")
            lines.append(
                f"{medal} <a href='tg://user?id={tg_id}'>{name}</a>: <b>{pages}</b> bet"
            )
        parts.append("\n".join(lines))
        parts.append(_t(
            lang,
            f"\n📚 Jami: <b>{grand_live} bet</b>",
            f"\n📚 Всего: <b>{grand_live} стр.</b>",
        ))

    # ── Audiokitob section ──
    if audio_rows:
        separator = "\n\n" if live_rows else ""
        parts.append(separator + _t(lang, "🎧 <b>Audiokitob:</b>\n", "🎧 <b>Аудиокниги:</b>\n"))
        grand_audio = sum(r["total"] or 0 for r in audio_rows)
        lines = []
        for i, r in enumerate(audio_rows, 1):
            name = escape(r["user__full_name"] or "Kitobxon")
            tg_id = r["user__telegram_id"]
            minutes = r["total"] or 0
            medal = medals.get(i, f"{i}.")
            lines.append(
                f"{medal} <a href='tg://user?id={tg_id}'>{name}</a>: <b>{minutes}</b> daqiqa"
            )
        parts.append("\n".join(lines))
        parts.append(_t(
            lang,
            f"\n⏱ Jami: <b>{grand_audio} daqiqa</b>",
            f"\n⏱ Всего: <b>{grand_audio} мин.</b>",
        ))

    return "".join(parts)


@sync_to_async
def _referral_top_text(lang: str, user=None) -> str:
    from tgbot.models import UserReferal
    from django.db.models import Count

    ranked = list(
        UserReferal.objects
        .values("referrer__id", "referrer__telegram_id", "referrer__full_name")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    rows = ranked[:20]
    header = _t(
        lang,
        "🌟 <b>Yaxshilik ulashuvchilar (Referal) — Top 20</b>\n\n"
        "Kitobxonlik odatini tarqatganlar reytingi:\n\n",
        "🌟 <b>Топ 20 распространителей</b>\n\n"
        "Рейтинг тех, кто популяризирует чтение:\n\n",
    )

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    if not rows:
        leaderboard = _t(
            lang,
            "<i>Reyting hali bo'sh — birinchi bo'lib do'stingizni taklif qiling va 1-o'rinda turing! 🚀</i>",
            "<i>Рейтинг пуст — пригласите друга первым и займите 1-е место! 🚀</i>",
        )
    else:
        lines = []
        for i, r in enumerate(rows, 1):
            name = escape(r["referrer__full_name"] or "Kitobxon")
            tg_id = r["referrer__telegram_id"]
            cnt = r["count"]
            medal = medals.get(i, f"{i}.")
            lines.append(
                f"{medal} <a href='tg://user?id={tg_id}'>{name}</a>: <b>{cnt}</b> ta taklif"
            )
        leaderboard = "\n".join(lines)

    prizes = _t(
        lang,
        (
            "\n\n🎁 <b>Mukofotlar:</b>\n"
            "  1-taklif: 20 🪙 | 2-taklif: 25 🪙 | 3-taklif: 30 🪙 …\n"
            "  Har 3 taklif → 💎 1 kun Premium\n"
            "  17-taklif dan keyin: doimiy 50 🪙 har bir taklif uchun\n\n"
            "<i>(Eslatma: taklif faqat do'stingiz birinchi kitob hisobotini yuborgach hisoblanadi — shunchaki /start bosish yetarli emas.)</i>"
        ),
        (
            "\n\n🎁 <b>Награды:</b>\n"
            "  1-е приглашение: 20 🪙 | 2-е: 25 🪙 | 3-е: 30 🪙 …\n"
            "  Каждые 3 приглашения → 💎 1 день Premium\n"
            "  С 17-го приглашения: фиксированно 50 🪙\n\n"
            "<i>(Примечание: приглашение засчитывается только после того, как ваш друг отправит свой первый отчёт о книге — одного /start недостаточно.)</i>"
        ),
    )

    my_block = ""
    if user:
        uid = user.id
        my_rank = next((i + 1 for i, r in enumerate(ranked) if r["referrer__id"] == uid), None)
        my_cnt = next((r["count"] for r in ranked if r["referrer__id"] == uid), 0)
        if my_rank:
            my_block = _t(
                lang,
                f"\n\n👤 <b>Sizning o'rningiz: {my_rank}-o'rin ({my_cnt} ta taklif)</b>",
                f"\n\n👤 <b>Ваше место: {my_rank}-е ({my_cnt} приглашений)</b>",
            )
        else:
            my_block = _t(
                lang,
                "\n\n👤 Siz hali hech kimni taklif qilmagansiz.",
                "\n\n👤 Вы ещё никого не пригласили.",
            )

    return header + leaderboard + prizes + my_block


async def _menu_reyting(call, user, _state: FSMContext):
    await call.answer()
    lang = _user_lang(user)
    is_admin = bool(user and getattr(user, "is_admin", False))
    text = await _top_readers_text("week", lang)
    await call.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=_reyting_kb(lang, "week", is_admin=is_admin),
        disable_web_page_preview=True,
    )


@sync_to_async
def _top_books_text(lang: str) -> str:
    from tgbot.models import GlobalBook
    from django.db.models import Count

    top_books = list(
        GlobalBook.objects
        .annotate(read_count=Count("user_books__confirmationreport", distinct=True))
        .filter(read_count__gt=0)
        .order_by("-read_count")[:30]
    )

    if not top_books:
        return _t(lang, "📭 Hali ma'lumot yo'q.", "📭 Данных пока нет.")

    header = _t(
        lang,
        "📚 <b>Eng ko'p o'qilgan kitoblar</b> (Admin)\n"
        "<i>Har bir kitob nechta hisobotda tilga olingani bo'yicha "
        "(tugatilgan kitoblar emas).</i>\n\n",
        "📚 <b>Самые читаемые книги</b> (Admin)\n"
        "<i>По числу отчётов, где упомянута книга (не завершённые книги).</i>\n\n",
    )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    unit = _t(lang, "marta", "раз")
    lines = []
    for i, book in enumerate(top_books, 1):
        medal = medals.get(i, f"{i}.")
        lines.append(
            f"{medal} <b>{escape(book.title)}</b> — {book.read_count} {unit}"
        )
    return header + "\n".join(lines)


@sync_to_async
def _finished_books_text(lang: str) -> str:
    """Most-finished books: counts how many users have completed each book
    (a BooksToRead with current_page >= total_pages > 0)."""
    from tgbot.models import GlobalBook
    from django.db.models import Count, Q, F

    top_books = list(
        GlobalBook.objects
        .annotate(finished_count=Count(
            "user_books",
            filter=Q(
                user_books__total_pages__gt=0,
                user_books__current_page__gte=F("user_books__total_pages"),
            ),
            distinct=True,
        ))
        .filter(finished_count__gt=0)
        .order_by("-finished_count")[:30]
    )

    if not top_books:
        return _t(lang, "📭 Hali tugatilgan kitob yo'q.", "📭 Завершённых книг пока нет.")

    header = _t(
        lang,
        "✅ <b>Eng ko'p tugatilgan kitoblar</b> (Admin)\n"
        "<i>Nechta foydalanuvchi kitobni to'liq o'qib tugatgani bo'yicha.</i>\n\n",
        "✅ <b>Самые завершённые книги</b> (Admin)\n"
        "<i>По числу пользователей, полностью прочитавших книгу.</i>\n\n",
    )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    unit = _t(lang, "kishi", "чел.")
    lines = []
    for i, book in enumerate(top_books, 1):
        medal = medals.get(i, f"{i}.")
        lines.append(
            f"{medal} <b>{escape(book.title)}</b> — {book.finished_count} {unit}"
        )
    return header + "\n".join(lines)


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("reyting:"),
    state="*",
)
async def reyting_period_pick(call: types.CallbackQuery, state: FSMContext):
    period = call.data.split(":", 1)[1]
    if period not in _VALID_PERIODS:
        await call.answer()
        return
    user = await aget_user(call.from_user.id)
    lang = _user_lang(user)
    is_admin = bool(user and getattr(user, "is_admin", False))

    # Book stats are admin-only
    if period in ("top_books", "finished_books") and not is_admin:
        await call.answer(_t(lang, "Bu bo'lim faqat adminlar uchun.", "Этот раздел только для админов."), show_alert=True)
        return

    await call.answer()
    try:
        if period == "referral":
            text = await _referral_top_text(lang, user)
        elif period == "top_books":
            text = await _top_books_text(lang)
        elif period == "finished_books":
            text = await _finished_books_text(lang)
        else:
            text = await _top_readers_text(period, lang)
    except Exception as e:
        print(f"reyting_period_pick error for {period}: {e}")
        await call.message.answer(_t(lang, "❌ Xato yuz berdi, qayta urining.", "❌ Ошибка, попробуйте ещё раз."))
        return
    try:
        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=_reyting_kb(lang, period, is_admin=is_admin),
            disable_web_page_preview=True,
        )
    except Exception:
        try:
            await call.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=_reyting_kb(lang, period, is_admin=is_admin),
                disable_web_page_preview=True,
            )
        except Exception as e2:
            print(f"reyting fallback answer failed: {e2}")


@dp.callback_query_handler(lambda c: c.data == "referral:link", state="*")
async def referral_link_handler(call: types.CallbackQuery, state: FSMContext):
    del state  # injected by aiogram, unused here
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing.", show_alert=True)
        return
    await call.answer()
    from tgbot.services.referral import ReferralService
    lang = _user_lang(user)
    ref_count = await ReferralService.get_referral_count(user)
    ref_link = await ReferralService.get_referral_link(user)
    BREAKPOINT = 17
    if ref_count < BREAKPOINT:
        next_reward = 20 + 5 * ref_count
    else:
        next_reward = 50
    # "Refs until next premium-day": cycle is every 3 invites.
    next_prem = 3 - (ref_count % 3) if ref_count % 3 != 0 else 3
    text = _t(
        lang,
        f"🔗 <b>Sizning taklif havolangiz:</b>\n<code>{ref_link}</code>\n\n"
        f"📊 Jami taklif: <b>{ref_count}</b> ta\n"
        f"🎁 Keyingi taklif uchun: <b>+{next_reward} Kitobcha</b>\n"
        f"💎 Keyingi premiumgacha: <b>{next_prem} ta</b> taklif qoldi\n\n"
        f"<i>(Eslatma: taklif faqat do'stingiz birinchi kitob hisobotini yuborgach hisoblanadi — shunchaki /start bosish yetarli emas.)</i>",
        f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"📊 Всего приглашений: <b>{ref_count}</b>\n"
        f"🎁 За следующее: <b>+{next_reward} Kitobcha</b>\n"
        f"💎 До следующего Premium: <b>{next_prem}</b> приглашений\n\n"
        f"<i>(Примечание: приглашение засчитывается только после того, как ваш друг отправит свой первый отчёт о книге — одного /start недостаточно.)</i>",
    )

    # Append the list of people this user has invited.
    from django.utils.html import escape as _esc
    ref_list = await ReferralService.get_referral_list(user)
    if ref_list:
        lines = []
        for i, (name, tid, _created) in enumerate(ref_list, 1):
            safe = _esc(name)
            # Tap the name to open the invited user's Telegram profile (works
            # without a @username — it goes by numeric id).
            lines.append(f'{i}. <a href="tg://user?id={tid}">{safe}</a>' if tid else f"{i}. {safe}")
        header = _t(lang, "\n\n👥 <b>Siz taklif qilganlar:</b>\n",
                    "\n\n👥 <b>Вы пригласили:</b>\n")
        text += header + "\n".join(lines)
        if ref_count > len(ref_list):
            text += _t(lang, f"\n… va yana <b>{ref_count - len(ref_list)}</b> ta",
                       f"\n… и ещё <b>{ref_count - len(ref_list)}</b>")
    else:
        text += _t(lang, "\n\n👥 <i>Hozircha hech kimni taklif qilmagansiz.</i>",
                   "\n\n👥 <i>Пока вы никого не пригласили.</i>")

    await call.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ──────────────────────────────────────────────────────────────────────────
# Top-list congratulations (from scheduled broadcast Tabriklash buttons).
# ──────────────────────────────────────────────────────────────────────────
@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("toplist_congrats:"),
    state="*",
)
async def toplist_congrats_handler(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer()
        return

    period = parts[1]
    date_str = parts[2]

    await call.answer("🎉 Tabrikladingiz! Xabarlar jo'natilmoqda...", show_alert=False)

    import asyncio as _asyncio
    import datetime as _dt
    import requests as _req
    import time as _time
    from asgiref.sync import sync_to_async
    from django.utils.html import escape as _esc
    from tgbot.models import TelegramProfile as _TP, ConfirmationReport as _CR
    from django.db.models import Sum as _Sum
    from tgbot.tasks import BOT_TOKEN

    # Delete the congrats DM from the user's chat 1 minute after they click.
    async def _del_after():
        await _asyncio.sleep(60)
        try:
            await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        except Exception:
            pass
    _asyncio.create_task(_del_after())

    congratulator_tg_id = call.from_user.id
    presser_name = _esc(user.full_name or "Kitobxon")

    period_map = {
        "daily":    (_dt.timedelta(days=0),   "Kunlik",   20),
        "3days":    (_dt.timedelta(days=2),   "3 kunlik", 20),
        "weekly":   (_dt.timedelta(days=6),   "Haftalik", 30),
        "monthly":  (_dt.timedelta(days=29),  "Oylik",    30),
        "3monthly": (_dt.timedelta(days=89),  "3 oylik",  40),
        "yearly":   (_dt.timedelta(days=364), "Yillik",   60),
    }
    if period not in period_map:
        return

    delta, period_label, limit = period_map[period]
    try:
        end_date = _dt.datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        return
    start_date = end_date - delta

    rows = await sync_to_async(lambda: list(
        _CR.objects
        .filter(date__date__gte=start_date, date__date__lte=end_date)
        .values("user__telegram_id", "user__full_name")
        .annotate(total=_Sum("pages_read"))
        .order_by("-total")[:limit]
    ))()

    if not rows:
        return

    async def _send_congrats(rows, presser_name, period_label, congratulator_tg_id, token):
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        def _do():
            for row in rows:
                tg_id = row["user__telegram_id"]
                if tg_id == congratulator_tg_id:
                    continue
                try:
                    _req.post(url, data={
                        "chat_id": tg_id,
                        "text": (
                            f"🎉 <b>{presser_name}</b> sizi tabriklamoqda!\n\n"
                            f"📊 <b>{period_label}</b> top ro'yxatida bo'lganingiz uchun!\n\n"
                            "Zo'r natija! Davom eting 📚🔥"
                        ),
                        "parse_mode": "HTML",
                    }, timeout=5)
                except Exception as e:
                    print(f"congrats DM failed {tg_id}: {e}")
                _time.sleep(0.05)

        loop = _asyncio.get_event_loop()
        await loop.run_in_executor(None, _do)

    _asyncio.create_task(_send_congrats(rows, presser_name, period_label, congratulator_tg_id, BOT_TOKEN))


# ──────────────────────────────────────────────────────────────────────────
# Settings — currently: per-user reminder count (0–3).
# ──────────────────────────────────────────────────────────────────────────
TABRIKLAR_RANGE_CHOICES = (
    ("any", "Hammasi"),
    ("3-10", "3-10"),
    ("11-20", "11-20"),
    ("21-40", "21-40"),
    ("41+", "41+"),
)


def _settings_markup(user, lang: str = "uz") -> InlineKeyboardMarkup:
    rc = getattr(user, "reminder_count", 3) if user else 3
    show_cal = bool(getattr(user, "show_calendar", False)) if user else False
    accept = (getattr(user, "accept_congrats_from", "any") or "any") if user else "any"
    send_to = (getattr(user, "send_congrats_to", "any") or "any") if user else "any"
    tab_range = (getattr(user, "tabriklar_range", "any") or "any") if user else "any"

    kb = InlineKeyboardMarkup(row_width=1)

    if lang == "ru":
        sec_books    = "── 📚 Книги ──"
        btn_manage   = "📖 Управление книгами"
        sec_remind   = "── 🔔 Напоминания ──"
        lbl_remind_hint = "0 — выкл  |  1 — вечер  |  2 — у+в  |  3 — 3×"
        sec_cal      = "── 📅 Стрик-календарь ──"
        lbl_cal_on   = "● Включён  (нажмите — выключить)"
        lbl_cal_off  = "○ Выключен (нажмите — включить)"
        sec_congrats = "── 🎉 Поздравления ──"
        lbl_accept   = "📥 Принимать:"
        lbl_send     = "📤 Отправлять:"
        lbl_range    = "🔔 Чьи поздравления получать (больше всего — «Все»):"
        sec_other    = "── ⚙️ Прочее ──"
        lbl_lang     = "🌐 Язык"
        lbl_how      = "❓ Как работает?"
        lbl_restart  = "🔄 Начать заново"
        lbl_reset    = "🗑 Удалить все данные"
        accept_labels = {"any": "Все", "male": "Мужчины", "female": "Женщины"}
        send_labels   = {"any": "Всем", "male": "Мужч.", "female": "Женщ."}
        # Filter = the achiever's total achievements. Higher band = rarer people
        # = FEWER messages. "Все" = receive every invitation (the most).
        range_labels  = {"any": "Все 🔝", "3-10": "3–10", "11-20": "11–20", "21-40": "21–40", "41+": "41+ (мало)"}
    else:
        sec_books    = "── 📚 Kitoblar ──"
        btn_manage   = "📖 Kitoblarni boshqarish"
        sec_remind   = "── 🔔 Eslatmalar ──"
        lbl_remind_hint = "0 — yo'q  |  1 — kechqurun  |  2 — e+k  |  3 — 3×"
        sec_cal      = "── 📅 Streak kalendar ──"
        lbl_cal_on   = "● Yoqilgan  (bosing — o'chirish)"
        lbl_cal_off  = "○ O'chirilgan (bosing — yoqish)"
        sec_congrats = "── 🎉 Tabriklash ──"
        lbl_accept   = "📥 Qabul qilish:"
        lbl_send     = "📤 Yuborish:"
        lbl_range    = "🔔 Kimlarning tabriklarini olish (eng ko'pi — «Hammasi»):"
        sec_other    = "── ⚙️ Boshqalar ──"
        lbl_lang     = "🌐 Til"
        lbl_how      = "❓ Qanday ishlaydi?"
        lbl_restart  = "🔄 Qayta boshlash"
        lbl_reset    = "🗑 Ma'lumotlarni o'chirish"
        accept_labels = {"any": "Hammadan", "male": "Erkak", "female": "Ayol"}
        send_labels   = {"any": "Hammaga", "male": "Erkak", "female": "Ayol"}
        # Filtr = tabriklanayotgan kishining umumiy yutuqlari soni. Yuqori daraja
        # = kam odam = KAM xabar. "Hammasi" = barcha takliflarni olasiz (eng ko'p).
        range_labels  = {"any": "Hammasi 🔝", "3-10": "3–10", "11-20": "11–20", "21-40": "21–40", "41+": "41+ (kam)"}

    # ── 📚 Kitoblar ──
    kb.row(InlineKeyboardButton(sec_books, callback_data="noop"))
    kb.row(InlineKeyboardButton(btn_manage, callback_data="cab:manage_books"))

    # ── 🔔 Eslatmalar ──
    kb.row(InlineKeyboardButton(sec_remind, callback_data="noop"))
    kb.row(InlineKeyboardButton(lbl_remind_hint, callback_data="noop"))
    reminders_row = []
    for n in range(0, 4):
        marker = "●" if n == rc else "○"
        reminders_row.append(InlineKeyboardButton(
            text=f"{marker} {n}", callback_data=f"settings:reminders:{n}"
        ))
    kb.row(*reminders_row)

    # ── 📅 Streak kalendar ──
    kb.row(InlineKeyboardButton(sec_cal, callback_data="noop"))
    cal_label = lbl_cal_on if show_cal else lbl_cal_off
    kb.row(InlineKeyboardButton(text=cal_label, callback_data="settings:cal_toggle"))

    # ── 🎉 Tabriklash ──
    kb.row(InlineKeyboardButton(sec_congrats, callback_data="noop"))
    accept_row = [InlineKeyboardButton(lbl_accept, callback_data="noop")]
    for code in ("any", "male", "female"):
        marker = "●" if accept == code else "○"
        accept_row.append(InlineKeyboardButton(
            text=f"{marker} {accept_labels[code]}", callback_data=f"settings:accept:{code}"
        ))
    kb.row(*accept_row)

    send_row = [InlineKeyboardButton(lbl_send, callback_data="noop")]
    for code in ("any", "male", "female"):
        marker = "●" if send_to == code else "○"
        send_row.append(InlineKeyboardButton(
            text=f"{marker} {send_labels[code]}", callback_data=f"settings:send:{code}"
        ))
    kb.row(*send_row)

    kb.row(InlineKeyboardButton(lbl_range, callback_data="noop"))
    range_row_1 = []
    for code, _ in TABRIKLAR_RANGE_CHOICES[:3]:
        marker = "●" if tab_range == code else "○"
        range_row_1.append(InlineKeyboardButton(
            text=f"{marker} {range_labels[code]}", callback_data=f"settings:tabriklar:{code}"
        ))
    kb.row(*range_row_1)
    range_row_2 = []
    for code, _ in TABRIKLAR_RANGE_CHOICES[3:]:
        marker = "●" if tab_range == code else "○"
        range_row_2.append(InlineKeyboardButton(
            text=f"{marker} {range_labels[code]}", callback_data=f"settings:tabriklar:{code}"
        ))
    kb.row(*range_row_2)

    # ── ⚙️ Boshqalar ──
    kb.row(InlineKeyboardButton(sec_other, callback_data="noop"))
    kb.row(
        InlineKeyboardButton(text=lbl_lang, callback_data="settings:language"),
        InlineKeyboardButton(text=lbl_how, callback_data="settings:how_it_works"),
    )
    kb.row(
        InlineKeyboardButton(text=lbl_restart, callback_data="settings:restart_ask"),
        InlineKeyboardButton(text=lbl_reset, callback_data="settings:reset_ask"),
    )
    return kb


def _settings_text(user, lang: str) -> str:
    rc = getattr(user, "reminder_count", 3) if user else 3
    show_cal = bool(getattr(user, "show_calendar", False)) if user else False
    accept = (getattr(user, "accept_congrats_from", "any") or "any") if user else "any"
    send_to = (getattr(user, "send_congrats_to", "any") or "any") if user else "any"
    tab_range = (getattr(user, "tabriklar_range", "any") or "any") if user else "any"

    if lang == "ru":
        a_lbl = {"any": "Ото всех", "male": "От мужчин", "female": "От женщин"}
        s_lbl = {"any": "Всем", "male": "Мужчинам", "female": "Женщинам"}
        r_lbl = {"any": "Все", "3-10": "3–10", "11-20": "11–20", "21-40": "21–40", "41+": "41+"}
        cal_status = "✅ Включён" if show_cal else "⭕ Выключен"
        remind_map = {0: "Выкл.", 1: "Вечер", 2: "Утро + вечер", 3: "3 раза в день"}
        return (
            "⚙️ <b>Настройки</b>\n\n"
            "📚 <b>Книги</b>\n"
            "  Управление своим списком книг.\n\n"
            f"🔔 <b>Напоминания:</b> <b>{remind_map.get(rc, rc)}</b>\n"
            "  0 — выкл · 1 — вечер · 2 — утро+вечер · 3 — три раза\n\n"
            f"📅 <b>Стрик-календарь:</b> {cal_status}\n"
            "  Отображает дни чтения в кабинете.\n\n"
            "🎉 <b>Поздравления</b>\n"
            f"  📥 Принимать: <b>{a_lbl.get(accept, accept)}</b>\n"
            f"  📤 Отправлять: <b>{s_lbl.get(send_to, send_to)}</b>\n"
            f"  🔔 Фильтр поздравлений: <b>{r_lbl.get(tab_range, tab_range)}</b>\n"
            "  <i>«Все» — получаете все поздравления (больше всего). Числовые\n"
            "  уровни — только самые активные читатели, сообщений меньше.</i>\n\n"
            "⚙️ <b>Прочее</b>\n"
            "  🌐 Язык — 🔄 Перезапуск — 🗑 Удаление данных"
        )
    else:
        a_lbl = {"any": "Hammadan", "male": "Erkakdan", "female": "Ayoldan"}
        s_lbl = {"any": "Hammaga", "male": "Erkaklarga", "female": "Ayollarga"}
        r_lbl = {"any": "Hammasi", "3-10": "3–10", "11-20": "11–20", "21-40": "21–40", "41+": "41+"}
        cal_status = "✅ Yoqilgan" if show_cal else "⭕ O'chirilgan"
        remind_map = {0: "Yo'q", 1: "Kechqurun", 2: "Ertalab + kechqurun", 3: "Kuniga 3 marta"}
        return (
            "⚙️ <b>Sozlamalar</b>\n\n"
            "📚 <b>Kitoblar</b>\n"
            "  O'zingizning kitoblar ro'yxatini boshqarish.\n\n"
            f"🔔 <b>Eslatmalar:</b> <b>{remind_map.get(rc, rc)}</b>\n"
            "  0 — yo'q · 1 — kechqurun · 2 — ertalab+kechqurun · 3 — kuniga 3×\n\n"
            f"📅 <b>Streak kalendar:</b> {cal_status}\n"
            "  Kabinetda kunlik streak ko'rinadi.\n\n"
            "🎉 <b>Tabriklash</b>\n"
            f"  📥 Qabul qilish: <b>{a_lbl.get(accept, accept)}</b>\n"
            f"  📤 Yuborish: <b>{s_lbl.get(send_to, send_to)}</b>\n"
            f"  🔔 Tabrik filtri: <b>{r_lbl.get(tab_range, tab_range)}</b>\n"
            "  <i>«Hammasi» — barcha tabriklarni olasiz (eng ko'p). Raqamli\n"
            "  darajalar faqat eng faol kitobxonlar uchun — kamroq xabar keladi.</i>\n\n"
            "⚙️ <b>Boshqalar</b>\n"
            "  🌐 Til — 🔄 Qayta boshlash — 🗑 Ma'lumotlarni o'chirish"
        )


async def _menu_settings(call, user, state: FSMContext):
    await call.answer()
    lang = _user_lang(user)
    try:
        await call.message.edit_text(
            _settings_text(user, lang),
            parse_mode="HTML",
            reply_markup=_settings_markup(user, lang),
        )
    except Exception:
        await call.message.answer(
            _settings_text(user, lang),
            parse_mode="HTML",
            reply_markup=_settings_markup(user, lang),
        )


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("settings:"),
    state="*",
)
async def settings_pick(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user:
        await call.answer("Avval /start bosing", show_alert=True)
        return
    parts = call.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "reminders":
        n = max(0, min(3, int(parts[2])))
        await sync_to_async(
            TelegramProfile.objects.filter(id=user.id).update
        )(reminder_count=n)
        user.reminder_count = n
        await call.answer(f"✅ Eslatma: {n}")
    elif action == "cal_toggle":
        new_val = not bool(getattr(user, "show_calendar", False))
        await sync_to_async(
            TelegramProfile.objects.filter(id=user.id).update
        )(show_calendar=new_val)
        user.show_calendar = new_val
        await call.answer(
            "✅ Kalendar yoqildi" if new_val else "⚪️ Kalendar o'chirildi"
        )
    elif action == "accept" and len(parts) > 2:
        choice = parts[2]
        if choice in ("any", "male", "female"):
            await sync_to_async(
                TelegramProfile.objects.filter(id=user.id).update
            )(accept_congrats_from=choice)
            user.accept_congrats_from = choice
            await call.answer("✅ Saqlandi")
        else:
            await call.answer()
            return
    elif action == "send" and len(parts) > 2:
        choice = parts[2]
        if choice in ("any", "male", "female"):
            await sync_to_async(
                TelegramProfile.objects.filter(id=user.id).update
            )(send_congrats_to=choice)
            user.send_congrats_to = choice
            await call.answer("✅ Saqlandi")
        else:
            await call.answer()
            return
    elif action == "tabriklar" and len(parts) > 2:
        choice = parts[2]
        if choice in {"any", "3-10", "11-20", "21-40", "41+"}:
            await sync_to_async(
                TelegramProfile.objects.filter(id=user.id).update
            )(tabriklar_range=choice)
            user.tabriklar_range = choice
            await call.answer(f"✅ Saqlandi: {choice}")
        else:
            await call.answer()
            return

    elif action == "language":
        await call.answer()
        lang = _user_lang(user)
        text = _t(lang, "Tilni o'zgartiring", "Измените язык")
        await call.message.answer(text, reply_markup=languages_markup)
        await ChangeLanguageState.language_change.set()
        return

    elif action == "how_it_works":
        await call.answer()
        await _show_how_it_works(call.message, user)
        return

    # -- Step-1: ask restart
    elif action == "restart_ask":
        confirm_kb = InlineKeyboardMarkup(row_width=2)
        confirm_kb.row(
            InlineKeyboardButton(text="✅ Ha, qayta boshlash",
                                 callback_data="settings:restart_confirm"),
            InlineKeyboardButton(text="❌ Bekor qilish",
                                 callback_data="settings:cancel_action"),
        )
        await call.answer(
            "⚠️ Diqqat! Bu amal faqat ro'yxatdan o'tish jarayonini qaytaradi. "
            "Hisobotlaringiz, kitoblaringiz va ballaringiz saqlanib qoladi.",
            show_alert=True,
        )
        try:
            await call.message.edit_reply_markup(reply_markup=confirm_kb)
        except Exception:
            pass
        return

    # -- Step-2: confirm restart
    elif action == "restart_confirm":
        await sync_to_async(
            TelegramProfile.objects.filter(id=user.id).update
        )(is_registered=False, full_name=None, gender=None, region_id=None,
          age_range=None, group_id=None)
        await state.finish()
        await call.answer("✅ Qayta boshlash amalga oshirildi.", show_alert=True)
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer(
            "🔄 Siz qayta ro'yxatdan o'tish uchun /start ni bosing.\n\n"
            "(Barcha hisobotlaringiz va ma'lumotlaringiz saqlanib qoldi.)"
        )
        uname = f"@{call.from_user.username}" if call.from_user.username else "—"
        await _notify_admins(
            f"🔄 <b>Qayta boshlash</b>\n"
            f"👤 {user.full_name or '—'} | {uname}\n"
            f"🆔 <code>{call.from_user.id}</code>\n"
            f"<i>Ma'lumotlar saqlanib qoldi.</i>"
        )
        return

    # -- Step-1: ask full reset — require user to type "Tasdiqlayman"
    elif action == "reset_ask":
        await call.answer()
        await call.message.answer(
            "⚠️ <b>DIQQAT!</b> Barcha ma'lumotlaringiz (hisobotlar, kitoblar, ballar, yutuqlar) "
            "<b>butunlay o'chiriladi</b> va tiklash imkoni bo'lmaydi!\n\n"
            "Tasdiqlash uchun quyidagi so'zni aynan shu ko'rinishda yozing:\n\n"
            "<code>Tasdiqlayman</code>\n\n"
            "<i>Bekor qilish uchun boshqa istalgan matn yozing.</i>",
            parse_mode="HTML",
        )
        await ConfirmDeleteState.confirm.set()
        return

    # -- Cancel two-step action
    elif action == "cancel_action":
        await call.answer("❌ Bekor qilindi")
        lang = _user_lang(user)
        try:
            await call.message.edit_text(
                _settings_text(user, lang),
                parse_mode="HTML",
                reply_markup=_settings_markup(user, lang),
            )
        except Exception:
            pass
        return

    else:
        await call.answer()
        return

    lang = _user_lang(user)
    try:
        await call.message.edit_text(
            _settings_text(user, lang),
            parse_mode="HTML",
            reply_markup=_settings_markup(user, lang),
        )
    except Exception:
        pass


@dp.message_handler(state=ConfirmDeleteState.confirm)
async def confirm_delete_handler(message: types.Message, state: FSMContext):
    """User must type 'Tasdiqlayman' exactly to confirm full data deletion."""
    user = await aget_user(message.from_user.id)
    if not user:
        await state.finish()
        return

    if message.text == "Tasdiqlayman":
        @sync_to_async
        def _do_full_reset(uid):
            from tgbot.models import (
                BookReport, ConfirmationReport, BooksToRead,
                UserAchievement, Congratulation, UserReferal, Payment,
            )
            profile = TelegramProfile.objects.filter(id=uid).first()
            if not profile:
                return
            Congratulation.objects.filter(achievement__user=profile).delete()
            Congratulation.objects.filter(congratulator=profile).delete()
            UserAchievement.objects.filter(user=profile).delete()
            ConfirmationReport.objects.filter(user=profile).delete()
            BookReport.objects.filter(user=profile).delete()
            BooksToRead.objects.filter(user=profile).delete()
            Payment.objects.filter(user=profile).delete()
            UserReferal.objects.filter(referrer=profile).delete()
            UserReferal.objects.filter(referred_user=profile).delete()
            TelegramProfile.objects.filter(id=uid).update(
                full_name=None, gender=None, region_id=None, age_range=None,
                group_id=None, ball=0, is_registered=False,
                last_progress_msg_id=None, show_calendar=False,
                reminder_count=3, accept_congrats_from="any",
                send_congrats_to="any",
            )

        await _do_full_reset(user.id)
        await state.finish()
        await message.answer(
            "🗑 Barcha ma'lumotlaringiz o'chirildi.\n\n"
            "Yangi foydalanuvchi sifatida /start ni bosing."
        )
        uname = f"@{message.from_user.username}" if message.from_user.username else "—"
        await _notify_admins(
            f"🗑 <b>To'liq o'chirish</b>\n"
            f"👤 {user.full_name or '—'} | {uname}\n"
            f"🆔 <code>{message.from_user.id}</code>\n"
            f"<i>Barcha ma'lumotlari o'chirildi.</i>"
        )
    else:
        await state.finish()
        await message.answer("❌ O'chirish bekor qilindi.")
        lang = _user_lang(user)
        await message.answer(
            _settings_text(user, lang),
            parse_mode="HTML",
            reply_markup=_settings_markup(user),
        )


@dp.callback_query_handler(lambda c: c.data == "noop", state="*")
async def menu_noop(call: types.CallbackQuery):
    await call.answer()


# ──────────────────────────────────────────────────────────────────────────
# Quiz list — shows all available quizzes for the user to play solo.
# ──────────────────────────────────────────────────────────────────────────
async def _menu_quiz(call, user, _state: FSMContext):
    await call.answer()
    if not user or not user.is_registered:
        await call.message.answer("Avval /start bosib ro'yxatdan o'ting.")
        return

    is_admin = bool(getattr(user, "is_admin", False))
    # Premium subscribers can create + manage their own quizzes (same flow
    # admins use). Free users see the playable list only.
    from tgbot.bot.handlers.users.quiz_admin import _is_active_premium
    can_create = is_admin or await _is_active_premium(user)

    @sync_to_async
    def _load():
        from tgbot.models import Quiz
        qs = list(Quiz.objects.prefetch_related("questions").filter(creator=user))
        return [(q.id, q.title, q.questions.count(), q.time_per_question, q.description) for q in qs]

    quizzes = await _load()

    kb = InlineKeyboardMarkup(row_width=1)
    if can_create:
        kb.add(InlineKeyboardButton(
            text="➕ Yangi quiz yaratish", callback_data="qz:new",
        ))
        kb.add(InlineKeyboardButton(
            text="🤖 AI yordamida yaratish (Premium)", callback_data="qz:ai",
        ))
        kb.add(InlineKeyboardButton(
            text="📋 Mening quizlarim", callback_data="qz:ls",
        ))

    if not quizzes:
        if can_create:
            await call.message.answer(
                "📭 <b>Hozircha quiz mavjud emas.</b>\n\nBirinchisini yarating:",
                parse_mode="HTML",
                reply_markup=kb,
            )
        else:
            await call.message.answer(
                "📭 Hozircha quiz mavjud emas.\n\n"
                "💎 <b>Premium</b> obunaga ega bo'lsangiz, o'zingiz ham quiz "
                "yaratishingiz mumkin.",
                parse_mode="HTML",
            )
        return

    for qid, title, q_count, tpq, _ in quizzes:
        # qprev shows a preview screen with Boshlash + Guruhga ulashish.
        # The timer no longer starts the instant you tap the title.
        kb.add(InlineKeyboardButton(
            text=f"📝 {title} ({q_count} savol · {tpq}s)",
            callback_data=f"qprev:{qid}",
        ))
    await call.message.answer(
        "📝 <b>Kitob Quizlar</b>\n\nQuyidagi quizlardan birini tanlang:",
        parse_mode="HTML",
        reply_markup=kb,
    )


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
