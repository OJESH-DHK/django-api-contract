from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ChangeKind(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class Severity(str, Enum):
    BREAKING = "breaking"
    POSSIBLY_BREAKING = "possibly-breaking"
    NON_BREAKING = "non-breaking"


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    severity: Severity
    endpoint: str
    detail: str = ""
    before: Optional[str] = None
    after: Optional[str] = None

    def describe(self) -> str:
        if self.before is not None and self.after is not None:
            return f"{self.detail}: {self.before} -> {self.after}"
        return self.detail

    @property
    def sort_key(self) -> tuple:
        return (self.endpoint, self.kind.value, self.detail)


@dataclass
class ContractDiff:
    changes: List[Change] = field(default_factory=list)

    def add(self, change: Change) -> None:
        self.changes.append(change)

    def extend(self, changes: List[Change]) -> None:
        self.changes.extend(changes)

    @property
    def is_empty(self) -> bool:
        return not self.changes

    def sorted_changes(self) -> List[Change]:
        return sorted(self.changes, key=lambda change: change.sort_key)

    def by_kind(self, kind: ChangeKind) -> List[Change]:
        return [change for change in self.sorted_changes() if change.kind is kind]

    def by_severity(self, severity: Severity) -> List[Change]:
        return [change for change in self.sorted_changes() if change.severity is severity]

    @property
    def breaking(self) -> List[Change]:
        return self.by_severity(Severity.BREAKING)

    @property
    def possibly_breaking(self) -> List[Change]:
        return self.by_severity(Severity.POSSIBLY_BREAKING)

    @property
    def added_endpoints(self) -> List[str]:
        return sorted(
            {c.endpoint for c in self.changes if c.kind is ChangeKind.ADDED and not c.detail}
        )

    @property
    def removed_endpoints(self) -> List[str]:
        return sorted(
            {c.endpoint for c in self.changes if c.kind is ChangeKind.REMOVED and not c.detail}
        )

    @property
    def changed_endpoints(self) -> List[str]:
        endpoints = {c.endpoint for c in self.changes if c.detail}
        return sorted(endpoints - set(self.added_endpoints) - set(self.removed_endpoints))
