import os
import time
import requests
from django.core.management.base import BaseCommand


MESSAGE_UZ = (
    "🎉 <b>Bot yangilandi!</b>\n\n"
    "Yangi imkoniyatlar:\n\n"
    "🎮 <b>10+ ta yangi jonli o'yin</b> — Zanjir, Emoji Kitob, Hikmat Xazinasi, "
    "Kitob Detektivi, Omon qolish, Bilim Qal'asi va boshqalar. Har kuni soat "
    "<b>10:00</b> va <b>22:00</b> da avtomatik boshlanadi!\n\n"
    "🎁 <b>Bepul Premium sinov</b> — har kuni tasodifiy 10 kishiga 3 soatlik "
    "Premium beriladi\n\n"
    "🌟 <b>Do'stingizga Premium sovg'a qiling</b> (YANGI!) — endi Premiumni "
    "o'zingiz uchun emas, do'stingiz uchun ham sotib olishingiz mumkin\n\n"
    "🗓 <b>3 oylik Premium tarif</b> qo'shildi (YANGI!) — uzoq muddatga arzonroq\n\n"
    "📚 <b>Kitob Viktorina</b> — kuniga 2 marta kitobni taxmin qiling, "
    "+100 Kitobcha yutib oling\n\n"
    "🏆 <b>Reytinglarda endi TOP 50</b> ko'rinadi (ilgari faqat 10 edi)\n\n"
    "❓ <b>\"Qanday ishlaydi\"</b> tugmasi — botdan foydalanishni bosqichma-bosqich "
    "tushuntiradi\n\n"
    "🔄 Yangi imkoniyatlardan foydalanish uchun pastda <b>/start</b> bosing!"
)

MESSAGE_RU = (
    "🎉 <b>Бот обновлён!</b>\n\n"
    "Новые возможности:\n\n"
    "🎮 <b>10+ новых живых игр</b> — Zanjir, Эмодзи Китоб, Хикмат Хазинаси, "
    "Китоб Детективи, Омон қолиш, Билим Қальаси и другие. Каждый день в "
    "<b>10:00</b> и <b>22:00</b> запускаются автоматически!\n\n"
    "🎁 <b>Бесплатный пробный Premium</b> — каждый день 10 случайным "
    "пользователям даётся 3 часа Premium\n\n"
    "🌟 <b>Подарите Premium другу</b> (НОВОЕ!) — теперь можно купить Premium "
    "не только себе, но и другу\n\n"
    "🗓 <b>Тариф Premium на 3 месяца</b> (НОВОЕ!) — выгоднее на долгий срок\n\n"
    "📚 <b>Китоб Викторина</b> — дважды в день угадывайте книгу, получайте "
    "+100 Китобча\n\n"
    "🏆 <b>В рейтингах теперь ТОП 50</b> (раньше было только 10)\n\n"
    "❓ <b>«Qanday ishlaydi»</b> — кнопка, которая пошагово объясняет, как "
    "пользоваться ботом\n\n"
    "🔄 Нажмите <b>/start</b> внизу, чтобы воспользоваться новыми возможностями!"
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
