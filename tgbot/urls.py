from django.urls import path
from .views import home, telegram
from src.settings import WEBHOOK_PATH
from tgbot.views import health_check_celery, health_check_redis
from tgbot.shop_views import shop_index, api_products, api_me, api_buy
from tgbot.game_views import (
    chain_index, api_chain_state, api_chain_submit, api_chain_challenge,
    feud_index, api_feud_state, api_feud_submit,
    castle_index, api_castle_state, api_castle_submit,
)


urlpatterns = [
    path('', home, name='home'),
    path(WEBHOOK_PATH, telegram, name='webhook'),
    path("health-check/redis/", health_check_redis, name="health-check-redis"),
    path("health-check/celery/", health_check_celery, name="health-check-celery"),
    path("shop/", shop_index, name="shop"),
    path("shop/api/products/", api_products, name="shop-api-products"),
    path("shop/api/me/", api_me, name="shop-api-me"),
    path("shop/api/buy/", api_buy, name="shop-api-buy"),
    path("zanjir/", chain_index, name="chain"),
    path("zanjir/api/state/", api_chain_state, name="chain-api-state"),
    path("zanjir/api/submit/", api_chain_submit, name="chain-api-submit"),
    path("zanjir/api/challenge/", api_chain_challenge, name="chain-api-challenge"),
    path("kopchilik/", feud_index, name="feud"),
    path("kopchilik/api/state/", api_feud_state, name="feud-api-state"),
    path("kopchilik/api/submit/", api_feud_submit, name="feud-api-submit"),
    path("qala/", castle_index, name="castle"),
    path("qala/api/state/", api_castle_state, name="castle-api-state"),
    path("qala/api/submit/", api_castle_submit, name="castle-api-submit"),
]
