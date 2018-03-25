"""Django settings for EventHub.

Everything environment-specific is read from environment variables so the same
settings module works for local development, tests, CI and containers:

* ``DATABASE_URL`` - any dj-database-url DSN. Falls back to a local SQLite file
  when unset, which keeps the test suite runnable without PostgreSQL.
* ``CELERY_BROKER_URL`` - Redis DSN. When unset, tasks run eagerly in-process.
* ``EMAIL_URL``-style settings are deliberately kept simple: ``EMAIL_BACKEND``
  plus the usual SMTP variables.
"""

from datetime import timedelta
from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from django.core.management.utils import get_random_secret_key

from .env import env, env_bool, env_int, env_list

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = env_bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env("DJANGO_SECRET_KEY", default="") or (
    "dev-insecure-" + get_random_secret_key() if DEBUG else ""
)
if not SECRET_KEY:
    # Stable fallback so `manage.py check` and tests work out of the box; never
    # used when DJANGO_SECRET_KEY is provided (as it is in docker-compose).
    SECRET_KEY = "insecure-local-key-change-me"  # noqa: S105

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "events",
    "ticketing",
    "checkin",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=env_int("DB_CONN_MAX_AGE", default=60),
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": env(
            "STATICFILES_BACKEND",
            default="django.contrib.staticfiles.storage.StaticFilesStorage",
        )
    },
}

LOGIN_URL = "admin:login"

# --- Django REST Framework -------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticatedOrReadOnly"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": env("API_ANON_THROTTLE", default="120/minute")},
}

# --- Email -----------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env_int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="EventHub <tickets@eventhub.local>")

# --- Celery ----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="") or None
# Without a broker we run tasks inline; this is what tests and quick local
# runs rely on.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", default=not CELERY_BROKER_URL)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "send-event-reminders": {
        "task": "ticketing.tasks.send_event_reminders",
        "schedule": crontab(minute="*/15"),
    },
}

# --- Domain settings -------------------------------------------------------
EVENTHUB = {
    # How far ahead of an event attendees get their reminder email.
    "REMINDER_LEAD_TIME": timedelta(hours=env_int("REMINDER_LEAD_HOURS", default=24)),
    # Check-in tokens stay valid this long after the event ends.
    "CHECKIN_TOKEN_GRACE": timedelta(days=1),
    # Hard cap on tickets per order to stop one buyer draining a tier.
    "MAX_TICKETS_PER_ORDER": env_int("MAX_TICKETS_PER_ORDER", default=10),
    "SITE_URL": env("SITE_URL", default="http://localhost:8000"),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("SECURE_COOKIES", default=False)
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
