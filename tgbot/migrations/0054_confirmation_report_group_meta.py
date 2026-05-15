from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0053_challenge'),
    ]

    operations = [
        migrations.AddField(
            model_name='confirmationreport',
            name='group_chat_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='confirmationreport',
            name='group_message_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='confirmationreport',
            name='group_thread_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='confirmationreport',
            name='reading_day',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
