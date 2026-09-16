from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..conf import ContractSettings, contract_settings
from ..constants import ARCHIVED_SUFFIX, CONFIDENT_RENAME_SCORE, METADATA_KEY
from ..exceptions import PostmanSyncError
from ..utils import method_sort_key
from .generator import build_collection
from .identity import PreviousOperation
from .merger import merge_folder, merge_request_item, metadata


@dataclass
class SyncResult:
    collection: dict[str, Any]
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    possible_renames: list[tuple[str, str, float]] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    preserved_manual: list[str] = field(default_factory=list)
    preserved_edits: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return bool(self.created or self.updated or self.renamed or self.archived or self.removed)


@dataclass
class _ExistingItem:
    item: dict[str, Any]
    folder: str | None
    order: int

    @property
    def is_request(self) -> bool:
        return isinstance(self.item.get("request"), dict)


def _walk(items: Any, folder: str | None, sink: list[_ExistingItem]) -> None:
    if not isinstance(items, list):
        return
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("item"), list):
            _walk(item["item"], item.get("name"), sink)
        else:
            sink.append(_ExistingItem(item=item, folder=folder, order=index))


def _existing_folders(collection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    folders: dict[str, dict[str, Any]] = {}
    for item in collection.get("item") or []:
        if isinstance(item, dict) and isinstance(item.get("item"), list):
            folders.setdefault(str(item.get("name", "")), item)
    return folders


def _match_existing(
    existing: list[_ExistingItem], generated_items: dict[str, dict[str, Any]]
) -> tuple[
    dict[str, _ExistingItem],
    list[_ExistingItem],
    list[_ExistingItem],
    list[tuple[str, str]],
]:
    """Pair existing managed requests with generated ones.

    Matching runs strongest-signal first: operationId survives a path change,
    the method+path identity survives an operationId change.
    """
    by_identity: dict[str, _ExistingItem] = {}
    manual: list[_ExistingItem] = []
    unmatched: list[_ExistingItem] = []
    renamed: list[tuple[str, str]] = []

    by_operation_id = {
        str(meta["operation_id"]): identity
        for identity, item in generated_items.items()
        if (meta := metadata(item)).get("operation_id")
    }

    for entry in existing:
        if not entry.is_request:
            continue
        meta = metadata(entry.item)
        if not meta.get("managed"):
            manual.append(entry)
            continue

        identity = meta.get("identity")
        if isinstance(identity, str) and identity in generated_items:
            by_identity.setdefault(identity, entry)
            continue

        operation_id = meta.get("operation_id")
        if operation_id and str(operation_id) in by_operation_id:
            target = by_operation_id[str(operation_id)]
            if target not in by_identity:
                by_identity[target] = entry
                if isinstance(identity, str) and identity and identity != target:
                    renamed.append((identity, target))
                continue

        unmatched.append(entry)

    return by_identity, unmatched, manual, renamed


def _detect_renames(
    unmatched_existing: list[_ExistingItem],
    unclaimed_generated: dict[str, dict[str, Any]],
    identities: dict[str, Any],
    settings: ContractSettings,
) -> tuple[dict[str, _ExistingItem], list[tuple[str, str]], list[tuple[str, str, float]]]:
    matched: dict[str, _ExistingItem] = {}
    renamed: list[tuple[str, str]] = []
    possible: list[tuple[str, str, float]] = []

    if not settings.DETECT_RENAMES:
        return matched, renamed, possible

    threshold = float(settings.RENAME_SIMILARITY_THRESHOLD)
    scored: list[tuple[float, str, _ExistingItem]] = []

    for entry in unmatched_existing:
        previous = PreviousOperation.from_metadata(metadata(entry.item))
        if previous is None:
            continue
        for identity, operation in identities.items():
            if identity not in unclaimed_generated:
                continue
            score = previous.score_against(operation)
            if score >= threshold:
                scored.append((score, identity, entry))

    scored.sort(key=lambda row: (-row[0], row[1]))
    claimed_identities: set = set()
    claimed_entries: set = set()

    for score, identity, entry in scored:
        entry_key = id(entry)
        if identity in claimed_identities or entry_key in claimed_entries:
            continue
        previous_identity = str(metadata(entry.item).get("identity", ""))
        if score >= CONFIDENT_RENAME_SCORE:
            matched[identity] = entry
            renamed.append((previous_identity, identity))
        else:
            possible.append((previous_identity, identity, score))
        claimed_identities.add(identity)
        claimed_entries.add(entry_key)

    return matched, renamed, possible


def _archive(item: dict[str, Any]) -> dict[str, Any]:
    archived = dict(item)
    name = str(archived.get("name", ""))
    if not name.endswith(ARCHIVED_SUFFIX):
        archived["name"] = name + ARCHIVED_SUFFIX
    meta = dict(metadata(archived))
    meta["archived"] = True
    archived[METADATA_KEY] = meta
    return archived


def synchronize_collection(
    schema: dict[str, Any],
    existing: dict[str, Any] | None = None,
    settings: ContractSettings | None = None,
) -> SyncResult:
    """Fold the current API into an existing collection instead of replacing it."""
    settings = settings or contract_settings
    generated = build_collection(schema, settings)

    if existing is None:
        result = SyncResult(collection=generated)
        result.created = [
            metadata(item)["identity"] for folder in generated["item"] for item in folder["item"]
        ]
        return result

    if not isinstance(existing, dict) or not isinstance(existing.get("item"), list):
        raise PostmanSyncError(
            "Existing Postman collection is not a valid v2.1 document (missing 'item' list)"
        )

    from .identity import build_identities

    identities = {item.identity: item for item in build_identities(schema)}
    generated_items = {
        metadata(item)["identity"]: item for folder in generated["item"] for item in folder["item"]
    }

    flat: list[_ExistingItem] = []
    _walk(existing.get("item"), None, flat)

    matched, unmatched, manual, id_renames = _match_existing(flat, generated_items)
    unclaimed = {key: value for key, value in generated_items.items() if key not in matched}
    rename_matches, renamed, possible_renames = _detect_renames(
        unmatched, unclaimed, identities, settings
    )
    matched.update(rename_matches)
    rename_entry_ids = {id(entry) for entry in rename_matches.values()}

    result = SyncResult(
        collection={},
        renamed=id_renames + renamed,
        possible_renames=possible_renames,
    )

    merged_items: dict[str, dict[str, Any]] = {}
    for identity, item in generated_items.items():
        previous = matched.get(identity)
        if previous is None:
            merged_items[identity] = item
            result.created.append(identity)
            continue
        merged, notes = merge_request_item(item, previous.item, settings)
        merged_items[identity] = merged
        if notes:
            result.preserved_edits[identity] = notes
        if _differs(previous.item, merged):
            result.updated.append(identity)
        else:
            result.unchanged.append(identity)

    stale = [entry for entry in unmatched if id(entry) not in rename_entry_ids]

    result.preserved_manual = [str(entry.item.get("name", "")) for entry in manual]

    collection, archived, removed = _rebuild(
        generated, existing, merged_items, manual, stale, settings
    )
    result.collection = collection
    result.archived = archived
    result.removed = removed
    return result


def _differs(previous: dict[str, Any], merged: dict[str, Any]) -> bool:
    from ..utils import canonical

    return canonical(previous) != canonical(merged)


def _rebuild(
    generated: dict[str, Any],
    existing: dict[str, Any],
    merged_items: dict[str, dict[str, Any]],
    manual: list[_ExistingItem],
    stale: list[_ExistingItem],
    settings: ContractSettings,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Reassemble the collection: generated folders first, human content kept."""
    existing_folders = _existing_folders(existing)
    generated_folder_names = {str(folder.get("name", "")) for folder in generated["item"]}

    archived: list[str] = []
    removed: list[str] = []

    keep_by_folder: dict[str | None, list[dict[str, Any]]] = {}

    if settings.PRESERVE_MANUAL_REQUESTS:
        for entry in manual:
            keep_by_folder.setdefault(entry.folder, []).append(entry.item)
    else:
        removed.extend(str(entry.item.get("name", "")) for entry in manual)

    for entry in stale:
        identity = str(metadata(entry.item).get("identity", entry.item.get("name", "")))
        if settings.REMOVE_DELETED_ENDPOINTS:
            removed.append(identity)
            continue
        archived.append(identity)
        if settings.ARCHIVE_DELETED_ENDPOINTS:
            keep_by_folder.setdefault(entry.folder, []).append(_archive(entry.item))
        else:
            keep_by_folder.setdefault(entry.folder, []).append(entry.item)

    collection = dict(generated)
    for key in ("variable", "auth", "event", "protocolProfileBehavior"):
        if key in existing and key != "variable":
            collection[key] = existing[key]
    if isinstance(existing.get("variable"), list) and existing["variable"]:
        collection["variable"] = _merge_collection_variables(
            generated.get("variable", []), existing["variable"]
        )

    raw_info = existing.get("info")
    existing_info: dict[str, Any] = raw_info if isinstance(raw_info, dict) else {}
    info = dict(generated["info"])
    if existing_info.get("_postman_id"):
        info["_postman_id"] = existing_info["_postman_id"]
    if existing_info.get("name"):
        info["name"] = existing_info["name"]
    collection["info"] = info

    folders: list[dict[str, Any]] = []
    for folder in generated["item"]:
        name = str(folder.get("name", ""))
        rebuilt = dict(folder)
        rebuilt["item"] = sorted(
            (
                merged_items[metadata(item)["identity"]]
                for item in folder["item"]
                if metadata(item)["identity"] in merged_items
            ),
            key=lambda item: (
                metadata(item)["path"],
                method_sort_key(metadata(item)["method"]),
            ),
        )
        rebuilt["item"].extend(keep_by_folder.pop(name, []))
        if name in existing_folders:
            rebuilt = merge_folder(rebuilt, existing_folders[name])
        folders.append(rebuilt)

    for name in sorted(key for key in keep_by_folder if key is not None):
        kept = keep_by_folder.pop(name)
        if name in generated_folder_names:
            continue
        source = existing_folders.get(name, {"name": name})
        preserved = {key: value for key, value in source.items() if key != "item"}
        preserved["name"] = name
        preserved["item"] = kept
        folders.append(preserved)

    root_level = keep_by_folder.pop(None, [])
    collection["item"] = folders + root_level
    return collection, archived, removed


def _merge_collection_variables(
    generated: list[dict[str, Any]], existing: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Never overwrite a value the developer configured for their environment."""
    by_key = {str(entry.get("key", "")): entry for entry in existing if isinstance(entry, dict)}
    merged: list[dict[str, Any]] = []
    for entry in generated:
        key = str(entry.get("key", ""))
        merged.append(by_key.pop(key, entry) if key in by_key else entry)
    merged.extend(by_key[key] for key in sorted(by_key))
    return merged
