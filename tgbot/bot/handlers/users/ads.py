"""Reklama auksioni g'olibining havolasi: yuborish, moderatsiya, efirga chiqish.

Oqim:
    auksion yakunlandi  -> AdCampaign(status=awaiting), g'olibga xabar
    g'olib havola+matn  -> status=review, adminlarga tugmali xabar
    admin tasdiqladi    -> approve() oynani ochadi va reklama tarqatiladi
    admin rad etdi      -> status=rejected, g'olib qayta yuborishi mumkin

Havola HECH QACHON moderatsiyasiz chiqmaydi: efirga chiqarishning yagona yo'li
admin tugmasi (`ad:ok:<id>`), u esa AdCampaign.approve() ni chaqiradi -- faqat
o'sha metod starts_at/ends_at ni belgilaydi, tarqatuvchi esa oynasi yo'q
kampaniyani e'tiborsiz qoldiradi.
"""
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from asgiref.sync import sync_to_async
from django.utils import timezone
from html import escape

from tgbot.models import AdCampaign, TelegramProfile
from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user

MAX_AD_TEXT_CHARS = 600


class AdSubmitState(StatesGroup):
    link = State()
    text = State()
    reject_reason = State()


def _is_valid_link(raw: str) -> bool:
    """Only http(s), one target, no whitespace hiding a second one."""
    raw = (raw or "").strip()
    if not raw.lower().startswith(("http://", "https://")):
        return False
    if len(raw) > 500 or any(c.isspace() for c in raw):
        return False
    return True


@sync_to_async
def _open_campaign_for(user):
    """The campaign this user still owes a link for, if any."""
    return (
        AdCampaign.objects
        .filter(winner=user, status__in=[AdCampaign.STATUS_AWAITING,
                                         AdCampaign.STATUS_REJECTED])
        .order_by("-created_at").first()
    )


@sync_to_async
def _save_submission(campaign_id, link, ad_text):
    c = AdCampaign.objects.filter(id=campaign_id).first()
    if not c:
        return None
    c.link = link
    c.ad_text = ad_text
    c.status = AdCampaign.STATUS_REVIEW
    c.submitted_at = timezone.now()
    c.save(update_fields=["link", "ad_text", "status", "submitted_at", "updated_at"])
    return c


@sync_to_async
def _admin_ids():
    return list(TelegramProfile.objects.filter(is_admin=True, is_blocked=False)
                .values_list("telegram_id", flat=True))


@sync_to_async
def _campaign(cid):
    return AdCampaign.objects.filter(id=cid).select_related("winner").first()


@sync_to_async
def _do_approve(campaign, admin):
    campaign.approve(admin)
    return campaign


@sync_to_async
def _do_reject(campaign, admin, reason):
    campaign.reject(admin, reason)
    return campaign


async def start_ad_submission(message: types.Message, state: FSMContext):
    """Entry point, reached from the winner's `/start reklama` deep link."""
    user = await aget_user(message.from_user.id)
    campaign = await _open_campaign_for(user)
    if not campaign:
        await message.answer(
            "Sizda hozir kutilayotgan reklama o'rni yo'q.\n\n"
            "Reklama o'rni <b>do'kondagi auksionda</b> yutib olinadi.",
            parse_mode="HTML",
        )
        return

    await state.update_data(ad_campaign_id=campaign.id)
    again = ""
    if campaign.status == AdCampaign.STATUS_REJECTED:
        why = f": <i>{escape(campaign.reject_reason)}</i>" if campaign.reject_reason else ""
        again = f"\n\n⚠️ Oldingi havolangiz rad etilgan edi{why}\nIltimos, qaytadan yuboring."

    await message.answer(
        f"📣 <b>{campaign.duration_hours} soatlik reklama o'rni</b>{again}\n\n"
        f"1️⃣ Avval <b>havolani</b> yuboring "
        f"(http:// yoki https:// bilan boshlanishi shart).",
        parse_mode="HTML",
    )
    await AdSubmitState.link.set()


@dp.message_handler(state=AdSubmitState.link)
async def process_ad_link(message: types.Message, state: FSMContext):
    link = (message.text or "").strip()
    if not _is_valid_link(link):
        await message.answer(
            "❌ Bu havolaga o'xshamaydi.\n\n"
            "<b>https://</b> yoki <b>http://</b> bilan boshlanadigan, bo'shliqsiz "
            "bitta havola yuboring.",
            parse_mode="HTML",
        )
        return
    await state.update_data(ad_link=link)
    await message.answer(
        f"✅ Havola qabul qilindi:\n<code>{escape(link)}</code>\n\n"
        f"2️⃣ Endi reklama <b>matnini</b> yuboring "
        f"(eng ko'pi {MAX_AD_TEXT_CHARS} belgi).",
        parse_mode="HTML",
    )
    await AdSubmitState.text.set()


@dp.message_handler(state=AdSubmitState.text)
async def process_ad_text(message: types.Message, state: FSMContext):
    ad_text = (message.text or "").strip()
    if not ad_text:
        await message.answer("Iltimos, reklama matnini yuboring.")
        return
    if len(ad_text) > MAX_AD_TEXT_CHARS:
        await message.answer(
            f"❌ Matn juda uzun: {len(ad_text)} belgi. "
            f"Eng ko'pi {MAX_AD_TEXT_CHARS} belgi bo'lsin."
        )
        return

    data = await state.get_data()
    campaign = await _save_submission(
        data.get("ad_campaign_id"), data.get("ad_link"), ad_text)
    await state.finish()
    if not campaign:
        await message.answer("Reklama o'rni topilmadi. Administratorga murojaat qiling.")
        return

    await message.answer(
        "📨 <b>Yuborildi!</b>\n\n"
        "Havolangiz va matningiz administrator tekshiruvidan o'tadi. "
        "Tasdiqlangan zahoti reklamangiz barcha guruhlarda va bot "
        f"foydalanuvchilariga <b>{campaign.duration_hours} soat davomida</b> "
        "ko'rsatiladi va sizga xabar beramiz.",
        parse_mode="HTML",
    )
    await _notify_admins_for_review(campaign)


async def _notify_admins_for_review(campaign):
    """Send the submission to every admin with approve / reject buttons."""
    admins = await _admin_ids()
    if not admins:
        print(f"ads: no admins to review campaign {campaign.id}")
        return
    who = escape(campaign.winner.full_name or str(campaign.winner.telegram_id))
    body = (
        f"🛡 <b>REKLAMA MODERATSIYASI</b>\n\n"
        f"👤 G'olib: {who}\n"
        f"⏱ Muddat: <b>{campaign.duration_hours} soat</b>\n"
        f"💰 Taklif: {campaign.bid_amount} Kitobcha\n\n"
        f"🔗 Havola:\n<code>{escape(campaign.link)}</code>\n\n"
        f"📝 Matn:\n{escape(campaign.ad_text)}\n\n"
        f"Tasdiqlasangiz, reklama <b>darhol</b> barcha guruhlar va bot "
        f"foydalanuvchilariga yuboriladi."
    )
    kb = InlineKeyboardMarkup().row(
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"ad:ok:{campaign.id}"),
        InlineKeyboardButton("❌ Rad etish", callback_data=f"ad:no:{campaign.id}"),
    )
    for tid in admins:
        try:
            await bot.send_message(tid, body, parse_mode="HTML", reply_markup=kb,
                                   disable_web_page_preview=True)
        except Exception as e:
            print(f"ads: notify admin {tid}: {e}")


@dp.callback_query_handler(lambda c: c.data.startswith("ad:ok:"), state="*")
async def approve_ad(call: CallbackQuery, state: FSMContext):
    admin = await aget_user(call.from_user.id)
    if not (admin and admin.is_admin):
        await call.answer("Faqat adminlar uchun.", show_alert=True)
        return
    campaign = await _campaign(int(call.data.split(":")[2]))
    if not campaign:
        await call.answer("Topilmadi.", show_alert=True)
        return
    if campaign.status == AdCampaign.STATUS_LIVE:
        await call.answer("Bu reklama allaqachon efirda.", show_alert=True)
        return
    if campaign.status != AdCampaign.STATUS_REVIEW:
        await call.answer("Bu reklama moderatsiyada emas.", show_alert=True)
        return

    await call.answer("Tasdiqlandi ✅")
    await _do_approve(campaign, admin)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(
        f"✅ Tasdiqladingiz. Reklama tarqatilmoqda — "
        f"{campaign.duration_hours} soat efirda bo'ladi."
    )
    # Broadcasting reaches thousands of chats, so it belongs on the worker.
    from tgbot.tasks import broadcast_ad_campaign
    try:
        broadcast_ad_campaign.delay(campaign.id)
    except Exception as e:
        print(f"ads: could not queue broadcast for {campaign.id}: {e}")
        await call.message.answer(
            "⚠️ Tarqatish navbatga qo'yilmadi. Worker ishlayotganini tekshiring."
        )


@dp.callback_query_handler(lambda c: c.data.startswith("ad:no:"), state="*")
async def reject_ad_ask_reason(call: CallbackQuery, state: FSMContext):
    admin = await aget_user(call.from_user.id)
    if not (admin and admin.is_admin):
        await call.answer("Faqat adminlar uchun.", show_alert=True)
        return
    campaign = await _campaign(int(call.data.split(":")[2]))
    if not campaign or campaign.status != AdCampaign.STATUS_REVIEW:
        await call.answer("Bu reklama moderatsiyada emas.", show_alert=True)
        return
    await call.answer()
    await state.update_data(reject_campaign_id=campaign.id)
    await call.message.answer(
        "❌ Rad etish sababini yozing — g'olibga shu matn yuboriladi, "
        "u tuzatib qayta yuborishi mumkin."
    )
    await AdSubmitState.reject_reason.set()


@dp.message_handler(state=AdSubmitState.reject_reason)
async def process_reject_reason(message: types.Message, state: FSMContext):
    admin = await aget_user(message.from_user.id)
    data = await state.get_data()
    campaign = await _campaign(data.get("reject_campaign_id"))
    await state.finish()
    if not campaign:
        await message.answer("Reklama topilmadi.")
        return
    reason = (message.text or "").strip()
    await _do_reject(campaign, admin, reason)
    await message.answer("❌ Rad etildi. G'olibga xabar berildi.")
    try:
        await bot.send_message(
            campaign.winner.telegram_id,
            "❌ <b>Reklama havolangiz tasdiqlanmadi.</b>\n\n"
            f"Sabab: <i>{escape(reason)}</i>\n\n"
            "Reklama o'rningiz saqlanib qoldi — havolani tuzatib qaytadan "
            "yuborishingiz mumkin: /reklama",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"ads: notify winner of rejection {campaign.id}: {e}")


@dp.message_handler(commands=["reklama"], state="*")
async def cmd_reklama(message: types.Message, state: FSMContext):
    await state.finish()
    await start_ad_submission(message, state)
