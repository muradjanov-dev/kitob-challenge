from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0051_audiokitob_support'),
    ]

    operations = [
        migrations.AddField(
            model_name='bookstoread',
            name='is_audio',
            field=models.BooleanField(default=False),
        ),
    ]
