
import os
import django
import sys

# Add project root to path
sys.path.append('/app')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "src.settings")
django.setup()

from tgbot.models import BooksToRead, TelegramProfile

def seed_books():
    # Get the last active user or any user
    user = TelegramProfile.objects.last()
    
    if not user:
        print("No users found in TelegramProfile. Cannot seed books.")
        return

    print(f"Seeding books for user: {user.full_name} ({user.telegram_id})")

    for i in range(1, 41):
        BooksToRead.objects.create(
            user=user,
            title=f"Test Kitob {i}",
            total_pages=200
        )
    
    print(f"Successfully added 40 books for {user.full_name}")

if __name__ == "__main__":
    seed_books()
