"""Links that open the shop Mini App straight on one product.

Group posts cannot carry web_app buttons (Telegram allows them only in
private chats), so a product announcement uses a URL button instead:

- with the bot's Main Mini App enabled in BotFather (getMe ->
  has_main_web_app), https://t.me/<bot>?startapp=shop_<id> opens the Mini
  App itself, in place, with start_param "shop_<id>"; _deeplink.html on the
  landing page forwards that to /shop/?p=<id>, which opens the product;
- until then, https://t.me/<bot>?start=shop_<id> goes through the bot chat,
  which answers with a one-tap web_app button to the same product page.
"""
import requests
from django.core.cache import cache

PARAM_PREFIX = "shop_"


def _get_me() -> dict:
    me = cache.get("bot_getme")
    if me is None:
        from tgbot.tasks import BOT_TOKEN
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
            me = r.json().get("result", {}) if r.ok else {}
        except Exception:
            me = {}
        # Short TTL: the owner can switch the Main Mini App on in BotFather
        # at any time, and links should follow within minutes.
        cache.set("bot_getme", me, 600 if me else 60)
    return me


def product_url(product_id) -> str | None:
    me = _get_me()
    username = me.get("username")
    if not username:
        return None
    param = f"{PARAM_PREFIX}{int(product_id)}"
    if me.get("has_main_web_app"):
        return f"https://t.me/{username}?startapp={param}"
    return f"https://t.me/{username}?start={param}"


def product_page(product_id) -> str:
    """The shop page itself, opened on `product_id` (for web_app buttons)."""
    from src.settings import WEB_DOMAIN
    base = str(WEB_DOMAIN).rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"
    return f"{base}/shop/?p={int(product_id)}"


def parse_param(value) -> int | None:
    value = (value or "").strip()
    if value.startswith(PARAM_PREFIX) and value[len(PARAM_PREFIX):].isdigit():
        return int(value[len(PARAM_PREFIX):])
    return None


def button(text: str, product_id) -> dict | None:
    url = product_url(product_id)
    return {"text": text, "url": url} if url else None
