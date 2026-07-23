from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0080_globalbook_pdf_audio'),
    ]

    operations = [
        migrations.AddField(
            model_name='globalbook',
            name='language',
            field=models.CharField(
                choices=[
                    ('uz', "O'zbekcha"),
                    ('ru', 'Ruscha'),
                    ('en', 'Inglizcha'),
                    ('tr', 'Turkcha'),
                    ('ar', 'Arabcha'),
                    ('other', 'Boshqa'),
                ],
                db_index=True,
                default='uz',
                max_length=10,
            ),
        ),
    ]
