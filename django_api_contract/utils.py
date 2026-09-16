from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional

from .constants import METHOD_ORDER, UUID_NAMESPACE

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, UUID_NAMESPACE)

_PATH_PARAM_RE = re.compile(r"\{[^}]*\}")
_TRAILING_SLASHES = re.compile(r"/+$")

ID_SEPARATOR = "\n"


def deterministic_uuid(*parts: str) -> str:
    """Build a UUID that only changes when its inputs change."""
    return str(uuid.uuid5(_NAMESPACE, ID_SEPARATOR.join(parts)))


def dumps(data: Any, indent: int = 2) -> str:
    """Serialize to JSON in a form that produces stable git diffs."""
    return json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=False) + "\n"


def load_json(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        content = handle.read().strip()
    if not content:
        return None
    return json.loads(content)


def atomic_write(path: str, content: str) -> None:
    """Write ``content`` to ``path`` without ever leaving a partial file.

    The temporary file lives in the destination directory so that the final
    ``os.replace`` stays on one filesystem and is therefore atomic.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=".api-contract-",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        if os.path.exists(handle.name):
            os.unlink(handle.name)
        raise


def normalize_path(path: str) -> str:
    """Collapse a URL path into a comparable form.

    Trailing slashes are preserved because DRF routes ``/customers`` and
    ``/customers/`` independently.
    """
    if not path:
        return "/"
    collapsed = re.sub(r"/{2,}", "/", path)
    if not collapsed.startswith("/"):
        collapsed = "/" + collapsed
    return collapsed


def path_shape(path: str) -> str:
    """Path with parameter names blanked out, so renames stay comparable."""
    return _PATH_PARAM_RE.sub("{}", normalize_path(path))


def path_segments(path: str) -> List[str]:
    stripped = _TRAILING_SLASHES.sub("", normalize_path(path))
    return [segment for segment in stripped.split("/") if segment]


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def method_sort_key(method: str) -> int:
    return METHOD_ORDER.get(method.lower(), len(METHOD_ORDER))


def sorted_unique(values: Iterable[str]) -> List[str]:
    return sorted(set(values))


def deep_sort_keys(value: Any) -> Any:
    """Recursively sort mapping keys so serialization is order independent."""
    if isinstance(value, dict):
        return {key: deep_sort_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [deep_sort_keys(item) for item in value]
    return value


def canonical(value: Any) -> str:
    """Stable string form of a JSON value, used for equality checks."""
    return json.dumps(deep_sort_keys(value), sort_keys=True, ensure_ascii=False)


def merge_preserving(
    generated: Dict[str, Any], existing: Dict[str, Any], keys: Iterable[str]
) -> None:
    """Copy user-owned ``keys`` from ``existing`` onto ``generated``."""
    for key in keys:
        if key in existing and existing[key] not in (None, "", [], {}):
            generated[key] = existing[key]


def humanize(segment: str) -> str:
    cleaned = segment.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return segment
    return cleaned[:1].upper() + cleaned[1:]


def content_hash(value: Any) -> str:
    """Short stable hash of a JSON value, used to detect manual edits."""
    import hashlib

    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()[:16]
