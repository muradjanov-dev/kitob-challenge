"""
Manually resend + re-pin the daily progress-bar message to every registered,
non-blocked user right now, instead of waiting for the 00:01 daily job.

Ishlatish (Railway console yoki SSH):
    python manage.py trigger_progress_broadcast
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Resend + re-pin the daily progress message to every user now (same as the 00:01 job)."

    def handle(self, *args, **options):
        from tgbot.tasks import daily_progress_broadcast
        daily_progress_broadcast()
        self.stdout.write(self.style.SUCCESS("daily_progress_broadcast finished — see output above for sent count."))
