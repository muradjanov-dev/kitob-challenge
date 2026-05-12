from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0049_quiz_system"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramprofile",
            name="contact_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Number of times the user has successfully messaged the admin.",
                verbose_name="Admin contact count",
            ),
        ),
    ]
