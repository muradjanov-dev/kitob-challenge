"""
One-off: announce the new 🎪 Market to every group (E'lonlar topic) and DM
every registered user. The group copy's button is a `url` deep link
(https://t.me/<bot>?start=market) — inline buttons with callback_data only
fire inside the chat they were posted in, and the Market menu must never be
posted into a group (see tgbot/bot/handlers/users/market.py's private-chat
guard). The DM copy can safely use callback_data since it's already private.

Ishlatish (Railway console yoki SSH):
    python manage.py announce_market_launch
"""
import json
import time

import requests
from django.core.management.base import BaseCommand


_TEXT = (
    "🎪 <b>YANGILIK: Kitob Challenge Market ochildi!</b>\n\n"
    "Endi yig'gan 🪙 Kitobchalaringizni qiziqarli xizmatlarga sarflashingiz "
    "mumkin:\n\n"
    "🛡 <b>Streak muzlatish</b> — 750 🪙\n"
    "   Bir kun hisobot yubormay qolsangiz ham, ketma-ketligingiz buzilmaydi!\n\n"
    "🎁 <b>Sirli quti</b> — 200 🪙\n"
    "   Tasodifiy mukofot: Kitobcha, o'yinga qo'shimcha jon yoki bonus token — "
    "hech qachon bo'sh chiqmaydi!\n\n"
    "📜 <b>Shaxsiy sertifikat</b> — 150 🪙\n"
    "   O'z statistikangiz bilan chiroyli rasm-sertifikat, darhol yuboriladi.\n\n"
    "🌟 <b>Kun qahramoni</b> — 500 🪙\n"
    "   Siz haqingizda tantanali e'lon guruhga darhol joylanadi.\n\n"
    "🏷 <b>Reyting sponsorligi</b> — 300 🪙\n"
    "   Keyingi \"Top kitobxonlar\" e'lonida ismingiz sponsor sifatida "
    "ko'rsatiladi.\n\n"
    "👇 Hoziroq ko'rib chiqing!"
)

_DM_KEYBOARD = json.dumps({
    "inline_keyboard": [[{"text": "🎪 Marketni ochish", "callback_data": "menu:market"}]]
})


class Command(BaseCommand):
    help = "Announce the new Market to every group and DM every registered user, right now."

    def handle(self, *args, **options):
        from tgbot.tasks import BOT_TOKEN, _announce_targets, _get_bot_username
        from tgbot.models import TelegramProfile

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        username = _get_bot_username()
        group_keyboard = json.dumps({
            "inline_keyboard": [[{
                "text": "🎪 Marketni ochish",
                "url": f"https://t.me/{username}?start=market" if username else "https://t.me/",
            }]]
        })

        # 1) Groups — E'lonlar topic (falls back to the group's default topic
        # if that env var isn't set for a given group, e.g. the boys group).
        # Uses a url deep link (not callback_data) so it opens the bot's DM.
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

        # 2) DM every registered, non-blocked user.
        qs = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
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
            f"Market announced: groups sent={g_sent} failed={g_failed}; "
            f"users sent={u_sent} failed={u_failed}."
        ))
