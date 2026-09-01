from __future__ import absolute_import, unicode_literals
import os
import environ
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab


env = environ.Env()
env.read_env(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE",
                      env.str("DJANGO_SETTINGS_MODULE", default="src.settings"))

app = Celery('src')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()


# celery_worker runs --pool=threads --concurrency=20 (entrypoint.sh). Django
# only auto-closes DB connections at the end of an HTTP request (via a signal
# wired for the WSGI request cycle) -- Celery has no such hook, so without
# this, each of those 20 threads accumulates its own permanent Postgres
# connection the moment it first touches the DB and never releases it. A
# stuck worker left running for a couple of days was enough on its own to
# exhaust Postgres's max_connections and take down the whole platform
# (2026-08-02).
#
# NOTE: close_old_connections() (the first attempt at this fix, same day)
# does NOT actually close a connection here -- it only closes one that's
# already past CONN_MAX_AGE (600s, set in settings.py), so busy threads just
# kept holding live connections and the outage recurred that same evening
# once traffic ramped up. connections.close_all() force-closes unconditionally,
# so every thread starts its next task with a clean slate.
from celery.signals import task_postrun  # noqa: E402


@task_postrun.connect
def _close_db_connections_after_task(**kwargs):
    from django.db import connections
    connections.close_all()

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
        # Runs every day; the task itself no-ops unless the active challenge's
        # end_date has actually passed (see docstring in tasks.py) — this
        # replaces a fixed day-of-month list that drifted at month boundaries
        # not divisible by 3, leaving some challenges unannounced for days.
        'task': 'tgbot.tasks.announce_challenge',
        'schedule': crontab(hour=0, minute=15),
    },
    'boom-reminder-tick': {
        'task': 'tgbot.tasks.boom_reminder_tick',
        'schedule': crontab(minute='*/5'),
    },
    'boom-daily-standings': {
        # No-ops if no boom is active. 22:00 -- end-of-day, but clear of the
        # 23:5x cluster (daily_challenge_check, personal report, streak
        # freezes) so this doesn't bunch up with those DMs.
        'task': 'tgbot.tasks.boom_daily_standings',
        'schedule': crontab(hour=22, minute=0),
    },
    'boom-public-daily-update': {
        # Public TOP-30 version of the above (posted to groups + everyone's
        # DM, not just each participant privately) -- a separate time slot
        # (10:00) so the two don't land back-to-back.
        'task': 'tgbot.tasks.boom_public_daily_update',
        'schedule': crontab(hour=10, minute=0),
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
    # Teaser DM 10 minutes ahead of each slot. DM only -- the groups get the
    # real announcement at slot time. This deliberately raises the documented
    # 3-DM/day cap below to 5 for a non-reporting user; it was asked for so
    # readers who are not watching the groups still hear the games starting.
    'games-teaser-morning': {
        'task': 'tgbot.tasks.send_game_teaser',
        'schedule': crontab(hour=9, minute=50),
        'args': ('morning',),
    },
    'games-teaser-evening': {
        'task': 'tgbot.tasks.send_game_teaser',
        'schedule': crontab(hour=21, minute=50),
        'args': ('evening',),
    },
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

    # Auto-spend a banked Market 'Streak muzlatish' token for anyone about to
    # lose their streak today — runs just before midnight so it's the last
    # possible moment to still count as "today".
    'apply-streak-freezes': {
        'task': 'tgbot.tasks.apply_streak_freezes',
        'schedule': crontab(hour=23, minute=58),
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
        'schedule': timedelta(days=2),  # every 2 days, not pinned to a weekday
    },

    # 3 days before a paying user's Premium lapses — funny, retention-focused
    # nudge to renew before they lose the 2x-Kitobcha/AI-report perks.
    'send-premium-expiry-reminders': {
        'task': 'tgbot.tasks.send_premium_expiry_reminders',
        'schedule': crontab(hour=19, minute=0),
    },

    # Daily trial Premium giveaway — 12:00 Tashkent. Randomly grants 10 users a
    # free 3-hour Premium trial (introduces them to the features); 3 hours
    # later expire_trial_premium (scheduled via apply_async countdown, not a
    # beat entry) DMs them the buy/referral upsell if they didn't convert.
    'grant-daily-trial-premium': {
        'task': 'tgbot.tasks.grant_daily_trial_premium',
        'schedule': crontab(hour=12, minute=0),
    },

    # 3 random non-Premium users get a 1-hour taste of AI quiz creation —
    # separate slot from the trial-Premium giveaway above so they don't land
    # on the same users' notifications back to back.
    'grant-daily-ai-quiz-trial': {
        'task': 'tgbot.tasks.grant_daily_ai_quiz_trial',
        'schedule': crontab(hour=13, minute=0),
    },
    # One-off make-good campaign: 100 users/hour, 05:00-00:59 Tashkent. The
    # task itself no-ops outside those hours and once the queue is empty, so
    # it's harmless to leave scheduled after the campaign finishes.
    'drip-ai-quiz-bonus': {
        'task': 'tgbot.tasks.drip_ai_quiz_bonus_task',
        'schedule': crontab(minute=10),
    },

    # Top 5 most active game players today — 23:00, after the evening game
    # sequence has wrapped up, before the admin summary and personal reports.
    'announce-top-game-players': {
        'task': 'tgbot.tasks.announce_top_game_players',
        'schedule': crontab(hour=23, minute=0),
    },

    # Public "Mukofotlar hisoboti" — 23:45, after the 22:30 VIP Premium arena
    # has finished and been settled, before the admin/personal reports. Shows
    # every Sirli quti prize and every VIP arena payout of the day so players
    # can see the rewards really were handed over. Silent no-op on days with
    # no box opens and no VIP game.
    'announce-rewards-report': {
        'task': 'tgbot.tasks.announce_rewards_report',
        'schedule': crontab(hour=23, minute=45),
    },

    # Admin daily summary — 23:55 every day, 2 minutes before the personal
    # reports go out so the admin sees platform totals first.
    'send-admin-daily-report': {
        'task': 'tgbot.tasks.send_admin_daily_report',
        'schedule': crontab(hour=23, minute=55),
    },

    # Check and settle ended shop auctions every 5 minutes.
    'settle-finished-auctions': {
        'task': 'tgbot.tasks.settle_finished_auctions',
        'schedule': crontab(minute='*/5'),
    },
}

# Use Tashkent local time for crontab schedules (matches admin-set HH:MM).
app.conf.timezone = 'Asia/Tashkent'
