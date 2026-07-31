from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)
from tgbot.bot.loader import gettext as _
from tgbot.models import TelegramButton, Group, Region
from utils.bot import get_object_value
from src.settings import WEB_DOMAIN


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


def _active_boom_for_menu():
    """The live ReferralBoom (if any), cached briefly -- main_markup() renders
    on every /start and menu tap, far more often than a boom's state changes,
    so this avoids a query per render without risking a stale button for long
    after a boom starts/ends."""
    from django.core.cache import cache
    from tgbot.models import ReferralBoom

    cached = cache.get("active_boom_for_menu", "unset")
    if cached != "unset":
        return cached
    boom = ReferralBoom.objects.filter(is_active=True).order_by("-created_at").first()
    cache.set("active_boom_for_menu", boom, 30)
    return boom


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
            "reyting": "📊 Рейтинг",
            "contact": "📞 Написать администратору",
            "settings": "⚙️ Настройки",
            "quiz": "📝 Книжный Квиз",
            "admin": "👑 Админ панель",
            "how": "❓ Как это работает?",
        }
    else:
        labels = {
            "report_big": "📚\n\n📚 Kitob hisoboti 📚\n\n📚",
            "cabinet": "👤 Kabinet",
            "premium": "💎 Premium obuna",
            "reyting": "📊 Reyting",
            "contact": "📞 Admin bilan bog'lanish",
            "settings": "⚙️ Sozlamalar",
            "quiz": "📝 Kitob Quiz",
            "market": "🎪 Market",
            "admin": "👑 Admin panel",
            "how": "❓ Qanday ishlaydi?",
        }

    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(InlineKeyboardButton(text=labels["report_big"], callback_data="menu:report"))
    # Dedicated, prominent entry while a Referral BOOM is live -- separate
    # from the always-there Kabinet -> Referal entry so a running competition
    # doesn't get buried a menu deep.
    active_boom = _active_boom_for_menu()
    if active_boom:
        kb.row(InlineKeyboardButton(
            text=f"🌟 {active_boom.title}",
            callback_data=f"join_boom:{active_boom.id}",
        ))
    kb.row(InlineKeyboardButton(text=labels["how"], callback_data="menu:how"))
    # Shop entry lives on the native chat menu button now (see
    # set_shop_menu_button management command), so it's removed from the
    # inline menu entirely.
    kb.row(
        InlineKeyboardButton(text=labels["cabinet"], callback_data="menu:cabinet"),
        InlineKeyboardButton(text=labels["reyting"], callback_data="menu:reyting"),
    )
    kb.row(
        InlineKeyboardButton(text=labels["premium"], callback_data="menu:premium"),
        InlineKeyboardButton(text=labels["quiz"], callback_data="menu:quiz"),
    )
    kb.row(InlineKeyboardButton(text=labels.get("market", "🎪 Market"), callback_data="menu:market"))
    kb.row(
        InlineKeyboardButton(text=labels["settings"], callback_data="menu:settings"),
        InlineKeyboardButton(text=labels["contact"], callback_data="menu:contact"),
    )
    if is_admin:
        kb.row(InlineKeyboardButton(text=labels["admin"], callback_data="menu:admin"))
    return kb


def report_reply_keyboard(language="uz", bajardim_label=None, is_admin=False):
    # is_admin kept for backwards compat with existing call sites; the shop
    # is now public so the Do'kon button always renders.
    if language == "ru":
        report_text = "📚 Отчет о книге"
        home_text = "🏠 Главное меню"
        done_text = bajardim_label or "✅ Выполнено!"
        site_text = "🌌 Параллельный мир"
    else:
        report_text = "📚 Kitob hisoboti"
        home_text = "🏠 Bosh menyu"
        done_text = bajardim_label or "✅ Bajardim!"
        site_text = "🌌 Parallel olam"

    # Single persistent site entry above the input on every client. The shop
    # (Do'kon) now lives INSIDE the site, reachable from its nav — so one
    # WebApp button opens the whole experience. Reply-keyboard WebApp buttons
    # always render the label (unlike the chat menu button which collapses to
    # an icon on mobile).
    rows = [
        [KeyboardButton(text=report_text), KeyboardButton(text=done_text)],
        [KeyboardButton(text=site_text, web_app=WebAppInfo(url=f"{WEB_DOMAIN}/"))],
    ]
    # Persistent entry to this user's own boom stats + share link, while a
    # Referral BOOM is live -- same active-boom cache main_markup() uses.
    active_boom = _active_boom_for_menu()
    if active_boom:
        rows.append([KeyboardButton(text=f"🌟 {active_boom.title}")])
    rows.append([KeyboardButton(text=home_text)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
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
    InlineKeyboardButton(text="👨‍👩‍👦‍👦 Foydalanuvchilar ro'yxati", callback_data="admin:all_users"),
    InlineKeyboardButton(text="🔍 Foydalanuvchi qidirish", callback_data="admin:user_search"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="📊 Statistikani ko'rish", callback_data="admin:stats"),
    InlineKeyboardButton(text="✉️ Habar yuborish", callback_data="admin:notify"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="📋 Eslatmalar", callback_data="admin:reminders"),
    InlineKeyboardButton(text="📊 So'rovnoma", callback_data="admin:poll_new"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="📊 So'rovnoma natijalari", callback_data="admin:poll_results"),
    InlineKeyboardButton(text="📊 Loyiha so'rovnomasi (500 🪙)", callback_data="admin:project_survey"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="🏆 Top kitobxonlar (broadcast)", callback_data="admin:top_readers"),
    InlineKeyboardButton(text="🏅 Kitobxon nominatsiyalari", callback_data="admin:reader_titles"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="🎁 Sovg'a: 24h Premium (hammaga)", callback_data="admin:founder_gift"),
    InlineKeyboardButton(text="🪙 Kitobcha reytingi", callback_data="admin:kitobcha_top"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="📝 Quizlar", callback_data="admin:quizzes"),
    InlineKeyboardButton(text="🧩 Viktorina yuborish", callback_data="admin:book_quiz"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="🎮 Barcha o'yinlar (14 ta)", callback_data="admin:games_menu"),
    InlineKeyboardButton(text="🧪 O'yinlarni jimgina sinash", callback_data="admin:games_test_menu"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="🛒 Do'kon boshqaruvi", callback_data="admin:shop"),
    InlineKeyboardButton(text="📚 Kutubxona boshqaruvi", callback_data="admin:library"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="🖱 Sayt Statistikasi", callback_data="admin:site_stats:7d"),
    InlineKeyboardButton(text="📊 Yaxshilik ulashuvchi statistikasi", callback_data="admin:boom_stats"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="🚀 Musobaqa boshlash", callback_data="admin:boom"),
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
