"""Real-time balance in the reader's pinned progress message, cheaply.

No polling: every wallet or Kitobcha move writes a ledger row
(WalletTransaction, KitobchaLedger). After its transaction commits, one
refresh is queued for that reader -- `pinbal:<id>` in the cache marks it
pending -- so a burst of moves (a report fee and its Kitobcha part, a game's
fee and prize) becomes a single editMessageText a few seconds later
(tasks.refresh_pinned_balance), and that one is skipped too when the shown
line would not change.
"""
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from tgbot.models import KitobchaLedger, WalletTransaction

DELAY_SECONDS = 8


def queue_refresh(user_id) -> None:
    if not user_id:
        return
    try:
        if cache.add(f"pinbal:{user_id}", 1, 120):
            from tgbot.tasks import refresh_pinned_balance
            refresh_pinned_balance.apply_async((user_id,), countdown=DELAY_SECONDS)
    except Exception as e:
        # A broker hiccup must never fail the report or payment behind it.
        print(f"pinned_balance queue {user_id}: {e}")


@receiver(post_save, sender=WalletTransaction)
@receiver(post_save, sender=KitobchaLedger)
def _on_balance_move(sender, instance, created, **kwargs):
    if created:
        user_id = instance.user_id
        transaction.on_commit(lambda: queue_refresh(user_id))
