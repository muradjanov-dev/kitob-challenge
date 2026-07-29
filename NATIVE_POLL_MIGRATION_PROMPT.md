# Loyiha: Quiz tizimini Telegram native Poll (type=quiz)ga o'tkazish

## Kontekst

Kitob Challenge botida "Kitob Quiz" tizimi bor (`tgbot/bot/handlers/users/quiz_play.py`,
`quiz_admin.py`, `quiz_ai.py`, modellar `tgbot/models.py`dagi `Quiz`, `QuizQuestion`,
`QuizOption`, `QuizSession`, `QuizParticipant`, `QuizUserAnswer`). Hozirgi tizim savolni
oddiy xabar (`sendMessage`) + inline tugmalar orqali yuboradi, javobni `callback_query`
(`qans:{session_id}:{question_id}:{option_id}`) orqali qabul qiladi, va taymerni
`asyncio.sleep` + `editMessageText` bilan qo'lda chizadi (`_question_timer`,
`quiz_play.py:183-220` atrofida) — 50% va 80% momentlarida ikki marta tahrirlanadi (har
soniyada emas, Telegram rate-limitiga tegmaslik uchun atayin shunday qilingan).

**Maqsad:** Telegram'ning **native Poll** turi (`sendPoll`, `type="quiz"`) ga o'tish —
uning dumaloq countdown animatsiyasini Telegram klienti o'zi chizadi, bizning serverdan
hech qanday tahrir yubormaydi. Bu ham UX'ni yaxshilaydi (chiroyli native animatsiya), ham
rate-limit xavfini butunlay yo'q qiladi.

## Nima o'zgarishi kerak

### 1. Savol yuborish
`_send_question` (`quiz_play.py:459` atrofida, solo) va guruh versiyasi (`~line 700-730`)
`bot.send_message` + `_answer_kb` inline keyboard o'rniga `bot.send_poll(...)` chaqirishi
kerak:

```python
poll_msg = await bot.send_poll(
    chat_id=chat_id,
    question=question.text,                 # <=300 belgi — allaqachon ta'minlangan
    options=[o.text for o in opts],          # har biri <=100 belgi — ta'minlangan
    type="quiz",
    correct_option_id=[i for i, o in enumerate(opts) if o.is_correct][0],
    is_anonymous=False,                      # MAJBURIY — aks holda poll_answer'da
                                              # kim ovoz berganini bilib bo'lmaydi
    explanation=question.hint or None,       # <=200 belgi — ta'minlangan
    open_period=time_limit,                  # yoki close_date — Telegram o'zi yopadi
)
```

`options`, `explanation`, `question` uzunlik chegaralari `quiz_ai.py`da allaqachon
kiritilgan (`MAX_QUESTION_CHARS=300`, `MAX_OPTION_CHARS=100`, `MAX_HINT_CHARS=200`,
`_clip()` funksiyasi) — bu qism tayyor, faqat qo'lda tuzilgan quizlar (AI emas,
`quiz_admin.py`dagi `QuizCreateState` orqali) uchun ham xuddi shu limitlarni tekshirish/
cheklash kerak bo'ladi (hozircha ular cheklanmagan).

### 2. Javobni qabul qilish
`callback_query_handler(..., "qans:...")` (`quiz_play.py:405` atrofidagi
`answer_question`) o'rniga aiogram'ning `@dp.poll_answer_handler()` orqali kelgan
`PollAnswer` obyektini qayta ishlash kerak. `PollAnswer` faqat `poll_id`, `user`,
`option_ids` beradi — `session_id`/`question_id` bilan bog'lash uchun **poll_id →
(session_id, question_id) xaritasi** kerak (masalan Redis/cache orqali, TTL bilan, yoki
`QuizQuestion`/session modeliga `last_poll_id` maydoni qo'shib).

`_record_answer` (`quiz_play.py:123-178`)dagi mantiq (allaqachon javob berganmi tekshirish,
`QuizUserAnswer.create`, `F("score") + 1` bilan ball qo'shish) deyarli o'zgarishsiz qoladi
— faqat kirish nuqtasi callback emas, poll_answer handler bo'ladi.

### 3. Taymer / keyingi savolga o'tish
Hozir `_question_timer` `time_limit` tugagach `_advance_after_timeout` chaqiradi. Native
poll bilan ham xuddi shunday — `open_period` bilan bir xil `time_limit`ga
`asyncio.sleep(time_limit)` qo'yib, keyin pollni yopish (`bot.stop_poll`, agar Telegram
avtomatik yopmagan bo'lsa — odatda `open_period` tugagach o'zi yopadi) va keyingi savolga
o'tish kerak. Bu qism arxitektura jihatdan deyarli aynan hozirgidek qoladi, faqat oraliq
edit'lar (50%/80%) endi kerak emas — native ring buni allaqachon ko'rsatadi.

### 4. Natijalar / hisob
`_finish_session_solo` va `_finish_group_session` (allaqachon shu sessiyada chiroyli
qilib yangilangan — progress bar, blockquote CTA, "G'olib" callout) — **o'zgarishsiz
qoladi**, chunki ular `QuizParticipant.score`ga asoslanadi, u native poll bilan ham xuddi
avvalgidek to'ldiriladi.

### 5. Modellar
`Quiz`, `QuizQuestion`, `QuizOption`, `QuizSession`, `QuizParticipant`, `QuizUserAnswer` —
struktura deyarli o'zgarishsiz qoladi. Qo'shish mumkin bo'lgan yangi maydon:
`QuizSession` yoki alohida jadvalga `poll_id → question_id` xaritasini saqlash uchun
(agar cache o'rniga DB tanlansa).

## Cheklovlar (Telegram sendPoll)

- `question`: 1–300 belgi
- Har bir `option`: taxminan 1–100 belgi (10 tagacha variant)
- `explanation`: 0–200 belgi
- `open_period`: 5–600 soniya oralig'ida (yoki `close_date`)
- Guruhda **anonim bo'lmagan** (`is_anonymous=False`) quiz-poll yuborish uchun bot admin
  bo'lishi shart emas, lekin ba'zi guruh sozlamalarida cheklov bo'lishi mumkin — test
  qilib ko'rish kerak.

## Ta'sir qiladigan fayllar

- `tgbot/bot/handlers/users/quiz_play.py` — asosiy o'zgarish: `_send_question`, group
  versiyasi, `answer_question` → poll_answer handler, `_question_timer`
- `tgbot/bot/loader.py` yoki `dp` ro'yxatidan o'tish joyi — `poll_answer_handler`
  ro'yxatdan o'tkazish kerak bo'lishi mumkin
- `tgbot/bot/handlers/users/quiz_admin.py` — qo'lda quiz tuzishda ham uzunlik
  cheklovlarini qo'shish (hozir faqat AI yo'lida bor)
- `tgbot/models.py` — poll_id xaritasi uchun ehtimoliy yangi maydon/jadval

## O'zgarmasligi kerak bo'lgan narsalar

- `_finish_session_solo` / `_finish_group_session` natija xabarlari (allaqachon
  professional darajada qilingan)
- AI quiz generatsiya pipeline'i (`quiz_ai.py`) — allaqachon poll-mos uzunlikda chiqaradi
- Ball hisoblash mantig'i (`F("score") + 1`)
- Creator-credit ("Kitob Challenge kitobxoni — X tomonidan tuzilgan") matnlari

## Tavsiya etilgan bosqichlar

1. `poll_answer_handler` qo'shish + poll_id↔session/question xaritasi mexanizmini
   loyihalash (cache asosida, TTL = quiz umumiy davomiyligi + bufer).
2. Solo oqimda (`_send_question`, `answer_question`) sinab ko'rish — eng kam risk, yakka
   foydalanuvchi.
3. Guruh oqimida sinash — bir nechta odam bir vaqtda ovoz berganda scoring to'g'ri
   ishlashini tekshirish.
4. Qo'lda quiz tuzishga (`QuizCreateState`) ham uzunlik cheklovi/ogohlantirish qo'shish.
5. Eski `_answer_kb`/callback yo'lini butunlay olib tashlash (yoki fallback sifatida
   vaqtincha qoldirish — ikkalasini parallel saqlash tavsiya etilmaydi, murakkablikni
   oshiradi).
6. Ishlab chiqarishda (production) bir necha kun kuzatish — ayniqsa guruh cheklovlari
   (ba'zi guruh sozlamalarida noma'lum foydalanuvchi ovozlari cheklangan bo'lishi mumkin).

## Nega hozir emas

Bu — mavjud (ishlab turgan) savol-javob mexanizmini butunlay almashtirish, kichik
tuzatish emas. Xato qilinsa, jonli botda quizlar butunlay ishlamay qolishi mumkin.
Shuning uchun alohida, sinovdan yaxshi o'tkazilgan bosqich sifatida qilinishi tavsiya
etiladi — joriy AI-quiz-sifat/broadcast ishlaridan keyin.
