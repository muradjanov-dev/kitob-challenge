from django.apps import AppConfig


class TgbotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tgbot"

    def ready(self):
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE quiz_games ADD COLUMN IF NOT EXISTS is_vip boolean DEFAULT false;")
        except Exception:
            pass
