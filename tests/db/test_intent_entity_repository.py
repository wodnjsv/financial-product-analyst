from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import os
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.intent.candidates import Mention
from financial_agent.intent.entity_repository import EntityCandidateRepository
from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_RECORD_HASH,
    insert_building_dataset,
)


if os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL") is None:
    pytest.skip(
        "FINANCIAL_AGENT_TEST_DATABASE_URL is not configured for the explicit PostgreSQL test.",
        allow_module_level=True,
    )


pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]


@dataclass(frozen=True, slots=True)
class SeededEntities:
    dataset_version: str
    samsung_id: str = "entity-samsung"


def mention(mention_id: str, text: str) -> Mention:
    return Mention(
        mention_id=mention_id,
        segment_id="s1",
        text=text,
        normalized_text=text,
        start_char=0,
        end_char=len(text),
    )


def _insert_entity(
    connection: psycopg.Connection,
    dataset_version: str,
    entity_id: str,
    normalized_name: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog.entity (
            dataset_version, entity_id, entity_type, canonical_name,
            normalized_name, record_hash, created_at
        ) VALUES (%s, %s, 'product', %s, %s, %s, %s)
        """,
        (
            dataset_version,
            entity_id,
            normalized_name,
            normalized_name,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO catalog.product (
            dataset_version, entity_id, product_family, primary_currency
        ) VALUES (%s, %s, 'domestic_etf', 'KRW')
        """,
        (dataset_version, entity_id),
    )


def _insert_alias(
    connection: psycopg.Connection,
    dataset_version: str,
    alias_id: str,
    entity_id: str,
    text: str,
    *,
    valid_to: date | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog.alias (
            dataset_version, alias_id, entity_id, alias_text,
            normalized_alias_text, valid_from, valid_to, record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, DATE '2026-01-01', %s, %s, %s)
        """,
        (
            dataset_version,
            alias_id,
            entity_id,
            text,
            text,
            valid_to,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


@pytest.fixture
def seeded_entities(migrated_database_url: str) -> SeededEntities:
    seeded = SeededEntities(dataset_version=f"intent-candidates-{uuid4().hex}")
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_building_dataset(connection, seeded.dataset_version)
        _insert_entity(connection, seeded.dataset_version, seeded.samsung_id, "삼성전자")
        connection.execute(
            """
            INSERT INTO catalog.identifier (
                dataset_version, identifier_id, entity_id, scheme, identifier_value,
                is_primary, valid_from, valid_to, record_hash, created_at
            ) VALUES (%s, 'identifier-samsung', %s, 'KRX', '005930', true,
                      DATE '2026-01-01', NULL, %s, %s)
            """,
            (seeded.dataset_version, seeded.samsung_id, VALID_RECORD_HASH, CREATED_AT),
        )
        _insert_alias(
            connection,
            seeded.dataset_version,
            "alias-samsung",
            seeded.samsung_id,
            "삼성전자",
        )
        _insert_entity(connection, seeded.dataset_version, "entity-alpha", "알파")
        _insert_entity(connection, seeded.dataset_version, "entity-beta", "베타")
        _insert_alias(
            connection, seeded.dataset_version, "alias-alpha", "entity-alpha", "동일명"
        )
        _insert_alias(
            connection, seeded.dataset_version, "alias-beta", "entity-beta", "동일명"
        )
        _insert_entity(connection, seeded.dataset_version, "entity-old", "구명칭")
        _insert_alias(
            connection,
            seeded.dataset_version,
            "alias-old",
            "entity-old",
            "구명칭",
            valid_to=date(2026, 8, 23),
        )
    return seeded


@pytest_asyncio.fixture
async def migrated_engine(migrated_database_url: str) -> AsyncEngine:
    engine = create_async_engine(migrated_database_url, pool_size=2, max_overflow=0)
    yield engine
    await engine.dispose()


async def test_entity_search_batches_mentions_and_pins_dataset(
    migrated_engine: AsyncEngine,
    seeded_entities: SeededEntities,
) -> None:
    """Catches per-mention queries, cross-version reads, or expired alias inclusion."""
    statement_count = 0

    def count_search_statements(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        nonlocal statement_count
        if "WITH mentions(mention_id, normalized_text)" in statement:
            statement_count += 1

    event.listen(
        migrated_engine.sync_engine,
        "before_cursor_execute",
        count_search_statements,
    )
    try:
        result = await EntityCandidateRepository(migrated_engine).search_batch(
            seeded_entities.dataset_version,
            (
                mention("m1", "005930"),
                mention("m2", "삼성전자"),
                mention("m3", "동일명"),
                mention("m4", "구명칭"),
            ),
        )
    finally:
        event.remove(
            migrated_engine.sync_engine,
            "before_cursor_execute",
            count_search_statements,
        )

    assert statement_count == 1
    assert result["m1"][0].match_kind == "exact_identifier"
    assert result["m2"][0].entity_id == seeded_entities.samsung_id
    assert [item.entity_id for item in result["m3"]] == [
        "entity-alpha",
        "entity-beta",
    ]
    assert result["m4"] == ()
    assert all(len(items) <= 5 for items in result.values())
