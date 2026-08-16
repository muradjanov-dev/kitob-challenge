"""
Settle every live-game reward the bot owes but never paid, then announce the
results that were never announced.

Two independent problems are fixed here:

1. Overdue games still sitting at status=live because the finalizer only knew
   the 8 original quiz flavors — the newer ones were charged an entry fee,
   played, and then silently dropped. These are finalized through the normal
   production path (tgbot.tasks._finalize_quiz_flavor), so winners get their
   tier rewards, the groups get the results post and winners get their DM.

2. QuizScore rows left with rewarded=False in games that ARE already finished:
   • scored (points > 0) — rank recomputed inside their own game, paid the
     tier they earned;
   • zero-point (points == 0) — paid a flat participation reward, so nobody
     who paid an entry fee walks away with nothing.

Rewards are only ever topped up, never clawed back.

Ishlatish:
    python manage.py settle_pending_game_rewards --dry-run
    python manage.py settle_pending_game_rewards
    python manage.py settle_pending_game_rewards --no-announce   # pay silently
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Finalize/announce overdue live games and pay every unpaid participant."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Show exactly what would be paid and posted, change nothing.")
        parser.add_argument("--no-announce", action="store_true",
                            help="Pay + DM, but skip the group apology announcement.")
        parser.add_argument("--participation", type=int, default=None,
                            help="Kitobcha for zero-point participants (default: PARTICIPATION=30).")
        parser.add_argument("--min-players", type=int, default=3,
                            help="Only announce results for games with at least this many players; "
                                 "smaller ones (admin test runs) are still paid, just silently.")

    def handle(self, *args, **options):
        import requests
        from django.utils import timezone
        from tgbot.models import QuizGame, QuizScore
        from tgbot.services.chain_game import _add_ball_reward, REWARD_TIERS, PARTICIPATION
        from tgbot.tasks import BOT_TOKEN, _game_targets

        dry = options["dry_run"]
        participation = options["participation"] or PARTICIPATION
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        # ── 1. Overdue games that were never finalized ──────────────────────
        now = timezone.now()
        due = list(
            QuizGame.objects.exclude(status=QuizGame.STATUS_FINISHED)
            .filter(ends_at__lt=now).order_by("starts_at")
        )
        min_players = options["min_players"]
        silent, loud = [], []
        self.stdout.write(f"Overdue unfinalized games: {len(due)}")
        for g in due:
            players = QuizScore.objects.filter(game=g).count()
            (loud if players >= min_players else silent).append(g)
            self.stdout.write(
                f"  #{g.id} {g.flavor} {timezone.localtime(g.starts_at):%d.%m %H:%M} "
                f"players={players} → {'announce' if players >= min_players else 'pay only'}"
            )

        if not dry:
            from tgbot.services import quiz_game
            from tgbot.tasks import _finalize_quiz_flavor
            # Pay out the tiny admin test runs first and without a post, so the
            # flavor sweep below only finds (and announces) the real games.
            for g in silent:
                try:
                    quiz_game.finalize(g.id)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  #{g.id} {g.flavor} pay-only failed: {e}"))
            for flavor in sorted({g.flavor for g in loud}):
                try:
                    _finalize_quiz_flavor(flavor)
                    self.stdout.write(self.style.SUCCESS(f"  finalized + announced: {flavor}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  {flavor} failed: {e}"))

        # ── 2. Participants still unpaid in finished games ──────────────────
        unpaid = (
            QuizScore.objects.filter(rewarded=False, game__status=QuizGame.STATUS_FINISHED)
            .select_related("game", "user")
        )
        by_game = {}
        for s in unpaid:
            by_game.setdefault(s.game_id, []).append(s)

        payouts = []  # (score, amount)
        for game_id, rows in by_game.items():
            game = rows[0].game
            # Same ordering _finalize_individual uses, over the WHOLE game, so a
            # late-settled row gets the rank it actually earned that night.
            ranked = list(
                QuizScore.objects.filter(game_id=game_id, points__gt=0)
                .order_by("-points", "total_time", "created_at")
                .values_list("id", flat=True)
            )
            for s in rows:
                if s.points > 0:
                    i = ranked.index(s.id) if s.id in ranked else len(ranked)
                    amount = REWARD_TIERS[i] if i < 3 else (PARTICIPATION if i < 10 else 25)
                else:
                    amount = participation
                if amount > (s.reward or 0):
                    payouts.append((s, amount, game))

        total = sum(a for _s, a, _g in payouts)
        self.stdout.write(
            f"\nUnpaid participants to settle: {len(payouts)} "
            f"(~{total} Kitobcha before Premium 2x)"
        )
        for s, amount, game in payouts[:60]:
            self.stdout.write(
                f"  {s.user.full_name or s.user.telegram_id} — {game.flavor} #{game.id} "
                f"pts={s.points} → +{amount}"
            )
        if len(payouts) > 60:
            self.stdout.write(f"  … and {len(payouts) - 60} more")

        if dry:
            self.stdout.write(self.style.WARNING("\nDry run — nothing paid, nothing posted."))
            if not options["no_announce"]:
                self.stdout.write("\nGroup announcement that WOULD be posted:\n")
                self.stdout.write(self._announcement_text(len(payouts)))
            return

        paid_users = 0
        for s, amount, game in payouts:
            try:
                applied = _add_ball_reward(s.user, amount)
                s.reward = max(s.reward or 0, applied)
                s.rewarded = True
                s.save(update_fields=["reward", "rewarded", "updated_at"])
                paid_users += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"pay failed for {s.user_id}: {e}"))
                continue
            try:
                requests.post(url, data={
                    "chat_id": s.user.telegram_id,
                    "text": (
                        "🙏 <b>Kechirim so'raymiz!</b>\n\n"
                        f"«{game.title}» o'yinida texnik xatolik tufayli mukofotingiz "
                        "o'z vaqtida berilmagan edi. Endi to'liq hisobingizga qo'shildi:\n"
                        f"🪙 <b>+{applied} Kitobcha</b> · Ball: {s.points}\n\n"
                        "Sabringiz va o'yinda qatnashganingiz uchun rahmat! 📚"
                    ),
                    "parse_mode": "HTML",
                }, timeout=8)
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS(f"\nPaid {paid_users} participants."))

        if options["no_announce"]:
            return
        text = self._announcement_text(paid_users)
        # Posted into the same games topic the results themselves land in.
        for gid, tid in _game_targets():
            data = {"chat_id": gid, "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": "true"}
            if tid:
                data["message_thread_id"] = tid
            try:
                requests.post(url, data=data, timeout=10)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"group {gid}: {e}"))
        self.stdout.write(self.style.SUCCESS("Announcement posted."))

    @staticmethod
    def _announcement_text(count: int) -> str:
        return (
            "🙏 <b>Kechirim so'raymiz — mukofotlar to'liq berildi!</b>\n\n"
            "Yangi qo'shilgan jonli o'yinlarda texnik xatolik tufayli natijalar e'lon "
            "qilinmay, mukofotlar kechikkan edi. Xatolik butunlay bartaraf etildi.\n\n"
            f"✅ Barcha ishtirokchilarga ({count} nafar) mukofotlari to'liq qo'shildi.\n"
            "✅ O'yinlar natijalari e'lon qilindi — g'oliblar tabriklanadi!\n"
            "✅ Bundan buyon <b>barcha 58 ta o'yin</b> natijasi avtomatik e'lon qilinadi.\n\n"
            "Noqulaylik uchun uzr so'raymiz. Har kuni <b>10:00</b> va <b>22:00</b> dagi "
            "o'yinlarda ko'rishguncha! 🎮📚"
        )
