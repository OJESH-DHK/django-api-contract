import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = "api-contract-test-key"
DEBUG = False
USE_TZ = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "drf_spectacular",
    "django_api_contract",
    "tests.demo",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

ROOT_URLCONF = "tests.demo.urls"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Demo API",
    "DESCRIPTION": "Fixture API used by the test suite.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

API_CONTRACT = {
    "OPENAPI_OUTPUT": "artifacts/openapi.json",
    "POSTMAN_OUTPUT": "artifacts/postman_collection.json",
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
