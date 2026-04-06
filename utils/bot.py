import requests
from django.conf import settings
from django.db.models import Q

URL = f'https://api.telegram.org/bot{settings.API_TOKEN}/'


def set_webhook_request(bot_token):
    webhook_url = settings.WEBHOOK_URL
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook?url={webhook_url}/bot/handle_telegram_webhook/{bot_token}"
    response = requests.post(url)
    return response.json()


def get_info(bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    response = requests.post(url)
    return response.json().get("result").get("username"), response.json().get(
        "result"
    ).get("first_name")


def send_message(chat_id, text):
    url = URL + 'sendMessage'
    params = {
        'chat_id': chat_id,
        'text': text
    }
    response = requests.post(url, params=params)
    if response.status_code == 200:
        print(f"Message sent to chat_id {chat_id}")
    else:
        print(f"Failed to send message to chat_id {chat_id}: {response.text}")
    return response


def get_object_value(object, field, language):
    if not language:
        language = 'uz'
   
    if hasattr(object, field):
        if hasattr(object, f"{field}_{language}"):
            return getattr(object, f"{field}_{language}")
        else:
            return getattr(object, field)


def get_model_queryset(model, text):
    return model.objects.filter(
        Q(title__iexact=text) | Q(title_uz__iexact=text) | Q(title_ru__iexact=text) | Q(title_en__iexact=text))


def parse_telegram_message(message):
    if message is not None:
        message = message.replace("<p>", "")
        if message.endswith("</p>"):
            message = message[:-4]
        for i in ["</p>", "<br>", "<br/>", "<br />"]:
            message = message.replace(i, "\n")
        message = message.replace("&nbsp;", " ")
    return message
