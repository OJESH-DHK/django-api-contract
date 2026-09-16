from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..constants import UNGROUPED_FOLDER
from ..schema.normalizer import iter_operations
from ..utils import canonical, normalize_path, path_shape, similarity


def identity_string(method: str, path: str) -> str:
    """Human readable identity: ``GET /api/v1/customers/{public_id}``.

    Method and path together are stable across operationId churn, and they are
    what a developer recognizes when reading collection metadata.
    """
    return f"{method.upper()} {normalize_path(path)}"


@dataclass
class OperationIdentity:
    """Everything needed to recognize one API operation across runs."""

    method: str
    path: str
    operation: Dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def identity(self) -> str:
        return identity_string(self.method, self.path)

    @property
    def operation_id(self) -> Optional[str]:
        value = self.operation.get("operationId")
        return value if isinstance(value, str) and value else None

    @property
    def shape(self) -> str:
        """Identity with parameter names removed, for rename detection."""
        return f"{self.method.upper()} {path_shape(self.path)}"

    @property
    def tag(self) -> str:
        tags = self.operation.get("tags")
        if isinstance(tags, list) and tags:
            return str(tags[0])
        return UNGROUPED_FOLDER

    @property
    def request_fingerprint(self) -> str:
        return canonical(
            {
                "parameters": self.operation.get("parameters", []),
                "requestBody": self.operation.get("requestBody", {}),
            }
        )

    @property
    def response_fingerprint(self) -> str:
        return canonical(self.operation.get("responses", {}))

    def similarity_to(self, other: "OperationIdentity") -> float:
        """Confidence that ``other`` is this operation under a new name.

        Weighted so that the request/response contract matters more than the
        spelling of the path: a renamed path parameter keeps the same body.
        """
        if self.method != other.method:
            return 0.0

        shape_score = 1.0 if self.shape == other.shape else similarity(self.shape, other.shape)
        request_score = 1.0 if self.request_fingerprint == other.request_fingerprint else 0.0
        response_score = 1.0 if self.response_fingerprint == other.response_fingerprint else 0.0
        path_score = similarity(normalize_path(self.path), normalize_path(other.path))

        return round(
            0.40 * shape_score + 0.25 * request_score + 0.15 * response_score + 0.20 * path_score,
            4,
        )


def build_identities(schema: Dict[str, Any]) -> List[OperationIdentity]:
    return [
        OperationIdentity(method=method, path=path, operation=operation)
        for path, method, operation in iter_operations(schema)
    ]


def index_by_identity(identities: List[OperationIdentity]) -> Dict[str, OperationIdentity]:
    return {item.identity: item for item in identities}


def index_by_operation_id(
    identities: List[OperationIdentity],
) -> Dict[str, OperationIdentity]:
    """Map operationId to operation, skipping ids that are not unique.

    A duplicated operationId cannot identify anything, so it is dropped rather
    than silently matching the wrong request.
    """
    counts: Dict[str, int] = {}
    for item in identities:
        if item.operation_id:
            counts[item.operation_id] = counts.get(item.operation_id, 0) + 1
    return {
        item.operation_id: item
        for item in identities
        if item.operation_id and counts[item.operation_id] == 1
    }
