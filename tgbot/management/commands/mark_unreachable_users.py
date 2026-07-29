"""
Mutating counterpart to diagnose_unreachable_users (which is read-only): for
every non-blocked TelegramProfile, call Telegram's getChat, and mark the
permanently-unreachable ones (bot blocked, or chat/account deleted) as
is_blocked=True — the same flag already checked everywhere broadcasts filter
users out, so this just stops future daily tasks from wasting time/API calls
on dead chats and stops them inflating "active user" counts.

Ishlatish:
    python manage.py mark_unreachable_users            # dry-run, only reports
    python manage.py mark_unreachable_users --apply     # actually updates is_blocked
"""
import time

import requests
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Mark permanently-unreachable users (blocked bot / deleted account) as is_blocked=True."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually update is_blocked (default: dry-run report only).",
        )

    def handle(self, *args, **options):
        from tgbot.tasks import BOT_TOKEN
        from tgbot.models import TelegramProfile

        apply_changes = options["apply"]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
        qs = TelegramProfile.objects.filter(is_blocked=False)
        total = qs.count()

        to_block_ids = []
        reachable = 0
        other_errors = 0
        other_samples = []

        for profile_id, chat_id in qs.values_list("id", "telegram_id").iterator():
            try:
                resp = requests.get(url, params={"chat_id": chat_id}, timeout=10)
                if resp.ok:
                    reachable += 1
                else:
                    desc = resp.json().get("description", "").lower()
                    if "blocked" in desc or "not found" in desc:
                        to_block_ids.append(profile_id)
                    else:
                        other_errors += 1
                        if len(other_samples) < 10:
                            other_samples.append(f"{chat_id}: {desc[:80]}")
                    if resp.status_code == 429:
                        retry_after = resp.json().get("parameters", {}).get("retry_after", 3)
                        time.sleep(retry_after)
            except Exception as e:
                other_errors += 1
                if len(other_samples) < 10:
                    other_samples.append(f"{chat_id}: {e}")
            time.sleep(0.05)

        self.stdout.write(self.style.SUCCESS(
            f"Checked {total} users:\n"
            f"  ✅ Reachable (untouched): {reachable}\n"
            f"  🛑 Unreachable (to block): {len(to_block_ids)}\n"
            f"  ❓ Other errors (untouched): {other_errors}"
        ))
        if other_samples:
            self.stdout.write("Sample 'other' errors:")
            for s in other_samples:
                self.stdout.write(f"  {s}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                "Dry-run only — nothing was changed. Re-run with --apply to set is_blocked=True on the unreachable ones."
            ))
            return

        updated = TelegramProfile.objects.filter(id__in=to_block_ids).update(is_blocked=True)
        self.stdout.write(self.style.SUCCESS(f"Marked {updated} profiles as is_blocked=True."))
