from tgbot.models import Contest
from datetime import timedelta
from django.utils import timezone
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'src.settings')
django.setup()


def verify_start_scheduling():
    print("Verifying Contest Start Scheduling...")

    # 1. Test Scheduling
    start_future = timezone.now() + timedelta(minutes=15)
    c1 = Contest.objects.create(
        name="Test Start Scheduling",
        start_date=start_future,
        req_referrals=0,
        is_active=True
    )
    print(f"Created contest starting in 15 mins: {c1.name}")
    print(f"Start Task ID: {c1.start_task_id}")

    if c1.start_task_id:
        print("PASS: Start task scheduled.")
    else:
        print("FAIL: Start task NOT scheduled.")

    # 2. Test Revocation/Reschedule
    old_task_id = c1.start_task_id
    new_start = timezone.now() + timedelta(minutes=20)
    c1.start_date = new_start
    c1.save()

    c1.refresh_from_db()
    print(f"Updated start time to 20 mins. New Task ID: {c1.start_task_id}")

    if c1.start_task_id and c1.start_task_id != old_task_id:
        print("PASS: Task rescheduled (ID changed).")
    else:
        print(
            f"FAIL: Task not rescheduled correctly. Old: {old_task_id}, New: {c1.start_task_id}")

    # Cleanup
    c1.delete()
    print("\nCleanup done.")


if __name__ == "__main__":
    verify_start_scheduling()
