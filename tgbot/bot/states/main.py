from aiogram.dispatcher.filters.state import State, StatesGroup


class AdmissionState(StatesGroup):
    language = State()
    full_name = State()
    gender = State()
    region = State()
    age = State()


class NotificationState(StatesGroup):
    get_text = State()
    is_picture = State()
    get_picture = State()
    confirm_text = State()


class ReportState(StatesGroup):
    reading_day = State()
    book_type = State()       # select: Kitob / Audiokitob / Ikkalasi ham
    select_book = State()
    enter_book_name = State()
    enter_book_pages = State()
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


class ReminderState(StatesGroup):
    text = State()
    time = State()


class PollAdminState(StatesGroup):
    question = State()
    options = State()
    confirm = State()


class ConfirmDeleteState(StatesGroup):
    confirm = State()


class ContactAdminState(StatesGroup):
    message = State()
    confirm = State()


class AdminReplyState(StatesGroup):
    message = State()
    confirm = State()
    padmin_reject_reason = State()


class QuizCreateState(StatesGroup):
    title = State()
    description = State()
    q_text = State()
    q_options = State()
    q_hint = State()
    time_limit = State()


class QuizEditState(StatesGroup):
    choose = State()
    title = State()
    description = State()
    time = State()
    edit_q_text = State()
    edit_q_opts = State()
    edit_q_hint = State()


class QuizBattleState(StatesGroup):
    start_time = State()


class AIQuizCreateState(StatesGroup):
    input_content = State()
    parsing = State()
