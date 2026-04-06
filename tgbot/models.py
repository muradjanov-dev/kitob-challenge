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

from django.db.models import F
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

    def update_ball(self, is_completed: bool, ball: int) -> None:
        ball = Decimal(str(ball))
        with transaction.atomic():
            self.refresh_from_db()
            self.ball = self.ball + ball if is_completed else self.ball - ball
            self.save(update_fields=["ball"])

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
    total_pages = models.PositiveIntegerField(default=1)
    current_page = models.PositiveIntegerField(default=0)

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

    def __str__(self):
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


class Hour(models.Model):
    time = models.TimeField(verbose_name=_("Time"))

    class Meta:
        verbose_name = _("Hour")
        verbose_name_plural = _("Hours")

    def __str__(self):
        return self.time.strftime("%H:%M")


class Habit(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        COMPLETED = "completed", _("Completed")

    name = models.CharField(
        max_length=255,
        verbose_name=_("Name")
    )
    duration = models.PositiveIntegerField(
        verbose_name=_("Duration (in days)")
    )
    reminders_per_day = models.PositiveSmallIntegerField(
        verbose_name=_("Number of daily reminders"),
        null=True,
        blank=True
    )
    user = models.ForeignKey(
        to=TelegramProfile,
        on_delete=models.CASCADE,
        related_name="habits",
        verbose_name=_("User")
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name=_("Status")
    )
    completed_days = models.PositiveSmallIntegerField(
        verbose_name=_("Completed days"),
        default=0
    )
    hours = models.ManyToManyField(
        to=Hour,
        related_name="habits",
        verbose_name=_("Reminder hours")
    )
    notification_must_be_sent = models.BooleanField(
        verbose_name=_("Notification must be sent"),
        default=True
    )

    class Meta:
        verbose_name = _("Habit")
        verbose_name_plural = _("Habits")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()}) - {self.user.username}"

    @transaction.atomic
    def set_notification_must_be_sent_false(self):
        habit = Habit.objects.select_for_update().get(id=self.id)
        habit.notification_must_be_sent = False
        habit.save(update_fields=["notification_must_be_sent"])

    @transaction.atomic
    def set_notification_must_be_sent_true(self):
        habit = Habit.objects.select_for_update().get(id=self.id)
        habit.notification_must_be_sent = True
        habit.save(update_fields=["notification_must_be_sent"])

    @transaction.atomic
    def set_completed_days(self):
        habit = Habit.objects.select_for_update().get(id=self.id)
        habit.completed_days = F("completed_days") + 1
        habit.save(update_fields=["completed_days"])
        habit.refresh_from_db()


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
        """To‘lovni `paid` holatiga o‘tkazish."""
        self.status = 'paid'
        self.save()

    def __str__(self) -> str:
        return f"""{self.user} | {self.start_date.strftime("%d/%m/%Y")}-{self.end_date.strftime("%d/%m/%Y")}"""


class Action(BaseModel):
    class Status(models.TextChoices):
        WAITING = "waiting", _("Waiting")
        DONE = "done", _("Done")
        NOT_DONE = "not_done", _("Not Done")

    user = models.ForeignKey(
        to=TelegramProfile,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name=_("User")
    )
    habit = models.ForeignKey(
        to=Habit,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name=_("Habit")
    )
    hour = models.ForeignKey(
        to=Hour,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name=_("Hour")
    )
    points_scored = models.BooleanField(
        verbose_name=_("Points scored"),
        default=False
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.WAITING,
        verbose_name=_("Status")
    )

    @transaction.atomic
    def set_status(self, status: str) -> None:
        action = Action.objects.select_for_update().get(id=self.id)
        if status == "done":
            action.status = self.Status.DONE
        elif status == "not_done":
            action.status = self.Status.NOT_DONE
        action.save(update_fields=["status"])

    @transaction.atomic
    def set_points_scored(self) -> None:
        action = Action.objects.select_for_update().get(id=self.id)
        action.points_scored = True
        action.save(update_fields=["points_scored"])

    class Meta:
        verbose_name = _("Action")
        verbose_name_plural = _("Actions")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.habit.name} - {self.hour.time.strftime('%H:%M')}"


auditlog.register(RequiredGroup)
auditlog.register(TelegramProfile)
auditlog.register(TelegramBot)
auditlog.register(Habit)


class Meta:
    verbose_name = _("Quiz")
    verbose_name_plural = _("Quizzes")
    db_table = "quizzes"


class Contest(BaseModel):
    name = models.CharField(max_length=255, verbose_name=_("Contest Name"))
    start_date = models.DateTimeField(verbose_name=_("Start Date"))
    req_referrals = models.PositiveIntegerField(
        default=0, verbose_name=_("Required Referrals"))
    created_by = models.ForeignKey(
        TelegramProfile,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Created By")
    )
    is_active = models.BooleanField(default=False, verbose_name=_("Is Active"))
    is_notified = models.BooleanField(
        default=False, verbose_name=_("Is Notified"))
    is_started = models.BooleanField(
        default=False, verbose_name=_("Is Started"))
    is_finished = models.BooleanField(
        default=False, verbose_name=_("Is Finished"))

    notification_date = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Notification Date"))
    notification_task_id = models.CharField(
        max_length=255, null=True, blank=True, verbose_name=_("Notification Task ID"))
    start_task_id = models.CharField(
        max_length=255, null=True, blank=True, verbose_name=_("Start Task ID"))

    def save(self, *args, **kwargs):
        old_instance = None
        # Auto-set notification_date if not set, default to 2 mins before start
        if not self.notification_date and self.start_date:
            self.notification_date = self.start_date - \
                timezone.timedelta(minutes=2)

        # Determine if notification_date changed
        old_notification_date = None
        old_start_date_for_notif = None
        if self.pk:
            old_instance = Contest.objects.filter(pk=self.pk).first()
            if old_instance:
                old_notification_date = old_instance.notification_date
                old_start_date_for_notif = old_instance.start_date

        # If start_date changed, update notification_date (if it wasn't manually changed)
        # Assuming we always want 2 mins buffer if start date shifts
        if old_start_date_for_notif and self.start_date != old_start_date_for_notif:
            self.notification_date = self.start_date - \
                timezone.timedelta(minutes=2)

        super(Contest, self).save(*args, **kwargs)

        # Schedule/Reschedule if date changed and is in future
        if self.notification_date and self.notification_date != old_notification_date:
            from src.celery_app import app
            from tgbot.tasks import notify_contest_participants

            # Revoke old task if exists
            if self.notification_task_id:
                app.control.revoke(self.notification_task_id, terminate=True)
                self.notification_task_id = None

            # Schedule new task
            # Calculate execute_at time
            execute_at = self.notification_date
            now = timezone.now()

            # If notification time passed but contest hasn't started, send NOW
            if execute_at < now and self.start_date > now and not self.is_notified:
                execute_at = now

            if execute_at >= now and not self.is_notified:
                task = notify_contest_participants.apply_async(
                    args=[self.id],
                    eta=execute_at
                )
                self.notification_task_id = task.id
                # Avoid recursion loop by updating only specific fields
                Contest.objects.filter(pk=self.pk).update(
                    notification_task_id=task.id)

        # If date cleared, revoke task
        elif self.notification_date is None and old_notification_date is not None:
            if self.notification_task_id:
                app.control.revoke(self.notification_task_id, terminate=True)
                Contest.objects.filter(pk=self.pk).update(
                    notification_task_id=None)

        # ---------------------------
        # Start Task Management
        # ---------------------------
        old_start_date = None
        if self.pk and old_instance:  # old_instance fetched above
            old_start_date = old_instance.start_date

        start_date_changed = self.start_date != old_start_date

        # If start date changed or new contest, and it's active and not started
        if (start_date_changed or not self.pk) and self.is_active and not self.is_started and not self.is_finished:
            from src.celery_app import app
            from tgbot.tasks import start_contest_by_id

            # Revoke old start task if exists
            if self.start_task_id:
                print(f"Revoking old start task: {self.start_task_id}")
                app.control.revoke(self.start_task_id, terminate=True)
                self.start_task_id = None
                # Update DB to clear ID immediately (optional but safer)
                Contest.objects.filter(pk=self.pk).update(start_task_id=None)

            # Schedule new task
            if self.start_date > timezone.now():
                print(f"Scheduling start task for {self.start_date}")
                task = start_contest_by_id.apply_async(
                    args=[self.id],
                    eta=self.start_date
                )
                self.start_task_id = task.id
                Contest.objects.filter(pk=self.pk).update(
                    start_task_id=task.id)
            else:
                # If start date is in the past/now, maybe run immediately?
                # Or user manually handles it?
                # Let's schedule immediately if it's "close enough" or just let it run.
                # Assuming if date is past, we want to start NOW.
                print(f"Start date is now/past. Scheduling immediately.")
                task = start_contest_by_id.apply_async(args=[self.id])
                self.start_task_id = task.id
                Contest.objects.filter(pk=self.pk).update(
                    start_task_id=task.id)

        # If cancelled (set inactive) or finished, revoke task
        if (not self.is_active or self.is_finished) and self.start_task_id:
            from src.celery_app import app
            app.control.revoke(self.start_task_id, terminate=True)
            self.start_task_id = None
            Contest.objects.filter(pk=self.pk).update(start_task_id=None)

    class Meta:
        verbose_name = _("Contest")
        verbose_name_plural = _("Contests")
        db_table = "contests"


class Question(BaseModel):
    contest = models.ForeignKey(
        Contest,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name=_("Contest")
    )
    question = models.TextField(verbose_name=_("Question"))
    # List of strings: ["Option A", "Option B"]
    options = models.JSONField(verbose_name=_("Options"))
    correct_option = models.PositiveSmallIntegerField(
        verbose_name=_("Correct Option Index"),
        help_text=_(
            "Index of the correct option in the options list (starts from 0)")
    )
    explanation = models.TextField(
        verbose_name=_("Explanation"),
        blank=True,
        null=True
    )
    order = models.PositiveIntegerField(default=1, verbose_name=_("Order"))

    def __str__(self):
        return self.question[:50]

    class Meta:
        verbose_name = _("Question")
        verbose_name_plural = _("Questions")
        ordering = ["order"]
        db_table = "questions"


class ContestParticipant(BaseModel):
    contest = models.ForeignKey(
        Contest, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        TelegramProfile, on_delete=models.CASCADE, related_name="contest_participations")
    total_score = models.IntegerField(default=0)
    total_time = models.FloatField(
        default=0.0, help_text="Total time in seconds")
    is_finished = models.BooleanField(default=False)
    current_question_index = models.IntegerField(default=0)
    last_question_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("contest", "user")
        indexes = [
            # For ranking
            models.Index(fields=['contest', 'total_score', 'total_time']),
        ]


class ContestSubmission(BaseModel):
    participant = models.ForeignKey(
        ContestParticipant, on_delete=models.CASCADE, related_name="submissions")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_option = models.IntegerField()
    is_correct = models.BooleanField(default=False)
    time_taken = models.FloatField(help_text="Time taken in seconds")

    class Meta:
        indexes = [
            models.Index(fields=['participant', 'question']),
        ]


class PollState(BaseModel):
    poll_id = models.CharField(max_length=255, unique=True, db_index=True)
    user = models.ForeignKey(
        TelegramProfile, on_delete=models.CASCADE, related_name="poll_states")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.user} - {self.question}"

    class Meta:
        db_table = "poll_states"
        verbose_name = _("Poll State")
        verbose_name_plural = _("Poll States")
