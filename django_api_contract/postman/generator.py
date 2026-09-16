from __future__ import annotations

import re
from typing import Any

from ..conf import ContractSettings, contract_settings
from ..constants import (
    BODY_METHODS,
    FORM_MEDIA_TYPE,
    JSON_MEDIA_TYPE,
    METADATA_KEY,
    MULTIPART_MEDIA_TYPE,
    POSTMAN_SCHEMA_URL,
    SUPPORTED_BODY_MEDIA_TYPES,
)
from ..utils import content_hash, deterministic_uuid, dumps, method_sort_key, path_segments
from .examples import example_for, flatten_form_fields, resolve_ref
from .identity import OperationIdentity, build_identities

_PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


def _postman_path(path: str) -> list[str]:
    """Convert ``/customers/{public_id}/`` to Postman's ``:public_id`` form."""
    segments = []
    for segment in path_segments(path):
        segments.append(_PATH_PARAM_RE.sub(lambda m: f":{m.group(1)}", segment))
    if path.endswith("/"):
        segments.append("")
    return segments


def _parameters(
    operation: dict[str, Any], root: dict[str, Any], location: str
) -> list[dict[str, Any]]:
    resolved = []
    for parameter in operation.get("parameters") or []:
        if not isinstance(parameter, dict):
            continue
        if "$ref" in parameter:
            parameter = resolve_ref(root, parameter["$ref"]) or {}
        if parameter.get("in") == location:
            resolved.append(parameter)
    return sorted(resolved, key=lambda p: str(p.get("name", "")))


def _parameter_value(parameter: dict[str, Any], root: dict[str, Any]) -> str:
    value = example_for(parameter.get("schema") or {}, root, for_request=True)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _url(
    identity: OperationIdentity, root: dict[str, Any], settings: ContractSettings
) -> dict[str, Any]:
    base = "{{" + settings.BASE_URL_VARIABLE + "}}"
    segments = _postman_path(identity.path)

    query: list[dict[str, Any]] = []
    for parameter in _parameters(identity.operation, root, "query"):
        entry: dict[str, Any] = {
            "key": str(parameter.get("name", "")),
            "value": _parameter_value(parameter, root),
        }
        if parameter.get("description"):
            entry["description"] = str(parameter["description"])
        if not parameter.get("required"):
            entry["disabled"] = True
        query.append(entry)

    variables: list[dict[str, Any]] = []
    for parameter in _parameters(identity.operation, root, "path"):
        entry = {
            "key": str(parameter.get("name", "")),
            "value": _parameter_value(parameter, root),
        }
        if parameter.get("description"):
            entry["description"] = str(parameter["description"])
        variables.append(entry)

    raw = base + "/" + "/".join(segments)
    if query:
        enabled = [item for item in query if not item.get("disabled")]
        if enabled:
            raw += "?" + "&".join(f"{item['key']}={item['value']}" for item in enabled)

    url: dict[str, Any] = {"raw": raw, "host": [base], "path": segments}
    if query:
        url["query"] = query
    if variables:
        url["variable"] = variables
    return url


def _pick_media_type(content: dict[str, Any]) -> str | None:
    for media_type in SUPPORTED_BODY_MEDIA_TYPES:
        if media_type in content:
            return media_type
    return next(iter(sorted(content)), None)


def _body(
    identity: OperationIdentity, root: dict[str, Any], settings: ContractSettings
) -> tuple[dict[str, Any] | None, str | None]:
    request_body = identity.operation.get("requestBody")
    if isinstance(request_body, dict) and "$ref" in request_body:
        request_body = resolve_ref(root, request_body["$ref"]) or {}
    if not isinstance(request_body, dict):
        return None, None

    content = request_body.get("content")
    if not isinstance(content, dict) or not content:
        return None, None

    media_type = _pick_media_type(content)
    if media_type is None:
        return None, None

    schema_node = (content.get(media_type) or {}).get("schema") or {}

    if media_type == MULTIPART_MEDIA_TYPE:
        return (
            {
                "mode": "formdata",
                "formdata": flatten_form_fields(schema_node, root, multipart=True),
            },
            media_type,
        )

    if media_type == FORM_MEDIA_TYPE:
        return {
            "mode": "urlencoded",
            "urlencoded": flatten_form_fields(schema_node, root),
        }, media_type

    example = example_for(schema_node, root, for_request=True)
    if example is None:
        example = {}
    return (
        {
            "mode": "raw",
            "raw": dumps(example, indent=settings.INDENT).rstrip("\n"),
            "options": {"raw": {"language": "json"}},
        },
        media_type,
    )


def _headers(
    identity: OperationIdentity, root: dict[str, Any], body_media_type: str | None
) -> list[dict[str, Any]]:
    headers: list[dict[str, Any]] = []
    for parameter in _parameters(identity.operation, root, "header"):
        entry: dict[str, Any] = {
            "key": str(parameter.get("name", "")),
            "value": _parameter_value(parameter, root),
        }
        if parameter.get("description"):
            entry["description"] = str(parameter["description"])
        if not parameter.get("required"):
            entry["disabled"] = True
        headers.append(entry)

    if body_media_type and body_media_type != MULTIPART_MEDIA_TYPE:
        headers.append({"key": "Content-Type", "value": body_media_type})

    accept = _response_media_type(identity.operation)
    if accept:
        headers.append({"key": "Accept", "value": accept})

    return sorted(headers, key=lambda item: item["key"])


def _response_media_type(operation: dict[str, Any]) -> str | None:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    for status in sorted(responses):
        content = (responses[status] or {}).get("content")
        if isinstance(content, dict) and content:
            if JSON_MEDIA_TYPE in content:
                return JSON_MEDIA_TYPE
            return sorted(content)[0]
    return None


def _auth_for_scheme(name: str, scheme: dict[str, Any]) -> dict[str, Any] | None:
    """Map an OpenAPI security scheme onto Postman auth.

    Values are always collection variables so that no real secret is written
    into a generated file.
    """
    scheme_type = scheme.get("type")
    if scheme_type == "http":
        http_scheme = str(scheme.get("scheme", "")).lower()
        if http_scheme == "bearer":
            return {
                "type": "bearer",
                "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}],
            }
        if http_scheme == "basic":
            return {
                "type": "basic",
                "basic": [
                    {"key": "username", "value": "{{basic_auth_username}}", "type": "string"},
                    {"key": "password", "value": "{{basic_auth_password}}", "type": "string"},
                ],
            }
    if scheme_type == "apiKey" and scheme.get("in") in {"header", "query"}:
        return {
            "type": "apikey",
            "apikey": [
                {"key": "key", "value": str(scheme.get("name", "X-API-Key")), "type": "string"},
                {"key": "value", "value": "{{api_key}}", "type": "string"},
                {"key": "in", "value": str(scheme["in"]), "type": "string"},
            ],
        }
    # Cookie/session auth is handled by Postman's own cookie jar.
    return None


_SCHEME_PRIORITY = {"http": 0, "apiKey": 1, "oauth2": 2, "openIdConnect": 3}


def _collection_auth(root: dict[str, Any]) -> dict[str, Any] | None:
    schemes = (root.get("components") or {}).get("securitySchemes") or {}
    if not isinstance(schemes, dict):
        return None
    for name in sorted(
        schemes, key=lambda key: (_SCHEME_PRIORITY.get(schemes[key].get("type"), 9), key)
    ):
        auth = _auth_for_scheme(name, schemes[name] or {})
        if auth:
            return auth
    return None


def _operation_auth(identity: OperationIdentity, root: dict[str, Any]) -> dict[str, Any] | None:
    security = identity.operation.get("security")
    if security is None:
        return None
    if isinstance(security, list) and not security:
        return {"type": "noauth"}
    schemes = (root.get("components") or {}).get("securitySchemes") or {}
    for requirement in security:
        if not isinstance(requirement, dict):
            continue
        for name in sorted(requirement):
            auth = _auth_for_scheme(name, schemes.get(name) or {})
            if auth:
                return auth
    return None


def build_request_item(
    identity: OperationIdentity, root: dict[str, Any], settings: ContractSettings
) -> dict[str, Any]:
    body, media_type = _body(identity, root, settings)

    request: dict[str, Any] = {
        "method": identity.method.upper(),
        "header": _headers(identity, root, media_type),
        "url": _url(identity, root, settings),
    }

    description = identity.operation.get("description") or identity.operation.get("summary")
    if description:
        request["description"] = str(description)

    if body is not None and identity.method.lower() in BODY_METHODS:
        request["body"] = body

    auth = _operation_auth(identity, root)
    if auth:
        request["auth"] = auth

    name = _request_name(identity)
    item: dict[str, Any] = {
        "name": name,
        "id": deterministic_uuid("request", identity.identity),
        "request": request,
        "response": _responses(identity, root, settings),
        METADATA_KEY: {
            "managed": True,
            "operation_id": identity.operation_id,
            "identity": identity.identity,
            "method": identity.method.upper(),
            "path": identity.path,
            "request_fingerprint": content_hash(identity.request_fingerprint),
            "response_fingerprint": content_hash(identity.response_fingerprint),
            # Hashes of the fields this package owns. A later run compares them
            # against the file on disk to tell a manual edit from a stale value.
            "generated": {
                "name": content_hash(name),
                "description": content_hash(request.get("description", "")),
                "body": content_hash(_raw_body(request)),
            },
            # Keys this package put there. Anything in the file outside these
            # lists was added by hand and is left alone; anything inside them
            # that the schema no longer produces is dropped.
            "owned": _owned_keys(request),
        },
    }
    return item


def _owned_keys(request: dict[str, Any]) -> dict[str, list[str]]:
    url = request.get("url") or {}
    body = request.get("body") or {}
    owned = {
        "header": [entry["key"] for entry in request.get("header", [])],
        "query": [entry["key"] for entry in url.get("query", [])],
        "variable": [entry["key"] for entry in url.get("variable", [])],
    }
    mode = body.get("mode")
    if mode in {"formdata", "urlencoded"}:
        owned[mode] = [entry["key"] for entry in body.get(mode, [])]
    return owned


def _raw_body(request: dict[str, Any]) -> Any:
    body = request.get("body")
    if not isinstance(body, dict):
        return ""
    return body.get("raw", "")


def _request_name(identity: OperationIdentity) -> str:
    summary = identity.operation.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return identity.identity


def _responses(
    identity: OperationIdentity, root: dict[str, Any], settings: ContractSettings
) -> list[dict[str, Any]]:
    responses = identity.operation.get("responses")
    if not isinstance(responses, dict):
        return []

    items: list[dict[str, Any]] = []
    for status in sorted(responses):
        if not status.isdigit():
            continue
        definition = responses[status] or {}
        content = definition.get("content") if isinstance(definition, dict) else None
        body = ""
        media_type = None
        if isinstance(content, dict) and content:
            media_type = JSON_MEDIA_TYPE if JSON_MEDIA_TYPE in content else sorted(content)[0]
            example = example_for(
                (content[media_type] or {}).get("schema") or {}, root, for_request=False
            )
            if example is not None:
                body = dumps(example, indent=settings.INDENT).rstrip("\n")

        entry: dict[str, Any] = {
            "id": deterministic_uuid("response", identity.identity, status),
            "name": f"{status} {definition.get('description') or ''}".strip(),
            "code": int(status),
            "status": str(definition.get("description") or ""),
            "_postman_previewlanguage": "json" if media_type == JSON_MEDIA_TYPE else "text",
            "header": ([{"key": "Content-Type", "value": media_type}] if media_type else []),
            "body": body,
            METADATA_KEY: {
                "managed": True,
                "status": status,
                "generated": {"body": content_hash(body)},
            },
        }
        items.append(entry)
    return items


def build_collection(
    schema: dict[str, Any], settings: ContractSettings | None = None
) -> dict[str, Any]:
    """Render a complete Postman v2.1 collection from an OpenAPI document."""
    settings = settings or contract_settings
    identities = build_identities(schema)

    info = schema.get("info") or {}
    name = settings.POSTMAN_COLLECTION_NAME or str(info.get("title") or "API")
    description = settings.POSTMAN_COLLECTION_DESCRIPTION or str(info.get("description") or "")
    collection_id = settings.POSTMAN_COLLECTION_ID or deterministic_uuid("collection", name)

    folders: dict[str, list[dict[str, Any]]] = {}
    for identity in identities:
        folders.setdefault(identity.tag, []).append(build_request_item(identity, schema, settings))

    items: list[dict[str, Any]] = []
    for tag in sorted(folders):
        requests = sorted(
            folders[tag],
            key=lambda item: (
                item[METADATA_KEY]["path"],
                method_sort_key(item[METADATA_KEY]["method"]),
            ),
        )
        items.append(
            {
                "name": tag,
                "id": deterministic_uuid("folder", tag),
                "item": requests,
                METADATA_KEY: {"managed": True, "tag": tag},
            }
        )

    collection: dict[str, Any] = {
        "info": {
            "_postman_id": collection_id,
            "name": name,
            "schema": POSTMAN_SCHEMA_URL,
        },
        "item": items,
        "variable": [
            {
                "key": settings.BASE_URL_VARIABLE,
                "value": _default_base_url(schema),
                "type": "string",
            }
        ],
        METADATA_KEY: {
            "managed": True,
            "openapi_version": str(info.get("version") or ""),
        },
    }
    if description:
        collection["info"]["description"] = description

    auth = _collection_auth(schema)
    if auth:
        collection["auth"] = auth

    return collection


def _default_base_url(schema: dict[str, Any]) -> str:
    servers = schema.get("servers")
    if isinstance(servers, list) and servers:
        url = (servers[0] or {}).get("url")
        if isinstance(url, str) and url:
            return url.rstrip("/")
    return "http://localhost:8000"
