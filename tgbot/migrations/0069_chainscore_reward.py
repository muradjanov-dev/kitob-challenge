from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0068_seed_chain_words'),
    ]

    operations = [
        migrations.AddField(
            model_name='chainscore',
            name='reward',
            field=models.PositiveIntegerField(default=0, help_text='Kitobcha paid at finish.'),
        ),
    ]
