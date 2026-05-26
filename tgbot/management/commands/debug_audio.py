"""
python manage.py debug_audio --tg-id 917456291
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Audio hisobotlarni DB dan tekshirish"

    def add_arguments(self, parser):
        parser.add_argument("--tg-id", type=int, required=True)

    def handle(self, *args, **options):
        from tgbot.models import ConfirmationReport, TelegramProfile
        from django.db.models import Sum

        tg_id = options["tg_id"]
        try:
            user = TelegramProfile.objects.get(telegram_id=tg_id)
        except TelegramProfile.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User {tg_id} topilmadi"))
            return

        self.stdout.write(f"User: {user.full_name} (id={user.id})")

        all_r = ConfirmationReport.objects.filter(user=user)
        self.stdout.write(f"\nJami hisobotlar: {all_r.count()}")

        audio_r = all_r.filter(is_audio=True)
        self.stdout.write(f"Audio hisobotlar: {audio_r.count()}")

        text_r = all_r.filter(is_audio=False)
        self.stdout.write(f"Oddiy hisobotlar: {text_r.count()}")

        total_min = audio_r.aggregate(t=Sum("minutes_listened"))["t"]
        total_pages = text_r.aggregate(t=Sum("pages_read"))["t"]
        self.stdout.write(f"\nJami minutes_listened: {total_min}")
        self.stdout.write(f"Jami pages_read (text): {total_pages}")

        self.stdout.write("\nSo'nggi 5 ta hisobot:")
        for r in all_r.order_by("-date")[:5]:
            self.stdout.write(
                f"  id={r.id} | is_audio={r.is_audio} | "
                f"pages={r.pages_read} | minutes={r.minutes_listened} | "
                f"date={r.date.strftime('%Y-%m-%d %H:%M')}"
            )
