import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-example-key-do-not-use-in-production"
DEBUG = True
ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "testserver"]

# Set only inside the `app` service in docker-compose.yml. The host venv
# (Q1-Q6 demos) never sets this and keeps using sqlite -- GDAL/GEOS, which
# django.contrib.gis needs to even import, is only installed inside that
# container (see Dockerfile), not on the host.
USE_POSTGIS = bool(os.environ.get("DJANGO_DB_HOST"))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_celery_results",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "payments",
]

if USE_POSTGIS:
    INSTALLED_APPS += ["django.contrib.gis", "fleet"]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

STATIC_URL = "static/"

ROOT_URLCONF = "config.urls"

if USE_POSTGIS:
    DATABASES = {
        "default": {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": os.environ["DJANGO_DB_NAME"],
            "USER": os.environ["DJANGO_DB_USER"],
            "PASSWORD": os.environ["DJANGO_DB_PASSWORD"],
            "HOST": os.environ["DJANGO_DB_HOST"],
            "PORT": os.environ.get("DJANGO_DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF / drf-spectacular --------------------------------------------------
# drf-yasg targets OpenAPI 2.0 (Swagger) and infers schema mostly from
# serializer introspection. drf-spectacular targets OpenAPI 3.0+, understands
# Python type hints natively, and lets you correct/extend what it infers via
# decorators (@extend_schema, @extend_schema_field) instead of fighting the
# auto-generated schema.
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Payments Demo API",
    "DESCRIPTION": "Wallet + idempotent event processing example.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- SimpleJWT ---------------------------------------------------------------
# ROTATE_REFRESH_TOKENS: every /api/token/refresh/ call issues a brand new
# refresh token alongside the new access token, instead of reusing the same
# refresh token for its whole lifetime.
# BLACKLIST_AFTER_ROTATION: the refresh token that was just used gets
# blacklisted immediately, so it cannot be replayed even once more. If it
# IS replayed (e.g. a stolen token racing the legitimate client), the
# request fails outright -- that failure is the signal a token was stolen.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# --- Celery / Redis --------------------------------------------------------
# DB 15 is used instead of the default DB 0 to avoid colliding with keys
# from any other app already using this Redis instance.
REDIS_URL = "redis://localhost:6379/15"

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = "django-db"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True  # redelivers the task if the worker dies mid-run
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_DEFAULT_RETRY_DELAY = 5
