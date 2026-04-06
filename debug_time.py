import os
import django
import sys

# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'src.settings')


def check_time():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'src.settings')
    django.setup()

    from django.conf import settings
    from django.utils import timezone
    from tgbot.models import Contest

    now = timezone.now()
    local_now = timezone.localtime(now)

    print(f"Timezone: {timezone.get_current_timezone_name()}")
    print(f"Timezone.now() (UTC expected): {now}")
    print(f"Local time (Asia/Tashkent): {local_now}")
    print("-" * 20)

    for c in Contest.objects.filter(is_active=True).order_by('-id')[:5]:
        print(f"Contest: {c.name} (ID: {c.id})")
        print(f"  Start Date (DB): {c.start_date}")
        print(f"  Start Date (Local): {timezone.localtime(c.start_date)}")
        print(f"  Is Started: {c.is_started}")
        print(
            f"  Should Start Now? (start_date <= now): {c.start_date <= now}")
        print("-" * 10)


if __name__ == "__main__":
    check_time()
