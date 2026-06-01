import os
import json
import base64
from django.core.cache import cache

from aiogram import types
from aiogram.dispatcher import FSMContext
from asgiref.sync import sync_to_async
from openai import AsyncOpenAI

from tgbot.bot.loader import dp, bot
from tgbot.bot.states.main import AIQuizCreateState
from tgbot.bot.utils import aget_user
from tgbot.models import Quiz, QuizQuestion, QuizOption, Payment
from tgbot.bot.handlers.users.quiz_admin import _quiz_view_kb, _quiz_view_text
from django.utils import timezone

# client will be initialized dynamically inside handlers using the environment variable


def _script_hint(text: str) -> str:
    """Detect the dominant alphabet of the source text and return a hard,
    explicit language directive. gpt-4o-mini tends to revert to English for
    famous works (e.g. 'Animal Farm') unless we anchor the output language
    to the actual script of the supplied text."""
    if not text:
        return ""
    cyrillic = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    if cyrillic >= 15 and cyrillic >= latin:
        return (
            "\n\n⚠️ MAJBURIY TIL QOIDASI: Manba matn KIRILL alifbosida yozilgan "
            "(o'zbek yoki rus tili). Butun viktorinani — sarlavha, tavsif, "
            "savollar, variantlar va maslahatlarni — MANBA MATN BILAN BIR XIL "
            "TILDA va AYNAN KIRILL alifbosida yozing. Inglizcha yoki lotin "
            "alifbosidan FOYDALANMANG."
        )
    # Latin-script Uzbek markers (o', g', apostrophes, common words)
    low = text.lower()
    uz_markers = ("o'", "g'", "o‘", "g‘", " va ", " bilan ", " uchun ", "ning ", "lar ")
    if latin >= 15 and any(m in low for m in uz_markers):
        return (
            "\n\n⚠️ MAJBURIY TIL QOIDASI: Manba matn LOTIN alifbosidagi o'zbek "
            "tilida. Butun viktorinani o'zbek tilida (lotin alifbosida) yozing. "
            "Inglizchaga tarjima QILMANG."
        )
    return ""


# Shared language/content rules appended to every generation prompt.
_PROMPT_RULES = """
Make sure options are up to 4 items. correct_index is 0-indexed.
Do not wrap JSON in markdown block. Just pure JSON.

CRITICAL LANGUAGE REQUIREMENT (HIGHEST PRIORITY):
Generate the ENTIRE JSON response (title, description, question text, options, and hints)
in EXACTLY the SAME LANGUAGE and the SAME ALPHABET/SCRIPT as the provided source text.
- Detect the language from the SUPPLIED TEXT ITSELF, not from your prior knowledge of the work.
- DO NOT translate into English. DO NOT switch to the book's "original" language.
- A book may be a famous foreign work (e.g. 'Animal Farm' / 'Hayvonot fermasi'), but if the
  supplied text is in Uzbek Cyrillic, you MUST write the quiz in Uzbek Cyrillic — NOT English.
- If the source is Uzbek Cyrillic → respond in Uzbek Cyrillic.
- If the source is Uzbek Latin → respond in Uzbek Latin.
- If the source is Russian → respond in Russian.
- If the source is English → respond in English.
Matching the source script is mandatory and overrides everything else.

CRITICAL CONTENT REQUIREMENT:
Focus ONLY on the actual content, story, characters, or core educational topic of the book/document.
Absolutely IGNORE any publisher advertisements, library introductions (such as 'ziyouz.com', 'Ziyouz kutubxonasi', library flyers, website purposes, etc.), copyright notices, or web link flyers at the beginning or end of the document.
The quiz must be about the BOOK'S actual content, not the website or library from which it was downloaded.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("aiqz_q:"), state=AIQuizCreateState.question_count)
async def process_question_count(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    q_count = int(call.data.split(":")[1])
    await state.update_data(question_count=q_count)
    
    kb = InlineKeyboardMarkup(row_width=5)
    kb.add(
        InlineKeyboardButton("15s", callback_data="aiqz_t:15"),
        InlineKeyboardButton("25s", callback_data="aiqz_t:25"),
        InlineKeyboardButton("35s", callback_data="aiqz_t:35"),
        InlineKeyboardButton("45s", callback_data="aiqz_t:45"),
        InlineKeyboardButton("55s", callback_data="aiqz_t:55"),
    )
    await call.message.edit_text(
        "🤖 <b>AI yordamida Quiz yaratish</b>\n\n"
        f"Tanlangan savollar soni: <b>{q_count} ta</b>\n\n"
        "Har bir savol uchun vaqt qancha bo'lishini xohlaysiz? Quyidagi tugmalardan birini tanlang:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await AIQuizCreateState.time_limit.set()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("aiqz_t:"), state=AIQuizCreateState.time_limit)
async def process_time_limit(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    t_limit = int(call.data.split(":")[1])
    await state.update_data(time_limit=t_limit)
    
    state_data = await state.get_data()
    q_count = state_data.get("question_count", 5)
    
    await call.message.edit_text(
        "🤖 <b>AI yordamida Quiz yaratish</b>\n\n"
        f"Savollar soni: <b>{q_count} ta</b>\n"
        f"Savol vaqti: <b>{t_limit} soniya</b>\n\n"
        "Sozlamalar saqlandi. Endi, quiz yaratish uchun matn yuboring, rasm yuklang yoki PDF fayl jo'nating:",
        parse_mode="HTML"
    )
    await AIQuizCreateState.input_content.set()


@dp.message_handler(content_types=['text', 'photo', 'document'], state=AIQuizCreateState.input_content)
async def process_ai_input(message: types.Message, state: FSMContext):
    if not os.environ.get("OPENAI_API_KEY"):
        await message.answer("⚠️ Bot adminstratori OPENAI_API_KEY kalitini kiritmagan. Bot ishlay olmaydi.")
        await state.finish()
        return

    user = await aget_user(message.from_user.id)
    
    # Get user choices
    state_data = await state.get_data()
    q_count = state_data.get("question_count", 5)
    t_limit = state_data.get("time_limit", 30)
    
    # 10 limit per day check
    cache_key = f"ai_quiz_limit_{user.id}"
    today_count = cache.get(cache_key, 0)
    if today_count >= 10:
        await message.answer(
            "⚠️ <b>Limit tugadi!</b>\n\n"
            "AI tarmog'ini ortiqcha yuklamaslik uchun bir kunda maksimal <b>10 ta</b> quiz yaratish mumkin. "
            "Iltimos, ertaga qayta urinib ko'ring.",
            parse_mode="HTML"
        )
        await state.finish()
        return

    pdf_cache_key = f"ai_quiz_pdf_limit_{user.id}"
    if message.document:
        if not message.document.file_name.lower().endswith('.pdf'):
            await message.answer("⚠️ Iltimos, faqat PDF formatidagi fayllarni yuboring.")
            return

        # PDF input requires active Premium (any tier). Super-premium check
        # has been retired — all Premium subscribers get one PDF/day.
        @sync_to_async
        def check_premium():
            return Payment.objects.filter(
                user=user,
                status="paid",
                end_date__gte=timezone.localdate(),
            ).exists()

        if not await check_premium():
            await message.answer(
                "💎 <b>Premium funksiyasi!</b>\n\n"
                "PDF kitoblar orqali avtomatik quiz yaratish uchun sizda "
                "<b>Premium</b> obunasi bo'lishi kerak.\n\n"
                "Obuna bo'lish uchun Asosiy menyudan <i>💎 Premium</i> bo'limiga o'ting.",
                parse_mode="HTML"
            )
            return

        # Premium PDF cap: 1 generation per day (the 10/day general cap still
        # applies on top, so this is a separate, stricter PDF-only counter).
        if cache.get(pdf_cache_key, 0) >= 1:
            await message.answer(
                "⚠️ <b>Bugungi PDF limit tugadi!</b>\n\n"
                "Premium foydalanuvchilar bir kunda <b>1 marta</b> PDF dan quiz yarata oladi. "
                "Ertaga qayta urinib ko'ring (matn yoki rasm orqali esa kuniga 10 martagacha mumkin).",
                parse_mode="HTML"
            )
            return

    msg = await message.answer("⏳ AI ma'lumotni tahlil qilib, quiz generatsiya qilmoqda... Iltimos kuting.")
    
    try:
        prompt = f"""You are an AI that creates quizzes. You will receive text or an image.
Extract the main concepts and create exactly {q_count} multiple choice questions.
Return ONLY valid JSON in the following format:
{{
  "title": "Quiz Title based on text",
  "description": "Short description",
  "time_per_question": {t_limit},
  "questions": [
    {{
      "text": "Question text here?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_index": 1,
      "hint": "Hint if they get it wrong"
    }}
  ]
}}
""" + _PROMPT_RULES

        messages = [
            {"role": "system", "content": prompt}
        ]

        if message.photo:
            # Get the highest resolution photo
            photo = message.photo[-1]
            file_info = await bot.get_file(photo.file_id)
            file_bytes = await bot.download_file(file_info.file_path)
            base64_image = base64.b64encode(file_bytes.read()).decode('utf-8')
            
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "Rasmdan foydalanib quiz yarating. Viktorinani rasmda "
                        "ko'rsatilgan matn bilan BIR XIL tilda va alifboda yozing "
                        "(inglizchaga tarjima qilmang)."
                    )},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            })
        elif message.document:
            file_info = await bot.get_file(message.document.file_id)
            pdf_bytes_io = await bot.download_file(file_info.file_path)

            import fitz
            doc = fitz.open(stream=pdf_bytes_io.read(), filetype="pdf")
            extracted_text = ""
            for page in doc:
                extracted_text += page.get_text() + "\n"
            doc.close()

            # Limit text if it's too huge to prevent token overflow (approx 80k chars)
            extracted_text = extracted_text[:80000]

            hint = _script_hint(extracted_text)
            messages.append({"role": "user", "content": (
                f"Quyidagi kitob matnidan foydalanib eng muhim joylaridan quiz yarating:"
                f"{hint}\n\n{extracted_text}"
            )})
        else:
            hint = _script_hint(message.text or "")
            messages.append({"role": "user", "content": (message.text or "") + hint})

        # All inputs (text, image, pdf) are handled by gpt-4o-mini for maximum speed and cost efficiency
        model = "gpt-4o-mini"

        # Call OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        openai_client = AsyncOpenAI(api_key=api_key)
        # max_tokens=1500 was overflowing for 15-20 question requests — the
        # model emitted ~120+ JSON fields and the response got truncated mid-
        # string, hitting "Unterminated string at line 98..." on json.loads.
        # gpt-4o-mini supports 16K output; 8000 is plenty for ~30 questions
        # with hints and options.
        response = await openai_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=8000,
            temperature=0.7,
            response_format={"type": "json_object"},
        )

        result_text = response.choices[0].message.content.strip()
        # Clean markdown code block if present
        if result_text.startswith("```json"):
            result_text = result_text.split("```json", 1)[1]
            if "```" in result_text:
                result_text = result_text.rsplit("```", 1)[0]
        elif result_text.startswith("```"):
            result_text = result_text.split("```", 1)[1]
            if "```" in result_text:
                result_text = result_text.rsplit("```", 1)[0]
        result_text = result_text.strip()
            
        data = json.loads(result_text)

        # Save to DB        
        @sync_to_async
        def create_quiz_from_ai(ai_data):
            q = Quiz.objects.create(
                creator=user,
                title=ai_data.get("title", "AI Quiz"),
                description=ai_data.get("description", ""),
                time_per_question=ai_data.get("time_per_question", t_limit),
            )
            for i, q_data in enumerate(ai_data.get("questions", [])):
                question = QuizQuestion.objects.create(
                    quiz=q,
                    text=q_data["text"],
                    hint=q_data.get("hint", ""),
                    order=i
                )
                for j, opt_text in enumerate(q_data["options"]):
                    QuizOption.objects.create(
                        question=question,
                        text=opt_text,
                        is_correct=(j == q_data.get("correct_index", 0)),
                        order=j
                    )
            return q

        quiz = await create_quiz_from_ai(data)
        
        # Increment usage counter
        if today_count == 0:
            cache.set(cache_key, 1, timeout=86400) # Reset after 24 hours
        else:
            cache.incr(cache_key)

        # Separate PDF-specific 1/day counter so PDFs are gated even when the
        # general 10/day cap isn't exhausted yet.
        if message.document and cache.get(pdf_cache_key, 0) == 0:
            cache.set(pdf_cache_key, 1, timeout=86400)
        
        await msg.delete()
        
        text = await _quiz_view_text(quiz)
        await message.answer(
            f"✅ <b>AI Quiz yaratildi!</b>\n"
            f"Quyidagi menyu orqali savollar, vaqt va matnlarni bemalol tahrirlashingiz mumkin.\n\n"
            + text,
            parse_mode="HTML",
            reply_markup=_quiz_view_kb(quiz)
        )
        await state.finish()

    except json.JSONDecodeError as e:
        # The AI response wasn't valid JSON — most commonly because the
        # output got truncated (large quiz, hit token cap). Tell the user
        # in plain language instead of dumping the raw decoder message.
        print(f"quiz_ai JSON decode failed: {e}")
        await msg.edit_text(
            "❌ AI javobi to'liq kelmadi (matn juda uzun bo'lishi mumkin).\n\n"
            "Iltimos qaytadan urinib ko'ring yoki:\n"
            "• Kamroq savol soni tanlang (masalan 10)\n"
            "• Kichikroq matn / PDF yuboring"
        )
    except Exception as e:
        print(f"quiz_ai unexpected error: {e}")
        await msg.edit_text(
            "❌ Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring "
            "yoki admin bilan bog'laning."
        )
        await state.finish()
