from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Announce a challenge immediately if no active challenge exists (run once on deploy)."

    def handle(self, *args, **options):
        from tgbot.models import Challenge, ReferralBoom
        if Challenge.objects.filter(is_active=True).exists():
            self.stdout.write("Active challenge already exists — skipping.")
            return
        if ReferralBoom.objects.filter(is_active=True).exists():
            self.stdout.write("A Referral BOOM is live — it owns the featured slot, skipping.")
            return
        self.stdout.write("No active challenge found — announcing now...")
        from tgbot.tasks import announce_challenge
        announce_challenge()
        self.stdout.write("Challenge announced.")
