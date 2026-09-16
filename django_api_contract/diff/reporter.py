from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import Change, ChangeKind, ContractDiff, Severity


def _section(title: str, lines: List[str]) -> List[str]:
    if not lines:
        return []
    return [f"{title}:", *lines, ""]


def _endpoint_block(endpoint: str, changes: List[Change]) -> List[str]:
    lines = [f"  {endpoint}"]
    for change in changes:
        if change.before is not None and change.after is not None:
            lines.append(f"    - {change.detail}: {change.before}")
            lines.append(f"    + {change.detail}: {change.after}")
        else:
            lines.append(f"    {change.detail}")
    return lines


def render_diff(diff: ContractDiff) -> str:
    """Endpoint-level report, not a JSON-level dump."""
    if diff.is_empty:
        return "No API changes."

    out: List[str] = []
    out += _section("Added", [f"  {name}" for name in diff.added_endpoints])
    out += _section("Removed", [f"  {name}" for name in diff.removed_endpoints])

    detailed: Dict[str, List[Change]] = {}
    for change in diff.sorted_changes():
        if change.detail and change.endpoint in diff.changed_endpoints:
            detailed.setdefault(change.endpoint, []).append(change)

    changed_lines: List[str] = []
    for endpoint in sorted(detailed):
        changed_lines += _endpoint_block(endpoint, detailed[endpoint])
    out += _section("Changed", changed_lines)

    breaking = diff.breaking
    if breaking:
        out += _section(
            "Breaking changes",
            [f"  {_breaking_line(change)}" for change in breaking],
        )

    possibly = diff.possibly_breaking
    if possibly:
        out += _section(
            "Potential breaking changes",
            [f"  {_breaking_line(change)}" for change in possibly],
        )

    return "\n".join(out).rstrip() + "\n"


def _breaking_line(change: Change) -> str:
    if change.kind is ChangeKind.REMOVED and not change.detail:
        return f"{change.endpoint} was removed"
    if change.before is not None and change.after is not None:
        return f"{change.endpoint}: {change.detail} {change.before} -> {change.after}"
    return f"{change.endpoint}: {change.detail}"


def _counts(rows: List[tuple]) -> List[str]:
    width = max((len(label) for label, _ in rows), default=0) + 1
    return [f"  {label + ':':<{width + 1}} {value}" for label, value in rows]


def render_sync_summary(
    diff: ContractDiff,
    sync: Any,
    *,
    dry_run: bool = False,
    openapi_path: Optional[str] = None,
    postman_path: Optional[str] = None,
) -> str:
    out: List[str] = ["API Contract Synchronization", ""]

    out.append("OpenAPI:")
    out += _counts(
        [
            ("Added", len(diff.added_endpoints)),
            ("Changed", len(diff.changed_endpoints)),
            ("Removed", len(diff.removed_endpoints)),
        ]
    )
    out.append("")

    prefix = "Would " if dry_run else ""
    out.append("Postman:")
    out += _counts(
        [
            (f"{prefix}create" if dry_run else "Created", len(sync.created)),
            (f"{prefix}update" if dry_run else "Updated", len(sync.updated)),
            ("Unchanged", len(sync.unchanged)),
            (f"{prefix}preserve" if dry_run else "Preserved", len(sync.preserved_manual)),
            (f"{prefix}archive" if dry_run else "Archived", len(sync.archived)),
            (f"{prefix}remove" if dry_run else "Removed", len(sync.removed)),
        ]
    )
    out.append("")

    if sync.renamed:
        out.append("Renamed:")
        for before, after in sync.renamed:
            out.append(f"  {before} -> {after}")
        out.append("")

    if sync.possible_renames:
        out.append("Possible endpoint renames (manual review required):")
        for before, after, score in sync.possible_renames:
            out.append(f"  {before} -> {after}  (confidence {score:.2f})")
        out.append("")

    if sync.preserved_edits:
        out.append("Manual edits kept:")
        for endpoint in sorted(sync.preserved_edits):
            out.append(f"  {endpoint}: {', '.join(sync.preserved_edits[endpoint])}")
        out.append("")

    if sync.archived:
        out.append("Removed from API:")
        for endpoint in sync.archived:
            out.append(f"  {endpoint}")
        out.append("")

    breaking = diff.breaking
    out.append(f"Breaking changes:\n  {len(breaking)}")
    for change in breaking:
        out.append(f"    {_breaking_line(change)}")
    out.append("")

    if not dry_run and (openapi_path or postman_path):
        out.append("Files:")
        if openapi_path:
            out.append(f"  {openapi_path}")
        if postman_path:
            out.append(f"  {postman_path}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def render_check_failure(diff: ContractDiff, stale_files: List[str]) -> str:
    out = ["API contract is out of date.", ""]
    if stale_files:
        out.append("Outdated files:")
        out += [f"  {path}" for path in stale_files]
        out.append("")

    changed = sorted(set(diff.added_endpoints + diff.removed_endpoints + diff.changed_endpoints))
    if changed:
        out.append("Changed:")
        out += [f"  {endpoint}" for endpoint in changed]
        out.append("")

    out.append("Run:")
    out.append("")
    out.append("  python manage.py api_contract sync")
    return "\n".join(out) + "\n"


def render_severity_counts(diff: ContractDiff) -> str:
    return (
        f"breaking={len(diff.by_severity(Severity.BREAKING))} "
        f"possible={len(diff.by_severity(Severity.POSSIBLY_BREAKING))} "
        f"safe={len(diff.by_severity(Severity.NON_BREAKING))}"
    )
