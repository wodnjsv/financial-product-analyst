from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.schema.catalog import entity
from financial_agent.db.schema.evidence import source_record
from financial_agent.db.schema import operations
from financial_agent.db.schema.operations import dataset_version as dataset_version_table
from financial_agent.ingestion.final_rebuild import (
    FINAL_DATASET_VERSION,
    FinalRebuildError,
    remove_incomplete_final_dataset,
)
from financial_agent.ingestion import cli
from tests.fixtures.db.synthetic_dataset import (
    VALID_MANIFEST_HASH,
    VALID_RECORD_HASH,
    insert_building_dataset,
    insert_entity,
    insert_product,
)


def _insert_source(connection: psycopg.Connection, dataset_version: str) -> None:
    insert_entity(
        connection,
        dataset_version=dataset_version,
        entity_id="publisher",
        entity_type="institution",
    )
    connection.execute(
        """
        INSERT INTO catalog.institution (
            dataset_version, entity_id, institution_kind
        ) VALUES (%s, 'publisher', 'regulator')
        """,
        (dataset_version,),
    )
    connection.execute(
        """
        INSERT INTO evidence.source_record (
            dataset_version, source_id, publisher, publisher_type,
            source_title, source_type, authority_tier, source_locator_root,
            content_checksum, eligible_for_claim, record_hash, created_at
        ) VALUES (
            %s, 'source', 'publisher', 'regulator', 'Synthetic source',
            'official_filing', 'primary', 'synthetic://source', %s, true, %s, %s
        )
        """,
        (
            dataset_version,
            VALID_MANIFEST_HASH,
            VALID_RECORD_HASH,
            datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )


@pytest.mark.asyncio
async def test_cleanup_rejects_any_dataset_name_other_than_exact_final() -> None:
    """Catches a broadened cleanup scope that could delete arbitrary datasets."""
    with pytest.raises(FinalRebuildError, match="TARGET_VERSION_NOT_ALLOWED"):
        await remove_incomplete_final_dataset(  # type: ignore[arg-type]
            object(),
            dataset_version="another-building-version",
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_cleanup_removes_only_exact_inactive_building_target(
    ingestion_admin_engine: AsyncEngine,
    ingestion_migrated_database_url: str,
) -> None:
    preserved = f"cleanup-preserved-{uuid4().hex}"
    with psycopg.connect(
        normalize_psycopg_url(ingestion_migrated_database_url)
    ) as connection:
        insert_building_dataset(connection, FINAL_DATASET_VERSION)
        insert_product(
            connection,
            dataset_version=FINAL_DATASET_VERSION,
            entity_id="target-product",
            product_family="domestic_etf",
        )
        _insert_source(connection, FINAL_DATASET_VERSION)
        insert_building_dataset(connection, preserved)
        insert_product(
            connection,
            dataset_version=preserved,
            entity_id="preserved-product",
            product_family="public_fund",
        )
        _insert_source(connection, preserved)

    report = await remove_incomplete_final_dataset(
        ingestion_admin_engine,
        dataset_version=FINAL_DATASET_VERSION,
    )

    assert report.dataset_version == FINAL_DATASET_VERSION
    assert report.deleted_counts["operations.dataset_version"] == 1
    assert report.deleted_counts["catalog.product"] == 1
    assert report.deleted_counts["catalog.entity"] == 2
    assert report.deleted_counts["evidence.source_record"] == 1
    async with ingestion_admin_engine.connect() as connection:
        assert (
            await connection.execute(
                sa.select(sa.func.count())
                .select_from(dataset_version_table)
                .where(dataset_version_table.c.dataset_version == FINAL_DATASET_VERSION)
            )
        ).scalar_one() == 0
        assert (
            await connection.execute(
                sa.select(sa.func.count())
                .select_from(entity)
                .where(entity.c.dataset_version == preserved)
            )
        ).scalar_one() == 2
        assert (
            await connection.execute(
                sa.select(sa.func.count())
                .select_from(source_record)
                .where(source_record.c.dataset_version == preserved)
            )
        ).scalar_one() == 1


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_state", ["active", "passed_validation"])
async def test_cleanup_refuses_active_or_successfully_validated_target(
    ingestion_admin_engine: AsyncEngine,
    ingestion_migrated_database_url: str,
    blocked_state: str,
) -> None:
    with psycopg.connect(
        normalize_psycopg_url(ingestion_migrated_database_url)
    ) as connection:
        insert_building_dataset(connection, FINAL_DATASET_VERSION)
        if blocked_state == "active":
            connection.execute("SET LOCAL session_replication_role = replica")
            connection.execute(
                """
                UPDATE operations.dataset_version
                   SET status = 'active'
                 WHERE dataset_version = %s
                """,
                (FINAL_DATASET_VERSION,),
            )
            connection.execute(
                """
                UPDATE operations.active_dataset
                   SET dataset_version = %s, activated_at = %s
                 WHERE singleton
                """,
                (FINAL_DATASET_VERSION, datetime(2026, 9, 1, tzinfo=UTC)),
            )
        else:
            connection.execute(
                """
                INSERT INTO operations.dataset_validation_run (
                    validation_run_id, dataset_version, dataset_manifest_hash,
                    validator_id, validator_version, started_at, finished_at,
                    status, report_hash
                ) VALUES (
                    'passed-run', %s, %s, 'test', '1', %s, %s, 'pass', %s
                )
                """,
                (
                    FINAL_DATASET_VERSION,
                    VALID_MANIFEST_HASH,
                    datetime(2026, 9, 1, tzinfo=UTC),
                    datetime(2026, 9, 1, 0, 1, tzinfo=UTC),
                    VALID_RECORD_HASH,
                ),
            )

    expected = (
        "TARGET_NOT_BUILDING"
        if blocked_state == "active"
        else "TARGET_HAS_SUCCESSFUL_VALIDATION"
    )
    with pytest.raises(FinalRebuildError, match=expected):
        await remove_incomplete_final_dataset(
            ingestion_admin_engine,
            dataset_version=FINAL_DATASET_VERSION,
        )

    async with ingestion_admin_engine.begin() as connection:
        await connection.execute(
            sa.text("SET LOCAL session_replication_role = replica")
        )
        if blocked_state == "active":
            await connection.execute(
                sa.update(operations.active_dataset)
                .where(operations.active_dataset.c.singleton.is_(True))
                .values(dataset_version=None, activated_at=None)
            )
            await connection.execute(
                sa.update(dataset_version_table)
                .where(
                    dataset_version_table.c.dataset_version
                    == FINAL_DATASET_VERSION
                )
                .values(status="building", activated_at=None)
            )
        else:
            await connection.execute(
                sa.delete(operations.dataset_validation_run).where(
                    operations.dataset_validation_run.c.dataset_version
                    == FINAL_DATASET_VERSION
                )
            )
    await remove_incomplete_final_dataset(
        ingestion_admin_engine,
        dataset_version=FINAL_DATASET_VERSION,
    )


@pytest.mark.asyncio
async def test_reset_cli_uses_only_explicit_final_target(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Catches the CLI selecting a default, source, or caller-broadened target."""
    monkeypatch.setenv(
        "FINANCIAL_AGENT_BUILD_DATABASE_URL",
        "postgresql://database.invalid/financial_agent",
    )
    monkeypatch.setenv("FINANCIAL_AGENT_DATASET_VERSION", FINAL_DATASET_VERSION)
    observed: dict[str, object] = {}

    class Engine:
        async def dispose(self) -> None:
            observed["disposed"] = True

    engine = Engine()
    monkeypatch.setattr(cli, "create_async_engine", lambda *args, **kwargs: engine)

    async def remove(candidate, *, dataset_version: str):
        observed["engine"] = candidate
        observed["dataset_version"] = dataset_version
        return SimpleNamespace(
            dataset_version=dataset_version,
            deleted_counts={"catalog.entity": 2, "operations.dataset_version": 1},
        )

    monkeypatch.setattr(cli, "remove_incomplete_final_dataset", remove)

    assert await cli._reset_incomplete_final_command() == 0
    assert observed == {
        "engine": engine,
        "dataset_version": FINAL_DATASET_VERSION,
        "disposed": True,
    }
    assert capsys.readouterr().out == (
        "FINAL_DATASET_RESET_OK dataset=competition-2026-08-24-final-v1 "
        "deleted=3 tables=2\n"
    )
