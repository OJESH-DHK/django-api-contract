from __future__ import annotations

from typing import Any

MAX_DEPTH = 6

# Deterministic, obviously fake placeholders. Nothing here may resemble a real
# credential or a real customer record.
STRING_FORMATS = {
    "email": "user@example.com",
    "uri": "https://example.com",
    "url": "https://example.com",
    "hostname": "example.com",
    "ipv4": "192.0.2.1",
    "ipv6": "2001:db8::1",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "date": "2024-01-01",
    "date-time": "2024-01-01T00:00:00Z",
    "time": "00:00:00",
    "duration": "P1D",
    "binary": "<file>",
    "password": "{{password}}",
    "slug": "example-slug",
    "decimal": "0.00",
}


def resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, dict) else None


def _merge_all_of(parts: list[Any], root: dict[str, Any], seen: set[str]) -> dict[str, Any]:
    merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    for part in parts:
        resolved = _deref(part, root, seen) or {}
        merged["properties"].update(resolved.get("properties") or {})
        merged["required"].extend(resolved.get("required") or [])
    merged["required"] = sorted(set(merged["required"]))
    return merged


def _deref(node: Any, root: dict[str, Any], seen: set[str]) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return None
        seen = seen | {ref}
        return _deref(resolve_ref(root, ref), root, seen)
    return node


def example_for(
    node: Any,
    root: dict[str, Any],
    *,
    for_request: bool = True,
    depth: int = 0,
    seen: set[str] | None = None,
) -> Any:
    """Build a deterministic example value for an OpenAPI schema node."""
    seen = seen or set()
    if depth > MAX_DEPTH:
        return None

    if isinstance(node, dict) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        if ref in seen:
            return None
        return example_for(
            resolve_ref(root, ref),
            root,
            for_request=for_request,
            depth=depth,
            seen=seen | {ref},
        )

    if not isinstance(node, dict):
        return None

    if "example" in node:
        return node["example"]
    if "default" in node:
        return node["default"]
    if node.get("enum"):
        return node["enum"][0]

    for combinator in ("oneOf", "anyOf"):
        if isinstance(node.get(combinator), list) and node[combinator]:
            return example_for(
                node[combinator][0],
                root,
                for_request=for_request,
                depth=depth + 1,
                seen=seen,
            )

    if isinstance(node.get("allOf"), list) and node["allOf"]:
        node = _merge_all_of(node["allOf"], root, seen)

    node_type = node.get("type")
    if isinstance(node_type, list):
        node_type = next((t for t in node_type if t != "null"), None)

    if node_type == "array":
        item = example_for(
            node.get("items") or {},
            root,
            for_request=for_request,
            depth=depth + 1,
            seen=seen,
        )
        return [] if item is None else [item]

    if node_type == "object" or "properties" in node:
        return _object_example(node, root, for_request=for_request, depth=depth, seen=seen)

    if node_type == "integer":
        return node.get("minimum", 0) or 0
    if node_type == "number":
        return float(node.get("minimum", 0) or 0)
    if node_type == "boolean":
        return False
    if node_type == "null":
        return None

    return _string_example(node)


def _string_example(node: dict[str, Any]) -> str:
    fmt = node.get("format")
    if fmt in STRING_FORMATS:
        return STRING_FORMATS[fmt]
    if node.get("pattern"):
        return "string"
    return "string"


def _object_example(
    node: dict[str, Any],
    root: dict[str, Any],
    *,
    for_request: bool,
    depth: int,
    seen: set[str],
) -> dict[str, Any]:
    properties = node.get("properties")
    if not isinstance(properties, dict):
        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            value = example_for(
                additional, root, for_request=for_request, depth=depth + 1, seen=seen
            )
            return {"key": value}
        return {}

    result: dict[str, Any] = {}
    for name in sorted(properties):
        prop = properties[name]
        resolved = _deref(prop, root, seen) or {}
        if for_request and resolved.get("readOnly"):
            continue
        if not for_request and resolved.get("writeOnly"):
            continue
        result[name] = example_for(prop, root, for_request=for_request, depth=depth + 1, seen=seen)
    return result


def flatten_form_fields(
    node: Any, root: dict[str, Any], *, multipart: bool = False
) -> list[dict[str, Any]]:
    """Turn an object schema into Postman formdata / urlencoded entries.

    In a multipart body a ``uri`` formatted string is also treated as a file:
    drf-spectacular renders DRF ``FileField`` that way unless
    ``COMPONENT_SPLIT_REQUEST`` is enabled.
    """
    resolved = _deref(node, root, set()) or {}
    if isinstance(resolved.get("allOf"), list) and resolved["allOf"]:
        resolved = _merge_all_of(resolved["allOf"], root, set())

    properties = resolved.get("properties")
    if not isinstance(properties, dict):
        return []

    required = set(resolved.get("required") or [])
    fields: list[dict[str, Any]] = []
    for name in sorted(properties):
        prop = _deref(properties[name], root, set()) or {}
        if prop.get("readOnly"):
            continue
        file_formats = {"binary", "uri"} if multipart else {"binary"}
        item_schema = _deref(prop.get("items"), root, set()) or {}
        is_file = prop.get("format") in file_formats or (
            prop.get("type") == "array" and item_schema.get("format") in file_formats
        )
        entry: dict[str, Any] = {"key": name, "type": "file" if is_file else "text"}
        if is_file:
            entry["src"] = []
        else:
            value = example_for(properties[name], root, for_request=True)
            entry["value"] = "" if value is None else _as_text(value)
        if prop.get("description"):
            entry["description"] = str(prop["description"])
        if name not in required:
            entry["disabled"] = True
        fields.append(entry)
    return fields


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)
