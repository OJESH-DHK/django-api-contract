from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ..constants import HTTP_METHODS
from ..exceptions import SchemaValidationError

_PATH_PARAM_RE = re.compile(r"\{([^}]*)\}")


def _collect_refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            found.add(ref)
        for value in node.values():
            _collect_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_refs(value, found)


def _resolve_ref(schema: dict[str, Any], ref: str) -> bool:
    if not ref.startswith("#/"):
        # External documents are out of scope; assume the author knows best.
        return True
    node: Any = schema
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return True


def _operation_problems(path: str, method: str, operation: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    label = f"{method.upper()} {path}"

    responses = operation.get("responses")
    if not isinstance(responses, dict) or not responses:
        problems.append(f"{label}: no responses documented")

    declared = {
        parameter.get("name")
        for parameter in operation.get("parameters", [])
        if isinstance(parameter, dict) and parameter.get("in") == "path"
    }
    for name in _PATH_PARAM_RE.findall(path):
        if not name:
            problems.append(f"{label}: empty path parameter placeholder")
        elif name not in declared:
            problems.append(f"{label}: path parameter {{{name}}} is not declared")

    for parameter in operation.get("parameters", []):
        if not isinstance(parameter, dict) or "$ref" in parameter:
            continue
        if parameter.get("in") == "path" and parameter.get("required") is not True:
            problems.append(f"{label}: path parameter {parameter.get('name')!r} must be required")

    return problems


def collect_problems(schema: dict[str, Any]) -> list[str]:
    problems: list[str] = []

    version = schema.get("openapi")
    if not isinstance(version, str) or not version.startswith("3."):
        problems.append(f"unsupported openapi version: {version!r}")

    info = schema.get("info")
    if not isinstance(info, dict):
        problems.append("info object is missing")
    else:
        for field in ("title", "version"):
            if not info.get(field):
                problems.append(f"info.{field} is missing")

    paths = schema.get("paths")
    if not isinstance(paths, dict):
        problems.append("paths object is missing")
        return problems

    seen_operation_ids: dict[str, str] = {}
    for path, item in paths.items():
        if not path.startswith("/"):
            problems.append(f"path {path!r} must start with '/'")
        if not isinstance(item, dict):
            problems.append(f"path {path!r} is not an object")
            continue
        for method, operation in item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                problems.append(f"{method.upper()} {path}: operation is not an object")
                continue
            problems.extend(_operation_problems(path, method, operation))

            operation_id = operation.get("operationId")
            if isinstance(operation_id, str) and operation_id:
                label = f"{method.upper()} {path}"
                if operation_id in seen_operation_ids:
                    problems.append(
                        f"duplicate operationId {operation_id!r} "
                        f"({seen_operation_ids[operation_id]} and {label})"
                    )
                else:
                    seen_operation_ids[operation_id] = label

    refs: set[str] = set()
    _collect_refs(schema, refs)
    for ref in sorted(refs):
        if not _resolve_ref(schema, ref):
            problems.append(f"unresolved reference: {ref}")

    return problems


def validate_schema(schema: dict[str, Any], strict: bool = True) -> list[str]:
    """Check the document and raise when it is structurally unusable.

    This is a targeted structural check rather than a full JSON Schema
    validation: it catches the failures that actually break downstream Postman
    generation without adding a validation dependency.
    """
    problems = collect_problems(schema)
    if problems and strict:
        raise SchemaValidationError(
            f"OpenAPI schema failed validation ({len(problems)} problem(s))", problems
        )
    return problems


def describe_problems(problems: Iterable[str]) -> str:
    return "\n".join(f"  - {problem}" for problem in problems)
