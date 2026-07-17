from django.db import migrations


def seed_words(apps, schema_editor):
    from tgbot.services.chain_text import normalize, first_letter, last_letter
    from tgbot.services.chain_words_seed import CHAIN_WORDS

    ChainWord = apps.get_model('tgbot', 'ChainWord')
    for display, kind in CHAIN_WORDS:
        display = (display or "").strip()
        norm = normalize(display)
        fl = first_letter(display)
        ll = last_letter(display)
        if not norm or not fl:
            continue
        ChainWord.objects.get_or_create(
            norm=norm,
            defaults={
                "display": display,
                "kind": kind,
                "first_letter": fl,
                "last_letter": ll,
                "is_active": True,
            },
        )


def unseed(apps, schema_editor):
    ChainWord = apps.get_model('tgbot', 'ChainWord')
    ChainWord.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0067_kitob_zanjiri'),
    ]

    operations = [
        migrations.RunPython(seed_words, unseed),
    ]
