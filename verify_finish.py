
from tgbot.tasks import _finish_contest
from django.utils import timezone
from tgbot.models import Contest
import os
import django
import asyncio
from asgiref.sync import sync_to_async

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'src.settings')
django.setup()

# Import AFTER setup

# We need _finish_contest but importing tasks.py triggers app loading.
# We will import it inside the function just to be safe, or right here is fine now that setup() is called.


async def verify_finish_logic():
    print("Verifying Finish Logic...")

    # Create Dummy Contest
    contest = await sync_to_async(Contest.objects.create)(
        name="Test Finish Logic",
        start_date=timezone.now(),
        req_referrals=0
    )
    print(f"Created contest: {contest.id}")

    # Run Finish Once
    print("Running finish (1st time)...")
    await _finish_contest(contest.id)

    await sync_to_async(contest.refresh_from_db)()
    if contest.is_finished:
        print("PASS: Contest finished.")
    else:
        print("FAIL: Contest NOT finished.")

    # Run Finish Twice
    print("Running finish (2nd time) - Should skip...")
    try:
        await _finish_contest(contest.id)
        print("PASS: Idempotency check passed (no error).")
    except Exception as e:
        print(f"FAIL: Error on 2nd run: {e}")

    # Cleanup
    await sync_to_async(contest.delete)()
    print("Cleanup done.")

if __name__ == "__main__":
    asyncio.run(verify_finish_logic())
