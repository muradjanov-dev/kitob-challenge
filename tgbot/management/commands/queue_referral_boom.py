from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Queue a Referral BOOM for the NEXT regular 3-day challenge rotation. "
        "The rotation runs it for one slot, then resumes the normal pool. "
        "Idempotent — re-running updates the queued boom instead of duplicating."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tier1", type=int, default=150,
                            help="Kitobcha per referral for the first --cap referrals.")
        parser.add_argument("--cap", type=int, default=10,
                            help="Referrals up to this count earn tier1; beyond earns tier2.")
        parser.add_argument("--tier2", type=int, default=300,
                            help="Kitobcha per referral beyond --cap.")
        parser.add_argument("--reminders", type=int, default=21,
                            help="Playful reminders per participant across the window.")
        parser.add_argument("--title", type=str, default=None)

    def handle(self, *args, **opts):
        from tgbot.tasks import queue_referral_boom
        boom_id = queue_referral_boom(
            tier1_reward=opts["tier1"],
            tier1_cap=opts["cap"],
            tier2_reward=opts["tier2"],
            total_reminders=opts["reminders"],
            title=opts["title"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Referral BOOM queued for the next rotation — boom_id={boom_id}"
        ))
