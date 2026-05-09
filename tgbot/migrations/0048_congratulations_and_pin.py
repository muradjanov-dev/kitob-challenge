from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0047_reminders_and_msg_deletion"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramprofile",
            name="last_progress_msg_id",
            field=models.BigIntegerField(
                blank=True, null=True,
                help_text="Most recent pinned daily-progress message id, used to repin/restore.",
            ),
        ),
        migrations.AddField(
            model_name="telegramprofile",
            name="show_calendar",
            field=models.BooleanField(
                default=False,
                help_text="When True, the cabinet shows a clickable streak calendar.",
            ),
        ),
        migrations.AddField(
            model_name="telegramprofile",
            name="accept_congrats_from",
            field=models.CharField(
                default="any",
                max_length=10,
                choices=[("any", "Hammadan"), ("male", "Erkaklardan"), ("female", "Ayollardan")],
                help_text="Whose congratulations the user accepts.",
            ),
        ),
        migrations.AddField(
            model_name="telegramprofile",
            name="send_congrats_to",
            field=models.CharField(
                default="any",
                max_length=10,
                choices=[("any", "Hammaga"), ("male", "Erkaklarga"), ("female", "Ayollarga")],
                help_text="Whom the user is willing to congratulate.",
            ),
        ),
        migrations.CreateModel(
            name="Congratulation",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("achievement", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="congratulations",
                    to="tgbot.userachievement",
                )),
                ("congratulator", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="congratulations_sent",
                    to="tgbot.telegramprofile",
                )),
            ],
            options={
                "db_table": "congratulations",
                "ordering": ("-created_at",),
                "unique_together": {("achievement", "congratulator")},
            },
        ),
    ]
