"""An auction switched off or deleted before it settles hands every bid back.

settle_finished_auctions only looks at active auctions, so an auction an admin
pauses (bot "⏸ O'chirish", the Django admin checkbox) or deletes (the bids go
with it) would otherwise keep the readers' Kitobcha for good. Settled means
the prize went out: a ShopPurchase (book) or an AdCampaign (ad slot) exists,
and settling refunds the losers itself.
"""
from django.db.models import F
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from tgbot.models import AdCampaign, KitobchaLedger, ShopAuctionBid, ShopProduct, ShopPurchase, TelegramProfile


def is_settled(product) -> bool:
    return (ShopPurchase.objects.filter(product=product).exists()
            or AdCampaign.objects.filter(product=product).exists())


def refund_open_bids(product) -> int:
    """Give back every bid not yet refunded on an unsettled auction."""
    if not product.is_auction or is_settled(product):
        return 0
    import html
    import os

    import requests
    done = 0
    for bid in list(product.auction_bids.filter(is_refunded=False).select_related("user")):
        # Claim the bid first: a second caller finds nothing to update.
        if not ShopAuctionBid.objects.filter(id=bid.id, is_refunded=False).update(is_refunded=True):
            continue
        TelegramProfile.objects.filter(id=bid.user_id).update(ball=F("ball") + bid.amount)
        KitobchaLedger.objects.create(user_id=bid.user_id, delta=bid.amount,
                                      reason=f"auction_refund:{product.id}")
        done += 1
        try:
            requests.post(
                f"https://api.telegram.org/bot{os.environ.get('API_TOKEN', '')}/sendMessage",
                data={"chat_id": bid.user.telegram_id, "parse_mode": "HTML", "text": (
                    f"ℹ️ <b>{html.escape(product.name, quote=False)}</b> auksioni bekor qilindi.\n\n"
                    f"Tikkan <b>{bid.amount} Kitobchangiz</b> to'liq qaytarildi 🪙"
                )}, timeout=5,
            )
        except Exception as e:
            print(f"refund_open_bids notify {bid.user_id}: {e}")
    return done


@receiver(pre_save, sender=ShopProduct)
def _note_switch_off(sender, instance, **kwargs):
    instance._auction_switched_off = bool(
        instance.pk and instance.is_auction and not instance.is_active
        and ShopProduct.objects.filter(pk=instance.pk, is_active=True).exists())


@receiver(post_save, sender=ShopProduct)
def _refund_on_switch_off(sender, instance, **kwargs):
    if getattr(instance, "_auction_switched_off", False):
        instance._auction_switched_off = False
        try:
            refund_open_bids(instance)
        except Exception as e:
            print(f"refund_open_bids {instance.pk}: {e}")


@receiver(pre_delete, sender=ShopProduct)
def _refund_on_delete(sender, instance, **kwargs):
    try:
        refund_open_bids(instance)
    except Exception as e:
        print(f"refund_open_bids {instance.pk}: {e}")
