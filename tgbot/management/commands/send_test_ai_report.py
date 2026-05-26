"""
Celery orqali emas, to'g'ridan-to'g'ri Gemini API va Telegram API dan foydalanib
admin ga test report yuboradi. Django models ishlatmaydi — faqat requests + google-generativeai.

Railway "Run Command" qatorida ishlatish uchun mo'ljallangan:
    python manage.py send_test_ai_report
"""
import io
import os
import requests
from django.core.management.base import BaseCommand


DEMO = {
    "full_name":        "Aziz Karimov",
    "week_pages":       312,
    "prev_week_pages":  245,
    "audio_minutes":    87,
    "streak":           12,
    "total_pages":      4350,
    "books_week":       1,
    "rank_pct_ahead":   78,
}


class Command(BaseCommand):
    help = "Admin ga AI haftalik report testi yuborish (DB siz, to'g'ridan-to'g'ri API)"

    def add_arguments(self, parser):
        parser.add_argument("--admin-id", type=int, default=None)
        parser.add_argument("--lang", choices=["uz", "ru"], default="uz")
        parser.add_argument("--text-only", action="store_true",
                            help="Imagen 3 generatsiya qilmaslik")

    def handle(self, *args, **options):
        token = os.environ.get("API_TOKEN", "")
        key   = os.environ.get("GEMINI_API_KEY", "")
        admins = os.environ.get("ADMINS", "917456291")
        admin_id = options["admin_id"] or int(admins.split(",")[0].strip())
        lang = options["lang"]
        text_only = options["text_only"]

        self.stdout.write(f"▶  Admin: {admin_id} | lang: {lang} | text-only: {text_only}")
        self.stdout.write(f"▶  GEMINI_API_KEY: {'✅' if key else '❌ YOQ'}")
        self.stdout.write(f"▶  API_TOKEN:      {'✅' if token else '❌ YOQ'}")

        if not token:
            self.stdout.write(self.style.ERROR("API_TOKEN topilmadi"))
            return

        # 1. Gemini text
        ai_text = self._gemini_text(key, lang)

        header = (
            "💎 <b>Haftalik Premium Hisobot</b> 📊 <i>[TEST]</i>"
            if lang != "ru" else
            "💎 <b>Еженедельный Premium Отчёт</b> 📊 <i>[ТЕСТ]</i>"
        )
        if lang == "ru":
            ach = ("\n\n🏆 <b>Достижения этой недели:</b>\n"
                   "🔥 <b>Серия 7 дней</b> <i>(+70 Kitobcha)</i>\n"
                   "📚 <b>Сто страниц</b> <i>(+20 Kitobcha)</i>")
        else:
            ach = ("\n\n🏆 <b>Bu haftadagi yutuqlar:</b>\n"
                   "🔥 <b>7 kunlik streak</b> <i>(+70 Kitobcha)</i>\n"
                   "📚 <b>Yuz bet</b> <i>(+20 Kitobcha)</i>")

        full_text = f"{header}\n\n{ai_text}{ach}"
        url_msg   = f"https://api.telegram.org/bot{token}/sendMessage"
        url_photo = f"https://api.telegram.org/bot{token}/sendPhoto"

        # 2. Imagen 3
        img = None
        if not text_only and key:
            self.stdout.write("🎨  Imagen 3 generatsiya qilinmoqda…")
            img = self._imagen(key)
            self.stdout.write(
                self.style.SUCCESS("✅  Rasm tayyor") if img
                else self.style.WARNING("⚠️   Rasm generatsiya qilinmadi — faqat text yuboriladi")
            )

        # 3. Yuborish
        if img:
            r = requests.post(
                url_photo,
                data={"chat_id": admin_id, "parse_mode": "HTML"},
                files={"photo": ("report.jpg", io.BytesIO(img), "image/jpeg")},
                timeout=20,
            )
            self.stdout.write(
                self.style.SUCCESS("📸  Rasm yuborildi") if r.ok
                else self.style.WARNING(f"Rasm yuborishda xatolik: {r.text[:200]}")
            )

        r = requests.post(
            url_msg,
            data={"chat_id": admin_id, "text": full_text, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.ok:
            self.stdout.write(self.style.SUCCESS(f"✅  Report yuborildi → {admin_id}"))
        else:
            self.stdout.write(self.style.ERROR(f"❌  Xatolik: {r.text[:300]}"))

    # ── helpers ──────────────────────────────────────────────────────────────

    def _gemini_text(self, key, lang):
        d = DEMO
        if not key:
            return self._fallback(lang)
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            model = genai.GenerativeModel("gemini-2.0-flash")

            p = round((d["week_pages"] - d["prev_week_pages"]) * 100 / max(d["prev_week_pages"], 1))
            pct = f"▲ +{p}%" if p > 0 else f"▼ {p}%"
            ah, am = divmod(d["audio_minutes"], 60)
            audio_str = f"{ah} soat {am} daqiqa" if ah else f"{d['audio_minutes']} daqiqa"

            if lang == "ru":
                prompt = (
                    f"Ты тренер по чтению. Напиши {d['full_name']} персональный еженедельный отчёт.\n"
                    f"Стиль: тёплый, воодушевляющий. Telegram HTML (<b>,<i>). 180-250 слов. Имя 2+ раза.\n"
                    f"Данные: {d['week_pages']} стр (прошлая неделя {d['prev_week_pages']} стр, {pct}), "
                    f"аудио {audio_str}, книг завершено {d['books_week']}, всего {d['total_pages']} стр, "
                    f"стрик {d['streak']} дней, топ {100-d['rank_pct_ahead']}%.\nТолько текст."
                )
            else:
                prompt = (
                    f"Sen kitobxonlik trenerisisan. {d['full_name']} ga shaxsiy haftalik hisobot yoz.\n"
                    f"Uslub: iliq, rag'batlantiruvchan. Telegram HTML (<b>,<i>). 180-250 so'z. Ism 2+ marta.\n"
                    f"Ma'lumotlar: {d['week_pages']} bet (o'tgan hafta {d['prev_week_pages']} bet, {pct}), "
                    f"audio {audio_str}, tugallangan kitoblar {d['books_week']} ta, jami {d['total_pages']} bet, "
                    f"streak {d['streak']} kun, top {100-d['rank_pct_ahead']}%.\nFaqat matn."
                )

            resp = model.generate_content(
                prompt,
                generation_config={"temperature": 0.85, "max_output_tokens": 600},
            )
            self.stdout.write(self.style.SUCCESS("✅  Gemini text tayyor"))
            return resp.text.strip()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Gemini xatolik: {e}"))
            return self._fallback(lang)

    def _imagen(self, key):
        d = DEMO
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            imagen = genai.ImageGenerationModel("imagen-3.0-generate-002")
            prompt = (
                f"Personalized weekly reading report card for '{d['full_name']}'. "
                f"Modern infographic, warm gold and deep navy palette. "
                f"Stats: {d['week_pages']} pages this week | {d['audio_minutes']} audio min | "
                f"{d['streak']}-day streak | {d['total_pages']} total pages | "
                f"top {100-d['rank_pct_ahead']}% reader. "
                f"Open book and star decorations. No faces. 16:9, high quality."
            )
            result = imagen.generate_images(
                prompt=prompt,
                number_of_images=1,
                aspect_ratio="16:9",
                safety_filter_level="block_only_high",
            )
            if not result.images:
                return None
            img_obj = result.images[0]
            # Try different attribute names across SDK versions
            for attr in ("_pil_image", "image", "_image"):
                pil = getattr(img_obj, attr, None)
                if pil is not None:
                    buf = io.BytesIO()
                    pil.save(buf, format="JPEG", quality=90)
                    return buf.getvalue()
            # Last resort: raw bytes attribute
            for attr in ("_image_bytes", "image_bytes", "data"):
                raw = getattr(img_obj, attr, None)
                if isinstance(raw, (bytes, bytearray)):
                    return bytes(raw)
            self.stdout.write("Imagen: rasm atributi topilmadi")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Imagen: {e}"))
        return None

    def _fallback(self, lang):
        d = DEMO
        if lang == "ru":
            return (f"Отличная работа, <b>{d['full_name']}</b>! "
                    f"На этой неделе — <b>{d['week_pages']} страниц</b>. "
                    f"🔥 Серия <b>{d['streak']} дней</b>. Так держать! 🚀")
        return (f"Ajoyib natija, <b>{d['full_name']}</b>! "
                f"Bu hafta — <b>{d['week_pages']} bet</b>. "
                f"🔥 Streak <b>{d['streak']} kun</b>. Davom eting! 🚀")
