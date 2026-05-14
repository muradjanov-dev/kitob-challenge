import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0052_bookstoreads_is_audio'),
    ]

    operations = [
        migrations.CreateModel(
            name='Challenge',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField()),
                ('emoji', models.CharField(default='🏆', max_length=10)),
                ('condition_type', models.CharField(choices=[
                    ('pages_daily',     'Kunlik betlar soni'),
                    ('audio_daily',     'Kunlik audio daqiqalari'),
                    ('referrals_daily', 'Kunlik referrallar'),
                    ('review_daily',    'Kunlik xulosa (200+ belgi)'),
                ], max_length=30)),
                ('condition_value', models.IntegerField(default=0)),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=False)),
                ('announced_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'verbose_name': 'Challenge', 'verbose_name_plural': 'Challengelar'},
        ),
        migrations.CreateModel(
            name='ChallengeParticipant',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('days_completed', models.IntegerField(default=0)),
                ('completed_dates', models.JSONField(default=list)),
                ('last_completed_at', models.DateTimeField(blank=True, null=True)),
                ('rank', models.IntegerField(blank=True, null=True)),
                ('reward_given', models.BooleanField(default=False)),
                ('challenge', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='participants', to='tgbot.challenge',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='challenge_participations', to='tgbot.telegramprofile',
                )),
            ],
            options={
                'verbose_name': 'Challenge Qatnashchisi',
                'verbose_name_plural': 'Challenge Qatnashchilari',
                'unique_together': {('challenge', 'user')},
            },
        ),
    ]
