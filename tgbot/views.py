import asyncio
import threading
import time
import traceback

from django.db import close_old_connections
from django.shortcuts import render
from .webhook import proceed_update_from_body
from django.http import HttpResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import redis
from celery import Celery
from celery.exceptions import OperationalError


# Persistent background event loop. aioredis (used by aiogram RedisStorage2)
# holds connections tied to whatever loop they were created in. If we spin up
# a fresh loop per request via async_to_sync, the next request hits the old
# loop's connections and dies with "Event loop is closed". One forever-running
# loop in a daemon thread keeps Redis connections healthy.
_bot_loop = asyncio.new_event_loop()


def _run_loop_forever():
    asyncio.set_event_loop(_bot_loop)
    _bot_loop.run_forever()


threading.Thread(target=_run_loop_forever, daemon=True, name="bot-loop").start()


async def _process_with_cleanup(body_bytes: bytes) -> None:
    start = time.monotonic()
    try:
        await proceed_update_from_body(body_bytes)
    except Exception:
        print("webhook bg error:\n" + traceback.format_exc())
    finally:
        close_old_connections()
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if elapsed_ms > 500:
            print(f"webhook handler took {elapsed_ms} ms")


def home(request: HttpRequest):
    return render(request, 'site/index.html')


@csrf_exempt
def telegram(request: HttpRequest):
    body = request.body
    asyncio.run_coroutine_threadsafe(_process_with_cleanup(body), _bot_loop)
    return HttpResponse(status=200)


app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Configure Redis connection
redis_client = redis.StrictRedis(
    host="redis",
    port="6379",
    db=0,
)


@api_view(["GET"])
def health_check_redis(request):
    try:
        redis_client.ping()
        return Response({"status": "success"}, status=status.HTTP_200_OK)
    except redis.ConnectionError:
        return Response(
            {"status": "error", "message": "Redis server is not working."},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
def health_check_celery(request):
    try:
        response = app.control.ping()
        if response:
            return Response(
                {"status": "success", "workers": response}, status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"status": "error", "message": "No Celery workers responded."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    except OperationalError:
        return Response(
            {"status": "error", "message": "Celery OperationalError occurred."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
