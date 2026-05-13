from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0050_add_contact_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='confirmationreport',
            name='is_audio',
            field=models.BooleanField(default=False, verbose_name='Is Audiobook'),
        ),
        migrations.AddField(
            model_name='confirmationreport',
            name='minutes_listened',
            field=models.IntegerField(blank=True, null=True, verbose_name='Minutes listened'),
        ),
    ]
