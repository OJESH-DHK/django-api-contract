from __future__ import annotations

from typing import Any, Dict, List

from ..constants import HTTP_METHODS
from ..utils import method_sort_key, normalize_path

TOP_LEVEL_ORDER = (
    "openapi",
    "info",
    "servers",
    "security",
    "tags",
    "paths",
    "webhooks",
    "components",
    "externalDocs",
)

OPERATION_ORDER = (
    "operationId",
    "summary",
    "description",
    "tags",
    "deprecated",
    "parameters",
    "requestBody",
    "responses",
    "security",
    "callbacks",
    "servers",
    "externalDocs",
)

COMPONENT_ORDER = (
    "schemas",
    "responses",
    "parameters",
    "examples",
    "requestBodies",
    "headers",
    "securitySchemes",
    "links",
    "callbacks",
)


def _ordered(data: Dict[str, Any], preferred: tuple) -> Dict[str, Any]:
    """Reorder mapping keys: preferred ones first, remainder sorted."""
    result: Dict[str, Any] = {}
    for key in preferred:
        if key in data:
            result[key] = data[key]
    for key in sorted(data):
        if key not in result:
            result[key] = data[key]
    return result


def _parameter_key(parameter: Dict[str, Any]) -> tuple:
    location_rank = {"path": 0, "query": 1, "header": 2, "cookie": 3}
    return (
        location_rank.get(parameter.get("in", ""), 9),
        str(parameter.get("name", "")),
        str(parameter.get("$ref", "")),
    )


def _normalize_operation(operation: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(operation)

    parameters = normalized.get("parameters")
    if isinstance(parameters, list):
        normalized["parameters"] = sorted(
            (p for p in parameters if isinstance(p, dict)), key=_parameter_key
        )

    tags = normalized.get("tags")
    if isinstance(tags, list):
        normalized["tags"] = sorted(str(tag) for tag in tags)

    responses = normalized.get("responses")
    if isinstance(responses, dict):
        normalized["responses"] = {key: responses[key] for key in sorted(responses)}

    return _ordered(normalized, OPERATION_ORDER)


def _normalize_path_item(path_item: Dict[str, Any]) -> Dict[str, Any]:
    methods = [key for key in path_item if key.lower() in HTTP_METHODS]
    others = sorted(key for key in path_item if key not in methods)

    normalized: Dict[str, Any] = {}
    for key in others:
        normalized[key] = path_item[key]
    for method in sorted(methods, key=method_sort_key):
        value = path_item[method]
        normalized[method] = (
            _normalize_operation(value) if isinstance(value, dict) else value
        )
    return normalized


def _normalize_schema_object(value: Any) -> Any:
    """Sort structural lists inside component schemas.

    ``required`` is a set in OpenAPI terms, so ordering it removes diff noise.
    ``enum`` is left untouched because its order is meaningful to readers.
    """
    if isinstance(value, dict):
        result = {}
        for key in sorted(value):
            item = value[key]
            if key == "required" and isinstance(item, list):
                result[key] = sorted(str(entry) for entry in item)
            else:
                result[key] = _normalize_schema_object(item)
        return result
    if isinstance(value, list):
        return [_normalize_schema_object(item) for item in value]
    return value


def normalize_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return a byte-stable version of ``schema``.

    Two runs over an unchanged API must produce identical files, otherwise the
    generated artifacts create meaningless git diffs.
    """
    normalized = dict(schema)

    paths = normalized.get("paths")
    if isinstance(paths, dict):
        rebuilt: Dict[str, Any] = {}
        for raw_path in sorted(paths, key=normalize_path):
            item = paths[raw_path]
            rebuilt[normalize_path(raw_path)] = (
                _normalize_path_item(item) if isinstance(item, dict) else item
            )
        normalized["paths"] = rebuilt

    components = normalized.get("components")
    if isinstance(components, dict):
        rebuilt_components: Dict[str, Any] = {}
        for section in COMPONENT_ORDER:
            if section in components and isinstance(components[section], dict):
                rebuilt_components[section] = {
                    name: _normalize_schema_object(components[section][name])
                    for name in sorted(components[section])
                }
        for section in sorted(components):
            if section not in rebuilt_components:
                rebuilt_components[section] = _normalize_schema_object(components[section])
        normalized["components"] = rebuilt_components

    tags = normalized.get("tags")
    if isinstance(tags, list):
        normalized["tags"] = sorted(
            (tag for tag in tags if isinstance(tag, dict)),
            key=lambda tag: str(tag.get("name", "")),
        )

    return _ordered(normalized, TOP_LEVEL_ORDER)


def iter_operations(schema: Dict[str, Any]) -> List[tuple]:
    """Yield ``(path, method, operation)`` triples in deterministic order."""
    results = []
    for path, item in (schema.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                results.append((path, method.lower(), operation))
    results.sort(key=lambda entry: (entry[0], method_sort_key(entry[1])))
    return results
