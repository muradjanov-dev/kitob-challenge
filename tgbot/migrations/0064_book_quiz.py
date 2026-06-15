import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0063_reader_title_announcement'),
    ]

    operations = [
        migrations.CreateModel(
            name='BookQuizRound',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('conclusion', models.TextField(verbose_name='Quoted conclusion')),
                ('correct_title', models.CharField(max_length=255)),
                ('options', models.JSONField(default=list, help_text='The 4 shuffled book titles shown as answers.')),
                ('correct_index', models.PositiveSmallIntegerField(default=0)),
                ('reward', models.PositiveIntegerField(default=100, help_text='Kitobcha granted to each correct guesser.')),
                ('is_active', models.BooleanField(default=True, help_text='Only the latest round accepts answers; older ones are closed.')),
                ('source_report', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='quiz_rounds', to='tgbot.confirmationreport', help_text='Report the quoted conclusion was taken from.')),
                ('source_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='authored_quiz_rounds', to='tgbot.telegramprofile', help_text="Author of the quote — excluded from the reward (they'd know it).")),
            ],
            options={
                'verbose_name': 'Book Quiz Round',
                'verbose_name_plural': 'Book Quiz Rounds',
                'db_table': 'book_quiz_rounds',
                'ordering': ('-created_at',),
            },
        ),
        migrations.CreateModel(
            name='BookQuizAnswer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('chosen_index', models.PositiveSmallIntegerField()),
                ('is_correct', models.BooleanField(default=False)),
                ('rewarded', models.BooleanField(default=False, help_text='True once the Kitobcha reward was paid out.')),
                ('quiz_round', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='tgbot.bookquizround')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='book_quiz_answers', to='tgbot.telegramprofile')),
            ],
            options={
                'verbose_name': 'Book Quiz Answer',
                'verbose_name_plural': 'Book Quiz Answers',
                'db_table': 'book_quiz_answers',
                'ordering': ('-created_at',),
                'unique_together': {('quiz_round', 'user')},
            },
        ),
        migrations.CreateModel(
            name='BookQuizPromoState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('launched_on', models.DateField(blank=True, null=True, help_text='Set automatically on the first promo run; day 1 of the 10-day daily window.')),
                ('last_sent_on', models.DateField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Book Quiz Promo State',
            },
        ),
    ]
