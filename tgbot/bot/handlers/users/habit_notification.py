from random import choice

from django.utils import timezone
from datetime import datetime
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType

from tgbot.bot.loader import dp, gettext as _

from tgbot.models import Habit, Payment, TelegramProfile, Action
from tgbot.bot.keyboards import send_receipt_button

FREE_TRIAL_PERIOD = 3
MONTHLY_PAYMENT = 9000
MONTHLY_PAYMENT_INWORD = "to'qqiz ming so'm"
BALL_FOR_PLUS = 5
BALL_FOR_MINUS = 2.5


def get_payment_status(user: TelegramProfile, current_time) -> bool:
    payment = Payment.objects.filter(
        user=user, status="paid").order_by("-end_date").first()
    if not payment:
        return False

    return payment.end_date > current_time.date()


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: "yes" in c.data)
async def habit_notification_handler(call: types.CallbackQuery, state: FSMContext):
    if ":" not in call.data:
        # Handle cases like "ignore" or other formats if needed, or just return
        return
    action_id = call.data.split(":")[1]
    action = Action.objects.filter(id=action_id).first()
    if not action:
        return

    habit = action.habit

    current_time = timezone.localtime()
    elapsed_days = (current_time.date() - habit.created_at.date()).days

    payment_status = get_payment_status(habit.user, current_time)
    if not payment_status and elapsed_days > FREE_TRIAL_PERIOD:
        payment_message = "📢 Xurmatli Lider kitobxon 5-kun davomida uchyapsiz!\n\n"
        payment_message += "Tabriklaymiz siz yondiryapsiz, shu tempda davom eting🦾\n\n"
        payment_message += "Davom etish uchun ba'zi texnik va tashkiliy harajatlar bor shunga biz buni qoplash uchun ham kichik summa bo'lsa ham belgilashga harakat qildik 😌\n\n"
        payment_message += "Xurmatli Lider, kitobxonlarni safini kengaytirishga hissa qo'shishga va super/xayrli odatlarini shakillantirishga hissa qo'shishingizni istaymiz.\n\n"
        payment_message += "Odatlarni davom etib ballarni yig'ishda davom etish uchun iltimos to'lov chekini yuboring \n\n"
        payment_message += "💳 To‘lov rekvizitlari:\n"
        payment_message += "Karta raqami: <code>9860 1766 0132 6737</code>\n"
        payment_message += "Egasi: N. Murodjonov\n\n"
        payment_message += f"📌 Oylik obuna narxi: {MONTHLY_PAYMENT} UZS ({MONTHLY_PAYMENT_INWORD})\n\n"
        payment_message += "✅ To‘lovni amalga oshirgach, chekni quyidagi tugma orqali bizga yuboring.\n\n"
        payment_message += "Yo'lda ko'rishguncha, Lider!"

        await call.message.answer(
            text=_(payment_message),
            reply_markup=send_receipt_button
        )
        return

    actions = Action.objects.filter(
        habit=habit,
        created_at__date=action.created_at.date(),
        status="done"
    )

    if actions.count() == 0:
        habit.set_completed_days()
        habit.user.update_ball(True, BALL_FOR_PLUS)
        action.set_points_scored()

    action.set_status("done")
    habit.set_notification_must_be_sent_false()

    if elapsed_days == habit.duration:
        text = f"🎉 Ajoyib natija, {habit.user.full_name}! 🎉\n\n"
        text += f"Siz {habit.name} odatini shakllantirish yo‘lida {habit.duration} kunlik sayohatni muvaffaqiyatli yakunladingiz! 🏆👏 Bu katta yutuq – o‘zingiz bilan faxrlansangiz arziydi!\n\n"
        text += "✅ Izchillik – muvaffaqiyatning kaliti!\n"
        text += "✅ Matonat – yangi odatlaringizni saqlab qolish uchun kuch beradi!\n"
        text += "✅ G‘alaba – siz bunga erishdingiz!\n\n"
        text += "Siz ajoyib natija ko‘rsatdingiz va bu faqat boshlanishi! 🚀 Endi shu odatni hayotingizning bir qismiga aylantirib, yanada rivojlanishingizni davom ettiring!\n"
        text += "🔹 Yangi maqsad qo‘yishga tayyormisiz? Biz sizni qo‘llab-quvvatlashda davom etamiz! 💪🔥"
        await call.message.answer(_(text))
        return
    message_list_for_competed = [_("Barakalla Lider!"), _(
        "Shunday davom eting 🔥"), _("Olovsiz!"), _("Millat Umidi 🏆")]
    random_text = choice(message_list_for_competed)
    text = random_text + "\n\n" + \
        _(f"✅ Umumiy ballingiz: 🎯 {habit.user.ball} ball 🌟")
    await call.message.answer(text)
    try:
        await call.message.delete()
    except Exception as e:
        print(e)


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: "no" in c.data)
async def habit_notification_handler(call: types.CallbackQuery, state: FSMContext):
    if ":" not in call.data:
        return
    action_id = call.data.split(":")[1]
    action = Action.objects.filter(id=action_id).first()
    if not action:
        return

    habit = action.habit

    last_hour = habit.hours.all().last()
    current_time = timezone.localtime()
    elapsed_days = (current_time.date() - habit.created_at.date()).days

    payment_status = get_payment_status(habit.user, current_time)
    if not payment_status and elapsed_days > FREE_TRIAL_PERIOD:
        payment_message = "📢 Xurmatli Lider kitobxon 5-kun davomida uchyapsiz!\n\n"
        payment_message += "Tabriklaymiz siz yondiryapsiz, shu tempda davom eting🦾\n\n"
        payment_message += "Davom etish uchun ba'zi texnik va tashkiliy harajatlar bor shunga biz buni qoplash uchun ham kichik summa bo'lsa ham belgilashga harakat qildik 😌\n\n"
        payment_message += "Xurmatli Lider, kitobxonlarni safini kengaytirishga hissa qo'shishga va super/xayrli odatlarini shakillantirishga hissa qo'shishingizni istaymiz.\n\n"
        payment_message += "Odatlarni davom etib ballarni yig'ishda davom etish uchun iltimos to'lov chekini yuboring \n\n"
        payment_message += "💳 To‘lov rekvizitlari:\n"
        payment_message += "Karta raqami: <code>9860 1766 0132 6737</code>\n"
        payment_message += "Egasi: N. Murodjonov\n\n"
        payment_message += f"📌 Oylik obuna narxi: {MONTHLY_PAYMENT} UZS ({MONTHLY_PAYMENT_INWORD})\n\n"
        payment_message += "✅ To‘lovni amalga oshirgach, chekni quyidagi tugma orqali bizga yuboring.\n\n"
        payment_message += "Yo'lda ko'rishguncha, Lider!"

        await call.message.answer(
            text=_(payment_message),
            reply_markup=send_receipt_button
        )
        return

    last_action = Action.objects.filter(
        habit=habit,
        hour=last_hour,
        created_at__date=action.created_at.date(),
        status="waiting"
    ).order_by("-created_at").first()

    if last_action == action:
        habit.user.update_ball(False, BALL_FOR_MINUS)
        action.set_points_scored()

    action.set_status("not_done")

    message_list_for_incomplete = ["Unaqamasda endi, man sizni boshqalarga maqtay deb turgandim😢",
                                   "Bugun o'zingizga o'xshamayapsiz😢", "Nega bunday bo'ldi 😢"]
    random_text = choice(message_list_for_incomplete)
    text = random_text + "\n\n" + \
        _(f"✅ Umumiy ballingiz: 🎯 {habit.user.ball} ball 🌟")

    await call.message.answer(text)
    await call.message.delete()
