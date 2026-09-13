"""Open the Kitobxonlar charity fund in the shop and announce it.

    python manage.py announce_charity_fund            # dry run: create/show fund, print the text
    python manage.py announce_charity_fund --send     # post to groups and DM every user
    python manage.py announce_charity_fund --send --groups-only
"""
from django.core.management.base import BaseCommand

from tgbot.models import CHARITY_MIN_CONTRIBUTION, ShopProduct, TelegramProfile

FUND_NAME = "💚 Kitobxonlar xayriya jamg'armasi"
FUND_DESCRIPTION = (
    "Istagancha Kitobcha qo'shing (kamida 100). Har 100.000 Kitobcha "
    "to'planganda loyiha Kitobxonlar nomidan 100.000 so'm xayriya qiladi yoki "
    "muhtoj insonga 100.000 so'mgacha qiymatdagi kitob olib beradi. Har bir "
    "xayriya hisoboti guruhlarda e'lon qilinadi."
)


class Command(BaseCommand):
    help = "Create the charity fund shop item (if missing) and announce it."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true", help="Actually send the announcement.")
        parser.add_argument("--groups-only", action="store_true", help="With --send: skip user DMs.")

    def handle(self, *args, **opts):
        from tgbot.services import charity
        from tgbot.tasks import charity_dm, charity_post_to_groups

        fund = ShopProduct.objects.filter(is_charity=True, is_active=True).first()
        if not fund:
            fund = ShopProduct.objects.create(
                name=FUND_NAME,
                description=FUND_DESCRIPTION,
                price_kitobcha=CHARITY_MIN_CONTRIBUTION,
                is_charity=True,
                charity_step=100_000,
                sort_order=-100,  # first card in the shop
                is_active=True,
            )
            self.stdout.write(self.style.SUCCESS(f"Created fund #{fund.id}"))
        else:
            self.stdout.write(f"Fund #{fund.id} already exists: {fund.name}")

        text = charity.launch_text()
        users = TelegramProfile.objects.filter(is_registered=True, is_blocked=False)
        self.stdout.write("\n" + text + "\n")
        self.stdout.write(f"Recipients: groups + {users.count()} users")

        if not opts["send"]:
            self.stdout.write(self.style.WARNING("Dry run -- nothing sent. Add --send to announce."))
            return

        groups = charity_post_to_groups(text)
        self.stdout.write(f"Groups: {groups}")
        if opts["groups_only"]:
            return
        ids = list(users.values_list("telegram_id", flat=True).distinct())
        sent = charity_dm(ids, lambda _tid: text)
        self.stdout.write(self.style.SUCCESS(f"DMs: {sent}/{len(ids)}"))
