"""Fail-closed readiness and activation gate for the final Stage 03/04 dataset."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from financial_agent.db.schema import operations
from financial_agent.db.schema.document import (
    document_chunk,
    document_coverage,
    document_source_artifact,
)
from financial_agent.db.schema.evidence import source_record
from financial_agent.db.schema.search import document_embedding
from financial_agent.embeddings.contracts import APPROVED_MODEL
from financial_agent.embeddings.repository import EmbeddingRepository
from financial_agent.ingestion.final_rebuild import FINAL_DATASET_VERSION
from financial_agent.ingestion.mapping.common import make_record_hash
from financial_agent.ingestion.pipeline import (
    _EVIDENCE_HASH_TABLES,
    _HASH_TABLES,
    _hash_statement,
)


FINAL_CUTOFF = date(2026, 8, 24)
FINAL_RELEASE_VALIDATOR_VERSION = "final-release-v1"
EXPECTED_DART_COUNTS = MappingProxyType(
    {
        "dart_chunk_count": 40_149,
        "dart_coverage_count": 7_267,
        "dart_document_count": 2_214,
        "dart_source_artifact_count": 2_214,
        "vector_eligible_count": 40_149,
        "vector_exact_count": 40_149,
    }
)
_COMPONENTS = ("evidence", "graph", "postgres", "vector")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FinalReleaseError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FinalReleaseInputs:
    dataset_version: str
    postgres_manifest_hash: str
    graph_manifest_hash: str
    vector_manifest_hash: str
    evidence_manifest_hash: str

    def __post_init__(self) -> None:
        if self.dataset_version != FINAL_DATASET_VERSION:
            raise FinalReleaseError("TARGET_VERSION_NOT_ALLOWED")
        for value in self.component_manifest_hashes.values():
            if not _is_sha256(value):
                raise FinalReleaseError("COMPONENT_MANIFEST_HASH_INVALID")

    @property
    def component_manifest_hashes(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "evidence": self.evidence_manifest_hash,
                "graph": self.graph_manifest_hash,
                "postgres": self.postgres_manifest_hash,
                "vector": self.vector_manifest_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class FinalReleaseAudit:
    dataset_manifest_hash: str
    cutoff_date: str
    dataset_status: str
    postgres_manifest_hash: str
    evidence_manifest_hash: str
    vector_manifest_hash: str
    nport_source_count: int
    dart_document_count: int
    dart_source_artifact_count: int
    dart_coverage_count: int
    dart_chunk_count: int
    vector_eligible_count: int
    vector_exact_count: int
    vector_missing_count: int
    vector_duplicate_count: int
    vector_stale_count: int
    vector_orphan_count: int
    vector_wrong_dimension_count: int
    vector_unapproved_count: int


@dataclass(frozen=True, slots=True)
class FinalReleaseReport:
    dataset_version: str
    dataset_status: str
    activated: bool
    validation_run_id: str
    report_hash: str
    component_manifest_hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_manifest_hashes",
            MappingProxyType(dict(sorted(self.component_manifest_hashes.items()))),
        )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_json_object(path: Path, *, code: str) -> tuple[bytes, Mapping[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise FinalReleaseError(code)
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise FinalReleaseError(code) from None
    if not isinstance(value, dict):
        raise FinalReleaseError(code)
    return payload, value


def load_graph_release_manifest_hash(
    release_directory: Path,
    *,
    dataset_version: str,
) -> str:
    """Accept only an internally bound Jena release output directory."""
    directory = Path(release_directory)
    if (
        not directory.is_absolute()
        or directory.is_symlink()
        or not directory.is_dir()
    ):
        raise FinalReleaseError("GRAPH_RELEASE_DIRECTORY_INVALID")
    try:
        directory.resolve().relative_to(_PROJECT_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise FinalReleaseError("GRAPH_RELEASE_DIRECTORY_INVALID")

    manifest_bytes, manifest = _read_json_object(
        directory / "manifest.json",
        code="GRAPH_MANIFEST_INVALID",
    )
    _, report = _read_json_object(
        directory / "report.json",
        code="GRAPH_REPORT_INVALID",
    )
    validation_bytes, validation = _read_json_object(
        directory / "validation.json",
        code="GRAPH_VALIDATION_REPORT_INVALID",
    )
    if report.get("conforms") is not True or validation.get("conforms") is not True:
        raise FinalReleaseError("GRAPH_VALIDATION_FAILED")
    if report.get("validation_backend") != "jena":
        raise FinalReleaseError("GRAPH_VALIDATION_BACKEND_INVALID")
    if (
        manifest.get("schema_version") != "2"
        or manifest.get("dataset_version") != dataset_version
        or report.get("dataset_version") != dataset_version
    ):
        raise FinalReleaseError("GRAPH_DATASET_MISMATCH")

    manifest_hash = sha256(manifest_bytes).hexdigest()
    validation_hash = sha256(validation_bytes).hexdigest()
    if (
        report.get("component_manifest_hash") != manifest_hash
        or manifest.get("validation_report_hash") != validation_hash
        or report.get("validation_report_hash") != validation_hash
    ):
        raise FinalReleaseError("GRAPH_MANIFEST_MISMATCH")
    return manifest_hash


def _update_digest(digest: object, value: str) -> None:
    payload = value.encode("utf-8")
    digest.update(len(payload).to_bytes(8, "big"))  # type: ignore[attr-defined]
    digest.update(payload)  # type: ignore[attr-defined]


async def _database_component_hashes(
    connection: AsyncConnection,
    dataset_version: str,
) -> tuple[str, str]:
    postgres_digest = hashlib.sha256()
    evidence_digest = hashlib.sha256()
    for table in sorted(_HASH_TABLES, key=lambda item: item.fullname):
        _update_digest(postgres_digest, table.fullname)
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
            _update_digest(postgres_digest, row_hash)
            if table.fullname in _EVIDENCE_HASH_TABLES:
                _update_digest(evidence_digest, row_hash)
    return postgres_digest.hexdigest(), evidence_digest.hexdigest()


async def _vector_manifest_hash(
    connection: AsyncConnection,
    dataset_version: str,
) -> str:
    digest = hashlib.sha256()
    _update_digest(digest, APPROVED_MODEL.model_hash)
    statement = (
        sa.select(
            document_embedding.c.embedding_id,
            document_embedding.c.document_id,
            document_embedding.c.chunk_id,
            document_embedding.c.chunk_content_hash,
            document_embedding.c.model_id,
            document_embedding.c.model_version,
            document_embedding.c.dimension,
            sa.cast(document_embedding.c.embedding, sa.Text).label("embedding"),
        )
        .where(document_embedding.c.dataset_version == dataset_version)
        .order_by(document_embedding.c.embedding_id)
    )
    rows = await connection.stream(statement)
    async for row in rows.mappings():
        _update_digest(digest, make_record_hash(dict(row)))
    return digest.hexdigest()


async def _vector_counts(
    connection: AsyncConnection,
    dataset_version: str,
) -> Mapping[str, int]:
    eligible = EmbeddingRepository.eligible_statement(dataset_version).subquery(
        "eligible_chunks"
    )
    approved_rows = sa.and_(
        document_embedding.c.dataset_version == dataset_version,
        document_embedding.c.model_id == APPROVED_MODEL.model_id,
        document_embedding.c.model_version == APPROVED_MODEL.model_version,
    )
    exact_match = sa.and_(
        document_embedding.c.dataset_version == eligible.c.dataset_version,
        document_embedding.c.document_id == eligible.c.document_id,
        document_embedding.c.chunk_id == eligible.c.chunk_id,
        document_embedding.c.chunk_content_hash == eligible.c.content_hash,
        document_embedding.c.model_id == APPROVED_MODEL.model_id,
        document_embedding.c.model_version == APPROVED_MODEL.model_version,
        document_embedding.c.dimension == APPROVED_MODEL.dimension,
    )
    same_chunk = sa.and_(
        document_embedding.c.dataset_version == document_chunk.c.dataset_version,
        document_embedding.c.document_id == document_chunk.c.document_id,
        document_embedding.c.chunk_id == document_chunk.c.chunk_id,
    )
    duplicate_groups = (
        sa.select(
            document_embedding.c.document_id,
            document_embedding.c.chunk_id,
            document_embedding.c.chunk_content_hash,
            (sa.func.count() - 1).label("duplicates"),
        )
        .where(approved_rows)
        .group_by(
            document_embedding.c.document_id,
            document_embedding.c.chunk_id,
            document_embedding.c.chunk_content_hash,
        )
        .having(sa.func.count() > 1)
        .subquery("duplicate_groups")
    )
    queries = {
        "eligible": sa.select(sa.func.count()).select_from(eligible),
        "exact": sa.select(sa.func.count()).select_from(
            eligible.join(document_embedding, exact_match)
        ),
        "missing": sa.select(sa.func.count())
        .select_from(eligible)
        .where(~sa.exists(sa.select(1).select_from(document_embedding).where(exact_match))),
        "duplicate": sa.select(
            sa.func.coalesce(sa.func.sum(duplicate_groups.c.duplicates), 0)
        ),
        "stale": sa.select(sa.func.count())
        .select_from(document_embedding.join(document_chunk, same_chunk))
        .where(
            approved_rows,
            document_embedding.c.chunk_content_hash != document_chunk.c.content_hash,
        ),
        "orphan": sa.select(sa.func.count())
        .select_from(document_embedding)
        .where(
            approved_rows,
            ~sa.exists(sa.select(1).select_from(document_chunk).where(same_chunk)),
        ),
        "wrong_dimension": sa.select(sa.func.count())
        .select_from(document_embedding)
        .where(
            approved_rows,
            sa.or_(
                document_embedding.c.dimension != APPROVED_MODEL.dimension,
                sa.func.cdb_admin.vector_dims(document_embedding.c.embedding)
                != APPROVED_MODEL.dimension,
            ),
        ),
        "unapproved": sa.select(sa.func.count())
        .select_from(document_embedding)
        .where(
            document_embedding.c.dataset_version == dataset_version,
            sa.not_(
                sa.and_(
                    document_embedding.c.model_id == APPROVED_MODEL.model_id,
                    document_embedding.c.model_version
                    == APPROVED_MODEL.model_version,
                )
            ),
        ),
    }
    return MappingProxyType(
        {
            name: int(await connection.scalar(statement) or 0)
            for name, statement in queries.items()
        }
    )


async def _collect_release_audit(
    connection: AsyncConnection,
    dataset_version: str,
) -> FinalReleaseAudit:
    target = (
        await connection.execute(
            sa.select(
                operations.dataset_version.c.manifest_hash,
                operations.dataset_version.c.cutoff_date,
                operations.dataset_version.c.status,
            ).where(operations.dataset_version.c.dataset_version == dataset_version)
        )
    ).one()
    artifact_documents = (
        sa.select(document_source_artifact.c.document_id)
        .where(document_source_artifact.c.dataset_version == dataset_version)
        .distinct()
        .subquery("dart_documents")
    )
    counts = {}
    counts["documents"] = int(
        await connection.scalar(sa.select(sa.func.count()).select_from(artifact_documents))
        or 0
    )
    counts["artifacts"] = int(
        await connection.scalar(
            sa.select(sa.func.count())
            .select_from(document_source_artifact)
            .where(document_source_artifact.c.dataset_version == dataset_version)
        )
        or 0
    )
    for name, table in (("coverages", document_coverage), ("chunks", document_chunk)):
        counts[name] = int(
            await connection.scalar(
                sa.select(sa.func.count()).select_from(
                    table.join(
                        artifact_documents,
                        table.c.document_id == artifact_documents.c.document_id,
                    )
                ).where(table.c.dataset_version == dataset_version)
            )
            or 0
        )
    nport_source_count = int(
        await connection.scalar(
            sa.select(sa.func.count())
            .select_from(source_record)
            .where(
                source_record.c.dataset_version == dataset_version,
                source_record.c.source_title
                == "SEC Form N-PORT 2026 Q2 public data set",
                source_record.c.authority_tier == "official",
                source_record.c.eligible_for_claim.is_(True),
            )
        )
        or 0
    )
    vector_counts = await _vector_counts(connection, dataset_version)
    postgres_hash, evidence_hash = await _database_component_hashes(
        connection, dataset_version
    )
    vector_hash = await _vector_manifest_hash(connection, dataset_version)
    return FinalReleaseAudit(
        dataset_manifest_hash=str(target.manifest_hash),
        cutoff_date=target.cutoff_date.isoformat(),
        dataset_status=str(target.status),
        postgres_manifest_hash=postgres_hash,
        evidence_manifest_hash=evidence_hash,
        vector_manifest_hash=vector_hash,
        nport_source_count=nport_source_count,
        dart_document_count=counts["documents"],
        dart_source_artifact_count=counts["artifacts"],
        dart_coverage_count=counts["coverages"],
        dart_chunk_count=counts["chunks"],
        vector_eligible_count=vector_counts["eligible"],
        vector_exact_count=vector_counts["exact"],
        vector_missing_count=vector_counts["missing"],
        vector_duplicate_count=vector_counts["duplicate"],
        vector_stale_count=vector_counts["stale"],
        vector_orphan_count=vector_counts["orphan"],
        vector_wrong_dimension_count=vector_counts["wrong_dimension"],
        vector_unapproved_count=vector_counts["unapproved"],
    )


def _validate_audit(
    inputs: FinalReleaseInputs,
    audit: FinalReleaseAudit,
    *,
    dataset_manifest_hash: str,
) -> None:
    if audit.dataset_manifest_hash != dataset_manifest_hash:
        raise FinalReleaseError("DATASET_MANIFEST_MISMATCH")
    if audit.cutoff_date != FINAL_CUTOFF.isoformat():
        raise FinalReleaseError("CUTOFF_MISMATCH")
    if audit.dataset_status != "building":
        raise FinalReleaseError("TARGET_NOT_BUILDING")
    if audit.postgres_manifest_hash != inputs.postgres_manifest_hash:
        raise FinalReleaseError("POSTGRES_MANIFEST_MISMATCH")
    if audit.evidence_manifest_hash != inputs.evidence_manifest_hash:
        raise FinalReleaseError("EVIDENCE_MANIFEST_MISMATCH")
    if audit.vector_manifest_hash != inputs.vector_manifest_hash:
        raise FinalReleaseError("VECTOR_MANIFEST_MISMATCH")
    if audit.nport_source_count != 1:
        raise FinalReleaseError("NPORT_SOURCE_MISSING")
    if any(getattr(audit, name) != expected for name, expected in EXPECTED_DART_COUNTS.items()):
        raise FinalReleaseError("DART_COUNT_MISMATCH")
    if any(
        getattr(audit, name) != 0
        for name in (
            "vector_missing_count",
            "vector_duplicate_count",
            "vector_stale_count",
            "vector_orphan_count",
            "vector_wrong_dimension_count",
            "vector_unapproved_count",
        )
    ):
        raise FinalReleaseError("VECTOR_RECONCILIATION_FAILED")


def _validation_payload(
    inputs: FinalReleaseInputs,
    audit: FinalReleaseAudit,
) -> bytes:
    payload = {
        "audit": asdict(audit),
        "components": dict(inputs.component_manifest_hashes),
        "dataset_version": inputs.dataset_version,
        "schema_version": "1",
        "validator_version": FINAL_RELEASE_VALIDATOR_VERSION,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


async def _existing_release(
    connection: AsyncConnection,
    inputs: FinalReleaseInputs,
) -> tuple[str, str]:
    rows = (
        await connection.execute(
            sa.select(
                operations.dataset_readiness.c.component,
                operations.dataset_readiness.c.component_manifest_hash,
                operations.dataset_readiness.c.validation_run_id,
            )
            .where(
                operations.dataset_readiness.c.dataset_version
                == inputs.dataset_version
            )
            .order_by(operations.dataset_readiness.c.component)
        )
    ).all()
    if len(rows) != 4 or tuple(row.component for row in rows) != _COMPONENTS:
        raise FinalReleaseError("READINESS_INCOMPLETE")
    if any(
        row.component_manifest_hash
        != inputs.component_manifest_hashes[row.component]
        for row in rows
    ):
        raise FinalReleaseError("READINESS_MANIFEST_MISMATCH")
    run_ids = {str(row.validation_run_id) for row in rows}
    if len(run_ids) != 1:
        raise FinalReleaseError("READINESS_VALIDATION_MISMATCH")
    run_id = next(iter(run_ids))
    run = (
        await connection.execute(
            sa.select(
                operations.dataset_validation_run.c.status,
                operations.dataset_validation_run.c.report_hash,
            ).where(
                operations.dataset_validation_run.c.validation_run_id == run_id,
                operations.dataset_validation_run.c.dataset_version
                == inputs.dataset_version,
            )
        )
    ).one_or_none()
    if run is None or run.status != "pass":
        raise FinalReleaseError("READINESS_VALIDATION_MISMATCH")
    return run_id, str(run.report_hash)


async def validate_and_activate_final_dataset(
    engine: AsyncEngine,
    *,
    inputs: FinalReleaseInputs,
    activate: bool,
) -> FinalReleaseReport:
    if not isinstance(activate, bool):
        raise FinalReleaseError("ACTIVATION_FLAG_INVALID")
    async with engine.begin() as connection:
        target = (
            await connection.execute(
                sa.select(
                    operations.dataset_version.c.manifest_hash,
                    operations.dataset_version.c.cutoff_date,
                    operations.dataset_version.c.status,
                )
                .where(
                    operations.dataset_version.c.dataset_version
                    == inputs.dataset_version
                )
                .with_for_update()
            )
        ).one_or_none()
        if target is None:
            raise FinalReleaseError("TARGET_NOT_FOUND")
        if target.cutoff_date != FINAL_CUTOFF:
            raise FinalReleaseError("CUTOFF_MISMATCH")

        if target.status == "building":
            audit = await _collect_release_audit(connection, inputs.dataset_version)
            _validate_audit(
                inputs,
                audit,
                dataset_manifest_hash=str(target.manifest_hash),
            )
            report_hash = sha256(_validation_payload(inputs, audit)).hexdigest()
            validation_run_id = f"final-release:{report_hash}"
            recorded_at = datetime.now(UTC)
            await connection.execute(
                sa.insert(operations.dataset_validation_run).values(
                    validation_run_id=validation_run_id,
                    dataset_version=inputs.dataset_version,
                    dataset_manifest_hash=target.manifest_hash,
                    validator_id="financial-agent-final-release",
                    validator_version=FINAL_RELEASE_VALIDATOR_VERSION,
                    started_at=recorded_at,
                    finished_at=recorded_at,
                    status="pass",
                    report_hash=report_hash,
                )
            )
            status = str(
                await connection.scalar(
                    sa.text("SELECT operations.finish_dataset_validation(:run_id)"),
                    {"run_id": validation_run_id},
                )
            )
            for component in _COMPONENTS:
                await connection.execute(
                    sa.text(
                        """
                        SELECT operations.record_dataset_readiness(
                            :dataset_version, :component, :run_id,
                            :component_hash, :validated_at, :validator_version
                        )
                        """
                    ),
                    {
                        "dataset_version": inputs.dataset_version,
                        "component": component,
                        "run_id": validation_run_id,
                        "component_hash": inputs.component_manifest_hashes[component],
                        "validated_at": recorded_at,
                        "validator_version": FINAL_RELEASE_VALIDATOR_VERSION,
                    },
                )
        elif target.status in {"validated", "active"}:
            validation_run_id, report_hash = await _existing_release(
                connection, inputs
            )
            status = str(target.status)
        else:
            raise FinalReleaseError("TARGET_NOT_RELEASABLE")

        if activate and status != "active":
            activated_version = await connection.scalar(
                sa.text("SELECT operations.activate_dataset(:dataset_version)"),
                {"dataset_version": inputs.dataset_version},
            )
            if activated_version != inputs.dataset_version:
                raise FinalReleaseError("ACTIVATION_FAILED")
            status = "active"

    return FinalReleaseReport(
        dataset_version=inputs.dataset_version,
        dataset_status=status,
        activated=status == "active",
        validation_run_id=validation_run_id,
        report_hash=report_hash,
        component_manifest_hashes=inputs.component_manifest_hashes,
    )
