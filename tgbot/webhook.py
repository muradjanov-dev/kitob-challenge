import json
from aiogram import types, Bot, Dispatcher
from django.http import HttpRequest, HttpResponse
from .bot.loader import bot, dp


async def proceed_update_from_body(body: bytes):
    upd = types.Update(**(json.loads(body)))
    Dispatcher.set_current(dp)
    Bot.set_current(bot)
    await dp.process_update(upd)


async def proceed_update(req: HttpRequest):
    await proceed_update_from_body(req.body)
