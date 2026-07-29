import io
import json
import os
import zipfile
from datetime import datetime, timedelta

import requests
from django.contrib import admin, messages
from django.contrib.auth.models import User, Group
from django.core import serializers
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone

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
            "fields": ("referral_code", "ball", "is_registered", "is_blocked", "is_admin",
                       "trial_premium_until")
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
        'grants_premium_days', 'sort_order', 'created_at',
    )
    list_filter = ('is_active',)
    list_editable = ('price_kitobcha', 'stock_qty', 'is_active', 'sort_order')
    search_fields = ('name', 'description')
    fields = (
        'name', 'description', 'image', 'price_kitobcha',
        'stock_qty', 'sort_order', 'is_active', 'grants_premium_days',
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            _announce_new_shop_product(obj)


def _announce_new_shop_product(product):
    """New shop items are announced to the groups (not DMed) — mirrors the
    bot-wizard announcement in shop_admin.py, for products added straight
    from the Django admin instead."""
    token = os.environ.get("API_TOKEN", "")
    if not token:
        return
    boys = os.environ.get("BOYS_GROUP_ID", "").strip()
    girls = os.environ.get("GIRLS_GROUP_ID", "").strip()
    general = "-1002237773868"
    group_ids = []
    for gid in [general, boys, girls]:
        if gid and gid not in group_ids:
            group_ids.append(gid)

    from django.utils.html import escape as _esc
    desc = (product.description or "").strip()
    desc_line = f"\n{_esc(desc)}\n" if desc else ""
    stock_label = "cheksiz" if product.stock_qty is None else str(product.stock_qty)
    text = (
        "🛍 <b>Do'konga yangi mahsulot qo'shildi!</b>\n\n"
        f"<b>{_esc(product.name)}</b>\n"
        f"{desc_line}\n"
        f"💰 <b>{product.price_kitobcha} Kitobcha</b> • 📦 {stock_label}\n\n"
        "Sotib olish uchun: «🛒 Do'kon» bo'limiga o'ting!"
    )

    for gid in group_ids:
        try:
            if product.image:
                with product.image.open("rb") as f:
                    requests.post(
                        f"https://api.telegram.org/bot{token}/sendPhoto",
                        data={"chat_id": gid, "caption": text, "parse_mode": "HTML"},
                        files={"photo": f},
                        timeout=15,
                    )
            else:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data={"chat_id": gid, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": "true"},
                    timeout=10,
                )
        except Exception as e:
            print(f"admin ShopProduct announce to {gid} failed: {e}")


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


@admin.register(models.StreakFreezeCoverage)
class StreakFreezeCoverageAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'created_at')
    list_filter = ('date',)
    search_fields = ('user__full_name', 'user__telegram_id')


@admin.register(models.LeaderboardSponsor)
class LeaderboardSponsorAdmin(admin.ModelAdmin):
    list_display = ('user', 'used_at', 'created_at')
    list_filter = ('used_at',)
    search_fields = ('user__full_name', 'user__telegram_id')


@admin.register(models.ReferralBoom)
class ReferralBoomAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'image', 'planned_days', 'is_active', 'is_queued', 'start_at', 'end_at',
        'tier1_reward', 'tier1_cap', 'tier2_reward', 'total_reminders',
    )
    list_filter = ('is_active', 'is_queued')
    actions = ('queue_next_rotation', 'launch_now', 'launch_default_now', 'finalize_now')

    @admin.action(description="📌 Keyingi navbatga BOOM qo'yish (rotatsiya)")
    def queue_next_rotation(self, request, queryset):
        from tgbot.tasks import queue_referral_boom
        boom_id = queue_referral_boom()
        self.message_user(
            request,
            f"Referal BOOM keyingi 3-kunlik challenge navbatiga qo'yildi — id={boom_id}",
            messages.SUCCESS,
        )

    @admin.action(description="🚀 Tanlangan BOOM'ni hozir e'lon qilish (shu qatordagi sarlavha/rasm/mukofot bilan)")
    def launch_now(self, request, queryset):
        from tgbot.tasks import launch_referral_boom
        boom = queryset.first()
        if not boom:
            self.message_user(request, "Avval bitta BOOM qatorini belgilang.", messages.WARNING)
            return
        if queryset.count() > 1:
            self.message_user(
                request,
                "Faqat bittasi ishga tushirildi — birdaniga bir nechta BOOM'ni e'lon qilib bo'lmaydi.",
                messages.WARNING,
            )
        boom_id = launch_referral_boom(boom_id=boom.id)
        self.message_user(request, f"Referal BOOM e'lon qilindi — id={boom_id}", messages.SUCCESS)

    @admin.action(description="🚀 Standart (3 kunlik) BOOM'ni hozir e'lon qilish (yangi qator yaratadi)")
    def launch_default_now(self, request, queryset):
        from tgbot.tasks import launch_referral_boom
        boom_id = launch_referral_boom()
        self.message_user(request, f"Referal BOOM e'lon qilindi — id={boom_id}", messages.SUCCESS)

    @admin.action(description="🏁 Tanlangan BOOM(lar)ni yakunlash")
    def finalize_now(self, request, queryset):
        from tgbot.tasks import finalize_referral_boom
        for boom in queryset:
            finalize_referral_boom(boom.id)
        self.message_user(request, "Yakunlandi.", messages.SUCCESS)


@admin.register(models.ReferralBoomParticipant)
class ReferralBoomParticipantAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'boom', 'referrals_count', 'kitobcha_earned',
        'reminders_sent', 'rules_sent', 'joined_at',
    )
    list_filter = ('boom', 'rules_sent')
    search_fields = ('user__full_name', 'user__telegram_id')
    readonly_fields = (
        'boom', 'user', 'joined_at', 'rules_sent', 'referrals_count',
        'kitobcha_earned', 'reminder_schedule', 'reminders_sent',
        'used_reminder_keys', 'created_at', 'updated_at',
    )


@admin.register(models.BookQuizRound)
class BookQuizRoundAdmin(admin.ModelAdmin):
    list_display = ('id', 'correct_title', 'is_active', 'reward', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('correct_title', 'conclusion')
    readonly_fields = ('created_at', 'updated_at')

    actions = ['post_quiz_now']

    @admin.action(description="Hozir yangi viktorina yuborish")
    def post_quiz_now(self, request, queryset):
        from tgbot.tasks import post_book_quiz
        post_book_quiz.delay()
        self.message_user(request, "Yangi viktorina yuborilmoqda…")


@admin.register(models.BookQuizAnswer)
class BookQuizAnswerAdmin(admin.ModelAdmin):
    list_display = ('user', 'quiz_round', 'chosen_index', 'is_correct', 'rewarded', 'created_at')
    list_filter = ('is_correct', 'rewarded')
    search_fields = ('user__full_name', 'user__telegram_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(models.BookQuizPromoState)
class BookQuizPromoStateAdmin(admin.ModelAdmin):
    list_display = ('launched_on', 'last_sent_on')


################################################################################
#                            KITOB ZANJIRI (GAME)                              #
################################################################################

@admin.register(models.ChainWord)
class ChainWordAdmin(admin.ModelAdmin):
    list_display = ('display', 'kind', 'first_letter', 'last_letter', 'is_active')
    list_filter = ('kind', 'is_active', 'first_letter')
    list_editable = ('is_active',)
    search_fields = ('display', 'norm')
    readonly_fields = ('norm', 'first_letter', 'last_letter', 'created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        # Keep the normalized/letter fields consistent with the display value.
        from tgbot.services.chain_text import normalize, first_letter, last_letter
        obj.display = (obj.display or "").strip()
        obj.norm = normalize(obj.display)
        obj.first_letter = first_letter(obj.display)
        obj.last_letter = last_letter(obj.display)
        super().save_model(request, obj, form, change)


@admin.register(models.ChainGame)
class ChainGameAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'starts_at', 'ends_at', 'rewarded')
    list_filter = ('status', 'rewarded')
    readonly_fields = ('chain', 'used_norms', 'pending', 'created_at', 'updated_at')


@admin.register(models.ChainScore)
class ChainScoreAdmin(admin.ModelAdmin):
    list_display = ('id', 'game', 'user', 'points', 'links', 'rewarded')
    list_filter = ('rewarded',)
    search_fields = ('user__full_name', 'user__telegram_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(models.FeudGame)
class FeudGameAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'starts_at', 'ends_at', 'rewarded')
    list_filter = ('status', 'rewarded')
    readonly_fields = ('questions', 'scored_indices', 'created_at', 'updated_at')


@admin.register(models.FeudScore)
class FeudScoreAdmin(admin.ModelAdmin):
    list_display = ('id', 'game', 'user', 'points', 'reward', 'rewarded')
    list_filter = ('rewarded',)
    search_fields = ('user__full_name', 'user__telegram_id')


@admin.register(models.CastleGame)
class CastleGameAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'boss_hp', 'boss_hp_max', 'victory', 'rewarded')
    list_filter = ('status', 'victory', 'rewarded')
    readonly_fields = ('questions', 'created_at', 'updated_at')


@admin.register(models.CastleHit)
class CastleHitAdmin(admin.ModelAdmin):
    list_display = ('id', 'game', 'user', 'q_index', 'is_correct')
    list_filter = ('is_correct',)
    search_fields = ('user__full_name', 'user__telegram_id')


@admin.register(models.EmojiGame)
class EmojiGameAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'starts_at', 'ends_at', 'rewarded')
    list_filter = ('status', 'rewarded')
    readonly_fields = ('questions', 'scored_indices', 'created_at', 'updated_at')


@admin.register(models.EmojiScore)
class EmojiScoreAdmin(admin.ModelAdmin):
    list_display = ('id', 'game', 'user', 'points', 'reward', 'rewarded')
    list_filter = ('rewarded',)
    search_fields = ('user__full_name', 'user__telegram_id')


@admin.register(models.WisdomGame)
class WisdomGameAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'starts_at', 'ends_at', 'rewarded')
    list_filter = ('status', 'rewarded')
    readonly_fields = ('questions', 'scored_indices', 'created_at', 'updated_at')


@admin.register(models.WisdomScore)
class WisdomScoreAdmin(admin.ModelAdmin):
    list_display = ('id', 'game', 'user', 'points', 'streak', 'best_streak', 'reward', 'rewarded')
    list_filter = ('rewarded',)
    search_fields = ('user__full_name', 'user__telegram_id')


@admin.register(models.DetectiveGame)
class DetectiveGameAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'starts_at', 'ends_at', 'rewarded')
    list_filter = ('status', 'rewarded')
    readonly_fields = ('rounds', 'solved', 'created_at', 'updated_at')


@admin.register(models.DetectiveScore)
class DetectiveScoreAdmin(admin.ModelAdmin):
    list_display = ('id', 'game', 'user', 'points', 'solved_count', 'reward', 'rewarded')
    list_filter = ('rewarded',)
    search_fields = ('user__full_name', 'user__telegram_id')


@admin.register(models.SurvivalGame)
class SurvivalGameAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'max_lives', 'jackpot', 'rewarded')
    list_filter = ('status', 'rewarded')
    readonly_fields = ('questions', 'scored_indices', 'created_at', 'updated_at')


@admin.register(models.SurvivalPlayer)
class SurvivalPlayerAdmin(admin.ModelAdmin):
    list_display = ('id', 'game', 'user', 'lives', 'correct_count', 'eliminated', 'reward', 'rewarded')
    list_filter = ('eliminated', 'rewarded')
    search_fields = ('user__full_name', 'user__telegram_id')


@admin.register(models.QuizGame)
class QuizGameAdmin(admin.ModelAdmin):
    list_display = ('id', 'flavor', 'title', 'status', 'team_a_points', 'team_b_points', 'rewarded')
    list_filter = ('flavor', 'status', 'rewarded')
    readonly_fields = ('questions', 'scored_indices', 'team_a', 'team_b', 'created_at', 'updated_at')


@admin.register(models.QuizScore)
class QuizScoreAdmin(admin.ModelAdmin):
    list_display = ('id', 'game', 'user', 'points', 'team', 'reward', 'rewarded')
    list_filter = ('team', 'rewarded')
    search_fields = ('user__full_name', 'user__telegram_id')


@admin.register(models.GameSequence)
class GameSequenceAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'slot', 'game_types', 'current_index',
                     'current_game_type', 'current_game_id', 'completed')
    list_filter = ('slot', 'completed')
    readonly_fields = ('created_at', 'updated_at')


################################################################################
#                          SAYT STATISTIKASI (ANALYTICS)                       #
################################################################################

SECTION_LABELS = {
    "site": "Bosh sahifa", "library": "Kutubxona", "shop": "Do'kon",
    "cabinet": "Kabinet", "chain": "Zanjiri (o'yin)", "feud": "Ko'pchilik (o'yin)",
    "castle": "Qal'a (o'yin)", "emoji": "Emoji (o'yin)", "wisdom": "Hikmat (o'yin)",
    "detective": "Detektiv (o'yin)", "survival": "Omon qolish (o'yin)",
    "quiz-twofacts": "Ikki haqiqat", "quiz-impostor": "Kim yolg'onchi",
    "quiz-connection": "Bog'lanish", "quiz-teams": "Jamoa jangi",
    "quiz-timeline": "Vaqt mashinasi", "quiz-matchbook": "Muallif-asar",
    "quiz-reverse": "Teskari viktorina",
}


@admin.register(models.SiteEvent)
class SiteEventAdmin(admin.ModelAdmin):
    """Raw event log doubles as the Statistika dashboard: `changelist_view`
    injects section/button aggregates above the standard filterable table."""
    change_list_template = "admin/tgbot/siteevent/change_list.html"
    list_display = ("id", "created_at", "event_type", "section", "label", "user")
    list_filter = ("event_type", "section", "created_at")
    search_fields = ("section", "label", "user__full_name", "user__username")
    date_hierarchy = "created_at"

    RANGE_CHOICES = {
        "today": ("Bugun", 1),
        "7d": ("So'nggi 7 kun", 7),
        "30d": ("So'nggi 30 kun", 30),
        "all": ("Hammasi", None),
    }

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        range_key = request.GET.get("range", "7d")
        if range_key not in self.RANGE_CHOICES:
            range_key = "7d"
        _, days = self.RANGE_CHOICES[range_key]

        qs = models.SiteEvent.objects.all()
        if days is not None:
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))

        top_sections = list(
            qs.values("section")
              .annotate(
                  views=Count("id", filter=Q(event_type=models.SiteEvent.TYPE_PAGEVIEW)),
                  click_count=Count("id", filter=Q(event_type=models.SiteEvent.TYPE_CLICK)),
                  users=Count("user", distinct=True),
              )
              .order_by("-views", "-click_count")[:30]
        )
        for row in top_sections:
            row["display"] = SECTION_LABELS.get(row["section"], row["section"])

        top_buttons = list(
            qs.filter(event_type=models.SiteEvent.TYPE_CLICK)
              .exclude(label="")
              .values("section", "label")
              .annotate(clicks=Count("id"))
              .order_by("-clicks")[:30]
        )
        for row in top_buttons:
            row["display"] = SECTION_LABELS.get(row["section"], row["section"])

        extra_context.update({
            "range_key": range_key,
            "range_choices": self.RANGE_CHOICES,
            "total_pageviews": qs.filter(event_type=models.SiteEvent.TYPE_PAGEVIEW).count(),
            "total_clicks": qs.filter(event_type=models.SiteEvent.TYPE_CLICK).count(),
            "total_users": qs.exclude(user__isnull=True).values("user").distinct().count(),
            "top_sections": top_sections,
            "top_buttons": top_buttons,
        })
        return super().changelist_view(request, extra_context=extra_context)
