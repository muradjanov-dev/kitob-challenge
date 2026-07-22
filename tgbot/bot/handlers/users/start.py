import os

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import CommandStart, ChatTypeFilter
from aiogram.types import ChatType
from asgiref.sync import sync_to_async

from tgbot.models import TelegramProfile, Region
from tgbot.bot.keyboards.reply import main_markup_for_user, back_keyboard
from tgbot.bot.handlers.users.menu_router import send_main_menu
from tgbot.bot.keyboards.inline import (
    gender_inline_kb,
    region_inline_kb,
    age_inline_kb,
)
from tgbot.bot.loader import dp, bot
from tgbot.bot.states.main import AdmissionState
from tgbot.bot.utils import aget_user


AGE_LABELS = {
    "u18": "&lt;18",
    "18_25": "18-25",
    "26_35": "26-35",
    "36p": "36+",
}

GENDER_LABELS_UZ = {"male": "Erkak", "female": "Ayol"}
GENDER_LABELS_RU = {"male": "Мужчина", "female": "Женщина"}


def t(language: str, uz: str, ru: str) -> str:
    return ru if language == "ru" else uz


def _user_lang(user) -> str:
    return (user.language if user else None) or "uz"


@dp.message_handler(
    CommandStart(),
    ChatTypeFilter((ChatType.GROUP, ChatType.SUPERGROUP)),
    state="*",
)
async def do_start_group(message: types.Message, state: FSMContext):
    """Group /start: only handles /start quiz_<code> (group quiz spawn).
    Anything else in a group is ignored — registration etc. is private-only."""
    args = message.get_args()
    if not args or not args.startswith("quiz_"):
        return
    from tgbot.bot.handlers.users.quiz_play import start_group_quiz
    await start_group_quiz(message, args[len("quiz_"):])


@dp.message_handler(CommandStart(), ChatTypeFilter(ChatType.PRIVATE), state="*")
async def do_start(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    args = message.get_args()
    lang = _user_lang(user)

    # Treat as registered if either flag is set OR they have a full_name
    # (handles legacy /restart that wiped is_registered=False).
    already_registered = bool(
        user and (user.is_registered or (user.full_name and user.gender))
    )

    # Admin deep link: /start prof_<telegram_id> — open that user's profile
    # card (with the message-relay button). Only admins get the card; for
    # everyone else it falls through to the normal start flow.
    if args and args.startswith("prof_") and user and user.is_admin:
        target_tid = args[len("prof_"):]
        if target_tid.isdigit():
            await state.finish()
            from tgbot.bot.handlers.users.admin_panel import open_profile_card_by_tid
            await open_profile_card_by_tid(message, int(target_tid))
            return

    # Admin deep link: /start msg_<telegram_id> — start writing a message to
    # that user (relayed as the project owner). Powers the "✍️ YOZISH" link on
    # the profile card. Non-admins fall through to the normal start flow.
    if args and args.startswith("msg_") and user and user.is_admin:
        target_tid = args[len("msg_"):]
        if target_tid.isdigit():
            await state.finish()
            from tgbot.bot.handlers.users.contact_admin import begin_owner_reply
            await begin_owner_reply(message, state, target_tid)
            return

    # Handle quiz deep link: /start quiz_<code>
    if args and args.startswith("quiz_"):
        if already_registered:
            if user and not user.is_registered:
                user.is_registered = True
                await sync_to_async(user.save)(update_fields=["is_registered"])
            await state.finish()
            from tgbot.bot.handlers.users.quiz_play import start_solo_quiz
            await start_solo_quiz(message, args[len("quiz_"):])
            return
        # Not registered yet — save code for after registration
        await state.update_data(pending_quiz_code=args[len("quiz_"):])

    # Report deep link: /start report — from the "Hisobot jo'natish" button in
    # group broadcasts. Open the report flow directly in the bot DM.
    if args == "report" and already_registered:
        if user and not user.is_registered:
            user.is_registered = True
            await sync_to_async(user.save)(update_fields=["is_registered"])
        await state.finish()
        from tgbot.bot.handlers.users.report import send_daily_report_handler
        await send_daily_report_handler(message, state)
        return

    # Kitob Zanjiri deep link: /start zanjir — from the group announcement
    # button. Opens the live game Mini App (web_app buttons are only allowed in
    # private chats, so we hand it off here in the DM).
    if args == "zanjir" and already_registered:
        if user and not user.is_registered:
            user.is_registered = True
            await sync_to_async(user.save)(update_fields=["is_registered"])
        await state.finish()
        from aiogram.types import (
            InlineKeyboardMarkup as _IKM, InlineKeyboardButton as _IKB, WebAppInfo as _WAI,
        )
        from src.settings import WEB_DOMAIN
        kb = _IKM().add(_IKB(
            "🔗 Kitob Zanjirini ochish", web_app=_WAI(url=f"{WEB_DOMAIN}/zanjir/"),
        ))
        await message.answer(
            "🔗 <b>Kitob Zanjiri</b> — jonli o'yin boshlandi!\n"
            "Pastdagi tugmani bosing va qatnashing 👇",
            reply_markup=kb, parse_mode="HTML",
        )
        return

    # Ko'pchilik / Qal'a / Emoji / Hikmat / Detektiv / Omon qolish / Bilim
    # O'yini (4 flavors) deep links — open the respective game Mini App.
    _GAME_DEEPLINKS = {
        "kopchilik": ("/kopchilik/", "🗣 O'yinni ochish", "Ko'pchilik nima dedi?"),
        "qala": ("/qala/", "🏰 O'yinni ochish", "Bilim Qal'asi"),
        "emoji": ("/emoji/", "🎬 O'yinni ochish", "Emoji Kitob"),
        "hikmat": ("/hikmat/", "☪️ O'yinni ochish", "Hikmat Xazinasi"),
        "detektiv": ("/detektiv/", "📖 O'yinni ochish", "Kitob Detektivi"),
        "omon-qolish": ("/omon-qolish/", "💀 O'yinni ochish", "Omon qolish"),
        "ikki-haqiqat": ("/ikki-haqiqat/", "🎭 O'yinni ochish", "Ikki haqiqat, bir yolg'on"),
        "kim-yolgonchi": ("/kim-yolgonchi/", "🃏 O'yinni ochish", "Kim yolg'onchi?"),
        "bog-lanish": ("/bog-lanish/", "🧩 O'yinni ochish", "Yashirin bog'lanish"),
        "jamoa-jangi": ("/jamoa-jangi/", "👥 O'yinni ochish", "Jamoa Jangi"),
    }
    if args in _GAME_DEEPLINKS and already_registered:
        if user and not user.is_registered:
            user.is_registered = True
            await sync_to_async(user.save)(update_fields=["is_registered"])
        await state.finish()
        from aiogram.types import (
            InlineKeyboardMarkup as _IKM2, InlineKeyboardButton as _IKB2, WebAppInfo as _WAI2,
        )
        from src.settings import WEB_DOMAIN
        path, label, title = _GAME_DEEPLINKS[args]
        kb = _IKM2().add(_IKB2(label, web_app=_WAI2(url=f"{WEB_DOMAIN}{path}")))
        await message.answer(
            f"<b>{title}</b> — jonli o'yin boshlandi!\nPastdagi tugmani bosing 👇",
            reply_markup=kb, parse_mode="HTML",
        )
        return

    if already_registered:
        if user and not user.is_registered:
            user.is_registered = True
            await sync_to_async(user.save)(update_fields=["is_registered"])
        await state.finish()
        await send_main_menu(
            message, user,
            header_text=t(lang, "🏠 Bosh menyu", "🏠 Главное меню"),
        )
        return

    if args:
        await state.update_data(referral_code=args)

    await message.answer(
        t(
            lang,
            "Iye, xush kelibsiz! 👋\nIltimos, ismingizni kiriting:",
            "Привет, добро пожаловать! 👋\nПожалуйста, введите ваше имя:",
        ),
        reply_markup=back_keyboard,
    )
    await AdmissionState.full_name.set()


@dp.message_handler(state=AdmissionState.full_name)
async def full_name_handler(message: types.Message, state: FSMContext):
    full_name_text = (message.text or "").strip()
    user = await aget_user(message.from_user.id)
    lang = _user_lang(user)

    if not full_name_text:
        await message.answer(t(lang, "Iltimos, ismingizni yozing.", "Пожалуйста, введите имя."))
        return

    if len(full_name_text) > 60:
        await message.answer(
            t(
                lang,
                "Ismingiz 60 belgidan uzun bo'lmasligi kerak.",
                "Имя не должно превышать 60 символов.",
            )
        )
        return

    await state.update_data(full_name=full_name_text)
    await message.answer(
        t(lang, "Jinsingizni tanlang:", "Выберите ваш пол:"),
        reply_markup=gender_inline_kb(language=lang),
    )
    await AdmissionState.gender.set()


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("reg_gender:"),
    state=AdmissionState.gender,
)
async def gender_pick(call: types.CallbackQuery, state: FSMContext):
    gender = call.data.split(":", 1)[1]
    await state.update_data(gender=gender)

    user = await aget_user(call.from_user.id)
    lang = _user_lang(user)

    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await call.message.answer(
        t(lang, "Hududingizni tanlang:", "Выберите ваш регион:"),
        reply_markup=await sync_to_async(region_inline_kb)(),
    )
    await AdmissionState.region.set()


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("reg_region:"),
    state=AdmissionState.region,
)
async def region_pick(call: types.CallbackQuery, state: FSMContext):
    region_id = int(call.data.split(":", 1)[1])
    await state.update_data(region_id=region_id)

    user = await aget_user(call.from_user.id)
    lang = _user_lang(user)

    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await call.message.answer(
        t(lang, "Yoshingizni tanlang:", "Выберите ваш возраст:"),
        reply_markup=age_inline_kb(),
    )
    await AdmissionState.age.set()


@dp.callback_query_handler(
    lambda c: c.data and c.data.startswith("reg_age:"),
    state=AdmissionState.age,
)
async def age_pick(call: types.CallbackQuery, state: FSMContext):
    age_code = call.data.split(":", 1)[1]
    user_pre = await aget_user(call.from_user.id)
    lang = _user_lang(user_pre)

    if age_code not in AGE_LABELS:
        await call.answer(
            t(lang, "Noto'g'ri tanlov", "Неверный выбор"), show_alert=True
        )
        return

    data = await state.get_data()
    full_name = data.get("full_name") or ""
    gender = data.get("gender")
    region_id = data.get("region_id")
    referral_code = data.get("referral_code")

    defaults = {
        "username": call.from_user.username,
        "full_name": full_name,
        "gender": gender,
        "region_id": region_id,
        "age_range": age_code,
        "is_registered": True,
    }
    # Pending referral: hold the inviter's code on the new user; it is processed
    # only after they submit their first ConfirmationReport, then cleared.
    if referral_code:
        defaults["pending_referral_code"] = referral_code

    user, _created = await sync_to_async(
        TelegramProfile.objects.update_or_create
    )(
        telegram_id=call.from_user.id,
        defaults=defaults,
    )

    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    lang = user.language or "uz"
    await call.message.answer(
        t(
            lang,
            "✅ Ro'yxatdan o'tdingiz!\nXush kelibsiz.",
            "✅ Вы успешно зарегистрированы!\nДобро пожаловать.",
        ),
        reply_markup=main_markup_for_user(user),
    )
    await state.finish()

    # Send welcome / how-it-works message immediately after registration.
    _WELCOME_UZ = (
        "👋 <b>Xush kelibsiz, {name}!</b>\n\n"
        "Bu bot bilan kitob o'qishni odatga aylantiring:\n\n"
        "📚 <b>Hisobot</b> — har kuni o'qigan sahifalaringizni yuboring\n"
        "📊 <b>Reyting</b> — boshqa kitobxonlar bilan bellashing\n"
        "🏆 <b>Yutuqlar</b> — 30+ yutuq yutib oling va Kitobcha to'plang\n"
        "📈 <b>Darajalar</b> — 100 bet dan boshlang, har yangi marra — mukofot!\n"
        "👥 <b>Referral</b> — do'stingizni taklif qiling va bonus oling\n\n"
        "Boshlash uchun ⬇️ pastdagi <b>«Kitob hisoboti»</b> tugmasini bosing!"
    )
    _WELCOME_RU = (
        "👋 <b>Добро пожаловать, {name}!</b>\n\n"
        "С этим ботом сделайте чтение привычкой:\n\n"
        "📚 <b>Отчёт</b> — отправляйте страницы каждый день\n"
        "📊 <b>Рейтинг</b> — соревнуйтесь с другими читателями\n"
        "🏆 <b>Достижения</b> — 30+ наград и Kitobcha за прогресс\n"
        "📈 <b>Уровни</b> — начните с 100 страниц, каждый уровень — бонус!\n"
        "👥 <b>Рефералы</b> — пригласите друга и получите награду\n\n"
        "Нажмите ⬇️ кнопку <b>«Отчёт о книге»</b> чтобы начать!"
    )
    display_name = (user.full_name or "").split()[0] if user.full_name else "do'st"
    welcome_text = (
        (_WELCOME_RU if lang == "ru" else _WELCOME_UZ).format(name=display_name)
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    welcome_kb = InlineKeyboardMarkup(row_width=2)
    if lang == "ru":
        welcome_kb.add(
            InlineKeyboardButton("📚 Отчёт о книге", callback_data="cta_send_report"),
            InlineKeyboardButton("❓ Как работает?", callback_data="menu:how"),
        )
    else:
        welcome_kb.add(
            InlineKeyboardButton("📚 Kitob hisoboti", callback_data="cta_send_report"),
            InlineKeyboardButton("❓ Qanday ishlaydi?", callback_data="menu:how"),
        )
    try:
        await call.message.answer(welcome_text, parse_mode="HTML", reply_markup=welcome_kb)
    except Exception as e:
        print(f"welcome message failed for {call.from_user.id}: {e}")

    # Auto-send the full, detailed "how it works" guide to every new user.
    try:
        from tgbot.bot.handlers.users.menu_router import _show_how_it_works
        await _show_how_it_works(call.message, user)
    except Exception as e:
        print(f"how-it-works auto-send failed for {call.from_user.id}: {e}")

    # Notify admins (best-effort, doesn't block the user). Always Uzbek for admin.
    try:
        admins_raw = os.environ.get("ADMINS", "")
        admin_ids = [a.strip() for a in admins_raw.split(",") if a.strip()]
        if admin_ids:
            region_name = "—"
            if region_id:
                r = await sync_to_async(
                    Region.objects.filter(id=region_id).first
                )()
                if r:
                    region_name = r.name
            username_link = (
                f"@{call.from_user.username}" if call.from_user.username else "—"
            )
            gender_label = GENDER_LABELS_UZ.get(gender or "", "—")
            admin_text = (
                "🆕 <b>Yangi foydalanuvchi ro'yxatdan o'tdi</b>\n\n"
                f"👤 Ism: <b>{user.full_name}</b>\n"
                f"🆔 ID: <code>{user.telegram_id}</code>\n"
                f"📱 Username: {username_link}\n"
                f"🚻 Jins: {gender_label}\n"
                f"🗺 Hudud: {region_name}\n"
                f"🎂 Yosh: {AGE_LABELS[age_code]}\n"
                f"🌐 Til: {lang}"
            )
            for chat_id in admin_ids:
                try:
                    await bot.send_message(
                        chat_id=chat_id, text=admin_text, parse_mode="HTML"
                    )
                except Exception as e:
                    print(f"new-user notify failed for {chat_id}: {e}")
    except Exception as e:
        print(f"new-user notify wrapper failed: {e}")
