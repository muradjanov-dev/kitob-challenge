"""O'yin ichidagi yordamlar ("jokerlar") — Kitobcha evaziga sotib olinadi.

Uchta joker, ikkala jonli o'yinda ham (Bilim O'yini va Omon qolish):

  💡 fifty  (100) — ikkita noto'g'ri variantni yashiradi.
  ❤️ shield (300) — Omon qolishda +1 jon; Bilim o'yinida bitta xato javobni
                    kechiruvchi qalqon (ochko baribir beriladi).
  🎯 sniper (500) — to'g'ri javobni avtomatik belgilab yuboradi.

Narxlar ataylab mukofotlardan yuqori: bir o'yindagi 1-o'rin 300 Kitobcha
(VIP arenada 500), ya'ni jokerlarni "foyda uchun" sotib olib bo'lmaydi —
ular faqat qulaylik va Kitobcha sarflash yo'li, reyting sotib olish emas.
"""

from django.db import IntegrityError, transaction

from tgbot.models import GameJoker, KitobchaLedger, TelegramProfile

FIFTY = GameJoker.KIND_FIFTY
SHIELD = GameJoker.KIND_SHIELD
SNIPER = GameJoker.KIND_SNIPER

PRICES = {FIFTY: 100, SHIELD: 300, SNIPER: 500}
KINDS = tuple(PRICES)

LABELS = {
    FIFTY: "💡 50/50",
    SHIELD: "❤️ Qo'shimcha jon",
    SNIPER: "🎯 Snayper",
}

# Bitta o'yinda nechta qalqon / qo'shimcha jon olish mumkin. Cheksiz bo'lsa
# balansi katta o'yinchi Omon qolishda umuman chetlatilmasdi.
MAX_SHIELDS_PER_GAME = 2


def charge(profile, amount: int, reason: str) -> bool:
    """Kitobchani balansdan yechib oladi. Yetarli bo'lmasa False qaytaradi.

    Ataylab `_add_ball_reward(user, -amount)` ishlatilmaydi: u
    `update_ball` orqali o'tadi va Premium a'zolarga 2× ko'paytirgichni
    qo'llaydi — ya'ni Premium foydalanuvchidan ikki baravar ko'p Kitobcha
    yechib olardi. Bu yerda narx hamma uchun bir xil.
    """
    amount = int(amount)
    if amount <= 0:
        return True
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=profile.id)
        if int(p.ball or 0) < amount:
            return False
        p.ball = p.ball - amount
        p.save(update_fields=["ball"])
        KitobchaLedger.objects.create(user=p, delta=-amount, reason=reason)
    # Chaqiruvchidagi nusxa eskirmasin — javobda yangi balans ko'rsatiladi.
    profile.ball = p.ball
    return True


def refund(profile, amount: int, reason: str) -> None:
    """Yechib olingan Kitobchani qaytaradi (joker qo'llanmay qolgan holatda)."""
    amount = int(amount)
    if amount <= 0:
        return
    with transaction.atomic():
        p = TelegramProfile.objects.select_for_update().get(id=profile.id)
        p.ball = p.ball + amount
        p.save(update_fields=["ball"])
        KitobchaLedger.objects.create(user=p, delta=amount, reason=reason)
    profile.ball = p.ball


def game_rows(profile, game_type: str, game_id: int) -> list:
    """Shu o'yinda shu foydalanuvchi olgan barcha jokerlar (odatda 0-5 ta).

    Holat so'rovi har 1.5 soniyada kelgani uchun ataylab bitta so'rov: kerakli
    hamma narsa (joriy savol uchun ishlatilganlari, 50/50 yashirgan indekslar,
    olingan qalqonlar soni) shu ro'yxatdan hisoblanadi.
    """
    return list(
        GameJoker.objects.filter(user=profile, game_type=game_type, game_id=game_id)
        .values("kind", "q_index", "payload")
    )


def summarize(rows: list, q_index: int) -> dict:
    """`game_rows` natijasini frontend kutadigan ko'rinishga keltiradi."""
    used, hidden = [], []
    shields = 0
    for r in rows:
        if r["kind"] == SHIELD:
            shields += 1
        if r["q_index"] == q_index:
            used.append(r["kind"])
            if r["kind"] == FIFTY:
                hidden = list((r["payload"] or {}).get("hidden") or [])
    return {
        "used": sorted(set(used)),
        "hidden": hidden,
        "shields_bought": shields,
        "shields_left_to_buy": max(0, MAX_SHIELDS_PER_GAME - shields),
    }


def find(profile, game_type: str, game_id: int, q_index: int, kind: str):
    return GameJoker.objects.filter(
        user=profile, game_type=game_type, game_id=game_id,
        q_index=q_index, kind=kind,
    ).first()


def used_kinds(profile, game_type: str, game_id: int, q_index: int) -> set:
    return set(
        GameJoker.objects.filter(
            user=profile, game_type=game_type, game_id=game_id, q_index=q_index,
        ).values_list("kind", flat=True)
    )


def shield_count(profile, game_type: str, game_id: int) -> int:
    """Shu o'yinda sotib olingan qalqon/jonlar soni (limitni tekshirish uchun)."""
    return GameJoker.objects.filter(
        user=profile, game_type=game_type, game_id=game_id, kind=SHIELD,
    ).count()


def buy(profile, *, game_type: str, game_id: int, q_index: int, kind: str,
        flavor: str = "", payload: dict | None = None):
    """Jokerni yozib qo'yadi va hisobdan Kitobcha yechadi.

    `(joker, created, error)` qaytaradi. Allaqachon sotib olingan bo'lsa
    ikkinchi marta pul yechilmaydi — mavjud yozuv `created=False` bilan
    qaytariladi, shuning uchun tarmoq uzilib qayta yuborilgan so'rov ham
    xavfsiz.
    """
    existing = find(profile, game_type, game_id, q_index, kind)
    if existing:
        return existing, False, None

    price = PRICES[kind]
    if not charge(profile, price, f"joker_{kind}"):
        return None, False, "insufficient_balance"

    try:
        joker = GameJoker.objects.create(
            user=profile, game_type=game_type, game_id=game_id, flavor=flavor,
            q_index=q_index, kind=kind, price=price, payload=payload or {},
        )
    except IntegrityError:
        # Bir vaqtda kelgan ikkinchi so'rov — pulni qaytarib, mavjudini beramiz.
        refund(profile, price, f"joker_{kind}_refund")
        return find(profile, game_type, game_id, q_index, kind), False, None
    return joker, True, None


def pick_hidden(options, correct_index: int) -> list:
    """50/50 uchun yashiriladigan noto'g'ri variant indekslari.

    4 ta variantda 2 tasini yashiradi, 3 tada esa 1 tasini — har doim
    kamida bitta noto'g'ri variant qoladi, aks holda joker to'g'ri javobni
    ochiq ko'rsatib qo'ygan bo'lardi.
    """
    import random

    wrong = [i for i in range(len(options or [])) if i != correct_index]
    if len(wrong) < 2:
        return []
    return sorted(random.sample(wrong, min(2, len(wrong) - 1)))


def prices_payload() -> dict:
    return {k: PRICES[k] for k in KINDS}
