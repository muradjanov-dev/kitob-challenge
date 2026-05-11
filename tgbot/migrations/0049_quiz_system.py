from django.db import migrations, models
import django.db.models.deletion
import tgbot.models


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0048_congratulations_and_pin"),
    ]

    operations = [
        migrations.CreateModel(
            name="Quiz",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("time_per_question", models.IntegerField(default=30)),
                ("shuffle", models.BooleanField(default=True)),
                ("link_code", models.CharField(default=tgbot.models._quiz_code, max_length=16, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("creator", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="quizzes",
                    to="tgbot.telegramprofile",
                )),
            ],
            options={"db_table": "quizzes", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="QuizQuestion",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField()),
                ("hint", models.TextField(blank=True)),
                ("order", models.IntegerField(default=0)),
                ("quiz", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="questions",
                    to="tgbot.quiz",
                )),
            ],
            options={"db_table": "quiz_questions", "ordering": ("order",)},
        ),
        migrations.CreateModel(
            name="QuizOption",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.CharField(max_length=500)),
                ("is_correct", models.BooleanField(default=False)),
                ("order", models.IntegerField(default=0)),
                ("question", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="options",
                    to="tgbot.quizquestion",
                )),
            ],
            options={"db_table": "quiz_options", "ordering": ("order",)},
        ),
        migrations.CreateModel(
            name="QuizSession",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chat_id", models.BigIntegerField(db_index=True)),
                ("join_message_id", models.BigIntegerField(blank=True, null=True)),
                ("status", models.CharField(default="waiting", max_length=20)),
                ("scheduled_start", models.DateTimeField(blank=True, null=True)),
                ("current_question_idx", models.IntegerField(default=0)),
                ("question_order", models.TextField(default="[]")),
                ("is_group", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("creator", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="quiz_sessions_led",
                    to="tgbot.telegramprofile",
                )),
                ("quiz", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="sessions",
                    to="tgbot.quiz",
                )),
            ],
            options={"db_table": "quiz_sessions"},
        ),
        migrations.CreateModel(
            name="QuizParticipant",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("score", models.IntegerField(default=0)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("session", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="participants",
                    to="tgbot.quizsession",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="quiz_participations",
                    to="tgbot.telegramprofile",
                )),
            ],
            options={
                "db_table": "quiz_participants",
                "unique_together": {("session", "user")},
            },
        ),
        migrations.CreateModel(
            name="QuizUserAnswer",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_correct", models.BooleanField(default=False)),
                ("answered_at", models.DateTimeField(auto_now_add=True)),
                ("option", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to="tgbot.quizoption",
                )),
                ("participant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="answers",
                    to="tgbot.quizparticipant",
                )),
                ("question", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="user_answers",
                    to="tgbot.quizquestion",
                )),
            ],
            options={
                "db_table": "quiz_user_answers",
                "unique_together": {("participant", "question")},
            },
        ),
    ]
