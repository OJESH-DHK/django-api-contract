METADATA_KEY = "x-api-contract"

POSTMAN_SCHEMA_URL = (
    "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
)

# Namespace used to derive deterministic Postman ids via uuid5.
UUID_NAMESPACE = "django-api-contract"

HTTP_METHODS = (
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "trace",
)

METHOD_ORDER = {method: index for index, method in enumerate(HTTP_METHODS)}

BODY_METHODS = frozenset({"post", "put", "patch", "delete"})

JSON_MEDIA_TYPE = "application/json"
FORM_MEDIA_TYPE = "application/x-www-form-urlencoded"
MULTIPART_MEDIA_TYPE = "multipart/form-data"

SUPPORTED_BODY_MEDIA_TYPES = (
    JSON_MEDIA_TYPE,
    MULTIPART_MEDIA_TYPE,
    FORM_MEDIA_TYPE,
)

DEFAULT_BASE_URL_VARIABLE = "base_url"

# Placeholder values used when generating request examples. They must never
# resemble real credentials or customer data.
AUTH_VARIABLES = {
    "bearer": "access_token",
    "apiKey": "api_key",
    "basic": "basic_auth",
}

UNGROUPED_FOLDER = "Default"

# A rename is applied automatically at or above this score and only reported
# between RENAME_SIMILARITY_THRESHOLD and this value.
CONFIDENT_RENAME_SCORE = 0.9

ARCHIVED_SUFFIX = " [removed from API]"
