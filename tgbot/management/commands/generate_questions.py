import os
import json
import asyncio
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = "Avtomatik ravishda AI orqali o'yin savollarini generatsiya qilish va faylga qo'shish"

    def add_arguments(self, parser):
        parser.add_argument('--flavor', type=str, required=True, help="O'yin turi (masalan: anagram, wordle, crossword)")
        parser.add_argument('--count', type=int, default=10, help="Nechta savol yaratish kerak?")
        parser.add_argument('--api_key', type=str, help="Google Gemini API kaliti (yo'q bo'lsa GEMINI_API_KEY env dan olinadi)")

    def handle(self, *args, **options):
        flavor = options['flavor']
        count = options['count']
        api_key = options.get('api_key') or os.environ.get("GEMINI_API_KEY")

        if not api_key:
            self.stdout.write(self.style.ERROR("API kalit topilmadi! --api_key orqali bering yoki GEMINI_API_KEY ni .env ga yozing."))
            return

        try:
            import google.generativeai as genai
        except ImportError:
            self.stdout.write(self.style.ERROR("google-generativeai kutubxonasi o'rnatilmagan! 'pip install google-generativeai' ni ishlating."))
            return

        genai.configure(api_key=api_key)
        
        # O'yin turlariga qarab promptlarni sozlaymiz
        prompts = {
            "anagram": (
                "Sen O'zbek adabiyoti bo'yicha uzbek tilida anagramma savollar tuzishing kerak.\n"
                f"Jami {count} ta savol tuzgin. Qaytaradigan javobing faqat toza JSON formatida, ro'yxat (list) bo'lishi shart.\n"
                "Strukturasi: [{\"anagram\": \"B M R O E U N A\", \"answer\": \"Boburnoma\", \"hint\": \"Bobur asari\", \"distractors\": [\"Xamsa\", \"Navoiy\", \"Qutadg'u bilig\"]}]\n"
                "Iltimos, JSON dan boshqa hech qanday izoh qo'shma."
            ),
            "wordle": (
                "Sen O'zbek adabiyoti, asarlar va qahramonlariga doir so'z topish (wordle) o'yini uchun savollar tuzishing kerak.\n"
                f"Jami {count} ta savol tuzgin. Qaytaradigan javobing faqat toza JSON formatida, ro'yxat (list) bo'lishi shart.\n"
                "Strukturasi: [{\"word\": \"OTABEK\", \"hint\": \"O'tkan kunlar bosh qahramoni\", \"distractors\": [\"KUMUSH\", \"ANVAR\", \"ZAYNAB\"]}]\n"
                "Iltimos, JSON dan boshqa hech qanday izoh qo'shma."
            ),
            "crossword": (
                "Sen O'zbek adabiyoti krossvord savollari tuzishing kerak.\n"
                f"Jami {count} ta savol tuzgin. Qaytaradigan javobing faqat toza JSON formatida, ro'yxat (list) bo'lishi shart.\n"
                "Strukturasi: [{\"answer\": \"CHO'LPON\", \"clue\": \"'Kecha va kunduz' romani muallifi kim?\", \"distractors\": [\"QODIRIY\", \"FITRAT\", \"OYBEK\"]}]\n"
                "Iltimos, JSON dan boshqa hech qanday izoh qo'shma."
            )
        }

        prompt = prompts.get(flavor)
        if not prompt:
            self.stdout.write(self.style.ERROR(f"Bu o'yin turi ({flavor}) uchun avtomatik generatsiya hali qo'shilmagan."))
            return

        self.stdout.write(f"AI orqali {count} ta {flavor} savoli yaratilmoqda... Iltimos kuting.")
        
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        
        try:
            new_questions = json.loads(text.strip())
        except json.JSONDecodeError:
            self.stdout.write(self.style.ERROR(f"AI noto'g'ri formatda javob qaytardi:\n{text}"))
            return

        if not isinstance(new_questions, list):
            self.stdout.write(self.style.ERROR("Kutilgan JSON list (ro'yxat) kelmadi."))
            return

        # Faylga qo'shish
        base_dir = getattr(settings, 'BASE_DIR', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        file_path = os.path.join(base_dir, 'tgbot', 'services', 'questions', f'{flavor}.py')

        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"Fayl topilmadi: {file_path}"))
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        new_dicts_str = ",\n  " + ",\n  ".join([json.dumps(q, ensure_ascii=False) for q in new_questions])
        last_bracket_idx = content.rfind(']')
        
        if last_bracket_idx != -1:
            content = content[:last_bracket_idx] + new_dicts_str + "\n" + content[last_bracket_idx:]
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.stdout.write(self.style.SUCCESS(f"Muvaffaqiyatli! {len(new_questions)} ta savol {flavor}.py ga qo'shildi."))
        else:
            self.stdout.write(self.style.ERROR(f"Fayl formati xato ( ] qavs topilmadi )."))
