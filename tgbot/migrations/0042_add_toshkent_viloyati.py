from django.db import migrations


def add_toshkent_viloyati(apps, schema_editor):
    Region = apps.get_model("tgbot", "Region")
    Region.objects.get_or_create(name="Toshkent viloyati")


def remove_toshkent_viloyati(apps, schema_editor):
    Region = apps.get_model("tgbot", "Region")
    Region.objects.filter(name="Toshkent viloyati").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0041_age_range_and_12_regions"),
    ]

    operations = [
        migrations.RunPython(add_toshkent_viloyati, remove_toshkent_viloyati),
    ]
