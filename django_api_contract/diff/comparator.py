from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ..constants import JSON_MEDIA_TYPE
from ..postman.examples import resolve_ref
from ..postman.identity import identity_string
from ..schema.normalizer import iter_operations
from .models import Change, ChangeKind, ContractDiff, Severity

MAX_DEPTH = 6


def _deref(node: Any, root: Dict[str, Any], seen: Set[str]) -> Dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return {}
        return _deref(resolve_ref(root, ref) or {}, root, seen | {ref})
    if isinstance(node.get("allOf"), list):
        merged: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for part in node["allOf"]:
            resolved = _deref(part, root, seen)
            merged["properties"].update(resolved.get("properties") or {})
            merged["required"].extend(resolved.get("required") or [])
        for key, value in node.items():
            if key != "allOf":
                merged[key] = value
        return merged
    return node


class FieldInfo(dict):
    """Flat description of one field, comparable between two schema versions."""


def _type_of(node: Dict[str, Any]) -> str:
    node_type = node.get("type")
    if isinstance(node_type, list):
        non_null = [t for t in node_type if t != "null"]
        return non_null[0] if non_null else "null"
    if node_type:
        return str(node_type)
    if "properties" in node:
        return "object"
    if node.get("oneOf") or node.get("anyOf"):
        return "union"
    return "unknown"


def flatten_fields(
    node: Any,
    root: Dict[str, Any],
    *,
    prefix: str = "",
    required: bool = False,
    depth: int = 0,
    seen: Optional[Set[str]] = None,
) -> Dict[str, FieldInfo]:
    """Flatten a schema into ``{dotted.name: descriptor}``.

    Arrays are marked with ``[]`` so that a list of objects still exposes its
    members for comparison.
    """
    seen = seen or set()
    resolved = _deref(node, root, seen)
    if not resolved or depth > MAX_DEPTH:
        return {}

    fields: Dict[str, FieldInfo] = {}
    node_type = _type_of(resolved)

    if node_type == "array":
        return flatten_fields(
            resolved.get("items") or {},
            root,
            prefix=f"{prefix}[]" if prefix else "[]",
            required=required,
            depth=depth + 1,
            seen=seen,
        )

    properties = resolved.get("properties")
    if isinstance(properties, dict):
        required_names = set(resolved.get("required") or [])
        for name in sorted(properties):
            child = _deref(properties[name], root, seen)
            path = f"{prefix}.{name}" if prefix else name
            fields[path] = FieldInfo(
                type=_type_of(child),
                required=name in required_names,
                nullable=bool(child.get("nullable")) or "null" in (child.get("type") or []),
                enum=tuple(child.get("enum")) if isinstance(child.get("enum"), list) else None,
                format=child.get("format"),
                read_only=bool(child.get("readOnly")),
                write_only=bool(child.get("writeOnly")),
            )
            if _type_of(child) in {"object", "array"}:
                fields.update(
                    flatten_fields(
                        properties[name],
                        root,
                        prefix=path,
                        required=name in required_names,
                        depth=depth + 1,
                        seen=seen,
                    )
                )
    return fields


def _body_schema(operation: Dict[str, Any], root: Dict[str, Any]) -> Any:
    body = operation.get("requestBody")
    if isinstance(body, dict) and "$ref" in body:
        body = resolve_ref(root, body["$ref"]) or {}
    if not isinstance(body, dict):
        return None
    content = body.get("content")
    if not isinstance(content, dict) or not content:
        return None
    media_type = JSON_MEDIA_TYPE if JSON_MEDIA_TYPE in content else sorted(content)[0]
    return (content.get(media_type) or {}).get("schema")


def _response_schema(operation: Dict[str, Any], root: Dict[str, Any]) -> Tuple[Optional[str], Any]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None, None
    for status in sorted(responses):
        if not status.startswith("2"):
            continue
        content = (responses[status] or {}).get("content")
        if isinstance(content, dict) and content:
            media_type = JSON_MEDIA_TYPE if JSON_MEDIA_TYPE in content else sorted(content)[0]
            return status, (content.get(media_type) or {}).get("schema")
    return None, None


def _parameters(operation: Dict[str, Any], root: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for parameter in operation.get("parameters") or []:
        if not isinstance(parameter, dict):
            continue
        if "$ref" in parameter:
            parameter = resolve_ref(root, parameter["$ref"]) or {}
        name = parameter.get("name")
        location = parameter.get("in")
        if name and location:
            result[f"{location}:{name}"] = parameter
    return result


def _compare_fields(
    endpoint: str,
    label: str,
    old_fields: Dict[str, FieldInfo],
    new_fields: Dict[str, FieldInfo],
    *,
    is_request: bool,
) -> List[Change]:
    changes: List[Change] = []

    for name in sorted(set(new_fields) - set(old_fields)):
        info = new_fields[name]
        if is_request and info.get("required"):
            severity = Severity.BREAKING
            detail = f"{label} field {name} added as required"
        else:
            severity = Severity.NON_BREAKING
            detail = f"{label} field {name} added"
        changes.append(Change(ChangeKind.CHANGED, severity, endpoint, detail))

    for name in sorted(set(old_fields) - set(new_fields)):
        severity = Severity.NON_BREAKING if is_request else Severity.BREAKING
        detail = f"{label} field {name} removed"
        if is_request and old_fields[name].get("required"):
            severity = Severity.POSSIBLY_BREAKING
        changes.append(Change(ChangeKind.CHANGED, severity, endpoint, detail))

    for name in sorted(set(old_fields) & set(new_fields)):
        old, new = old_fields[name], new_fields[name]

        if old.get("type") != new.get("type"):
            changes.append(
                Change(
                    ChangeKind.CHANGED,
                    Severity.BREAKING,
                    endpoint,
                    f"{label} field {name} type",
                    str(old.get("type")),
                    str(new.get("type")),
                )
            )

        if is_request and not old.get("required") and new.get("required"):
            changes.append(
                Change(
                    ChangeKind.CHANGED,
                    Severity.BREAKING,
                    endpoint,
                    f"{label} field {name} changed from optional to required",
                )
            )
        elif is_request and old.get("required") and not new.get("required"):
            changes.append(
                Change(
                    ChangeKind.CHANGED,
                    Severity.NON_BREAKING,
                    endpoint,
                    f"{label} field {name} changed from required to optional",
                )
            )

        if old.get("nullable") and not new.get("nullable"):
            severity = Severity.BREAKING if not is_request else Severity.POSSIBLY_BREAKING
            changes.append(
                Change(
                    ChangeKind.CHANGED,
                    severity,
                    endpoint,
                    f"{label} field {name} is no longer nullable",
                )
            )

        old_enum, new_enum = old.get("enum"), new.get("enum")
        if old_enum and new_enum and old_enum != new_enum:
            dropped = sorted(set(old_enum) - set(new_enum), key=str)
            added = sorted(set(new_enum) - set(old_enum), key=str)
            if dropped:
                changes.append(
                    Change(
                        ChangeKind.CHANGED,
                        Severity.BREAKING,
                        endpoint,
                        f"{label} field {name} dropped enum value(s) "
                        + ", ".join(str(value) for value in dropped),
                    )
                )
            if added:
                severity = Severity.NON_BREAKING if is_request else Severity.POSSIBLY_BREAKING
                changes.append(
                    Change(
                        ChangeKind.CHANGED,
                        severity,
                        endpoint,
                        f"{label} field {name} added enum value(s) "
                        + ", ".join(str(value) for value in added),
                    )
                )

    return changes


def _compare_parameters(
    endpoint: str,
    old_operation: Dict[str, Any],
    new_operation: Dict[str, Any],
    old_root: Dict[str, Any],
    new_root: Dict[str, Any],
) -> List[Change]:
    changes: List[Change] = []
    old_params = _parameters(old_operation, old_root)
    new_params = _parameters(new_operation, new_root)

    for key in sorted(set(new_params) - set(old_params)):
        parameter = new_params[key]
        required = bool(parameter.get("required"))
        severity = Severity.BREAKING if required else Severity.NON_BREAKING
        changes.append(
            Change(ChangeKind.CHANGED, severity, endpoint, f"parameter {key} added"
                   + (" as required" if required else ""))
        )

    for key in sorted(set(old_params) - set(new_params)):
        location = key.split(":", 1)[0]
        severity = Severity.BREAKING if location == "path" else Severity.POSSIBLY_BREAKING
        changes.append(
            Change(ChangeKind.CHANGED, severity, endpoint, f"parameter {key} removed")
        )

    for key in sorted(set(old_params) & set(new_params)):
        old_type = _type_of(_deref(old_params[key].get("schema") or {}, old_root, set()))
        new_type = _type_of(_deref(new_params[key].get("schema") or {}, new_root, set()))
        if old_type != new_type:
            changes.append(
                Change(
                    ChangeKind.CHANGED,
                    Severity.BREAKING,
                    endpoint,
                    f"parameter {key} type",
                    old_type,
                    new_type,
                )
            )
        if not old_params[key].get("required") and new_params[key].get("required"):
            changes.append(
                Change(
                    ChangeKind.CHANGED,
                    Severity.BREAKING,
                    endpoint,
                    f"parameter {key} changed from optional to required",
                )
            )

    return changes


def _security_signature(operation: Dict[str, Any], root: Dict[str, Any]) -> str:
    security = operation.get("security")
    if security is None:
        security = root.get("security")
    if not isinstance(security, list):
        return "inherited"
    names = sorted(
        name for requirement in security if isinstance(requirement, dict) for name in requirement
    )
    return ", ".join(names) if names else "none"


def compare_schemas(old: Dict[str, Any], new: Dict[str, Any]) -> ContractDiff:
    """Report what changed between two OpenAPI documents, endpoint by endpoint."""
    diff = ContractDiff()

    old_ops = {
        identity_string(method, path): operation for path, method, operation in iter_operations(old)
    }
    new_ops = {
        identity_string(method, path): operation for path, method, operation in iter_operations(new)
    }

    for endpoint in sorted(set(new_ops) - set(old_ops)):
        diff.add(Change(ChangeKind.ADDED, Severity.NON_BREAKING, endpoint))

    for endpoint in sorted(set(old_ops) - set(new_ops)):
        diff.add(Change(ChangeKind.REMOVED, Severity.BREAKING, endpoint))

    for endpoint in sorted(set(old_ops) & set(new_ops)):
        old_operation, new_operation = old_ops[endpoint], new_ops[endpoint]

        diff.extend(_compare_parameters(endpoint, old_operation, new_operation, old, new))

        old_body = flatten_fields(_body_schema(old_operation, old) or {}, old)
        new_body = flatten_fields(_body_schema(new_operation, new) or {}, new)
        if old_body or new_body:
            diff.extend(
                _compare_fields(endpoint, "request", old_body, new_body, is_request=True)
            )

        old_status, old_response = _response_schema(old_operation, old)
        new_status, new_response = _response_schema(new_operation, new)
        if old_status != new_status and old_status and new_status:
            diff.add(
                Change(
                    ChangeKind.CHANGED,
                    Severity.POSSIBLY_BREAKING,
                    endpoint,
                    "success status code",
                    old_status,
                    new_status,
                )
            )
        old_response_fields = flatten_fields(old_response or {}, old)
        new_response_fields = flatten_fields(new_response or {}, new)
        if old_response_fields or new_response_fields:
            diff.extend(
                _compare_fields(
                    endpoint, "response", old_response_fields, new_response_fields,
                    is_request=False,
                )
            )

        old_security = _security_signature(old_operation, old)
        new_security = _security_signature(new_operation, new)
        if old_security != new_security:
            diff.add(
                Change(
                    ChangeKind.CHANGED,
                    Severity.BREAKING,
                    endpoint,
                    "authentication",
                    old_security,
                    new_security,
                )
            )

    return diff
