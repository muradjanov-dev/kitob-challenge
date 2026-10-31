import datetime

from django.db import migrations, models
from django.utils import timezone


def keep_current_members(apps, schema_editor):
    """Perks move from "holds 15 000+ so'm" to a bought date (owner,
    2026-11-01). Nobody who has them today loses them: a reader already
    holding 15 000+ gets one perk day per 1 000 so'm held."""
    TelegramProfile = apps.get_model("tgbot", "TelegramProfile")
    yesterday = timezone.localdate() - datetime.timedelta(days=1)
    rows = (TelegramProfile.objects.filter(wallet_balance__gte=15000, wallet_member_until__isnull=True)
            .values_list("id", "wallet_balance"))
    for pid, balance in rows:
        TelegramProfile.objects.filter(id=pid).update(
            wallet_member_until=yesterday + datetime.timedelta(days=balance // 1000))


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0112_wallet'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramprofile',
            name='wallet_member_until',
            field=models.DateField(
                blank=True, null=True,
                help_text="Imtiyozlar shu kungacha (shu kun ham) faol. Bir martada 15 000 so'm va undan "
                          "ko'p to'ldirish har 1 000 so'm uchun 1 kun qo'shadi.",
            ),
        ),
        migrations.RunPython(keep_current_members, migrations.RunPython.noop),
    ]
