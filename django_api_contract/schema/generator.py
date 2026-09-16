from __future__ import annotations

from typing import Any, Dict, Optional

from django.utils.module_loading import import_string

from ..conf import ContractSettings, contract_settings
from ..exceptions import SchemaGenerationError


def _load_generator_class(dotted_path: str):
    try:
        return import_string(dotted_path)
    except ImportError as exc:  # pragma: no cover - configuration error path
        raise SchemaGenerationError(
            f"Could not import SCHEMA_GENERATOR_CLASS {dotted_path!r}: {exc}"
        ) from exc


def generate_schema(settings: Optional[ContractSettings] = None) -> Dict[str, Any]:
    """Build the OpenAPI document for the project's DRF routes.

    Everything here comes from the installed URLconf and the serializers it
    reaches, so the API code stays the single source of truth.
    """
    settings = settings or contract_settings
    generator_class = _load_generator_class(settings.SCHEMA_GENERATOR_CLASS)

    kwargs: Dict[str, Any] = {}
    if settings.URLCONF:
        kwargs["urlconf"] = settings.URLCONF

    try:
        generator = generator_class(**kwargs)
        schema = generator.get_schema(request=None, public=True)
    except Exception as exc:
        raise SchemaGenerationError(f"OpenAPI generation failed: {exc}") from exc

    if not isinstance(schema, dict):
        raise SchemaGenerationError(
            f"Schema generator returned {type(schema).__name__}, expected a mapping"
        )

    schema = _as_plain_json(schema)

    if settings.SERVERS is not None:
        schema["servers"] = settings.SERVERS

    return schema


def _as_plain_json(value: Any) -> Any:
    """Convert OrderedDict/tuple structures into plain JSON containers.

    drf-spectacular returns ordered mappings and occasionally tuples; the rest
    of the pipeline compares and serializes plain dicts and lists.
    """
    if isinstance(value, dict):
        return {str(key): _as_plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_plain_json(item) for item in value]
    return value
