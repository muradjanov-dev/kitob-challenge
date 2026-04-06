from aiogram import Dispatcher

from tgbot.bot.loader import dp
# from .is_admin import AdminFilter
from .private_chat import IsPrivate


if __name__ == "filters":
    #dp.filters_factory.bind(is_admin)
    dp.filters_factory.bind(IsPrivate)
    pass
