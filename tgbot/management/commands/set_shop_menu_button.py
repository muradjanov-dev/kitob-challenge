"""Set the Telegram chat menu button (the chip to the left of the input box)
to open the shop Mini App.

Scoped per-admin: the WebApp button only appears for users where is_admin=True
because the shop is still in admin-only test mode. Non-admins keep Telegram's
default 'Menu' button.

Usage:
    python manage.py set_shop_menu_button           # set 'Do'kon' for admins
    python manage.py set_shop_menu_button --reset   # revert admins to default
"""
import json
from django.conf import settings
from django.core.management.base import BaseCommand

import requests

from tgbot.models import TelegramProfile


class Command(BaseCommand):
    help = "Set/reset the chat menu button to open the shop Mini App for admins."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Revert to Telegram's default Menu button.",
        )
        parser.add_argument(
            "--label", default="🛍 Do'kon",
            help="Button label (max 14 chars per Telegram). Default: 🛍 Do'kon.",
        )

    def handle(self, *args, reset=False, label="🛍 Do'kon", **opts):
        url = f"https://api.telegram.org/bot{settings.API_TOKEN}/setChatMenuButton"
        shop_url = f"{settings.WEB_DOMAIN}/shop/"

        admins = list(
            TelegramProfile.objects
            .filter(is_admin=True, is_blocked=False)
            .values_list("telegram_id", flat=True)
        )
        if not admins:
            self.stdout.write(self.style.WARNING("No is_admin users found."))
            return

        if reset:
            menu_button = {"type": "default"}
            action = "reset"
        else:
            menu_button = {
                "type": "web_app",
                "text": label,
                "web_app": {"url": shop_url},
            }
            action = "set"

        ok, failed = 0, 0
        for tid in admins:
            try:
                resp = requests.post(url, data={
                    "chat_id": str(tid),
                    "menu_button": json.dumps(menu_button),
                }, timeout=10)
                if resp.ok and resp.json().get("ok"):
                    ok += 1
                    self.stdout.write(self.style.SUCCESS(f"  {action} for {tid}"))
                else:
                    failed += 1
                    self.stdout.write(self.style.ERROR(
                        f"  {action} FAILED for {tid}: {resp.status_code} {resp.text[:200]}"
                    ))
            except Exception as e:
                failed += 1
                self.stdout.write(self.style.ERROR(f"  {action} EXCEPTION for {tid}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Done: {ok} {action}, {failed} failed. Mini App URL: {shop_url}"
        ))
