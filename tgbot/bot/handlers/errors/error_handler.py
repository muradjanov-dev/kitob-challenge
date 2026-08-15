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


if hasattr(dp, "errors_handler"):
    errors_handler = dp.errors_handler()(errors_handler)
