from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
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


def main_markup(language="uz"):
    if language == "uz":
        content = "📚 Kitob hisoboti"
        premium = "💎 Premium obuna"
        lang = "🌐 Tilni o'zgartirish"
        message_to_admin = "📞 Adminga bilan bog'lanish"
    elif language == "ru":
        content = "📚 Отчет о книге"
        premium = "💎 Подписка"
        lang = "🌐 Изменить язык"
        message_to_admin = "📞 Напишите администратору"
    else:
        content = "📚 Kitob hisoboti"
        premium = "💎 Premium obuna"
        lang = "🌐 Tilni o'zgartirish"
        message_to_admin = "📞 Adminga bilan bog'lanish"

    button = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    button.add(
        KeyboardButton(text="🏆 Konkurs(Yanvar)"),
        KeyboardButton(text=content),
        KeyboardButton(text="👤 Kabinet"),
        KeyboardButton(text=premium),
        KeyboardButton(text=message_to_admin),
    )
    button.row(
        KeyboardButton(text=lang)
    )
    return button


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
        [KeyboardButton(text="✉️ Habar yuborish"),
         KeyboardButton(text="📥 Viktorina yuklash")]
    ],
    resize_keyboard=True,
)
