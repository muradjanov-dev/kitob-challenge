"""
Management command: admin uchun haftalik AI report testini yuborish.

Ishlatish:
    python manage.py test_weekly_report
    python manage.py test_weekly_report --admin-id 917456291
"""
import io
import os
import requests
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Test haftalik AI report + Imagen 3 rasm generatsiyasini adminga yuborish"

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin-id",
            type=int,
            default=None,
            help="Telegram ID (default: ADMINS env variable)",
        )
        parser.add_argument(
            "--text-only",
            action="store_true",
            help="Faqat text, rasm generatsiya qilmaslik",
        )
        parser.add_argument(
            "--lang",
            choices=["uz", "ru"],
            default="uz",
            help="Til: uz yoki ru",
        )

    def handle(self, *args, **options):
        token = os.environ.get("API_TOKEN", "")
        if not token:
            self.stdout.write(self.style.ERROR("API_TOKEN not set"))
            return

        admin_id = options["admin_id"]
        if not admin_id:
            admins_str = os.environ.get("ADMINS", "")
            admin_id_str = admins_str.split(",")[0].strip() if admins_str else ""
            if not admin_id_str:
                self.stdout.write(self.style.ERROR("ADMINS env not set. Use --admin-id"))
                return
            admin_id = int(admin_id_str)

        lang = options["lang"]
        text_only = options["text_only"]

        self.stdout.write(f"📤 Admin {admin_id} ga test report yuborilmoqda...")

        # ── Demo stats ─────────────────────────────────────────────────
        demo_achievements = [
            {"emoji": "🔥", "title_uz": "7 kunlik streak", "title_ru": "Серия 7 дней", "points": 70},
            {"emoji": "📚", "title_uz": "Yuz bet",         "title_ru": "Сто страниц",   "points": 20},
        ]

        from tgbot.services.weekly_ai_report import generate_weekly_report
        self.stdout.write("🤖 Gemini AI text generatsiya qilinmoqda...")
        ai_text = generate_weekly_report(
            full_name="Aziz Karimov",
            week_pages=312,
            prev_week_pages=245,
            week_audio_minutes=87,
            prev_week_audio_minutes=60,
            books_finished_week=1,
            total_books_finished=8,
            total_pages_all_time=4350,
            streak=12,
            new_achievements=demo_achievements,
            rank_pct_ahead=78,
            avg_pages_per_day_week=44.6,
            best_day_pages=89,
            language=lang,
        )

        header = (
            "💎 <b>Haftalik Premium Hisobot</b> 📊 <i>(test)</i>"
            if lang != "ru" else
            "💎 <b>Еженедельный Premium Отчёт</b> 📊 <i>(тест)</i>"
        )
        ach_header = (
            "\n\n🏆 <b>Bu haftadagi yutuqlar:</b>\n"
            if lang != "ru" else
            "\n\n🏆 <b>Достижения этой недели:</b>\n"
        )
        ach_lines = "\n".join(
            f"{a['emoji']} <b>{a.get('title_ru' if lang=='ru' else 'title_uz', '')}</b>"
            f" <i>(+{a['points']} Kitobcha)</i>"
            for a in demo_achievements
        )
        full_text = f"{header}\n\n{ai_text}{ach_header}{ach_lines}"

        url_msg = f"https://api.telegram.org/bot{token}/sendMessage"
        url_photo = f"https://api.telegram.org/bot{token}/sendPhoto"

        img_bytes = None
        if not text_only:
            self.stdout.write("🎨 Imagen 3 rasm generatsiya qilinmoqda...")
            from tgbot.tasks import _generate_report_image
            img_bytes = _generate_report_image(
                full_name="Aziz Karimov",
                week_pages=312,
                week_audio_minutes=87,
                streak=12,
                total_pages=4350,
                books_finished_week=1,
                rank_pct_ahead=78,
                new_achievement_titles=["7 kunlik streak", "Yuz bet"],
            )
            if img_bytes:
                self.stdout.write(self.style.SUCCESS("✅ Rasm muvaffaqiyatli generatsiya qilindi"))
            else:
                self.stdout.write(self.style.WARNING(
                    "⚠️  Rasm generatsiya qilinmadi (GEMINI_API_KEY yo'q yoki xatolik). "
                    "Faqat text yuboriladi."
                ))

        # ── Send ────────────────────────────────────────────────────────
        if img_bytes:
            resp = requests.post(
                url_photo,
                data={"chat_id": admin_id, "parse_mode": "HTML"},
                files={"photo": ("report.jpg", io.BytesIO(img_bytes), "image/jpeg")},
                timeout=15,
            )
            if resp.ok:
                self.stdout.write(self.style.SUCCESS("📸 Rasm yuborildi"))
            else:
                self.stdout.write(self.style.WARNING(f"Rasm yuborishda xatolik: {resp.text}"))

        resp = requests.post(
            url_msg,
            data={"chat_id": admin_id, "text": full_text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.ok:
            self.stdout.write(self.style.SUCCESS(
                f"✅ Test report muvaffaqiyatli yuborildi → Telegram ID: {admin_id}"
            ))
        else:
            self.stdout.write(self.style.ERROR(f"❌ Yuborishda xatolik: {resp.text}"))

        # ── Budget tahlili ──────────────────────────────────────────────
        self.stdout.write("\n" + "─" * 50)
        self.stdout.write("💰 BUDGET TAHLILI:")
        self.stdout.write("  Gemini 2.0 Flash:")
        self.stdout.write("    Input (~800 token): $0.00008")
        self.stdout.write("    Output (~600 token): $0.00024")
        self.stdout.write("  Imagen 3 (1 rasm):    $0.04")
        self.stdout.write("  Jami / user / hafta:  ~$0.041  ≈  525 UZS")
        self.stdout.write("  Jami / user / OY:     ~$0.16   ≈  2,100 UZS")
        self.stdout.write(f"  Premium narxi:        17,000 UZS/oy")
        self.stdout.write("  Xarajat ulushi:       ~12.4% (text+rasm bilan)")
        self.stdout.write("")
        self.stdout.write("  ❗ Faqat TEXT (Imagen 3 siz):")
        self.stdout.write("    ~0.0013 $ / user / hafta ≈ 17 UZS")
        self.stdout.write("    Oylik: ~68 UZS → xarajat ulushi: 0.4% ✅")
        self.stdout.write("─" * 50)
