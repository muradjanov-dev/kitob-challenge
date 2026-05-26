"""
Django-dan mustaqil standalone script — faqat requests va google-generativeai
ishlatadi. Railway serverida yoki mahalliyda ishlaydi.

Ishlatish (Railway console yoki SSH):
    python manage.py trigger_weekly_report_test
"""
import os
import io
import requests
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Gemini AI + Imagen 3 test — adminga demo report yuborish (DB siz)"

    def add_arguments(self, parser):
        parser.add_argument("--admin-id", type=int, default=None)
        parser.add_argument("--lang", choices=["uz", "ru"], default="uz")
        parser.add_argument("--text-only", action="store_true")

    def handle(self, *args, **options):
        token = os.environ.get("API_TOKEN", "")
        gemini_key = os.environ.get("GEMINI_API_KEY", "")

        admin_id = options["admin_id"] or int(
            os.environ.get("ADMINS", "917456291").split(",")[0].strip()
        )
        lang = options["lang"]
        text_only = options["text_only"]

        self.stdout.write(f"Admin ID: {admin_id}")
        self.stdout.write(f"GEMINI_API_KEY: {'✅ bor' if gemini_key else '❌ YOQ'}")

        # ── 1. AI text generatsiya ──────────────────────────────────────
        full_name = "Aziz Karimov"
        week_pages = 312
        prev_week_pages = 245
        week_audio_minutes = 87
        streak = 12
        total_pages = 4350
        books_finished_week = 1
        rank_pct_ahead = 78

        ai_text = self._generate_text(
            gemini_key=gemini_key,
            full_name=full_name,
            week_pages=week_pages,
            prev_week_pages=prev_week_pages,
            week_audio_minutes=week_audio_minutes,
            streak=streak,
            total_pages=total_pages,
            books_finished_week=books_finished_week,
            rank_pct_ahead=rank_pct_ahead,
            lang=lang,
        )

        header = (
            "💎 <b>Haftalik Premium Hisobot</b> 📊 <i>(TEST)</i>"
            if lang != "ru" else
            "💎 <b>Еженедельный Premium Отчёт</b> 📊 <i>(ТЕСТ)</i>"
        )
        ach_block = (
            "\n\n🏆 <b>Bu haftadagi yutuqlar:</b>\n"
            "🔥 <b>7 kunlik streak</b> <i>(+70 Kitobcha)</i>\n"
            "📚 <b>Yuz bet</b> <i>(+20 Kitobcha)</i>"
        ) if lang != "ru" else (
            "\n\n🏆 <b>Достижения этой недели:</b>\n"
            "🔥 <b>Серия 7 дней</b> <i>(+70 Kitobcha)</i>\n"
            "📚 <b>Сто страниц</b> <i>(+20 Kitobcha)</i>"
        )
        full_text = f"{header}\n\n{ai_text}{ach_block}"

        url_msg = f"https://api.telegram.org/bot{token}/sendMessage"
        url_photo = f"https://api.telegram.org/bot{token}/sendPhoto"

        # ── 2. Imagen 3 rasm ───────────────────────────────────────────
        img_bytes = None
        if not text_only and gemini_key:
            self.stdout.write("🎨 Imagen 3 rasm generatsiya qilinmoqda...")
            img_bytes = self._generate_image(
                gemini_key=gemini_key,
                full_name=full_name,
                week_pages=week_pages,
                week_audio_minutes=week_audio_minutes,
                streak=streak,
                total_pages=total_pages,
                books_finished_week=books_finished_week,
                rank_pct_ahead=rank_pct_ahead,
            )
            if img_bytes:
                self.stdout.write(self.style.SUCCESS("✅ Rasm tayyor"))
            else:
                self.stdout.write(self.style.WARNING("⚠️  Rasm generatsiya qilinmadi"))

        # ── 3. Yuborish ────────────────────────────────────────────────
        if img_bytes:
            resp = requests.post(
                url_photo,
                data={"chat_id": admin_id, "parse_mode": "HTML"},
                files={"photo": ("report.jpg", io.BytesIO(img_bytes), "image/jpeg")},
                timeout=20,
            )
            if resp.ok:
                self.stdout.write(self.style.SUCCESS("📸 Rasm yuborildi"))
            else:
                self.stdout.write(self.style.WARNING(f"Rasm yuborishda xatolik: {resp.text[:200]}"))

        resp = requests.post(
            url_msg,
            data={"chat_id": admin_id, "text": full_text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.ok:
            self.stdout.write(self.style.SUCCESS(f"✅ Test report yuborildi → {admin_id}"))
        else:
            self.stdout.write(self.style.ERROR(f"❌ Xatolik: {resp.text[:300]}"))

    def _generate_text(self, gemini_key, full_name, week_pages, prev_week_pages,
                       week_audio_minutes, streak, total_pages, books_finished_week,
                       rank_pct_ahead, lang):
        if not gemini_key:
            return self._fallback_text(full_name, week_pages, prev_week_pages, total_pages, streak, lang)
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.0-flash")

            pct = ""
            if prev_week_pages > 0:
                p = round((week_pages - prev_week_pages) * 100 / prev_week_pages)
                pct = f"▲ +{p}%" if p > 0 else f"▼ {p}%"
            else:
                pct = "yangi rekord 🆕"

            audio_h = week_audio_minutes // 60
            audio_m = week_audio_minutes % 60
            audio_str = f"{audio_h} soat {audio_m} daqiqa" if audio_h else f"{week_audio_minutes} daqiqa"

            if lang == "ru":
                prompt = f"""Ты мотивационный тренер по чтению. Напиши {full_name} персональный еженедельный отчёт по чтению.
Стиль: тёплый, воодушевляющий. Формат: только Telegram HTML (<b>, <i>). 180-250 слов. Имя {full_name} использовать 2+ раза.
Статистика: прочитано {week_pages} стр (прошлая неделя {prev_week_pages} стр, {pct}), аудио {audio_str},
завершено книг {books_finished_week}, всего страниц {total_pages}, стрик {streak} дней, рейтинг топ {100-rank_pct_ahead}%.
Только текст, без лишнего."""
            else:
                prompt = f"""Sen motivatsion kitobxonlik trenerisisan. {full_name} ga shaxsiy haftalik o'qish hisobotini yoz.
Uslub: iliq, rag'batlantiruvchan. Format: faqat Telegram HTML (<b>, <i>). 180-250 so'z. Ism {full_name} 2+ marta ishlatilsin.
Statistika: o'qildi {week_pages} bet (o'tgan hafta {prev_week_pages} bet, {pct}), audio {audio_str},
tugallangan kitoblar {books_finished_week} ta, jami {total_pages} bet, streak {streak} kun, reyting top {100-rank_pct_ahead}%.
Faqat matn, boshqa hech narsa yozma."""

            response = model.generate_content(
                prompt,
                generation_config={"temperature": 0.85, "max_output_tokens": 600},
            )
            self.stdout.write(self.style.SUCCESS("✅ Gemini text generatsiya qilindi"))
            return response.text.strip()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Gemini xatolik: {e}"))
            return self._fallback_text(full_name, week_pages, prev_week_pages, total_pages, streak, lang)

    def _fallback_text(self, full_name, week_pages, prev_week_pages, total_pages, streak, lang):
        if lang == "ru":
            return (f"Отличная работа, <b>{full_name}</b>! На этой неделе вы прочитали <b>{week_pages} страниц</b> "
                    f"(прошлая неделя: {prev_week_pages} стр). Всего прочитано: <b>{total_pages} страниц</b>. "
                    f"🔥 Серия: <b>{streak} дней</b>. Продолжайте в том же духе! 🚀")
        return (f"Ajoyib natija, <b>{full_name}</b>! Bu hafta <b>{week_pages} bet</b> o'qidingiz "
                f"(o'tgan hafta: {prev_week_pages} bet). Jami: <b>{total_pages} bet</b>. "
                f"🔥 Streak: <b>{streak} kun</b>. Davom eting! 🚀")

    def _generate_image(self, gemini_key, full_name, week_pages, week_audio_minutes,
                        streak, total_pages, books_finished_week, rank_pct_ahead):
        try:
            import google.generativeai as genai
            from PIL import Image as _PIL
            genai.configure(api_key=gemini_key)
            imagen = genai.ImageGenerationModel("imagen-3.0-generate-002")

            prompt = (
                f"A beautiful personalized weekly reading report card for '{full_name}'. "
                f"Modern clean infographic style, warm golden and deep navy blue colors. "
                f"Display these stats prominently: "
                f"'{week_pages} pages this week', "
                f"'{week_audio_minutes} audio minutes', "
                f"'{streak}-day streak', "
                f"'{total_pages} total pages', "
                f"'{books_finished_week} books finished', "
                f"'Top {100 - rank_pct_ahead}% reader'. "
                f"Include decorative open book and golden star elements. "
                f"No human faces. 16:9 landscape, professional design, high quality."
            )
            result = imagen.generate_images(
                prompt=prompt,
                number_of_images=1,
                aspect_ratio="16:9",
                safety_filter_level="block_only_high",
            )
            if result.images:
                img = result.images[0]
                # Convert to bytes
                buf = io.BytesIO()
                # _image attribute contains PIL image
                pil_img = img._pil_image if hasattr(img, '_pil_image') else None
                if pil_img is None and hasattr(img, 'image'):
                    pil_img = img.image
                if pil_img:
                    pil_img.save(buf, format="JPEG", quality=90)
                    return buf.getvalue()
                # Try raw bytes
                if hasattr(img, '_image_bytes'):
                    return img._image_bytes
            self.stdout.write(self.style.WARNING("Imagen: rasm qaytarilmadi"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Imagen xatolik: {e}"))
        return None
