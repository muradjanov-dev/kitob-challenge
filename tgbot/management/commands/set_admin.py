"""
Grant (or revoke) TelegramProfile.is_admin for a given telegram_id — this is
what admin_panel.py's handlers check to allow admin panel access.

Ishlatish:
    python manage.py set_admin 8278937151
    python manage.py set_admin 8278937151 --revoke
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Grant or revoke bot admin access (TelegramProfile.is_admin) for a telegram_id."

    def add_arguments(self, parser):
        parser.add_argument("telegram_id", type=int)
        parser.add_argument("--revoke", action="store_true")

    def handle(self, *args, **options):
        from tgbot.models import TelegramProfile

        tid = options["telegram_id"]
        user = TelegramProfile.objects.filter(telegram_id=tid).first()
        if not user:
            raise CommandError(f"No TelegramProfile found with telegram_id={tid}")

        user.is_admin = not options["revoke"]
        user.save(update_fields=["is_admin"])
        action = "revoked from" if options["revoke"] else "granted to"
        self.stdout.write(self.style.SUCCESS(
            f"Admin access {action} {user.full_name or user.username or tid} (telegram_id={tid})."
        ))
