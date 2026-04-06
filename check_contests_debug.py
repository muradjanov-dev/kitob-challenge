from tgbot.models import Contest
import os
import django
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()


def check_contests():
    now = timezone.now()
    two_minutes_later = now + timezone.timedelta(minutes=2)
    check_start = now - timezone.timedelta(minutes=5)

    print(f"Current time (UTC): {now}")
    print(f"Check Window: {check_start} to {two_minutes_later}")

    print("\n--- All Contests ---")
    contests = Contest.objects.all().order_by('-start_date')[:5]
    for c in contests:
        print(f"ID: {c.id}, Name: {c.name}, Start: {c.start_date} (UTC), Active: {c.is_active}, Finished: {c.is_finished}, Notified: {c.is_notified}")

    print("\n--- Matching Query ---")
    upcoming = Contest.objects.filter(
        start_date__gte=check_start,
        start_date__lte=two_minutes_later,
        is_active=True,
        is_finished=False,
        is_notified=False
    )
    print(f"Found {upcoming.count()} matching contents.")
    for c in upcoming:
        print(f"MATCH: {c.name}")


if __name__ == "__main__":
    check_contests()
