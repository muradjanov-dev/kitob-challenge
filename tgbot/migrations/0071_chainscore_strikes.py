from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0070_feud_and_castle'),
    ]

    operations = [
        migrations.AddField(
            model_name='chainscore',
            name='strikes',
            field=models.PositiveIntegerField(
                default=0, help_text="How many of this user's links the crowd rejected."),
        ),
        migrations.AddField(
            model_name='chainscore',
            name='kicked',
            field=models.BooleanField(
                default=False, help_text='Removed from the game after 3 rejected links.'),
        ),
    ]
