from django.db import migrations, models


def cashback_for_earlier_topups(apps, schema_editor):
    """Top-ups approved before the cashback existed earn it too (1%)."""
    from django.db.models import Sum
    WalletTopup = apps.get_model("tgbot", "WalletTopup")
    TelegramProfile = apps.get_model("tgbot", "TelegramProfile")
    rows = (WalletTopup.objects.filter(status="approved").values("user_id")
            .annotate(s=Sum("amount")).values_list("user_id", "s"))
    for user_id, total in rows:
        TelegramProfile.objects.filter(id=user_id).update(cashback_balance=int(total or 0) // 100)


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0115_wallet_referral_kind'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramprofile',
            name='cashback_balance',
            field=models.PositiveIntegerField(
                default=0,
                help_text="Kitob hamyonchasi, so'm: har to'ldirishning 1% keshbegi. 50 000 ga "
                          "yetganda butunlay asosiy hamyonga o'tadi (services/wallet).",
            ),
        ),
        migrations.AlterField(
            model_name='wallettransaction',
            name='kind',
            field=models.CharField(choices=[
                ('topup', "To'ldirish"), ('bonus', 'Bonus'),
                ('premium_conversion', 'Premium → hamyon'), ('report_fee', "Kunlik to'lov"),
                ('report_extra', "Qo'shimcha hisobot"), ('refund', 'Qaytarildi'),
                ('referral', 'Referal mukofoti'), ('cashback', 'Kitob hamyonchasidan'),
                ('admin', 'Admin tuzatishi'),
            ], max_length=24),
        ),
        migrations.RunPython(cashback_for_earlier_topups, migrations.RunPython.noop),
    ]
