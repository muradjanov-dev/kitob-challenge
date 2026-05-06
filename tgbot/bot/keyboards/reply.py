from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from tgbot.bot.loader import gettext as _
from tgbot.models import TelegramButton, Group, Region
from utils.bot import get_object_value


def confirm_markup():
    button = ReplyKeyboardMarkup(resize_keyboard=True)
    button.add(KeyboardButton(_("Tasdiqlash")),
               KeyboardButton(_("Bekor qilish")))
    return button


def yes_or_no_markup():
    button = ReplyKeyboardMarkup(resize_keyboard=True)
    button.add(KeyboardButton(_("Ha")),
               KeyboardButton(_("Yo'q")))
    return button


def group_markup(language="uz", gender=False):
    button_obj = Group.objects.filter(gender=gender, is_deleted=False)
    button = ReplyKeyboardMarkup(row_width=3, resize_keyboard=True)
    button.add(*(KeyboardButton(text=get_object_value(button, "title", language)) for button in button_obj if
                 get_object_value(button, "title", language) is not None))
    return button


def region_markup():
    regions = Region.objects.all()
    button = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    button.add(*[KeyboardButton(text=str(region.name)) for region in regions])
    return button


def main_markup(language="uz", is_admin=False):
    """Inline main menu. callback_data uses `menu:<action>` namespace."""
    if language == "ru":
        labels = {
            "report": "📚 Отчет о книге",
            "cabinet": "👤 Кабинет",
            "premium": "💎 Подписка",
            "achievements": "🏆 Мои достижения",
            "contact": "📞 Написать администратору",
            "lang": "🌐 Изменить язык",
            "admin": "👑 Админ панель",
        }
    else:
        labels = {
            "report": "📚 Kitob hisoboti",
            "cabinet": "👤 Kabinet",
            "premium": "💎 Premium obuna",
            "achievements": "🏆 Yutuqlarim",
            "contact": "📞 Admin bilan bog'lanish",
            "lang": "🌐 Tilni o'zgartirish",
            "admin": "👑 Admin panel",
        }

    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton(text=labels["report"], callback_data="menu:report"),
        InlineKeyboardButton(text=labels["cabinet"], callback_data="menu:cabinet"),
    )
    kb.row(
        InlineKeyboardButton(text=labels["premium"], callback_data="menu:premium"),
        InlineKeyboardButton(text=labels["achievements"], callback_data="menu:achievements"),
    )
    kb.row(InlineKeyboardButton(text=labels["contact"], callback_data="menu:contact"))
    kb.row(InlineKeyboardButton(text=labels["lang"], callback_data="menu:language"))
    if is_admin:
        kb.row(InlineKeyboardButton(text=labels["admin"], callback_data="menu:admin"))
    return kb


def main_markup_for_user(user):
    """Pick the right main menu for a TelegramProfile (handles language + admin)."""
    lang = (user.language if user else None) or "uz"
    is_admin = bool(user and getattr(user, "is_admin", False))
    return main_markup(language=lang, is_admin=is_admin)


main_menu_markup = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=_("🏠 Asosiy menyu")),
        ],
        [
            KeyboardButton(text=_("🔙 Orqaga"))
        ]
    ],
    resize_keyboard=True
)

phone_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=_("📞 Telefon raqamni yuborish"),
                           request_contact=True),
        ],
        [
            KeyboardButton(text=_("🔙 Orqaga"))
        ]
    ],
    resize_keyboard=True,
)


gender_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🤵/🧔"), KeyboardButton(text="👩‍💼/🧕"),
        ],
        [
            KeyboardButton(text=_("🔙 Orqaga"))
        ]
    ],
    resize_keyboard=True,
)

back_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=_("🔙 Orqaga"))
        ]
    ],
    resize_keyboard=True,
)

admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=_("✅ Ro'yhatdan o'tganlar")),
            KeyboardButton(text=_("❌ Ro'yhatdan o'tmaganlar"))
        ],
        [
            KeyboardButton(text=_("👨‍👩‍👦‍👦 Barcha foydalanuvchilar")),
            KeyboardButton(text=_("📊 Statistikani ko'rish"))
        ],
        [
            KeyboardButton(text="✉️ Habar yuborish"),
            KeyboardButton(text="📋 Eslatmalar"),
        ],
        [
            KeyboardButton(text="📊 So'rovnoma"),
            KeyboardButton(text="📊 So'rovnoma natijalari"),
        ],
        [KeyboardButton(text=_("🔙 Orqaga"))],
    ],
    resize_keyboard=True,
)
