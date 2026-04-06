
from django.utils import timezone
from tgbot.models import Contest
from tgbot.tasks import notify_contest_participants
import datetime

# Setup
now = timezone.now()
start_time = now + datetime.timedelta(minutes=1)  # Starts in 1 min

print(f"Current UTC: {now}")
print(f"Creating contest starting at: {start_time}")

contest = Contest.objects.create(
    name="Test Contest TZ",
    start_date=start_time,
    is_active=True,
    is_finished=False,
    is_notified=False,
    req_referrals=0,
    description="Test"
)

try:
    # Run Logic
    print("Running notify_contest_participants logic...")
    # We call the function directly (synchronously for test)
    # Note: notify_contest_participants is a shared_task, calling it directly works in newer celery/django,
    # but strictly we might need to invoke the underlying function if it was wrapped differently.
    # But usually `notify_contest_participants()` calls the wrapper.
    # Let's inspect source if needed, but standard celery tasks are callable.

    # However, to be safe and inspect internals, I'll replicate the query or just call it.
    notify_contest_participants(contest.id)

    # Check result
    contest.refresh_from_db()
    if contest.is_notified:
        print("SUCCESS: Contest was notified!")
    else:
        print("FAILURE: Contest was NOT notified.")

finally:
    # Cleanup
    print("Cleaning up...")
    contest.delete()
