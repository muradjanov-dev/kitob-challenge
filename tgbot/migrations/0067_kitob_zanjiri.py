from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0066_telegramprofile_optimal_send_hour'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChainWord',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('display', models.CharField(help_text='Shown to players.', max_length=200)),
                ('norm', models.CharField(
                    db_index=True, max_length=200, unique=True,
                    help_text='Normalized lookup/dedupe key (lowercase, unified apostrophes).',
                )),
                ('kind', models.CharField(
                    choices=[('book', 'Kitob'), ('author', 'Muallif')],
                    default='book', max_length=10,
                )),
                ('first_letter', models.CharField(db_index=True, default='', max_length=1)),
                ('last_letter', models.CharField(db_index=True, default='', max_length=1)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': "Kitob Zanjiri — So'z",
                'verbose_name_plural': "Kitob Zanjiri — Lug'at",
                'db_table': 'chain_words',
                'ordering': ('norm',),
            },
        ),
        migrations.CreateModel(
            name='ChainGame',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('title', models.CharField(default='Kitob Zanjiri', max_length=120)),
                ('status', models.CharField(
                    choices=[('scheduled', 'Rejalashtirilgan'), ('live', 'Jonli'), ('finished', 'Tugagan')],
                    default='scheduled', max_length=12,
                )),
                ('starts_at', models.DateTimeField()),
                ('ends_at', models.DateTimeField()),
                ('current_letter', models.CharField(default='', max_length=1)),
                ('chain', models.JSONField(
                    default=list,
                    help_text='Won links: [{"norm","display","user_id","name","letter","at"}].',
                )),
                ('used_norms', models.JSONField(
                    default=list, help_text='Normalized words already played (no repeats).',
                )),
                ('rewarded', models.BooleanField(default=False)),
            ],
            options={
                'verbose_name': "Kitob Zanjiri — O'yin",
                'verbose_name_plural': "Kitob Zanjiri — O'yinlar",
                'db_table': 'chain_games',
                'ordering': ('-starts_at',),
            },
        ),
        migrations.CreateModel(
            name='ChainScore',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('points', models.PositiveIntegerField(default=0)),
                ('links', models.PositiveIntegerField(default=0, help_text='Links this user won.')),
                ('rewarded', models.BooleanField(default=False)),
                ('game', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='scores', to='tgbot.chaingame',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='chain_scores', to='tgbot.telegramprofile',
                )),
            ],
            options={
                'verbose_name': "Kitob Zanjiri — Ball",
                'verbose_name_plural': "Kitob Zanjiri — Ballar",
                'db_table': 'chain_scores',
                'ordering': ('-points', 'created_at'),
                'unique_together': {('game', 'user')},
            },
        ),
    ]
