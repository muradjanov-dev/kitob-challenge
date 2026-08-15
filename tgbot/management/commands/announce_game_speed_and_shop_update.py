from django.core.management.base import BaseCommand
from tgbot.services.update_announce import broadcast_update_announcement


class Command(BaseCommand):
    help = "Broadcast Game Speed Ranking, Shop Fix, and 3D Reader update to all groups and users."

    def handle(self, *args, **options):
        self.stdout.write("Broadcasting update announcement...")
        res = broadcast_update_announcement()
        self.stdout.write(self.style.SUCCESS(f"Broadcast complete: {res}"))
