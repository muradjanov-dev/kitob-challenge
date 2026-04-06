from django.urls import path
from .views import home, telegram
from src.settings import WEBHOOK_PATH
from tgbot.views import health_check_celery, health_check_redis


urlpatterns = [
    path('', home, name='home'),
    path(WEBHOOK_PATH, telegram, name='webhook'),
    path("health-check/redis/", health_check_redis, name="health-check-redis"),
    path("health-check/celery/", health_check_celery, name="health-check-celery"),
]
