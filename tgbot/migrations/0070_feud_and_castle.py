from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0069_chainscore_reward'),
    ]

    operations = [
        migrations.CreateModel(
            name='FeudGame',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('title', models.CharField(default="Ko'pchilik nima dedi?", max_length=120)),
                ('status', models.CharField(choices=[('scheduled', 'Rejalashtirilgan'), ('live', 'Jonli'), ('finished', 'Tugagan')], default='scheduled', max_length=12)),
                ('starts_at', models.DateTimeField()),
                ('ends_at', models.DateTimeField()),
                ('questions', models.JSONField(default=list, help_text='List of question strings.')),
                ('answer_seconds', models.PositiveIntegerField(default=25)),
                ('reveal_seconds', models.PositiveIntegerField(default=8)),
                ('scored_indices', models.JSONField(default=list, help_text='Questions already scored.')),
                ('rewarded', models.BooleanField(default=False)),
            ],
            options={'verbose_name': "Ko'pchilik — O'yin", 'verbose_name_plural': "Ko'pchilik — O'yinlar", 'db_table': 'feud_games', 'ordering': ('-starts_at',)},
        ),
        migrations.CreateModel(
            name='FeudAnswer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('q_index', models.PositiveSmallIntegerField()),
                ('text', models.CharField(max_length=120)),
                ('norm', models.CharField(db_index=True, max_length=120)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='tgbot.feudgame')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feud_answers', to='tgbot.telegramprofile')),
            ],
            options={'db_table': 'feud_answers', 'ordering': ('created_at',), 'unique_together': {('game', 'user', 'q_index')}},
        ),
        migrations.CreateModel(
            name='FeudScore',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('points', models.PositiveIntegerField(default=0)),
                ('reward', models.PositiveIntegerField(default=0)),
                ('rewarded', models.BooleanField(default=False)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scores', to='tgbot.feudgame')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feud_scores', to='tgbot.telegramprofile')),
            ],
            options={'db_table': 'feud_scores', 'ordering': ('-points', 'created_at'), 'unique_together': {('game', 'user')}},
        ),
        migrations.CreateModel(
            name='CastleGame',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('title', models.CharField(default="Bilim Qal'asi", max_length=120)),
                ('status', models.CharField(choices=[('scheduled', 'Rejalashtirilgan'), ('live', 'Jonli'), ('finished', 'Tugagan')], default='scheduled', max_length=12)),
                ('starts_at', models.DateTimeField()),
                ('ends_at', models.DateTimeField()),
                ('boss_name', models.CharField(default='Bilim Ajdari', max_length=60)),
                ('boss_hp_max', models.PositiveIntegerField(default=300)),
                ('boss_hp', models.PositiveIntegerField(default=300)),
                ('damage_per_hit', models.PositiveIntegerField(default=10)),
                ('questions', models.JSONField(default=list, help_text='[{"q","options":[4],"correct":idx}]')),
                ('question_seconds', models.PositiveIntegerField(default=20)),
                ('victory', models.BooleanField(default=False)),
                ('rewarded', models.BooleanField(default=False)),
            ],
            options={'verbose_name': "Bilim Qal'asi — O'yin", 'verbose_name_plural': "Bilim Qal'asi — O'yinlar", 'db_table': 'castle_games', 'ordering': ('-starts_at',)},
        ),
        migrations.CreateModel(
            name='CastleHit',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('q_index', models.PositiveSmallIntegerField()),
                ('is_correct', models.BooleanField(default=False)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hits', to='tgbot.castlegame')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='castle_hits', to='tgbot.telegramprofile')),
            ],
            options={'db_table': 'castle_hits', 'ordering': ('created_at',), 'unique_together': {('game', 'user', 'q_index')}},
        ),
    ]
