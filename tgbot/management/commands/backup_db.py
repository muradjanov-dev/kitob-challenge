"""Run the daily database backup now: python manage.py backup_db"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Dump the database and DM the .sql.gz to every admin."

    def handle(self, *args, **opts):
        from tgbot.services.db_backup import run_backup
        result = run_backup()
        self.stdout.write(str({k: v for k, v in result.items() if k != "failures"}))
        if result.get("failures"):
            self.stdout.write(self.style.WARNING(str(result["failures"])))
