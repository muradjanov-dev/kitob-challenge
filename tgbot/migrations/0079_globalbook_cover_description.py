from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0078_shopproduct_grants_premium_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='globalbook',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='globalbook',
            name='cover',
            field=models.ImageField(blank=True, null=True, upload_to='library/covers/'),
        ),
    ]
