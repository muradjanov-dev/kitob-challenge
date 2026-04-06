from datetime import datetime
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType

from tgbot.bot.utils import get_user, get_hours_button
from tgbot.bot.states.main import HabitFormation, UpdateHours, DeleteHabitState
from tgbot.bot.loader import dp, bot, gettext as _
from tgbot.bot.keyboards.reply import create_habit_keyboard, main_markup, back_keyboard
from tgbot.bot.keyboards.inline import yes_no_markup
from tgbot.bot.keyboards.inline import make_update_hours
from tgbot.models import Habit, Hour

from tgbot.bot.consts import CHALLENGE_CHANNEL_ID, GAMES_THREAD_ID

@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="🏆 Мои привычки", state="*")
@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="🏆 Mening odatlarim", state="*")
async def habit_message_handler(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    habits = Habit.objects.filter(user=user)
    
    if not habits:
        await message.answer(_("📝Sizda hozircha hech qanday shakllantirmoqchi bo'lgan odatingiz mavjud emas.\n\nQuyidagi tugma yordamida yangi odatni qo'shishingiz mumkin!"), reply_markup=create_habit_keyboard)
        return 
    
    for habit in habits:
        status_emoji = "🏆 Tugatilgan" if habit.status == "completed" else "🟢 Jarayonda"
        habit_message = f"\n\nNomi: {habit.name} – 🎯\n\n"
        habit_message += f"Davomiyligi: {habit.duration} – 📈\n\n"
        habit_message += f"""Kunlik ogohlantirishlar vaqti: {", ".join(str(hour) for hour in habit.hours.all())} – 😊\n\n"""
        habit_message += f"Bajarilgan kunlar: {habit.completed_days}/{habit.duration} – ✅\n\n"
        habit_message += f"""Odatni yaratgan vaqti: {habit.created_at.strftime("%d/%m/%Y")} – 📆\n\n"""
        habit_message += f"Odat holati: {status_emoji}"
        await message.answer(habit_message, reply_markup=await make_update_hours(habit_id=habit.id))
    
    await message.answer(f"✅ Umumiy ballingiz: 🎯 {user.ball} ball 🌟", reply_markup=create_habit_keyboard)


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text=_("💡 Yangi odat qo'shish"), state="*")
async def habit_message_handler(message: types.Message, state: FSMContext):
    await message.answer(_("📥Yaxshi, demak yangi odat shakllantiramiz."))
    await message.answer(_("⚡️Shakllantirmoqchi bo'lgan odatingizni kiriting:\n\nNamuna: Erta turish"), reply_markup=back_keyboard)
    await HabitFormation.name.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), content_types=types.ContentType.TEXT, state=HabitFormation.name)
async def habit_message_handler(message: types.Message, state: FSMContext):
    name = message.text
    if len(name) > 255:
        await message.answer(_("🪚Iltimos odatingiz nomini qisqartiring!"))
        return
    await state.update_data(name=name)
    await message.answer(_("📅 Bu odatingiz bo‘yicha qancha kun davomida eslatma yuboray?"))
    await HabitFormation.duration.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=HabitFormation.name)
async def habit_message_handler(message: types.Message, state: FSMContext):
    await message.answer(_("📝 Iltimos, shakllantirmoqchi bo‘lgan odatingizni matn ko‘rinishida yuboring."))
    await HabitFormation.name.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), content_types=types.ContentType.TEXT, state=HabitFormation.duration)
async def habit_message_handler(message: types.Message, state: FSMContext):
    duration = message.text
    if not (duration.isdigit() and any(char != '0' for char in duration)):
        await message.answer(_("📅 Kiritilgan qiymat kunga mos kelmaydi. Iltimos, qayta yuboring.!"))
        return
    if int(duration) > 500:
        await message.answer(_("⚠️ Uzr, men sizni 500 kundan oshiq ogohlantira olmayman! Iltimos, mosroq qiymat kiriting. ⏳"))
        return
    await state.update_data(duration=duration)
    hours_button = await get_hours_button()
    await message.answer(
        text=_("⏰ Bu odatingiz bo‘yicha kunlik eslatma yuborishim kerak bo'lgan vaqtlarni quyidan tanlang:"),
        reply_markup=hours_button
    )
    await HabitFormation.reminders_per_day.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=HabitFormation.duration)
async def habit_message_handler(message: types.Message, state: FSMContext):
    await message.answer(_("📅 Iltimos, eslatma yuborishim kerak bo'lgan kunlar sonini matn ko'rinishida menga yuboring."))
    await HabitFormation.duration.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), content_types=types.ContentType.TEXT, state=HabitFormation.reminders_per_day)
async def habit_message_handler(message: types.Message, state: FSMContext):
    text = message.text
    if text == _("📝 Davom etish"):
        user = get_user(message.from_user.id)
        data = await state.get_data()
        name = data.get("name")
        duration = data.get("duration")
        hours = data.get("hours")
        try:
            is_error = False
            habit = Habit.objects.create(
                name=name,
                duration=duration,
                user=user
            )
            if hours:
                hour_objects = Hour.objects.filter(time__in=hours)
                habit.hours.set(hour_objects)
        except:
            is_error = True

        if is_error:
            await message.answer(_("⚠️ Odatni yaratish muvaffaqiyatsiz tugadi. Iltimos, qaytadan urinib ko‘ring! 🔄"), reply_markup=create_habit_keyboard)
            await state.finish()
            return

        await message.answer(_("✅ Ajoyib! Yangi odat muvaffaqiyatli qo‘shildi! 🚀"), reply_markup=main_markup())
        await state.finish()
        try:
            await bot.send_message(
                chat_id=CHALLENGE_CHANNEL_ID,
                message_thread_id=GAMES_THREAD_ID,
                text=_(f"Do'stingiz {user.full_name} yangi odat shakllantirishni boshladi, siz-chi?")
            )
        except Exception as e:
            print(f"{CHALLENGE_CHANNEL_ID} guruhga xabar yuborishda xatolik: {e}") 
        return

    hours_button = await get_hours_button()
    try:
        hour_datetime_object = datetime.strptime(text, "%H:%M").time()
    except:
        await message.answer(_("⬇️Iltimos quyidagi vaqtlardan tanglang:"), reply_markup=hours_button)
        return

    hour_objects = Hour.objects.filter(time=hour_datetime_object)
    if hour_objects.count() == 0:
        await message.answer(_("⬇️Iltimos quyidagi vaqtlardan tanglang:"), reply_markup=hours_button)
        return

    data = await state.get_data()
    hours = data.get("hours")
    if hours:
        hours.append(text)
    else:
        hours = [text]
    await state.update_data(hours=hours)

    await message.answer(
        text=_("⏰ Yana qachon eslataylik tanglang:"),
        reply_markup=hours_button
    )
    await HabitFormation.reminders_per_day.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), state=HabitFormation.reminders_per_day)
async def habit_message_handler(message: types.Message, state: FSMContext):
    hours_button = await get_hours_button()
    await message.answer(
        text=_(
            "⏰ Bu odatingiz bo‘yicha kunlik eslatma yuborish vaqtlarini quyidan tanglang:"
        ),
        reply_markup=hours_button
    )
    await HabitFormation.reminders_per_day.set()


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: "update_hours" in c.data)
async def habit_notification_handler(call: types.CallbackQuery, state: FSMContext):
    habit_id = call.data.split(":")[1]
    habit = Habit.objects.filter(id=habit_id).first()
    if not habit:
        return
    
    habit_message = _(f"\n\nNomi: {habit.name} – 🎯\n")
    habit_message += _(f"""Kunlik ogohlantirishlar vaqti: {", ".join(str(hour) for hour in habit.hours.all())} – 😊\n\n""")
    habit_message += _("⏰ Quyidan o'zgartirmoqchi bo'lgan vaqtlarni tanglang:")

    hours_button = await get_hours_button()
    await call.message.answer(
        text=habit_message,
        reply_markup=hours_button
    )
    await state.update_data(habit_id=habit_id)
    await UpdateHours.update_date.set()


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), content_types=types.ContentType.TEXT, state=UpdateHours.update_date)
async def habit_message_handler(message: types.Message, state: FSMContext):
    text = message.text
    if text == _("📝 Davom etish"):
        user = get_user(message.from_user.id)
        data = await state.get_data()
        habit_id = data.get("habit_id")
        hours = data.get("hours")
        try:
            is_error = False
            habit = Habit.objects.filter(id=habit_id).first()
            habit.hours.clear()
            if hours:
                hour_objects = Hour.objects.filter(time__in=hours)
                habit.hours.set(hour_objects)
        except:
            is_error = True

        if is_error:
            await message.answer(_("⚠️ Eslatma yuborish vaqtlarini o'zgartirishda xatolik bo'ldi. Iltimos, qaytadan urinib ko‘ring! 🔄"), reply_markup=create_habit_keyboard)
            await state.finish()
            return

        await message.answer(_("✅ Ajoyib! Eslatma vaqtlari o'zgartirildi 🚀"), reply_markup=main_markup(language=user.language))
        await state.finish()
        return 
    
    hours_button = await get_hours_button()
    try:
        hour_datetime_object = datetime.strptime(text, "%H:%M").time()
    except:
        await message.answer(_("⬇️Iltimos quyidagi vaqtlardan tanglang:"), reply_markup=hours_button)
        return

    hour_objects = Hour.objects.filter(time=hour_datetime_object)
    if hour_objects.count() == 0:
        await message.answer(_("⬇️Iltimos quyidagi vaqtlardan tanglang:"), reply_markup=hours_button)
        return

    data = await state.get_data()
    hours = data.get("hours")
    if hours:
        hours.append(text)
    else:
        hours = [text]
    await state.update_data(hours=hours)

    await message.answer(
        text=_("⏰ Yana qachon eslataylik, tanglang:"),
        reply_markup=hours_button
    )
    await UpdateHours.update_date.set()


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: "delete_habit" in c.data)
async def habit_notification_handler(call: types.CallbackQuery, state: FSMContext):
    habit_id = call.data.split(":")[1]
    habit = Habit.objects.filter(id=habit_id).first()
    if not habit:
        return
    
    habit_message = _(f"\n\nNomi: {habit.name} – 🎯\n")
    habit_message += _(f"""Kunlik ogohlantirishlar vaqti: {", ".join(str(hour) for hour in habit.hours.all())} – 😊\n\n""")
    habit_message += _("Bu odatni o'chirishni tasdiqlaysizmi?")

    await call.message.answer(
        text=habit_message,
        reply_markup=yes_no_markup
    )
    await state.update_data(habit_id_for_delete=habit_id)
    await DeleteHabitState.confirmation.set()

@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: "yes" in c.data, state=DeleteHabitState.confirmation)
async def habit_notification_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    habit_id = data.get("habit_id_for_delete")
    habit = Habit.objects.filter(id=habit_id).first()
    if not habit:
        await state.finish()
        return
    
    habit.delete()
    await call.message.answer(_("✅ Odat muvaffaqiyatli o'chirildi!"), reply_markup=main_markup())
    await state.finish()
    await call.message.delete()
    return


@dp.callback_query_handler(ChatTypeFilter(ChatType.PRIVATE), lambda c: "no" in c.data, state=DeleteHabitState.confirmation)
async def habit_notification_handler(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer(_("❌ Odat o'chirishni bekor qildingiz!"), reply_markup=main_markup())
    await state.finish()
    await call.message.delete()
    return