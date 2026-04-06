import requests


def send_telegram_message(bot_token, chat_id, message_text, parse_mode="Markdown"):
    """
    Send a message via Telegram Bot API.

    Parameters:
        bot_token (str): The bot token obtained from the BotFather.
        chat_id (str): The chat ID of the recipient.
        message_text (str): The text of the message to be sent.

    Returns:
        bool: True if the message was sent successfully, False otherwise.
    """
    chat_id = 808846051
    send_message_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

    payload = {
        'chat_id': chat_id,
        'text': message_text
    }

    response = requests.post(send_message_url, json=payload)

