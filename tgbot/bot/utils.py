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


def get_user(telegram_id):
    user = User.objects.filter(telegram_id=telegram_id).first()
    return user


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
