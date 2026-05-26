"""
Weekly AI Report generator — Google Gemini API.

Har shanba kechqurun Premium foydalanuvchilarga:
  1. Ismlari yozilgan shaxsiy haftalik statistika report (AI generated)
  2. Hafta davomida qo'lga kiritilgan yutuqlar (Tabriknoma)

Ishlatish:
    from tgbot.services.weekly_ai_report import generate_weekly_report
    text = generate_weekly_report(user_data)
"""
from __future__ import annotations

import os
import re
from typing import Optional


def _gemini_client():
    """Return a configured Gemini GenerativeModel instance."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError(
            "google-generativeai not installed. "
            "Run: pip install google-generativeai"
        )
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.0-flash")


def generate_weekly_report(
    full_name: str,
    week_pages: int,
    prev_week_pages: int,
    week_audio_minutes: int,
    prev_week_audio_minutes: int,
    books_finished_week: int,
    total_books_finished: int,
    total_pages_all_time: int,
    streak: int,
    new_achievements: list[dict],     # [{"emoji": "🔥", "title_uz": "..."}, ...]
    rank_pct_ahead: int,               # % of users behind this user (by pages)
    avg_pages_per_day_week: float,
    best_day_pages: int,
    language: str = "uz",
) -> str:
    """
    Call Gemini to generate a personal weekly report.
    Returns HTML-safe Telegram text (no markdown, only <b> and <i> tags).
    Falls back to a static template if API call fails.
    """
    pct_change = _pct_change(prev_week_pages, week_pages)
    audio_pct_change = _pct_change(prev_week_audio_minutes, week_audio_minutes)
    streak_comment = _streak_comment(streak, language)
    achievements_block = _format_achievements(new_achievements, language)
    week_audio_h = week_audio_minutes // 60
    week_audio_m = week_audio_minutes % 60
    audio_str = (
        f"{week_audio_h} soat {week_audio_m} daqiqa"
        if week_audio_h > 0 else f"{week_audio_minutes} daqiqa"
    ) if week_audio_minutes > 0 else "0 daqiqa"

    if language == "ru":
        prompt = _build_prompt_ru(
            full_name=full_name,
            week_pages=week_pages,
            prev_week_pages=prev_week_pages,
            pct_change=pct_change,
            week_audio=audio_str,
            audio_pct_change=audio_pct_change,
            books_finished_week=books_finished_week,
            total_books_finished=total_books_finished,
            total_pages=total_pages_all_time,
            streak=streak,
            streak_comment=streak_comment,
            rank_pct_ahead=rank_pct_ahead,
            avg_pages=avg_pages_per_day_week,
            best_day=best_day_pages,
            achievements_block=achievements_block,
        )
    else:
        prompt = _build_prompt_uz(
            full_name=full_name,
            week_pages=week_pages,
            prev_week_pages=prev_week_pages,
            pct_change=pct_change,
            week_audio=audio_str,
            audio_pct_change=audio_pct_change,
            books_finished_week=books_finished_week,
            total_books_finished=total_books_finished,
            total_pages=total_pages_all_time,
            streak=streak,
            streak_comment=streak_comment,
            rank_pct_ahead=rank_pct_ahead,
            avg_pages=avg_pages_per_day_week,
            best_day=best_day_pages,
            achievements_block=achievements_block,
        )

    try:
        model = _gemini_client()
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.85,
                "max_output_tokens": 700,
            },
        )
        raw = response.text.strip()
        return _sanitize_html(raw)
    except Exception as e:
        print(f"[weekly_ai_report] Gemini API error: {e}")
        return _static_fallback(
            full_name=full_name,
            week_pages=week_pages,
            prev_week_pages=prev_week_pages,
            pct_change=pct_change,
            total_pages=total_pages_all_time,
            streak=streak,
            achievements_block=achievements_block,
            language=language,
        )


# ── Prompt builders ──────────────────────────────────────────────────────────

def _build_prompt_uz(
    full_name, week_pages, prev_week_pages, pct_change,
    week_audio, audio_pct_change, books_finished_week, total_books_finished,
    total_pages, streak, streak_comment, rank_pct_ahead, avg_pages, best_day,
    achievements_block,
) -> str:
    achiev_section = (
        f"\n\nBu hafta qo'lga kiritilgan YANGI YUTUQLAR:\n{achievements_block}"
        if achievements_block else ""
    )
    return f"""Sen motivatsion kitobxonlik trenerisisan. Quyidagi statistika asosida {full_name} ga \
shaxsiy haftalik report yoz. Uslub: iliq, rag'batlantiruvchan, konkret, O'zbek tilida.

Talablar:
- Foydalanuvchining ISMI {full_name} — matnda kamida 2 marta ishlat
- Telegram HTML formati: faqat <b>qalin</b> va <i>kursiv</i> teglar ishlatilsin, boshqa HTML yo'q
- Uzunlik: 180-250 so'z, 8-12 gap
- Tuzilma: 1) Salomlashuv va kuchli ochilish; 2) Asosiy statistika qisqacha; 3) O'sish/kamayish tahlili; 4) Eng zo'r natija yoki yutuq; 5) Keyingi haftaga ilhomlantiruvchi chaqiruv
- Emojilar ishlat, lekin har gapda emas — faqat kalit joylarida

FOYDALANUVCHI STATISTIKASI (bu hafta):
- Ismi: {full_name}
- O'qilgan betlar: {week_pages} bet (o'tgan hafta: {prev_week_pages} bet, o'zgarish: {pct_change})
- Audio eshitish: {week_audio} (o'tgan haftadan: {audio_pct_change})
- Tugallangan kitoblar (bu hafta): {books_finished_week} ta
- Jami tugallangan kitoblar (umuman): {total_books_finished} ta
- Jami o'qilgan betlar (hamma vaqt): {total_pages} bet
- Joriy streak: {streak} kun — {streak_comment}
- Reyting: foydalanuvchilarning {rank_pct_ahead}% dan ko'proq o'qigan
- O'rtacha kunlik o'qish (bu hafta): {avg_pages:.0f} bet/kun
- Eng yaxshi kun (bu hafta): {best_day} bet{achiev_section}

Faqat Telegram HTML text yoz, boshqa hech narsa yozma. <code> yoki ``` ishlatma."""


def _build_prompt_ru(
    full_name, week_pages, prev_week_pages, pct_change,
    week_audio, audio_pct_change, books_finished_week, total_books_finished,
    total_pages, streak, streak_comment, rank_pct_ahead, avg_pages, best_day,
    achievements_block,
) -> str:
    achiev_section = (
        f"\n\nНОВЫЕ ДОСТИЖЕНИЯ на этой неделе:\n{achievements_block}"
        if achievements_block else ""
    )
    return f"""Ты мотивационный тренер по чтению. На основе статистики ниже напиши \
{full_name} персональный еженедельный отчёт. Стиль: тёплый, воодушевляющий, конкретный, на русском языке.

Требования:
- Имя пользователя {full_name} — используй минимум 2 раза
- Формат Telegram HTML: только <b>жирный</b> и <i>курсив</i>, никакого другого HTML
- Длина: 180-250 слов, 8-12 предложений
- Структура: 1) Приветствие и сильное начало; 2) Краткие основные показатели; 3) Анализ роста/снижения; 4) Лучший результат или достижение; 5) Вдохновляющий призыв на следующую неделю
- Используй эмодзи, но не в каждом предложении — только в ключевых местах

СТАТИСТИКА ПОЛЬЗОВАТЕЛЯ (за неделю):
- Имя: {full_name}
- Прочитано страниц: {week_pages} стр (прошлая неделя: {prev_week_pages} стр, изменение: {pct_change})
- Прослушано аудио: {week_audio} (изменение: {audio_pct_change})
- Завершено книг (за неделю): {books_finished_week}
- Всего завершено книг: {total_books_finished}
- Всего прочитано страниц (за всё время): {total_pages} стр
- Текущий стрик: {streak} дней — {streak_comment}
- Рейтинг: читает больше {rank_pct_ahead}% пользователей
- Среднее в день (за неделю): {avg_pages:.0f} стр/день
- Лучший день (за неделю): {best_day} стр{achiev_section}

Пиши только Telegram HTML текст, ничего лишнего. Не используй <code> или ```."""


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pct_change(old: int, new: int) -> str:
    if old == 0:
        return "yangi rekord! 🆕" if new > 0 else "—"
    p = round((new - old) * 100 / old)
    if p > 0:
        return f"▲ +{p}%"
    if p < 0:
        return f"▼ {p}%"
    return "→ o'zgarmagan"


def _streak_comment(streak: int, language: str) -> str:
    if language == "ru":
        if streak >= 30:
            return "невероятная серия 🔥"
        if streak >= 14:
            return "отличная серия! ⚡"
        if streak >= 7:
            return "хорошая неделя 💪"
        if streak >= 3:
            return "хорошее начало 🌱"
        return "начинаем строить серию"
    else:
        if streak >= 30:
            return "ajoyib streak 🔥"
        if streak >= 14:
            return "zo'r streak! ⚡"
        if streak >= 7:
            return "yaxshi hafta 💪"
        if streak >= 3:
            return "yaxshi boshlanish 🌱"
        return "streakni qurishni boshlaymiz"


def _format_achievements(achievements: list[dict], language: str) -> str:
    if not achievements:
        return ""
    lines = []
    for ach in achievements[:5]:  # max 5 ta yutuq ko'rsatilsin
        emoji = ach.get("emoji", "🏆")
        title = ach.get("title_ru" if language == "ru" else "title_uz") or ach.get("title_uz", "")
        points = ach.get("points", 0)
        pts_str = f" (+{points} Kitobcha)" if points else ""
        lines.append(f"{emoji} <b>{title}</b>{pts_str}")
    return "\n".join(lines)


def _sanitize_html(text: str) -> str:
    """Remove unsupported HTML tags, keep only <b>, <i>, <a>."""
    # Strip code blocks
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", "", text)
    # Remove disallowed tags but keep content
    allowed = {"b", "i", "a", "u", "s"}
    text = re.sub(
        r"</?(?!(?:" + "|".join(allowed) + r")(?:\s[^>]*)?>)[a-zA-Z][^>]*>",
        "",
        text,
    )
    return text.strip()


def _static_fallback(
    full_name, week_pages, prev_week_pages, pct_change,
    total_pages, streak, achievements_block, language,
) -> str:
    """Used when Gemini API is unavailable."""
    if language == "ru":
        ach_section = f"\n\n🏆 <b>Новые достижения:</b>\n{achievements_block}" if achievements_block else ""
        return (
            f"📊 <b>Еженедельный отчёт — {full_name}</b>\n\n"
            f"Отличная работа на этой неделе, <b>{full_name}</b>!\n\n"
            f"📖 Прочитано: <b>{week_pages} страниц</b> (прошлая неделя: {prev_week_pages} стр, {pct_change})\n"
            f"📚 Всего за всё время: <b>{total_pages} страниц</b>\n"
            f"🔥 Серия: <b>{streak} дней</b>\n"
            f"{ach_section}\n\n"
            f"Продолжайте в том же духе! 🚀"
        )
    else:
        ach_section = f"\n\n🏆 <b>Yangi yutuqlar:</b>\n{achievements_block}" if achievements_block else ""
        return (
            f"📊 <b>Haftalik hisobot — {full_name}</b>\n\n"
            f"Bu hafta ham ajoyib natija, <b>{full_name}</b>!\n\n"
            f"📖 O'qildi: <b>{week_pages} bet</b> (o'tgan hafta: {prev_week_pages} bet, {pct_change})\n"
            f"📚 Jami hamma vaqt: <b>{total_pages} bet</b>\n"
            f"🔥 Streak: <b>{streak} kun</b>\n"
            f"{ach_section}\n\n"
            f"Davom eting! 🚀"
        )
