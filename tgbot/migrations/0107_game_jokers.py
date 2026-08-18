# O'yinlarda yordam (jokerlar) tizimi — 0107.
#
# Qo'lda yozilgan: bu muhitda `makemigrations` aiogram 2/3 nomuvofiqligi
# sababli ishga tushmaydi (tgbot.urls -> bot handlerlarini import qiladi),
# shuning uchun operatsiyalar model ta'riflaridan aynan ko'chirilgan.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0106_add_profile_theme_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='quizanswer',
            name='shielded',
            field=models.BooleanField(
                default=False,
                help_text='Javob xato edi, lekin 🛡 Qalqon jokeri uni kechirdi — ochko berildi.',
            ),
        ),
        migrations.CreateModel(
            name='GameJoker',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('game_type', models.CharField(help_text="'quiz' yoki 'survival'.", max_length=12)),
                ('game_id', models.PositiveIntegerField(help_text="QuizGame yoki SurvivalGame id — game_type bo'yicha.")),
                ('flavor', models.CharField(blank=True, default='', help_text='Quiz uchun flavor.', max_length=24)),
                ('q_index', models.SmallIntegerField(help_text='Joker sotib olingan savol raqami (0 dan).')),
                ('kind', models.CharField(choices=[('fifty', '50/50'), ('shield', "Qalqon / Qo'shimcha jon"), ('sniper', 'Snayper')], max_length=10)),
                ('price', models.PositiveIntegerField(default=0, help_text='Yechib olingan Kitobcha.')),
                ('payload', models.JSONField(blank=True, default=dict, help_text='50/50 uchun {"hidden": [i, j]}.')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='game_jokers', to='tgbot.telegramprofile')),
            ],
            options={
                'verbose_name': "O'yin jokeri",
                'verbose_name_plural': "O'yin jokerlari",
                'db_table': 'game_jokers',
                'ordering': ('-created_at',),
                'unique_together': {('user', 'game_type', 'game_id', 'q_index', 'kind')},
            },
        ),
    ]
