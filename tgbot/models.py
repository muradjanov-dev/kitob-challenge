from django.db import models
from django.utils.translation import gettext_lazy as _
from solo.models import SingletonModel

from django.conf import settings
from django.core.exceptions import ValidationError
from ckeditor.fields import RichTextField
from auditlog.registry import auditlog

from utils.bot import set_webhook_request, get_info
from utils.validate_supported_tags import is_valid_content, validate_content
from django.utils import timezone

from django.db import transaction
from decimal import Decimal


class BaseModel(models.Model):
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created at")
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated at")
    )

    class Meta:
        abstract = True


class TelegramBot(BaseModel):
    name = models.CharField(max_length=30, null=True, blank=True)
    bot_token = models.CharField(max_length=255)
    bot_username = models.CharField(max_length=125, blank=True, null=True)

    def save(self, *args, **kwargs):
        set_webhook_request(self.bot_token)
        username, name = get_info(bot_token=self.bot_token)
        self.bot_username = username
        self.name = name
        super(TelegramBot, self).save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Telegram Bot")
        verbose_name_plural = _("Telegram Bots")
        db_table = "telegram_bots"


class Group(BaseModel):
    title = models.CharField(max_length=255, verbose_name=_("Group name"))
    topic_id = models.CharField(max_length=255, verbose_name=_("Topic ID"))
    chat_id = models.CharField(
        max_length=255,
        verbose_name=_("Chat ID"),
        default="-1002237773868",
        db_index=True
    )
    gender = models.BooleanField(
        help_text="False for females, True for males",
        default=False
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name=_("Group is deleted ?")
    )

    ordering = models.IntegerField(_("Ordering"), default=1)

    def __str__(self):
        return self.title

    class Meta:
        db_table = "groups"
        verbose_name = _("Group")
        verbose_name_plural = _("Groups")


class Region(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name=_("Region Name")
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Region")
        verbose_name_plural = _("Regions")
        db_table = "regions"


class TelegramProfile(BaseModel):
    telegram_id = models.PositiveBigIntegerField(db_index=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    language = models.CharField(
        max_length=255,
        choices=settings.LANGUAGES,
        null=True,
        blank=True
    )
    referral_code = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Referral Code"
    )
    pending_referral_code = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        db_index=True,
        help_text="The referral code that brought this user in. Counted only after their first ConfirmationReport, then cleared.",
    )
    full_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Full Name")
    )
    phone_number = models.CharField(
        max_length=128, blank=True, null=True, verbose_name=_("Phone Number"))
    group = models.ForeignKey(
        Group, models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Group")
    )
    gender = models.CharField(
        choices=[('male', 'Male'), ('female', 'Female')],
        max_length=6,
        null=True
    )
    region = models.ForeignKey(
        to=Region,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Region"),
        related_name='users'
    )
    ball = models.DecimalField(
        verbose_name=_("Ball"),
        max_digits=10,
        decimal_places=2,
        default=0.00
    )
    is_registered = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    age_range = models.CharField(
        max_length=16,
        null=True,
        blank=True,
        choices=[
            ("u18", "<18"),
            ("18_25", "18-25"),
            ("26_35", "26-35"),
            ("36p", "36+"),
        ],
        verbose_name=_("Age Range"),
    )
    reminder_count = models.PositiveSmallIntegerField(
        default=3,
        help_text="Daily inspirational reminders this user wants. 0=off, max=3.",
        verbose_name=_("Daily reminders"),
    )
    last_progress_msg_id = models.BigIntegerField(
        null=True, blank=True,
        help_text="Most recent pinned daily-progress message id, used to repin/restore."
    )
    show_calendar = models.BooleanField(
        default=False,
        help_text="When True, the cabinet shows a clickable streak calendar.",
    )
    accept_congrats_from = models.CharField(
        max_length=10,
        default="any",
        choices=[("any", "Hammadan"), ("male", "Erkaklardan"), ("female", "Ayollardan")],
        help_text="Whose congratulations the user accepts.",
    )
    send_congrats_to = models.CharField(
        max_length=10,
        default="any",
        choices=[("any", "Hammaga"), ("male", "Erkaklarga"), ("female", "Ayollarga")],
        help_text="Whom the user is willing to congratulate.",
    )
    tabriklar_range = models.CharField(
        max_length=10,
        default="any",
        choices=[
            ("any", "Hammasi"),
            ("3-10", "3-10 yutuq"),
            ("11-20", "11-20 yutuq"),
            ("21-40", "21-40 yutuq"),
            ("41+", "41+ yutuq"),
        ],
        help_text=(
            "Filter Tabriklash DMs by the achiever's total achievement count. "
            "'any' = receive all (default)."
        ),
    )
    contact_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Admin contact count"),
        help_text="Number of times the user has successfully messaged the admin.",
    )
    congrats_dm_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of Tabriklash DMs this user has received; used to "
                  "surface the reminder-config button on every 10th one.",
    )
    optimal_send_hour = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Hour (0-23, Tashkent time) when this user is most likely to submit a report. "
            "Computed from their ConfirmationReport history by compute_optimal_send_hours. "
            "NULL = not enough data yet; falls back to fixed broadcast slots."
        ),
    )

    def update_ball(self, is_completed: bool, ball: int) -> int:
        """Add or subtract Kitobcha. Premium users earn 2× on every add.
        Returns the effective amount actually applied."""
        ball_decimal = Decimal(str(ball))
        if is_completed:
            # Check active premium subscription; Payment is defined later in this module.
            if Payment.objects.filter(
                user=self, status="paid", end_date__gte=timezone.localdate()
            ).exists():
                ball_decimal = ball_decimal * 2
        with transaction.atomic():
            self.refresh_from_db()
            self.ball = self.ball + ball_decimal if is_completed else self.ball - ball_decimal
            self.save(update_fields=["ball"])
        return int(ball_decimal)

    def __str__(self):
        return f"{self.full_name} - {self.username}"

    class Meta:
        verbose_name = "Telegram Profile"
        verbose_name_plural = "Telegram Profiles"
        db_table = "telegram_profiles"


class UserReferal(BaseModel):
    referrer = models.ForeignKey(
        TelegramProfile,
        on_delete=models.CASCADE,
        related_name='referrals',
        verbose_name=_("Referrer")
    )
    referred_user = models.OneToOneField(
        TelegramProfile,
        on_delete=models.CASCADE,
        related_name='referred_by',
        verbose_name=_("Referred User")
    )

    def __str__(self):
        return f"{self.referrer} invited {self.referred_user}"

    class Meta:
        db_table = "user_referrals"
        verbose_name = _("User Referral")
        verbose_name_plural = _("User Referrals")


class RequiredGroup(BaseModel):
    chat_id = models.CharField(
        max_length=255,
        verbose_name=_("Chat ID or Username"),
        help_text=_("Chat ID: -100000000 or Username: @username")
    )
    invite_link = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Invite Link"),
        help_text=_("https://t.me/...")
    )
    title = models.CharField(max_length=255, null=True, blank=True)
    bot = models.ForeignKey(TelegramBot, models.CASCADE)

    def __str__(self):
        return f"{self.chat_id} - {self.bot.name}"

    class Meta:
        verbose_name = _("Required Chats")
        verbose_name_plural = _("Required Chats")
        db_table = "required_groups"


class TelegramButton(BaseModel):
    bot = models.ForeignKey(
        TelegramBot,
        models.CASCADE,
        verbose_name=_("Telegram Bot")
    )
    parent = models.ForeignKey(
        "self",
        models.CASCADE,
        blank=True,
        null=True
    )
    title = models.CharField(
        max_length=255,
        verbose_name=_("Button Name")
    )
    text = RichTextField(
        verbose_name=_("Button Text"),
        blank=True,
        null=True
    )
    content = models.FileField(
        upload_to="buttons",
        verbose_name=_("Button Content"),
        blank=True,
        null=True
    )
    file_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("File ID")
    )

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.title_uz:
            self.title_uz = self.title
        if not self.title_ru:
            self.title_ru = self.title

        if not self.text_uz:
            self.text_uz = self.text
        if not self.text_ru:
            self.text_ru = self.text

        if self.text_ru:
            self.text_ru = validate_content(self.text_ru)
        if self.text_uz:
            self.text_uz = validate_content(self.text_uz)
        super(TelegramButton, self).save(*args, **kwargs)


CYRILLIC_TO_LATIN = {
    'А': 'A', 'а': 'a', 'Б': 'B', 'б': 'b', 'В': 'V', 'в': 'v', 'Г': 'G', 'г': 'g',
    'Д': 'D', 'д': 'd', 'Е': 'E', 'е': 'e', 'Ё': 'Yo', 'ё': 'yo', 'Ж': 'J', 'ж': 'j',
    'З': 'Z', 'з': 'z', 'И': 'I', 'и': 'i', 'Й': 'Y', 'й': 'y', 'К': 'K', 'к': 'k',
    'Л': 'L', 'л': 'l', 'М': 'M', 'м': 'm', 'Н': 'N', 'н': 'n', 'О': 'O', 'о': 'o',
    'П': 'P', 'п': 'p', 'Р': 'R', 'р': 'r', 'С': 'S', 'с': 's', 'Т': 'T', 'т': 't',
    'У': 'U', 'у': 'u', 'Ф': 'F', 'ф': 'f', 'Х': 'X', 'х': 'x', 'Ц': 'Ts', 'ц': 'ts',
    'Ч': 'Ch', 'ч': 'ch', 'Ш': 'Sh', 'ш': 'sh', 'Ъ': '', 'ъ': '', 'Ь': '', 'ь': '',
    'Э': 'E', 'э': 'e', 'Ю': 'Yu', 'ю': 'yu', 'Я': 'Ya', 'я': 'ya', 'Ў': 'O', 'ў': 'o',
    'Қ': 'Q', 'қ': 'q', 'Ғ': 'G', 'ғ': 'g', 'Ҳ': 'H', 'ҳ': 'h',
}

def normalize_uzbek_text(text: str) -> str:
    if not text:
        return ""
    # 1. Transliterate Cyrillic characters to Latin
    latin_chars = [CYRILLIC_TO_LATIN.get(c, c) for c in text]
    latin_text = "".join(latin_chars).lower()

    # 2. Strip all styles of apostrophes (', `, ’, ’, ”, ʻ) to prevent matching mismatch
    apostrophes = ["'", "`", "’", "‘", "ʻ", "\"", "”", "“"]
    for ap in apostrophes:
        latin_text = latin_text.replace(ap, "")

    # 3. Clean extra whitespaces
    return " ".join(latin_text.split())


class GlobalBook(BaseModel):
    title = models.CharField(max_length=255, unique=True, verbose_name="Book Title")
    normalized_title = models.CharField(max_length=255, db_index=True)
    author = models.CharField(max_length=255, blank=True, null=True)

    def save(self, *args, **kwargs):
        self.normalized_title = normalize_uzbek_text(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = _("Global Book")
        verbose_name_plural = _("Global Books")
        db_table = "global_book"


class BooksToRead(BaseModel):
    user = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE)
    global_book = models.ForeignKey(GlobalBook, on_delete=models.SET_NULL, null=True, blank=True, related_name="user_books")
    title = models.CharField(max_length=255)
    is_audio = models.BooleanField(default=False)
    total_pages = models.PositiveIntegerField(default=1)  # for audio: total minutes
    current_page = models.PositiveIntegerField(default=0)  # for audio: minutes listened so far

    def __str__(self):
        return f"{self.title} - {self.user}"

    class Meta:
        verbose_name = _("Book to read")
        verbose_name_plural = _("Books to read")
        db_table = "books_to_read"


class BookReport(BaseModel):
    user = models.ForeignKey(
        TelegramProfile,
        on_delete=models.CASCADE,
        verbose_name=_("User")
    )
    global_book = models.ForeignKey(
        GlobalBook,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name=_("Global Book")
    )
    reading_day = models.IntegerField(
        default=1,
        verbose_name=_("Reading day")
    )
    book = models.CharField(
        max_length=255,
        verbose_name=_("Book title")
    )
    pages_read = models.IntegerField(
        default=1,
        verbose_name=_("Pages read")
    )

    def __str__(self):
        return f'{self.user.username}: {self.reading_day}-kun {self.book}. {self.pages_read}+ bet.'


class ReportMessage(models.Model):
    chat_id = models.CharField(max_length=255)
    group = models.ForeignKey(
        Group,
        models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Group")
    )
    message_id = models.PositiveIntegerField(null=True, blank=True)
    message_text = models.TextField(null=True, blank=True)
    last_update = models.DateField(default=timezone.now)
    message_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Message {self.message_id} in chat {self.chat_id}"


class ConfirmationReport(models.Model):
    user = models.ForeignKey(
        TelegramProfile,
        on_delete=models.CASCADE,
        verbose_name=_("User"),
    )
    date = models.DateTimeField(default=timezone.now)
    book = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )
    books = models.ManyToManyField(
        BooksToRead, verbose_name=_("Books"), blank=True)
    pages_read = models.IntegerField()
    spent_time = models.IntegerField(
        null=True, verbose_name=_("Spent time (in minutes)"))
    conclusion = models.TextField(
        verbose_name=_("Xulosa"), null=True, blank=True)
    is_audio = models.BooleanField(
        default=False, verbose_name=_("Is Audiobook"))
    minutes_listened = models.IntegerField(
        null=True, blank=True, verbose_name=_("Minutes listened"))
    group_chat_id = models.BigIntegerField(null=True, blank=True)
    group_message_id = models.BigIntegerField(null=True, blank=True)
    group_thread_id = models.IntegerField(null=True, blank=True)
    reading_day = models.IntegerField(null=True, blank=True)

    def __str__(self):
        if self.is_audio:
            return f"User {self.user.full_name} listened {self.minutes_listened} minutes"
        return f"User {self.user.full_name} readed {self.pages_read} pages"


class LastTopicID(SingletonModel):
    topic_id = models.CharField(max_length=255, verbose_name=_("Topic ID"))

    def __str__(self):
        return self.topic_id


class DailyMessage(models.Model):
    message = models.TextField(
        verbose_name=_("Message"),
        default="Notification"
    )

    def __str__(self):
        return self.message

    class Meta:
        verbose_name = _("Daily Message")
        verbose_name_plural = _("Daily Messages")


class Payment(BaseModel):
    STATUS_CHOICES = [
        ('paid', 'Paid'),
        ('unpaid', 'Unpaid'),
    ]
    user = models.ForeignKey(
        to=TelegramProfile,
        on_delete=models.CASCADE,
        related_name="payments"
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    start_date = models.DateField(
        verbose_name=_("Subscription start time")
    )
    end_date = models.DateField(
        verbose_name=_("Subscription end time")
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='unpaid'
    )

    def mark_as_paid(self):
        """To'lovni `paid` holatiga o'tkazish."""
        self.status = 'paid'
        self.save()

    def __str__(self) -> str:
        return f"""{self.user} | {self.start_date.strftime("%d/%m/%Y")}-{self.end_date.strftime("%d/%m/%Y")}"""


auditlog.register(RequiredGroup)
auditlog.register(TelegramProfile)
auditlog.register(TelegramBot)


class ScheduledReminder(BaseModel):
    text = models.TextField(verbose_name=_("Reminder text"))
    hour = models.PositiveSmallIntegerField(verbose_name=_("Hour (0-23)"))
    minute = models.PositiveSmallIntegerField(verbose_name=_("Minute (0-59)"))
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    created_by = models.ForeignKey(
        TelegramProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reminders_created",
    )

    def __str__(self):
        return f"{self.hour:02d}:{self.minute:02d} — {self.text[:40]}"

    class Meta:
        db_table = "scheduled_reminders"
        verbose_name = _("Scheduled Reminder")
        verbose_name_plural = _("Scheduled Reminders")
        ordering = ("hour", "minute", "id")


class BotPoll(BaseModel):
    question = models.TextField()
    options = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        TelegramProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="polls_created",
    )

    def __str__(self):
        return f"Poll #{self.id}: {self.question[:50]}"

    class Meta:
        db_table = "bot_polls"
        ordering = ("-created_at",)


class BotPollVote(BaseModel):
    poll = models.ForeignKey(BotPoll, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE)
    option_index = models.PositiveSmallIntegerField()

    class Meta:
        db_table = "bot_poll_votes"
        unique_together = (("poll", "user"),)
        ordering = ("-created_at",)


class UserAchievement(BaseModel):
    """Records that a user has unlocked a particular achievement.
    Achievement metadata (title, emoji, criteria) lives in code, not DB —
    `code` is the stable identifier that maps to ACHIEVEMENTS in achievements.py."""
    user = models.ForeignKey(
        TelegramProfile, on_delete=models.CASCADE, related_name="achievements"
    )
    code = models.CharField(max_length=64)
    awarded_at = models.DateTimeField(auto_now_add=True)
    congratulated = models.BooleanField(
        default=False,
        help_text="True once the Tabriklash broadcast has been sent.",
    )

    class Meta:
        db_table = "user_achievements"
        unique_together = (("user", "code"),)
        ordering = ("-awarded_at",)

    def __str__(self):
        return f"{self.user_id}/{self.code}"


class Congratulation(models.Model):
    """One row per (achievement-unlock event, congratulator) tuple.
    The achievement-unlock event is identified by the UserAchievement row."""
    achievement = models.ForeignKey(
        UserAchievement, on_delete=models.CASCADE,
        related_name="congratulations",
    )
    congratulator = models.ForeignKey(
        TelegramProfile, on_delete=models.CASCADE,
        related_name="congratulations_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "congratulations"
        unique_together = (("achievement", "congratulator"),)
        ordering = ("-created_at",)


class ScheduledMessageDeletion(models.Model):
    """A queued auto-delete: a periodic task scans this table and deletes
    messages whose delete_at has passed. Used for end-of-day percentile
    messages (72h TTL) and future congratulation messages (12h TTL)."""
    chat_id = models.BigIntegerField(db_index=True)
    message_id = models.BigIntegerField()
    delete_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "scheduled_message_deletions"
        ordering = ("delete_at",)


# ─────────────────────────────────────────────────────────────────────────────
# Quiz system
# ─────────────────────────────────────────────────────────────────────────────
import random as _random
import string as _string


def _quiz_code():
    return ''.join(_random.choices(_string.ascii_lowercase + _string.digits, k=8))


class Quiz(models.Model):
    creator = models.ForeignKey(
        'TelegramProfile', on_delete=models.CASCADE, related_name='quizzes'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    time_per_question = models.IntegerField(default=30)
    shuffle = models.BooleanField(default=True)
    link_code = models.CharField(max_length=16, unique=True, default=_quiz_code)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quizzes'
        ordering = ('-created_at',)


class QuizQuestion(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField()
    hint = models.TextField(blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        db_table = 'quiz_questions'
        ordering = ('order',)


class QuizOption(models.Model):
    question = models.ForeignKey(
        QuizQuestion, on_delete=models.CASCADE, related_name='options'
    )
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    order = models.IntegerField(default=0)

    class Meta:
        db_table = 'quiz_options'
        ordering = ('order',)


class QuizSession(models.Model):
    WAITING = 'waiting'
    ACTIVE = 'active'
    FINISHED = 'finished'

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='sessions')
    creator = models.ForeignKey(
        'TelegramProfile', on_delete=models.CASCADE, related_name='quiz_sessions_led'
    )
    chat_id = models.BigIntegerField(db_index=True)
    join_message_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, default='waiting')
    scheduled_start = models.DateTimeField(null=True, blank=True)
    current_question_idx = models.IntegerField(default=0)
    question_order = models.TextField(default='[]')  # JSON list of question IDs
    is_group = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quiz_sessions'


class QuizParticipant(models.Model):
    session = models.ForeignKey(
        QuizSession, on_delete=models.CASCADE, related_name='participants'
    )
    user = models.ForeignKey(
        'TelegramProfile', on_delete=models.CASCADE, related_name='quiz_participations'
    )
    score = models.IntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quiz_participants'
        unique_together = ('session', 'user')


class QuizUserAnswer(models.Model):
    participant = models.ForeignKey(
        QuizParticipant, on_delete=models.CASCADE, related_name='answers'
    )
    question = models.ForeignKey(
        QuizQuestion, on_delete=models.CASCADE, related_name='user_answers'
    )
    option = models.ForeignKey(
        QuizOption, on_delete=models.CASCADE, null=True, blank=True
    )
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quiz_user_answers'
        unique_together = ('participant', 'question')


# ──────────────────────────────────────────────────────────────────────────
# Kitobxonlik Challenge
# ──────────────────────────────────────────────────────────────────────────

class Challenge(models.Model):
    CONDITION_TYPES = [
        ('pages_daily',     'Kunlik betlar soni'),
        ('audio_daily',     'Kunlik audio daqiqalari'),
        ('referrals_daily', 'Kunlik referrallar'),
        ('review_daily',    'Kunlik xulosa (200+ belgi)'),
    ]
    title          = models.CharField(max_length=200)
    description    = models.TextField()
    emoji          = models.CharField(max_length=10, default='🏆')
    condition_type = models.CharField(max_length=30, choices=CONDITION_TYPES)
    condition_value = models.IntegerField(default=0)
    start_date     = models.DateField(null=True, blank=True)
    end_date       = models.DateField(null=True, blank=True)
    is_active      = models.BooleanField(default=False)
    announced_at   = models.DateTimeField(null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Challenge"
        verbose_name_plural = "Challengelar"

    def __str__(self):
        return f"{self.title} ({self.start_date} – {self.end_date})"


class ChallengeParticipant(models.Model):
    challenge        = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name="participants")
    user             = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE, related_name="challenge_participations")
    joined_at        = models.DateTimeField(auto_now_add=True)
    days_completed   = models.IntegerField(default=0)
    completed_dates  = models.JSONField(default=list)  # ["YYYY-MM-DD", ...]
    last_completed_at = models.DateTimeField(null=True, blank=True)  # set when days_completed reaches 3
    rank             = models.IntegerField(null=True, blank=True)
    reward_given     = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Challenge Qatnashchisi"
        verbose_name_plural = "Challenge Qatnashchilari"
        unique_together = ('challenge', 'user')

    def __str__(self):
        return f"{self.user.full_name} — {self.challenge.title} ({self.days_completed}/3)"


# ─────────────────────────────────────────────────────────────────────────────
# Shop — Kitob Challenge Mini App marketplace where users redeem their
# Kitobcha balance (TelegramProfile.ball) for prizes uploaded by admins.
# Currently gated to is_admin users for testing; flip the gate in the bot
# keyboard + view to roll out.
# ─────────────────────────────────────────────────────────────────────────────
class ShopProduct(BaseModel):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    image = models.ImageField(upload_to="shop/products/", blank=True, null=True)
    price_kitobcha = models.PositiveIntegerField(
        help_text="Cost in Kitobcha. Deducted atomically from the buyer's ball.",
    )
    stock_qty = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Leave blank for unlimited. Decremented on each purchase.",
    )
    sort_order = models.IntegerField(
        default=0,
        help_text="Lower = shown first. Ties broken by newest-first.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Shop Product"
        verbose_name_plural = "Shop Products"
        ordering = ("sort_order", "-created_at")

    def __str__(self):
        return f"{self.name} — {self.price_kitobcha} Kitobcha"

    @property
    def is_available(self) -> bool:
        if not self.is_active:
            return False
        return self.stock_qty is None or self.stock_qty > 0


class ShopPurchase(BaseModel):
    STATUS_PENDING = "pending"
    STATUS_FULFILLED = "fulfilled"
    STATUS_REFUNDED = "refunded"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_FULFILLED, "Fulfilled"),
        (STATUS_REFUNDED, "Refunded"),
    ]

    user = models.ForeignKey(
        TelegramProfile, on_delete=models.CASCADE, related_name="shop_purchases",
    )
    # SET_NULL so deleting a product doesn't wipe historical purchase records.
    product = models.ForeignKey(
        ShopProduct, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="purchases",
    )
    product_name_snapshot = models.CharField(
        max_length=120,
        help_text="Name at time of purchase, kept even if product is deleted.",
    )
    price_at_purchase = models.PositiveIntegerField()
    code = models.CharField(
        max_length=12, unique=True,
        help_text="Short pickup code the user shows the admin.",
    )
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING,
    )

    class Meta:
        verbose_name = "Shop Purchase"
        verbose_name_plural = "Shop Purchases"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.code} — {self.user.full_name} — {self.product_name_snapshot}"


class ReaderTitleAnnouncement(BaseModel):
    """Snapshot of one "Kitobxon nominatsiyalari" broadcast. Stores the winners
    so a single 🎉 Tabriklash button (shared across every copy of the message)
    can DM all of them, and so repeat clicks per user are de-duplicated."""
    winners = models.JSONField(
        default=list,
        help_text='List of {"k": category_key, "t": winner_telegram_id}.',
    )
    congratulators = models.JSONField(
        default=list,
        help_text="Telegram ids who already congratulated (dedupe).",
    )

    class Meta:
        verbose_name = "Reader Title Announcement"
        verbose_name_plural = "Reader Title Announcements"
        ordering = ("-created_at",)

    def __str__(self):
        return f"Nominatsiyalar #{self.id} — {len(self.winners or [])} g'olib"


# ─────────────────────────────────────────────────────────────────────────────
# Referral BOOM — a time-boxed (3-day) referral blitz. While a boom is live,
# every NEW referral a participant brings pays a flat Kitobcha bonus:
#   • the first `tier1_cap` referrals  → `tier1_reward` each (e.g. 150)
#   • every referral beyond that        → `tier2_reward` each (e.g. 300)
# On joining, the bot DMs the user their personal referral link + the rules
# (once), then drip-feeds `total_reminders` playful reminders over the window.
# This is intentionally separate from the daily-completion `Challenge` system.
# ─────────────────────────────────────────────────────────────────────────────
class ReferralBoom(BaseModel):
    title = models.CharField(max_length=200, default="3 Kunlik Referal BOOM")
    start_at = models.DateTimeField(verbose_name=_("Start"))
    end_at = models.DateTimeField(verbose_name=_("End"))
    tier1_reward = models.PositiveIntegerField(
        default=150, help_text="Kitobcha per referral for the first tier1_cap referrals.",
    )
    tier1_cap = models.PositiveIntegerField(
        default=10, help_text="Referrals up to and including this count earn tier1_reward.",
    )
    tier2_reward = models.PositiveIntegerField(
        default=300, help_text="Kitobcha per referral once tier1_cap is exceeded.",
    )
    total_reminders = models.PositiveIntegerField(
        default=21, help_text="How many playful reminders each participant receives across the window.",
    )
    is_active = models.BooleanField(default=False)
    is_queued = models.BooleanField(
        default=False,
        help_text="If set, the next regular 3-day challenge rotation launches "
                  "this boom instead of a normal challenge (then resumes the pool).",
    )
    announced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Referral BOOM"
        verbose_name_plural = "Referral BOOMlar"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.title} ({self.start_at:%d.%m %H:%M} – {self.end_at:%d.%m %H:%M})"

    def is_live(self) -> bool:
        now = timezone.now()
        return bool(self.is_active and self.start_at <= now <= self.end_at)

    def reward_for(self, referral_number: int) -> int:
        """Kitobcha paid for the participant's Nth boom referral (1-indexed)."""
        return self.tier1_reward if referral_number <= self.tier1_cap else self.tier2_reward


# ─────────────────────────────────────────────────────────────────────────────
# Kitob Viktorina — twice-a-day "guess the book" quiz built from the conclusions
# (xulosa/iqtibos) users have submitted with their daily reports. One real quote
# is shown with 4 book options (1 correct + 3 random books pulled from the whole
# library). Correct guessers earn a flat Kitobcha reward. Premium-only feature;
# answering also requires being a member of one of the reading groups.
# ─────────────────────────────────────────────────────────────────────────────
class BookQuizRound(BaseModel):
    source_report = models.ForeignKey(
        ConfirmationReport, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quiz_rounds",
        help_text="Report the quoted conclusion was taken from.",
    )
    source_user = models.ForeignKey(
        TelegramProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="authored_quiz_rounds",
        help_text="Author of the quote — excluded from the reward (they'd know it).",
    )
    conclusion = models.TextField(verbose_name=_("Quoted conclusion"))
    correct_title = models.CharField(max_length=255)
    options = models.JSONField(
        default=list, help_text="The 4 shuffled book titles shown as answers.",
    )
    correct_index = models.PositiveSmallIntegerField(default=0)
    reward = models.PositiveIntegerField(
        default=100, help_text="Kitobcha granted to each correct guesser.",
    )
    consolation = models.PositiveIntegerField(
        default=5, help_text="Kitobcha granted to wrong guessers as motivation.",
    )
    group_messages = models.JSONField(
        default=list,
        help_text='Posted group copies as [{"chat_id":…, "message_id":…}], '
                  "edited live to show the right/wrong board.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Only the latest round accepts answers; older ones are closed.",
    )

    class Meta:
        db_table = "book_quiz_rounds"
        verbose_name = _("Book Quiz Round")
        verbose_name_plural = _("Book Quiz Rounds")
        ordering = ("-created_at",)

    def __str__(self):
        return f"Viktorina #{self.id} — {self.correct_title}"


class BookQuizAnswer(BaseModel):
    quiz_round = models.ForeignKey(
        BookQuizRound, on_delete=models.CASCADE, related_name="answers",
    )
    user = models.ForeignKey(
        TelegramProfile, on_delete=models.CASCADE, related_name="book_quiz_answers",
    )
    chosen_index = models.PositiveSmallIntegerField()
    is_correct = models.BooleanField(default=False)
    rewarded = models.BooleanField(
        default=False, help_text="True once the Kitobcha reward was paid out.",
    )

    class Meta:
        db_table = "book_quiz_answers"
        verbose_name = _("Book Quiz Answer")
        verbose_name_plural = _("Book Quiz Answers")
        unique_together = ("quiz_round", "user")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user_id} → round {self.quiz_round_id} ({'✓' if self.is_correct else '✗'})"


class BookQuizPromoState(SingletonModel):
    """Tracks the rollout of the Viktorina promo reminders: once a day for the
    first 10 days after launch, then only on a random subset of days."""
    launched_on = models.DateField(
        null=True, blank=True,
        help_text="Set automatically on the first promo run; day 1 of the 10-day daily window.",
    )
    last_sent_on = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = _("Book Quiz Promo State")

    def __str__(self):
        return f"Viktorina promo (launched {self.launched_on})"


class ReferralBoomParticipant(BaseModel):
    boom = models.ForeignKey(
        ReferralBoom, on_delete=models.CASCADE, related_name="participants",
    )
    user = models.ForeignKey(
        TelegramProfile, on_delete=models.CASCADE, related_name="boom_participations",
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    rules_sent = models.BooleanField(
        default=False, help_text="True once the welcome+rules DM has been sent (sent exactly once).",
    )
    referrals_count = models.PositiveIntegerField(
        default=0, help_text="Referrals brought in DURING this boom window.",
    )
    kitobcha_earned = models.PositiveIntegerField(
        default=0, help_text="Total boom-bonus Kitobcha earned by this participant.",
    )
    reminder_schedule = models.JSONField(
        default=list, help_text="Ascending list of ISO datetimes when reminders fire.",
    )
    reminders_sent = models.PositiveIntegerField(
        default=0, help_text="Pointer into reminder_schedule — index of the next reminder to send.",
    )
    used_reminder_keys = models.JSONField(
        default=list, help_text="Template keys already used, to avoid repeating copy.",
    )

    class Meta:
        verbose_name = "Referral BOOM Qatnashchisi"
        verbose_name_plural = "Referral BOOM Qatnashchilari"
        unique_together = ("boom", "user")

    def __str__(self):
        return f"{self.user.full_name} — {self.boom.title} ({self.referrals_count} taklif)"


# ─────────────────────────────────────────────────────────────────────────────
# Kitob Zanjiri — a live, twice-a-week "book chain" race on the website Mini
# App. A session shows a required starting letter; everyone races to submit a
# book title / author name starting with it (from the ChainWord dictionary, not
# already used). The first valid submission wins the link, scores a point, and
# the chain advances to a new letter. Top scorers earn Kitobcha at the end.
# ─────────────────────────────────────────────────────────────────────────────
class ChainWord(BaseModel):
    KIND_BOOK = "book"
    KIND_AUTHOR = "author"
    KIND_CHOICES = [(KIND_BOOK, "Kitob"), (KIND_AUTHOR, "Muallif")]

    display = models.CharField(max_length=200, help_text="Shown to players.")
    norm = models.CharField(
        max_length=200, unique=True, db_index=True,
        help_text="Normalized lookup/dedupe key (lowercase, unified apostrophes).",
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_BOOK)
    first_letter = models.CharField(max_length=1, db_index=True, default="")
    last_letter = models.CharField(max_length=1, db_index=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "chain_words"
        verbose_name = "Kitob Zanjiri — So'z"
        verbose_name_plural = "Kitob Zanjiri — Lug'at"
        ordering = ("norm",)

    def __str__(self):
        return f"{self.display} ({self.first_letter}…{self.last_letter})"


class ChainGame(BaseModel):
    STATUS_SCHEDULED = "scheduled"
    STATUS_LIVE = "live"
    STATUS_FINISHED = "finished"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Rejalashtirilgan"),
        (STATUS_LIVE, "Jonli"),
        (STATUS_FINISHED, "Tugagan"),
    ]

    title = models.CharField(max_length=120, default="Kitob Zanjiri")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    current_letter = models.CharField(max_length=1, default="")
    chain = models.JSONField(
        default=list,
        help_text='Won links: [{"norm","display","user_id","name","letter","at"}].',
    )
    used_norms = models.JSONField(
        default=list, help_text="Normalized words already played (no repeats).",
    )
    rewarded = models.BooleanField(default=False)

    class Meta:
        db_table = "chain_games"
        verbose_name = "Kitob Zanjiri — O'yin"
        verbose_name_plural = "Kitob Zanjiri — O'yinlar"
        ordering = ("-starts_at",)

    def __str__(self):
        return f"{self.title} #{self.id} — {self.status} ({self.starts_at:%d.%m %H:%M})"

    def is_live(self) -> bool:
        now = timezone.now()
        return self.status == self.STATUS_LIVE and self.starts_at <= now <= self.ends_at


class ChainScore(BaseModel):
    game = models.ForeignKey(ChainGame, on_delete=models.CASCADE, related_name="scores")
    user = models.ForeignKey(
        TelegramProfile, on_delete=models.CASCADE, related_name="chain_scores",
    )
    points = models.PositiveIntegerField(default=0)
    links = models.PositiveIntegerField(default=0, help_text="Links this user won.")
    reward = models.PositiveIntegerField(default=0, help_text="Kitobcha paid at finish.")
    rewarded = models.BooleanField(default=False)
    strikes = models.PositiveIntegerField(
        default=0, help_text="How many of this user's links the crowd rejected.")
    kicked = models.BooleanField(
        default=False, help_text="Removed from the game after 3 rejected links.")

    class Meta:
        db_table = "chain_scores"
        verbose_name = "Kitob Zanjiri — Ball"
        verbose_name_plural = "Kitob Zanjiri — Ballar"
        unique_together = ("game", "user")
        ordering = ("-points", "created_at")

    def __str__(self):
        return f"{self.user_id} → game {self.game_id}: {self.points}"


# ─────────────────────────────────────────────────────────────────────────────
# Ko'pchilik nima dedi? — a live "Family Feud" style game. Each round asks an
# open question; everyone types one answer within a window. Answers are grouped;
# the more people who gave the same answer, the more points each of them earns
# (matching the crowd wins). Top scorers earn Kitobcha; every player gets a
# guest reward.
# ─────────────────────────────────────────────────────────────────────────────
class FeudGame(BaseModel):
    STATUS_SCHEDULED = "scheduled"
    STATUS_LIVE = "live"
    STATUS_FINISHED = "finished"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Rejalashtirilgan"), (STATUS_LIVE, "Jonli"),
        (STATUS_FINISHED, "Tugagan"),
    ]
    title = models.CharField(max_length=120, default="Ko'pchilik nima dedi?")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    questions = models.JSONField(default=list, help_text="List of question strings.")
    answer_seconds = models.PositiveIntegerField(default=25)
    reveal_seconds = models.PositiveIntegerField(default=8)
    scored_indices = models.JSONField(default=list, help_text="Questions already scored.")
    rewarded = models.BooleanField(default=False)

    class Meta:
        db_table = "feud_games"
        verbose_name = "Ko'pchilik — O'yin"
        verbose_name_plural = "Ko'pchilik — O'yinlar"
        ordering = ("-starts_at",)

    def __str__(self):
        return f"Ko'pchilik #{self.id} — {self.status}"


class FeudAnswer(BaseModel):
    game = models.ForeignKey(FeudGame, on_delete=models.CASCADE, related_name="answers")
    user = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE, related_name="feud_answers")
    q_index = models.PositiveSmallIntegerField()
    text = models.CharField(max_length=120)
    norm = models.CharField(max_length=120, db_index=True)

    class Meta:
        db_table = "feud_answers"
        unique_together = ("game", "user", "q_index")
        ordering = ("created_at",)


class FeudScore(BaseModel):
    game = models.ForeignKey(FeudGame, on_delete=models.CASCADE, related_name="scores")
    user = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE, related_name="feud_scores")
    points = models.PositiveIntegerField(default=0)
    reward = models.PositiveIntegerField(default=0)
    rewarded = models.BooleanField(default=False)

    class Meta:
        db_table = "feud_scores"
        unique_together = ("game", "user")
        ordering = ("-points", "created_at")


# ─────────────────────────────────────────────────────────────────────────────
# Bilim Qal'asi — a cooperative live quiz. Everyone answers multiple-choice
# literary questions; each correct answer damages a shared "boss". If the whole
# community drops the boss's HP to zero before time runs out, every contributor
# wins Kitobcha. Inclusive: even one correct answer counts.
# ─────────────────────────────────────────────────────────────────────────────
class CastleGame(BaseModel):
    STATUS_SCHEDULED = "scheduled"
    STATUS_LIVE = "live"
    STATUS_FINISHED = "finished"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Rejalashtirilgan"), (STATUS_LIVE, "Jonli"),
        (STATUS_FINISHED, "Tugagan"),
    ]
    title = models.CharField(max_length=120, default="Bilim Qal'asi")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    boss_name = models.CharField(max_length=60, default="Bilim Ajdari")
    boss_hp_max = models.PositiveIntegerField(default=300)
    boss_hp = models.PositiveIntegerField(default=300)
    damage_per_hit = models.PositiveIntegerField(default=10)
    questions = models.JSONField(default=list, help_text='[{"q","options":[4],"correct":idx}]')
    question_seconds = models.PositiveIntegerField(default=20)
    victory = models.BooleanField(default=False)
    rewarded = models.BooleanField(default=False)

    class Meta:
        db_table = "castle_games"
        verbose_name = "Bilim Qal'asi — O'yin"
        verbose_name_plural = "Bilim Qal'asi — O'yinlar"
        ordering = ("-starts_at",)

    def __str__(self):
        return f"Qal'a #{self.id} — {self.status} (HP {self.boss_hp}/{self.boss_hp_max})"


class CastleHit(BaseModel):
    game = models.ForeignKey(CastleGame, on_delete=models.CASCADE, related_name="hits")
    user = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE, related_name="castle_hits")
    q_index = models.PositiveSmallIntegerField()
    is_correct = models.BooleanField(default=False)

    class Meta:
        db_table = "castle_hits"
        unique_together = ("game", "user", "q_index")
        ordering = ("created_at",)


# ─────────────────────────────────────────────────────────────────────────────
# Emoji Kitob — live "guess the book from emojis" multiple-choice game. Each
# question shows emojis; players pick the book from 4 options. Correct answers
# score; top scorers earn Kitobcha.
# ─────────────────────────────────────────────────────────────────────────────
class EmojiGame(BaseModel):
    STATUS_SCHEDULED = "scheduled"
    STATUS_LIVE = "live"
    STATUS_FINISHED = "finished"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Rejalashtirilgan"), (STATUS_LIVE, "Jonli"),
        (STATUS_FINISHED, "Tugagan"),
    ]
    title = models.CharField(max_length=120, default="Emoji Kitob")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    questions = models.JSONField(default=list, help_text='[{"emoji","options":[4],"correct":idx}]')
    answer_seconds = models.PositiveIntegerField(default=15)
    reveal_seconds = models.PositiveIntegerField(default=5)
    scored_indices = models.JSONField(default=list)
    rewarded = models.BooleanField(default=False)

    class Meta:
        db_table = "emoji_games"
        verbose_name = "Emoji Kitob — O'yin"
        verbose_name_plural = "Emoji Kitob — O'yinlar"
        ordering = ("-starts_at",)

    def __str__(self):
        return f"Emoji #{self.id} — {self.status}"


class EmojiAnswer(BaseModel):
    game = models.ForeignKey(EmojiGame, on_delete=models.CASCADE, related_name="answers")
    user = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE, related_name="emoji_answers")
    q_index = models.PositiveSmallIntegerField()
    choice = models.PositiveSmallIntegerField()
    is_correct = models.BooleanField(default=False)

    class Meta:
        db_table = "emoji_answers"
        unique_together = ("game", "user", "q_index")
        ordering = ("created_at",)


class EmojiScore(BaseModel):
    game = models.ForeignKey(EmojiGame, on_delete=models.CASCADE, related_name="scores")
    user = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE, related_name="emoji_scores")
    points = models.PositiveIntegerField(default=0)
    reward = models.PositiveIntegerField(default=0)
    rewarded = models.BooleanField(default=False)

    class Meta:
        db_table = "emoji_scores"
        unique_together = ("game", "user")
        ordering = ("-points", "created_at")
