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
    """Inline main menu. callback_data uses `menu:<action>` namespace.
    The 📚 Kitob hisoboti button is rendered as a tall full-width hero
    (visually ≈ 4 ordinary buttons) by stacking decorative lines + a
    blank padding row above and below the title."""
    if language == "ru":
        labels = {
            "report_big": "📚\n\n📚 Отчет о книге 📚\n\n📚",
            "cabinet": "👤 Кабинет",
            "premium": "💎 Подписка",
            "shop": "🛒 Магазин Kitob Challenge",
            "reyting": "📊 Рейтинг",
            "contact": "📞 Написать администратору",
            "settings": "⚙️ Настройки",
            "quiz": "📝 Книжный Квиз",
            "admin": "👑 Админ панель",
        }
    else:
        labels = {
            "report_big": "📚\n\n📚 Kitob hisoboti 📚\n\n📚",
            "cabinet": "👤 Kabinet",
            "premium": "💎 Premium obuna",
            "shop": "🛒 Kitob Challenge Shop",
            "reyting": "📊 Reyting",
            "contact": "📞 Admin bilan bog'lanish",
            "settings": "⚙️ Sozlamalar",
            "quiz": "📝 Kitob Quiz",
            "admin": "👑 Admin panel",
        }

    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(InlineKeyboardButton(text=labels["report_big"], callback_data="menu:report"))
    # Yutuqlarim moved inside Kabinet — its old slot now hosts the Shop entry,
    # which is currently a 'Tez kunda' placeholder.
    kb.row(
        InlineKeyboardButton(text=labels["cabinet"], callback_data="menu:cabinet"),
        InlineKeyboardButton(text=labels["shop"], callback_data="menu:shop"),
    )
    kb.row(
        InlineKeyboardButton(text=labels["reyting"], callback_data="menu:reyting"),
        InlineKeyboardButton(text=labels["premium"], callback_data="menu:premium"),
    )
    kb.row(InlineKeyboardButton(text=labels["quiz"], callback_data="menu:quiz"))
    kb.row(
        InlineKeyboardButton(text=labels["settings"], callback_data="menu:settings"),
        InlineKeyboardButton(text=labels["contact"], callback_data="menu:contact"),
    )
    if is_admin:
        kb.row(InlineKeyboardButton(text=labels["admin"], callback_data="menu:admin"))
    return kb


def report_reply_keyboard(language="uz", bajardim_label=None):
    """Persistent bottom reply keyboard. Two rows of two so the 4 highest-
    frequency actions are always reachable in one tap — never 'lost in flow'.

    Row 1: report submission (the hero action) + daily challenge done mark.
    Row 2: cabinet shortcut + home menu.

    `bajardim_label` lets the caller pass a dynamic label that embeds the
    user's challenge progress and condition (e.g. '✅ Bajardim! (1/3) · 50+
    bet'). The text handler matches on the '✅ Bajardim!' / '✅ Выполнено!'
    prefix so any suffix still routes correctly.
    """
    if language == "ru":
        report_text = "📚 Отчет о книге"
        home_text = "🏠 Главное меню"
        cabinet_text = "👤 Кабинет"
        done_text = bajardim_label or "✅ Выполнено!"
    else:
        report_text = "📚 Kitob hisoboti"
        home_text = "🏠 Bosh menyu"
        cabinet_text = "👤 Kabinet"
        done_text = bajardim_label or "✅ Bajardim!"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=report_text), KeyboardButton(text=done_text)],
            [KeyboardButton(text=cabinet_text), KeyboardButton(text=home_text)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


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

admin_keyboard = InlineKeyboardMarkup(row_width=2)
admin_keyboard.row(
    InlineKeyboardButton(text="👨‍👩‍👦‍👦 Barcha foydalanuvchilar", callback_data="admin:all_users"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="📊 Statistikani ko'rish", callback_data="admin:stats"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="✉️ Habar yuborish", callback_data="admin:notify"),
    InlineKeyboardButton(text="📋 Eslatmalar", callback_data="admin:reminders"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="📊 So'rovnoma", callback_data="admin:poll_new"),
    InlineKeyboardButton(text="📊 So'rovnoma natijalari", callback_data="admin:poll_results"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="🏆 Top kitobxonlar (broadcast)", callback_data="admin:top_readers"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="📝 Quizlar", callback_data="admin:quizzes"),
)

# The deprecated reply-keyboard version (kept for any legacy callers).
_admin_reply_keyboard_legacy = ReplyKeyboardMarkup(
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
