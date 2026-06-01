from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Launch a 3-day Referral BOOM immediately: finalize any running boom, "
        "create a fresh one and announce it to all groups + users."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3)
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
        from tgbot.tasks import launch_referral_boom
        boom_id = launch_referral_boom(
            days=opts["days"],
            tier1_reward=opts["tier1"],
            tier1_cap=opts["cap"],
            tier2_reward=opts["tier2"],
            total_reminders=opts["reminders"],
            title=opts["title"],
        )
        self.stdout.write(self.style.SUCCESS(f"Referral BOOM launched — boom_id={boom_id}"))
