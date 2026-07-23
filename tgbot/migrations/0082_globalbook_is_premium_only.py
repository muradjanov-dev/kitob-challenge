from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0081_globalbook_language'),
    ]

    operations = [
        migrations.AddField(
            model_name='globalbook',
            name='is_premium_only',
            field=models.BooleanField(default=False, verbose_name='Faqat Premium uchun'),
        ),
    ]
