import os


def clean_null_byte_files(directory):
    print(f"Scanning {directory} for corrupt files containing null bytes...")
    deleted_files = []

    # Extensions that are expected to be binary (do not delete these)
    SAFE_EXTENSIONS = {
        '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico',
        '.woff', '.woff2', '.ttf', '.eot', '.otf',
        '.pdf', '.zip', '.gz', '.tar', '.rar',
        '.mp3', '.mp4', '.avi', '.mov',
        '.pyc', '.mo'  # compiled python/translation files should be deleted via other means usually, but let's check content
    }

    # But wait, .pyc SHOULD contain null bytes. We should probably just delete all .pyc files separately.
    # The user said "null bytes mavjud bo'lgan barcha fayllarni o'chirib yubor".
    # If I delete a .png because it has a null byte (which it does), I break assets.
    # So I MUST skip media extensions.

    for root, dirs, files in os.walk(directory):
        # Skip .git directory
        if '.git' in dirs:
            dirs.remove('.git')
        if 'venv' in dirs:
            dirs.remove('venv')

        for file in files:
            file_path = os.path.join(root, file)
            ext = os.path.splitext(file)[1].lower()

            if ext in SAFE_EXTENSIONS:
                continue

            try:
                with open(file_path, 'rb') as f:
                    content = f.read()

                if b'\x00' in content:
                    print(f"Deleting corrupt file: {file_path}")
                    os.remove(file_path)
                    deleted_files.append(file_path)

            except Exception as e:
                print(f"Error processing {file_path}: {e}")

    print("\n" + "="*30)
    print("DELETED FILES LIST:")
    if deleted_files:
        for f in deleted_files:
            print(f)
    else:
        print("No corrupt files found.")
    print("="*30)


if __name__ == "__main__":
    clean_null_byte_files(".")
