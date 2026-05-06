from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0037_bookstoread_current_page"),
    ]

    operations = [
        migrations.DeleteModel(
            name="PollState",
        ),
        migrations.DeleteModel(
            name="ContestSubmission",
        ),
        migrations.DeleteModel(
            name="ContestParticipant",
        ),
        migrations.DeleteModel(
            name="Question",
        ),
        migrations.DeleteModel(
            name="Contest",
        ),
    ]
