from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0046_delete_groups_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramprofile",
            name="reminder_count",
            field=models.PositiveSmallIntegerField(
                default=3,
                help_text="Daily inspirational reminders this user wants. 0=off, max=3.",
                verbose_name="Daily reminders",
            ),
        ),
        migrations.CreateModel(
            name="ScheduledMessageDeletion",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chat_id", models.BigIntegerField(db_index=True)),
                ("message_id", models.BigIntegerField()),
                ("delete_at", models.DateTimeField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "scheduled_message_deletions",
                "ordering": ("delete_at",),
            },
        ),
    ]
