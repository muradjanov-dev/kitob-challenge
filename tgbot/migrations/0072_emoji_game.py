from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0071_chainscore_strikes'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmojiGame',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('title', models.CharField(default='Emoji Kitob', max_length=120)),
                ('status', models.CharField(choices=[('scheduled', 'Rejalashtirilgan'), ('live', 'Jonli'), ('finished', 'Tugagan')], default='scheduled', max_length=12)),
                ('starts_at', models.DateTimeField()),
                ('ends_at', models.DateTimeField()),
                ('questions', models.JSONField(default=list, help_text='[{"emoji","options":[4],"correct":idx}]')),
                ('answer_seconds', models.PositiveIntegerField(default=15)),
                ('reveal_seconds', models.PositiveIntegerField(default=5)),
                ('scored_indices', models.JSONField(default=list)),
                ('rewarded', models.BooleanField(default=False)),
            ],
            options={'verbose_name': "Emoji Kitob — O'yin", 'verbose_name_plural': "Emoji Kitob — O'yinlar", 'db_table': 'emoji_games', 'ordering': ('-starts_at',)},
        ),
        migrations.CreateModel(
            name='EmojiAnswer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('q_index', models.PositiveSmallIntegerField()),
                ('choice', models.PositiveSmallIntegerField()),
                ('is_correct', models.BooleanField(default=False)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='tgbot.emojigame')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='emoji_answers', to='tgbot.telegramprofile')),
            ],
            options={'db_table': 'emoji_answers', 'ordering': ('created_at',), 'unique_together': {('game', 'user', 'q_index')}},
        ),
        migrations.CreateModel(
            name='EmojiScore',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('points', models.PositiveIntegerField(default=0)),
                ('reward', models.PositiveIntegerField(default=0)),
                ('rewarded', models.BooleanField(default=False)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scores', to='tgbot.emojigame')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='emoji_scores', to='tgbot.telegramprofile')),
            ],
            options={'db_table': 'emoji_scores', 'ordering': ('-points', 'created_at'), 'unique_together': {('game', 'user')}},
        ),
    ]
