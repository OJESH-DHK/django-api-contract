from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .conf import ContractSettings, contract_settings
from .diff import ContractDiff, compare_schemas
from .exceptions import BreakingChangeError
from .postman import SyncResult, synchronize_collection
from .schema import generate_schema, normalize_schema, validate_schema
from .utils import atomic_write, canonical, dumps, load_json


@dataclass
class ContractBuild:
    """The complete result of building a contract, before anything is written."""

    schema: Dict[str, Any]
    sync: SyncResult
    diff: ContractDiff
    previous_schema: Optional[Dict[str, Any]] = None
    written: List[str] = field(default_factory=list)

    @property
    def collection(self) -> Dict[str, Any]:
        return self.sync.collection


def build_contract(settings: Optional[ContractSettings] = None) -> ContractBuild:
    """Produce the schema and collection in memory.

    Nothing is written here, so a failure at any step leaves the committed
    contract untouched.
    """
    settings = settings or contract_settings

    schema = normalize_schema(generate_schema(settings))
    validate_schema(schema)

    previous_schema = load_json(settings.openapi_path)
    existing_collection = load_json(settings.postman_path)

    sync = synchronize_collection(schema, existing_collection, settings)
    diff = (
        compare_schemas(previous_schema, schema)
        if isinstance(previous_schema, dict)
        else ContractDiff()
    )

    return ContractBuild(
        schema=schema, sync=sync, diff=diff, previous_schema=previous_schema
    )


def write_contract(build: ContractBuild, settings: Optional[ContractSettings] = None) -> List[str]:
    """Write both artifacts atomically once everything has been produced."""
    settings = settings or contract_settings
    indent = int(settings.INDENT)

    paths = []
    atomic_write(settings.openapi_path, dumps(build.schema, indent=indent))
    paths.append(settings.openapi_path)
    atomic_write(settings.postman_path, dumps(build.collection, indent=indent))
    paths.append(settings.postman_path)

    build.written = paths
    return paths


def enforce_compatibility(
    build: ContractBuild, settings: Optional[ContractSettings] = None
) -> None:
    settings = settings or contract_settings
    if not settings.FAIL_ON_BREAKING_CHANGE:
        return
    breaking = build.diff.breaking
    if breaking:
        raise BreakingChangeError(
            f"{len(breaking)} breaking change(s) detected", breaking
        )


@dataclass
class CheckResult:
    build: ContractBuild
    stale: List[str] = field(default_factory=list)

    @property
    def up_to_date(self) -> bool:
        return not self.stale


def check_contract(settings: Optional[ContractSettings] = None) -> CheckResult:
    """Compare the freshly built contract with the files on disk."""
    settings = settings or contract_settings
    build = build_contract(settings)

    stale: List[str] = []
    committed_schema = load_json(settings.openapi_path)
    if committed_schema is None or canonical(committed_schema) != canonical(build.schema):
        stale.append(settings.openapi_path)

    committed_collection = load_json(settings.postman_path)
    if committed_collection is None or canonical(committed_collection) != canonical(
        build.collection
    ):
        stale.append(settings.postman_path)

    return CheckResult(build=build, stale=stale)
