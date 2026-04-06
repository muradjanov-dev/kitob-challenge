
from tgbot.models import Contest
import os
import django
from django.conf import settings
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'src.settings')
django.setup()


def list_contests():
    print(f"Current Time (UTC): {timezone.now()}")
    print(f"Current Time (Local): {timezone.localtime(timezone.now())}")

    # Check contests around now +/- 1 day
    start_range = timezone.now() - timezone.timedelta(days=1)
    end_range = timezone.now() + timezone.timedelta(days=1)

    contests = Contest.objects.filter(
        start_date__range=(start_range, end_range))

    print(f"\nFound {contests.count()} contests in +/- 1 day range:")
    for contest in contests:
        print(f"ID: {contest.id} | Name: {contest.name}")
        print(f"  Start (DB/UTC): {contest.start_date}")
        print(f"  Start (Local):  {timezone.localtime(contest.start_date)}")
        print(f"  Is Active: {contest.is_active}")
        print(f"  Is Finished: {contest.is_finished}")
        print(f"  Is Notified: {contest.is_notified}")


if __name__ == '__main__':
    list_contests()
