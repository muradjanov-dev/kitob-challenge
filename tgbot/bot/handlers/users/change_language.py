from aiogram import types
from aiogram.dispatcher import FSMContext

from tgbot.bot.keyboards.reply import main_markup
from tgbot.bot.loader import dp
from tgbot.bot.loader import gettext as _
from tgbot.bot.utils import get_user
from tgbot.bot.keyboards.inline import languages_markup
from tgbot.bot.states.main import ChangeLanguageState
from aiogram.dispatcher.filters.builtin import ChatTypeFilter
from aiogram.types import ChatType



@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="🌐 Tilni o'zgartirish", state="*")
@dp.message_handler(ChatTypeFilter(ChatType.PRIVATE), text="🌐 Изменить язык", state="*")
async def change_language_handler(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    
    if user.language == "uz":
        content = "Tilni o'zgartirin"
    elif user.language == "ru":
        content = "Измените язык"
    else:
        content = "Tilni o'zgartirin"

    
    await message.answer(text=content, reply_markup=languages_markup)
    await ChangeLanguageState.language_change.set()
    
    
@dp.message_handler(state=ChangeLanguageState.language_change)
async def back_to_main_menu_handler(message: types.Message, state: FSMContext):
    changed_language = message.text
    user = get_user(message.from_user.id)
    if changed_language == "O'zbekcha":
        user.language = "uz"
    elif changed_language == "Русский":
        user.language = "ru"
    else:
        await message.answer(_("Noma'lum til. Iltimos, tilni to'g'ri tanlang."))
        return
    
    user.save() 
    if user.language == "uz":
        content = f'Til {changed_language} ga oʻzgartirildi'
    elif user.language == "ru":
        content = f'Язык изменен на {changed_language}'
    else:
        content = _("Bosh menyu")
        
    await message.answer(text=content, reply_markup=main_markup(language=user.language))   
    await state.finish()
