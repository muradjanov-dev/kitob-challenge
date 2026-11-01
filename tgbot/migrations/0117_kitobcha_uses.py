from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0116_wallet_cashback'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramprofile',
            name='report_frame',
            field=models.CharField(blank=True, default='', max_length=20,
                                   help_text='Guruhdagi hisobot posti ramkasi (kitobcha_uses.FRAMES).'),
        ),
        migrations.AddField(
            model_name='telegramprofile',
            name='report_frame_until',
            field=models.DateField(blank=True, null=True, help_text='Ramka shu kungacha faol.'),
        ),
        migrations.AddField(
            model_name='telegramprofile',
            name='mentor_days_given',
            field=models.PositiveIntegerField(default=0,
                                              help_text="Ustoz sifatida yangilarga to'lagan hisobot kunlari."),
        ),
        migrations.AddField(
            model_name='telegramprofile',
            name='honor_wall_at',
            field=models.DateTimeField(blank=True, null=True,
                                       help_text='«Hurmatli kitobxonlar devori»ga yozilgan vaqt.'),
        ),
        migrations.AlterField(
            model_name='wallettransaction',
            name='kind',
            field=models.CharField(choices=[
                ('topup', "To'ldirish"), ('bonus', 'Bonus'),
                ('premium_conversion', 'Premium → hamyon'), ('report_fee', "Kunlik to'lov"),
                ('report_extra', "Qo'shimcha hisobot"), ('refund', 'Qaytarildi'),
                ('referral', 'Referal mukofoti'), ('cashback', 'Kitob hamyonchasidan'),
                ('mentor', "Ustoz sovg'asi"), ('admin', 'Admin tuzatishi'),
            ], max_length=24),
        ),
    ]
