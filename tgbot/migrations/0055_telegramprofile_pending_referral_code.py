from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0054_confirmation_report_group_meta'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramprofile',
            name='pending_referral_code',
            field=models.CharField(
                blank=True, db_index=True, max_length=20, null=True,
                help_text=(
                    "The referral code that brought this user in. Counted only "
                    "after their first ConfirmationReport, then cleared."
                ),
            ),
        ),
    ]
