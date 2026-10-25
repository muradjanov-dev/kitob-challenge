# Muallif bo'lib ko'r — 0111.
#
# Hand-written: makemigrations does not run in this environment (aiogram 2/3
# mismatch, see 0107), so the operations are copied from the model
# definitions.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0110_hide_premium_shop_products'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthorGame',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('status', models.CharField(choices=[('scheduled', 'Rejalashtirilgan'), ('live', 'Jonli'), ('finished', 'Tugagan')], default='scheduled', max_length=12)),
                ('starts_at', models.DateTimeField()),
                ('writing_ends_at', models.DateTimeField()),
                ('ends_at', models.DateTimeField(help_text='End of the voting window.')),
                ('prompt', models.JSONField(default=dict, help_text='{"key","book","author","scene","task"}')),
                ('rewarded', models.BooleanField(default=False)),
            ],
            options={
                'verbose_name': "Muallif bo'lib ko'r — O'yin",
                'verbose_name_plural': "Muallif bo'lib ko'r — O'yinlar",
                'db_table': 'author_games',
                'ordering': ('-starts_at',),
            },
        ),
        migrations.CreateModel(
            name='AuthorEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('text', models.TextField()),
                ('votes', models.PositiveIntegerField(default=0)),
                ('reward', models.PositiveIntegerField(default=0)),
                ('rewarded', models.BooleanField(default=False)),
                ('hidden', models.BooleanField(default=False, help_text='Hidden by an admin: kept out of voting and prizes.')),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='tgbot.authorgame')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='author_entries', to='tgbot.telegramprofile')),
            ],
            options={
                'verbose_name': "Muallif bo'lib ko'r — Yozuv",
                'verbose_name_plural': "Muallif bo'lib ko'r — Yozuvlar",
                'db_table': 'author_entries',
                'ordering': ('-votes', 'created_at'),
                'unique_together': {('game', 'user')},
            },
        ),
        migrations.CreateModel(
            name='AuthorVote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('entry', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='vote_rows', to='tgbot.authorentry')),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='votes', to='tgbot.authorgame')),
                ('voter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='author_votes', to='tgbot.telegramprofile')),
            ],
            options={
                'db_table': 'author_votes',
                'unique_together': {('voter', 'entry')},
            },
        ),
    ]
