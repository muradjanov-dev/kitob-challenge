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
    contact_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Admin contact count"),
        help_text="Number of times the user has successfully messaged the admin.",
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


class BooksToRead(BaseModel):
    user = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE)
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
