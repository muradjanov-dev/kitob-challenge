"""
One-off: re-send a reminder DM to everyone who actually earned Kitobcha in
the most recently finished challenge, confirming their reward was already
credited. Does NOT re-grant any Kitobcha — purely a reminder resend, for
when winners ask "did I get paid?" after the fact.

Ishlatish (Railway console yoki SSH):
    python manage.py remind_challenge_rewards                 # latest finished challenge
    python manage.py remind_challenge_rewards --challenge-id 7  # a specific one
"""
import requests
from django.core.management.base import BaseCommand

# Mirrors tgbot.tasks._finalize_challenge_results's prize logic exactly —
# recomputed here (ChallengeParticipant doesn't store the granted amount).
_PRIZE_MAP = {1: 200, 2: 100, 3: 50}


def _kitobcha_for(rank, days):
    if days < 1:
        return 0
    if rank <= 3 and days >= 3:
        return _PRIZE_MAP[rank]
    if days >= 3:
        return 25
    if days == 2:
        return 15
    if days == 1:
        return 5
    return 0


class Command(BaseCommand):
    help = "Resend a 'your reward was already credited' reminder to a finished challenge's winners, without re-granting anything."

    def add_arguments(self, parser):
        parser.add_argument("--challenge-id", dest="challenge_id", type=int, default=None)

    def handle(self, *args, **options):
        from tgbot.tasks import BOT_TOKEN
        from tgbot.models import Challenge, ChallengeParticipant

        if options.get("challenge_id"):
            challenge = Challenge.objects.filter(id=options["challenge_id"]).first()
        else:
            challenge = Challenge.objects.filter(is_active=False).order_by("-end_date", "-id").first()

        if not challenge:
            self.stdout.write(self.style.WARNING("No finished challenge found."))
            return

        winners = list(
            ChallengeParticipant.objects.filter(challenge=challenge, days_completed__gte=1)
            .select_related("user")
            .order_by("rank")
        )
        if not winners:
            self.stdout.write(self.style.WARNING(f"No rewarded participants in '{challenge.title}'."))
            return

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        place_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}
        sent = failed = 0
        for p in winners:
            kitobcha = _kitobcha_for(p.rank, p.days_completed)
            if kitobcha <= 0:
                continue
            emoji = place_emoji.get(p.rank, "🏅")
            text = (
                f"🔔 <b>Eslatma</b>\n\n"
                f"{challenge.emoji} <b>{challenge.title}</b> challengeda natijangiz:\n\n"
                f"{emoji} O'rningiz: <b>{p.rank}</b>\n"
                f"✅ Bajargan kunlar: <b>{p.days_completed}/3</b>\n"
                f"🪙 Mukofotingiz: <b>+{kitobcha} Kitobcha</b> — hisobingizga allaqachon qo'shilgan!\n\n"
                f"Rahmat, faol ishtirokingiz uchun! 🚀"
            )
            try:
                resp = requests.post(
                    url,
                    data={"chat_id": p.user.telegram_id, "text": text, "parse_mode": "HTML"},
                    timeout=10,
                )
                if resp.ok:
                    sent += 1
                else:
                    failed += 1
                    self.stdout.write(self.style.WARNING(f"user {p.user.telegram_id} failed: {resp.text[:150]}"))
            except Exception as e:
                failed += 1
                self.stdout.write(self.style.WARNING(f"user {p.user.telegram_id} error: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Reminder resent for '{challenge.title}': {len(winners)} winners, sent={sent} failed={failed}. "
            f"No Kitobcha was re-granted."
        ))
