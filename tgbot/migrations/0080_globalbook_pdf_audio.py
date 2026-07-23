from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0079_globalbook_cover_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='globalbook',
            name='pdf_file',
            field=models.FileField(blank=True, null=True, upload_to='library/pdfs/'),
        ),
        migrations.AddField(
            model_name='globalbook',
            name='audio_file',
            field=models.FileField(blank=True, null=True, upload_to='library/audio/'),
        ),
    ]
