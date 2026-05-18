from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0055_telegramprofile_pending_referral_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramprofile',
            name='tabriklar_range',
            field=models.CharField(
                max_length=10,
                default='any',
                choices=[
                    ('any', 'Hammasi'),
                    ('3-10', '3-10 yutuq'),
                    ('11-20', '11-20 yutuq'),
                    ('21-40', '21-40 yutuq'),
                    ('41+', '41+ yutuq'),
                ],
                help_text=(
                    "Filter Tabriklash DMs by the achiever's total achievement "
                    "count. 'any' = receive all (default)."
                ),
            ),
        ),
    ]
