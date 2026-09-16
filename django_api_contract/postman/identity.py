from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..constants import UNGROUPED_FOLDER
from ..schema.normalizer import iter_operations
from ..utils import canonical, content_hash, normalize_path, path_shape, similarity


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
        """Canonical request contract, ignoring path parameter names.

        Renaming ``{id}`` to ``{public_id}`` leaves the actual contract
        untouched, so the name is replaced by its position. Query and header
        parameter names are part of the contract and are kept.
        """
        parameters = []
        position = 0
        for parameter in self.operation.get("parameters", []) or []:
            if not isinstance(parameter, dict):
                continue
            if parameter.get("in") == "path":
                anonymous = {k: v for k, v in parameter.items() if k != "name"}
                anonymous["name"] = f"<path:{position}>"
                position += 1
                parameters.append(anonymous)
            else:
                parameters.append(parameter)
        return canonical(
            {
                "parameters": parameters,
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


@dataclass
class PreviousOperation:
    """An operation as recorded in an existing Postman collection.

    Only the metadata this package wrote is available, which is why the
    fingerprints are stored at generation time rather than recomputed.
    """

    method: str
    path: str
    operation_id: Optional[str] = None
    request_fingerprint: Optional[str] = None
    response_fingerprint: Optional[str] = None

    @classmethod
    def from_metadata(cls, data: Dict[str, Any]) -> Optional["PreviousOperation"]:
        method = data.get("method")
        path = data.get("path")
        if not method or not path:
            return None
        return cls(
            method=str(method).lower(),
            path=str(path),
            operation_id=data.get("operation_id") or None,
            request_fingerprint=data.get("request_fingerprint"),
            response_fingerprint=data.get("response_fingerprint"),
        )

    @property
    def identity(self) -> str:
        return identity_string(self.method, self.path)

    @property
    def shape(self) -> str:
        return f"{self.method.upper()} {path_shape(self.path)}"

    def score_against(self, candidate: OperationIdentity) -> float:
        """Confidence that ``candidate`` is this operation after a rename."""
        if self.method != candidate.method:
            return 0.0

        shape_score = (
            1.0 if self.shape == candidate.shape else similarity(self.shape, candidate.shape)
        )
        request_score = (
            1.0
            if self.request_fingerprint
            and self.request_fingerprint == content_hash(candidate.request_fingerprint)
            else 0.0
        )
        response_score = (
            1.0
            if self.response_fingerprint
            and self.response_fingerprint == content_hash(candidate.response_fingerprint)
            else 0.0
        )
        path_score = similarity(normalize_path(self.path), normalize_path(candidate.path))

        return round(
            0.40 * shape_score + 0.25 * request_score + 0.15 * response_score + 0.20 * path_score,
            4,
        )
