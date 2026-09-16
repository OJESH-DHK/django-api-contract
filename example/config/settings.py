from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "example-project-key-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "django_api_contract",
    "catalog",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Catalog API",
    "DESCRIPTION": "Example API showing django-api-contract in use.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

API_CONTRACT = {
    "OPENAPI_OUTPUT": "api-contract/openapi.json",
    "POSTMAN_OUTPUT": "api-contract/postman_collection.json",
    "SERVERS": [{"url": "http://localhost:8000", "description": "Local development"}],
}

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
