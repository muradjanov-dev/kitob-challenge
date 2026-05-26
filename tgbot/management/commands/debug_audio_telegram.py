"""
DB dagi audio hisobotlarni tekshirib natijani Telegram ga yuboradi.
Faqat Railway serverida ishlaydi (DB ga to'g'ri ulanadi).

Celery orqali ishga tushirish uchun mo'ljallangan:
    python manage.py debug_audio_telegram --tg-id 917456291
"""
import os
import requests
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Audio hisobotlarni DB dan tekshirib natijani Telegram ga yuboradi"

    def add_arguments(self, parser):
        parser.add_argument("--tg-id", type=int, required=True)

    def handle(self, *args, **options):
        from tgbot.models import ConfirmationReport, TelegramProfile
        from django.db.models import Sum

        tg_id = options["tg_id"]
        token = os.environ.get("API_TOKEN", "")
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        try:
            user = TelegramProfile.objects.get(telegram_id=tg_id)
        except TelegramProfile.DoesNotExist:
            self.stdout.write(f"User {tg_id} topilmadi")
            return

        all_r = ConfirmationReport.objects.filter(user=user)
        audio_r = all_r.filter(is_audio=True)
        text_r = all_r.filter(is_audio=False)

        total_min = audio_r.aggregate(t=Sum("minutes_listened"))["t"]
        total_pages = text_r.aggregate(t=Sum("pages_read"))["t"]

        lines = [
            f"<b>🔍 Debug: Audio hisobotlar</b>",
            f"User: {user.full_name} (tg_id={tg_id})",
            f"",
            f"Jami hisobotlar: <b>{all_r.count()}</b>",
            f"Audio hisobotlar: <b>{audio_r.count()}</b>",
            f"Oddiy hisobotlar: <b>{text_r.count()}</b>",
            f"",
            f"Jami minutes_listened (SUM): <b>{total_min}</b>",
            f"Jami pages_read (SUM, text): <b>{total_pages}</b>",
            f"",
            f"<b>So'nggi 8 ta hisobot:</b>",
        ]

        for r in all_r.order_by("-date")[:8]:
            lines.append(
                f"  id={r.id} | is_audio={r.is_audio} | "
                f"pages={r.pages_read} | min={r.minutes_listened} | "
                f"{r.date.strftime('%m-%d %H:%M')}"
            )

        text = "\n".join(lines)
        self.stdout.write(text.replace("<b>", "").replace("</b>", ""))

        if token:
            requests.post(
                url,
                data={"chat_id": tg_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            self.stdout.write("Telegram ga yuborildi.")
