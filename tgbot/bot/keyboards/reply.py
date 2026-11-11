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
    """Inline main menu, callback_data `menu:<action>` (owner, 2026-11-11:
    minimal, and clearly thought through). One main action on top -- the
    day's report, a tall full-width button -- then everything else in pairs
    by what the reader wants: money and self (Hamyon, Kabinet), standing
    and the currency they earn (Reyting, Kitobcha), play (Kitob Quiz,
    Market), and the quiet corner (Sozlamalar, Yordam -- "how it works" and
    "write to the admin" live inside it)."""
    from tgbot.services import wallet as _wallet
    ru = language == "ru"
    labels = {
        "report_big": "\n📖  Отчёт за сегодня\n" if ru else "\n📖  Bugungi hisobot\n",
        "wallet": ("👛 Кошелёк" if ru else "👛 Hamyon") if _wallet.is_live_launch()
        else ("💎 Подписка" if ru else "💎 Premium obuna"),
        "cabinet": "👤 Кабинет" if ru else "👤 Kabinet",
        "reyting": "🏆 Рейтинг" if ru else "🏆 Reyting",
        "kitobcha": "🪙 Kitobcha",
        "quiz": "📝 Книжный квиз" if ru else "📝 Kitob Quiz",
        "market": "🎪 Market",
        "settings": "⚙️ Настройки" if ru else "⚙️ Sozlamalar",
        "help": "💬 Помощь" if ru else "💬 Yordam",
        "admin": "👑 Админ панель" if ru else "👑 Admin panel",
    }

    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(InlineKeyboardButton(text=labels["report_big"], callback_data="menu:report"))
    # Dedicated, prominent entry while a Referral BOOM is live.
    active_boom = _active_boom_for_menu()
    if active_boom:
        kb.row(InlineKeyboardButton(text=f"🌟 {active_boom.title}", callback_data=f"join_boom:{active_boom.id}"))
    # The shop lives on the native chat menu button and inside the site.
    kb.row(InlineKeyboardButton(text=labels["wallet"], callback_data="menu:premium"),
           InlineKeyboardButton(text=labels["cabinet"], callback_data="menu:cabinet"))
    kb.row(InlineKeyboardButton(text=labels["reyting"], callback_data="menu:reyting"),
           InlineKeyboardButton(text=labels["kitobcha"], callback_data="kuse:menu"))
    kb.row(InlineKeyboardButton(text=labels["quiz"], callback_data="menu:quiz"),
           InlineKeyboardButton(text=labels["market"], callback_data="menu:market"))
    kb.row(InlineKeyboardButton(text=labels["settings"], callback_data="menu:settings"),
           InlineKeyboardButton(text=labels["help"], callback_data="menu:help"))
    if is_admin:
        kb.row(InlineKeyboardButton(text=labels["admin"], callback_data="menu:admin"))
    return kb


def help_markup(language="uz"):
    """💬 Yordam: the two things a reader looks for when stuck."""
    ru = language == "ru"
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("❓ Как это работает?" if ru else "❓ Qanday ishlaydi?", callback_data="menu:how"))
    kb.add(InlineKeyboardButton("📞 Написать администратору" if ru else "📞 Admin bilan bog'lanish",
                                callback_data="menu:contact"))
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
    base_domain = str(WEB_DOMAIN).rstrip('/')
    if not base_domain.startswith('http'):
        base_domain = f"https://{base_domain}"

    # "✅ Bajardim!" only while a reading challenge runs (they are on hold
    # since 2026-11-11): compute_bajardim_label gives "" when none does.
    first = [KeyboardButton(text=report_text)]
    if bajardim_label != "":
        first.append(KeyboardButton(text=done_text))
    rows = [
        first,
        [KeyboardButton(text=site_text, web_app=WebAppInfo(url=f"{base_domain}/"))],
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

# ── COMPACT 5-HUB MODULAR ADMIN PANEL ──
admin_keyboard = InlineKeyboardMarkup(row_width=2)
admin_keyboard.row(
    InlineKeyboardButton(text="👥 Foydalanuvchilar Markazi", callback_data="admin:hub_users"),
    InlineKeyboardButton(text="🎮 O'yinlar & Quizlar", callback_data="admin:hub_games"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="📢 Xabarnoma & Eslatmalar", callback_data="admin:hub_broadcast"),
    InlineKeyboardButton(text="📚 Do'kon & Kutubxona", callback_data="admin:hub_content"),
)
admin_keyboard.row(
    InlineKeyboardButton(text="📊 Statistika & Analitika", callback_data="admin:hub_analytics"),
)

# 1. Hub: Foydalanuvchilar
admin_users_hub_kb = InlineKeyboardMarkup(row_width=2)
admin_users_hub_kb.row(
    InlineKeyboardButton(text="👨‍👩‍👦‍👦 Foydalanuvchilar ro'yxati", callback_data="admin:all_users"),
    InlineKeyboardButton(text="🔍 Foydalanuvchi qidirish", callback_data="admin:user_search"),
)
admin_users_hub_kb.row(
    InlineKeyboardButton(text="🪙 Kitobcha reytingi", callback_data="admin:kitobcha_top"),
    InlineKeyboardButton(text="🎁 24h Premium (hammaga)", callback_data="admin:founder_gift"),
)
admin_users_hub_kb.row(
    InlineKeyboardButton(text="🔙 Asosiy Admin menyu", callback_data="admin:main"),
)

# 2. Hub: O'yinlar & Quizlar
admin_games_hub_kb = InlineKeyboardMarkup(row_width=2)
admin_games_hub_kb.row(
    InlineKeyboardButton(text="🎮 58 ta O'yinni boshqarish", callback_data="admin:games_menu"),
    InlineKeyboardButton(text="🧪 O'yinlarni sinash", callback_data="admin:games_test_menu"),
)
admin_games_hub_kb.row(
    InlineKeyboardButton(text="📝 Quizlar boshqaruvi", callback_data="admin:quizzes"),
    InlineKeyboardButton(text="🧩 Viktorina yuborish", callback_data="admin:book_quiz"),
)
admin_games_hub_kb.row(
    InlineKeyboardButton(text="🔙 Asosiy Admin menyu", callback_data="admin:main"),
)

# 3. Hub: Xabarnoma & Eslatmalar
admin_broadcast_hub_kb = InlineKeyboardMarkup(row_width=2)
admin_broadcast_hub_kb.row(
    InlineKeyboardButton(text="✉️ Habar yuborish", callback_data="admin:notify"),
    InlineKeyboardButton(text="📋 Eslatmalar", callback_data="admin:reminders"),
)
admin_broadcast_hub_kb.row(
    InlineKeyboardButton(text="📊 Yangi so'rovnoma", callback_data="admin:poll_new"),
    InlineKeyboardButton(text="📊 So'rovnoma natijalari", callback_data="admin:poll_results"),
)
admin_broadcast_hub_kb.row(
    InlineKeyboardButton(text="💡 Loyiha so'rovnomasi (500 🪙)", callback_data="admin:project_survey"),
)
admin_broadcast_hub_kb.row(
    InlineKeyboardButton(text="🔙 Asosiy Admin menyu", callback_data="admin:main"),
)

# 4. Hub: Do'kon & Kutubxona
admin_content_hub_kb = InlineKeyboardMarkup(row_width=2)
admin_content_hub_kb.row(
    InlineKeyboardButton(text="🛒 Do'kon boshqaruvi", callback_data="admin:shop"),
    InlineKeyboardButton(text="📚 Kutubxona boshqaruvi", callback_data="admin:library"),
)
admin_content_hub_kb.row(
    InlineKeyboardButton(text="🎬 Xush kelibsiz video", callback_data="admin:welcome_video"),
)
admin_content_hub_kb.row(
    InlineKeyboardButton(text="🔙 Asosiy Admin menyu", callback_data="admin:main"),
)

# 5. Hub: Statistika & Analitika
admin_analytics_hub_kb = InlineKeyboardMarkup(row_width=2)
admin_analytics_hub_kb.row(
    InlineKeyboardButton(text="📈 Bot statistikasi", callback_data="admin:stats"),
    InlineKeyboardButton(text="🖱 Sayt statistikasi", callback_data="admin:site_stats:7d"),
)
admin_analytics_hub_kb.row(
    InlineKeyboardButton(text="🏆 Top kitobxonlar (broadcast)", callback_data="admin:top_readers"),
    InlineKeyboardButton(text="🏅 Kitobxon nominatsiyalari", callback_data="admin:reader_titles"),
)
admin_analytics_hub_kb.row(
    InlineKeyboardButton(text="🚀 Musobaqa (BOOM) boshlash", callback_data="admin:boom"),
    InlineKeyboardButton(text="📊 BOOM statistikasi", callback_data="admin:boom_stats"),
)
admin_analytics_hub_kb.row(
    InlineKeyboardButton(text="🔙 Asosiy Admin menyu", callback_data="admin:main"),
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
