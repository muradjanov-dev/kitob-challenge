import time
from django.core.management.base import BaseCommand

from bot.models import TelegramProfile as User
from utils.bot import send_message


class Command(BaseCommand):
    help = 'Send Notifications'

    def add_arguments(self, parser):
        # Adding argument to specify the classroom
        parser.add_argument(
            '--classroom',
            nargs='+',
            type=str,
            help='Specify the classrooms to send notifications to',
            default=["10-sinf", "11-sinf"]
        )
        # Adding argument to specify the registration status
        parser.add_argument(
            '--not_registered',
            type=bool,
            help='Specify the not completed registration status to filter users',
            default=False
        )

    def handle(self, *args, **options):
        classrooms = options['classroom']
        not_registered = options['not_registered']
        text = ("Kelajak yoshlari Olimpiadasi bugun 23:59 gacha ochiq! Agar siz haliham test yechmagan bo'lsangiz, "
                "/start ni bosing va 🏆Olimpiadalar🏆 bo'limidan test topshiring va sovg'alaringizni yutib oling! "
                "Murojaat: @roboteachhelp")
        success_count = failed_count = 0
        users = User.objects.filter(class_room__in=classrooms)
        if not_registered:
            text = ("Barcha 🏆 Olimpiadada qatnashib, test yechib, 🎁 sovrinlar yutayapti? Sizchi, haliham "
                    "ro'yxatdan o'tmadingizmi? 🏁 /start ni bosing, ro'yxatdan o'ting va 🏆sovrinlarni qo'lga kiriting. "
                    "Murojaat: @roboteachhelp")
            users = User.objects.filter(is_registered=False)
        self.stdout.write(self.style.SUCCESS("Xabar yuborish boshlandi"))
        for user in users:
            response = send_message(chat_id=user.telegram_id, text=text)
            if response.status_code == 200:
                success_count += 1
            else:
                failed_count += 1
            time.sleep(0.05)
        self.stdout.write(self.style.SUCCESS(
            f"Muvaffaqiyatli yuborilganlar: {success_count} ta\n\nYubora olmaganlar: {failed_count} ta"))
