import io
import json
import os
import zipfile
from datetime import datetime

import requests
from django.contrib import admin, messages
from django.contrib.auth.models import User, Group
from django.core import serializers
from django.db.models import Count, Sum
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path, reverse

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
    change_list_template = "admin/tgbot/telegramprofile/change_list.html"

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

    # ── Custom admin URLs (export + send-total-pages) ───────────────────────
    def get_urls(self):
        urls = super().get_urls()
        info = self.model._meta.app_label, self.model._meta.model_name
        custom = [
            path("export-all-users/",
                 self.admin_site.admin_view(self.export_all_users_view),
                 name="%s_%s_export_all" % info),
            path("send-total-pages/",
                 self.admin_site.admin_view(self.send_total_pages_view),
                 name="%s_%s_send_total_pages" % info),
        ]
        return custom + urls

    @staticmethod
    def _user_export_dict(user):
        """Return a JSON-serializable dict with user profile + all related rows."""
        related_managers = [
            ("books", "bookstoread_set"),
            ("book_reports", "bookreport_set"),
            ("confirmation_reports", "confirmationreport_set"),
            ("payments", "payment_set"),
            ("referrals_made", "referrals"),
        ]
        try:
            profile = serializers.serialize("python", [user])[0]
        except Exception as e:
            profile = {"_error": f"profile serialize failed: {e}"}
        related = {}
        for label, mgr_attr in related_managers:
            try:
                mgr = getattr(user, mgr_attr, None)
                if mgr is None:
                    related[label] = []
                    continue
                qs = mgr.all() if hasattr(mgr, "all") else mgr
                related[label] = serializers.serialize("python", qs)
            except Exception as e:
                related[label] = {"_error": str(e)}
        return {"profile": profile, "related": related}

    def export_all_users_view(self, request):
        users = (
            models.TelegramProfile.objects
            .all()
            .select_related("region", "group")
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for u in users:
                payload = self._user_export_dict(u)
                fname = f"user_{u.telegram_id or u.id}.json"
                zf.writestr(
                    fname,
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        resp = HttpResponse(buf.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="kitob_users_{ts}.zip"'
        return resp

    def send_total_pages_view(self, request):
        confirm_total = (
            models.ConfirmationReport.objects.aggregate(s=Sum("pages_read"))["s"] or 0
        )
        report_total = (
            models.BookReport.objects.aggregate(s=Sum("pages_read"))["s"] or 0
        )
        user_count = models.TelegramProfile.objects.count()

        text = (
            "📚 <b>Kitob Challenge — Statistika</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{user_count}</b>\n"
            f"📖 ConfirmationReport jami: <b>{confirm_total}</b> bet\n"
            f"📕 BookReport jami: <b>{report_total}</b> bet\n"
            f"📊 Jami: <b>{confirm_total + report_total}</b> bet"
        )

        token = os.environ.get("API_TOKEN")
        admins_raw = os.environ.get("ADMINS", "")
        admin_ids = [a.strip() for a in admins_raw.split(",") if a.strip()]
        sent, failed = 0, []
        if token and admin_ids:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            for chat_id in admin_ids:
                try:
                    r = requests.post(
                        url,
                        data={
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": "HTML",
                        },
                        timeout=5,
                    )
                    if r.ok:
                        sent += 1
                    else:
                        failed.append(f"{chat_id}: {r.status_code}")
                except Exception as e:
                    failed.append(f"{chat_id}: {e}")

        if sent:
            self.message_user(
                request,
                f"Statistics sent to {sent} admin(s). Total: {confirm_total + report_total} pages.",
                messages.SUCCESS,
            )
        if failed:
            self.message_user(
                request,
                f"Failed for: {', '.join(failed)}",
                messages.WARNING,
            )
        if not sent and not failed:
            self.message_user(
                request,
                "No admins configured (ADMINS env var is empty).",
                messages.ERROR,
            )
        return HttpResponseRedirect(
            reverse("admin:tgbot_telegramprofile_changelist")
        )


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

    actions = ["trigger_top_readers_report"]

    def trigger_top_readers_report(self, request, queryset):
        weekly_report_for_general.delay()
        self.message_user(
            request,
            "Top readers report (3/7/30 kun) has been triggered.",
            messages.SUCCESS
        )

    trigger_top_readers_report.short_description = "Send 3/7/30-day top readers report to channel"


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

################################################################################
#                               QUIZ SYSTEM                                    #
################################################################################

class QuizOptionInline(admin.TabularInline):
    model = models.QuizOption
    extra = 4

@admin.register(models.QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'quiz', 'order')
    list_filter = ('quiz',)
    search_fields = ('text',)
    inlines = [QuizOptionInline]

class QuizQuestionInline(admin.TabularInline):
    model = models.QuizQuestion
    extra = 1
    show_change_link = True

@admin.register(models.Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'creator', 'time_per_question', 'shuffle', 'created_at')
    search_fields = ('title', 'description')
    list_filter = ('created_at', 'creator')
    inlines = [QuizQuestionInline]
    
    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        if request.user.is_authenticated:
            # Try to find corresponding TelegramProfile for the admin user
            try:
                profile = models.TelegramProfile.objects.filter(is_admin=True).first()
                if profile:
                    initial['creator'] = profile.id
            except Exception:
                pass
        return initial

@admin.register(models.QuizSession)
class QuizSessionAdmin(admin.ModelAdmin):
    list_display = ('quiz', 'creator', 'status', 'is_group', 'created_at')
    list_filter = ('status', 'is_group', 'created_at')
    search_fields = ('quiz__title',)


@admin.register(models.ShopProduct)
class ShopProductAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'price_kitobcha', 'stock_qty', 'is_active',
        'sort_order', 'created_at',
    )
    list_filter = ('is_active',)
    list_editable = ('price_kitobcha', 'stock_qty', 'is_active', 'sort_order')
    search_fields = ('name', 'description')
    fields = (
        'name', 'description', 'image', 'price_kitobcha',
        'stock_qty', 'sort_order', 'is_active',
    )


@admin.register(models.ShopPurchase)
class ShopPurchaseAdmin(admin.ModelAdmin):
    list_display = (
        'code', 'user', 'product_name_snapshot', 'price_at_purchase',
        'status', 'created_at',
    )
    list_filter = ('status', 'created_at')
    list_editable = ('status',)
    search_fields = (
        'code', 'product_name_snapshot',
        'user__full_name', 'user__telegram_id',
    )
    readonly_fields = (
        'user', 'product', 'product_name_snapshot',
        'price_at_purchase', 'code', 'created_at', 'updated_at',
    )
