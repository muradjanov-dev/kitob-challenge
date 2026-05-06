from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0038_remove_contest_subsystem"),
    ]

    operations = [
        migrations.DeleteModel(
            name="Action",
        ),
        migrations.DeleteModel(
            name="Habit",
        ),
        migrations.DeleteModel(
            name="Hour",
        ),
    ]
