from django.urls import path
from .views import home, telegram
from src.settings import WEBHOOK_PATH
from tgbot.views import health_check_celery, health_check_redis
from tgbot.shop_views import shop_index, api_products, api_me, api_buy


urlpatterns = [
    path('', home, name='home'),
    path(WEBHOOK_PATH, telegram, name='webhook'),
    path("health-check/redis/", health_check_redis, name="health-check-redis"),
    path("health-check/celery/", health_check_celery, name="health-check-celery"),
    path("shop/", shop_index, name="shop"),
    path("shop/api/products/", api_products, name="shop-api-products"),
    path("shop/api/me/", api_me, name="shop-api-me"),
    path("shop/api/buy/", api_buy, name="shop-api-buy"),
]
