from django import forms
import json
from django.contrib import admin, messages
from django.contrib.auth.models import User, Group
from django.db.models import Count

from . import models
from tgbot.tasks import weekly_report_for_general, run_total_pages, \
    daily_top_read_user, weekly_top_read_user
from tgbot.mixins import TabbedTranslationAdmin, TranslationRequiredMixin


admin.site.unregister(User)
admin.site.unregister(Group)


################################################################################
#                               USER SYSTEM                                    #
################################################################################

@admin.register(models.Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    list_display_links = ("id", "name")
    search_fields = ("name",)


class ReferralCountFilter(admin.SimpleListFilter):
    title = 'Referral Count'
    parameter_name = 'referral_count'

    def lookups(self, request, model_admin):
        return (
            ('has_referrals', 'Has referrals'),
            ('no_referrals', 'No referrals'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'has_referrals':
            return queryset.filter(referrals__isnull=False).distinct()
        if self.value() == 'no_referrals':
            return queryset.filter(referrals__isnull=True)
        return queryset


@admin.register(models.TelegramProfile)
class TelegramProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "username",
                    "language", "ball", "referral_count", "referral_code", "is_admin", "is_registered", "created_at", "updated_at")
    list_display_links = ("id", "full_name")
    list_filter = ("language", "is_registered", "group",
                   "is_admin", ReferralCountFilter)
    search_fields = ("username", "full_name", "referral_code")

    fieldsets = (
        ("Identify", {
            "fields": ("full_name", "username", "telegram_id", "phone_number")
        }),
        ("Profile Details", {
            "fields": ("language", "gender", "region", "group")
        }),
        ("System Status", {
            "fields": ("referral_code", "ball", "is_registered", "is_blocked", "is_admin")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    readonly_fields = ("created_at", "updated_at", "referral_count")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            _referral_count=Count("referrals", distinct=True),
        )
        return queryset

    def referral_count(self, obj):
        return obj._referral_count

    referral_count.admin_order_field = '_referral_count'
    referral_count.short_description = 'Referrals'

    actions = ['trigger_total_pages_by_user',
               'trigger_daily_top_read_user_action_button', 'trigger_weekly_top_read_user_action_button']

    def trigger_total_pages_by_user(self, request, queryset):
        """
        Admin action to trigger the Celery task to send total pages
        """
        run_total_pages.delay()
        self.message_user(
            request,
            "The task to send total pages has been triggered successfully!",
        )

    trigger_total_pages_by_user.short_description = "Send total pages to Telegram group"

    def trigger_daily_top_read_user_action_button(self, request, queryset):
        """
        Admin action to trigger the Celery task to send top 20 users for today
        """
        daily_top_read_user.delay()
        self.message_user(
            request,
            "The task to send top 20 students has been triggered successfully!"
        )

    trigger_daily_top_read_user_action_button.short_description = "Send top 20 pages to Telegram group"

    def trigger_weekly_top_read_user_action_button(self, request, queryset):
        """
        Admin action to trigger the Celery task to send top 20 users for week
        """
        weekly_top_read_user.delay()
        self.message_user(
            request,
            "The task to send top 20 students has been triggered successfully!"
        )

    trigger_weekly_top_read_user_action_button.short_description = "Send top 20 pages in week to Telegram group"


@admin.register(models.UserReferal)
class UserReferalAdmin(admin.ModelAdmin):
    list_display = ("id", "referrer", "referred_user", "created_at")
    list_display_links = ("id", "referrer")
    search_fields = ("referrer__username", "referrer__full_name",
                     "referred_user__username", "referred_user__full_name")
    list_filter = ("created_at",)


################################################################################
#                               GROUP SYSTEM                                   #
################################################################################

@admin.register(models.Group)
class GroupAdmin(TabbedTranslationAdmin):
    list_display = ("id", "title", "created_at")
    list_display_links = ("id", "title")

    actions = ["trigger_three_days_challenge"]

    def trigger_three_days_challenge(self, request, queryset):
        if queryset.exists():
            weekly_report_for_general.delay()
            self.message_user(
                request,
                "Weekly report task has been triggered successfully!",
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                "Weekly report task has not been triggered successfully!",
                messages.WARNING
            )

    trigger_three_days_challenge.short_description = "Trigger weekly report for selected groups"


@admin.register(models.RequiredGroup)
class RequiredGroupAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "title", "bot", "created_at")
    list_display_links = ("id", "chat_id")
    search_fields = ("chat_id", "title")
    list_filter = ("bot",)



################################################################################
#                            BOOKS & CONFIRMATION                              #
################################################################################

@admin.register(models.BooksToRead)
class BooksToReadAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "total_pages", "created_at")
    list_display_links = ("id", "title")
    search_fields = ("title", "user__full_name", "user__username")
    list_filter = ("user", "created_at")


@admin.register(models.ConfirmationReport)
class ConfirmationReportAdmin(admin.ModelAdmin):
    list_display = ('user', 'book', 'date', 'pages_read', 'display_books')
    search_fields = ('user__username', 'user__full_name', 'book')
    list_filter = ('date', 'user')
    filter_horizontal = ('books',)

    fieldsets = (
        ("Reading Info", {
            "fields": ("user", "book", "books", "pages_read", "date")
        }),
        ("Details", {
            "fields": ("spent_time", "conclusion")
        }),
    )

    def display_books(self, obj):
        return ", ".join([book.title for book in obj.books.all()])
    display_books.short_description = "Books"


################################################################################
#                               CONTEST SYSTEM                                 #
################################################################################

class QuestionInline(admin.StackedInline):
    model = models.Question
    extra = 1
    fields = ("question", "options", "correct_option", "explanation", "order")


class ContestAdminForm(forms.ModelForm):
    json_questions = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 10, 'cols': 80}),
        required=False,
        help_text="Paste JSON list of questions here. Example: [{'question': '...', 'options': ['...'], 'correct_option': 0, 'explanation': '...'}]",
        label="Import Questions from JSON"
    )

    class Meta:
        model = models.Contest
        fields = '__all__'


@admin.register(models.Contest)
class ContestAdmin(admin.ModelAdmin):
    form = ContestAdminForm
    list_display = ("id", "name", "start_date",
                    "is_active", "is_started", "created_by")
    list_filter = ("is_active", "is_started", "start_date")
    list_editable = ("is_active", "is_started")
    search_fields = ("name",)
    inlines = [QuestionInline]

    fieldsets = (
        (None, {
            "fields": ("name", "start_date", "req_referrals", "created_by")
        }),
        ("Status (Holati)", {
            "fields": ("is_active", "is_started", "is_notified", "is_finished")
        }),
        ("Import Questions", {
            "fields": ("json_questions",),
            "classes": ("collapse",)
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        json_questions = form.cleaned_data.get('json_questions')
        if json_questions:
            try:
                questions_data = json.loads(json_questions)
                if isinstance(questions_data, list):
                    for q_data in questions_data:
                        models.Question.objects.create(
                            contest=obj,
                            question=q_data.get('question'),
                            options=q_data.get('options', []),
                            correct_option=q_data.get('correct_option', 0),
                            explanation=q_data.get('explanation', ''),
                            order=q_data.get('order', 1)
                        )
                    self.message_user(
                        request, f"{len(questions_data)} questions imported successfully.", messages.SUCCESS)
                else:
                    self.message_user(
                        request, "Invalid JSON format. Expected a list of questions.", messages.ERROR)
            except json.JSONDecodeError:
                self.message_user(
                    request, "Invalid JSON format.", messages.ERROR)


@admin.register(models.Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "contest", "question", "correct_option", "order")
    list_filter = ("contest",)
    search_fields = ("question", "contest__name")
    ordering = ("contest", "order")


@admin.register(models.ContestParticipant)
class ContestParticipantAdmin(admin.ModelAdmin):
    list_display = ("contest", "user", "total_score",
                    "total_time", "is_finished", "current_question_index")
    list_filter = ("contest", "is_finished")
    search_fields = ("user__full_name", "user__username", "contest__name")


@admin.register(models.ContestSubmission)
class ContestSubmissionAdmin(admin.ModelAdmin):
    list_display = ("get_user", "question", "selected_option",
                    "is_correct", "time_taken", "created_at")
    list_filter = ("is_correct", "participant__contest", "participant__user")
    search_fields = ("participant__user__full_name", "question__question")
    readonly_fields = ("created_at",)

    def get_user(self, obj):
        return obj.participant.user
    get_user.short_description = 'User'
    get_user.admin_order_field = 'participant__user'


################################################################################
#                               BOT & PAYMENTS                                 #
################################################################################

admin.site.register(models.TelegramBot)


@admin.register(models.DailyMessage)
class DailyMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "message")


@admin.register(models.Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "status",
                    "start_date", "end_date", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__full_name", "user__username", "amount")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    actions = ["mark_as_paid"]

    def mark_as_paid(self, request, queryset):
        """Tanlangan to‘lovlarni `paid` holatiga o‘tkazish."""
        queryset.update(status="paid")
    mark_as_paid.short_description = "To‘lovlarni 'paid' holatiga o‘tkazish"
