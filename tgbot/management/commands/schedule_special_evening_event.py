"""
Schedule tonight's one-off "N-game bonus night" event a few seconds before
the regular 22:00 evening slot, so it wins the GameSequence creation race and
the regular auto-sequence quietly no-ops instead of double-starting.

Ishlatish (Railway console yoki SSH):
    python manage.py schedule_special_evening_event
    python manage.py schedule_special_evening_event --count 5 --bonus 2
"""
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Schedule tonight's special evening game event (bonus night)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=5)
        parser.add_argument("--bonus", type=int, default=2)
        parser.add_argument("--hour", type=int, default=21)
        parser.add_argument("--minute", type=int, default=59)
        parser.add_argument("--second", type=int, default=50)

    def handle(self, *args, **options):
        from tgbot.tasks import start_special_evening_event

        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        naive = datetime.datetime.combine(
            today, datetime.time(options["hour"], options["minute"], options["second"]),
        )
        eta = timezone.make_aware(naive, tz)
        now = timezone.now()
        if eta <= now:
            self.stdout.write(self.style.WARNING(
                f"Target time {eta} has already passed (now={now}); scheduling 10s from now instead."
            ))
            eta = now + datetime.timedelta(seconds=10)

        result = start_special_evening_event.apply_async(
            args=[options["count"], options["bonus"]], eta=eta,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Scheduled start_special_evening_event(count={options['count']}, "
            f"bonus_count={options['bonus']}) for {eta} (task id: {result.id})"
        ))
