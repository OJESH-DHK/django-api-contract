from __future__ import annotations

import os
from typing import Any, Dict

from django.conf import settings as django_settings

from .constants import DEFAULT_BASE_URL_VARIABLE
from .exceptions import ConfigurationError

SETTINGS_KEY = "API_CONTRACT"

DEFAULTS: Dict[str, Any] = {
    # Output locations, relative to BASE_DIR unless absolute.
    "OPENAPI_OUTPUT": "api-contract/openapi.json",
    "POSTMAN_OUTPUT": "api-contract/postman_collection.json",
    # Collection identity. When omitted both are derived from the schema title
    # so that repeated runs stay deterministic.
    "POSTMAN_COLLECTION_ID": None,
    "POSTMAN_COLLECTION_NAME": None,
    "POSTMAN_COLLECTION_DESCRIPTION": None,
    # Synchronization behaviour.
    "PRESERVE_MANUAL_REQUESTS": True,
    "REMOVE_DELETED_ENDPOINTS": False,
    "ARCHIVE_DELETED_ENDPOINTS": True,
    "PRESERVE_RESPONSE_EXAMPLES": True,
    "DETECT_RENAMES": True,
    "RENAME_SIMILARITY_THRESHOLD": 0.7,
    # Compatibility checking.
    "FAIL_ON_BREAKING_CHANGE": True,
    # Schema generation.
    "URLCONF": None,
    "SERVERS": None,
    "SCHEMA_GENERATOR_CLASS": "drf_spectacular.generators.SchemaGenerator",
    # Formatting.
    "BASE_URL_VARIABLE": DEFAULT_BASE_URL_VARIABLE,
    "INDENT": 2,
}

BOOLEAN_KEYS = frozenset(
    {
        "PRESERVE_MANUAL_REQUESTS",
        "REMOVE_DELETED_ENDPOINTS",
        "ARCHIVE_DELETED_ENDPOINTS",
        "PRESERVE_RESPONSE_EXAMPLES",
        "DETECT_RENAMES",
        "FAIL_ON_BREAKING_CHANGE",
    }
)


class ContractSettings:
    """Read-only view over ``settings.API_CONTRACT`` with defaults applied."""

    def __init__(self, overrides: Dict[str, Any] | None = None):
        self._overrides = dict(overrides or {})

    @property
    def _user_settings(self) -> Dict[str, Any]:
        configured = getattr(django_settings, SETTINGS_KEY, {}) or {}
        if not isinstance(configured, dict):
            raise ConfigurationError(f"settings.{SETTINGS_KEY} must be a dict")
        merged = dict(configured)
        merged.update(self._overrides)
        return merged

    def __getattr__(self, name: str) -> Any:
        if name not in DEFAULTS:
            raise AttributeError(f"Unknown API_CONTRACT setting: {name}")
        value = self._user_settings.get(name, DEFAULTS[name])
        if name in BOOLEAN_KEYS:
            return bool(value)
        return value

    def with_overrides(self, **overrides: Any) -> ContractSettings:
        merged = dict(self._overrides)
        merged.update({k: v for k, v in overrides.items() if v is not None})
        return ContractSettings(merged)

    @property
    def base_dir(self) -> str:
        base = getattr(django_settings, "BASE_DIR", None)
        return str(base) if base else os.getcwd()

    def resolve_path(self, value: str) -> str:
        if os.path.isabs(value):
            return value
        return os.path.join(self.base_dir, value)

    @property
    def openapi_path(self) -> str:
        return self.resolve_path(self.OPENAPI_OUTPUT)

    @property
    def postman_path(self) -> str:
        return self.resolve_path(self.POSTMAN_OUTPUT)

    def as_dict(self) -> Dict[str, Any]:
        return {key: getattr(self, key) for key in DEFAULTS}


contract_settings = ContractSettings()
