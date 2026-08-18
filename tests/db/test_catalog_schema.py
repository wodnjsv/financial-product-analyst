from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_RECORD_HASH,
    insert_building_dataset,
    insert_entity,
)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[psycopg.Connection]:
    from financial_agent.db.preflight import normalize_psycopg_url

    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as database_connection:
        yield database_connection
        database_connection.rollback()


@pytest.mark.postgres
def test_entity_id_is_unique_only_within_its_dataset_version(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "catalog-v1")
    insert_building_dataset(connection, "catalog-v2")
    insert_entity(
        connection,
        dataset_version="catalog-v1",
        entity_id="shared-product",
    )
    insert_entity(
        connection,
        dataset_version="catalog-v2",
        entity_id="shared-product",
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_entity(
            connection,
            dataset_version="catalog-v1",
            entity_id="shared-product",
        )


@pytest.mark.postgres
def test_subtype_cannot_reference_entity_from_another_dataset_version(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "catalog-v1")
    insert_building_dataset(connection, "catalog-v2")
    insert_entity(
        connection,
        dataset_version="catalog-v1",
        entity_id="product-v1",
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        connection.execute(
            """
            INSERT INTO catalog.product (
                dataset_version, entity_id, product_family, primary_currency
            ) VALUES ('catalog-v2', 'product-v1', 'domestic_bond', 'KRW')
            """
        )


@pytest.mark.postgres
def test_product_family_is_limited_to_the_four_supported_families(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "catalog-v1")
    insert_entity(
        connection,
        dataset_version="catalog-v1",
        entity_id="unsupported-family",
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            """
            INSERT INTO catalog.product (
                dataset_version, entity_id, product_family
            ) VALUES ('catalog-v1', 'unsupported-family', 'etn')
            """
        )


@pytest.mark.postgres
def test_product_requires_an_entity_with_product_type(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "catalog-v1")
    insert_entity(
        connection,
        dataset_version="catalog-v1",
        entity_id="security-entity",
        entity_type="security",
    )
    connection.execute(
        """
        INSERT INTO catalog.product (dataset_version, entity_id, product_family)
        VALUES ('catalog-v1', 'security-entity', 'domestic_bond')
        """
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
def test_identifier_cannot_be_reassigned_within_a_dataset_version(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "catalog-v1")
    insert_entity(
        connection,
        dataset_version="catalog-v1",
        entity_id="product-one",
    )
    insert_entity(
        connection,
        dataset_version="catalog-v1",
        entity_id="product-two",
    )
    connection.execute(
        """
        INSERT INTO catalog.identifier (
            dataset_version, identifier_id, entity_id, scheme, identifier_value,
            is_primary, record_hash, created_at
        ) VALUES (%s, 'identifier-one', 'product-one', 'isin', 'KR0000000001',
                  true, %s, %s)
        """,
        ("catalog-v1", VALID_RECORD_HASH, CREATED_AT),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        connection.execute(
            """
            INSERT INTO catalog.identifier (
                dataset_version, identifier_id, entity_id, scheme,
                identifier_value, is_primary, record_hash, created_at
            ) VALUES (%s, 'identifier-two', 'product-two', 'isin',
                      'KR0000000001', false, %s, %s)
            """,
            ("catalog-v1", VALID_RECORD_HASH, CREATED_AT),
        )


@pytest.mark.postgres
def test_entity_has_at_most_one_primary_identifier_per_scheme(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "catalog-v1")
    insert_entity(
        connection,
        dataset_version="catalog-v1",
        entity_id="product-one",
    )
    connection.execute(
        """
        INSERT INTO catalog.identifier (
            dataset_version, identifier_id, entity_id, scheme, identifier_value,
            is_primary, record_hash, created_at
        ) VALUES (%s, 'identifier-one', 'product-one', 'ticker', 'AAA', true,
                  %s, %s)
        """,
        ("catalog-v1", VALID_RECORD_HASH, CREATED_AT),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        connection.execute(
            """
            INSERT INTO catalog.identifier (
                dataset_version, identifier_id, entity_id, scheme,
                identifier_value, is_primary, record_hash, created_at
            ) VALUES (%s, 'identifier-two', 'product-one', 'ticker', 'BBB',
                      true, %s, %s)
            """,
            ("catalog-v1", VALID_RECORD_HASH, CREATED_AT),
        )


@pytest.mark.postgres
def test_alias_preserves_original_and_normalized_text_separately(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "catalog-v1")
    insert_entity(
        connection,
        dataset_version="catalog-v1",
        entity_id="product-one",
    )
    connection.execute(
        """
        INSERT INTO catalog.alias (
            dataset_version, alias_id, entity_id, alias_text,
            normalized_alias_text, record_hash, created_at
        ) VALUES (%s, 'alias-one', 'product-one', '  KODEX 200  ', 'kodex 200',
                  %s, %s)
        """,
        ("catalog-v1", VALID_RECORD_HASH, CREATED_AT),
    )

    assert connection.execute(
        """
        SELECT alias_text, normalized_alias_text
        FROM catalog.alias
        WHERE dataset_version = 'catalog-v1' AND alias_id = 'alias-one'
        """
    ).fetchone() == ("  KODEX 200  ", "kodex 200")


@pytest.mark.postgres
def test_catalog_rows_become_immutable_after_dataset_validation(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "catalog-v1")
    insert_entity(
        connection,
        dataset_version="catalog-v1",
        entity_id="product-one",
    )
    connection.execute(
        """
        UPDATE operations.dataset_version
        SET status = 'validated'
        WHERE dataset_version = 'catalog-v1'
        """
    )

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(
            """
            UPDATE catalog.entity
            SET canonical_name = 'Changed'
            WHERE dataset_version = 'catalog-v1' AND entity_id = 'product-one'
            """
        )
