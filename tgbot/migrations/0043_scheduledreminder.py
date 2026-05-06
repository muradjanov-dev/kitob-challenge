from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0042_add_toshkent_viloyati"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScheduledReminder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated at")),
                ("text", models.TextField(verbose_name="Reminder text")),
                ("hour", models.PositiveSmallIntegerField(verbose_name="Hour (0-23)")),
                ("minute", models.PositiveSmallIntegerField(verbose_name="Minute (0-59)")),
                ("is_active", models.BooleanField(default=True, verbose_name="Active")),
                ("created_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="reminders_created",
                    to="tgbot.telegramprofile",
                )),
            ],
            options={
                "verbose_name": "Scheduled Reminder",
                "verbose_name_plural": "Scheduled Reminders",
                "db_table": "scheduled_reminders",
                "ordering": ("hour", "minute", "id"),
            },
        ),
    ]
