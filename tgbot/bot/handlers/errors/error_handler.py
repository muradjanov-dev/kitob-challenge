import logging
try:
    from aiogram.utils.exceptions import (Unauthorized, InvalidQueryID, TelegramAPIError,
                                          CantDemoteChatCreator, MessageNotModified, MessageToDeleteNotFound,
                                          MessageTextIsEmpty, RetryAfter,
                                          CantParseEntities, MessageCantBeDeleted)
except (ImportError, ModuleNotFoundError):
    class TelegramAPIError(Exception): pass
    class Unauthorized(TelegramAPIError): pass
    class InvalidQueryID(TelegramAPIError): pass
    class CantDemoteChatCreator(TelegramAPIError): pass
    class MessageNotModified(TelegramAPIError): pass
    class MessageToDeleteNotFound(TelegramAPIError): pass
    class MessageTextIsEmpty(TelegramAPIError): pass
    class RetryAfter(TelegramAPIError): pass
    class CantParseEntities(TelegramAPIError): pass
    class MessageCantBeDeleted(TelegramAPIError): pass


from tgbot.bot.loader import dp


async def errors_handler(update, exception):
    """
    Exceptions handler. Catches all exceptions within task factory tasks.
    :param dispatcher:
    :param update:
    :param exception:
    :return: stdout logging
    """

    if isinstance(exception, CantDemoteChatCreator):
        logging.exception("Can't demote chat creator")
        return True

    if isinstance(exception, MessageNotModified):
        logging.exception('Message is not modified')
        return True
    if isinstance(exception, MessageCantBeDeleted):
        logging.exception('Message cant be deleted')
        return True

    if isinstance(exception, MessageToDeleteNotFound):
        logging.exception('Message to delete not found')
        return True

    if isinstance(exception, MessageTextIsEmpty):
        logging.exception('MessageTextIsEmpty')
        return True

    if isinstance(exception, Unauthorized):
        logging.exception(f'Unauthorized: {exception}')
        return True

    if isinstance(exception, InvalidQueryID):
        logging.exception(f'InvalidQueryID: {exception} \nUpdate: {update}')
        return True

    if isinstance(exception, TelegramAPIError):
        logging.exception(f'TelegramAPIError: {exception} \nUpdate: {update}')
        return True
    if isinstance(exception, RetryAfter):
        logging.exception(f'RetryAfter: {exception} \nUpdate: {update}')
        return True
    if isinstance(exception, CantParseEntities):
        logging.exception(f'CantParseEntities: {exception} \nUpdate: {update}')
        return True
    
    logging.exception(f'Update: {update} \n{exception}')
    await _tell_reader_and_admins(update, exception)
    return True


async def _tell_reader_and_admins(update, exception):
    """A crash used to leave the reader with a spinning button or silence.
    Now they get a plain apology and a way back, and the admins get the error
    (each kind at most once in 10 minutes)."""
    from tgbot.bot.loader import bot
    text = ("⚠️ Kechirasiz, kutilmagan xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring "
            "yoki /menu orqali bosh menyuga qayting.")
    try:
        call = getattr(update, "callback_query", None)
        msg = getattr(update, "message", None)
        if call:
            try:
                await call.answer(text, show_alert=True)
            except Exception:
                await bot.send_message(call.from_user.id, text)
        elif msg and msg.chat.type == "private":
            await msg.answer(text)
    except Exception:
        pass
    try:
        from django.core.cache import cache
        kind = f"{type(exception).__name__}:{str(exception)[:60]}"
        if not cache.add(f"err_notified:{hash(kind)}", 1, 600):
            return
        from asgiref.sync import sync_to_async
        from tgbot.models import TelegramProfile
        admins = await sync_to_async(lambda: list(
            TelegramProfile.objects.filter(is_admin=True).values_list("telegram_id", flat=True)))()
        where = ""
        if getattr(update, "callback_query", None):
            where = f"tugma: {update.callback_query.data}"
        elif getattr(update, "message", None):
            where = f"xabar: {(update.message.text or update.message.content_type or '')[:60]}"
        import html
        note = (f"🐞 <b>Botda xatolik</b>\n{html.escape(where)}\n"
                f"<code>{html.escape(type(exception).__name__ + ': ' + str(exception)[:300])}</code>")
        for a in admins:
            try:
                await bot.send_message(a, note, parse_mode="HTML")
            except Exception:
                pass
    except Exception:
        pass


if hasattr(dp, "errors_handler"):
    errors_handler = dp.errors_handler()(errors_handler)
