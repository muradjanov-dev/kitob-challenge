"""Manually trigger a Kitob Viktorina round (for testing / one-off posts).

Usage:
    python manage.py post_book_quiz            # build + broadcast a round now
    python manage.py post_book_quiz --dry-run  # build only, print, don't send
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Build and post a Kitob Viktorina round immediately."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Build and print the quiz without posting it to groups/users.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            from tgbot.services.book_quiz import build_quiz_round, build_quiz_text
            quiz_round = build_quiz_round()
            if not quiz_round:
                self.stdout.write(self.style.WARNING(
                    "Yetarli xulosa topilmadi — viktorina qurib bo'lmadi."
                ))
                return
            self.stdout.write(self.style.SUCCESS(f"Round #{quiz_round.id} built:"))
            self.stdout.write(build_quiz_text(quiz_round))
            self.stdout.write(f"\nTo'g'ri javob: {quiz_round.correct_title} "
                              f"(index {quiz_round.correct_index})")
            self.stdout.write(f"Variantlar: {quiz_round.options}")
            return

        from tgbot.tasks import post_book_quiz
        post_book_quiz()
        self.stdout.write(self.style.SUCCESS("post_book_quiz bajarildi."))
