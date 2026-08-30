from __future__ import annotations

from datetime import date
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.repositories.document_targets import DocumentTargetRepository
from financial_agent.documents import DocumentRole
from tests.fixtures.db.synthetic_dataset import (
    insert_building_dataset,
    insert_entity,
    insert_identifier,
    insert_product,
    insert_relation,
)


CUTOFF = date(2026, 8, 24)


def test_compiled_queries_join_each_dataset_scoped_table_by_dataset_version() -> None:
    repository = DocumentTargetRepository(None)  # type: ignore[arg-type]
    statements = repository.compiled_statements("facts-v1")

    compiled_sql = "\n".join(
        str(statement.compile(compile_kwargs={"literal_binds": True}))
        for statement in statements
    )

    assert all(statement.is_select for statement in statements)
    assert not hasattr(repository, "append")
    assert not hasattr(repository, "update")
    assert "catalog.product.dataset_version = catalog.entity.dataset_version" in compiled_sql
    assert "catalog.identifier.dataset_version = catalog.entity.dataset_version" in compiled_sql
    assert "relation.relation_record.dataset_version = catalog.product.dataset_version" in compiled_sql
    assert "relation.relation_record.dataset_version = index_entity.dataset_version" in compiled_sql
    assert "index_identifier.dataset_version = index_entity.dataset_version" in compiled_sql


@pytest.mark.asyncio
async def test_blank_dataset_version_is_rejected_before_query() -> None:
    repository = DocumentTargetRepository(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="dataset_version"):
        await repository.list_targets(" ", cutoff_date=CUTOFF)


class _MappingsResult:
    def __init__(self, rows: list[dict[str, str | None]]) -> None:
        self._rows = rows

    def mappings(self) -> _MappingsResult:
        return self

    def all(self) -> list[dict[str, str | None]]:
        return self._rows


class _DuplicateIdentifierConnection:
    def __init__(self) -> None:
        self._results = [
            _MappingsResult(
                [
                    {
                        "entity_id": "product-1",
                        "entity_type": "product",
                        "canonical_name": "Product One",
                        "product_family": "domestic_etf",
                        "scheme": "ISIN",
                        "identifier_value": "KR0000000001",
                    },
                    {
                        "entity_id": "product-1",
                        "entity_type": "product",
                        "canonical_name": "Product One",
                        "product_family": "domestic_etf",
                        "scheme": "ISIN",
                        "identifier_value": "KR0000000001",
                    },
                ]
            ),
            _MappingsResult([]),
        ]

    async def execute(self, _statement: object) -> _MappingsResult:
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_duplicate_identifier_rows_yield_one_exact_identifier() -> None:
    repository = DocumentTargetRepository(_DuplicateIdentifierConnection())  # type: ignore[arg-type]

    targets = await repository.list_targets("facts-v1", cutoff_date=CUTOFF)

    assert targets[0].identifiers == (("ISIN", "KR0000000001"),)


def _token() -> str:
    return uuid4().hex


def _prepare_target_scope(database_url: str) -> str:
    dataset_version = f"facts-{_token()}"
    foreign_dataset_version = f"foreign-{_token()}"
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        insert_building_dataset(connection, dataset_version)
        insert_building_dataset(connection, foreign_dataset_version)
        for entity_id, product_family in (
            ("bond-1", "domestic_bond"),
            ("domestic-etf-1", "domestic_etf"),
            ("domestic-etf-2", "domestic_etf"),
            ("overseas-etf-1", "overseas_etf"),
            ("public-fund-1", "public_fund"),
        ):
            insert_entity(
                connection,
                dataset_version=dataset_version,
                entity_id=entity_id,
            )
            insert_product(
                connection,
                dataset_version=dataset_version,
                entity_id=entity_id,
                product_family=product_family,
            )
            insert_identifier(
                connection,
                dataset_version=dataset_version,
                identifier_id=f"id-{entity_id}",
                entity_id=entity_id,
                scheme="ISIN",
                identifier_value=f"KR-{entity_id}",
            )
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id="index-space",
            entity_type="index",
        )
        insert_identifier(
            connection,
            dataset_version=dataset_version,
            identifier_id="id-index-space",
            entity_id="index-space",
            scheme="INDEX_CODE",
            identifier_value="SPACE",
        )
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id="not-an-index",
            entity_type="theme",
        )
        insert_relation(
            connection,
            dataset_version=dataset_version,
            relation_id="tracks-1",
            subject_id="domestic-etf-1",
            predicate_id="tracksIndex",
            object_id="index-space",
        )
        insert_relation(
            connection,
            dataset_version=dataset_version,
            relation_id="tracks-2",
            subject_id="domestic-etf-2",
            predicate_id="tracksIndex",
            object_id="index-space",
        )
        insert_relation(
            connection,
            dataset_version=dataset_version,
            relation_id="tracks-not-index",
            subject_id="public-fund-1",
            predicate_id="tracksIndex",
            object_id="not-an-index",
        )
        insert_entity(
            connection,
            dataset_version=foreign_dataset_version,
            entity_id="domestic-etf-1",
        )
        insert_identifier(
            connection,
            dataset_version=foreign_dataset_version,
            identifier_id="foreign-id-domestic-etf-1",
            entity_id="domestic-etf-1",
            scheme="ISIN",
            identifier_value="FOREIGN-ONLY",
        )
    return dataset_version


@pytest_asyncio.fixture
async def repository_engine(migrated_database_url: str) -> AsyncEngine:
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    yield engine
    await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_lists_all_product_and_unique_index_targets(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version = _prepare_target_scope(migrated_database_url)
    async with repository_engine.connect() as connection:
        targets = await DocumentTargetRepository(connection).list_targets(
            dataset_version,
            cutoff_date=CUTOFF,
        )

    assert [
        (item.entity_id, item.required_role)
        for item in targets
    ] == [
        ("bond-1", DocumentRole.PRODUCT_SUMMARY),
        ("domestic-etf-1", DocumentRole.PRODUCT_SUMMARY),
        ("domestic-etf-2", DocumentRole.PRODUCT_SUMMARY),
        ("index-space", DocumentRole.INDEX_METHODOLOGY),
        ("overseas-etf-1", DocumentRole.PRODUCT_SUMMARY),
        ("public-fund-1", DocumentRole.PRODUCT_SUMMARY),
    ]
    assert sum(item.entity_id == "index-space" for item in targets) == 1
    assert targets[1].identifiers == (("ISIN", "KR-domestic-etf-1"),)
    assert all(("ISIN", "FOREIGN-ONLY") not in item.identifiers for item in targets)
