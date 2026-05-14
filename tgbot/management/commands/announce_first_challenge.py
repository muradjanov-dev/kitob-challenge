from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Announce a challenge immediately if no active challenge exists (run once on deploy)."

    def handle(self, *args, **options):
        from tgbot.models import Challenge
        if Challenge.objects.filter(is_active=True).exists():
            self.stdout.write("Active challenge already exists — skipping.")
            return
        self.stdout.write("No active challenge found — announcing now...")
        from tgbot.tasks import announce_challenge
        announce_challenge()
        self.stdout.write("Challenge announced.")
