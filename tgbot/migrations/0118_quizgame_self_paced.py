from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0117_kitobcha_uses"),
    ]

    operations = [
        migrations.AddField(
            model_name="quizgame",
            name="self_paced",
            field=models.BooleanField(default=False),
        ),
    ]
