from django.db import migrations


REGIONS = [
    "Toshkent shahri",
    "Toshkent viloyati",
    "Andijon viloyati",
    "Buxoro viloyati",
    "Farg'ona viloyati",
    "Jizzax viloyati",
    "Namangan viloyati",
    "Navoiy viloyati",
    "Qashqadaryo viloyati",
    "Qoraqalpog'iston Respublikasi",
    "Samarqand viloyati",
    "Sirdaryo viloyati",
    "Surxondaryo viloyati",
    "Xorazm viloyati",
]


def seed_regions(apps, schema_editor):
    Region = apps.get_model("tgbot", "Region")
    for name in REGIONS:
        Region.objects.get_or_create(name=name)


def unseed_regions(apps, schema_editor):
    Region = apps.get_model("tgbot", "Region")
    Region.objects.filter(name__in=REGIONS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0039_remove_habit_subsystem"),
    ]

    operations = [
        migrations.RunPython(seed_regions, unseed_regions),
    ]
