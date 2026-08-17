"""Pay out and announce VIP Premium Arena games that were never settled.

Why they weren't: `_finalize_individual` granted the top-3 Premium bonus with
`Payment.grant_or_extend(...)` while `Payment` was never imported into
tgbot/services/quiz_game.py. The NameError fired on the FIRST placed winner,
so for every VIP game:

  • 1st place got their Kitobcha but no Premium;
  • everyone below them got nothing at all, despite paying the entry fee;
  • the results were never announced;
  • `_advance_game_sequence` never ran, so the VIP sequence stalled.

This command replays the payout for those games through the fixed code path.
It is safe to re-run: Kitobcha is guarded by `QuizScore.rewarded` and Premium
by `QuizScore.premium_days`, so nothing is ever granted twice.

Ishlatish:
    python manage.py settle_vip_arena --dry-run          # last VIP game, show only
    python manage.py settle_vip_arena                    # last VIP game, pay + announce
    python manage.py settle_vip_arena --days 7           # every VIP game of the last week
    python manage.py settle_vip_arena --game-id 123
    python manage.py settle_vip_arena --no-announce      # pay + DM, no group post
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Settle Kitobcha + Premium and announce results for unsettled VIP arena games."

    def add_arguments(self, parser):
        parser.add_argument("--game-id", type=int, default=None,
                            help="Settle exactly this QuizGame id.")
        parser.add_argument("--days", type=int, default=None,
                            help="Settle every VIP game started in the last N days.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Show the payouts and the exact group post, change nothing.")
        parser.add_argument("--no-announce", action="store_true",
                            help="Pay and DM the winners, but post nothing to the groups.")
        parser.add_argument("--ignore-ledger", action="store_true",
                            help="Skip the already-credited check and pay every unflagged row "
                                 "(only if you know the ledger evidence is wrong).")

    def handle(self, *args, **options):
        import requests
        from datetime import timedelta
        from django.utils import timezone
        from django.utils.html import escape
        from tgbot.models import QuizGame, QuizScore, KitobchaLedger
        from tgbot.services import quiz_game
        from tgbot.services.chain_game import _add_ball_reward
        from tgbot.tasks import (BOT_TOKEN, _game_targets, _quiz_headline, _scoreline,
                                 _answer_key_lines, _trim_telegram)

        dry = options["dry_run"]

        def already_credited(score, game, earned):
            """Kitobcha this row was paid despite `rewarded` never being saved.

            The old crash happened *after* `_add_ball_reward` but *before*
            `s.save()`, so the highest-placed winner really was paid while the
            flag says otherwise — settling them again would double-pay. The
            ledger is the only surviving evidence: look for an `update_ball`
            entry for exactly the tier amount (or twice it, for a Premium 2x
            earner) in the minutes around the game ending. Returns the amount
            found, or 0.
            """
            if options["ignore_ledger"]:
                return 0
            hit = KitobchaLedger.objects.filter(
                user_id=score.user_id, reason="update_ball",
                delta__in=[earned, earned * 2],
                created_at__range=(game.ends_at - timedelta(minutes=2),
                                   game.ends_at + timedelta(minutes=3)),
            ).first()
            return hit.delta if hit else 0

        if options["game_id"]:
            games = list(QuizGame.objects.filter(id=options["game_id"]))
        elif options["days"]:
            since = timezone.now() - timedelta(days=options["days"])
            games = list(QuizGame.objects.filter(is_vip=True, starts_at__gte=since).order_by("starts_at"))
        else:
            last = QuizGame.objects.filter(is_vip=True).order_by("-starts_at").first()
            games = [last] if last else []

        if not games:
            self.stdout.write(self.style.WARNING("No VIP arena games found."))
            return

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        for g in games:
            self.stdout.write(self.style.HTTP_INFO(
                f"\n═══ VIP #{g.id} · {g.flavor} · {timezone.localtime(g.starts_at):%d.%m.%Y %H:%M} "
                f"· status={g.status} rewarded={g.rewarded}"
            ))
            rows = quiz_game.ranked_scores(g)
            if not rows:
                self.stdout.write("  Hech kim ochko olmagan — o'tkazib yuborildi.")
                continue

            tiers = quiz_game.VIP_REWARD_TIERS
            nq = len(g.questions or [])
            winners, owed_ball, owed_prem = [], 0, 0

            for i, s in enumerate(rows):
                earned = tiers[i] if i < 3 else (quiz_game.VIP_PARTICIPATION if i < 10 else 25)
                prem_due = quiz_game.VIP_PREMIUM_DAYS_BONUS.get(i, 0)
                paid_already = 0 if s.rewarded else already_credited(s, g, earned)
                needs_ball = not s.rewarded and not paid_already
                needs_prem = bool(prem_due) and not s.premium_days

                if needs_ball:
                    owed_ball += earned
                if needs_prem:
                    owed_prem += prem_due

                flags = []
                if needs_ball:
                    flags.append(f"+{earned} 🪙 BERILADI")
                elif paid_already:
                    flags.append(f"🪙 allaqachon +{paid_already} olingan (ledger) — QAYTA BERILMAYDI")
                if needs_prem:
                    flags.append(f"+{prem_due} kun Premium BERILADI")
                if not flags:
                    flags.append("allaqachon berilgan ✔")
                self.stdout.write(
                    f"  {i + 1}. {s.user.full_name or s.user.telegram_id} — "
                    f"{s.points} ochko · ✅ {s.points // quiz_game.POINTS}/{nq} · "
                    f"⏱ {round(s.effective_time, 1)}s → {', '.join(flags)}"
                )

                applied = s.reward or paid_already or earned
                if not dry:
                    if needs_ball:
                        applied = _add_ball_reward(s.user, earned)
                    if needs_ball or paid_already:
                        # Close the flag either way, so this row can never be
                        # settled a second time from any other code path.
                        s.rewarded = True
                        s.reward = applied
                        s.save(update_fields=["rewarded", "reward", "updated_at"])
                    quiz_game.grant_vip_premium(s, i)

                winners.append({
                    "rank": i + 1, "user_id": s.user_id, "telegram_id": s.user.telegram_id,
                    "name": s.user.full_name or "Kitobxon", "points": s.points,
                    "reward": applied, "correct": s.points // quiz_game.POINTS,
                    "q_total": nq, "time": round(s.effective_time, 1),
                    "premium_days": (prem_due if (needs_prem or s.premium_days) else 0),
                    "was_owed": needs_ball or needs_prem,
                    "ball_was_owed": needs_ball,
                })

            if not dry and not g.rewarded:
                g.rewarded = True
                g.status = QuizGame.STATUS_FINISHED
                g.save(update_fields=["rewarded", "status", "updated_at"])

            self.stdout.write(self.style.SUCCESS(
                f"  → {owed_ball} Kitobcha va {owed_prem} kun Premium "
                f"{'beriladi' if dry else 'berildi'}."
            ))

            # ── The group post ──────────────────────────────────────────────
            _, title = _quiz_headline(g.flavor)
            medals = ["🥇", "🥈", "🥉"]
            lines = [
                f"⭐️ <b>{title} (VIP Premium) — natijalar</b>\n",
                "<i>Texnik xatolik tufayli bu o'yin natijasi e'lon qilinmay qolgan va "
                "mukofotlar to'liq berilmagan edi. Xatolik tuzatildi — barcha yutuqlar "
                "hozir egalariga o'tkazildi:</i>\n",
            ]
            for i, w in enumerate(winners[:10]):
                m = medals[i] if i < 3 else f"{i + 1}."
                prem = f" + <b>{w['premium_days']} kun Premium</b> 💎" if w.get("premium_days") else ""
                lines.append(
                    f"{m} {escape(w['name'])} — <b>{w['points']}</b> ochko"
                    f"{_scoreline(w)} (+{w['reward']} 🪙){prem}"
                )
            lines += _answer_key_lines(g)
            lines.append(
                "\n<i>⏱ vaqt — javob bergan soniyalaringiz; javob berilmagan savol to'liq "
                "vaqt deb hisoblanadi. Ball teng bo'lsa — tezroq javob bergan yuqorida.</i>\n"
                "🙏 Noqulaylik uchun uzr so'raymiz."
            )
            text = _trim_telegram("\n".join(lines))

            if dry:
                self.stdout.write("\n" + self.style.WARNING("─── GURUHGA YUBORILADIGAN MATN ───"))
                self.stdout.write(text)
                self.stdout.write(self.style.WARNING("─── (dry-run: hech narsa yuborilmadi) ───"))
                continue

            for w in winners:
                if not w.get("was_owed"):
                    continue
                dm = (
                    f"⭐️ <b>{title} (VIP Premium)</b> — kechiktirilgan mukofotingiz berildi!\n\n"
                    f"🏅 {w['rank']}-o'rin · <b>{w['points']}</b> ochko{_scoreline(w)}\n"
                )
                dm += (f"🪙 <b>+{w['reward']} Kitobcha</b>" if w.get("ball_was_owed")
                       else f"🪙 <b>{w['reward']} Kitobcha</b> — allaqachon hisobingizga o'tgan edi")
                if w.get("premium_days"):
                    dm += (f"\n💎 <b>{w['premium_days']} kun BEPUL Premium</b> faollashtirildi — "
                           "barcha VIP imtiyozlar ochiq!")
                dm += "\n\n🙏 Kechikkani uchun uzr so'raymiz, qatnashganingiz uchun rahmat! 📚"
                try:
                    requests.post(url, data={"chat_id": w["telegram_id"], "text": dm,
                                             "parse_mode": "HTML"}, timeout=8)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  DM {w['telegram_id']}: {e}"))

            if options["no_announce"]:
                self.stdout.write("  (--no-announce: guruhga post qilinmadi)")
                continue
            for gid, tid in _game_targets():
                data = {"chat_id": gid, "text": text, "parse_mode": "HTML",
                        "disable_web_page_preview": "true"}
                if tid:
                    data["message_thread_id"] = tid
                try:
                    resp = requests.post(url, data=data, timeout=10)
                    if resp.status_code != 200:
                        self.stdout.write(self.style.WARNING(f"  group {gid}: {resp.text[:200]}"))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  group {gid}: {e}"))
            self.stdout.write(self.style.SUCCESS("  Guruhlarga e'lon qilindi."))
