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


def _sample_book_text(pages: list[str], budget: int = 80000) -> str:
    """Sample PDF text from the beginning, middle, and end of the BODY (not
    the raw first N chars) so a book's front matter — title page, TOC,
    dedication, translator's/publisher's note, which can easily run 10-20+
    pages — doesn't dominate what the AI sees. Feeding it mostly front
    matter is the main reason AI-generated quizzes end up asking about the
    publisher or table of contents instead of the actual story."""
    full = "\n".join(pages)
    if len(full) <= budget:
        return full
    if len(pages) < 6:
        # Too few pages to safely trim front/back matter — just take the head.
        return full[:budget]

    skip = max(1, int(len(pages) * 0.04))
    body_pages = pages[skip: len(pages) - skip] or pages
    body = "\n".join(body_pages)
    if len(body) <= budget:
        return body

    chunk = budget // 3
    beginning = body[:chunk]
    mid_start = max(0, len(body) // 2 - chunk // 2)
    middle = body[mid_start: mid_start + chunk]
    end = body[-chunk:]
    sep = "\n\n[... kitobning ushbu qismi o'tkazib yuborildi ...]\n\n"
    return beginning + sep + middle + sep + end


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
The quiz MUST be about the actual STORY, EVENTS, CHARACTERS, and IDEAS inside the book.
Concretely, GOOD question topics are:
  - Who did what to whom, when, and why (plot events, decisions, motivations)
  - Conversations and what characters said
  - Cause-and-effect relationships in the narrative
  - Concrete details from scenes (objects, places mentioned in the story)
  - Lessons, morals, or themes that emerge from the events described

DO NOT ask about (these are FORBIDDEN topic areas — pretend the user can't see them):
  - The author's biography or life
  - The book's publication year, publisher, or page count
  - The book's purpose statement or who it is dedicated to
  - The book's chapter structure, table of contents, or preface
  - Anything from the title page, library introduction, or 'about this book' section
  - Generic 'what is the main goal of this book' meta-questions
  - Translator, editor, or library website (e.g. 'ziyouz.com', 'Ziyouz kutubxonasi')

Ignore the front matter (title page, preface, author bio, dedication, table of contents,
publisher notes) and the back matter (afterword, bibliography, library flyers) entirely.
Build every question from the actual narrative text in between.
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
        "Sozlamalar saqlandi. Endi, quiz yaratish uchun matn yuboring, rasm yuklang yoki PDF fayl jo'nating.\n\n"
        "📎 <i>Eslatma: PDF fayl hajmi eng ko'pi bilan <b>20 MB</b> bo'lishi mumkin "
        "(Telegram bot cheklovi). Kattaroq kitobning bir bo'limini alohida yuboring.</i>",
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
    
    # Daily cap, tiered by plan: regular Premium = 1/day (~30/month), Extra/
    # Super Premium = 6/day — both comfortably inside the OpenAI cost budget
    # for their respective subscription price (see cost note in the PR).
    # Trial-window users (non-Premium, granted via grant_daily_ai_quiz_trial)
    # get the regular 1/day cap for their trial hour.
    from tgbot.bot.handlers.users.payment import SUPER_PREMIUM_PRICE

    @sync_to_async
    def _is_extra_premium():
        p = (
            Payment.objects.filter(user=user, status="paid", end_date__gte=timezone.localdate())
            .order_by("-end_date").first()
        )
        return bool(p and p.amount >= SUPER_PREMIUM_PRICE)

    daily_cap = 6 if await _is_extra_premium() else 1

    cache_key = f"ai_quiz_limit_{user.id}"
    today_count = cache.get(cache_key, 0)
    if today_count >= daily_cap:
        await message.answer(
            f"⚠️ <b>Bugungi limit tugadi!</b>\n\n"
            f"Sizning tarifingizda kuniga <b>{daily_cap} ta</b> AI quiz yaratish mumkin. "
            "Ertaga qayta urinib ko'ring.",
            parse_mode="HTML"
        )
        await state.finish()
        return

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

        # Telegram bots can only download files up to 20 MB via getFile. A
        # larger file would fail deep inside bot.get_file() and surface as the
        # generic "Xatolik" — so reject it up front with a clear reason.
        MAX_PDF_BYTES = 20 * 1024 * 1024
        if message.document.file_size and message.document.file_size > MAX_PDF_BYTES:
            size_mb = message.document.file_size / (1024 * 1024)
            await message.answer(
                f"⚠️ <b>Fayl juda katta ({size_mb:.0f} MB).</b>\n\n"
                f"Telegram bot orqali eng ko'pi bilan <b>20 MB</b> gacha PDF qabul qila oladi.\n"
                f"Iltimos, kichikroq fayl yoki kitobning bir bo'limini alohida PDF qilib yuboring.",
                parse_mode="HTML",
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
            pages = [page.get_text() for page in doc]
            doc.close()

            extracted_text = _sample_book_text(pages, budget=80000)

            hint = _script_hint(extracted_text)
            messages.append({"role": "user", "content": (
                f"Quyidagi kitob matnidan foydalanib eng muhim joylaridan quiz yarating. "
                f"Matn kitobning boshi, o'rtasi va oxiridan olingan uch qismdan iborat — "
                f"ular orasida uzilishlar bor, buni tabiiy qabul qiling:"
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
