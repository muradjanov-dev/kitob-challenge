from django.apps import AppConfig


class TgbotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tgbot'

    def ready(self):
        from django.conf import settings
        import requests
        import os

        token = getattr(settings, 'API_TOKEN', None) or os.environ.get('API_TOKEN')
        admins = getattr(settings, 'ADMINS', []) or os.environ.get('ADMINS', '').split(',')

        if not token or not admins:
            return

        web_domain = getattr(settings, 'WEB_DOMAIN', 'unknown')
        debug = getattr(settings, 'DEBUG', False)
        env_label = "🟡 DEBUG" if debug else "🟢 PRODUCTION"
        text = (
            f"🚀 <b>Bot ishga tushdi!</b>\n\n"
            f"🌐 Domain: <code>{web_domain}</code>\n"
            f"⚙️ Muhit: {env_label}"
        )

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        for admin_id in admins:
            admin_id = str(admin_id).strip()
            if admin_id:
                try:
                    requests.post(url, data={"chat_id": admin_id, "text": text, "parse_mode": "HTML"}, timeout=5)
                except Exception:
                    pass
