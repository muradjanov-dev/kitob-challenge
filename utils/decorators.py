import json
from django.utils.translation import activate, gettext_lazy, get_language
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import CallbackContext

from django.core.cache import cache

from apps.bot.buttons import default
from apps.bot import models
from apps.bot.state import state

from utils.send_message import send_telegram_message


def _(text):
    return str(gettext_lazy(text))


def get_member(func):
    def wrap(update: Update, context: CallbackContext, *args, **kwargs):
        try:
            user_id = update.effective_user.id
        except AttributeError:
            user_id = update.poll_answer.user.id
        except AttributeError:
            user_id = update.callback_query.message.chat_id
        bot = models.TelegramBot.objects.get(bot_username=context.bot.username)
        user, created = models.TelegramProfile.objects.get_or_create(
            telegram_id=user_id,
            bot=bot,
            defaults={
                'first_name': update.effective_user.first_name,
                'last_name': update.effective_user.last_name,
                'username': update.effective_user.username,
            }
        )

        if not created:
            user.first_name = update.effective_user.first_name
            user.last_name = update.effective_user.last_name
            user.username = update.effective_user.username
            user._user_data = context.user_data
        else:
            user.language = None

        user.save()

        activate(user.language)
        if update.message and user.is_olimpic:
            context.bot.send_message(
                user.telegram_id,
                _("Siz Olimpiadada siz!!!")
            )
            return
        return func(update, context, user, *args, **kwargs)

    return wrap


def is_subscribe(func):
    def wrap(update: Update, context: CallbackContext, user, *args, **kwargs):
        if cache.get(f'user_is_subscribe_{user.telegram_id}', None) is not None:
            return func(update, context, user, *args, **kwargs)
        user_id = update.effective_user.id
        final_status = True

        language = get_language().split("-")[0]

        try:
            update = update
        except AttributeError:
            update = update.callback_query

        keyboards = []
        if cache.get(f"bot_channels_{context.bot.username}", None) is None:
            channels = models.RequiredGroup.objects.filter(bot__bot_username=context.bot.username)
            cache.set(f"bot_channels_{context.bot.username}", channels, 60 * 5)
        else:
            channels = cache.get(f"bot_channels_{context.bot.username}")

        for channel in channels:
            status = update.message.bot.get_chat_member(channel.chat_id, user_id)['status'] in [
                'member', 'administrator', 'creator', 'owner']
            final_status *= status
            get_channel = context.bot.get_chat(channel.chat_id)
            keyboards.append(
                [
                    InlineKeyboardButton(
                        text=getattr(channel, f"title_{language}"),
                        url=f"https://t.me/{get_channel.username}",
                    )
                ]
            )
        keyboards.append(
            [
                InlineKeyboardButton(
                    _("Tekshirish"), callback_data="check_sub"
                )
            ]
        )

        if not final_status:
            update.message.reply_text(
                _("Obuna bo'ling"), reply_markup=InlineKeyboardMarkup(keyboards), parse_mode="HTML"
            )
            return

        cache.set(f'user_is_subscribe_{user.telegram_id}', True, 60 * 60 * 24 * 2)

        return func(update, context, user, *args, **kwargs)

    return wrap
