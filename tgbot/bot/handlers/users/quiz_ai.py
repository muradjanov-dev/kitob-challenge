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

client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy_key"))

AI_PROMPT = """You are an AI that creates quizzes. You will receive text or an image.
Extract the main concepts and create exactly 5 multiple choice questions.
Return ONLY valid JSON in the following format:
{
  "title": "Quiz Title based on text",
  "description": "Short description",
  "time_per_question": 30,
  "questions": [
    {
      "text": "Question text here?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_index": 1,
      "hint": "Hint if they get it wrong"
    }
  ]
}
Make sure options are up to 4 items. correct_index is 0-indexed.
Do not wrap JSON in markdown block. Just pure JSON.
"""

@dp.message_handler(content_types=['text', 'photo', 'document'], state=AIQuizCreateState.input_content)
async def process_ai_input(message: types.Message, state: FSMContext):
    if not os.environ.get("OPENAI_API_KEY"):
        await message.answer("⚠️ Bot adminstratori OPENAI_API_KEY kalitini kiritmagan. Bot ishlay olmaydi.")
        await state.finish()
        return

    user = await aget_user(message.from_user.id)
    
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
        messages = [
            {"role": "system", "content": AI_PROMPT}
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
                    {"type": "text", "text": "Rasmdan foydalanib quiz yarating."},
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
            
            messages.append({"role": "user", "content": f"Quyidagi kitob matnidan foydalanib eng muhim joylaridan quiz yarating:\n\n{extracted_text}"})
        else:
            messages.append({"role": "user", "content": message.text})

        # All inputs (text, image, pdf) are handled by gpt-4o-mini for maximum speed and cost efficiency
        model = "gpt-4o-mini"

        # Call OpenAI
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1500,
            temperature=0.7,
        )

        result_text = response.choices[0].message.content.strip()
        # Clean markdown code block if present
        if result_text.startswith("```json"):
            result_text = result_text[7:-3].strip()
        elif result_text.startswith("```"):
            result_text = result_text[3:-3].strip()
            
        data = json.loads(result_text)

        # Save to DB        
        @sync_to_async
        def create_quiz_from_ai(ai_data):
            q = Quiz.objects.create(
                creator=user,
                title=ai_data.get("title", "AI Quiz"),
                description=ai_data.get("description", ""),
                time_per_question=ai_data.get("time_per_question", 30),
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

    except Exception as e:
        await msg.edit_text(f"❌ Xatolik yuz berdi: {e}\nIltimos, qaytadan urinib ko'ring yoki admin bilan bog'laning.")
        await state.finish()
