"""
One-off: send TODAY's rich Premium-style personal report (week/month/year
comparisons, motivation line) to EVERY user who reported today, regardless of
their real Premium status — a one-time taste of the feature. Non-Premium
recipients get a closing reminder that this is normally Premium-only.

The regular daily 23:57 send_daily_personal_report task is untouched and
keeps running as usual going forward (rich report for real Premium users,
simple report + teaser for everyone else).

Ishlatish:
    python manage.py send_premium_preview_report
"""
import datetime as _dt

from django.core.management.base import BaseCommand
from django.db.models import Sum as _S
from django.utils import timezone


class Command(BaseCommand):
    help = "Send everyone today's rich Premium-style report as a one-time preview."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default=None,
                             help="YYYY-MM-DD to report on. Defaults to the server's current date.")

    def handle(self, *args, **options):
        import requests
        from tgbot.models import ConfirmationReport, TelegramProfile, Payment as _Pay
        from tgbot.tasks import BOT_TOKEN

        today = (_dt.datetime.strptime(options["date"], "%Y-%m-%d").date()
                 if options["date"] else timezone.localdate())
        yesterday = today - _dt.timedelta(days=1)
        d3_start = today - _dt.timedelta(days=2)
        week_start = today - _dt.timedelta(days=6)
        prev_week_s = today - _dt.timedelta(days=13)
        prev_week_e = today - _dt.timedelta(days=7)
        month_start = today - _dt.timedelta(days=29)
        prev_month_s = today - _dt.timedelta(days=59)
        prev_month_e = today - _dt.timedelta(days=30)
        year_start = _dt.date(today.year, 1, 1)
        prev_year_s = _dt.date(today.year - 1, 1, 1)
        prev_year_e = _dt.date(today.year - 1, 12, 31)

        premium_user_ids = set(
            _Pay.objects.filter(status="paid", end_date__gte=today).values_list("user_id", flat=True)
        )

        today_rows = list(
            ConfirmationReport.objects
            .filter(date__date=today, is_audio=False, user__is_blocked=False)
            .values("user_id")
            .annotate(today_pages=_S("pages_read"))
            .filter(today_pages__gt=0)
            .order_by("-today_pages")
        )
        if not today_rows:
            self.stdout.write(self.style.WARNING("No reporters today — nothing to send."))
            return

        user_ids = [r["user_id"] for r in today_rows]
        total_reporters = len(user_ids)

        def _bulk(start, end):
            qs = ConfirmationReport.objects.filter(
                date__date__gte=start, date__date__lte=end, is_audio=False, user_id__in=user_ids,
            )
            return {r["user_id"]: r["t"] or 0 for r in qs.values("user_id").annotate(t=_S("pages_read"))}

        yest_all = _bulk(yesterday, yesterday)
        d3_all = _bulk(d3_start, today)
        week_all = _bulk(week_start, today)
        pw_all = _bulk(prev_week_s, prev_week_e)
        month_all = _bulk(month_start, today)
        pm_all = _bulk(prev_month_s, prev_month_e)
        year_all = _bulk(year_start, today)
        py_all = _bulk(prev_year_s, prev_year_e)
        total_at = {r["user_id"]: r["t"] or 0 for r in
                    ConfirmationReport.objects.filter(is_audio=False, user_id__in=user_ids)
                    .values("user_id").annotate(t=_S("pages_read"))}

        def _pct_str(old, new):
            if old == 0:
                return "▲ yangi rekord!" if new > 0 else "→ 0%"
            p = round((new - old) * 100 / old)
            if p > 0: return f"▲ +{p}%"
            if p < 0: return f"▼ {p}%"
            return "→ 0%"

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        sent = failed = 0
        for rank, row in enumerate(today_rows, start=1):
            uid = row["user_id"]
            today_p = row["today_pages"] or 0
            user = TelegramProfile.objects.filter(id=uid).first()
            if not user:
                continue
            is_prem = uid in premium_user_ids
            behind = total_reporters - rank
            pct_ahead = round(behind * 100 / max(total_reporters - 1, 1))
            yest_p = yest_all.get(uid, 0)

            if rank == 1:
                motiv = "🥇 Barakalla! Bugun siz BIRINCHI bo'ldingiz! Zo'r natija!"
            elif rank <= 3:
                motiv = f"🏅 Zo'r! Bugun TOP-3 ichida turibsiz ({rank}-o'rin)!"
            elif pct_ahead >= 75:
                motiv = f"📈 Ajoyib! Kitobxonlarning {pct_ahead}% dan ko'p o'qidingiz!"
            elif today_p > yest_p > 0:
                motiv = "📗 Kechagidan ko'proq o'qidingiz! O'sish davom etyapti!"
            else:
                motiv = "📖 Har bir bet — kelajakka investitsiya. Davom eting!"

            reminder = "" if is_prem else (
                "\n\n💎 <b>Diqqat:</b> Bu — Premium a'zolarga xos batafsil hisobotning "
                "bir martalik NAMUNASI edi. Bunday hisobotni har kuni olishni xohlaysizmi? "
                "💎 Premium oling — menyudan tugmani bosing!"
            )
            text = (
                f"💎 <b>Premium Hisobot — {today.strftime('%d.%m.%Y')}</b>\n\n"
                f"✨ {motiv}\n\n"
                f"📊 <b>Bugungi natijalar:</b>\n"
                f"📖 Bugun o'qidingiz: <b>{today_p} bet</b>\n"
                f"📅 Kecha: {yest_p} bet → <b>{_pct_str(yest_p, today_p)}</b>\n"
                f"📆 Oxirgi 3 kun: <b>{d3_all.get(uid, 0)} bet</b>\n"
                f"🗓 Bu hafta: {week_all.get(uid, 0)} bet (o'tgan hafta: {pw_all.get(uid, 0)} bet) "
                f"→ <b>{_pct_str(pw_all.get(uid, 0), week_all.get(uid, 0))}</b>\n"
                f"🗃 Bu oy: {month_all.get(uid, 0)} bet (o'tgan oy: {pm_all.get(uid, 0)} bet) "
                f"→ <b>{_pct_str(pm_all.get(uid, 0), month_all.get(uid, 0))}</b>\n"
                f"📈 Bu yil: {year_all.get(uid, 0)} bet (o'tgan yil: {py_all.get(uid, 0)} bet) "
                f"→ <b>{_pct_str(py_all.get(uid, 0), year_all.get(uid, 0))}</b>\n\n"
                f"📚 <b>Umumiy:</b> Jami <b>{total_at.get(uid, 0)} bet</b> o'qilgan"
                f"{reminder}"
            )
            try:
                resp = requests.post(
                    url, data={"chat_id": user.telegram_id, "text": text, "parse_mode": "HTML"}, timeout=8,
                )
                if resp.ok:
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                self.stdout.write(self.style.WARNING(f"failed for {user.full_name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Premium preview report sent: {sent} ok, {failed} failed."))
