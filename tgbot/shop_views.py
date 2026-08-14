"""Kitob Challenge Shop — Telegram Mini App.

Admins upload products via Django admin; users (currently gated to is_admin
for testing) browse and buy with their Kitobcha balance.

Telegram WebApp authentication: every API request must include the raw
`initData` query string from `window.Telegram.WebApp.initData` either as a
header (`X-Telegram-Init-Data`) or as a body field. We verify the HMAC and
look up the TelegramProfile by `id` from the embedded user payload.

To open the shop to all users later: remove the `is_admin` check in
`_require_authed_admin` AND switch the menu keyboard to show the WebApp
button to non-admins (see tgbot/bot/keyboards/reply.py).
"""

import hashlib
import hmac
import html as _html
import json
import secrets
from decimal import Decimal
from functools import wraps
from urllib.parse import parse_qsl

import requests
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from tgbot.models import Payment, ShopProduct, ShopPurchase, TelegramProfile, KitobchaLedger


# ─────────────────────────────────────────────────────────────────────────────
# initData verification.
#
# Per https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app,
# the secret key is HMAC_SHA256(key=b"WebAppData", msg=bot_token).
# The hash over (k=v) pairs sorted by k, joined by \n, must match the `hash`
# field.
# ─────────────────────────────────────────────────────────────────────────────
def _verify_init_data(init_data: str) -> dict | None:
    if not init_data:
        print("shop_verify: init_data empty")
        return None
    try:
        # strict_parsing=False — some Telegram clients put fields with quirky
        # encoding into initData; strict mode would raise on them.
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    except ValueError as e:
        print(f"shop_verify: parse_qsl failed: {e}")
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        print(f"shop_verify: no hash in pairs, keys={list(pairs.keys())}")
        return None
    # Per Telegram docs: data_check_string is k=v lines sorted by k, joined by \n.
    # Values are the URL-decoded form (parse_qsl already decoded them).
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", settings.API_TOKEN.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        # Log enough to diagnose without leaking the bot token.
        print(
            f"shop_verify: hash mismatch. computed={computed[:12]}... "
            f"received={received_hash[:12]}... keys={sorted(pairs.keys())} "
            f"raw_len={len(init_data)}"
        )
        return None
    user_json = pairs.get("user")
    if not user_json:
        print(f"shop_verify: no user field in initData, keys={list(pairs.keys())}")
        return None
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError as e:
        print(f"shop_verify: user JSON decode failed: {e}")
        return None
    if not isinstance(user, dict) or "id" not in user:
        print(f"shop_verify: user payload missing id: {user!r}")
        return None
    return user


def _read_init_data(request: HttpRequest) -> str:
    """initData may arrive via header (preferred for API calls) or as a query
    param on the initial HTML page load. We accept both."""
    return (
        request.headers.get("X-Telegram-Init-Data")
        or request.GET.get("initData")
        or ""
    )


def _resolve_profile(init_data: str) -> tuple[TelegramProfile | None, str | None]:
    """Returns (profile, error_code). error_code is None on success."""
    tg_user = _verify_init_data(init_data)
    if not tg_user:
        return None, "invalid_init_data"
    profile = TelegramProfile.objects.filter(telegram_id=str(tg_user["id"])).first()
    if not profile:
        return None, "profile_not_found"
    if profile.is_blocked:
        return None, "blocked"
    return profile, None


def _require_authed(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        init_data = _read_init_data(request)
        profile, err = _resolve_profile(init_data)
        if err:
            return JsonResponse({"ok": False, "error": err}, status=403)
        request.tg_profile = profile
        return view(request, *args, **kwargs)
    return wrapper


# Back-compat alias — earlier code (admin-only test mode) used this name.
_require_authed_admin = _require_authed


# ─────────────────────────────────────────────────────────────────────────────
# Views.
# ─────────────────────────────────────────────────────────────────────────────
def shop_index(request: HttpRequest) -> HttpResponse:
    """Single-page Mini App. The page itself doesn't require a valid initData
    (the Telegram WebApp SDK injects it client-side); the actual gate is on
    every API call. This keeps initial render fast and lets us show a friendly
    'not authorized' state instead of a 403 wall."""
    resp = render(request, "shop/index.html", {
        "shop_currency_label": "Kitobcha",
    })
    # Telegram Desktop's embedded WebView2 caches aggressively. Force a fresh
    # fetch on every open so JS fixes ship immediately to clients that
    # already loaded the page in this session.
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp


def _product_payload(p: ShopProduct, request: HttpRequest) -> dict:
    img = None
    if p.image:
        try:
            img = request.build_absolute_uri(p.image.url)
        except Exception:
            img = None
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description or "",
        "image_url": img,
        "price": p.price_kitobcha,
        "stock_qty": p.stock_qty,
        "is_available": p.is_available,
    }


@csrf_exempt
@require_GET
def api_products_public(request: HttpRequest) -> JsonResponse:
    """Catalog only, no Telegram auth -- the product list itself (name,
    price, image, stock) isn't personal data, so it doesn't need to wait on
    initData at all. This is what makes the shop page feel instant: the grid
    renders the moment this resolves, while the slower authed balance/'me'
    call (api_me) fills in the personal parts in the background. Cached
    briefly since it's now the very first thing every shop-page load hits."""
    from django.core.cache import cache

    cached = cache.get("kc_shop_products_public_v1")
    if cached is None:
        products = list(ShopProduct.objects.filter(is_active=True).order_by("sort_order", "-created_at"))
        products.sort(key=lambda p: not p.is_available)
        cached = [_product_payload(p, request) for p in products]
        cache.set("kc_shop_products_public_v1", cached, 20)
    return JsonResponse({"ok": True, "products": cached})


@csrf_exempt
@require_GET
@_require_authed_admin
def api_products(request: HttpRequest) -> JsonResponse:
    products = list(ShopProduct.objects.filter(is_active=True).order_by("sort_order", "-created_at"))
    # In-stock items first (admin's sort_order/-created_at order preserved within
    # each group) — sold-out items sink to the bottom instead of cluttering the top.
    products.sort(key=lambda p: not p.is_available)
    return JsonResponse({
        "ok": True,
        "products": [_product_payload(p, request) for p in products],
        "me": {
            "telegram_id": request.tg_profile.telegram_id,
            "full_name": request.tg_profile.full_name or "",
            "balance": int(request.tg_profile.ball or 0),
        },
    })


@csrf_exempt
@require_GET
@_require_authed_admin
def api_me(request: HttpRequest) -> JsonResponse:
    return JsonResponse({
        "ok": True,
        "telegram_id": request.tg_profile.telegram_id,
        "full_name": request.tg_profile.full_name or "",
        "balance": int(request.tg_profile.ball or 0),
    })


def _gen_purchase_code() -> str:
    """12-char uppercase base32-ish code, e.g. 'KC-7F9X-A2H4'."""
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # avoid look-alike chars
    rnd = lambda n: "".join(secrets.choice(alpha) for _ in range(n))
    return f"KC-{rnd(4)}-{rnd(4)}"


@csrf_exempt
@require_POST
@_require_authed_admin
def api_buy(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    product_id = body.get("product_id")
    if not isinstance(product_id, int):
        return JsonResponse({"ok": False, "error": "product_id_required"}, status=400)

    # Atomic: lock the buyer row and the product row, recheck availability,
    # decrement balance + stock, write the purchase. select_for_update keeps
    # double-spend safe under concurrent clicks.
    try:
        with transaction.atomic():
            user = TelegramProfile.objects.select_for_update().get(id=request.tg_profile.id)
            product = ShopProduct.objects.select_for_update().filter(
                id=product_id, is_active=True,
            ).first()
            if not product:
                return JsonResponse({"ok": False, "error": "product_unavailable"}, status=400)
            if product.stock_qty is not None and product.stock_qty <= 0:
                return JsonResponse({"ok": False, "error": "out_of_stock"}, status=400)
            price = product.price_kitobcha
            if int(user.ball or 0) < price:
                return JsonResponse({
                    "ok": False, "error": "insufficient_balance",
                    "balance": int(user.ball or 0), "price": price,
                }, status=400)

            user.ball = (user.ball or Decimal("0")) - Decimal(price)
            user.save(update_fields=["ball"])
            KitobchaLedger.objects.create(user=user, delta=-price, reason="shop_purchase")
            if product.stock_qty is not None:
                product.stock_qty = product.stock_qty - 1
                product.save(update_fields=["stock_qty"])

            # Unique code with a few retries to dodge the astronomically rare
            # collision.
            for _ in range(5):
                code = _gen_purchase_code()
                if not ShopPurchase.objects.filter(code=code).exists():
                    break
            else:
                return JsonResponse({"ok": False, "error": "code_gen_failed"}, status=500)

            purchase = ShopPurchase.objects.create(
                user=user,
                product=product,
                product_name_snapshot=product.name,
                price_at_purchase=price,
                code=code,
                status=ShopPurchase.STATUS_PENDING,
            )

            # Premium-granting products (e.g. "Kitob Challenge Premium — 1
            # oy") are fulfilled instantly: no admin hand-off needed, and any
            # remaining active Premium is extended rather than reset.
            premium_grant = None
            if product.grants_premium_days:
                premium_grant = Payment.grant_or_extend(user, product.grants_premium_days)
                purchase.status = ShopPurchase.STATUS_FULFILLED
                purchase.save(update_fields=["status"])
    except TelegramProfile.DoesNotExist:
        return JsonResponse({"ok": False, "error": "profile_missing"}, status=403)

    if premium_grant:
        try:
            _notify_user_of_premium_grant(user, product, premium_grant)
        except Exception as e:
            print(f"shop: premium-grant notify failed for purchase {purchase.code}: {e}")
    else:
        # Fire-and-forget admin notifications. Wrapped in try/except so a
        # Telegram API hiccup never fails the actual purchase — the user
        # already paid.
        try:
            _notify_admins_of_purchase(purchase, user)
        except Exception as e:
            print(f"shop: admin notify failed for purchase {purchase.code}: {e}")

    return JsonResponse({
        "ok": True,
        "purchase": {
            "code": purchase.code,
            "product_name": purchase.product_name_snapshot,
            "price": purchase.price_at_purchase,
        },
        "balance": int(user.ball or 0),
    })


def _notify_admins_of_purchase(purchase: ShopPurchase, buyer: TelegramProfile) -> None:
    """DM every is_admin user about a new purchase so they can hand over the
    prize. The message carries the buyer's full profile plus one-tap contact
    options so the admin can reach out immediately.
    Best-effort: failures are logged and swallowed (caller does this)."""
    admins = list(
        TelegramProfile.objects
        .filter(is_admin=True, is_blocked=False)
        .values_list("telegram_id", flat=True)
    )
    if not admins:
        return

    name = _html.escape(buyer.full_name or "Kitobxon")
    product = _html.escape(purchase.product_name_snapshot or "")

    # Full buyer profile so the admin has everything needed to deliver the prize.
    username = f"@{buyer.username}" if buyer.username else "—"
    phone = _html.escape(buyer.phone_number or "—")
    gender_label = {"male": "Erkak", "female": "Ayol"}.get(buyer.gender or "", "—")
    try:
        region_label = buyer.region.name if buyer.region else "—"
    except Exception:
        region_label = "—"
    region_label = _html.escape(region_label or "—")
    try:
        referrals_total = buyer.referrals.count()
    except Exception:
        referrals_total = 0
    balance_left = int(buyer.ball or 0)

    # Two ways to reach the buyer: a tg://user deep-link (works even with no
    # @username) and the @username itself when present.
    contact_link = f"<a href=\"tg://user?id={buyer.telegram_id}\">✍️ Xabar yozish</a>"

    text = (
        "🛒 <b>Yangi xarid!</b>\n\n"
        f"🎁 <b>Mahsulot:</b> {product}\n"
        f"💰 <b>Narx:</b> {purchase.price_at_purchase} Kitobcha\n"
        f"🎫 <b>Kod:</b> <code>{purchase.code}</code>\n\n"
        f"👤 <b>Xaridor ma'lumotlari</b>\n"
        f"• Ism: <b>{name}</b>\n"
        f"• Username: {username}\n"
        f"• Telefon: {phone}\n"
        f"• Telegram ID: <code>{buyer.telegram_id}</code>\n"
        f"• Jins: {gender_label}\n"
        f"• Hudud: {region_label}\n"
        f"• Takliflar soni: {referrals_total} ta\n"
        f"• Qolgan balans: <b>{balance_left} Kitobcha</b>\n\n"
        f"📞 {contact_link} — mukofotni topshiring va admin paneldan "
        "<i>Fulfilled</i> deb belgilang."
    )
    url = f"https://api.telegram.org/bot{settings.API_TOKEN}/sendMessage"
    for admin_id in admins:
        try:
            requests.post(url, data={
                "chat_id": admin_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }, timeout=5)
        except Exception as e:
            print(f"shop: notify admin {admin_id} failed: {e}")


def _notify_user_of_premium_grant(buyer: TelegramProfile, product: ShopProduct, grant: Payment) -> None:
    """DM the buyer that their Premium-granting shop purchase was applied
    instantly — no admin hand-off needed for these, unlike ordinary prizes."""
    text = (
        "🎉 <b>Tabriklaymiz! Premium faollashtirildi!</b>\n\n"
        f"🛍 <b>{_html.escape(product.name)}</b> sotib olindi.\n"
        f"📅 Muddati: <b>{grant.start_date.strftime('%d.%m.%Y')}</b> — "
        f"<b>{grant.end_date.strftime('%d.%m.%Y')}</b>\n\n"
        "Agar avvaldan faol Premiumingiz bo'lsa, yangi kunlar shu muddatga "
        "qo'shildi — muddat qisqarmadi, faqat uzaydi.\n\n"
        "Kabinetingizni oching va barcha imkoniyatlardan bahramand bo'ling! 🚀"
    )
    requests.post(
        f"https://api.telegram.org/bot{settings.API_TOKEN}/sendMessage",
        data={"chat_id": buyer.telegram_id, "text": text, "parse_mode": "HTML"},
        timeout=5,
    )
