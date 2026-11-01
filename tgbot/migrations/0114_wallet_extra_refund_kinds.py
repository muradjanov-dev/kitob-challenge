from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0113_wallet_member_until'),
    ]

    operations = [
        migrations.AlterField(
            model_name='wallettransaction',
            name='kind',
            field=models.CharField(choices=[
                ('topup', "To'ldirish"), ('bonus', 'Bonus'),
                ('premium_conversion', 'Premium → hamyon'), ('report_fee', "Kunlik to'lov"),
                ('report_extra', "Qo'shimcha hisobot"), ('refund', 'Qaytarildi'),
                ('admin', 'Admin tuzatishi'),
            ], max_length=24),
        ),
    ]
