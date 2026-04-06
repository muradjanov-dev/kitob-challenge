
from tgbot.models import BooksToRead, TelegramProfile
import os
import sys
import django

# Add project root to path
sys.path.append('/app')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "src.settings")
django.setup()

# Imports MUST come after django.setup()


def reassign_books():
    target_telegram_id = 1603330179

    try:
        target_user = TelegramProfile.objects.get(
            telegram_id=target_telegram_id)
    except TelegramProfile.DoesNotExist:
        try:
            # Fallback: Try with other ID if 1603330179 is invalid, but user asked specifically for this.
            # Or list all users to debug
            users = TelegramProfile.objects.all()
            print(
                f"Target user not found. Available users: {[u.telegram_id for u in users]}")
            return
        except Exception:
            print("Error finding user")
            return

    # Find books created by seed script (assuming they start with "Test Kitob")
    books = BooksToRead.objects.filter(title__startswith="Test Kitob")

    updated_count = books.update(user=target_user)

    print(
        f"Successfully reassigned {updated_count} books to user {target_user.full_name} ({target_user.telegram_id})")


if __name__ == "__main__":
    reassign_books()
