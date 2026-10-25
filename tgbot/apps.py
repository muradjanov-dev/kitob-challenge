from django.apps import AppConfig


class TgbotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tgbot"

    def ready(self):
        # New alphabet on every Bot API call made with requests (Celery tasks,
        # services) -- see services/alphabet.py.
        try:
            from tgbot.services import alphabet
            alphabet.install()
        except Exception as e:
            print(f"alphabet install failed: {e}")
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE quiz_games ADD COLUMN IF NOT EXISTS is_vip boolean DEFAULT false;")
        except Exception:
            pass
