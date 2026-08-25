from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

from financial_agent.contracts import canonical_sha256


@dataclass(frozen=True, slots=True)
class SourceSpec:
    source_code: str
    table_id: str
    data_file_name: str
    data_sheet_name: str
    schema_file_name: str
    schema_sheet_name: str
    expected_columns: tuple[str, ...]
    expected_row_count: int
    natural_key: tuple[str, ...]
    parser_version: str
    mapping_version: str


@dataclass(frozen=True, slots=True)
class MappingIssue:
    source_code: str
    row_number: int | None
    column: str | None
    code: str
    severity: Literal["limited", "quarantined", "fatal"]


@dataclass(frozen=True, slots=True)
class MappedRow:
    row_number: int
    disposition: Literal["accepted", "limited", "quarantined"]
    records_by_table: Mapping[str, tuple[Mapping[str, object], ...]]
    issues: tuple[MappingIssue, ...]


@dataclass(frozen=True, slots=True)
class IdentifierCandidate:
    source_code: str
    row_number: int
    natural_key: str
    entity_role: str
    scheme: str
    value: str


@dataclass(frozen=True, slots=True)
class CanonicalIdentity:
    entity_id: str
    owner_source_code: str
    owner_natural_key: str
    roles: frozenset[str]


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    status: Literal["MATCHED", "NOT_FOUND", "AMBIGUOUS"]
    canonical_identity: CanonicalIdentity | None


@dataclass(frozen=True, slots=True)
class BuildReport:
    dataset_version: str
    cutoff_date: date
    dataset_manifest_hash: str
    source_counts: Mapping[str, Mapping[str, int]]
    table_counts: Mapping[str, int]
    issue_counts: Mapping[str, int]
    component_hashes: Mapping[str, str]
    passed: bool

    def to_json_mapping(self) -> dict[str, object]:
        return {
            "component_hashes": dict(sorted(self.component_hashes.items())),
            "cutoff_date": self.cutoff_date.isoformat(),
            "dataset_manifest_hash": self.dataset_manifest_hash,
            "dataset_version": self.dataset_version,
            "issue_counts": dict(sorted(self.issue_counts.items())),
            "passed": self.passed,
            "source_counts": {
                source: dict(sorted(counts.items()))
                for source, counts in sorted(self.source_counts.items())
            },
            "table_counts": dict(sorted(self.table_counts.items())),
        }


def manifest_hash(manifest: Mapping[str, object]) -> str:
    return canonical_sha256(manifest)
