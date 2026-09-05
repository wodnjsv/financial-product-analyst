from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.schema import operations
from financial_agent.ingestion.final_rebuild import FINAL_DATASET_VERSION
from financial_agent.ingestion.final_release import (
    FinalReleaseAudit,
    FinalReleaseError,
    FinalReleaseInputs,
    _collect_release_audit,
    load_graph_release_manifest_hash,
    validate_and_activate_final_dataset,
)
from financial_agent.ingestion import cli
from tests.fixtures.db.synthetic_dataset import insert_building_dataset


POSTGRES_HASH = "1" * 64
GRAPH_HASH = "2" * 64
VECTOR_HASH = "3" * 64
EVIDENCE_HASH = "4" * 64


def _inputs() -> FinalReleaseInputs:
    return FinalReleaseInputs(
        dataset_version=FINAL_DATASET_VERSION,
        postgres_manifest_hash=POSTGRES_HASH,
        graph_manifest_hash=GRAPH_HASH,
        vector_manifest_hash=VECTOR_HASH,
        evidence_manifest_hash=EVIDENCE_HASH,
    )


def _audit(*, status: str = "building") -> FinalReleaseAudit:
    return FinalReleaseAudit(
        dataset_manifest_hash="a" * 64,
        cutoff_date="2026-08-24",
        dataset_status=status,
        postgres_manifest_hash=POSTGRES_HASH,
        evidence_manifest_hash=EVIDENCE_HASH,
        vector_manifest_hash=VECTOR_HASH,
        nport_source_count=1,
        dart_document_count=2_214,
        dart_source_artifact_count=2_214,
        dart_coverage_count=7_267,
        dart_chunk_count=40_149,
        vector_eligible_count=40_149,
        vector_exact_count=40_149,
        vector_missing_count=0,
        vector_duplicate_count=0,
        vector_stale_count=0,
        vector_orphan_count=0,
        vector_wrong_dimension_count=0,
        vector_unapproved_count=0,
    )


def _purge_final_dataset(database_url: str) -> None:
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            """
            UPDATE operations.active_dataset
               SET dataset_version = NULL, activated_at = NULL
             WHERE dataset_version = %s
            """,
            (FINAL_DATASET_VERSION,),
        )
        connection.execute(
            "DELETE FROM operations.dataset_readiness WHERE dataset_version = %s",
            (FINAL_DATASET_VERSION,),
        )
        connection.execute(
            "DELETE FROM operations.dataset_validation_run WHERE dataset_version = %s",
            (FINAL_DATASET_VERSION,),
        )
        connection.execute(
            "DELETE FROM operations.dataset_version WHERE dataset_version = %s",
            (FINAL_DATASET_VERSION,),
        )


def _active_dataset(database_url: str) -> str | None:
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        return connection.execute(
            "SELECT dataset_version FROM operations.active_dataset WHERE singleton"
        ).fetchone()[0]


def _restore_active_dataset(database_url: str, dataset_version: str | None) -> None:
    if dataset_version is None:
        return
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            """
            UPDATE operations.dataset_version SET status = 'active'
             WHERE dataset_version = %s
            """,
            (dataset_version,),
        )
        connection.execute(
            """
            UPDATE operations.active_dataset
               SET dataset_version = %s, activated_at = clock_timestamp()
             WHERE singleton
            """,
            (dataset_version,),
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_release_audit_executes_against_postgresql_schema(
    ingestion_admin_engine: AsyncEngine,
    ingestion_migrated_database_url: str,
) -> None:
    """Catches invalid SQL in the real aggregate and vector checks."""
    _purge_final_dataset(ingestion_migrated_database_url)
    with psycopg.connect(
        normalize_psycopg_url(ingestion_migrated_database_url)
    ) as connection:
        insert_building_dataset(connection, FINAL_DATASET_VERSION)
    try:
        async with ingestion_admin_engine.connect() as connection:
            audit = await _collect_release_audit(connection, FINAL_DATASET_VERSION)
        assert audit.dataset_status == "building"
        assert audit.dart_document_count == 0
        assert audit.vector_eligible_count == 0
        assert audit.vector_unapproved_count == 0
        assert len(audit.postgres_manifest_hash) == 64
        assert len(audit.evidence_manifest_hash) == 64
        assert len(audit.vector_manifest_hash) == 64
    finally:
        _purge_final_dataset(ingestion_migrated_database_url)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_release_records_four_components_then_activates_explicitly(
    ingestion_admin_engine: AsyncEngine,
    ingestion_migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _purge_final_dataset(ingestion_migrated_database_url)
    prior_active = _active_dataset(ingestion_migrated_database_url)
    with psycopg.connect(
        normalize_psycopg_url(ingestion_migrated_database_url)
    ) as connection:
        insert_building_dataset(connection, FINAL_DATASET_VERSION)

    async def collect(_connection, _dataset_version: str) -> FinalReleaseAudit:
        return _audit()

    monkeypatch.setattr(
        "financial_agent.ingestion.final_release._collect_release_audit",
        collect,
    )
    try:
        validated = await validate_and_activate_final_dataset(
            ingestion_admin_engine,
            inputs=_inputs(),
            activate=False,
        )

        assert validated.dataset_status == "validated"
        assert validated.activated is False
        async with ingestion_admin_engine.connect() as connection:
            assert await connection.scalar(
                sa.select(sa.func.count()).select_from(
                    operations.dataset_validation_run
                ).where(
                    operations.dataset_validation_run.c.dataset_version
                    == FINAL_DATASET_VERSION
                )
            ) == 1
            readiness = (
                await connection.execute(
                    sa.select(
                        operations.dataset_readiness.c.component,
                        operations.dataset_readiness.c.component_manifest_hash,
                    )
                    .where(
                        operations.dataset_readiness.c.dataset_version
                        == FINAL_DATASET_VERSION
                    )
                    .order_by(operations.dataset_readiness.c.component)
                )
            ).all()
            assert readiness == [
                ("evidence", EVIDENCE_HASH),
                ("graph", GRAPH_HASH),
                ("postgres", POSTGRES_HASH),
                ("vector", VECTOR_HASH),
            ]
            assert await connection.scalar(
                sa.select(operations.active_dataset.c.dataset_version).where(
                    operations.active_dataset.c.singleton.is_(True)
                )
            ) == prior_active

        activated = await validate_and_activate_final_dataset(
            ingestion_admin_engine,
            inputs=_inputs(),
            activate=True,
        )
        assert activated.dataset_status == "active"
        assert activated.activated is True
        async with ingestion_admin_engine.connect() as connection:
            assert await connection.scalar(
                sa.select(operations.active_dataset.c.dataset_version).where(
                    operations.active_dataset.c.singleton.is_(True)
                )
            ) == FINAL_DATASET_VERSION
            assert await connection.scalar(
                sa.select(sa.func.count()).select_from(
                    operations.dataset_validation_run
                ).where(
                    operations.dataset_validation_run.c.dataset_version
                    == FINAL_DATASET_VERSION
                )
            ) == 1
    finally:
        _purge_final_dataset(ingestion_migrated_database_url)
        _restore_active_dataset(ingestion_migrated_database_url, prior_active)


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"dart_chunk_count": 40_148}, "DART_COUNT_MISMATCH"),
        ({"vector_missing_count": 1}, "VECTOR_RECONCILIATION_FAILED"),
        ({"nport_source_count": 0}, "NPORT_SOURCE_MISSING"),
        ({"postgres_manifest_hash": "f" * 64}, "POSTGRES_MANIFEST_MISMATCH"),
        ({"evidence_manifest_hash": "f" * 64}, "EVIDENCE_MANIFEST_MISMATCH"),
        ({"vector_manifest_hash": "f" * 64}, "VECTOR_MANIFEST_MISMATCH"),
    ],
)
async def test_release_failure_leaves_building_dataset_unchanged(
    ingestion_admin_engine: AsyncEngine,
    ingestion_migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict[str, object],
    code: str,
) -> None:
    _purge_final_dataset(ingestion_migrated_database_url)
    with psycopg.connect(
        normalize_psycopg_url(ingestion_migrated_database_url)
    ) as connection:
        insert_building_dataset(connection, FINAL_DATASET_VERSION)

    async def collect(_connection, _dataset_version: str) -> FinalReleaseAudit:
        return replace(_audit(), **mutation)

    monkeypatch.setattr(
        "financial_agent.ingestion.final_release._collect_release_audit",
        collect,
    )
    try:
        with pytest.raises(FinalReleaseError, match=code):
            await validate_and_activate_final_dataset(
                ingestion_admin_engine,
                inputs=_inputs(),
                activate=True,
            )
        async with ingestion_admin_engine.connect() as connection:
            assert await connection.scalar(
                sa.select(operations.dataset_version.c.status).where(
                    operations.dataset_version.c.dataset_version
                    == FINAL_DATASET_VERSION
                )
            ) == "building"
            assert await connection.scalar(
                sa.select(sa.func.count()).select_from(
                    operations.dataset_validation_run
                ).where(
                    operations.dataset_validation_run.c.dataset_version
                    == FINAL_DATASET_VERSION
                )
            ) == 0
    finally:
        _purge_final_dataset(ingestion_migrated_database_url)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_activation_refuses_incomplete_existing_readiness(
    ingestion_admin_engine: AsyncEngine,
    ingestion_migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _purge_final_dataset(ingestion_migrated_database_url)
    with psycopg.connect(
        normalize_psycopg_url(ingestion_migrated_database_url)
    ) as connection:
        insert_building_dataset(connection, FINAL_DATASET_VERSION)

    async def collect(_connection, _dataset_version: str) -> FinalReleaseAudit:
        return _audit()

    monkeypatch.setattr(
        "financial_agent.ingestion.final_release._collect_release_audit",
        collect,
    )
    try:
        await validate_and_activate_final_dataset(
            ingestion_admin_engine,
            inputs=_inputs(),
            activate=False,
        )
        with psycopg.connect(
            normalize_psycopg_url(ingestion_migrated_database_url)
        ) as connection:
            connection.execute("SET LOCAL session_replication_role = replica")
            connection.execute(
                """
                DELETE FROM operations.dataset_readiness
                 WHERE dataset_version = %s AND component = 'graph'
                """,
                (FINAL_DATASET_VERSION,),
            )

        with pytest.raises(FinalReleaseError, match="READINESS_INCOMPLETE"):
            await validate_and_activate_final_dataset(
                ingestion_admin_engine,
                inputs=_inputs(),
                activate=True,
            )
    finally:
        _purge_final_dataset(ingestion_migrated_database_url)


def test_graph_release_loader_rejects_failed_or_fabricated_report(
    tmp_path: Path,
) -> None:
    manifest = {
        "schema_version": "2",
        "dataset_version": FINAL_DATASET_VERSION,
        "validation_report_hash": "b" * 64,
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    (tmp_path / "manifest.json").write_bytes(manifest_bytes)
    (tmp_path / "validation.json").write_bytes(b'{"conforms":false}')
    (tmp_path / "report.json").write_text(
        json.dumps(
            {
                "component_manifest_hash": sha256(manifest_bytes).hexdigest(),
                "conforms": False,
                "dataset_version": FINAL_DATASET_VERSION,
                "validation_backend": "jena",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FinalReleaseError, match="GRAPH_VALIDATION_FAILED"):
        load_graph_release_manifest_hash(
            tmp_path,
            dataset_version=FINAL_DATASET_VERSION,
        )


def test_graph_release_loader_accepts_bound_jena_outputs(tmp_path: Path) -> None:
    validation = b'{"conforms":true}'
    manifest = {
        "schema_version": "2",
        "dataset_version": FINAL_DATASET_VERSION,
        "validation_report_hash": sha256(validation).hexdigest(),
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    manifest_hash = sha256(manifest_bytes).hexdigest()
    (tmp_path / "manifest.json").write_bytes(manifest_bytes)
    (tmp_path / "validation.json").write_bytes(validation)
    (tmp_path / "report.json").write_text(
        json.dumps(
            {
                "component_manifest_hash": manifest_hash,
                "conforms": True,
                "dataset_version": FINAL_DATASET_VERSION,
                "validation_backend": "jena",
                "validation_report_hash": sha256(validation).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    assert load_graph_release_manifest_hash(
        tmp_path,
        dataset_version=FINAL_DATASET_VERSION,
    ) == manifest_hash


def test_finalize_cli_defaults_to_validation_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    graph_directory = tmp_path / "graph"
    graph_directory.mkdir()
    monkeypatch.setenv(
        "FINANCIAL_AGENT_BUILD_DATABASE_URL",
        "postgresql://database.invalid/financial_agent",
    )
    monkeypatch.setenv("FINANCIAL_AGENT_DATASET_VERSION", FINAL_DATASET_VERSION)
    monkeypatch.setenv(
        "FINANCIAL_AGENT_GRAPH_RELEASE_DIRECTORY", str(graph_directory)
    )
    monkeypatch.setenv("FINANCIAL_AGENT_POSTGRES_COMPONENT_HASH", POSTGRES_HASH)
    monkeypatch.setenv("FINANCIAL_AGENT_VECTOR_COMPONENT_HASH", VECTOR_HASH)
    monkeypatch.setenv("FINANCIAL_AGENT_EVIDENCE_COMPONENT_HASH", EVIDENCE_HASH)
    observed: dict[str, object] = {}

    class Engine:
        async def dispose(self) -> None:
            observed["disposed"] = True

    monkeypatch.setattr(cli, "create_async_engine", lambda *args, **kwargs: Engine())
    monkeypatch.setattr(
        cli,
        "load_graph_release_manifest_hash",
        lambda directory, *, dataset_version: GRAPH_HASH,
    )

    async def finalize(engine, *, inputs: FinalReleaseInputs, activate: bool):
        observed["engine"] = engine
        observed["inputs"] = inputs
        observed["activate"] = activate
        return type(
            "Report",
            (),
            {
                "dataset_version": FINAL_DATASET_VERSION,
                "dataset_status": "validated",
                "activated": False,
                "validation_run_id": "final-release:test",
                "report_hash": "f" * 64,
            },
        )()

    monkeypatch.setattr(cli, "validate_and_activate_final_dataset", finalize)

    assert cli.main(["finalize-stage03-stage04"]) == 0
    assert observed["activate"] is False
    assert observed["inputs"] == _inputs()
    assert observed["disposed"] is True
    output = capsys.readouterr().out
    assert "status=validated activated=0" in output
    assert "database.invalid" not in output
