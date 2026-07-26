"""
One-off: compile every "Loyihani yaxshilash so'rovnomasi" (ProjectSurveyResponse)
response collected so far into a single readable list and (re)send it to every
admin — instead of the noisy one-DM-per-answer stream sent live as people
filled it out (see tgbot/bot/handlers/users/project_survey.py).

Ishlatish (Railway console yoki SSH):
    python manage.py resend_survey_results               # sends to every ADMINS-env admin
    python manage.py resend_survey_results --to 8278937151  # sends to this chat_id only
"""
from html import escape

import requests
from django.core.management.base import BaseCommand

YEARS_LABELS = {"0-1": "0-1 yil", "1-3": "1-3 yil", "3-5": "3-5 yil", "6+": "6+ yil"}


class Command(BaseCommand):
    help = "Compile all project-survey responses into a list and send it to every admin (or --to a specific chat_id)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to", dest="to", default=None,
            help="Send only to this chat_id instead of every ADMINS-env admin.",
        )

    def handle(self, *args, **options):
        from tgbot.tasks import BOT_TOKEN
        from tgbot.bot.handlers.users.project_survey import _admin_ids
        from tgbot.models import ProjectSurveyResponse

        responses = list(
            ProjectSurveyResponse.objects.select_related("user")
            .order_by("-completed", "-created_at")
        )
        if not responses:
            self.stdout.write(self.style.WARNING("No survey responses yet."))
            return

        total = len(responses)
        completed = sum(1 for r in responses if r.completed)
        blocks = [f"📊 <b>Loyiha so'rovnomasi — natijalar</b>\n\nJami: <b>{total}</b> ta, "
                  f"yakunlangan: <b>{completed}</b> ta\n"]

        for i, r in enumerate(responses, start=1):
            name = escape(r.user.full_name or str(r.user.telegram_id))
            status = "✅" if r.completed else "⏳"
            years = YEARS_LABELS.get(r.years_reading, r.years_reading or "—")
            lines = [f"\n{i}. {status} <b>{escape(name)}</b>"]
            lines.append(f"   1) Kitobxonlik staji: {years}")
            if r.wishes_text:
                lines.append(f"   2) Istaklar: {escape(r.wishes_text)}")
            lines.append(f"   3) Yiliga kitob: {r.books_per_year or '—'}")
            if r.suggestions_text:
                ctype = r.suggestions_content_type or "text"
                lines.append(f"   4) Takliflar ({ctype}): {escape(r.suggestions_text)}")
            if r.rating is not None:
                lines.append(f"   5) Baho: {r.rating}/10")
            blocks.append("\n".join(lines))

        # Telegram caps messages at 4096 chars — split on entry boundaries.
        MAX = 3900
        chunks = []
        current = ""
        for part in blocks:
            if len(current) + len(part) > MAX and current:
                chunks.append(current)
                current = ""
            current += part
        if current:
            chunks.append(current)

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        admin_ids = [options["to"]] if options.get("to") else _admin_ids()
        sent = failed = 0
        for admin_id in admin_ids:
            for chunk in chunks:
                try:
                    resp = requests.post(
                        url,
                        data={"chat_id": admin_id, "text": chunk, "parse_mode": "HTML"},
                        timeout=10,
                    )
                    if resp.ok:
                        sent += 1
                    else:
                        failed += 1
                        self.stdout.write(self.style.WARNING(f"admin {admin_id} failed: {resp.text[:150]}"))
                except Exception as e:
                    failed += 1
                    self.stdout.write(self.style.WARNING(f"admin {admin_id} error: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Survey results resent: {total} responses, {len(chunks)} message(s) per admin, "
            f"{len(admin_ids)} admin(s). sent={sent} failed={failed}."
        ))
