from aiogram import types
from aiogram.dispatcher import FSMContext

from tgbot.bot.keyboards.reply import main_markup, back_keyboard
from tgbot.bot.loader import dp
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType
from tgbot.bot.states.main import ShareLinkState
from tgbot.bot.loader import gettext as _


@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="🔗 Kanalga o'tish", state="*")
@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="🔗 Перейти на канал", state="*")
async def share_channel_link_handler(message: types.Message, state: FSMContext):
    if message.text == "🔗 Kanalga o'tish":
        await message.answer(
            text="<b>Guruhlarimizga bemalol a'zo bo'ling.</b>\n\nhttps://t.me/kitob_challenge_uz\n\n" \
                "💡 @kitobchallenge_uz - Rasmiy kanal\n" \
                "💡 @muradjanovs_way - Founder (with team)\n" \
                "💡 @kitob_challenge_uz - Ayol/Qizlar guruhi\n" \
                "💡 @kitob_challenge_men - Yigitlar\n" \
                "💡 @kitob_challange_bot - botimiz (shu bot orqali ro‘yxatdan o‘tib hisobotlarni boshlang 📚🚀)\n\n" \
                "@muradjanovs_way",
            reply_markup=back_keyboard,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    elif message.text == "🔗 Перейти на канал":
        await message.answer(
            text="<b>Присоединяйтесь к нашим группам бесплатно.</b>\n\nhttps://t.me/kitob_challenge_uz\n\n" \
                "💡 @kitobchallenge_uz - Официальный канал\n" \
                "💡 @muradjanovs_way - Основатель (с командой)\n" \
                "💡 @kitob_challenge_uz - Группа для девушек\n" \
                "💡 @kitob_challenge_men - Группа для парней\n" \
                "💡 @kitob_challange_bot - Наш бот (через этого бота зарегистрируйтесь и начните отчёты 📚🚀)\n\n" \
                "@muradjanovs_way",
            reply_markup=back_keyboard,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    await ShareLinkState.go_back.set()


@dp.message_handler(state=ShareLinkState.go_back)
async def go_back_handler(message, state: FSMContext):
    await state.finish()
    await message.answer(_("Bosh menyu."), reply_markup=main_markup())

