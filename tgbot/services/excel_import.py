import openpyxl
from asgiref.sync import sync_to_async


def parse_quiz_excel(file_path: str) -> list[dict]:
    """
    Parses an Excel file to extract quiz questions.
    Expected format (Columns A-G):
    A: Question Text
    B: Option 1
    C: Option 2
    D: Option 3
    E: Option 4
    F: Correct Answer Index (1-4)
    G: Explanation (Optional)
    """
    try:
        workbook = openpyxl.load_workbook(file_path)
        sheet = workbook.active

        quiz_data = []

        # Skip header row (assuming row 1 is header)
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:  # Skip empty rows
                continue

            question_text = row[0]
            options = [str(opt)
                       for opt in row[1:5] if opt]  # Get non-empty options

            # Validate options count
            if len(options) < 2:
                continue  # Skip invalid questions

            try:
                # Excel index 1-4 to 0-based index
                correct_index_raw = row[5]
                correct_option_id = int(correct_index_raw) - 1
            except (ValueError, TypeError):
                # If conversion fails or missing, default to 0 or skip?
                # Let's try to find if the value matches one of the options
                try:
                    correct_option_id = options.index(str(correct_index_raw))
                except ValueError:
                    correct_option_id = 0  # Default fallback

            # Ensure valid bounds
            if correct_option_id < 0 or correct_option_id >= len(options):
                correct_option_id = 0

            explanation = row[6] if len(row) > 6 else ""

            quiz_data.append({
                "question": question_text,
                "options": options,
                "correct_option_id": correct_option_id,
                "explanation": explanation,
                "type": "quiz"  # Telegram API type
            })

        return quiz_data

    except Exception as e:
        print(f"Error parsing Excel: {e}")
        return []


@sync_to_async
def process_quiz_file(file_path):
    return parse_quiz_excel(file_path)
