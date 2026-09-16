from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..conf import ContractSettings
from ..constants import METADATA_KEY
from ..utils import content_hash

# Item keys that belong to whoever edits the collection, never to this package.
USER_OWNED_ITEM_KEYS = (
    "description",
    "event",
    "variable",
    "protocolProfileBehavior",
)

KEYED_LIST_USER_FIELDS = ("value", "disabled", "src")


def metadata(node: Dict[str, Any]) -> Dict[str, Any]:
    value = node.get(METADATA_KEY)
    return value if isinstance(value, dict) else {}


def is_managed(node: Dict[str, Any]) -> bool:
    return bool(metadata(node).get("managed"))


def _generated_hash(node: Dict[str, Any], field: str) -> Optional[str]:
    return metadata(node).get("generated", {}).get(field)


def was_edited(existing: Dict[str, Any], field: str, current_value: Any) -> bool:
    """True when the value on disk differs from what this package last wrote.

    Without a recorded hash the value cannot be attributed, so it is treated as
    generated rather than risking a silent overwrite of nothing.
    """
    recorded = _generated_hash(existing, field)
    if recorded is None:
        return False
    return content_hash(current_value) != recorded


def merge_keyed_list(
    generated: List[Dict[str, Any]], existing: Optional[List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """Merge header / query / form entries without duplicating keys.

    Structure (which keys exist, their descriptions) comes from the schema.
    Values and enabled/disabled toggles are environment specific, so an
    existing entry keeps them. Entries the schema no longer knows about are
    appended untouched.
    """
    existing = existing or []
    by_key: Dict[str, Dict[str, Any]] = {}
    for entry in existing:
        if isinstance(entry, dict) and entry.get("key") is not None:
            by_key.setdefault(str(entry["key"]), entry)

    merged: List[Dict[str, Any]] = []
    used: set = set()
    for entry in generated:
        key = str(entry.get("key", ""))
        previous = by_key.get(key)
        if previous is None:
            merged.append(entry)
            continue
        used.add(key)
        combined = dict(entry)
        for field in KEYED_LIST_USER_FIELDS:
            if field in previous:
                combined[field] = previous[field]
        merged.append(combined)

    for entry in existing:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key", ""))
        if key not in used and key not in {str(e.get("key", "")) for e in generated}:
            merged.append(entry)

    return merged


def _merge_url(generated: Dict[str, Any], existing: Any) -> Dict[str, Any]:
    if not isinstance(existing, dict):
        return generated
    merged = dict(generated)
    if "query" in generated or "query" in existing:
        query = merge_keyed_list(generated.get("query", []), existing.get("query"))
        if query:
            merged["query"] = query
        else:
            merged.pop("query", None)
    if "variable" in generated or "variable" in existing:
        variables = merge_keyed_list(generated.get("variable", []), existing.get("variable"))
        if variables:
            merged["variable"] = variables
        else:
            merged.pop("variable", None)
    return merged


def _merge_body(
    generated: Optional[Dict[str, Any]],
    existing: Any,
    existing_item: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Return the merged body and whether a manual edit was preserved."""
    if generated is None:
        return (existing if isinstance(existing, dict) else None), False
    if not isinstance(existing, dict):
        return generated, False

    mode = generated.get("mode")
    if mode != existing.get("mode"):
        return generated, False

    if mode == "raw":
        if was_edited(existing_item, "body", existing.get("raw", "")):
            merged = dict(generated)
            merged["raw"] = existing.get("raw", "")
            return merged, True
        return generated, False

    if mode in {"formdata", "urlencoded"}:
        merged = dict(generated)
        merged[mode] = merge_keyed_list(generated.get(mode, []), existing.get(mode))
        return merged, False

    return generated, False


def _merge_responses(
    generated: List[Dict[str, Any]],
    existing: Any,
    settings: ContractSettings,
) -> Tuple[List[Dict[str, Any]], int]:
    """Keep manual examples; refresh generated ones."""
    existing_list = [item for item in (existing or []) if isinstance(item, dict)]
    managed_by_status: Dict[str, Dict[str, Any]] = {}
    manual: List[Dict[str, Any]] = []
    for item in existing_list:
        if is_managed(item):
            managed_by_status.setdefault(str(metadata(item).get("status", item.get("code"))), item)
        else:
            manual.append(item)

    merged: List[Dict[str, Any]] = []
    for entry in generated:
        status = str(metadata(entry).get("status", entry.get("code")))
        previous = managed_by_status.get(status)
        if previous is None:
            merged.append(entry)
            continue
        combined = dict(entry)
        combined["id"] = previous.get("id", entry.get("id"))
        if settings.PRESERVE_RESPONSE_EXAMPLES and was_edited(
            previous, "body", previous.get("body", "")
        ):
            combined["body"] = previous.get("body", "")
        if previous.get("name") and previous["name"] != entry.get("name"):
            combined["name"] = previous["name"]
        merged.append(combined)

    return merged + manual, len(manual)


def merge_request_item(
    generated: Dict[str, Any],
    existing: Dict[str, Any],
    settings: ContractSettings,
) -> Tuple[Dict[str, Any], List[str]]:
    """Fold a freshly generated request into the one already in the file.

    Returns the merged item plus a list of notes describing what was kept
    because a human had changed it.
    """
    notes: List[str] = []
    merged = dict(generated)

    if existing.get("id"):
        merged["id"] = existing["id"]

    if was_edited(existing, "name", existing.get("name", "")):
        merged["name"] = existing.get("name", generated.get("name"))
        notes.append("name")

    for key in USER_OWNED_ITEM_KEYS:
        if key in existing:
            merged[key] = existing[key]
            if key == "event":
                notes.append("scripts")

    generated_request = dict(generated.get("request") or {})
    existing_request = existing.get("request") if isinstance(existing.get("request"), dict) else {}

    generated_request["header"] = merge_keyed_list(
        generated_request.get("header", []), existing_request.get("header")
    )
    generated_request["url"] = _merge_url(
        generated_request.get("url", {}), existing_request.get("url")
    )

    body, body_preserved = _merge_body(
        generated_request.get("body"), existing_request.get("body"), existing
    )
    if body is None:
        generated_request.pop("body", None)
    else:
        generated_request["body"] = body
    if body_preserved:
        notes.append("body")

    if was_edited(existing, "description", existing_request.get("description", "")):
        if existing_request.get("description"):
            generated_request["description"] = existing_request["description"]
            notes.append("description")

    if existing_request.get("auth"):
        generated_request["auth"] = existing_request["auth"]
        notes.append("auth")

    merged["request"] = generated_request

    responses, manual_count = _merge_responses(
        generated.get("response", []), existing.get("response"), settings
    )
    merged["response"] = responses
    if manual_count:
        notes.append(f"{manual_count} manual response(s)")

    return merged, notes


def merge_folder(generated: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
    """Keep a folder's identity and human notes, replace only its contents."""
    merged = dict(generated)
    if existing.get("id"):
        merged["id"] = existing["id"]
    for key in ("description", "event", "variable", "auth", "protocolProfileBehavior"):
        if key in existing:
            merged[key] = existing[key]
    return merged
