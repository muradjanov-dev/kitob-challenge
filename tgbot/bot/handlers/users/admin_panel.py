from aiogram.utils.markdown import hlink
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from django.utils import timezone
from asgiref.sync import sync_to_async
from tgbot.bot.keyboards.reply import admin_keyboard, confirm_markup, main_markup, yes_or_no_markup, back_keyboard
from aiogram.dispatcher.filters import Text
from tgbot.bot import dp
from tgbot.models import TelegramProfile, BookReport, ConfirmationReport, BooksToRead, UserAchievement
from aiogram import types
from aiogram.dispatcher import FSMContext
from tgbot.bot.states.main import StatisticState, NotificationState, AdminUserBrowse
from tgbot.bot.filters import IsPrivate
from tgbot.bot.utils import aget_user
from tgbot.bot.loader import gettext as _, bot


@dp.message_handler(IsPrivate(), commands=["admin"], state="*")
@dp.message_handler(IsPrivate(), Text(equals=["👑 Admin panel", "👑 Админ панель"]), state="*")
async def admin_commands(message: types.Message, state: FSMContext = None):
    telegram_id = message.from_user.id
    user = await aget_user(telegram_id)
    if user and user.is_admin:
        if state is not None:
            try:
                await state.finish()
            except Exception:
                pass
        await message.answer("Menudan birini tanlang:", reply_markup=admin_keyboard)
    else:
        await message.answer("Siz admin emassiz!")


@dp.message_handler(IsPrivate(), commands=["test_weekly_report"], state="*")
async def test_weekly_report_handler(message: types.Message, state: FSMContext = None):
    """Admin-only: trigger AI-generated weekly report card to self.
    Usage: /test_weekly_report   (default uz)
           /test_weekly_report ru

    Runs the task inline (in bot process thread) so it works even if the
    celery_worker service is on a stale image without the task registered.
    """
    import asyncio
    user = await aget_user(message.from_user.id)
    if not (user and user.is_admin):
        await message.answer("Siz admin emassiz!")
        return

    args = (message.get_args() or "").strip().lower()
    lang = "ru" if args == "ru" else "uz"

    await message.answer(
        "⏳ AI report generatsiya qilinmoqda...\n"
        "🎨 Imagen 3 + 💎 Gemini 2.0 Flash\n"
        "20-40 soniyada rasm va matn keladi."
    )

    from tgbot.tasks import send_ai_report_to_admin
    # Run sync task in a thread to keep bot loop responsive.
    # .run() invokes the underlying function directly, bypassing Celery's
    # broker — so it works even when celery_worker is on a stale image.
    asyncio.create_task(asyncio.to_thread(
        send_ai_report_to_admin.run, message.from_user.id, lang
    ))


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
        await message.answer("Iltimos, faqat 'Ha' yoki 'Yo'q' yozing.", reply_markup=yes_or_no_markup())
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


USERS_PER_PAGE = 50


def _users_page_markup(page: int, total_pages: int, page_users):
    """Inline kb: per-user 'detail' buttons + page navigation."""
    kb = InlineKeyboardMarkup(row_width=2)
    for u in page_users:
        flag = "✅" if u.is_registered else "🚫"
        label = u.full_name or (("@" + u.username) if u.username else "Ism yo'q")
        if len(label) > 30:
            label = label[:28] + "…"
        kb.insert(
            InlineKeyboardButton(
                text=f"{flag} {u.id} · {label}",
                callback_data=f"adm_userd:{u.id}",
            )
        )
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"adm_userp:{page - 1}"
        ))
    nav.append(InlineKeyboardButton(
        text=f"{page}/{total_pages}", callback_data="noop"
    ))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            text="➡️", callback_data=f"adm_userp:{page + 1}"
        ))
    if nav:
        kb.row(*nav)
    return kb


def _build_users_overview(page: int):
    """Returns (text, markup) for the all-users overview page."""
    qs = TelegramProfile.objects.all().order_by("id")
    total = qs.count()
    registered = qs.filter(is_registered=True).count()
    unregistered = total - registered
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(1, min(page, total_pages))

    offset = (page - 1) * USERS_PER_PAGE
    page_users = list(qs[offset:offset + USERS_PER_PAGE])

    text = (
        "👨‍👩‍👦‍👦 <b>Barcha foydalanuvchilar</b>\n\n"
        f"📊 Jami: <b>{total}</b>\n"
        f"✅ Ro'yxatdan to'liq o'tgan: <b>{registered}</b>\n"
        f"🚫 Ro'yxatdan to'liq o'tmagan: <b>{unregistered}</b>\n\n"
        f"📄 Sahifa: <b>{page}/{total_pages}</b> · {USERS_PER_PAGE} tadan\n\n"
        "<i>Tugmalar:</i>\n"
        "Foydalanuvchini bosing — batafsil ma'lumot ko'rinadi\n"
        "✅ ro'yxatdan o'tgan · 🚫 o'tmagan"
    )
    markup = _users_page_markup(page, total_pages, page_users)
    return text, markup


def _format_books_section(user) -> str:
    """Finished + in-progress book lists with titles, for the admin detail card.
    Audio books are flagged; long lists are capped with a '+N more' tail."""
    from django.db.models import F
    from django.utils.html import escape

    CAP = 20

    finished = list(
        BooksToRead.objects.filter(
            user=user, current_page__gte=F("total_pages"), total_pages__gt=0
        ).order_by("title").values("title", "is_audio")
    )
    in_progress = list(
        BooksToRead.objects.filter(
            user=user, current_page__lt=F("total_pages"), total_pages__gt=0
        ).order_by("title").values("title", "current_page", "total_pages", "is_audio")
    )

    def _unit(is_audio):
        return "daq" if is_audio else "bet"

    section = ""
    if finished:
        lines = []
        for b in finished[:CAP]:
            tag = " 🎧" if b["is_audio"] else ""
            lines.append(f"  ✅ {escape(b['title'])}{tag}")
        if len(finished) > CAP:
            lines.append(f"  …va yana {len(finished) - CAP} ta")
        section += (
            f"\n\n📖 <b>Tugatgan kitoblar ({len(finished)}):</b>\n" + "\n".join(lines)
        )
    if in_progress:
        lines = []
        for b in in_progress[:CAP]:
            tag = " 🎧" if b["is_audio"] else ""
            lines.append(
                f"  📕 {escape(b['title'])}{tag} — {b['current_page']}/{b['total_pages']} {_unit(b['is_audio'])}"
            )
        if len(in_progress) > CAP:
            lines.append(f"  …va yana {len(in_progress) - CAP} ta")
        section += (
            f"\n\n📕 <b>Tugatilmagan kitoblar ({len(in_progress)}):</b>\n" + "\n".join(lines)
        )
    if not finished and not in_progress:
        section += "\n\n📚 <i>Kitoblar ro'yxati bo'sh.</i>"
    return section


def _build_user_detail(user_id: int) -> str:
    """Returns full HTML detail for a single TelegramProfile (admin view)."""
    from django.db.models import Count, Avg, Sum, F
    from django.db.models.functions import ExtractWeekDay, ExtractHour, TruncDate

    user = TelegramProfile.objects.select_related('region').filter(id=user_id).first()
    if not user:
        return "❌ Foydalanuvchi topilmadi."

    total_pages = (
        BookReport.objects.filter(user=user).aggregate(s=Sum("pages_read"))["s"] or 0
    )
    avg_pages = (
        BookReport.objects.filter(user=user).aggregate(a=Avg("pages_read"))["a"] or 0
    )
    completed_books = BooksToRead.objects.filter(
        user=user, current_page__gte=F("total_pages"), total_pages__gt=0
    ).count()
    in_progress_books = BooksToRead.objects.filter(
        user=user, current_page__lt=F("total_pages"), total_pages__gt=0
    ).count()

    distinct_days = (
        ConfirmationReport.objects.filter(user=user)
        .annotate(_d=TruncDate("date"))
        .values("_d").distinct().count()
    )
    reports_count = ConfirmationReport.objects.filter(user=user).count()

    weekday_stats = list(
        BookReport.objects.filter(user=user)
        .annotate(weekday=ExtractWeekDay("created_at"))
        .values("weekday").annotate(c=Count("id")).order_by("-c")
    )
    hour_stats = list(
        BookReport.objects.filter(user=user)
        .annotate(hour=ExtractHour("created_at"))
        .values("hour").annotate(c=Count("id")).order_by("-c")
    )

    weekday_map = {
        1: "Yakshanba", 2: "Dushanba", 3: "Seshanba", 4: "Chorshanba",
        5: "Payshanba", 6: "Juma", 7: "Shanba",
    }
    most_active_day = (
        weekday_map.get(weekday_stats[0]["weekday"], "—") if weekday_stats else "—"
    )
    if hour_stats:
        h = hour_stats[0]["hour"]
        active_hour = f"{h:02d}:00–{h+1:02d}:00"
    else:
        active_hour = "—"

    achievements = list(
        UserAchievement.objects.filter(user=user).values_list("code", flat=True)
    )
    ach_count = len(achievements)

    region_name = user.region.name if user.region else "—"
    gender_label = {"male": "Erkak", "female": "Ayol"}.get(user.gender or "", "—")
    age_label = {
        "u18": "<18", "18_25": "18–25", "26_35": "26–35", "36p": "36+",
    }.get(user.age_range or "", "—")

    from tgbot.models import Payment as _Payment
    prem_payment = (
        _Payment.objects
        .filter(user=user, status="paid", end_date__gte=timezone.localdate())
        .order_by("-end_date").first()
    )
    premium_line = (
        f"💎 <b>Premium:</b> faol — {prem_payment.end_date.strftime('%d.%m.%Y')} gacha"
        if prem_payment else "💎 <b>Premium:</b> yo'q"
    )

    username_str = f"@{user.username}" if user.username else "—"
    full_name = user.full_name or "—"
    reg_status = "✅ Ro'yxatdan to'liq o'tgan" if user.is_registered else "🚫 Tugatmagan"
    blocked = "🚫 Bloklangan" if user.is_blocked else ""
    admin_flag = "👑 Admin" if user.is_admin else ""
    days_since_join = (timezone.now() - user.created_at).days if user.created_at else 0

    ach_text = ""
    if achievements:
        from tgbot.services.achievements import find_achievement
        items = []
        for code in achievements:
            ach = find_achievement(code)
            if ach:
                items.append(f"{ach['emoji']} {ach['title_uz']}")
        ach_text = "\n\n🏆 <b>Yutuqlar (" + str(ach_count) + "):</b>\n" + "\n".join(items)

    return (
        f"👤 <b>{full_name}</b>\n"
        f"🆔 <code>{user.telegram_id}</code> · DB id: {user.id}\n"
        f"📱 {username_str}\n"
        f"🌐 Til: {(user.language or '—').upper()}\n"
        f"🚻 Jins: {gender_label}\n"
        f"🗺 Hudud: {region_name}\n"
        f"🎂 Yosh: {age_label}\n"
        f"📅 A'zo bo'lgan: {days_since_join} kun oldin\n"
        f"{reg_status}{(' · ' + blocked) if blocked else ''}{(' · ' + admin_flag) if admin_flag else ''}\n\n"
        f"🪙 <b>Kitobcha balansi:</b> {int(user.ball or 0)}\n"
        f"{premium_line}\n"
        f"📚 Hisobotlar: <b>{reports_count}</b>\n"
        f"📄 Jami betlar: <b>{total_pages}</b>\n"
        f"⚡️ O'rtacha: <b>{int(avg_pages)} bet/hisobot</b>\n"
        f"📅 Faol kunlar (uniq): <b>{distinct_days}</b>\n"
        f"📖 Tugatgan kitoblar: <b>{completed_books}</b>\n"
        f"📕 O'qilayotgan: <b>{in_progress_books}</b>\n"
        f"🗓 Eng faol kun: <b>{most_active_day}</b>\n"
        f"⏰ Eng faol vaqt: <b>{active_hour}</b>"
        f"{_format_books_section(user)}"
        f"{ach_text}"
    )


USERS_LIST_PER_PAGE = 50


def _active_users_qs():
    """Users shown in the admin list: everyone who hasn't blocked the bot,
    ordered stably by id so ordinal numbers are reproducible across pages."""
    return TelegramProfile.objects.filter(is_blocked=False).order_by("id")


def _user_by_ordinal(n: int):
    """Resolve the 1-based ordinal shown in the list back to a TelegramProfile."""
    if n < 1:
        return None
    rows = list(_active_users_qs()[n - 1:n])
    return rows[0] if rows else None


def _build_users_numbered(page: int):
    """(text, markup, total_pages) for the numbered, blocked-excluded users list.
    Ordinals are global: page 2 continues from where page 1 stopped."""
    from tgbot.models import Payment
    from django.utils.html import escape

    qs = _active_users_qs()
    total = qs.count()
    total_pages = max(1, (total + USERS_LIST_PER_PAGE - 1) // USERS_LIST_PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * USERS_LIST_PER_PAGE
    page_users = list(qs[offset:offset + USERS_LIST_PER_PAGE])

    page_ids = [u.id for u in page_users]
    prem_ids = set(
        Payment.objects.filter(
            user_id__in=page_ids, status="paid", end_date__gte=timezone.localdate()
        ).values_list("user_id", flat=True)
    )

    lines = [
        "👨‍👩‍👦‍👦 <b>Foydalanuvchilar ro'yxati</b>",
        f"📊 Jami (bloklanmagan): <b>{total}</b> · 📄 Sahifa <b>{page}/{total_pages}</b>\n",
    ]
    for i, u in enumerate(page_users, start=offset + 1):
        name = escape(u.full_name or (("@" + u.username) if u.username else "Ism yo'q"))
        badges = ""
        if u.id in prem_ids:
            badges += " 💎"
        if not u.is_registered:
            badges += " 🚫"
        if u.is_admin:
            badges += " 👑"
        lines.append(f"<b>{i}.</b> {name}{badges}")
    lines.append(
        "\n🔢 Foydalanuvchi ma'lumotini ko'rish uchun uning <b>raqamini</b> yuboring."
    )
    text = "\n".join(lines)

    kb = InlineKeyboardMarkup(row_width=3)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"adm_ulist:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"adm_ulist:{page + 1}"))
    kb.row(*nav)
    return text, kb, total_pages


@dp.message_handler(IsPrivate(), Text(contains="Foydalanuvchilar ro'yxati"))
async def all_users(message: types.Message, state: FSMContext = None):
    text, markup, _tp = _build_users_numbered(page=1)
    if state is not None:
        await AdminUserBrowse.listing.set()
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("adm_ulist:"), state="*")
async def adm_users_list_page(call: types.CallbackQuery, state: FSMContext):
    actor = await aget_user(call.from_user.id)
    if not (actor and actor.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    page = int(call.data.split(":", 1)[1])
    text, markup, _tp = await sync_to_async(_build_users_numbered)(page)
    await AdminUserBrowse.listing.set()
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=markup)
    await call.answer()


@dp.message_handler(IsPrivate(), state=AdminUserBrowse.listing, regexp=r"^\s*\d+\s*$")
async def admin_userlist_pick(message: types.Message, state: FSMContext):
    actor = await aget_user(message.from_user.id)
    if not (actor and actor.is_admin):
        await state.finish()
        return
    n = int(message.text.strip())
    target = await sync_to_async(_user_by_ordinal)(n)
    if not target:
        await message.answer("❌ Bunday raqamli foydalanuvchi yo'q. Boshqa raqam yuboring.")
        return
    text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(target.id)
    await message.answer(
        text, parse_mode="HTML",
        reply_markup=_user_detail_markup(target_user, is_premium),
    )


@dp.message_handler(IsPrivate(), state=AdminUserBrowse.listing)
async def admin_userlist_text(message: types.Message, state: FSMContext):
    # In the list, a non-numeric text is treated as a search query (the digit
    # handler above caught the numbers). Stays in listing mode so the admin can
    # keep browsing/searching freely.
    actor = await aget_user(message.from_user.id)
    if not (actor and actor.is_admin):
        await state.finish()
        return
    await _do_user_search(message, (message.text or "").strip())


def _search_users(query: str, limit: int = 20):
    """Find users by name / username / phone / id.

    Numeric queries match telegram_id / db-id / phone exactly first. Name
    queries use a fuzzy, transliteration-aware match: the query and every
    stored name are normalized (Cyrillic→Latin, apostrophes stripped) so
    "Maryam" finds "Марям"/"Maryamoy"/"Mariam". Results are ranked by closeness
    and the nearest ones are always returned even on typos. Blocked users are
    included so admins can find and unblock them."""
    from django.db.models import Q
    import difflib
    from tgbot.models import normalize_uzbek_text

    q = (query or "").strip()
    if not q:
        return []

    digits = q.lstrip("+").replace(" ", "").replace("-", "")
    if digits.isdigit():
        exact = list(
            TelegramProfile.objects.filter(
                Q(telegram_id=int(digits)) | Q(id=int(digits))
            )[:limit]
        )
        if exact:
            return exact
        phone_hits = list(
            TelegramProfile.objects.filter(phone_number__icontains=digits)[:limit]
        )
        if phone_hits:
            return phone_hits

    norm_q = normalize_uzbek_text(q)
    if not norm_q:
        return []

    # Score every user by how close their (normalized) name is to the query.
    scored = []  # (score, id)
    rows = TelegramProfile.objects.values_list("id", "full_name", "username")
    for uid, full_name, username in rows.iterator():
        name = (full_name or username or "")
        norm_name = normalize_uzbek_text(name)
        if not norm_name:
            continue
        if norm_q in norm_name:
            # Substring hit — strongest; reward matches near the start.
            pos = norm_name.index(norm_q)
            score = 0.9 + 0.1 * (1.0 - pos / max(len(norm_name), 1))
        else:
            best = difflib.SequenceMatcher(None, norm_q, norm_name).ratio()
            for tok in norm_name.split():
                r = difflib.SequenceMatcher(None, norm_q, tok).ratio()
                if r > best:
                    best = r
            score = best
        scored.append((score, uid))

    scored.sort(key=lambda x: x[0], reverse=True)
    # Prefer reasonably-close matches; if none clear the bar, still return the
    # nearest few so the admin always gets the closest candidates.
    good = [uid for s, uid in scored if s >= 0.45][:limit]
    top_ids = good or [uid for _, uid in scored[:5]]
    if not top_ids:
        return []

    by_id = {u.id: u for u in TelegramProfile.objects.filter(id__in=top_ids)}
    return [by_id[i] for i in top_ids if i in by_id]


async def _do_user_search(message: types.Message, query: str):
    """Run a user search and render results. Shared by the list-mode text path,
    the searching state, and the /find command — so search works no matter how
    the admin got here (and even if FSM state was lost)."""
    from django.utils.html import escape as _escape

    if not query:
        await message.answer("Ism, username, telefon yoki ID yuboring.")
        return

    results = await sync_to_async(_search_users)(query)

    if not results:
        await message.answer(f"🔍 «{_escape(query)}» bo'yicha hech narsa topilmadi.")
        return

    if len(results) == 1:
        u = results[0]
        text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(u.id)
        await message.answer(
            text, parse_mode="HTML",
            reply_markup=_user_detail_markup(target_user, is_premium),
        )
        return

    kb = InlineKeyboardMarkup(row_width=1)
    lines = [f"🔍 «{_escape(query)}» — <b>{len(results)}</b> ta natija:\n"]
    for u in results:
        name = u.full_name or (("@" + u.username) if u.username else "Ism yo'q")
        flag = "🚫" if u.is_blocked else ("✅" if u.is_registered else "·")
        lines.append(f"{flag} {_escape(name)} — <code>{u.telegram_id}</code>")
        label = f"{name}"[:40]
        kb.add(InlineKeyboardButton(f"👤 {label}", callback_data=f"adm_userd:{u.id}"))
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@dp.message_handler(IsPrivate(), commands=["find", "qidir"], state="*")
async def admin_find_command(message: types.Message, state: FSMContext = None):
    """Bulletproof search that works in ANY state: /find <name|phone|id>."""
    actor = await aget_user(message.from_user.id)
    if not (actor and actor.is_admin):
        await message.answer("Siz admin emassiz!")
        return
    await _do_user_search(message, (message.get_args() or "").strip())


@dp.message_handler(IsPrivate(), state=AdminUserBrowse.searching)
async def admin_user_search_query(message: types.Message, state: FSMContext):
    actor = await aget_user(message.from_user.id)
    if not (actor and actor.is_admin):
        await state.finish()
        return
    # Switch to listing mode so further plain numbers/names keep working even if
    # this message landed on a worker that had lost the 'searching' state.
    await AdminUserBrowse.listing.set()
    await _do_user_search(message, (message.text or "").strip())


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("adm_userp:"), state="*")
async def adm_user_page(call: types.CallbackQuery):
    user = await aget_user(call.from_user.id)
    if not (user and user.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    page = int(call.data.split(":", 1)[1])
    text, markup = _build_users_overview(page=page)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=markup)
    await call.answer()


def _is_user_premium(user) -> bool:
    """True if the user has an active paid subscription today."""
    from tgbot.models import Payment
    return Payment.objects.filter(
        user=user, status="paid", end_date__gte=timezone.localdate()
    ).exists()


def _user_detail_markup(target_user, is_premium: bool) -> InlineKeyboardMarkup:
    """Shared admin detail-card keyboard: contact, premium toggle, block toggle,
    and back. Used by the detail view and both toggle handlers so the buttons
    never diverge."""
    kb = InlineKeyboardMarkup(row_width=1)
    if target_user and target_user.telegram_id:
        kb.add(InlineKeyboardButton(
            "✉️ Xabar yozish (Loyiha asoschisidan)",
            callback_data=f"owner_reply:{target_user.telegram_id}",
        ))
        # Premium grant / revoke — admin-only.
        if is_premium:
            kb.add(InlineKeyboardButton(
                "❌ Premiumni o'chirish",
                callback_data=f"adm_prem_toggle:{target_user.id}:0",
            ))
        else:
            kb.add(InlineKeyboardButton(
                "💎 Premium berish (30 kun)",
                callback_data=f"adm_prem_toggle:{target_user.id}:1",
            ))
        # Block / Unblock toggle — admin-only control over user access.
        if target_user.is_blocked:
            kb.add(InlineKeyboardButton(
                "✅ Blokdan chiqarish",
                callback_data=f"adm_block_toggle:{target_user.id}:0",
            ))
        else:
            kb.add(InlineKeyboardButton(
                "🚫 Bloklash",
                callback_data=f"adm_block_toggle:{target_user.id}:1",
            ))
    kb.add(InlineKeyboardButton(
        "⬅️ Ro'yxatga qaytish", callback_data="adm_ulist:1",
    ))
    return kb


def _detail_text_user_premium(target_id: int):
    """Sync helper: returns (text, target_user, is_premium) in one DB round."""
    text = _build_user_detail(target_id)
    target_user = TelegramProfile.objects.filter(id=target_id).first()
    is_premium = _is_user_premium(target_user) if target_user else False
    return text, target_user, is_premium


@dp.callback_query_handler(IsPrivate(), lambda c: c.data and c.data.startswith("adm_userd:"), state="*")
async def adm_user_detail(call: types.CallbackQuery):
    actor = await aget_user(call.from_user.id)
    if not (actor and actor.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    target_id = int(call.data.split(":", 1)[1])
    text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(target_id)
    back_kb = _user_detail_markup(target_user, is_premium)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=back_kb)
    await call.answer()


@dp.callback_query_handler(
    IsPrivate(),
    lambda c: c.data and c.data.startswith("adm_block_toggle:"),
    state="*",
)
async def adm_block_toggle(call: types.CallbackQuery):
    """Toggle a user's is_blocked flag. Notifies the target so they aren't
    silently locked out, and re-renders the detail card."""
    actor = await aget_user(call.from_user.id)
    if not (actor and actor.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer()
        return
    target_id = int(parts[1])
    block = parts[2] == "1"

    target_user = await sync_to_async(
        TelegramProfile.objects.filter(id=target_id).first
    )()
    if not target_user:
        await call.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    if target_user.is_admin and block:
        await call.answer("Adminni bloklash mumkin emas.", show_alert=True)
        return

    await sync_to_async(
        TelegramProfile.objects.filter(id=target_id).update
    )(is_blocked=block)

    # Inform the affected user so they understand why the bot stopped responding.
    try:
        if block:
            await bot.send_message(
                target_user.telegram_id,
                "🚫 <b>Sizning hisobingiz cheklangan.</b>\n\n"
                "Bot funksiyalaridan foydalana olmaysiz.\n"
                "Sabab yoki blokdan chiqarish bo'yicha "
                "<b>📞 Admin bilan bog'lanish</b> tugmasi orqali murojaat qilishingiz mumkin.",
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                target_user.telegram_id,
                "✅ <b>Sizning hisobingiz qayta tiklandi.</b>\n\n"
                "Botning barcha funksiyalari yana ochildi. Marhamat!",
                parse_mode="HTML",
            )
    except Exception as e:
        print(f"block-toggle notify failed for {target_user.telegram_id}: {e}")

    await call.answer(
        "🚫 Bloklandi" if block else "✅ Blokdan chiqarildi",
        show_alert=False,
    )

    # Re-render the detail card so the button flips immediately.
    text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(target_id)
    back_kb = _user_detail_markup(target_user, is_premium)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
    except Exception:
        pass


@dp.callback_query_handler(
    IsPrivate(),
    lambda c: c.data and c.data.startswith("adm_prem_toggle:"),
    state="*",
)
async def adm_prem_toggle(call: types.CallbackQuery):
    """Grant or revoke Premium for any user from the admin user-detail card.
    Grant = a 30-day paid Payment (extends an existing active one). Revoke =
    expire every active paid Payment. Notifies the target and re-renders."""
    actor = await aget_user(call.from_user.id)
    if not (actor and actor.is_admin):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer()
        return
    target_id = int(parts[1])
    grant = parts[2] == "1"

    @sync_to_async
    def _apply():
        from datetime import timedelta
        from tgbot.models import Payment
        target = TelegramProfile.objects.filter(id=target_id).first()
        if not target:
            return None, None
        today = timezone.localdate()
        if grant:
            active = Payment.objects.filter(
                user=target, status="paid", end_date__gte=today
            ).order_by("-end_date").first()
            if active:
                active.end_date = active.end_date + timedelta(days=30)
                active.save(update_fields=["end_date"])
                new_until = active.end_date
            else:
                p = Payment.objects.create(
                    user=target, amount=0, start_date=today,
                    end_date=today + timedelta(days=30), status="paid",
                )
                new_until = p.end_date
            return target, new_until
        else:
            Payment.objects.filter(
                user=target, status="paid", end_date__gte=today
            ).update(end_date=today - timedelta(days=1))
            return target, None

    target_user, new_until = await _apply()
    if not target_user:
        await call.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    # Notify the affected user.
    try:
        if grant:
            await bot.send_message(
                target_user.telegram_id,
                "💎 <b>Sizga Premium obuna faollashtirildi!</b>\n\n"
                f"📅 Amal qilish muddati: <b>{new_until.strftime('%d.%m.%Y')}</b> gacha\n\n"
                "Barcha Premium imtiyozlardan bahramand bo'ling! 🔥",
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                target_user.telegram_id,
                "💎 <b>Premium obunangiz to'xtatildi.</b>\n\n"
                "Qayta faollashtirish uchun «💎 Premium obuna» bo'limiga o'ting.",
                parse_mode="HTML",
            )
    except Exception as e:
        print(f"prem-toggle notify failed for {target_user.telegram_id}: {e}")

    await call.answer(
        "💎 Premium berildi (30 kun)" if grant else "❌ Premium o'chirildi",
        show_alert=False,
    )

    # Re-render the detail card so the button flips immediately.
    text, target_user, is_premium = await sync_to_async(_detail_text_user_premium)(target_id)
    back_kb = _user_detail_markup(target_user, is_premium)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
    except Exception:
        pass


@dp.callback_query_handler(IsPrivate(), lambda c: c.data == "noop", state="*")
async def adm_noop(call: types.CallbackQuery):
    await call.answer()


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
    user = await aget_user(call.from_user.id)
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

    admin_id = call.from_user.id
    if action == "registered":
        await registered_lists(msg)
    elif action == "unregistered":
        await unregistered_lists(msg)
    elif action == "all_users":
        await all_users(msg, state)
    elif action == "user_search":
        await AdminUserBrowse.listing.set()
        await call.message.answer(
            "🔍 <b>Foydalanuvchi qidirish</b>\n\n"
            "Ism, username, telefon yoki ID yuboring — eng yaqin mosliklar chiqadi.\n"
            "Yoki istalgan paytda: <code>/find ism</code>\n"
            "Ro'yxatdan tartib raqamini yuborsangiz — o'sha foydalanuvchi ochiladi.",
            parse_mode="HTML",
        )
    elif action == "stats":
        await show_global_statistics(msg)
    elif action == "notify":
        await send_notification_text_handler(msg)
    elif action == "reminders":
        from tgbot.bot.handlers.users.reminders import reminders_menu
        await reminders_menu(msg, state, _admin_id=admin_id)
    elif action == "poll_new":
        from tgbot.bot.handlers.users.polls_admin import poll_admin_start
        await poll_admin_start(msg, state, _admin_id=admin_id)
    elif action == "poll_results":
        from tgbot.bot.handlers.users.polls_admin import poll_results_list
        await poll_results_list(msg, state, _admin_id=admin_id)
    elif action == "book_quiz":
        # Build one fresh Viktorina round now and broadcast it. Build runs
        # synchronously so the admin gets immediate feedback (incl. the
        # "not enough material" case); the broadcast is fired in the background
        # on THIS process so it doesn't depend on a separate worker deploy.
        import asyncio
        from asgiref.sync import sync_to_async
        from tgbot.services.book_quiz import build_quiz_round
        from tgbot.tasks import _broadcast_quiz_round

        quiz_round = await sync_to_async(build_quiz_round)()
        if not quiz_round:
            await call.message.answer(
                "⚠️ Hozircha yetarli xulosa yo'q — viktorina qurib bo'lmadi.\n"
                "Foydalanuvchilar ko'proq xulosa yuborgach qayta urinib ko'ring."
            )
        else:
            asyncio.get_event_loop().run_in_executor(
                None, lambda: _broadcast_quiz_round(quiz_round)
            )
            await call.message.answer(
                f"✅ Yangi viktorina yuborilmoqda!\n\n"
                f"📖 To'g'ri javob: <b>{quiz_round.correct_title}</b>\n"
                f"<i>Guruhlar va barcha foydalanuvchilarga tarqatilyapti…</i>",
                parse_mode="HTML",
            )
    elif action == "reader_titles":
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(
            "✅ Hammaga e'lon qilish", callback_data="admin:reader_titles_go",
        ))
        await call.message.answer(
            "🏅 <b>Kitobxon nominatsiyalari</b> (oxirgi 30 kun) — 8 ta toifa:\n"
            "🌙 Tungi · 🌅 Saharxez · ☀️ Kunduzgi · 🎧 Audio · ✍️ So'z ustasi · "
            "🤝 Sahiy tabriklovchi · 🎁 Eng ko'p tabriklangan · 🔥 Eng intizomli\n\n"
            "Barcha guruhlar va foydalanuvchilarga yuborilsinmi?",
            parse_mode="HTML",
            reply_markup=kb,
        )
    elif action == "reader_titles_go":
        # Run on THIS (web) process in a background thread rather than dispatching
        # to the celery worker — admin one-off broadcasts shouldn't depend on a
        # separate worker deploy. Fire-and-forget so the handler returns at once.
        import asyncio
        from tgbot.tasks import announce_reader_titles
        asyncio.get_event_loop().run_in_executor(None, announce_reader_titles)
        await call.message.answer(
            "✅ Kitobxon nominatsiyalari e'lon qilinmoqda — barcha guruh va "
            "foydalanuvchilarga yuborilyapti! 🏅"
        )
    elif action == "founder_gift":
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(
            "✅ Ha, hammaga 24h Premium berish", callback_data="admin:founder_gift_go",
        ))
        await call.message.answer(
            "🎁 <b>Loyiha asoschisidan sovg'a</b>\n\n"
            "Barcha ro'yxatdan o'tgan foydalanuvchilarga <b>24 soatlik 💎 Premium</b> "
            "beriladi va hamma joyda (guruhlar + shaxsiy) e'lon qilinadi.\n\n"
            "Davom etamizmi?",
            parse_mode="HTML",
            reply_markup=kb,
        )
    elif action == "founder_gift_go":
        # Run on THIS (web) process in a background thread (see note above).
        import asyncio
        from tgbot.tasks import grant_everyone_premium
        asyncio.get_event_loop().run_in_executor(
            None, lambda: grant_everyone_premium(days=1, announce=True)
        )
        await call.message.answer(
            "✅ Sovg'a ulashilmoqda — barchaga 24 soatlik 💎 Premium berilib, "
            "e'lon qilinyapti! 🎁🔥\n\n"
            "<i>E'lon barcha guruhlar va foydalanuvchilarga yuborilmoqda — "
            "bir-ikki daqiqada yakunlanadi.</i>",
            parse_mode="HTML",
        )
    elif action == "top_readers":
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📅 Bugun",    callback_data="admin:top_readers:daily"),
            InlineKeyboardButton("📅 3 kun",    callback_data="admin:top_readers:3days"),
            InlineKeyboardButton("📅 Hafta",    callback_data="admin:top_readers:weekly"),
            InlineKeyboardButton("📅 Oy",       callback_data="admin:top_readers:monthly"),
            InlineKeyboardButton("📅 3 oy",     callback_data="admin:top_readers:3monthly"),
            InlineKeyboardButton("📅 Yil",      callback_data="admin:top_readers:yearly"),
        )
        await call.message.answer(
            "📊 Qaysi davr uchun yuborish?",
            reply_markup=kb,
        )
    elif action.startswith("top_readers:"):
        import datetime as _dt
        import json as _json
        from asgiref.sync import sync_to_async
        from tgbot.tasks import _build_top_readers_message, _toplist_congrats_keyboard
        from tgbot.bot.loader import bot
        from tgbot.bot.consts import BOYS_GROUP_ID, GIRLS_GROUP_ID

        period_key = action.split(":", 1)[1]
        from django.utils import timezone as _tz
        today = _tz.localdate()
        period_cfg = {
            "daily":    (today,                              today, "Bugun 🔥",        20),
            "3days":    (today - _dt.timedelta(days=2),     today, "Oxirgi 3 kunda",  20),
            "weekly":   (today - _dt.timedelta(days=6),     today, "Bu hafta 🏆",     25),
            "monthly":  (today - _dt.timedelta(days=29),    today, "Bu oy 📅",        30),
            "3monthly": (today - _dt.timedelta(days=89),    today, "3 oylik 📊",      40),
            "yearly":   (today - _dt.timedelta(days=364),   today, "Yillik 🏅",       60),
        }
        if period_key not in period_cfg:
            await call.message.answer("Noma'lum davr.")
        else:
            start_date, end_date, label, limit = period_cfg[period_key]
            msg_text = await sync_to_async(_build_top_readers_message)(start_date, end_date, label, limit=limit)
            if not msg_text:
                await call.message.answer("❌ Bu davr uchun ma'lumot yo'q.")
            else:
                date_str = end_date.strftime("%Y%m%d")
                keyboard_json = _toplist_congrats_keyboard(period_key, date_str)
                kb_data = _json.loads(keyboard_json)
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                congrats_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"])
                     for btn in row]
                    for row in kb_data["inline_keyboard"]
                ])

                # ── 1. Groups: sent immediately via bot (reliable, no Celery) ──
                GENERAL_GROUP_ID = -1002237773868
                general_thread = __import__('os').environ.get("MESSAGE_THREAD_ID")
                general_thread = int(general_thread) if general_thread else None

                for group_id, thread_id in [
                    (GENERAL_GROUP_ID, general_thread),
                    (int(BOYS_GROUP_ID), None),
                    (int(GIRLS_GROUP_ID), None),
                ]:
                    try:
                        await bot.send_message(
                            chat_id=group_id,
                            text=msg_text,
                            parse_mode="HTML",
                            reply_markup=congrats_kb,
                            message_thread_id=thread_id,
                            disable_web_page_preview=True,
                        )
                    except Exception as e:
                        print(f"group send {group_id} failed: {e}")

                await call.message.answer("✅ Guruhga yuborildi.")
    elif action == "quizzes":
        from tgbot.bot.handlers.users.quiz_admin import show_quiz_list
        await show_quiz_list(call.message, user)
    elif action == "kitobcha_top":
        await _send_kitobcha_top(call.message)
    elif action == "shop":
        from tgbot.bot.handlers.users.shop_admin import shop_admin_menu
        await shop_admin_menu(call.message, user)
    else:
        await msg.answer("Noma'lum amal.")


async def _send_kitobcha_top(message):
    """Admin-only ranking of users by Kitobcha (ball) balance, Top 30."""
    from asgiref.sync import sync_to_async
    from django.utils.html import escape as _esc
    from tgbot.models import TelegramProfile

    @sync_to_async
    def _load():
        return list(
            TelegramProfile.objects
            .filter(is_registered=True)
            .exclude(ball__isnull=True)
            .order_by("-ball", "id")[:30]
            .values_list("telegram_id", "full_name", "ball")
        )

    rows = await _load()
    rows = [r for r in rows if (r[2] or 0) > 0]
    if not rows:
        await message.answer("🪙 Hozircha hech kimda Kitobcha yo'q.")
        return

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🪙 <b>Kitobcha bo'yicha reyting (Top 30):</b>\n"]
    for i, (tg_id, name, ball) in enumerate(rows, 1):
        marker = medals.get(i, f"{i}.")
        nm = _esc(name or "Kitobxon")
        lines.append(
            f"{marker} <a href='tg://user?id={tg_id}'>{nm}</a>: <b>{int(ball or 0)}</b> 🪙"
        )
    total = sum(int(r[2] or 0) for r in rows)
    lines.append(f"\n📊 Top 30 jami: <b>{total}</b> 🪙")
    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
