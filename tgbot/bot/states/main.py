from aiogram.dispatcher.filters.state import State, StatesGroup


class AdmissionState(StatesGroup):
    language = State()
    full_name = State()
    region = State()
    gender = State()
    phone_number = State()


class NotificationState(StatesGroup):
    get_text = State()
    is_picture = State()
    get_picture = State()
    confirm_text = State()


class ReportState(StatesGroup):
    reading_day = State()
    select_book = State()
    enter_book_name = State()
    enter_book_pages = State()
    # Keeping for compatibility if needed, but likely replaced by M2M logic
    book_title = State()
    pages_read = State()
    spent_time = State()
    conclusion = State()
    enter_pages_loop = State()
    confirm_report = State()


class ChangeLanguageState(StatesGroup):
    language_change = State()


class GroupStates(StatesGroup):
    group = State()


class StatisticState(StatesGroup):
    input_user_id = State()


class ShareLinkState(StatesGroup):
    go_back = State()


class PaymentStates(StatesGroup):
    receipt = State()


class SendMessageInBot(StatesGroup):
    content = State()
    message = State()


class AnswerMessageState(StatesGroup):
    message = State()


class QuizUploadState(StatesGroup):
    select_contest = State()
    choose_action = State()
    quiz_name = State()
    upload_file = State()
