from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0058_backfill_global_books'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramprofile',
            name='congrats_dm_count',
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    "Number of Tabriklash DMs this user has received; used to "
                    "surface the reminder-config button on every 10th one."
                ),
            ),
        ),
    ]
