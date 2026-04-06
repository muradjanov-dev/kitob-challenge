import py_compile
import sys
import os

files = [
    "tgbot/tasks.py",
    "tgbot/bot/handlers/users/quiz_answer.py",
    "tgbot/bot/handlers/users/contest.py"
]

print("Checking syntax...")
errors = False
for f in files:
    if os.path.exists(f):
        try:
            py_compile.compile(f, doraise=True)
            print(f"✅ {f} OK")
        except py_compile.PyCompileError as e:
            print(f"❌ {f} ERROR: {e}")
            errors = True
    else:
        print(f"⚠️ {f} NOT FOUND")

if errors:
    sys.exit(1)
else:
    print("All files passed syntax check.")
