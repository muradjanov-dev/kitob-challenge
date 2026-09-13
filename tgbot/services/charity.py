"""Xayriya jamg'armasi — Kitobcha qaytib olinmaydigan, qimorsiz chiqim.

Har kim istagancha (kamida CHARITY_MIN_CONTRIBUTION) Kitobcha qo'shadi. Har
`ShopProduct.charity_step` (100.000) Kitobcha to'planganda loyiha
Kitobxonlar nomidan 100.000 so'm xayriya qiladi yoki muhtoj insonga shu
qiymatgacha kitob olib beradi.

Oqim:
  contribute()            -- Kitobcha yechiladi, hissa yoziladi; bosqich
                             kesib o'tilsa CharityMilestone yaratiladi va
                             tranzaksiyadan keyin Celery vazifasi navbatga
                             qo'yiladi.
  tasks.charity_milestone_broadcast
                          -- guruhlarga tabrik, qatnashganlarga rahmat,
                             qatnashmaganlarga taklif, adminlarga eslatma.
  admin "Bajarildi" action -- announce_fulfilled(): guruhlarga hisobot.
"""
import html as _html

from django.db import transaction
from django.db.models import Count, Sum

from tgbot.models import (
    CHARITY_MIN_CONTRIBUTION, CharityContribution, CharityMilestone,
    KitobchaLedger, ShopProduct, TelegramProfile,
)


class CharityError(Exception):
    def __init__(self, code: str, **extra):
        super().__init__(code)
        self.code = code
        self.extra = extra


def fmt(n: int) -> str:
    """100000 -> '100.000' (Uzbek thousands separator)."""
    return f"{int(n):,}".replace(",", ".")


def raised_total(product_id: int) -> int:
    return CharityContribution.objects.filter(product_id=product_id).aggregate(
        s=Sum("amount"))["s"] or 0


def contribute(user_id: int, product_id: int, amount: int) -> dict:
    """Deduct `amount` Kitobcha from the user into the fund. Raises
    CharityError on any refusal; nothing is written in that case."""
    if not isinstance(amount, int) or amount < CHARITY_MIN_CONTRIBUTION:
        raise CharityError("amount_too_low", min_required=CHARITY_MIN_CONTRIBUTION)

    new_milestone_ids = []
    with transaction.atomic():
        # Product lock first: it serialises every contribution to this fund,
        # so the before/after totals below can't interleave and each step is
        # detected exactly once.
        product = ShopProduct.objects.select_for_update().filter(
            id=product_id, is_active=True, is_charity=True,
        ).first()
        if not product:
            raise CharityError("charity_not_found")
        user = TelegramProfile.objects.select_for_update().get(id=user_id)

        balance = int(user.ball or 0)
        if balance < amount:
            raise CharityError("insufficient_balance", balance=balance, needed=amount)

        before = raised_total(product.id)
        user.ball = user.ball - amount
        user.save(update_fields=["ball"])
        KitobchaLedger.objects.create(user=user, delta=-amount, reason=f"charity:{product.id}")
        contribution = CharityContribution.objects.create(
            product=product, user=user, amount=amount,
        )
        after = before + amount

        step = product.charity_step or 100_000
        for number in range(before // step + 1, after // step + 1):
            milestone = CharityMilestone.objects.create(
                product=product, number=number, last_contribution=contribution,
            )
            milestone.participants_count = len(milestone.participant_ids())
            milestone.save(update_fields=["participants_count"])
            new_milestone_ids.append(milestone.id)

        def _queue():
            from tgbot.tasks import charity_milestone_broadcast
            for mid in new_milestone_ids:
                try:
                    charity_milestone_broadcast.delay(mid)
                except Exception as e:
                    print(f"charity: could not queue milestone #{mid}: {e}")

        if new_milestone_ids:
            transaction.on_commit(_queue)

    my_total = CharityContribution.objects.filter(
        product_id=product.id, user_id=user.id).aggregate(s=Sum("amount"))["s"] or 0
    return {
        "balance": int(user.ball or 0),
        "my_total": my_total,
        "raised": after,
        "milestone_reached": bool(new_milestone_ids),
    }


def details(product: ShopProduct, viewer_id: int | None) -> dict:
    step = product.charity_step or 100_000
    raised = raised_total(product.id)
    contributions = CharityContribution.objects.filter(product_id=product.id)

    top = (
        contributions.values("user_id", "user__full_name", "user__telegram_id")
        .annotate(total=Sum("amount"))
        .order_by("-total")[:20]
    )
    top_donors = [{
        "rank": i,
        "name": r["user__full_name"] or f"Kitobxon #{r['user__telegram_id']}",
        "amount": r["total"],
        "is_me": r["user_id"] == viewer_id,
    } for i, r in enumerate(top, 1)]

    milestones = [{
        "number": m.number,
        "is_fulfilled": m.is_fulfilled,
        "note": m.fulfilled_note if m.is_fulfilled else "",
    } for m in product.charity_milestones.all()]

    my_total = 0
    if viewer_id:
        my_total = contributions.filter(user_id=viewer_id).aggregate(
            s=Sum("amount"))["s"] or 0

    return {
        "step": step,
        "raised": raised,
        "done_count": raised // step,
        "progress": raised % step,
        "donors_count": contributions.aggregate(n=Count("user_id", distinct=True))["n"] or 0,
        "top_donors": top_donors,
        "milestones": milestones,
        "my_total": my_total,
        "min_contribution": CHARITY_MIN_CONTRIBUTION,
    }


# ── Message texts ──────────────────────────────────────────────────────────

def milestone_group_text(m: CharityMilestone) -> str:
    step = fmt(m.product.charity_step)
    return (
        f"💚 <b>KITOBXONLAR {step} KITOBCHA TO'PLADI!</b> 🎉\n\n"
        f"Xayriya jamg'armasining <b>{m.number}-bosqichi</b> yakunlandi!\n"
        f"🤝 <b>{m.participants_count} nafar kitobxon</b> bu savobli ishga sherik bo'ldi.\n\n"
        f"Endi loyiha <b>Kitobxonlar nomidan {step} so'm</b> xayriya qiladi "
        f"yoki muhtoj insonga <b>{step} so'mgacha qiymatdagi kitob</b> olib beradi. "
        "Amalga oshirilgach, hisobotini shu yerda e'lon qilamiz.\n\n"
        "Barchangizga katta rahmat! Keyingi bosqich allaqachon boshlandi — "
        f"kamida <b>{CHARITY_MIN_CONTRIBUTION} Kitobcha</b> bilan qo'shiling 👇"
    )


def milestone_participant_text(m: CharityMilestone) -> str:
    step = fmt(m.product.charity_step)
    return (
        "💚 <b>Tabriklaymiz! Birgalikda uddaladik!</b>\n\n"
        f"Xayriya jamg'armasi <b>{step} Kitobcha</b>ga yetdi — va unda "
        "<b>sizning ham hissangiz bor!</b>\n\n"
        f"🤝 Siz bilan birga <b>{m.participants_count} nafar kitobxon</b> savobga sherik bo'ldi.\n"
        f"🎁 Endi loyiha Kitobxonlar nomidan <b>{step} so'm</b> xayriya qiladi "
        "yoki muhtoj insonga kitob olib beradi.\n\n"
        "Xayrli ishda sherik bo'lganingiz uchun chin qalbdan rahmat! 🤲\n\n"
        f"<b>{m.number + 1}-bosqich</b> allaqachon boshlandi — keyingisidan ham "
        "qolib ketmang!"
    )


def milestone_non_participant_text(m: CharityMilestone) -> str:
    step = fmt(m.product.charity_step)
    return (
        f"💚 <b>{m.participants_count} nafar kitobxon savobga sherik bo'ldi!</b>\n\n"
        f"Kitobxonlar birgalikda <b>{step} Kitobcha</b> to'pladi. Endi loyiha "
        f"ular nomidan <b>{step} so'm</b> xayriya qiladi yoki muhtoj insonga "
        "kitob olib beradi.\n\n"
        f"<b>{m.number + 1}-bosqich</b> hozir boshlandi. Keyingisidan qolib "
        f"ketmang — hatto <b>{CHARITY_MIN_CONTRIBUTION} Kitobcha</b> bilan ham "
        "bu savobli ishga sherik bo'lishingiz mumkin! 🤲"
    )


def milestone_admin_text(m: CharityMilestone) -> str:
    step = fmt(m.product.charity_step)
    return (
        f"💚 <b>Xayriya #{m.number} bosqichiga yetildi!</b>\n\n"
        f"🪙 {step} Kitobcha to'plandi, {m.participants_count} ta ishtirokchi.\n\n"
        f"Endi <b>{step} so'm</b> xayriya qiling yoki muhtoj insonga kitob "
        "olib bering. So'ng Django admin → <i>Xayriya bosqichlari</i>da nima "
        "qilinganini yozib, «✅ Bajarildi — guruhlarga hisobot» amalini bosing."
    )


def launch_text() -> str:
    return (
        "💚 <b>KITOBXONLAR XAYRIYA JAMG'ARMASI OCHILDI!</b> 🤲📚\n\n"
        "Kitobchalaringiz endi nafaqat mukofot, balki <b>haqiqiy yaxshilik</b> "
        "ham bo'la oladi!\n\n"
        "🎯 <b>Qanday ishlaydi:</b>\n"
        "• Do'kondagi «Xayriya jamg'armasi»ga istagancha Kitobcha qo'shasiz "
        f"(kamida <b>{CHARITY_MIN_CONTRIBUTION} Kitobcha</b>).\n"
        "• Har <b>100.000 Kitobcha</b> to'planganda loyiha <b>Kitobxonlar nomidan "
        "100.000 so'm</b> xayriya qiladi yoki muhtoj insonga <b>100.000 so'mgacha "
        "qiymatdagi kitob</b> olib beradi.\n"
        "• Har bir xayriya hisoboti guruhlarda e'lon qilinadi.\n"
        "• Kim qancha qo'shgani do'kondagi ro'yxatda jonli ko'rinib turadi.\n\n"
        "O'qiganingiz — ilm, ulashganingiz — savob. Birinchi 100.000 ni birga "
        "yig'amiz! 👇"
    )


def fulfilled_group_text(m: CharityMilestone) -> str:
    return (
        f"✅ <b>XAYRIYA #{m.number} AMALGA OSHIRILDI!</b> 💚\n\n"
        f"{_html.escape(m.fulfilled_note.strip())}\n\n"
        f"🤝 Bu yaxshilik <b>{m.participants_count} nafar kitobxon</b> hissasi bilan "
        "amalga oshdi. Alloh qabul qilsin! 🤲\n\n"
        "Keyingi bosqichga ham hissa qo'shing — «🛒 Do'kon» → «Xayriya jamg'armasi»."
    )
