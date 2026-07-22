"""
One-off: send an intriguing teaser about tonight's 22:00 bonus-game event to
every group right now, to build anticipation before the 21:59:50 kickoff.

Ishlatish (Railway console yoki SSH):
    python manage.py send_hype_teaser
"""
import requests
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send tonight's bonus-event hype teaser to every group right now."

    def handle(self, *args, **options):
        from tgbot.tasks import BOT_TOKEN, _group_chat_ids

        text = (
            "🔮 <b>BUGUN KECHQURUN NIMADIR ODATDAGIDEK BO'LMAYDI...</b>\n\n"
            "Soat <b>22:00</b> da sizni kutilmagan voqea kutmoqda. 👀\n"
            "Necha o'yin bo'ladi? Qaysi birlari maxsus BONUS? "
            "Bugun hech qachon ko'rilmagan darajada qiziqarli tun! 🎁🔥\n\n"
            "⏳ Sanoq boshlandi... Tayyor turing, 22:00 ni kuzating — "
            "pushti tugmani bosishga shay bo'ling! 📚🎮"
        )
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        sent = failed = 0
        for gid in _group_chat_ids():
            try:
                resp = requests.post(
                    url,
                    data={"chat_id": gid, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": "true"},
                    timeout=10,
                )
                if resp.ok:
                    sent += 1
                else:
                    failed += 1
                    self.stdout.write(self.style.WARNING(f"group {gid} failed: {resp.text[:150]}"))
            except Exception as e:
                failed += 1
                self.stdout.write(self.style.WARNING(f"group {gid} error: {e}"))
        self.stdout.write(self.style.SUCCESS(f"Hype teaser sent: {sent} ok, {failed} failed."))
