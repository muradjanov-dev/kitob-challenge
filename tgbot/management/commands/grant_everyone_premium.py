from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Founder's gift: grant every registered user Premium for N days and "
        "announce it to all groups + users. Default 1 day (~24h)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=1)
        parser.add_argument("--no-announce", action="store_true",
                            help="Grant premium silently, without broadcasting.")

    def handle(self, *args, **opts):
        from tgbot.tasks import grant_everyone_premium
        granted = grant_everyone_premium(
            days=opts["days"], announce=not opts["no_announce"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Granted {opts['days']}-day premium to {granted} users."
        ))
