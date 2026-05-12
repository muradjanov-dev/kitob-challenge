import os
import requests
from datetime import datetime, timezone

from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Send a deploy notification to all admins via Telegram."

    def handle(self, *args, **options):
        token = os.environ.get("API_TOKEN", "")
        if not token:
            self.stdout.write("API_TOKEN not set — skipping deploy notification.")
            return

        sha = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:7] or "local"
        branch = os.environ.get("RAILWAY_GIT_BRANCH") or "—"
        raw_msg = (os.environ.get("RAILWAY_GIT_COMMIT_MESSAGE") or "").strip()
        commit_summary = raw_msg.splitlines()[0][:120] if raw_msg else ""
        deployment_id = os.environ.get("RAILWAY_DEPLOYMENT_ID") or "—"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        commit_line = f"\n📝 <i>{commit_summary}</i>" if commit_summary else ""
        text = (
            f"🚀 <b>Kitob Challenge deployed</b>\n"
            f"🕒 {now}\n"
            f"🌿 branch: <code>{branch}</code>\n"
            f"🔖 commit: <code>{sha}</code>{commit_line}\n"
            f"📦 deployment: <code>{deployment_id}</code>"
        )

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        for admin_id in settings.ADMINS:
            try:
                resp = requests.post(
                    url,
                    data={"chat_id": admin_id, "text": text, "parse_mode": "HTML"},
                    timeout=5,
                )
                if resp.ok:
                    self.stdout.write(f"Deploy notif sent to {admin_id}")
                else:
                    self.stdout.write(f"Failed to notify {admin_id}: {resp.text}")
            except Exception as e:
                self.stdout.write(f"Error notifying {admin_id}: {e}")
