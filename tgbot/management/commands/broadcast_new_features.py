import os
import time
import requests
from django.core.management.base import BaseCommand


MESSAGE_UZ = (
    "🎉 <b>Bot yangilandi!</b>\n\n"
    "Yangi imkoniyatlar:\n"
    "♾️ <b>Premium</b>: kuniga cheksiz hisobot — barchasi avtomatik jamlanadi, "
    "guruhda esa faqat eng so'nggi (jamlangan) xabar qoladi\n"
    "📊 <b>Premium kunlik shaxsiy hisobot</b> (23:57) — bugun vs kecha, hafta, oy, yil "
    "(% bilan), reytingdagi o'rin va motivatsion xat\n"
    "🌟 <b>Yaxshilik ulashuvchi (Referal)</b> — Reytingda yangi bo'lim, top 20 taklif qiluvchilar\n"
    "🏆 <b>Kitobxonlik Challenge</b> — har 3 kunda yangi musobaqa, mukofotlar: 200/100/50 Kitobcha\n"
    "📖 / 🎧 <b>Aniq kitob turi</b> — audiokitob va qog'oz kitoblar tushunarli ko'rsatiladi\n"
    "🏆 <b>30+ yangi yutuq</b> — endi 60 dan ortiq yutuqlarni yutib olishingiz mumkin\n"
    "💎 Va boshqa ko'plab yangiliklar!\n\n"
    "🔄 Yangi imkoniyatlardan foydalanish uchun pastda <b>/start</b> bosing!"
)

MESSAGE_RU = (
    "🎉 <b>Бот обновлён!</b>\n\n"
    "Новые возможности:\n"
    "♾️ <b>Premium</b>: безлимитные отчёты в день — все автоматически суммируются, "
    "в группе остаётся только последний (итоговый) отчёт\n"
    "📊 <b>Ежедневный личный отчёт Premium</b> (23:57) — сегодня vs вчера, неделя, месяц, год "
    "(в %), место в рейтинге и мотивационное письмо\n"
    "🌟 <b>Yaxshilik ulashuvchi (Реферал)</b> — новый раздел в Рейтинге, топ 20\n"
    "🏆 <b>Kitobxonlik Challenge</b> — новый челлендж каждые 3 дня, награды: 200/100/50 Kitobcha\n"
    "📖 / 🎧 <b>Тип книги</b> — аудио и бумажные книги показаны раздельно\n"
    "🏆 <b>30+ новых достижений</b>\n"
    "💎 И многое другое!\n\n"
    "🔄 Нажмите <b>/start</b> внизу, чтобы открыть новое меню!"
)


class Command(BaseCommand):
    help = "Broadcast 'new features — click /start' announcement to all registered, non-blocked users."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Print count of recipients without sending.")

    def handle(self, *args, **options):
        from tgbot.models import TelegramProfile

        token = os.environ.get("API_TOKEN", "")
        if not token:
            self.stdout.write(self.style.ERROR("API_TOKEN not set"))
            return

        qs = TelegramProfile.objects.filter(
            is_registered=True, is_blocked=False
        ).values_list("telegram_id", "language")
        recipients = list(qs)
        self.stdout.write(f"Recipients: {len(recipients)}")

        if options["dry_run"]:
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        success = failed = 0

        for tg_id, lang in recipients:
            text = MESSAGE_RU if lang == "ru" else MESSAGE_UZ
            try:
                resp = requests.post(
                    url,
                    data={
                        "chat_id": tg_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=5,
                )
                if resp.ok:
                    success += 1
                elif resp.status_code == 429:
                    delay = resp.json().get("parameters", {}).get("retry_after", 5)
                    time.sleep(delay)
                    resp = requests.post(
                        url,
                        data={
                            "chat_id": tg_id,
                            "text": text,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                        },
                        timeout=5,
                    )
                    if resp.ok:
                        success += 1
                    else:
                        failed += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                self.stdout.write(f"send to {tg_id} failed: {e}")
            time.sleep(0.04)

        self.stdout.write(self.style.SUCCESS(
            f"Broadcast done. success={success}, failed={failed}"
        ))
