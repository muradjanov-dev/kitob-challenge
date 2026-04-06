from aiogram import types
from aiogram.dispatcher import FSMContext
from asgiref.sync import sync_to_async
from aiogram.dispatcher.filters.builtin import CommandStart, ChatTypeFilter
from aiogram.types import ChatType


from tgbot.models import TelegramProfile, Region, UserReferal
from tgbot.bot.keyboards.reply import (
    phone_keyboard,
    back_keyboard,
    main_markup,
    gender_keyboard,
    region_markup
)
from tgbot.bot.loader import dp, bot
from tgbot.bot.loader import gettext as _
from tgbot.bot.states.main import AdmissionState
from tgbot.bot.utils import get_user
from tgbot.bot.consts import ADMIN_GROUP_ID, TECHNICAL_SUPPORT_THREAD_ID
from tgbot.services.referral import ReferralService


@dp.message_handler(CommandStart(), ChatTypeFilter(ChatType.PRIVATE), state="*")
async def do_start(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    args = message.get_args()

    if not user.is_registered:
        if args:
            await state.update_data(referral_code=args)

        await message.answer(_("Iltimos, familiyangizni, ismingizni va otangizning ismini kiriting ⬇️"),
                             reply_markup=back_keyboard)
        await AdmissionState.full_name.set()
    else:
        await message.answer(
            text=_("Bosh menyu."),
            reply_markup=main_markup()
        )
        await state.finish()


@dp.message_handler(state=AdmissionState.full_name)
async def full_name(message: types.Message, state: FSMContext):
    full_name_text = message.text.strip()
    is_correct = full_name_text.split(' ')

    if len(full_name_text) <= 60:
        await state.update_data({"full_name": full_name_text})

        await message.answer(
            _('Hududingizni tanlang.'),
            reply_markup=region_markup()
        )
        await AdmissionState.region.set()

    elif len(full_name_text) > 60:
        await message.answer(_("Ismingiz 60belgidan uzun bo'lmasligi kerak."))


@dp.message_handler(state=AdmissionState.region)
async def region_handler(message: types.Message, state: FSMContext):
    region = message.text

    await state.update_data(region=region)
    await message.answer(
        _('Jinsizni tanlang.'),
        reply_markup=gender_keyboard
    )
    await AdmissionState.gender.set()


@dp.message_handler(state=AdmissionState.gender)
async def gender_handler(message: types.Message, state: FSMContext):
    gender_dict = {
        '🤵/🧔': 'male',
        '👩‍💼/🧕': 'female',
    }
    gender = gender_dict.get(message.text)

    await state.update_data({'gender': gender})
    await message.answer(
        _('Telefon raqamingizni quyidagi tugmani bosgan holda yuboring.'),
        reply_markup=phone_keyboard
    )
    await AdmissionState.phone_number.set()


@dp.message_handler(state=AdmissionState.phone_number, content_types=types.ContentTypes.TEXT)
@dp.message_handler(state=AdmissionState.phone_number, content_types=types.ContentTypes.CONTACT)
async def contact_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    tg_user = get_user(message.from_user.id)
    language = tg_user.language

    if message.content_type in types.ContentTypes.TEXT:
        await message.answer(_("Pastdagi tugma orqali raqamingizni yuboring"))
    elif (
        message.content_type in types.ContentTypes.CONTACT and
        message.contact.phone_number and
        message.from_user.id == message.contact.user_id
    ):
        phone_number = message.contact.phone_number
        region = Region.objects.filter(name=data.get("region")).first()

        # saving data
        user, created = TelegramProfile.objects.update_or_create(
            telegram_id=message.from_user.id,
            defaults={
                'full_name': data.get("full_name"),
                'gender': data.get("gender"),
                'region': region,
                'phone_number': phone_number,
                'is_registered': True
            }
        )
        if not created:
            user.full_name = data.get("full_name")
            user.phone_number = phone_number
            user.is_registered = True
            user.save()

        # Handle Referral (Post-Registration)
        referral_code = data.get("referral_code")
        if referral_code:
            await ReferralService.process_referral(user, referral_code)

        await message.answer(_("Ro'yxatdan o'tdingiz, ma'lumotlaringiz saqlandi."), reply_markup=main_markup(language=language))
        await state.reset_data()
        await state.finish()

    else:
        await message.answer(_('📲 Iltimos Raqamni Yuborish Tugmasini Bosing'))
