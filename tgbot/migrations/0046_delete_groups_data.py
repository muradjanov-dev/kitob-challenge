from django.db import migrations


def delete_all_groups(apps, schema_editor):
    TelegramProfile = apps.get_model("tgbot", "TelegramProfile")
    Group = apps.get_model("tgbot", "Group")
    TelegramProfile.objects.filter(group__isnull=False).update(group=None)
    Group.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0045_userachievement"),
    ]

    operations = [
        migrations.RunPython(delete_all_groups, reverse_code=migrations.RunPython.noop),
    ]
