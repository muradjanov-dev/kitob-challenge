"""
Diagnose + fix a finished Kitob Zanjiri game whose stored rewards don't match
the final point standings (top up under-rewarded users, never claw back from
anyone), and optionally post an apology + compensation announcement to the
groups (bot's fault, not the admin's).

Ishlatish:
    python manage.py fix_chain_game_rewards
    python manage.py fix_chain_game_rewards --game-id 42 --dry-run
    python manage.py fix_chain_game_rewards --announce
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Diagnose/fix a Kitob Zanjiri game's reward mismatch and optionally announce an apology."

    def add_arguments(self, parser):
        parser.add_argument("--game-id", type=int, default=None,
                             help="Defaults to the most recently finished game.")
        parser.add_argument("--announce", action="store_true",
                             help="Post an apology + compensation announcement to the groups.")
        parser.add_argument("--dry-run", action="store_true",
                             help="Show what would change without applying it.")
        parser.add_argument("--list", type=int, default=0, metavar="N",
                             help="Just list the last N finished games' top-3 scorers and exit "
                                  "(no fixing) — use this to find the right --game-id.")

    def handle(self, *args, **options):
        from tgbot.models import ChainGame, ChainScore
        from tgbot.services.chain_game import _add_ball_flat, REWARD_TIERS, PARTICIPATION

        if options["list"]:
            games = ChainGame.objects.filter(status="finished").order_by("-starts_at")[:options["list"]]
            for g in games:
                top = list(
                    ChainScore.objects.filter(game=g).order_by("-points", "created_at")[:3]
                    .values_list("user__full_name", "points", "reward")
                )
                self.stdout.write(f"#{g.id} starts_at={g.starts_at} players={ChainScore.objects.filter(game=g).count()} top3={top}")
            return

        game_id = options["game_id"]
        g = (ChainGame.objects.filter(id=game_id).first() if game_id
             else ChainGame.objects.filter(status="finished").order_by("-starts_at").first())
        if not g:
            self.stdout.write(self.style.ERROR("No finished game found."))
            return

        self.stdout.write(
            f"Game #{g.id} status={g.status} rewarded={g.rewarded} "
            f"starts_at={g.starts_at} ends_at={g.ends_at}"
        )

        # NOTE: kicked users are INCLUDED here on purpose. The 3-strikes kick
        # mechanic (which forfeited the whole reward, even for top scorers)
        # has been removed per feedback — this recompute retroactively forgives
        # any kick and rewards purely by point rank, same as everyone else.
        scores = list(
            ChainScore.objects.filter(game=g)
            .select_related("user").order_by("-points", "created_at")
        )
        self.stdout.write(f"{len(scores)} scores:")
        for i, s in enumerate(scores):
            self.stdout.write(
                f"  [{i}] {s.user.full_name} points={s.points} stored_reward={s.reward} "
                f"rewarded={s.rewarded} kicked={s.kicked} created={s.created_at} updated={s.updated_at}"
            )

        fixes = []
        for i, s in enumerate(scores):
            if s.points <= 0:
                correct = 0
            elif i < 3:
                correct = REWARD_TIERS[i]
            else:
                correct = PARTICIPATION
            if correct > (s.reward or 0):
                fixes.append((s, correct, correct - (s.reward or 0)))

        if not fixes:
            self.stdout.write(self.style.SUCCESS("No under-rewarded users found — nothing to fix."))
            return

        self.stdout.write("\nUnder-rewarded users (top up only, never claw back):")
        for s, correct, delta in fixes:
            self.stdout.write(f"  {s.user.full_name}: had {s.reward or 0}, should have {correct}, +{delta}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — no changes applied."))
            return

        import requests
        from tgbot.tasks import BOT_TOKEN, _group_chat_ids

        for s, correct, delta in fixes:
            applied = _add_ball_flat(s.user, delta)
            s.reward = correct
            s.rewarded = True
            s.save(update_fields=["reward", "rewarded", "updated_at"])
            try:
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    data={
                        "chat_id": s.user.telegram_id,
                        "text": (
                            f"🙏 <b>Kechirim so'raymiz!</b> Kitob Zanjiri o'yinida tizim xatosi tufayli "
                            f"mukofotingiz to'liq berilmagan edi. Endi to'g'irlandi: "
                            f"<b>+{applied} Kitobcha</b> qo'shildi (jami mukofot: {correct} 🪙)."
                        ),
                        "parse_mode": "HTML",
                    },
                    timeout=8,
                )
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"DM failed for {s.user.full_name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Fixed {len(fixes)} users."))

        if options["announce"]:
            text = (
                "🙏 <b>Kechirim so'raymiz!</b>\n\n"
                "So'nggi Kitob Zanjiri o'yinida tizimiy xatolik tufayli ba'zi g'oliblarga mukofot "
                "to'liq berilmagan edi. Bu — botning texnik xatosi, admin bunga aloqador emas.\n\n"
                "Jabrlangan foydalanuvchilarga yetishmagan Kitobcha shaxsiy xabar orqali to'liq "
                "qo'shib qo'yildi. Noqulaylik uchun uzr so'raymiz va halol o'yiningiz uchun rahmat! 🤲📚"
            )
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            for gid in _group_chat_ids():
                try:
                    requests.post(url, data={"chat_id": gid, "text": text, "parse_mode": "HTML",
                                             "disable_web_page_preview": "true"}, timeout=10)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"group {gid}: {e}"))
            self.stdout.write(self.style.SUCCESS("Announcement posted."))
