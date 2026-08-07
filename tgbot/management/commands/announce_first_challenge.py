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
        self.stdout.write("No active challenge found — dispatching announcement to Celery...")
        from tgbot.tasks import announce_challenge
        # This command runs synchronously in the web container's boot
        # sequence, before gunicorn starts (see Procfile). announce_challenge()
        # itself creates the Challenge fast, but then DMs every registered
        # user one at a time with a rate-limit sleep between each -- at
        # today's user count that's tens of minutes. Called inline, that
        # blocked gunicorn from ever binding to the port, taking the entire
        # site down (502s) for the whole broadcast. .delay() hands it to the
        # Celery worker instead, so a deploy that happens to land exactly
        # when a challenge is due can never repeat that outage.
        announce_challenge.delay()
        self.stdout.write("Challenge announcement dispatched.")
