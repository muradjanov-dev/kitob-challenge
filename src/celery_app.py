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

    'send-daily-users-unread-book': {
        'task': 'tgbot.tasks.users_unread_book',
        'schedule': crontab(hour=22, minute=0)
    },

    'send_three_days_report': {
        'task': 'tgbot.tasks.weekly_report_for_general',
        'schedule': crontab(hour=0, minute=17, day_of_month='*/3')
    },

    'check-and-dispatch-reminders': {
        'task': 'tgbot.tasks.check_and_dispatch_reminders',
        'schedule': crontab(),  # every minute
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
}

# Use Tashkent local time for crontab schedules (matches admin-set HH:MM).
app.conf.timezone = 'Asia/Tashkent'
