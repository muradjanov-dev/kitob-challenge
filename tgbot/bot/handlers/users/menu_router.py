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
from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import get_user
from tgbot.bot.keyboards.reply import (
    main_markup_for_user, admin_keyboard, back_keyboard, report_reply_keyboard,
)
from tgbot.bot.keyboards.inline import languages_markup
from tgbot.bot.states.main import (
    ContactAdminState, ChangeLanguageState, ReportState,
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
    elif action == "settings":
        await _menu_settings(call, user, state)
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
        # M2M titles for fallback when ConfirmationReport.book CharField is empty.
        conclusion_titles = {}
        for r in top_conclusions:
            titles = list(r.books.values_list("title", flat=True))
            if titles:
                conclusion_titles[r.id] = ", ".join(titles)

        # Ranking — ahead/behind percentages.
        all_user_pages = list(
            ConfirmationReport.objects
            .values("user_id")
            .annotate(total=Sum("pages_read"))
            .values_list("total", flat=True)
        )
        active_user_count = ConfirmationReport.objects.values_list(
            "user_id"
        ).distinct().count()
        registered_total = TelegramProfile.objects.filter(is_registered=True).count()
        zero_count = max(registered_total - active_user_count, 0)
        all_user_pages.extend([0] * zero_count)

        return (completed_books_count, total_pages_read, avg_pages_per_day,
                weekday_stats, hour_stats, top_conclusions, conclusion_titles,
                all_user_pages)

    (completed_books_count, total_pages_read, avg_pages_per_day,
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
    if top_conclusions:
        conclusion_text = "\n\n✍️ <b>Eng uzun xulosalaringiz</b> (matn uzunligi bo'yicha):\n"
        for i, report in enumerate(top_conclusions, 1):
            book_title = (
                (report.book or "").strip()
                or conclusion_titles.get(report.id)
                or "Tanlanmagan kitob"
            )
            conclusion_text += f"{i}. <i>{book_title}</i> ({report.pages_read} bet)\n"

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

    response_text = (
        f"👤 <b>Sizning shaxsiy kabinetingiz</b>\n\n"
        f"🪙 <b>Kitobcha balansi:</b> {kitobcha_balance}\n"
        f"📚 <b>O'qilgan kitoblar:</b> {completed_books_count} ta\n"
        f"📄 <b>Jami o'qilgan sahifalar:</b> {total_pages_read}\n"
        f"⚡️ <b>O'rtacha kunlik o'qish:</b> {int(avg_pages_per_day)} bet\n"
        f"📅 <b>Eng faol kuningiz:</b> {most_active_day}\n"
        f"⏰ <b>Sevimli vaqtingiz:</b> {active_hour}\n"
        f"{rank_text}"
        f"{overtake_text}"
        f"{conclusion_text}"
        f"\n<i>Ma'lumotlar avtomatik yangilanib boradi.</i>"
    )

    show_cal = bool(user and getattr(user, "show_calendar", False))
    if show_cal:
        now = timezone.now()
        calendar_markup = await sync_to_async(generate_calendar_markup)(
            user_id, now.year, now.month
        )
        # Append a 'hide' toggle row so user can collapse from inside cabinet.
        calendar_markup.row(
            InlineKeyboardButton(
                "📅 Streak kalendarni yashirish",
                callback_data="cab:cal_toggle",
            )
        )
        await call.message.answer(response_text, parse_mode="HTML",
                                  reply_markup=calendar_markup)
    else:
        kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton(
                "📅 Streak kalendarni ko'rsatish",
                callback_data="cab:cal_toggle",
            )
        )
        await call.message.answer(response_text, parse_mode="HTML",
                                  reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "cab:cal_toggle", state="*")
async def cabinet_toggle_calendar(call: types.CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
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
# Settings — currently: per-user reminder count (0–3).
# ──────────────────────────────────────────────────────────────────────────
def _settings_markup(user) -> InlineKeyboardMarkup:
    rc = getattr(user, "reminder_count", 3) if user else 3
    show_cal = bool(getattr(user, "show_calendar", False)) if user else False
    accept = (getattr(user, "accept_congrats_from", "any") or "any") if user else "any"
    send_to = (getattr(user, "send_congrats_to", "any") or "any") if user else "any"

    kb = InlineKeyboardMarkup(row_width=4)
    # Reminder count row
    kb.insert(InlineKeyboardButton(text="🔔 Eslatma:", callback_data="noop"))
    for n in range(0, 4):
        marker = "●" if n == rc else "○"
        kb.insert(InlineKeyboardButton(
            text=f"{marker}{n}", callback_data=f"settings:reminders:{n}",
        ))
    # Calendar toggle
    cal_label = "✅ Kalendar yoqilgan" if show_cal else "⚪️ Kalendar o'chirilgan"
    kb.row(InlineKeyboardButton(text=cal_label, callback_data="settings:cal_toggle"))

    # Accept congrats from
    kb.row(InlineKeyboardButton("Tabriklarni qabul qilish:", callback_data="noop"))
    for code, label in (("any", "Hammadan"), ("male", "Erkak"), ("female", "Ayol")):
        marker = "●" if accept == code else "○"
        kb.insert(InlineKeyboardButton(
            text=f"{marker} {label}", callback_data=f"settings:accept:{code}",
        ))
    # Send congrats to
    kb.row(InlineKeyboardButton("Tabriklash yuborish:", callback_data="noop"))
    for code, label in (("any", "Hammaga"), ("male", "Erkak"), ("female", "Ayol")):
        marker = "●" if send_to == code else "○"
        kb.insert(InlineKeyboardButton(
            text=f"{marker} {label}", callback_data=f"settings:send:{code}",
        ))

    # Restart & Full reset buttons
    kb.row(
        InlineKeyboardButton(
            text="🔄 Qayta boshlash (ma'lumotlar saqlanadi)",
            callback_data="settings:restart_ask",
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="🗑 Barcha ma'lumotlarni o'chirish",
            callback_data="settings:reset_ask",
        )
    )
    return kb


def _settings_text(user, lang: str) -> str:
    rc = getattr(user, "reminder_count", 3) if user else 3
    show_cal = bool(getattr(user, "show_calendar", False)) if user else False
    accept = (getattr(user, "accept_congrats_from", "any") or "any") if user else "any"
    send_to = (getattr(user, "send_congrats_to", "any") or "any") if user else "any"

    label = {"any": "Hammadan/Hammaga", "male": "Erkak", "female": "Ayol"}
    return _t(
        lang,
        (
            "⚙️ <b>Sozlamalar</b>\n\n"
            "🔔 <b>Kunlik eslatmalar:</b>\n"
            "  0 — yo'q · 1 — kechqurun · 2 — ertalab + kechqurun · 3 — uch marta\n"
            f"  Joriy: <b>{rc}</b>\n\n"
            f"📅 <b>Kalendar (streak):</b> {'yoqilgan' if show_cal else 'o’chirilgan'}\n"
            "  Yoqsangiz, kabinetda kunlar ko'rsatiladi va kunni bossangiz o'sha kuni o'qigan kitobi va hisoboti ochiladi.\n\n"
            f"🎉 <b>Tabriklash filtri:</b>\n"
            f"  Qabul qilish: <b>{label.get(accept, accept)}</b>\n"
            f"  Yuborish: <b>{label.get(send_to, send_to)}</b>\n\n"
            "🔄 <b>Qayta boshlash</b> — faqat roʼyxatdan oʼtish jarayonini qaytaradi, ma’lumotlar saqlanadi.\n"
            "🗑 <b>Ma’lumotlarni oʼchirish</b> — barcha ma’lumotlaringiz butunlay oʼchiriladi va yangi foydalanuvchi sifatida boshlaysiz."
        ),
        (
            "⚙️ <b>Настройки</b>\n\n"
            "🔔 <b>Ежедневные напоминания:</b>\n"
            "  0 — нет · 1 — вечер · 2 — утро+вечер · 3 — три раза\n"
            f"  Текущее: <b>{rc}</b>\n\n"
            f"📅 <b>Календарь (streak):</b> {'включен' if show_cal else 'выключен'}\n\n"
            f"🎉 <b>Поздравления:</b>\n"
            f"  Принимаю: <b>{label.get(accept, accept)}</b>\n"
            f"  Отправляю: <b>{label.get(send_to, send_to)}</b>\n\n"
            "🔄 <b>Перезапуск</b> — только регистрация заново, данные сохраняются.\n"
            "🗑 <b>Удаление данных</b> — все данные удаляются, начинаете как новый пользователь."
        ),
    )


async def _menu_settings(call, user, state: FSMContext):
    await call.answer()
    lang = _user_lang(user)
    await call.message.answer(
        _settings_text(user, lang),
        parse_mode="HTML",
        reply_markup=_settings_markup(user),
    )


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("settings:"),
    state="*",
)
async def settings_pick(call: types.CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
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

    # -- Step-1: ask full reset
    elif action == "reset_ask":
        confirm_kb = InlineKeyboardMarkup(row_width=2)
        confirm_kb.row(
            InlineKeyboardButton(text="⚠️ Tasdiqlayman — o'chirish",
                                 callback_data="settings:reset_confirm"),
            InlineKeyboardButton(text="❌ Bekor qilish",
                                 callback_data="settings:cancel_action"),
        )
        await call.answer(
            "🚨 OGOH! Barcha ma'lumotlaringiz (hisobotlar, kitoblar, ballar, yutuqlar) "
            "butunlay o'chiriladi va tiklash imkoni bo'lmaydi! "
            "Davom etishni xohlaysizmi?",
            show_alert=True,
        )
        try:
            await call.message.edit_reply_markup(reply_markup=confirm_kb)
        except Exception:
            pass
        return

    # -- Step-2: confirm full reset
    elif action == "reset_confirm":
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
        await call.answer(
            "✅ Barcha ma'lumotlaringiz o'chirildi. Endi /start bosib qayta ro'yxatdan o'ting.",
            show_alert=True,
        )
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer(
            "🗑 Barcha ma'lumotlaringiz o'chirildi.\n\n"
            "Yangi foydalanuvchi sifatida /start ni bosing."
        )
        uname = f"@{call.from_user.username}" if call.from_user.username else "—"
        await _notify_admins(
            f"🗑 <b>To'liq o'chirish</b>\n"
            f"👤 {user.full_name or '—'} | {uname}\n"
            f"🆔 <code>{call.from_user.id}</code>\n"
            f"<i>Barcha ma'lumotlari o'chirildi.</i>"
        )
        return

    # -- Cancel two-step action
    elif action == "cancel_action":
        await call.answer("❌ Bekor qilindi")
        lang = _user_lang(user)
        try:
            await call.message.edit_text(
                _settings_text(user, lang),
                parse_mode="HTML",
                reply_markup=_settings_markup(user),
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
            reply_markup=_settings_markup(user),
        )
    except Exception:
        pass


@dp.callback_query_handler(lambda c: c.data == "noop", state="*")
async def menu_noop(call: types.CallbackQuery):
    await call.answer()


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
