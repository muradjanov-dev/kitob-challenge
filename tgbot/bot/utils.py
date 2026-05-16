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
