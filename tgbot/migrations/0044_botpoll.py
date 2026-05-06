from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0043_scheduledreminder"),
    ]

    operations = [
        migrations.CreateModel(
            name="BotPoll",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated at")),
                ("question", models.TextField()),
                ("options", models.JSONField(default=list)),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="polls_created",
                    to="tgbot.telegramprofile",
                )),
            ],
            options={
                "db_table": "bot_polls",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="BotPollVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated at")),
                ("option_index", models.PositiveSmallIntegerField()),
                ("poll", models.ForeignKey(
                    on_delete=models.deletion.CASCADE,
                    related_name="votes",
                    to="tgbot.botpoll",
                )),
                ("user", models.ForeignKey(
                    on_delete=models.deletion.CASCADE,
                    to="tgbot.telegramprofile",
                )),
            ],
            options={
                "db_table": "bot_poll_votes",
                "ordering": ("-created_at",),
                "unique_together": {("poll", "user")},
            },
        ),
    ]
