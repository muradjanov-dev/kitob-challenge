import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.management.base import BaseCommand
from django.db import connections, transaction
from tgbot.models import TelegramProfile

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Simulates high concurrency database load to test connection pooling'

    def add_arguments(self, parser):
        parser.add_argument('--users', type=int, default=100,
                            help='Number of concurrent simulated users')
        parser.add_argument('--iterations', type=int,
                            default=10, help='Number of actions per user')
        parser.add_argument('--cleanup', action='store_true',
                            help='Delete test users after running')

    def simulate_user_action(self, user_id):
        """
        Simulates a user interaction:
        1. Query user (db read)
        2. Update/Create user (db write)
        """
        try:
            # Random sleep to de-synchronize threads slightly, like real traffic
            time.sleep(random.uniform(0.01, 0.5))

            # This mimics `get_user` and subsequent write in handlers
            user, created = TelegramProfile.objects.get_or_create(
                telegram_id=user_id,
                defaults={'full_name': f'LoadTestUser_{user_id}'}
            )

            # Simulate a small update
            user.ball += 1
            user.save(update_fields=['ball'])

            return True
        except Exception as e:
            return f"Error: {e}"

    def handle(self, *args, **options):
        num_users = options['users']
        iterations = options['iterations']

        self.stdout.write(self.style.SUCCESS(
            f'Starting load test with {num_users} concurrent threads...'))

        # Connection DB info (just for debug)
        db_settings = connections['default'].settings_dict
        self.stdout.write(
            f"Connecting to DB: {db_settings.get('HOST')}:{db_settings.get('PORT')}")

        start_time = time.time()
        start_user_id = 999000000

        success_count = 0
        error_count = 0
        errors = []

        with ThreadPoolExecutor(max_workers=num_users) as executor:
            futures = []
            for i in range(num_users):
                # Each "user" performs multiple iterations
                for j in range(iterations):
                    user_id = start_user_id + i
                    futures.append(executor.submit(
                        self.simulate_user_action, user_id))

            self.stdout.write(
                f"Scheduled {len(futures)} tasks. Waiting for completion...")

            for future in as_completed(futures):
                result = future.result()
                if result is True:
                    success_count += 1
                else:
                    error_count += 1
                    errors.append(result)

        duration = time.time() - start_time

        self.stdout.write(self.style.HTTP_INFO(
            '--------------------------------------------------'))
        self.stdout.write(f"Total Time: {duration:.2f} seconds")
        self.stdout.write(f"Total Requests: {success_count + error_count}")
        self.stdout.write(f"Successful: {success_count}")
        self.stdout.write(f"Failed: {error_count}")
        if errors:
            self.stdout.write(self.style.ERROR(
                f"First 5 Errors: {errors[:5]}"))

        if error_count == 0:
            self.stdout.write(self.style.SUCCESS(
                'PASSED: System handled the load without DB errors.'))
        else:
            self.stdout.write(self.style.ERROR(
                'FAILED: Some connections failed.'))

        if options['cleanup']:
            self.stdout.write("Cleaning up test data...")
            count, _ = TelegramProfile.objects.filter(
                telegram_id__gte=999000000).delete()
            self.stdout.write(self.style.SUCCESS(
                f"Deleted {count} test users."))
