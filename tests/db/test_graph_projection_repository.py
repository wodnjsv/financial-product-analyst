from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg.types.json import Jsonb
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.graph.contract import (
    EntityProjection,
    EvidenceProjection,
    RelationMetricProjection,
    RelationProjection,
    SourceProjection,
)
from financial_agent.graph.repository import (
    GraphProjectionLoadError,
    GraphProjectionRepository,
)
from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_RECORD_HASH,
    insert_building_dataset,
    insert_entity,
)


pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
_TAGGED = Jsonb({"type": "string", "value": "synthetic"})


def _insert_product(connection, dataset_version: str, entity_id: str, family: str) -> None:
    insert_entity(connection, dataset_version=dataset_version, entity_id=entity_id)
    connection.execute(
        """
        INSERT INTO catalog.product (
            dataset_version, entity_id, product_family, primary_currency
        ) VALUES (%s, %s, %s, 'KRW')
        """,
        (dataset_version, entity_id, family),
    )


def _insert_institution(
    connection, dataset_version: str, entity_id: str, institution_kind: str
) -> None:
    insert_entity(
        connection,
        dataset_version=dataset_version,
        entity_id=entity_id,
        entity_type="institution",
    )
    connection.execute(
        """
        INSERT INTO catalog.institution (
            dataset_version, entity_id, institution_kind
        ) VALUES (%s, %s, %s)
        """,
        (dataset_version, entity_id, institution_kind),
    )


def _insert_source(connection, dataset_version: str, publisher: str) -> None:
    connection.execute(
        """
        INSERT INTO evidence.source_record (
            dataset_version, source_id, publisher, publisher_type,
            source_title, source_type, authority_tier, source_locator_root,
            content_checksum, eligible_for_claim, record_hash, created_at
        ) VALUES (%s, 'source-one', %s, 'exchange', 'Synthetic source',
                  'dataset', 'official', 'synthetic/source', %s, true, %s, %s)
        """,
        (dataset_version, publisher, "c" * 64, VALID_RECORD_HASH, CREATED_AT),
    )


def _insert_relation_with_evidence(
    connection,
    dataset_version: str,
    *,
    relation_id: str,
    subject_id: str,
    predicate_id: str,
    object_id: str,
    evidence_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO relation.relation_record (
            dataset_version, relation_id, subject_id, predicate_id, object_id,
            valid_from, valid_to, record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, DATE '2026-01-01', NULL, %s, %s)
        """,
        (
            dataset_version,
            relation_id,
            subject_id,
            predicate_id,
            object_id,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO evidence.evidence_record (
            dataset_version, evidence_id, evidence_kind, source_id, subject_id,
            predicate_id, value_or_object_id, normalized_value,
            applicable_date, valid_from, locator_type,
            locator_uri_or_object_key, parser_version, mapping_version,
            cutoff_status, record_hash, created_at
        ) VALUES (%s, %s, 'relation', 'source-one', %s, %s, %s, %s,
                  DATE '2026-08-23', DATE '2026-01-01', 'tabular',
                  'synthetic://graph', 'parser.v1', 'mapping.v1', 'eligible',
                  %s, %s)
        """,
        (
            dataset_version,
            evidence_id,
            subject_id,
            predicate_id,
            _TAGGED,
            _TAGGED,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO evidence.evidence_relation_origin (
            dataset_version, evidence_id, relation_id
        ) VALUES (%s, %s, %s)
        """,
        (dataset_version, evidence_id, relation_id),
    )


def _insert_metric_definition(connection, metric_id: str, version: str, kind: str) -> None:
    connection.execute(
        """
        INSERT INTO observation.metric_definition (
            metric_id, definition_version, semantic_family, value_kind,
            default_unit, definition_hash, approved_at
        ) VALUES (%s, %s, 'graph-test', %s, NULL, %s, %s)
        ON CONFLICT (metric_id, definition_version) DO NOTHING
        """,
        (metric_id, version, kind, "d" * 64, CREATED_AT),
    )


def _insert_product_type(
    connection,
    dataset_version: str,
    entity_id: str,
    value: str,
    definition_version: str,
    ordinal: int = 1,
) -> None:
    connection.execute(
        """
        INSERT INTO observation.observation_record (
            dataset_version, observation_id, entity_id, relation_id, metric_id,
            metric_definition_version, value_status, text_value, applicable_date,
            record_hash, created_at
        ) VALUES (%s, %s, %s, NULL, 'product_type', %s, 'present', %s,
                  DATE '2026-08-24', %s, %s)
        """,
        (
            dataset_version,
            f"product-type-{entity_id}-{ordinal}",
            entity_id,
            definition_version,
            value,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def _seed_projection(database_url: str) -> str:
    dataset_version = f"graph-{uuid4().hex}"
    definition_version = f"graph-{uuid4().hex}"
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        insert_building_dataset(connection, dataset_version)
        _insert_product(connection, dataset_version, "z-etf", "domestic_etf")
        _insert_product(connection, dataset_version, "a-representative", "public_fund")
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id="m-security",
            entity_type="security",
        )
        connection.execute(
            """
            INSERT INTO catalog.security (
                dataset_version, entity_id, security_kind, ticker_display
            ) VALUES (%s, 'm-security', 'listed_equity', 'SYN')
            """,
            (dataset_version,),
        )
        _insert_institution(connection, dataset_version, "b-manager", "asset_manager")
        _insert_institution(connection, dataset_version, "y-market", "exchange")
        _insert_source(connection, dataset_version, "y-market")
        connection.execute(
            """
            INSERT INTO catalog.identifier (
                dataset_version, identifier_id, entity_id, scheme,
                identifier_value, is_primary, record_hash, created_at
            ) VALUES (%s, 'fund-share-id', 'z-etf', 'PRFD_ITM_NO',
                      'SYN-SHARE', true, %s, %s)
            """,
            (dataset_version, VALID_RECORD_HASH, CREATED_AT),
        )
        _insert_metric_definition(connection, "product_type", definition_version, "text")
        _insert_metric_definition(
            connection,
            "official_holding_weight_pct",
            definition_version,
            "numeric",
        )
        _insert_metric_definition(
            connection,
            "holding_weight_like_but_unapproved",
            definition_version,
            "numeric",
        )
        _insert_product_type(
            connection,
            dataset_version,
            "z-etf",
            "ETF",
            definition_version,
        )
        _insert_relation_with_evidence(
            connection,
            dataset_version,
            relation_id="rel-b-share-class",
            subject_id="a-representative",
            predicate_id="hasShareClass",
            object_id="z-etf",
            evidence_id="evidence-b",
        )
        _insert_relation_with_evidence(
            connection,
            dataset_version,
            relation_id="rel-a-holding",
            subject_id="z-etf",
            predicate_id="holdsSecurity",
            object_id="m-security",
            evidence_id="evidence-a",
        )
        connection.execute(
            """
            INSERT INTO observation.observation_record (
                dataset_version, observation_id, entity_id, relation_id,
                metric_id, metric_definition_version, value_status,
                numeric_value, unit, applicable_date, record_hash, created_at
            ) VALUES
                (%s, 'weight-approved', NULL, 'rel-a-holding',
                 'official_holding_weight_pct', %s, 'zero', 0,
                 'percentage_point', DATE '2026-08-23', %s, %s),
                (%s, 'weight-unapproved', NULL, 'rel-a-holding',
                 'holding_weight_like_but_unapproved', %s, 'present', 91,
                 'percentage_point', DATE '2026-08-23', %s, %s)
            """,
            (
                dataset_version,
                definition_version,
                VALID_RECORD_HASH,
                CREATED_AT,
                dataset_version,
                definition_version,
                VALID_RECORD_HASH,
                CREATED_AT,
            ),
        )
    return dataset_version


def _snapshot_operations(database_url: str) -> tuple[list[tuple], list[tuple]]:
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        readiness = connection.execute(
            """
            SELECT dataset_version, component, validation_run_id,
                   component_manifest_hash
            FROM operations.dataset_readiness
            ORDER BY dataset_version, component
            """
        ).fetchall()
        active = connection.execute(
            """
            SELECT singleton, dataset_version, activated_at
            FROM operations.active_dataset
            ORDER BY singleton
            """
        ).fetchall()
    return readiness, active


@pytest_asyncio.fixture
async def repository_engine(migrated_database_url: str) -> Iterator[AsyncEngine]:
    engine = create_async_engine(migrated_database_url, pool_size=2, max_overflow=0)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    yield engine
    await engine.dispose()


async def test_load_projects_one_version_with_exact_types_metrics_and_stable_sorting(
    migrated_database_url: str,
    repository_engine: AsyncEngine,
) -> None:
    dataset_version = _seed_projection(migrated_database_url)
    before_operations = _snapshot_operations(migrated_database_url)
    statements: list[str] = []
    rollbacks: list[bool] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many) -> None:
        statements.append(" ".join(statement.split()))

    def capture_rollback(_conn) -> None:
        rollbacks.append(True)

    event.listen(repository_engine.sync_engine, "before_cursor_execute", capture_statement)
    event.listen(repository_engine.sync_engine, "rollback", capture_rollback)
    try:
        repository = GraphProjectionRepository(repository_engine)
        first = await repository.load(dataset_version)
        second = await repository.load(dataset_version)
    finally:
        event.remove(repository_engine.sync_engine, "before_cursor_execute", capture_statement)
        event.remove(repository_engine.sync_engine, "rollback", capture_rollback)

    assert first == second
    assert first.dataset_version == dataset_version
    assert first.cutoff_date.isoformat() == "2026-08-24"
    assert first.entities == (
        EntityProjection(
            dataset_version,
            "a-representative",
            ("FinancialProduct", "PublicFund", "RepresentativeFund"),
        ),
        EntityProjection(dataset_version, "b-manager", ("AssetManager", "Organization")),
        EntityProjection(dataset_version, "m-security", ("EquitySecurity", "Security")),
        EntityProjection(dataset_version, "y-market", ("Market", "Organization")),
        EntityProjection(
            dataset_version,
            "z-etf",
            ("DomesticETF", "ETF", "FinancialProduct", "FundShareClass"),
        ),
    )
    assert first.sources == (SourceProjection(dataset_version, "source-one", "y-market"),)
    assert first.evidences == (
        EvidenceProjection(
            dataset_version,
            "evidence-a",
            "source-one",
            datetime(2026, 8, 23, tzinfo=UTC).date(),
            datetime(2026, 1, 1, tzinfo=UTC).date(),
            None,
            None,
            None,
            "eligible",
        ),
        EvidenceProjection(
            dataset_version,
            "evidence-b",
            "source-one",
            datetime(2026, 8, 23, tzinfo=UTC).date(),
            datetime(2026, 1, 1, tzinfo=UTC).date(),
            None,
            None,
            None,
            "eligible",
        ),
    )
    assert first.relations == (
        RelationProjection(
            dataset_version,
            "rel-a-holding",
            "z-etf",
            "holdsSecurity",
            "m-security",
            datetime(2026, 1, 1, tzinfo=UTC).date(),
            None,
            ("evidence-a",),
            (
                RelationMetricProjection(
                    dataset_version,
                    "rel-a-holding",
                    "official_holding_weight_pct",
                    Decimal("0E-12"),
                    "percentage_point",
                    datetime(2026, 8, 23, tzinfo=UTC).date(),
                ),
            ),
        ),
        RelationProjection(
            dataset_version,
            "rel-b-share-class",
            "a-representative",
            "hasShareClass",
            "z-etf",
            datetime(2026, 1, 1, tzinfo=UTC).date(),
            None,
            ("evidence-b",),
        ),
    )
    assert statements[0].upper() == "SET TRANSACTION READ ONLY"
    assert all(
        statement.upper().startswith(("SELECT ", "SET TRANSACTION READ ONLY"))
        for statement in statements
    )
    assert len(rollbacks) >= 2
    assert repository_engine.sync_engine.pool.checkedout() == 0
    assert _snapshot_operations(migrated_database_url) == before_operations


async def test_load_returns_an_empty_exact_version_and_rejects_a_missing_version(
    migrated_database_url: str,
    repository_engine: AsyncEngine,
) -> None:
    dataset_version = f"graph-empty-{uuid4().hex}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_building_dataset(connection, dataset_version)
    repository = GraphProjectionRepository(repository_engine)

    batch = await repository.load(dataset_version)
    assert batch.dataset_version == dataset_version
    assert batch.entities == batch.sources == batch.evidences == batch.relations == ()

    rollbacks: list[bool] = []

    def capture_rollback(_connection) -> None:
        rollbacks.append(True)

    event.listen(repository_engine.sync_engine, "rollback", capture_rollback)
    try:
        with pytest.raises(GraphProjectionLoadError, match="dataset_version"):
            await repository.load(f"missing-{uuid4().hex}")
    finally:
        event.remove(repository_engine.sync_engine, "rollback", capture_rollback)
    assert rollbacks
    assert repository_engine.sync_engine.pool.checkedout() == 0


async def test_load_rejects_a_non_finite_approved_relation_metric(
    migrated_database_url: str,
    repository_engine: AsyncEngine,
) -> None:
    dataset_version = _seed_projection(migrated_database_url)
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        connection.execute(
            """
            UPDATE observation.observation_record
            SET value_status = 'present', numeric_value = 'NaN'::numeric
            WHERE dataset_version = %s AND observation_id = 'weight-approved'
            """,
            (dataset_version,),
        )

    with pytest.raises(GraphProjectionLoadError, match="metric"):
        await GraphProjectionRepository(repository_engine).load(dataset_version)
    assert repository_engine.sync_engine.pool.checkedout() == 0


@pytest.mark.parametrize("product_types", [(), ("ETF", "ETN")])
async def test_load_fails_closed_when_relation_typing_facts_are_missing_or_conflicting(
    migrated_database_url: str,
    repository_engine: AsyncEngine,
    product_types: tuple[str, ...],
) -> None:
    dataset_version = f"graph-invalid-{uuid4().hex}"
    definition_version = f"graph-{uuid4().hex}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_building_dataset(connection, dataset_version)
        _insert_product(connection, dataset_version, "etp", "domestic_etf")
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id="index-one",
            entity_type="index",
        )
        _insert_institution(connection, dataset_version, "publisher", "exchange")
        _insert_source(connection, dataset_version, "publisher")
        _insert_metric_definition(connection, "product_type", definition_version, "text")
        for ordinal, product_type in enumerate(product_types, start=1):
            _insert_product_type(
                connection,
                dataset_version,
                "etp",
                product_type,
                definition_version,
                ordinal,
            )
        _insert_relation_with_evidence(
            connection,
            dataset_version,
            relation_id="tracks",
            subject_id="etp",
            predicate_id="tracksIndex",
            object_id="index-one",
            evidence_id="evidence-tracks",
        )

    with pytest.raises(GraphProjectionLoadError, match="type"):
        await GraphProjectionRepository(repository_engine).load(dataset_version)
    assert repository_engine.sync_engine.pool.checkedout() == 0
