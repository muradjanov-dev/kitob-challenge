from django.db import migrations, models


REGIONS_12 = [
    "Andijon",
    "Buxoro",
    "Farg'ona",
    "Jizzax",
    "Namangan",
    "Navoiy",
    "Qashqadaryo",
    "Samarqand",
    "Sirdaryo",
    "Surxondaryo",
    "Toshkent",
    "Xorazm",
]


def replace_regions(apps, schema_editor):
    Region = apps.get_model("tgbot", "Region")
    TelegramProfile = apps.get_model("tgbot", "TelegramProfile")
    TelegramProfile.objects.update(region=None)
    Region.objects.all().delete()
    for name in REGIONS_12:
        Region.objects.create(name=name)


def restore_14_regions(apps, schema_editor):
    Region = apps.get_model("tgbot", "Region")
    Region.objects.all().delete()
    for name in [
        "Toshkent shahri", "Toshkent viloyati", "Andijon viloyati",
        "Buxoro viloyati", "Farg'ona viloyati", "Jizzax viloyati",
        "Namangan viloyati", "Navoiy viloyati", "Qashqadaryo viloyati",
        "Qoraqalpog'iston Respublikasi", "Samarqand viloyati",
        "Sirdaryo viloyati", "Surxondaryo viloyati", "Xorazm viloyati",
    ]:
        Region.objects.create(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0040_seed_regions"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramprofile",
            name="age_range",
            field=models.CharField(
                blank=True,
                null=True,
                max_length=16,
                choices=[
                    ("u18", "<18"),
                    ("18_25", "18-25"),
                    ("26_35", "26-35"),
                    ("36p", "36+"),
                ],
                verbose_name="Age Range",
            ),
        ),
        migrations.RunPython(replace_regions, restore_14_regions),
    ]
