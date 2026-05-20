from django.db import migrations

def backfill_global_books(apps, schema_editor):
    GlobalBook = apps.get_model('tgbot', 'GlobalBook')
    BooksToRead = apps.get_model('tgbot', 'BooksToRead')
    BookReport = apps.get_model('tgbot', 'BookReport')

    CYRILLIC_TO_LATIN = {
        'А': 'A', 'а': 'a', 'Б': 'B', 'б': 'b', 'В': 'V', 'в': 'v', 'Г': 'G', 'г': 'g',
        'Д': 'D', 'д': 'd', 'Е': 'E', 'е': 'e', 'Ё': 'Yo', 'ё': 'yo', 'Ж': 'J', 'ж': 'j',
        'З': 'Z', 'з': 'z', 'И': 'I', 'и': 'i', 'Й': 'Y', 'й': 'y', 'К': 'K', 'к': 'k',
        'Л': 'L', 'л': 'l', 'М': 'M', 'м': 'm', 'Н': 'N', 'н': 'n', 'О': 'O', 'о': 'o',
        'П': 'P', 'п': 'p', 'Р': 'R', 'р': 'r', 'С': 'S', 'с': 's', 'Т': 'T', 'т': 't',
        'У': 'U', 'у': 'u', 'Ф': 'F', 'ф': 'f', 'Х': 'X', 'х': 'x', 'Ц': 'Ts', 'ц': 'ts',
        'Ч': 'Ch', 'ч': 'ch', 'Ш': 'Sh', 'ш': 'sh', 'Ъ': '', 'ъ': '', 'Ь': '', 'ь': '',
        'Э': 'E', 'э': 'e', 'Ю': 'Yu', 'ю': 'yu', 'Я': 'Ya', 'ya': 'ya', 'Ў': 'O', 'ў': 'o',
        'Қ': 'Q', 'қ': 'q', 'Ғ': 'G', 'ғ': 'g', 'Ҳ': 'H', 'ҳ': 'h',
    }

    def normalize_text(text):
        if not text:
            return ""
        latin_chars = [CYRILLIC_TO_LATIN.get(c, c) for c in text]
        latin_text = "".join(latin_chars).lower()
        apostrophes = ["'", "`", "’", "‘", "ʻ", "\"", "”", "“"]
        for ap in apostrophes:
            latin_text = latin_text.replace(ap, "")
        return " ".join(latin_text.split())

    # 1. Backfill from BooksToRead
    for book in BooksToRead.objects.all():
        title_stripped = book.title.strip()
        if not title_stripped:
            continue
        normalized = normalize_text(title_stripped)
        
        # Get or create GlobalBook record using normalized title
        gbook = GlobalBook.objects.filter(normalized_title=normalized).first()
        if not gbook:
            # Check if there is any other exact matching title to prevent unique constraint crash
            gbook = GlobalBook.objects.filter(title__iexact=title_stripped).first()
            if not gbook:
                try:
                    gbook = GlobalBook.objects.create(
                        title=title_stripped,
                        normalized_title=normalized
                    )
                except Exception:
                    # Fallback if another thread/process created it in the meantime
                    gbook = GlobalBook.objects.filter(normalized_title=normalized).first()
        
        if gbook:
            book.global_book = gbook
            book.save()

    # 2. Backfill from BookReport
    for report in BookReport.objects.all():
        title_stripped = report.book.strip()
        if not title_stripped:
            continue
        normalized = normalize_text(title_stripped)
        
        gbook = GlobalBook.objects.filter(normalized_title=normalized).first()
        if not gbook:
            gbook = GlobalBook.objects.filter(title__iexact=title_stripped).first()
            if not gbook:
                try:
                    gbook = GlobalBook.objects.create(
                        title=title_stripped,
                        normalized_title=normalized
                    )
                except Exception:
                    gbook = GlobalBook.objects.filter(normalized_title=normalized).first()
        
        if gbook:
            report.global_book = gbook
            report.save()

class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0057_globalbook_requiredgroup_invite_link_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_global_books),
    ]
