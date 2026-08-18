from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


def insert_institution(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    entity_id: str = "publisher-one",
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
        ) VALUES (%s, %s, 'organizer')
        """,
        (dataset_version, entity_id),
    )


def insert_source(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    source_id: str = "source-one",
    publisher: str = "publisher-one",
    eligible_for_claim: bool = True,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence.source_record (
            dataset_version, source_id, publisher, publisher_type,
            source_title, source_type, authority_tier, source_locator_root,
            content_checksum, license_or_usage_note, eligible_for_claim,
            record_hash, created_at
        ) VALUES (%s, %s, %s, 'organizer', 'Synthetic source', 'dataset',
                  'organizer', 'synthetic/source', %s, 'test use', %s,
                  %s, %s)
        """,
        (
            dataset_version,
            source_id,
            publisher,
            "c" * 64,
            eligible_for_claim,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def insert_request_run(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    run_id: str = "run-one",
    subtask_id: str = "subtask-one",
) -> None:
    connection.execute(
        """
        INSERT INTO operations.request_run (
            run_id, request_key, question_id, question, schema_version,
            dataset_version, cutoff_date, created_at, deadline_at
        ) VALUES (%s, %s, 'Q-001', 'Synthetic question', '1.0', %s,
                  DATE '2026-07-11', %s, %s)
        """,
        (
            run_id,
            "d" * 64,
            dataset_version,
            CREATED_AT,
            CREATED_AT + timedelta(seconds=55),
        ),
    )
    connection.execute(
        """
        INSERT INTO operations.request_subtask (run_id, subtask_id, importance)
        VALUES (%s, %s, 'critical')
        """,
        (run_id, subtask_id),
    )
