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

    # ── Leaderboards (group posts, not DMs) ──────────────────────────────────
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
    'send-3-monthly-top-read-pages-user': {
        'task': 'tgbot.tasks.three_months_top_read_user',
        'schedule': crontab(hour=0, minute=10, day_of_month=1, month_of_year='1,4,7,10'),
    },
    'send-3-day-top-readers': {
        'task': 'tgbot.tasks.three_day_top_report',
        'schedule': crontab(hour=19, minute=0, day_of_month='*/3'),
    },
    'send-7-day-top-readers': {
        'task': 'tgbot.tasks.seven_day_top_report',
        'schedule': crontab(hour=20, minute=0, day_of_week=0),
    },
    'send-30-day-top-readers': {
        'task': 'tgbot.tasks.thirty_day_top_report',
        'schedule': crontab(hour=12, minute=0, day_of_month=1),
    },

    # ── Group / infra tasks (not user DMs) ───────────────────────────────────
    'send-daily-users-unread-book': {
        # Posts to group chats, not individual DMs.
        'task': 'tgbot.tasks.users_unread_book',
        'schedule': crontab(hour=22, minute=0),
    },
    'daily-progress-broadcast': {
        'task': 'tgbot.tasks.daily_progress_broadcast',
        'schedule': crontab(hour=0, minute=1),
    },
    'ensure-progress-pin': {
        'task': 'tgbot.tasks.ensure_progress_pin',
        'schedule': crontab(minute=15),
    },
    'process-scheduled-deletions': {
        'task': 'tgbot.tasks.process_scheduled_deletions',
        'schedule': crontab(),
    },
    'daily-challenge-check': {
        'task': 'tgbot.tasks.daily_challenge_check',
        'schedule': crontab(hour=23, minute=50),
    },
    'announce-challenge': {
        'task': 'tgbot.tasks.announce_challenge',
        'schedule': crontab(hour=9, minute=5, day_of_month='1,4,7,10,13,16,19,22,25,28'),
    },
    'boom-reminder-tick': {
        'task': 'tgbot.tasks.boom_reminder_tick',
        'schedule': crontab(minute='*/5'),
    },
    'recompute-optimal-send-hours': {
        'task': 'tgbot.tasks.recompute_optimal_send_hours',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),
    },

    # ── Live games — 3 auto-chained per slot, twice a day (10:00 & 22:00) ────
    # Each slot randomly picks 3 of the 4 live games (Kitob Zanjiri / Ko'pchilik
    # nima dedi / Bilim Qal'asi / Emoji Kitob), no repeats, and runs them back
    # to back: game #2 starts only once #1 finishes, then #3 (see
    # start_game_sequence + _advance_game_sequence in tasks.py, hooked into the
    # chain-game-tick / games-finalize-tick below). Entry fee is a flat 25
    # Kitobcha regardless of which game is live. Admins can still start any
    # specific game anytime via the management commands.
    'games-random-morning': {
        'task': 'tgbot.tasks.start_game_sequence',
        'schedule': crontab(hour=10, minute=0),
        'args': ('morning',),
    },
    'games-random-evening': {
        'task': 'tgbot.tasks.start_game_sequence',
        'schedule': crontab(hour=22, minute=0),
        'args': ('evening',),
    },
    'chain-game-tick': {
        'task': 'tgbot.tasks.chain_game_tick',
        'schedule': crontab(minute='*/1'),
    },

    # Ko'pchilik nima dedi? + Bilim Qal'asi + Emoji Kitob — finalizes + rewards
    # each once its time is up, and (like chain-game-tick above) advances the
    # daily sequence to its next game if this one was part of it.
    'games-finalize-tick': {
        'task': 'tgbot.tasks.games_finalize_tick',
        'schedule': crontab(minute='*/1'),
    },

    # ── User DMs — hard cap of 3 per day ─────────────────────────────────────
    #
    # Slot 1 — 08:30  Kitob Viktorina (GROUP post only — never a DM)
    # Slot 2 — 10:00  Single inspiration (personalized hour OR fixed 10:00 fallback)
    # Slot 3 — 20:00  Streak warning (non-reporters only)
    # Slot 4 — 23:57  Personal daily report (everyone)
    #
    # At most 3 reminder DMs/day to any user (congratulations are event-driven
    # and are NOT counted):
    #   reporters     → inspiration + personal report            = 2
    #   non-reporters → inspiration + streak warning + report    = 3
    #
    # REMOVED to stay within budget:
    #   daily_no_report_reminder (12:00) — redundant with the 20:00 streak warning
    #   send_daily_message      (09:00 + 21:00) — duplicate of inspiration
    #   broadcast_random_pool_reminder (09:00 + 21:00) — duplicate of inspiration
    #   send_daily_features     (11:00) — bot-feature ad every day = spam; moved to weekly
    #   send_random_inspiration (13:30 + 21:00 extra slots) — one slot is enough
    #   send_viktorina_promo    (19:30) — quiz posts itself; separate promo is redundant
    #   end_of_day_percentile   (23:58) — 60 s after personal report = two DMs back-to-back;
    #                                     percentile is now shown inside personal report
    #   challenge_reminder      (18:00) — folded into streak warning at 20:00

    # Kitob Viktorina — 3x daily (GROUP posts only, never personal DMs, so they
    # don't count against the 3-DM/day budget above).
    'book-quiz-morning': {
        'task': 'tgbot.tasks.post_book_quiz',
        'schedule': crontab(hour=8, minute=30),
    },
    'book-quiz-midday': {
        'task': 'tgbot.tasks.post_book_quiz',
        'schedule': crontab(hour=14, minute=0),
    },
    'book-quiz-evening': {
        'task': 'tgbot.tasks.post_book_quiz',
        'schedule': crontab(hour=21, minute=0),
    },

    # Single daily inspiration — personalized hour wins; fixed 10:00 is the
    # fallback for users whose optimal_send_hour hasn't been computed yet.
    'random-inspiration-fallback': {
        'task': 'tgbot.tasks.send_random_inspiration',
        'schedule': crontab(hour=10, minute=0),
    },
    'personalized-inspiration': {
        'task': 'tgbot.tasks.send_personalized_inspiration',
        'schedule': crontab(minute=5),
    },

    # Evening streak warning — moved earlier (20:00 → gives users 2+ hrs to act).
    # Replaces both the old 22:00 streak warning and the 18:00 challenge reminder.
    'send-streak-warning': {
        'task': 'tgbot.tasks.send_streak_warning',
        'schedule': crontab(hour=20, minute=0),
    },

    # End-of-day personal report — the one rich DM users actually want.
    # Percentile info is already included inside this report, so the separate
    # end_of_day_percentile task at 23:58 is no longer needed.
    'send-daily-personal-report': {
        'task': 'tgbot.tasks.send_daily_personal_report',
        'schedule': crontab(hour=23, minute=57),
    },

    # ── Weekly premium DMs ────────────────────────────────────────────────────
    'send-weekly-ai-report': {
        'task': 'tgbot.tasks.send_weekly_ai_report',
        'schedule': crontab(hour=20, minute=0, day_of_week=6),  # Saturday 20:00
    },
    'send-book-recommendations': {
        'task': 'tgbot.tasks.send_book_recommendations',
        'schedule': crontab(hour=21, minute=0, day_of_week=0),  # Sunday 21:00
    },

    # Weekly bot-features overview — Friday 11:00 (once a week, not daily).
    'send-weekly-features': {
        'task': 'tgbot.tasks.send_daily_features',
        'schedule': crontab(hour=11, minute=0, day_of_week=5),  # Friday
    },

    # Premium conversion predictor — Wednesday 20:00 Tashkent.
    # Scores all free users and sends a personalised upsell to the top 200
    # candidates (score >= 40/100). Mid-week timing avoids weekend clutter
    # and is far from the Saturday AI report so Premium feels distinct.
    'send-premium-upsell': {
        'task': 'tgbot.tasks.send_premium_upsell',
        'schedule': crontab(hour=20, minute=0, day_of_week=3),  # Wednesday
    },

    # Daily trial Premium giveaway — 12:00 Tashkent. Randomly grants 10 users a
    # free 3-hour Premium trial (introduces them to the features); 3 hours
    # later expire_trial_premium (scheduled via apply_async countdown, not a
    # beat entry) DMs them the buy/referral upsell if they didn't convert.
    'grant-daily-trial-premium': {
        'task': 'tgbot.tasks.grant_daily_trial_premium',
        'schedule': crontab(hour=12, minute=0),
    },

    # Top 5 most active game players today — 23:00, after the evening game
    # sequence has wrapped up, before the admin summary and personal reports.
    'announce-top-game-players': {
        'task': 'tgbot.tasks.announce_top_game_players',
        'schedule': crontab(hour=23, minute=0),
    },

    # Admin daily summary — 23:55 every day, 2 minutes before the personal
    # reports go out so the admin sees platform totals first.
    'send-admin-daily-report': {
        'task': 'tgbot.tasks.send_admin_daily_report',
        'schedule': crontab(hour=23, minute=55),
    },
}

# Use Tashkent local time for crontab schedules (matches admin-set HH:MM).
app.conf.timezone = 'Asia/Tashkent'
