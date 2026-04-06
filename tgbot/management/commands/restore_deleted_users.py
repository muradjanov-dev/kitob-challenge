from django.core.management.base import BaseCommand
from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from tgbot.models import TelegramProfile, Habit
import json


class Command(BaseCommand):
    help = 'Restores deleted TelegramProfile objects and Habits from AuditLog'

    def handle(self, *args, **options):
        # 1. Restore Users
        ct_user = ContentType.objects.get_for_model(TelegramProfile)
        deleted_users = LogEntry.objects.filter(content_type=ct_user, action=2)

        self.stdout.write(
            f"Found {deleted_users.count()} deleted users in AuditLog.")

        restored_users_count = 0
        skipped_users_count = 0

        # We need to map old IDs to restored objects if we can't force the ID.
        # But we CAN force the ID in Django create().

        for entry in deleted_users:
            try:
                changes = entry.changes
                if not changes:
                    continue

                data = {}
                telegram_id = None
                user_pk = None

                for field, values in changes.items():
                    val = values[0]
                    if field == 'id':
                        user_pk = val
                        continue
                    if field == 'telegram_id':
                        telegram_id = val

                    if field in ['full_name', 'username', 'language', 'phone_number', 'is_registered', 'is_admin', 'ball']:
                        data[field] = val

                if telegram_id:
                    # Check if exists by telegram_id
                    existing = TelegramProfile.objects.filter(
                        telegram_id=telegram_id).first()
                    if existing:
                        skipped_users_count += 1
                        # If the existing user has a different PK than the old one, we have a problem for relations.
                        # But presumably the user was just restored or re-created.
                        continue

                    # Attempt to restore WITH ORIGINAL ID if possible
                    if user_pk:
                        # Check if ID is taken (unlikely for auto-increment unless we have gaps or partial restores)
                        if TelegramProfile.objects.filter(id=user_pk).exists():
                            self.stdout.write(self.style.WARNING(
                                f"User ID {user_pk} taken, creating with new ID."))
                            TelegramProfile.objects.create(
                                telegram_id=telegram_id, **data)
                        else:
                            TelegramProfile.objects.create(
                                id=user_pk, telegram_id=telegram_id, **data)
                    else:
                        TelegramProfile.objects.create(
                            telegram_id=telegram_id, **data)

                    restored_users_count += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"Failed to restore user entry {entry.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Restored {restored_users_count} users. Skipped {skipped_users_count}."))

        # 2. Restore Habits
        ct_habit = ContentType.objects.get_for_model(Habit)
        deleted_habits = LogEntry.objects.filter(
            content_type=ct_habit, action=2)
        self.stdout.write(
            f"Found {deleted_habits.count()} deleted Habits in AuditLog.")

        restored_habits = 0
        for entry in deleted_habits:
            try:
                changes = entry.changes
                if not changes:
                    continue

                data = {}
                user_pk_str = None

                for field, values in changes.items():
                    val = values[0]
                    if field == 'id':
                        continue
                    if field == 'user':
                        user_pk_str = val  # This is likely the PK ID as string '46'

                    if field in ['name', 'duration', 'reminders_per_day', 'status', 'completed_days', 'notification_must_be_sent']:
                        data[field] = val

                if user_pk_str:
                    try:
                        user_id = int(user_pk_str)
                        # Find the user. They SHOULD exist now.
                        user = TelegramProfile.objects.filter(
                            id=user_id).first()
                        if user:
                            Habit.objects.create(user=user, **data)
                            restored_habits += 1
                        else:
                            self.stdout.write(self.style.WARNING(
                                f"Habit {entry.id} skipped: User {user_id} not found."))
                    except ValueError:
                        self.stdout.write(self.style.ERROR(
                            f"Habit {entry.id} skipped: Invalid User ID {user_pk_str}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"Failed to restore habit {entry.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Restored {restored_habits} habits."))
