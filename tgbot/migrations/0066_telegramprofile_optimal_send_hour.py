from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0065_book_quiz_board'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramprofile',
            name='optimal_send_hour',
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                help_text=(
                    'Hour (0-23, Tashkent time) when this user is most likely to submit a report. '
                    'Computed from their ConfirmationReport history by compute_optimal_send_hours. '
                    'NULL = not enough data yet; falls back to fixed broadcast slots.'
                ),
            ),
        ),
    ]
