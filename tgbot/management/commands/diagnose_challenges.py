"""
Diagnose why 3-day challenge winners aren't being announced — lists recent
Challenge rows with their active/finalized state and participant counts.

Ishlatish:
    python manage.py diagnose_challenges
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "List recent Challenges with dates, active/finalized state, participant counts."

    def handle(self, *args, **options):
        from tgbot.models import Challenge, ChallengeParticipant

        today = timezone.localdate()
        self.stdout.write(f"Server today (localdate): {today}\n")

        challenges = Challenge.objects.order_by("-created_at")[:10]
        if not challenges:
            self.stdout.write(self.style.WARNING("No Challenge rows at all."))
            return

        for c in challenges:
            participants = ChallengeParticipant.objects.filter(challenge=c)
            total = participants.count()
            rewarded = participants.filter(reward_given=True).count()
            top3 = list(
                participants.filter(reward_given=True).order_by("rank")
                .values_list("rank", "user__full_name")[:3]
            )
            overdue = (not c.is_active is False) and c.is_active and c.end_date < today
            self.stdout.write(
                f"#{c.id} '{c.title}' ({c.condition_type}={c.condition_value}) "
                f"start={c.start_date} end={c.end_date} is_active={c.is_active} "
                f"created_at={c.created_at} participants={total} rewarded={rewarded} "
                f"top3={top3}"
                + ("  <-- OVERDUE, NOT FINALIZED YET" if (c.is_active and c.end_date < today) else "")
            )
