from celery.schedules import crontab
import os
import hashlib
from pathlib import Path
from environs import Env
import dj_database_url
from django.utils.translation import gettext_lazy as _

env = Env()
if os.path.exists('.env'):
    env.read_env()

API_TOKEN = env.str('API_TOKEN')
SECRET_KEY = env.str('SECRET_KEY')
WEB_DOMAIN = env.str('WEB_DOMAIN')
DEBUG = env.bool('DEBUG')
ADMINS = env.list('ADMINS')
CHANNELS = env.list('CHANNELS')

WEBHOOK_PATH = 'tgbot/' + hashlib.md5(API_TOKEN.encode()).hexdigest()
WEBHOOK_URL = f"{WEB_DOMAIN}/{WEBHOOK_PATH}"

LANGUAGES = (
    ("uz", "O'zbekcha"),
    ("ru", "Русский"),
)

BASE_DIR = Path(__file__).resolve().parent.parent

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS')
# Application definition

INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'tgbot',

    ###
    "rest_framework",
    "drf_yasg",
    "corsheaders",
    "modeltranslation",
    "captcha",
    "ckeditor",
    'rosetta',
    "celery",
    "django_celery_beat",
    "import_export",
    "solo.apps.SoloAppConfig",
    'auditlog',
    'admin_reorder',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'admin_reorder.middleware.ModelAdminReorder',
]

ROOT_URLCONF = 'src.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'src.wsgi.application'

# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

if DEBUG:
    DATABASES = {
        # Postgresql
        "default": {
            "ENGINE": env.str("DB_ENGINE"),
            "NAME": env.str("DB_NAME"),
            "USER": env.str("DB_USER"),
            "PASSWORD": env.str("DB_PASS"),
            "HOST": env.str("DB_HOST"),
            "PORT": env.str("DB_PORT"),
        },
    }
else:
    # PG Bouncer Database
    DATABASES = {
        'default': dj_database_url.config(conn_max_age=600, ssl_require=False)
    }
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True

    # Security enhancements for production
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = 'ru'

TIME_ZONE = "Asia/Tashkent"

USE_I18N = True

USE_TZ = True

CELERY_TIMEZONE = 'Asia/Tashkent'

CELERY_ENABLE_UTC = False

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
# CSRF_COOKIE_SECURE = False
# CSRF_COOKIE_HTTPONLY = False

# Example Redis credentials
# In production, replace these with secure environment variables or a configuration file
REDIS_HOST = env.str("REDIS_HOST", "redis")
REDIS_PORT = env.int("REDIS_PORT", 6379)
REDIS_DB = env.int("REDIS_DB", 0)
REDIS_URL = f'{REDIS_HOST}://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}'

I18N_DOMAIN = "django"
LOCALES_DIR = BASE_DIR / "locale"
RECAPTCHA_PUBLIC_KEY = env.str(
    "RECAPTCHA_PUBLIC_KEY", "6LdlOWYpAAAAAOEsejvu7mT-tYr9PBmMlYbVio7R")
RECAPTCHA_PRIVATE_KEY = env.str(
    "RECAPTCHA_PRIVATE_KEY", "6LdlOWYpAAAAAP2nediVlYsjEXrFZpzH4DZlUarQ")

CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False


# Celery settings
CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

# CSRF settings
CORS_ALLOW_METHODS = [
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
]

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'authorizations',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

JAZZMIN_SETTINGS = {
    "hide_models": [
        "django_celery_beat.PeriodicTask",
        "django_celery_beat.CrontabSchedule",
        "django_celery_beat.IntervalSchedule",
        "django_celery_beat.SolarSchedule",
        "django_celery_beat.ClockedSchedule",
    ],
}

ADMIN_REORDER = (
    {
        'app': 'tgbot',
        'label': 'Foydalanuvchilar',
        'models': (
            'tgbot.TelegramProfile',
            'tgbot.UserReferal',
            'tgbot.Region',
        )
    },
    {
        'app': 'tgbot',
        'label': 'Guruhlar',
        'models': (
            'tgbot.Group',
            'tgbot.RequiredGroup',
        )
    },
{
        'app': 'tgbot',
        'label': 'Kitoblar (Books)',
        'models': (
            'tgbot.BooksToRead',
            'tgbot.ConfirmationReport',
        )
    },
    {
        'app': 'tgbot',
        'label': "To'lovlar",
        'models': (
            'tgbot.Payment',
        )
    },
    {
        'app': 'tgbot',
        'label': 'Bot Sozlamalari',
        'models': (
            'tgbot.TelegramBot',
            'tgbot.DailyMessage',
        )
    },
)
