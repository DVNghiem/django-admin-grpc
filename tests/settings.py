"""
Minimal Django settings for testing django-grpc-admin without a real database.
"""

SECRET_KEY = "test-secret-key-not-for-production"

DEBUG = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.messages",
    "django_grpc_admin",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
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
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

USE_TZ = True
TIME_ZONE = "UTC"

ROOT_URLCONF = "tests.urls"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Minimal logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {
        "null": {
            "class": "logging.NullHandler",
        },
    },
    "root": {
        "handlers": ["null"],
        "level": "WARNING",
    },
}

# gRPC admin settings
GRPC_ADMIN_TRACE_CONTEXT_PROVIDER = None
GRPC_ADMIN_DEFAULT_PAGE_SIZE = 25
GRPC_ADMIN_MAX_PAGE_SIZE = 100
GRPC_ADMIN_CURSOR_PAGINATION = False
GRPC_ADMIN_LOG_LEVEL = "INFO"
