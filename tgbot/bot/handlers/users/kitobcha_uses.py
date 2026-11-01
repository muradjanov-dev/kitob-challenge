"""🪙 Kitobcha bilan nima qilish mumkin? -- the bot side of
services/kitobcha_uses: give Kitobcha (members), mentor a newcomer, Kitobcha
-> Kitob hamyonchasi, report post frames, the honour wall, and the
streak-gift buttons that tasks.ask_streak_gifts sends.
"""
from html import escape

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, KeyboardButtonRequestUser, ReplyKeyboardMarkup,
)
from asgiref.sync import sync_to_async

from tgbot.bot.keyboards.reply import main_markup
from tgbot.bot.loader import bot, dp
from tgbot.bot.states.main import KitobchaStates
from tgbot.bot.utils import aget_user
from tgbot.models import TelegramProfile
from tgbot.services import kitobcha_uses as ku
from tgbot.services import wallet

CANCEL = "❌ Bekor qilish"
_REQ_GIVE, _REQ_MENTOR = 71, 72


def _n(v) -> str:
    return f"{int(v or 0):,}".replace(",", " ")


def _menu_text(user) -> str:
    return (
        "🪙 <b>Kitobcha bilan nima qilish mumkin?</b>\n\n"
        f"Balansingiz: <b>{_n(user.ball)}</b> Kitobcha\n\n"
        f"🎁 <b>Sovg'a qilish</b> — istalgan kitobxonga Kitobcha o'tkazing (imtiyozlilar uchun, kuniga "
        f"{_n(ku.TRANSFER_DAILY_CAP)} tagacha).\n\n"
        f"🎓 <b>Ustoz bo'lish</b> — yangi kitobxonning hisobot kunlarini to'lang: 1 kun = "
        f"{_n(ku.MENTOR_DAY_PRICE)} Kitobcha. Hisobotlaringizda «🎓» nishoni paydo bo'ladi.\n\n"
        f"🔄 <b>Kitob hamyonchasiga</b> — 1 Kitobcha = 1 so'm, oyiga {_n(ku.POT_MONTHLY_CAP)} tagacha. "
        f"Hamyoncha {_n(wallet.CASHBACK_PAYOUT)} so'mga yetganda asosiy hamyonga o'tadi.\n\n"
        f"🖼 <b>Hisobot ramkasi</b> — guruhdagi hisobotingizni bezang: {ku.FRAME_DAYS} kun = "
        f"{_n(ku.FRAME_PRICE)} Kitobcha.\n\n"
        f"🏛 <b>Hurmatli kitobxonlar devori</b> — ismingiz devorda abadiy qoladi: {_n(ku.WALL_PRICE)} Kitobcha.\n\n"
        "🛡 <b>Do'stni qutqarish</b> — kimningdir streaki kuyish arafasida bo'lsa, bot sizdan yordam "
        "so'rashi mumkin. Bir necha bosish bilan streak muzlatish sovg'a qilasiz."
    )


def _menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🎁 Sovg'a qilish", callback_data="kuse:give"),
           InlineKeyboardButton("🎓 Ustoz bo'lish", callback_data="kuse:mentor"))
    kb.add(InlineKeyboardButton("🔄 Hamyonchaga", callback_data="kuse:pot"),
           InlineKeyboardButton("🖼 Ramka", callback_data="kuse:frames"))
    kb.add(InlineKeyboardButton("🏛 Hurmatli kitobxonlar devori", callback_data="kuse:wall"))
    kb.add(InlineKeyboardButton("⬅️ Hamyon", callback_data="wallet:open"))
    return kb


def _pick_kb(request_id: int) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("👤 Kitobxonni tanlash",
                          request_user=KeyboardButtonRequestUser(request_id=request_id, user_is_bot=False)))
    kb.add(KeyboardButton(CANCEL))
    return kb


def _no_kb(text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup().add(InlineKeyboardButton(text, callback_data="kuse:cancel"))


@sync_to_async
def _resolve(message: types.Message):
    """The reader the message points at: a shared contact, @username or ID."""
    if getattr(message, "user_shared", None):
        return TelegramProfile.objects.filter(telegram_id=message.user_shared.user_id, is_registered=True).first()
    text = (message.text or "").strip()
    if text.startswith("@") and len(text) > 1:
        return TelegramProfile.objects.filter(username__iexact=text[1:], is_registered=True).first()
    if text.isdigit():
        return TelegramProfile.objects.filter(telegram_id=int(text), is_registered=True).first()
    return None


@sync_to_async
def _profile(pid):
    return TelegramProfile.objects.filter(id=pid).first()


async def _dm(user, text: str) -> None:
    try:
        await bot.send_message(user.telegram_id, text, parse_mode="HTML")
    except Exception as e:
        print(f"kitobcha_uses DM {user.telegram_id}: {e}")


# ── menu ────────────────────────────────────────────────────────────────────

@dp.message_handler(commands=["kitobcha"], state="*")
async def kitobcha_command(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    if not user:
        return
    await state.finish()
    await message.answer(_menu_text(user), parse_mode="HTML", reply_markup=_menu_kb())


@dp.callback_query_handler(lambda c: c.data == "kuse:menu", state="*")
async def kuse_menu(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    await call.answer()
    if user:
        await state.finish()
        await call.message.answer(_menu_text(user), parse_mode="HTML", reply_markup=_menu_kb())


@dp.callback_query_handler(lambda c: c.data == "kuse:cancel", state="*")
async def kuse_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.finish()
    try:
        await call.message.edit_text("👌 Bekor qilindi.")
    except Exception:
        pass


@dp.message_handler(lambda m: m.text == CANCEL, state=[KitobchaStates.give_who, KitobchaStates.give_amount,
                                                      KitobchaStates.mentor_who])
async def kuse_cancel_text(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    await state.finish()
    await message.answer("👌 Bekor qilindi.", reply_markup=main_markup(language=(user.language if user else "uz")))


# ── give ────────────────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "kuse:give", state="*")
async def kuse_give(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not user or not await sync_to_async(wallet.is_member)(user):
        await call.answer(f"🎁 Kitobcha sovg'a qilish imtiyozli kitobxonlar uchun: hamyonni bir martada "
                          f"{_n(wallet.MEMBER_MIN)} so'm va undan ko'p to'ldiring.", show_alert=True)
        return
    await call.answer()
    await KitobchaStates.give_who.set()
    await call.message.answer("🎁 Kimga sovg'a qilasiz? Pastdagi tugma bilan kitobxonni tanlang "
                              "yoki @username / ID yozing.", reply_markup=_pick_kb(_REQ_GIVE))


@dp.message_handler(state=KitobchaStates.give_who, content_types=types.ContentType.ANY)
async def kuse_give_who(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    r = await _resolve(message)
    if not r:
        await message.answer("Bu kitobxon botda ro'yxatdan o'tmagan ekan. Boshqasini tanlang yoki «❌ Bekor qilish».")
        return
    if r.id == user.id:
        await message.answer("O'zingizga sovg'a qilib bo'lmaydi 🙂 Boshqa kitobxonni tanlang.")
        return
    await state.update_data(rid=r.id)
    await KitobchaStates.give_amount.set()
    await message.answer(f"Nechta Kitobcha sovg'a qilasiz, <b>{escape(ku._first_name(r))}</b>ga? "
                         f"(kamida {_n(ku.TRANSFER_MIN)}, balansingiz: {_n(user.ball)})",
                         parse_mode="HTML", reply_markup=main_markup(language=user.language or "uz"))


@dp.message_handler(state=KitobchaStates.give_amount, content_types=types.ContentType.TEXT)
async def kuse_give_amount(message: types.Message, state: FSMContext):
    text = (message.text or "").replace(" ", "")
    if not text.isdigit() or int(text) < ku.TRANSFER_MIN:
        await message.answer(f"Raqam yozing, kamida {_n(ku.TRANSFER_MIN)}.")
        return
    data = await state.get_data()
    await state.finish()
    r = await _profile(data.get("rid"))
    amount = int(text)
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Ha, sovg'a qilaman", callback_data=f"kuse:giveok:{r.id}:{amount}"),
        InlineKeyboardButton("❌ Yo'q", callback_data="kuse:cancel"))
    await message.answer(f"🎁 <b>{escape(r.full_name or 'Kitobxon')}</b>ga <b>{_n(amount)} Kitobcha</b> "
                         "sovg'a qilasizmi?", parse_mode="HTML", reply_markup=kb)


_ERR = {
    "not_member": "Bu imkoniyat imtiyozli kitobxonlar uchun.",
    "self": "O'zingizga bo'lmaydi 🙂",
    "too_small": f"Kamida {_n(ku.TRANSFER_MIN)} Kitobcha.",
    "insufficient": "Kitobchangiz yetarli emas.",
    "not_newcomer": f"Ustoz faqat so'nggi {ku.MENTOR_NEWCOMER_DAYS} kunda qo'shilgan kitobxonga yordam bera oladi.",
    "already": "Ismingiz devorda allaqachon bor 🏛",
    "already_saved": "Rahmat! Uni allaqachon boshqa kitobxon qutqardi 💛",
}


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("kuse:giveok:"), state="*")
async def kuse_give_ok(call: types.CallbackQuery, state: FSMContext):
    _, _, rid, amount = call.data.split(":")
    user = await aget_user(call.from_user.id)
    r = await _profile(int(rid))
    res = await sync_to_async(ku.transfer)(user, r, int(amount))
    if not res["ok"]:
        msg = (f"Bugungi chegara: yana {_n(res.get('left'))} Kitobcha yuborish mumkin."
               if res["error"] == "daily_cap" else _ERR.get(res["error"], "Bajarilmadi."))
        await call.answer(msg, show_alert=True)
        return
    await call.answer("✅")
    try:
        await call.message.edit_text(f"✅ <b>{_n(res['amount'])} Kitobcha</b> sovg'a qilindi! "
                                     f"Qoldiq: {_n(res['balance'])}", parse_mode="HTML")
    except Exception:
        pass
    await _dm(r, f"🎁 <b>{escape(ku._first_name(user))}</b> sizga <b>{_n(res['amount'])} Kitobcha</b> "
                 "sovg'a qildi! 💛")


# ── mentor ──────────────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "kuse:mentor", state="*")
async def kuse_mentor(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await KitobchaStates.mentor_who.set()
    await call.message.answer(
        f"🎓 Kimga ustoz bo'lasiz? So'nggi {ku.MENTOR_NEWCOMER_DAYS} kunda qo'shilgan kitobxonni tanlang "
        "(pastdagi tugma) yoki @username / ID yozing.", reply_markup=_pick_kb(_REQ_MENTOR))


@dp.message_handler(state=KitobchaStates.mentor_who, content_types=types.ContentType.ANY)
async def kuse_mentor_who(message: types.Message, state: FSMContext):
    user = await aget_user(message.from_user.id)
    r = await _resolve(message)
    if not r or r.id == user.id:
        await message.answer("Bu kitobxon topilmadi. Boshqasini tanlang yoki «❌ Bekor qilish».")
        return
    if not ku.is_newcomer_for_mentor(r):
        await message.answer(_ERR["not_newcomer"])
        return
    await state.finish()
    kb = InlineKeyboardMarkup(row_width=3).add(*[
        InlineKeyboardButton(f"🎓 {d} kun · {_n(d * ku.MENTOR_DAY_PRICE)} 🪙", callback_data=f"kuse:mdays:{r.id}:{d}")
        for d in ku.MENTOR_DAY_OPTIONS])
    kb.add(InlineKeyboardButton("❌ Yo'q", callback_data="kuse:cancel"))
    await message.answer(f"🎓 <b>{escape(r.full_name or 'Kitobxon')}</b>ga necha kunlik hisobot sovg'a qilasiz? "
                         f"Har kun uchun uning hamyoniga {_n(wallet.DAY_FEE)} so'm tushadi.",
                         parse_mode="HTML", reply_markup=kb)
    await message.answer("👇", reply_markup=main_markup(language=user.language or "uz"))


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("kuse:mdays:"), state="*")
async def kuse_mentor_days(call: types.CallbackQuery, state: FSMContext):
    _, _, rid, days = call.data.split(":")
    user = await aget_user(call.from_user.id)
    r = await _profile(int(rid))
    res = await sync_to_async(ku.mentor)(user, r, int(days))
    if not res["ok"]:
        await call.answer(_ERR.get(res["error"], "Bajarilmadi."), show_alert=True)
        return
    await call.answer("✅")
    try:
        await call.message.edit_text(f"🎓 Rahmat, ustoz! <b>{escape(ku._first_name(r))}</b>ga <b>{res['days']} kunlik</b> "
                                     f"hisobot sovg'a qildingiz. Qoldiq: {_n(res['balance'])} Kitobcha", parse_mode="HTML")
    except Exception:
        pass
    await _dm(r, f"🎓 <b>{escape(ku._first_name(user))}</b> ustozingiz bo'lib, sizga <b>{res['days']} kunlik</b> "
                 f"hisobot sovg'a qildi! Hamyoningizga {_n(res['days'] * wallet.DAY_FEE)} so'm tushdi 👛\n\n"
                 "Birga o'qiymiz! 📚")


# ── Kitobcha -> Kitob hamyonchasi ───────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "kuse:pot", state="*")
async def kuse_pot(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    await call.answer()
    left = await sync_to_async(ku.pot_left_this_month)(user)
    can = min(int(user.ball or 0), left) // ku.POT_STEP * ku.POT_STEP
    text = (f"🔄 <b>Kitobcha → Kitob hamyonchasi</b>\n\n1 Kitobcha = 1 so'm. Bu oy yana <b>{_n(left)}</b> tagacha "
            f"o'tkazish mumkin.\nHamyonchada: <b>{_n(user.cashback_balance)} / {_n(wallet.CASHBACK_PAYOUT)} so'm</b>")
    if can < ku.POT_STEP:
        await call.message.answer(text + f"\n\nHozir o'tkazib bo'lmaydi: kamida {_n(ku.POT_STEP)} Kitobcha kerak.",
                                  parse_mode="HTML")
        return
    amounts = sorted({a for a in (1000, 5000, 10000, 25000, 50000) if a <= can} | {can})
    kb = InlineKeyboardMarkup(row_width=3).add(*[
        InlineKeyboardButton(f"{_n(a)}", callback_data=f"kuse:potgo:{a}") for a in amounts])
    await call.message.answer(text + "\n\nQanchasini o'tkazamiz?", parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("kuse:potgo:"), state="*")
async def kuse_pot_go(call: types.CallbackQuery, state: FSMContext):
    amount = int(call.data.split(":")[-1])
    await call.answer()
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Ha", callback_data=f"kuse:potok:{amount}"),
        InlineKeyboardButton("❌ Yo'q", callback_data="kuse:cancel"))
    await call.message.edit_text(f"🔄 <b>{_n(amount)} Kitobcha</b> → <b>{_n(amount)} so'm</b> Kitob hamyonchasiga. "
                                 "Tasdiqlaysizmi?", parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("kuse:potok:"), state="*")
async def kuse_pot_ok(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    res = await sync_to_async(ku.to_pot)(user, int(call.data.split(":")[-1]))
    if not res["ok"]:
        msg = (f"Bu oy yana {_n(res.get('left'))} tagacha mumkin." if res["error"] == "monthly_cap"
               else _ERR.get(res["error"], "Bajarilmadi."))
        await call.answer(msg, show_alert=True)
        return
    await call.answer("✅")
    tail = (f"🎉 Hamyoncha {_n(wallet.CASHBACK_PAYOUT)} so'mga yetdi — <b>{_n(res['paid_out'])} so'm</b> asosiy "
            "hamyonga o'tkazildi!" if res["paid_out"]
            else f"Hamyonchada: <b>{_n(res['pot'])} / {_n(wallet.CASHBACK_PAYOUT)} so'm</b>")
    await call.message.edit_text(f"✅ {_n(res['amount'])} Kitobcha hamyonchaga o'tdi.\n{tail}", parse_mode="HTML")


# ── frames ──────────────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "kuse:frames", state="*")
async def kuse_frames(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    await call.answer()
    now = ku.active_frame(user)
    lines = [f"🖼 <b>Hisobot ramkasi</b> — guruhdagi hisobotingiz tepasida va pastida chiroyli chiziq. "
             f"{ku.FRAME_DAYS} kun = {_n(ku.FRAME_PRICE)} Kitobcha.\n"]
    if now:
        lines.append(f"Hozir: <b>{ku.FRAMES[now][0]}</b>, {user.report_frame_until:%d.%m} gacha "
                     "(o'shani olsangiz muddat uzayadi).\n")
    for code, (title, top, bottom) in ku.FRAMES.items():
        lines.append(f"<b>{title}</b>\n{top}\n<i>…hisobotingiz…</i>\n{bottom}\n")
    kb = InlineKeyboardMarkup(row_width=2).add(*[
        InlineKeyboardButton(title, callback_data=f"kuse:frame:{code}") for code, (title, _, _) in ku.FRAMES.items()])
    await call.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("kuse:frame:"), state="*")
async def kuse_frame_pick(call: types.CallbackQuery, state: FSMContext):
    code = call.data.split(":")[-1]
    if code not in ku.FRAMES:
        await call.answer()
        return
    await call.answer()
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Ha", callback_data=f"kuse:frameok:{code}"),
        InlineKeyboardButton("❌ Yo'q", callback_data="kuse:cancel"))
    await call.message.answer(f"🖼 <b>{ku.FRAMES[code][0]}</b> ramkasi {ku.FRAME_DAYS} kunga — "
                              f"{_n(ku.FRAME_PRICE)} Kitobcha. Tasdiqlaysizmi?", parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("kuse:frameok:"), state="*")
async def kuse_frame_ok(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    res = await sync_to_async(ku.buy_frame)(user, call.data.split(":")[-1])
    if not res["ok"]:
        await call.answer(_ERR.get(res["error"], "Bajarilmadi."), show_alert=True)
        return
    await call.answer("✅")
    await call.message.edit_text(f"✅ Ramka faol: {res['until']:%d.%m} gacha. Keyingi hisobotingiz chiroyli chiqadi ✨",
                                 parse_mode="HTML")


# ── honour wall ─────────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "kuse:wall", state="*")
async def kuse_wall(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    await call.answer()
    rows = await sync_to_async(ku.wall_entries)()
    names = "\n".join(f"{i}. {escape(n or 'Kitobxon')} <i>({d:%d.%m.%Y})</i>" for i, (n, d) in enumerate(rows, 1))
    text = ("🏛 <b>Hurmatli kitobxonlar devori</b>\n\n"
            + (names or "<i>Devor hali bo'sh — birinchi bo'ling!</i>")
            + f"\n\nIsmingizni devorga abadiy yozdirish: <b>{_n(ku.WALL_PRICE)} Kitobcha</b>.")
    kb = None
    if not user.honor_wall_at:
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton(f"✍️ Ismimni yozdirish · {_n(ku.WALL_PRICE)} 🪙",
                                                             callback_data="kuse:walljoin"))
    await call.message.answer(text[:4000], parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "kuse:walljoin", state="*")
async def kuse_wall_join(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Ha", callback_data="kuse:wallok"),
        InlineKeyboardButton("❌ Yo'q", callback_data="kuse:cancel"))
    await call.message.answer(f"🏛 Ismingiz «Hurmatli kitobxonlar devori»ga abadiy yoziladi — "
                              f"{_n(ku.WALL_PRICE)} Kitobcha. Tasdiqlaysizmi?", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "kuse:wallok", state="*")
async def kuse_wall_ok(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    res = await sync_to_async(ku.join_wall)(user)
    if not res["ok"]:
        await call.answer(_ERR.get(res["error"], "Bajarilmadi."), show_alert=True)
        return
    await call.answer("✅")
    await call.message.edit_text("🏛 Tabriklaymiz! Ismingiz «Hurmatli kitobxonlar devori»da 💛")


# ── streak gift (asks from tasks.ask_streak_gifts) ──────────────────────────

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("sgift:"), state="*")
async def streak_gift(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    if parts[1] == "no":
        await call.answer("Mayli 😊")
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    donor = await aget_user(call.from_user.id)
    r = await _profile(int(parts[1]))
    if not donor or not r:
        await call.answer()
        return
    res = await sync_to_async(ku.gift_streak)(donor, r, int(parts[2]))
    if not res["ok"]:
        if res["error"] == "already_saved":
            await call.answer()
            try:
                await call.message.edit_text(_ERR["already_saved"])
            except Exception:
                pass
            return
        await call.answer(_ERR.get(res["error"], "Bajarilmadi."), show_alert=True)
        return
    await call.answer("💛")
    try:
        await call.message.edit_text(f"✅ Rahmat! <b>{escape(ku._first_name(r))}</b>ning streaki saqlanib qoladi 💛\n"
                                     f"Qoldiq: {_n(res['balance'])} Kitobcha", parse_mode="HTML")
    except Exception:
        pass
    await _dm(r, f"🎁 Loyihadagi kitobxon <b>{escape(ku._first_name(donor))}</b> sizga <b>{res['days']} kunlik "
                 "streak muzlatish</b> sovg'a qildi! 🛡 Streakingiz saqlanib qoladi.\n\n"
                 "Imkon bo'lishi bilan hisobotingizni yuboring 📚")
