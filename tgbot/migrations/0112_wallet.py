# Hamyon (1 Nov 2026 launch) — 0112.
#
# Hand-written: makemigrations does not run in this environment (aiogram 2/3
# mismatch, see 0107), so the operations are copied from the model
# definitions.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0111_author_game'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramprofile',
            name='wallet_balance',
            field=models.PositiveIntegerField(default=0, help_text="Hamyon balansi, so'm. Faqat services/wallet orqali o'zgaradi."),
        ),
        migrations.AddField(
            model_name='telegramprofile',
            name='wallet_use_kitobcha',
            field=models.BooleanField(default=True, help_text="Kunlik to'lovning 30% gacha qismini Kitobcha bilan to'lash."),
        ),
        migrations.CreateModel(
            name='WalletTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('kind', models.CharField(choices=[('topup', "To'ldirish"), ('bonus', 'Bonus'), ('premium_conversion', 'Premium → hamyon'), ('report_fee', "Kunlik to'lov"), ('admin', 'Admin tuzatishi')], max_length=24)),
                ('delta', models.IntegerField(help_text="So'm: musbat — kirim, manfiy — chiqim.")),
                ('kitobcha', models.PositiveIntegerField(default=0, help_text="Kunlik to'lovning Kitobcha qismi.")),
                ('day', models.DateField(blank=True, help_text="Kunlik to'lov qaysi kun uchun.", null=True)),
                ('balance_after', models.PositiveIntegerField(default=0)),
                ('note', models.CharField(blank=True, default='', max_length=120)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wallet_transactions', to='tgbot.telegramprofile')),
            ],
            options={
                'verbose_name': 'Hamyon tranzaksiyasi',
                'verbose_name_plural': 'Hamyon tranzaksiyalari',
                'db_table': 'wallet_transactions',
                'ordering': ('-created_at',),
            },
        ),
        migrations.AddConstraint(
            model_name='wallettransaction',
            constraint=models.UniqueConstraint(condition=models.Q(('kind', 'report_fee')), fields=('user', 'day'), name='wallet_one_fee_per_day'),
        ),
        migrations.AddConstraint(
            model_name='wallettransaction',
            constraint=models.UniqueConstraint(condition=models.Q(('kind', 'bonus')), fields=('user',), name='wallet_one_launch_bonus'),
        ),
        migrations.AddConstraint(
            model_name='wallettransaction',
            constraint=models.UniqueConstraint(condition=models.Q(('kind', 'premium_conversion')), fields=('user',), name='wallet_one_premium_conversion'),
        ),
        migrations.CreateModel(
            name='WalletTopup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('amount', models.PositiveIntegerField(help_text="So'm.")),
                ('status', models.CharField(choices=[('pending', 'Kutilmoqda'), ('approved', 'Tasdiqlangan'), ('rejected', 'Rad etilgan')], default='pending', max_length=10)),
                ('photo_file_id', models.CharField(blank=True, default='', max_length=255)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('reject_reason', models.TextField(blank=True, default='')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_wallet_topups', to='tgbot.telegramprofile')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wallet_topups', to='tgbot.telegramprofile')),
            ],
            options={
                'verbose_name': "Hamyonni to'ldirish",
                'verbose_name_plural': "Hamyonni to'ldirishlar",
                'db_table': 'wallet_topups',
                'ordering': ('-created_at',),
            },
        ),
    ]
