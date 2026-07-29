"""
One-off: announce the AI quiz generation quality upgrade to every group
(E'lonlar topic) and DM every registered user, inviting everyone — Premium
or not — to try building one AI quiz for free, then pitching Premium for
unlimited use. The group copy's button is a `url` deep link
(https://t.me/<bot>?start=aiquiz); the DM copy uses callback_data
("aiquiz_start") for a snappier one-tap experience since it's already
private.

Ishlatish (Railway console yoki SSH):
    python manage.py announce_ai_quiz_upgrade
"""
import json
import time

import requests
from django.core.management.base import BaseCommand


_TEXT = (
    "🎉 <b>Kitob quizlar sifati juda yaxshilandi!</b>\n\n"
    "🤖 AI endi kitobingizdan ancha aniqroq va sifatliroq savollar tuzadi — "
    "muqova yoki mundarija emas, aynan voqealar, qahramonlar va syujet "
    "asosida!\n\n"
    "🎁 Buni his qilib ko'rishingiz uchun — <b>hammaga (Premium bo'lmasa "
    "ham!) bitta AI quiz tuzish BEPUL!</b>\n\n"
    "📖 Matn, rasm yoki kitobning PDF faylini yuboring — AI o'zi qiziqarli "
    "savollar bilan quiz tuzib beradi. Eng sifatli testni o'zingiz tuzib "
    "ko'ring!\n\n"
    "📤 <b>Eslatma:</b> tuzgan testingizni faqat shu yerda emas — istalgan "
    "boshqa guruhda ham \"Guruhga ulashish\" tugmasi orqali ishlata olasiz!\n\n"
    "👇 Hoziroq sinab ko'ring!"
)

_DM_KEYBOARD = json.dumps({
    "inline_keyboard": [[{"text": "🤖 Bepul AI quiz tuzish", "callback_data": "aiquiz_start"}]]
})


class Command(BaseCommand):
    help = "Announce the AI quiz quality upgrade + free trial to every group and DM every registered user."

    def handle(self, *args, **options):
        from tgbot.tasks import BOT_TOKEN, _announce_targets, _get_bot_username
        from tgbot.models import TelegramProfile

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        username = _get_bot_username()
        group_keyboard = json.dumps({
            "inline_keyboard": [[{
                "text": "🤖 Bepul AI quiz tuzish",
                "url": f"https://t.me/{username}?start=aiquiz" if username else "https://t.me/",
            }]]
        })

        # 1) Groups — E'lonlar topic (falls back to the group's default topic
        # if that env var isn't set for a given group, e.g. the boys group).
        g_sent = g_failed = 0
        for chat_id, thread_id in _announce_targets():
            data = {"chat_id": chat_id, "text": _TEXT, "parse_mode": "HTML",
                    "reply_markup": group_keyboard, "disable_web_page_preview": "true"}
            if thread_id:
                data["message_thread_id"] = thread_id
            try:
                resp = requests.post(url, data=data, timeout=10)
                if resp.ok:
                    g_sent += 1
                else:
                    g_failed += 1
                    self.stdout.write(self.style.WARNING(f"group {chat_id} failed: {resp.text[:150]}"))
            except Exception as e:
                g_failed += 1
                self.stdout.write(self.style.WARNING(f"group {chat_id} error: {e}"))

        # 2) DM every non-blocked user, registered or not (a user who pressed
        # /start but abandoned registration partway has no row here at all —
        # nothing is stored for them — so this is everyone reachable in
        # practice, not just is_registered=True profiles).
        qs = TelegramProfile.objects.filter(is_blocked=False)
        u_sent = u_failed = 0
        for chat_id in qs.values_list("telegram_id", flat=True).iterator():
            try:
                resp = requests.post(
                    url,
                    data={"chat_id": chat_id, "text": _TEXT, "parse_mode": "HTML",
                          "reply_markup": _DM_KEYBOARD, "disable_web_page_preview": "true"},
                    timeout=10,
                )
                if resp.ok:
                    u_sent += 1
                else:
                    u_failed += 1
                    if resp.status_code == 429:
                        retry_after = resp.json().get("parameters", {}).get("retry_after", 3)
                        time.sleep(retry_after)
            except Exception:
                u_failed += 1
            time.sleep(0.05)

        self.stdout.write(self.style.SUCCESS(
            f"AI quiz upgrade announced: groups sent={g_sent} failed={g_failed}; "
            f"users sent={u_sent} failed={u_failed}."
        ))
