"""
Management command: compute_optimal_send_hours
----------------------------------------------
For every registered user, look at their ConfirmationReport history and find
the hour of day (Tashkent time) when they most often submit reports.  That
hour − 1 becomes their optimal_send_hour — we nudge them one hour BEFORE their
natural peak so the message lands just as they're getting into reading mode.

The result is written to TelegramProfile.optimal_send_hour (NULL if the user
has fewer than MIN_REPORTS reports — not enough signal yet).

Run this once after deploy to seed existing users, then wire it into a weekly
Celery beat task so new users accumulate signal over time.

    python manage.py compute_optimal_send_hours
    python manage.py compute_optimal_send_hours --min-reports 5
"""

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tgbot.models import ConfirmationReport, TelegramProfile

# Users with fewer reports than this get NULL (no strong signal yet).
DEFAULT_MIN_REPORTS = 3

# Allowable window: 07:00–22:00 Tashkent.  Outside this range we clamp to the
# nearest boundary so we never schedule a nudge in the middle of the night.
SEND_HOUR_MIN = 7
SEND_HOUR_MAX = 22


def _clamp(hour: int) -> int:
    return max(SEND_HOUR_MIN, min(SEND_HOUR_MAX, hour))


def compute_hour_for_user(user_id: int, min_reports: int) -> int | None:
    """
    Return the optimal send hour for one user, or None if not enough data.

    Algorithm (no external libraries needed):
    1. Pull the submission hour (Tashkent local time) for every report.
    2. Count how many reports fall in each hour → frequency histogram.
    3. Pick the mode (most-frequent hour).
    4. Subtract 1 so the reminder arrives slightly before their usual session.
    5. Clamp to [SEND_HOUR_MIN, SEND_HOUR_MAX].
    """
    reports = ConfirmationReport.objects.filter(user_id=user_id).values_list("date", flat=True)

    hours = []
    for dt in reports:
        local_dt = timezone.localtime(dt)   # convert UTC → Tashkent
        hours.append(local_dt.hour)

    if len(hours) < min_reports:
        return None

    # Mode of submission hours
    counter = Counter(hours)
    peak_hour = counter.most_common(1)[0][0]

    # Nudge one hour earlier, clamp to safe window
    send_hour = _clamp(peak_hour - 1)
    return send_hour


class Command(BaseCommand):
    help = (
        "Compute the optimal reminder hour for each user from their "
        "ConfirmationReport submission history and store it on TelegramProfile."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-reports",
            type=int,
            default=DEFAULT_MIN_REPORTS,
            help=f"Minimum number of reports required to assign an hour (default: {DEFAULT_MIN_REPORTS}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be set without writing to the database.",
        )

    def handle(self, *args, **options):
        min_reports = options["min_reports"]
        dry_run = options["dry_run"]

        users = TelegramProfile.objects.filter(
            is_registered=True, is_blocked=False
        ).values_list("id", "telegram_id", "full_name", "optimal_send_hour")

        updated = skipped = cleared = 0

        updates = []   # (pk, new_hour) pairs

        for user_id, tg_id, name, current_hour in users:
            new_hour = compute_hour_for_user(user_id, min_reports)

            if new_hour == current_hour:
                skipped += 1
                continue

            updates.append((user_id, new_hour))

            if new_hour is None:
                cleared += 1
                action = "→ NULL (not enough data)"
            else:
                updated += 1
                action = f"→ hour {new_hour:02d}:00"

            if dry_run or options["verbosity"] >= 2:
                self.stdout.write(f"  [{tg_id}] {name or '?'}: {action}")

        if not dry_run:
            # Bulk-update in chunks to avoid one enormous transaction
            chunk_size = 500
            for i in range(0, len(updates), chunk_size):
                chunk = updates[i : i + chunk_size]
                with transaction.atomic():
                    for pk, hour in chunk:
                        TelegramProfile.objects.filter(pk=pk).update(optimal_send_hour=hour)

        self.stdout.write(
            self.style.SUCCESS(
                f"{'[DRY RUN] ' if dry_run else ''}"
                f"Done — updated: {updated}, cleared: {cleared}, unchanged: {skipped}"
            )
        )
