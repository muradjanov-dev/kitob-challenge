from __future__ import absolute_import, unicode_literals
import os
import environ

from celery import Celery
from celery.schedules import crontab


env = environ.Env()
env.read_env(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE",
                      env.str("DJANGO_SETTINGS_MODULE"))

app = Celery('src')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'send-daily-message-at-9': {
        'task': 'tgbot.tasks.send_daily_message',
        'schedule': crontab(hour=9, minute=0),
    },

    'send-daily-message-at-21': {
        'task': 'tgbot.tasks.send_daily_message',
        'schedule': crontab(hour=21, minute=0),
    },

    'send-daily-top-read-pages-user': {
        'task': 'tgbot.tasks.daily_top_read_user',
        'schedule': crontab(hour=23, minute=35),
    },

    'daily-top-readers-kitobcha-reward': {
        'task': 'tgbot.tasks.daily_top_readers_reward',
        'schedule': crontab(hour=23, minute=55),
    },

    'send-weekly-top-read-pages-user': {
        'task': 'tgbot.tasks.weekly_top_read_user',
        'schedule': crontab(hour=23, minute=5, day_of_week=6),
    },

    'send-monthly-top-read-pages-user': {
        'task': 'tgbot.tasks.monthly_top_read_user',
        'schedule': crontab(hour=0, minute=0, day_of_month=1),
    },

    'send-yearly-top-read-pages-user': {
        'task': 'tgbot.tasks.yearly_top_read_user',
        'schedule': crontab(hour=23, minute=59, day_of_month='31', month_of_year='12'),
    },

    # 3-monthly top (1st of Jan/Apr/Jul/Oct at 00:10).
    'send-3-monthly-top-read-pages-user': {
        'task': 'tgbot.tasks.three_months_top_read_user',
        'schedule': crontab(hour=0, minute=10, day_of_month=1, month_of_year='1,4,7,10'),
    },

    # Daily features overview — sent once at 11:00 Tashkent.
    'send-daily-features': {
        'task': 'tgbot.tasks.send_daily_features',
        'schedule': crontab(hour=11, minute=0),
    },

    'send-daily-users-unread-book': {
        'task': 'tgbot.tasks.users_unread_book',
        'schedule': crontab(hour=22, minute=0)
    },

    'send_three_days_report': {
        'task': 'tgbot.tasks.weekly_report_for_general',
        'schedule': crontab(hour=0, minute=17, day_of_month='*/3')
    },

    # Pool-based admin reminders — fire 09:00 and 21:00 (Tashkent), each time
    # the worker picks a random text from the active ScheduledReminder pool.
    'admin-reminder-pool-09': {
        'task': 'tgbot.tasks.broadcast_random_pool_reminder',
        'schedule': crontab(hour=9, minute=0),
    },
    'admin-reminder-pool-21': {
        'task': 'tgbot.tasks.broadcast_random_pool_reminder',
        'schedule': crontab(hour=21, minute=0),
    },

    # Daily 3x random inspiration with "Hisobot jo'natish" CTA button (Tashkent).
    'random-inspiration-07': {
        'task': 'tgbot.tasks.send_random_inspiration',
        'schedule': crontab(hour=7, minute=0),
    },
    'random-inspiration-13-30': {
        'task': 'tgbot.tasks.send_random_inspiration',
        'schedule': crontab(hour=13, minute=30),
    },
    'random-inspiration-21': {
        'task': 'tgbot.tasks.send_random_inspiration',
        'schedule': crontab(hour=21, minute=0),
    },

    # Daily progress bar — refreshed at 00:01 Tashkent.
    'daily-progress-broadcast': {
        'task': 'tgbot.tasks.daily_progress_broadcast',
        'schedule': crontab(hour=0, minute=1),
    },

    # Safety net — every hour, repin (or resend if deleted) the latest progress.
    'ensure-progress-pin': {
        'task': 'tgbot.tasks.ensure_progress_pin',
        'schedule': crontab(minute=15),
    },

    # Reminder for users who haven't reported by 12:00 Tashkent.
    'daily-no-report-reminder': {
        'task': 'tgbot.tasks.daily_no_report_reminder',
        'schedule': crontab(hour=12, minute=0),
    },

    # End-of-day percentile DM with 72h TTL — runs after daily_top_readers_reward.
    'end-of-day-percentile': {
        'task': 'tgbot.tasks.end_of_day_percentile',
        'schedule': crontab(hour=23, minute=58),
    },

    # Scrub auto-delete queue every minute.
    'process-scheduled-deletions': {
        'task': 'tgbot.tasks.process_scheduled_deletions',
        'schedule': crontab(),
    },
}

# Use Tashkent local time for crontab schedules (matches admin-set HH:MM).
app.conf.timezone = 'Asia/Tashkent'
