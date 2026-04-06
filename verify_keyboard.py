
from aiogram.types import ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from tgbot.tasks import send_notification_with_celery
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'src.settings')
django.setup()


def verify_keyboards():
    print("Verifying Keyboard Sending...")

    # 1. Test sending with Remove Keyboard
    # Using a dummy ID or admin ID if known. The logs will show if it succeeds or fails.
    # We'll use the ID from migration/tasks: 631751797 (seems to be admin)
    admin_id = 631751797

    print("\nTest 1: Sending 'Removing Keyboard'...")
    kb_remove = ReplyKeyboardRemove().to_python()
    # Sending directly to test the function logic, bypassing celery queue for immediate feedback if possible?
    # No, let's use the task function synchronously (it's a python function after all) to test the `send_notification` logic inside it.
    # The @shared_task decorator wraps it, but accessible.

    try:
        res = send_notification_with_celery(
            admin_id, "Testing: Removing Keyboard", reply_markup=kb_remove)
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error: {e}")

    # 2. Test sending with Main Menu (simulated)
    print("\nTest 2: Sending 'Main Menu'...")
    kb_menu = ReplyKeyboardMarkup(resize_keyboard=True)
    kb_menu.add(KeyboardButton("Test Button"))
    kb_menu_dict = kb_menu.to_python()

    try:
        res = send_notification_with_celery(
            admin_id, "Testing: Restoring Keyboard", reply_markup=kb_menu_dict)
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    verify_keyboards()
