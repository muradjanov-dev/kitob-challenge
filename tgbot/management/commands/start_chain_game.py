from django.core.management.base import BaseCommand

from tgbot.tasks import start_chain_game


class Command(BaseCommand):
    help = "Start a live Kitob Zanjiri game now and announce it to the groups."

    def handle(self, *args, **options):
        start_chain_game()
        self.stdout.write(self.style.SUCCESS("✅ Kitob Zanjiri boshlandi."))
