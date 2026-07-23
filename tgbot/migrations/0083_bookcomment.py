from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0082_globalbook_is_premium_only'),
    ]

    operations = [
        migrations.CreateModel(
            name='BookComment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('text', models.TextField(max_length=1000)),
                ('book', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='comments',
                    to='tgbot.globalbook',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='book_comments',
                    to='tgbot.telegramprofile',
                )),
            ],
            options={
                'verbose_name': 'Book Comment',
                'verbose_name_plural': 'Book Comments',
                'db_table': 'book_comment',
                'ordering': ['-created_at'],
                'unique_together': {('book', 'user')},
            },
        ),
    ]
