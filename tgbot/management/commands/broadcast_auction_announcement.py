from django.core.management.base import BaseCommand
from tgbot.services.auction_announce import broadcast_auction_announcement


class Command(BaseCommand):
    help = "Broadcast the 10-day Shop Auction announcement to all groups and users with interactive inline buttons."

    def handle(self, *args, **options):
        self.stdout.write("Starting auction announcement broadcast...")
        res = broadcast_auction_announcement()
        self.stdout.write(self.style.SUCCESS(
            f"Done! Sent to {res.get('groups_sent', 0)} groups and {res.get('users_sent', 0)} users."
        ))
