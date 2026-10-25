"""Take the two Premium subscriptions off the shop (owner's request, 2026-10-25).

Premium is being retired with the 1 November wallet launch. Products #30 and
#31 ("Kitob Challenge Premium (1 oylik)", 35 000 Kitobcha / 30 days) are the
two on sale; they are hidden, not deleted, so past purchases keep their
product. The name and grants_premium_days checks keep this from touching
anything else should the ids ever differ.
"""
from django.db import migrations

PREMIUM_PRODUCT_IDS = (30, 31)


def hide_premium_products(apps, schema_editor):
    ShopProduct = apps.get_model("tgbot", "ShopProduct")
    ShopProduct.objects.filter(
        id__in=PREMIUM_PRODUCT_IDS,
        name__icontains="premium",
        grants_premium_days__isnull=False,
    ).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0109_charity_mixed_payment"),
    ]

    operations = [
        migrations.RunPython(hide_premium_products, migrations.RunPython.noop),
    ]
