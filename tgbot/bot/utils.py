from asgiref.sync import sync_to_async
from django.conf import settings
from tgbot.models import TelegramProfile as User
from html import escape


def get_lang(language):
    lang_code = None
    languages = settings.LANGUAGES
    for lang in languages:
        if lang[1] == language:
            lang_code = lang[0]
    return lang_code


async def get_lang_code(state):
    data = await state.get_data()
    language = data.get("lang")
    return get_lang(language)


def get_user_sync(telegram_id):
    return User.objects.filter(telegram_id=telegram_id).first()


# Async wrapper so bot handlers (running on the asyncio event loop) don't
# block the loop on every DB lookup. DJANGO_ALLOW_ASYNC_UNSAFE=True in
# settings was silencing the warning while every Telegram update serialized
# behind this one query — the visible "slow / unresponsive" symptom.
aget_user = sync_to_async(get_user_sync, thread_sensitive=True)


# Backwards-compat alias: any caller that does `user = get_user(...)` from a
# sync context still works (admin actions, management commands, etc.). All
# async bot handlers MUST use `aget_user` instead.
get_user = get_user_sync


def get_admin_ids_sync():
    """Union of DB-flagged admins (TelegramProfile.is_admin=True) and the
    legacy ADMINS env var -- the env var used to be the ONLY admin broadcast
    list for contact_admin.py, silently excluding anyone granted admin only
    through the DB/admin panel (they'd never receive user messages, and
    couldn't reply even if forwarded one by another admin)."""
    import os
    db_ids = set(
        User.objects.filter(is_admin=True).values_list("telegram_id", flat=True)
    )
    env_raw = os.environ.get("ADMINS", "")
    env_ids = {int(a.strip()) for a in env_raw.split(",") if a.strip().lstrip("-").isdigit()}
    return db_ids | env_ids


aget_admin_ids = sync_to_async(get_admin_ids_sync, thread_sensitive=True)


def is_admin_id_sync(telegram_id):
    return int(telegram_id) in get_admin_ids_sync()


aget_is_admin = sync_to_async(is_admin_id_sync, thread_sensitive=True)


def get_all_users():
    users = User.objects.all()
    return users


def sanitize_text(text):
    return escape(text)


def get_chat_and_thread_id(user):
    default_chat_id = "-1002237773868"
    default_topic_id = None

    if user.group:
        chat_id = user.group.chat_id
        topic_id = user.group.topic_id
        return chat_id, topic_id
    return default_chat_id, default_topic_id
