from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0044_botpoll"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserAchievement",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated at")),
                ("code", models.CharField(max_length=64)),
                ("awarded_at", models.DateTimeField(auto_now_add=True)),
                ("congratulated", models.BooleanField(default=False, help_text="True once the Tabriklash broadcast has been sent.")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="achievements", to="tgbot.telegramprofile")),
            ],
            options={
                "db_table": "user_achievements",
                "ordering": ("-awarded_at",),
                "unique_together": {("user", "code")},
            },
        ),
    ]
