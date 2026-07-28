"""
One-off: schedule tgbot.tasks.send_recs_to_all_promo to fire once at a given
wall-clock time today (default 07:00 Tashkent) via Celery's apply_async(eta=...).
Not a recurring beat entry — this is a single occurrence.

Ishlatish (Railway console yoki SSH):
    python manage.py schedule_recs_promo                # today at 07:00
    python manage.py schedule_recs_promo --hour 8 --minute 30
    python manage.py schedule_recs_promo --now           # fire immediately instead
"""
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Schedule (or immediately fire) the one-off recommend-to-everyone promo broadcast."

    def add_arguments(self, parser):
        parser.add_argument("--hour", type=int, default=7)
        parser.add_argument("--minute", type=int, default=0)
        parser.add_argument("--now", action="store_true", help="Fire immediately instead of scheduling.")

    def handle(self, *args, **options):
        from tgbot.tasks import send_recs_to_all_promo

        if options["now"]:
            send_recs_to_all_promo.delay()
            self.stdout.write(self.style.SUCCESS("send_recs_to_all_promo queued to run immediately."))
            return

        today = timezone.localdate()
        naive = datetime.datetime.combine(today, datetime.time(options["hour"], options["minute"]))
        eta = timezone.make_aware(naive)

        if eta <= timezone.now():
            self.stdout.write(self.style.WARNING(
                f"{eta.strftime('%H:%M')} already passed today — use --now to fire immediately, "
                "or pick a later --hour/--minute."
            ))
            return

        send_recs_to_all_promo.apply_async(eta=eta)
        self.stdout.write(self.style.SUCCESS(
            f"Scheduled send_recs_to_all_promo for {eta.strftime('%Y-%m-%d %H:%M %Z')} (Tashkent)."
        ))
