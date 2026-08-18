from __future__ import annotations

from datetime import UTC, datetime

import psycopg


VALID_MANIFEST_HASH = "a" * 64
VALID_RECORD_HASH = "b" * 64
CREATED_AT = datetime(2026, 8, 18, tzinfo=UTC)


def insert_building_dataset(
    connection: psycopg.Connection,
    dataset_version: str,
) -> None:
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES (%s, DATE '2026-07-11', 'building', %s, %s)
        """,
        (dataset_version, VALID_MANIFEST_HASH, CREATED_AT),
    )


def insert_entity(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    entity_id: str,
    entity_type: str = "product",
) -> None:
    connection.execute(
        """
        INSERT INTO catalog.entity (
            dataset_version, entity_id, entity_type, canonical_name,
            normalized_name, record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            entity_id,
            entity_type,
            f"Canonical {entity_id}",
            f"canonical {entity_id}",
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
