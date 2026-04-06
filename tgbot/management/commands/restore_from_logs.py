from django.core.management.base import BaseCommand
import re
from tgbot.models import ConfirmationReport, TelegramProfile
from datetime import datetime


class Command(BaseCommand):
    help = 'Restore failed INSERTs from log file by stripping IDs'

    def handle(self, *args, **options):
        log_file = 'restore_logs.txt'
        success_count = 0
        error_count = 0
        skipped_count = 0

        # Regex to capture the VALUES part.
        # It looks for "VALUES (id, 'date', pages, user_id, 'book', spent_time, 'conclusion');"
        # We need to handle multi-line strings in conclusion.
        # Strategy: Find "VALUES (" and then parse manually or use a smarter regex.
        # Given the logs, the values start after "VALUES (" and end with ");".
        # But wait, looking at the logs, some span multiple lines.

        # We will read the whole file and join lines to handle multi-line logs.
        try:
            with open(log_file, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'File {log_file} not found!'))
            return

        # Split by "STATEMENT:  INSERT INTO" to find blocks
        blocks = content.split(
            "STATEMENT:  INSERT INTO public.tgbot_confirmationreport")

        # Skip the first block (junk before first insert)
        for i in range(1, len(blocks)):
            block = blocks[i]

        # Regex to capture content inside VALUES (...)
        # Matches: VALUES ( <anything until );> )
        # Using DOTALL to handle newlines
        values_pattern = re.compile(r"VALUES\s*\((.*)\);", re.DOTALL)

        # Regex to match SQL values:
        # 1. Quoted string: ' ( [^'] | '' )* '  (matches 'text' or 'te''xt')
        # 2. Number: -?\d+(\.\d+)?
        # 3. NULL: NULL
        sql_value_pattern = re.compile(
            r"(?:'((?:[^']|'')*)')|(-?\d+(?:\.\d+)?)|(NULL)")

        for i in range(1, len(blocks)):
            block = blocks[i]

            # Extract the raw values string inside parenthesis
            match = values_pattern.search(block)
            if not match:
                continue

            raw_values_str = match.group(1)

            # Find all matches for values
            # This returns a list of tuples: [('string_content', '', ''), ('', '123', ''), ('', '', 'NULL'), ...]
            tokens = sql_value_pattern.findall(raw_values_str)

            # Flatten and clean tokens
            # We expect exactly 7 values for this specific INSERT statement
            parsed_values = []
            for t in tokens:
                if t[0]:  # String
                    # Replace escaped quotes '' with '
                    parsed_values.append(t[0].replace("''", "'"))
                elif t[1]:  # Number
                    # Assuming integers based on schema
                    parsed_values.append(int(t[1]))
                elif t[2]:  # NULL
                    parsed_values.append(None)

            if len(parsed_values) != 7:
                self.stdout.write(self.style.WARNING(
                    f"Skipping block {i}: Expected 7 values, found {len(parsed_values)}. Raw: {raw_values_str[:50]}..."))
                continue

            # Mapping based on log structure:
            # (id, date, pages_read, user_id, book, spent_time, conclusion)
            #   0    1       2          3       4        5           6

            # data dict for Django
            try:
                user_id = parsed_values[3]

                # Check user existence
                try:
                    user = TelegramProfile.objects.get(id=user_id)
                except TelegramProfile.DoesNotExist:
                    self.stdout.write(self.style.ERROR(
                        f"User ID {user_id} not found. Skipping."))
                    error_count += 1
                    continue

                data = {
                    'user': user,
                    'date': parsed_values[1],  # timestamp string
                    'pages_read': parsed_values[2],
                    'book': parsed_values[4],
                    'spent_time': parsed_values[5],
                    'conclusion': parsed_values[6]
                }

                # Using get_or_create to avoid duplicates if re-run
                # Unique constraints might be on user + date + book?
                # Or just create new ones as requested "restore failed inserts".
                # Given we stripped ID, these are "new" records.
                ConfirmationReport.objects.create(**data)
                success_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f"Restored report for User {user_id}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"Error processing values: {parsed_values} - Error: {e}"))
                error_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"DONE. Success: {success_count}, Errors: {error_count}"))
