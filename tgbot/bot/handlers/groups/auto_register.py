from aiogram import types
from aiogram.types import ChatType
from asgiref.sync import sync_to_async

from tgbot.bot.loader import dp
from tgbot.models import BroadcastGroup

ADMIN_STATUSES = {"administrator", "creator"}


@sync_to_async
def _set_active(chat_id: str, title: str, active: bool):
    BroadcastGroup.objects.update_or_create(
        chat_id=chat_id, defaults={"title": title, "is_active": active},
    )


@dp.my_chat_member_handler()
async def on_bot_membership_change(update: types.ChatMemberUpdated):
    """Auto-registers/deregisters this chat as a broadcast target purely from
    the bot's own admin status — no manual chat_id/env-var wiring needed to
    get quiz/games/leaderboard/announcements flowing into a new group. See
    BroadcastGroup and tasks.py's _category_targets()."""
    if update.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    is_admin_now = update.new_chat_member.status in ADMIN_STATUSES
    await _set_active(str(update.chat.id), update.chat.title or "", is_admin_now)
