"""Approved one-off announcements, sent through views.internal_ops.

The text arrives in the request instead of living in code, so the exact
wording the owner approved goes out without a deploy per message. Each
campaign reaches every group and reader at most once: a per-recipient cache
key is claimed before sending, so a retry or a double trigger skips whoever
already has it. Progress is kept in the cache under ops_bc:<campaign>.
"""
import json
import time

import requests
from django.core.cache import cache

KEEP = 30 * 86400


def _progress_key(campaign):
    return f"ops_bc:{campaign}"


def status(campaign) -> dict:
    return cache.get(_progress_key(campaign)) or {"state": "none"}


def run(campaign: str, text: str, groups: bool = True, users: bool = True,
        button_text: str = "", button_url: str = "") -> dict:
    from tgbot.models import TelegramProfile
    from tgbot.tasks import BOT_TOKEN, _announce_targets

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    markup = None
    if button_text and button_url:
        markup = json.dumps({"inline_keyboard": [[{"text": button_text, "url": button_url}]]})

    prog = {"state": "running", "groups_sent": 0, "users_sent": 0, "skipped": 0,
            "blocked": 0, "failed": 0, "total_users": 0}
    cache.set(_progress_key(campaign), prog, KEEP)

    def _send(chat_id, thread_id=None):
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": "true"}
        if thread_id:
            data["message_thread_id"] = thread_id
        if markup:
            data["reply_markup"] = markup
        for _ in range(3):
            resp = requests.post(url, data=data, timeout=10)
            if resp.status_code == 429:
                time.sleep(int(resp.json().get("parameters", {}).get("retry_after", 5)) + 1)
                continue
            return resp
        return resp

    if groups:
        for chat_id, thread_id in _announce_targets():
            if not cache.add(f"ops_bc:{campaign}:g:{chat_id}", 1, KEEP):
                prog["skipped"] += 1
                continue
            try:
                if _send(chat_id, thread_id).ok:
                    prog["groups_sent"] += 1
                else:
                    prog["failed"] += 1
            except Exception as e:
                print(f"ops_broadcast {campaign} group {chat_id}: {e}")
                prog["failed"] += 1

    if users:
        ids = list(
            TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
            .values_list("telegram_id", flat=True).distinct()
        )
        prog["total_users"] = len(ids)
        for n, tg_id in enumerate(ids, 1):
            if not cache.add(f"ops_bc:{campaign}:u:{tg_id}", 1, KEEP):
                prog["skipped"] += 1
                continue
            try:
                resp = _send(tg_id)
                if resp.ok:
                    prog["users_sent"] += 1
                elif resp.status_code == 403:
                    prog["blocked"] += 1
                    TelegramProfile.objects.filter(telegram_id=tg_id).update(is_blocked=True)
                else:
                    prog["failed"] += 1
            except Exception:
                prog["failed"] += 1
            if n % 50 == 0:
                cache.set(_progress_key(campaign), prog, KEEP)
            time.sleep(0.05)

    prog["state"] = "done"
    cache.set(_progress_key(campaign), prog, KEEP)
    print(f"ops_broadcast {campaign}: {prog}")
    return prog
