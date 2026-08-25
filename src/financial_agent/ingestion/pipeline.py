from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts import canonical_sha256
from financial_agent.db.schema.catalog import (
    alias,
    entity,
    identifier,
    institution,
    product,
    security,
)
from financial_agent.db.schema.evidence import (
    evidence_observation_origin,
    evidence_record,
    evidence_relation_origin,
    source_record,
)
from financial_agent.db.schema.observation import (
    metric_definition,
    observation_record,
)
from financial_agent.db.schema.relation import relation_record
from financial_agent.ingestion.identity import (
    AuthoritativeIdentityIndex,
    AuthoritativeIdentityValidationError,
    build_authoritative_identity_index,
    collect_organizer_identifier_candidates,
)
from financial_agent.ingestion.mapping.common import make_record_hash, stable_id
from financial_agent.ingestion.mapping.domestic_bond import (
    SPEC as DOMESTIC_BOND_SPEC,
)
from financial_agent.ingestion.mapping.domestic_bond import (
    map_row as map_domestic_bond_row,
)
from financial_agent.ingestion.mapping.domestic_etp import (
    SPEC as DOMESTIC_ETP_SPEC,
)
from financial_agent.ingestion.mapping.domestic_etp import (
    map_row as map_domestic_etp_row,
)
from financial_agent.ingestion.mapping.overseas_etp import (
    SPEC as OVERSEAS_ETP_SPEC,
)
from financial_agent.ingestion.mapping.overseas_etp import (
    collect_duplicate_identifier_values,
)
from financial_agent.ingestion.mapping.overseas_etp import (
    map_row as map_overseas_etp_row,
)
from financial_agent.ingestion.mapping.public_fund import (
    SPEC as PUBLIC_FUND_SPEC,
)
from financial_agent.ingestion.mapping.public_fund import (
    analyze_repeated_fund_rows,
)
from financial_agent.ingestion.mapping.public_fund import (
    map_row as map_public_fund_row,
)
from financial_agent.ingestion.models import (
    BuildReport,
    IdentifierCandidate,
    MappedRow,
    SourceSpec,
)
from financial_agent.ingestion.sources import (
    SourceVerificationError,
    iter_workbook_rows,
    verify_local_source,
    verify_schema_header,
)
from financial_agent.ingestion.writer import DatasetBuildWriter


CUTOFF_DATE = date(2026, 8, 24)
SOURCE_SPECS: Mapping[str, SourceSpec] = {
    spec.source_code: spec
    for spec in (
        DOMESTIC_BOND_SPEC,
        DOMESTIC_ETP_SPEC,
        OVERSEAS_ETP_SPEC,
        PUBLIC_FUND_SPEC,
    )
}

_HASH_TABLES = (
    entity,
    product,
    security,
    institution,
    source_record,
    metric_definition,
    identifier,
    alias,
    relation_record,
    observation_record,
    evidence_record,
    evidence_observation_origin,
    evidence_relation_origin,
)
_EVIDENCE_HASH_TABLES = frozenset(
    {
        source_record.fullname,
        evidence_record.fullname,
        evidence_observation_origin.fullname,
        evidence_relation_origin.fullname,
    }
)


class OrganizerSourceValidationError(RuntimeError):
    def __init__(self, issue_counts: Mapping[str, int]) -> None:
        normalized = dict(sorted(issue_counts.items()))
        self.issue_counts = normalized
        self.code = (
            next(iter(normalized))
            if len(normalized) == 1
            else "SOURCE_PREFLIGHT_FAILED"
        )
        super().__init__(self.code)


class OrganizerBuildError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _PreflightResult:
    manifest: Mapping[str, object]
    manifest_hash: str
    contexts: Mapping[str, object]
    data_hashes: Mapping[str, str]
    identity_index: AuthoritativeIdentityIndex


@dataclass(frozen=True, slots=True)
class OrganizerWriteResult:
    source_counts: Mapping[str, Mapping[str, int]]
    issue_counts: Mapping[str, int]
    passed: bool


@contextmanager
def _snapshot_source_inputs(
    data_paths: Mapping[str, Path],
    schema_paths: Mapping[str, Path],
) -> Iterator[tuple[Mapping[str, Path], Mapping[str, Path]]]:
    try:
        with tempfile.TemporaryDirectory(
            prefix="financial-agent-organizer-snapshot-"
        ) as temporary_root:
            root = Path(temporary_root)
            data_root = root / "data"
            schema_root = root / "schema"
            data_root.mkdir()
            schema_root.mkdir()
            data_snapshots: dict[str, Path] = {}
            schema_snapshots: dict[str, Path] = {}
            for source_code in sorted(SOURCE_SPECS):
                spec = SOURCE_SPECS[source_code]
                data_snapshot = data_root / spec.data_file_name
                schema_snapshot = schema_root / spec.schema_file_name
                shutil.copyfile(data_paths[source_code], data_snapshot)
                shutil.copyfile(schema_paths[source_code], schema_snapshot)
                data_snapshots[source_code] = data_snapshot
                schema_snapshots[source_code] = schema_snapshot
            yield data_snapshots, schema_snapshots
    except OSError:
        raise SourceVerificationError(
            "SOURCE_READ_FAILED",
            "local source could not be snapshotted",
        ) from None


def _require_complete_source_inputs(
    *inputs: Mapping[str, object],
) -> None:
    expected = set(SOURCE_SPECS)
    if any(set(values) != expected for values in inputs):
        raise OrganizerSourceValidationError({"SOURCE_SET_MISMATCH": 1})


def _prescan_source(
    source_code: str,
    rows: Iterable[Mapping[str, object]],
) -> object:
    if source_code == OVERSEAS_ETP_SPEC.source_code:
        return collect_duplicate_identifier_values(rows)
    if source_code == PUBLIC_FUND_SPEC.source_code:
        return analyze_repeated_fund_rows(rows)
    for _ in rows:
        pass
    return None


def _map_source_row(
    source_code: str,
    row_number: int,
    row: Mapping[str, object],
    context: object,
) -> MappedRow:
    if source_code == DOMESTIC_BOND_SPEC.source_code:
        return map_domestic_bond_row(row_number, row)
    if source_code == DOMESTIC_ETP_SPEC.source_code:
        return map_domestic_etp_row(row_number, row)
    if source_code == OVERSEAS_ETP_SPEC.source_code:
        if not isinstance(context, Mapping):
            raise OrganizerBuildError("SOURCE_PRESCAN_CONTEXT_INVALID")
        return map_overseas_etp_row(
            row_number,
            row,
            duplicate_identifier_values=context,
        )
    if source_code == PUBLIC_FUND_SPEC.source_code:
        return map_public_fund_row(
            row_number,
            row,
            repeat_analysis=context,  # type: ignore[arg-type]
        )
    raise OrganizerBuildError("SOURCE_CODE_UNSUPPORTED")


def _record_preflight_issue(
    issues: Counter[str],
    operation: object,
) -> object | None:
    try:
        return operation()  # type: ignore[operator]
    except SourceVerificationError as error:
        issues[error.code] += 1
        return None
    except AuthoritativeIdentityValidationError as error:
        issues.update(error.issue_counts)
        return None
    except Exception:
        issues["SOURCE_PREFLIGHT_FAILED"] += 1
        return None


def _preflight_sources(
    *,
    data_paths: Mapping[str, Path],
    schema_paths: Mapping[str, Path],
    data_sha256: Mapping[str, str],
    schema_sha256: Mapping[str, str],
) -> _PreflightResult:
    _require_complete_source_inputs(
        data_paths,
        schema_paths,
        data_sha256,
        schema_sha256,
    )
    issues: Counter[str] = Counter()
    manifest_sources: list[dict[str, object]] = []
    contexts: dict[str, object] = {}
    verified_data_hashes: dict[str, str] = {}
    identity_candidates: list[IdentifierCandidate] = []

    for source_code in sorted(SOURCE_SPECS):
        spec = SOURCE_SPECS[source_code]
        data_hash = _record_preflight_issue(
            issues,
            lambda: verify_local_source(
                data_paths[source_code], data_sha256[source_code]
            ),
        )
        schema_hash = _record_preflight_issue(
            issues,
            lambda: verify_local_source(
                schema_paths[source_code], schema_sha256[source_code]
            ),
        )
        schema_columns = None
        if schema_hash is not None:
            schema_columns = _record_preflight_issue(
                issues,
                lambda: verify_schema_header(schema_paths[source_code], spec),
            )
        context = None
        if data_hash is not None:
            context = _record_preflight_issue(
                issues,
                lambda: _prescan_source(
                    source_code,
                    iter_workbook_rows(data_paths[source_code], spec),
                ),
            )
            candidates = _record_preflight_issue(
                issues,
                lambda: collect_organizer_identifier_candidates(
                    source_code,
                    iter_workbook_rows(data_paths[source_code], spec),
                ),
            )
            if isinstance(candidates, tuple):
                identity_candidates.extend(candidates)
        if (
            data_hash is not None
            and schema_hash is not None
            and schema_columns is not None
        ):
            contexts[source_code] = context
            verified_data_hashes[source_code] = data_hash
            manifest_sources.append(
                {
                    "data_sha256": data_hash,
                    "header_hash": canonical_sha256(
                        {"columns": list(schema_columns)}
                    ),
                    "mapping_version": spec.mapping_version,
                    "parser_version": spec.parser_version,
                    "row_count": spec.expected_row_count,
                    "schema_sha256": schema_hash,
                    "source_code": source_code,
                }
            )

    if issues:
        raise OrganizerSourceValidationError(issues)

    try:
        identity_index = build_authoritative_identity_index(identity_candidates)
    except AuthoritativeIdentityValidationError as error:
        raise OrganizerSourceValidationError(error.issue_counts) from None

    manifest = {
        "cutoff_date": CUTOFF_DATE.isoformat(),
        "sources": manifest_sources,
    }
    return _PreflightResult(
        manifest=manifest,
        manifest_hash=canonical_sha256(manifest),
        contexts=contexts,
        data_hashes=verified_data_hashes,
        identity_index=identity_index,
    )


def _organizer_source_rows(preflight: _PreflightResult) -> tuple[MappedRow, ...]:
    publisher_id = stable_id(
        "institution",
        "organizer",
        "competition-organizer",
    )
    publisher_payload = {
        "entity_id": publisher_id,
        "entity_type": "institution",
        "canonical_name": "Competition Organizer",
        "normalized_name": "Competition Organizer",
    }
    publisher_entity = dict(publisher_payload)
    publisher_entity["record_hash"] = make_record_hash(publisher_payload)
    rows: list[MappedRow] = []
    for source_code in sorted(SOURCE_SPECS):
        spec = SOURCE_SPECS[source_code]
        source_payload = {
            "source_id": stable_id(
                "source",
                source_code,
                spec.data_file_name,
            ),
            "publisher": publisher_id,
            "publisher_type": "organizer",
            "source_title": f"{source_code} organizer product master",
            "source_type": "dataset",
            "authority_tier": "organizer",
            "source_locator_root": spec.data_file_name,
            "content_checksum": preflight.data_hashes[source_code],
            "license_or_usage_note": "Competition-provided source data",
            "eligible_for_claim": True,
        }
        source = dict(source_payload)
        source["record_hash"] = make_record_hash(source_payload)
        rows.append(
            MappedRow(
                row_number=0,
                disposition="accepted",
                records_by_table={
                    "catalog.entity": (publisher_entity,),
                    "catalog.institution": (
                        {
                            "entity_id": publisher_id,
                            "institution_kind": "organizer",
                        },
                    ),
                    "evidence.source_record": (source,),
                },
                issues=(),
            )
        )
    return tuple(rows)


def _update_digest(digest: object, value: str) -> None:
    payload = value.encode("utf-8")
    digest.update(len(payload).to_bytes(8, "big"))  # type: ignore[attr-defined]
    digest.update(payload)  # type: ignore[attr-defined]


def _hash_statement(table: sa.Table, dataset_version: str) -> sa.Select:
    if table is metric_definition:
        referenced = (
            sa.select(
                observation_record.c.metric_id,
                observation_record.c.metric_definition_version,
            )
            .where(observation_record.c.dataset_version == dataset_version)
            .distinct()
            .subquery()
        )
        statement = sa.select(metric_definition).join(
            referenced,
            sa.and_(
                metric_definition.c.metric_id == referenced.c.metric_id,
                metric_definition.c.definition_version
                == referenced.c.metric_definition_version,
            ),
        )
    else:
        statement = sa.select(table).where(
            table.c.dataset_version == dataset_version
        )
    return statement.order_by(*table.primary_key.columns)


async def _database_component_hashes(
    engine: AsyncEngine,
    dataset_version: str,
) -> Mapping[str, str]:
    postgresql_digest = hashlib.sha256()
    evidence_digest = hashlib.sha256()
    async with engine.connect() as connection:
        for table in sorted(_HASH_TABLES, key=lambda item: item.fullname):
            _update_digest(postgresql_digest, table.fullname)
            if table.fullname in _EVIDENCE_HASH_TABLES:
                _update_digest(evidence_digest, table.fullname)
            rows = await connection.stream(_hash_statement(table, dataset_version))
            async for row in rows.mappings():
                payload = {
                    column.name: row[column.name]
                    for column in table.columns
                    if column.name not in {"created_at", "dataset_version"}
                }
                row_hash = make_record_hash(payload)
                _update_digest(postgresql_digest, row_hash)
                if table.fullname in _EVIDENCE_HASH_TABLES:
                    _update_digest(evidence_digest, row_hash)
    return {
        "evidence": evidence_digest.hexdigest(),
        "postgresql": postgresql_digest.hexdigest(),
    }


async def write_preflighted_organizer_rows(
    writer: DatasetBuildWriter,
    *,
    dataset_version: str,
    data_paths: Mapping[str, Path],
    preflight: _PreflightResult,
    batch_size: int = 1000,
) -> OrganizerWriteResult:
    if batch_size < 1:
        raise OrganizerBuildError("BUILD_BATCH_SIZE_INVALID")
    _require_complete_source_inputs(data_paths)
    await writer.write_rows(dataset_version, _organizer_source_rows(preflight))

    source_counts: dict[str, dict[str, int]] = {}
    issue_counts: Counter[str] = Counter()
    passed = True
    for source_code in sorted(SOURCE_SPECS):
        spec = SOURCE_SPECS[source_code]
        counts = {
            "accepted": 0,
            "fatal": 0,
            "limited": 0,
            "quarantined": 0,
            "rows": 0,
        }
        batch: list[MappedRow] = []
        for row_number, row in enumerate(
            iter_workbook_rows(data_paths[source_code], spec),
            start=2,
        ):
            mapped = _map_source_row(
                source_code,
                row_number,
                row,
                preflight.contexts[source_code],
            )
            if mapped.disposition not in {
                "accepted",
                "limited",
                "quarantined",
            }:
                raise OrganizerBuildError("MAPPING_DISPOSITION_INVALID")
            if mapped.row_number != row_number:
                raise OrganizerBuildError("MAPPING_ROW_NUMBER_MISMATCH")
            counts["rows"] += 1
            counts[mapped.disposition] += 1
            fatal = False
            for issue in mapped.issues:
                issue_counts[issue.code] += 1
                fatal = fatal or issue.severity == "fatal"
            if fatal:
                counts["fatal"] += 1
                passed = False
            batch.append(mapped)
            if len(batch) == batch_size:
                await writer.write_rows(dataset_version, batch)
                batch = []
        if batch:
            await writer.write_rows(dataset_version, batch)
        if (
            counts["accepted"]
            + counts["limited"]
            + counts["quarantined"]
            != counts["rows"]
        ):
            raise OrganizerBuildError("MAPPING_DISPOSITION_COUNT_MISMATCH")
        source_counts[source_code] = counts

    return OrganizerWriteResult(
        source_counts=source_counts,
        issue_counts=dict(issue_counts),
        passed=passed,
    )


async def _build_organizer_dataset_from_snapshot(
    engine: AsyncEngine,
    *,
    dataset_version: str,
    data_paths: Mapping[str, Path],
    schema_paths: Mapping[str, Path],
    data_sha256: Mapping[str, str],
    schema_sha256: Mapping[str, str],
    batch_size: int = 1000,
) -> BuildReport:
    preflight = _preflight_sources(
        data_paths=data_paths,
        schema_paths=schema_paths,
        data_sha256=data_sha256,
        schema_sha256=schema_sha256,
    )
    writer = DatasetBuildWriter(engine)
    await writer.create_building_dataset(
        dataset_version,
        preflight.manifest_hash,
        CUTOFF_DATE,
    )
    write_result = await write_preflighted_organizer_rows(
        writer,
        dataset_version=dataset_version,
        data_paths=data_paths,
        preflight=preflight,
        batch_size=batch_size,
    )

    table_counts = await writer.table_counts(dataset_version)
    component_hashes = await _database_component_hashes(engine, dataset_version)
    return BuildReport(
        dataset_version=dataset_version,
        cutoff_date=CUTOFF_DATE,
        dataset_manifest_hash=preflight.manifest_hash,
        source_counts=write_result.source_counts,
        table_counts=table_counts,
        issue_counts=write_result.issue_counts,
        component_hashes=component_hashes,
        passed=write_result.passed,
    )


async def build_organizer_dataset(
    engine: AsyncEngine,
    *,
    dataset_version: str,
    data_paths: Mapping[str, Path],
    schema_paths: Mapping[str, Path],
    data_sha256: Mapping[str, str],
    schema_sha256: Mapping[str, str],
    batch_size: int = 1000,
) -> BuildReport:
    if batch_size < 1:
        raise OrganizerBuildError("BUILD_BATCH_SIZE_INVALID")
    _require_complete_source_inputs(
        data_paths,
        schema_paths,
        data_sha256,
        schema_sha256,
    )
    with _snapshot_source_inputs(data_paths, schema_paths) as (
        data_snapshots,
        schema_snapshots,
    ):
        return await _build_organizer_dataset_from_snapshot(
            engine,
            dataset_version=dataset_version,
            data_paths=data_snapshots,
            schema_paths=schema_snapshots,
            data_sha256=data_sha256,
            schema_sha256=schema_sha256,
            batch_size=batch_size,
        )
