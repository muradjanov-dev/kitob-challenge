from django.core.management.base import BaseCommand
from tgbot.bot.loader import dp
import tgbot.bot.middlewares, tgbot.bot.filters, tgbot.bot.handlers
from utils.bot import send_message
from django.conf import settings
from aiogram import executor


class Command(BaseCommand):
    help = 'Run bot in poolling'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Bot started"))
        for admin in settings.ADMINS:
            send_message(chat_id=admin, text="Bot ishga tushdi!")
        executor.start_polling(dp, skip_updates=True)
