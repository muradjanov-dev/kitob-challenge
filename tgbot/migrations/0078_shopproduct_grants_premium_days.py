# Generated manually (aiogram 2/3 mismatch blocks makemigrations locally —
# see feedback_makemigrations_stray_id_alters memory).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0077_alter_castlegame_id_alter_castlehit_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='shopproduct',
            name='grants_premium_days',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text=(
                    "If set, buying this product automatically grants/extends "
                    "this many days of bot Premium (e.g. 30 for a 1-month "
                    "Kitob Challenge Premium item) and the purchase is "
                    "auto-fulfilled — no manual pickup needed. Leave blank for "
                    "ordinary prizes that still need manual hand-off (e.g. a "
                    "3rd-party 'Mutolaa Premium' code)."
                ),
            ),
        ),
    ]
