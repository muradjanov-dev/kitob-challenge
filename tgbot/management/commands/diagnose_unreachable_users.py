"""
Read-only diagnostic: for every non-blocked TelegramProfile, call Telegram's
getChat (does NOT send a message) to find out how many are actually
reachable right now, and bucket the unreachable ones by error reason
(bot blocked by user / chat not found — deleted account / other).

Ishlatish (Railway console yoki SSH):
    python manage.py diagnose_unreachable_users
"""
import time

import requests
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Read-only: bucket non-blocked users by whether the bot can still reach their chat."

    def handle(self, *args, **options):
        from tgbot.tasks import BOT_TOKEN
        from tgbot.models import TelegramProfile

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
        qs = TelegramProfile.objects.filter(is_blocked=False)
        total = qs.count()

        reachable = 0
        bot_blocked = 0
        deleted_or_not_found = 0
        other_errors = 0
        other_samples = []

        for chat_id in qs.values_list("telegram_id", flat=True).iterator():
            try:
                resp = requests.get(url, params={"chat_id": chat_id}, timeout=10)
                if resp.ok:
                    reachable += 1
                else:
                    desc = resp.json().get("description", "").lower()
                    if "blocked" in desc:
                        bot_blocked += 1
                    elif "not found" in desc or "chat not found" in desc:
                        deleted_or_not_found += 1
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
            f"  ✅ Reachable: {reachable}\n"
            f"  🚫 Blocked the bot: {bot_blocked}\n"
            f"  🗑 Deleted / chat not found: {deleted_or_not_found}\n"
            f"  ❓ Other errors: {other_errors}"
        ))
        if other_samples:
            self.stdout.write("Sample 'other' errors:")
            for s in other_samples:
                self.stdout.write(f"  {s}")
