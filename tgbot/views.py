from django.shortcuts import render
from asgiref.sync import async_to_sync
from .webhook import proceed_update
from django.http import HttpResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import redis
from celery import Celery
from celery.exceptions import OperationalError


def home(request: HttpRequest):
    return HttpResponse('Hello world')

@csrf_exempt
def telegram(request: HttpRequest):
    # if request.method == 'post':
    try:
        async_to_sync(proceed_update)(request)
    except Exception as e:
        print(e)
    return HttpResponse()
    # else:
    #     return HttpResponse(status=403)
    

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
        # Check Redis connection
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
        # Ping Celery workers
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
