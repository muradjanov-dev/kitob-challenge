from django.apps import AppConfig


class TgbotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tgbot'

    def ready(self):
        try:
            from django.conf import settings
            import requests
            import os

            token = getattr(settings, 'API_TOKEN', None) or os.environ.get('API_TOKEN')
            admins_raw = getattr(settings, 'ADMINS', None) or os.environ.get('ADMINS', '')
            if isinstance(admins_raw, str):
                admins = [a.strip() for a in admins_raw.split(',') if a.strip()]
            else:
                admins = [str(a).strip() for a in admins_raw if str(a).strip()]

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
                try:
                    requests.post(url, data={"chat_id": admin_id, "text": text, "parse_mode": "HTML"}, timeout=5)
                except Exception:
                    pass
        except Exception:
            pass
