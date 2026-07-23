from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.types.chat_member import ChatMemberStatus
from django.conf import settings
from tgbot.bot.loader import bot
from tgbot.models import RequiredGroup, TelegramProfile, Region
from tgbot.bot.loader import gettext as _


def gender_inline_kb(language: str = "uz") -> InlineKeyboardMarkup:
    if language == "ru":
        male, female = "🤵 Мужчины", "👩 Девушки и Женщины"
    else:
        male, female = "🤵 Erkaklar", "👩 Qizlar va Ayollar"
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton(male, callback_data="reg_gender:male"),
        InlineKeyboardButton(female, callback_data="reg_gender:female"),
    )


def region_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    for r in Region.objects.all().order_by("name"):
        kb.add(InlineKeyboardButton(r.name, callback_data=f"reg_region:{r.id}"))
    return kb


def age_inline_kb() -> InlineKeyboardMarkup:
    options = [
        ("u18", "🧒 < 18"),
        ("18_25", "🧑 18 — 25"),
        ("26_35", "🧔 26 — 35"),
        ("36p", "👴 36+"),
    ]
    kb = InlineKeyboardMarkup(row_width=2)
    for code, label in options:
        kb.insert(InlineKeyboardButton(label, callback_data=f"reg_age:{code}"))
    return kb


languages_markup = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=lang[1]),
        ] for lang in settings.LANGUAGES
    ],
    resize_keyboard=True,
)


async def get_check_button(chat_ids: list = []):
    channels = RequiredGroup.objects.filter(id__in=chat_ids)

    buttons = []
    # We loop through DB objects directly, no API calls needed if invite_link is set
    for channel in channels:
        url = channel.invite_link
        title = channel.title

        # Fallback if invite_link is missing (though we strongly recommend setting it)
        if not url or not title:
            try:
                chat = await bot.get_chat(channel.chat_id)
                url = await chat.export_invite_link()
                title = chat.title

                # Verify we are in async context before saving?
                # Actually, better to avoid side-effects here or save asynchronously if possible.
                # For now, just use the fetched data.
            except Exception as error:
                print(f"Error fetching chat {channel.chat_id}: {error}")
                continue

        buttons.append([InlineKeyboardButton(
            text=title or "Channel", url=url)])

    if buttons:
        buttons.append([InlineKeyboardButton(
            text=_("✅ Check"), callback_data="check_subs")])
        check_button = InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
        return check_button
    return None


async def get_required_chats_markup(required_chats, user_id):
    keyboard = []
    for chat in required_chats:
        ch = await bot.get_chat(chat.chat_id)
        member = await bot.get_chat_member(ch.id, user_id)
        if member.status not in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.CREATOR
        ]:
            keyboard.append([
                InlineKeyboardButton(text=chat.title, url=ch.invite_link)
            ])
    if not keyboard:
        return None
    keyboard.append([
        InlineKeyboardButton(
            text=_("Obuna bo'ldim/Qo'shildim"), callback_data="subscribed")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


send_receipt_button = InlineKeyboardMarkup().add(
    InlineKeyboardButton(_("🧾 To'lov chekini yuborish"),
                         callback_data="send_receipt")
)


async def make_send_receipt_to_group_button(price: int, telegram_id: str, message_id: int, days: int = 30):
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton(
            _("✅ Ruxsat berish"), callback_data=f"accept:{price}:{telegram_id}:{message_id}:{days}"),
        InlineKeyboardButton(
            _("❗️ Rad etish"), callback_data=f"rejection:{price}:{telegram_id}:{message_id}"),
    )


send_message_type = InlineKeyboardMarkup(row_width=2).add(
    InlineKeyboardButton(_("🛠️ Texnik muammo"), callback_data="technical"),
    InlineKeyboardButton(_("📝 Boshqa"), callback_data="other"),
    InlineKeyboardButton(_("❌ Bekor qilish"), callback_data="cancel")
)


async def send_answer_to_question(user_id):
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton(_("✅  Javob yuborish"),
                             callback_data=f"send_answer:{user_id}"),
    )

yes_no_markup = InlineKeyboardMarkup(row_width=2).add(
    InlineKeyboardButton(_("✅ Ha, tasdiqlayman"), callback_data="yes"),
    InlineKeyboardButton(_("❌ Yo'q"), callback_data="no")
)
