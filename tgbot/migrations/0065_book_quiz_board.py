from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0064_book_quiz'),
    ]

    operations = [
        migrations.AddField(
            model_name='bookquizround',
            name='consolation',
            field=models.PositiveIntegerField(default=5, help_text='Kitobcha granted to wrong guessers as motivation.'),
        ),
        migrations.AddField(
            model_name='bookquizround',
            name='group_messages',
            field=models.JSONField(default=list, help_text='Posted group copies as [{"chat_id":…, "message_id":…}], edited live to show the right/wrong board.'),
        ),
    ]
