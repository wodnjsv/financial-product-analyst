from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb


VALID_MANIFEST_HASH = "a" * 64
VALID_RECORD_HASH = "b" * 64
CREATED_AT = datetime(2026, 8, 18, tzinfo=UTC)


def insert_building_dataset(
    connection: psycopg.Connection,
    dataset_version: str,
    *,
    manifest_hash: str = VALID_MANIFEST_HASH,
) -> None:
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES (%s, DATE '2026-08-24', 'building', %s, %s)
        """,
        (dataset_version, manifest_hash, CREATED_AT),
    )


def insert_entity(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    entity_id: str,
    entity_type: str = "product",
    canonical_name: str | None = None,
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
            canonical_name or f"Canonical {entity_id}",
            (canonical_name or f"Canonical {entity_id}").casefold(),
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def insert_product(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    entity_id: str,
    product_family: str,
    canonical_name: str | None = None,
    primary_currency: str | None = None,
) -> None:
    insert_entity(
        connection,
        dataset_version=dataset_version,
        entity_id=entity_id,
        canonical_name=canonical_name,
    )
    connection.execute(
        """
        INSERT INTO catalog.product (
            dataset_version, entity_id, product_family, primary_currency
        ) VALUES (%s, %s, %s, %s)
        """,
        (dataset_version, entity_id, product_family, primary_currency),
    )


def insert_identifier(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    identifier_id: str,
    entity_id: str,
    scheme: str,
    identifier_value: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog.identifier (
            dataset_version, identifier_id, entity_id, scheme,
            identifier_value, record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            identifier_id,
            entity_id,
            scheme,
            identifier_value,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def insert_numeric_metric_definition(
    connection: psycopg.Connection,
    *,
    metric_id: str,
    default_unit: str,
    definition_version: str = "metric.v1",
) -> None:
    connection.execute(
        """
        INSERT INTO observation.metric_definition (
            metric_id, definition_version, semantic_family, value_kind,
            default_unit, description, definition_hash, approved_at
        ) VALUES (%s, %s, 'financial_product', 'numeric', %s,
                  'Synthetic semantic SQL metric', %s, %s)
        ON CONFLICT (metric_id, definition_version) DO NOTHING
        """,
        (metric_id, definition_version, default_unit, "e" * 64, CREATED_AT),
    )


def insert_numeric_observation_with_evidence(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    entity_id: str,
    observation_id: str,
    metric_id: str,
    value: Decimal | None,
    unit: str,
    currency: str | None,
    applicable_date: date,
    source_id: str = "source-one",
    definition_version: str = "metric.v1",
    reason_code: str = "synthetic_missing",
) -> None:
    status = "missing" if value is None else ("zero" if value == 0 else "present")
    connection.execute(
        """
        INSERT INTO observation.observation_record (
            dataset_version, observation_id, entity_id, relation_id,
            metric_id, metric_definition_version, value_status,
            numeric_value, unit, currency, applicable_date, reason_code,
            record_hash, created_at
        ) VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            observation_id,
            entity_id,
            metric_id,
            definition_version,
            status,
            value,
            unit,
            currency,
            applicable_date,
            reason_code if value is None else None,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    evidence_id = f"evidence-{observation_id}"
    tagged = (
        {"type": "null", "value": None}
        if value is None
        else {"type": "decimal", "value": str(value)}
    )
    connection.execute(
        """
        INSERT INTO evidence.evidence_record (
            dataset_version, evidence_id, evidence_kind, source_id,
            subject_id, predicate_id, value_or_object_id, normalized_value,
            unit, currency, applicable_date, locator_type,
            locator_uri_or_object_key, parser_version, mapping_version,
            cutoff_status, record_hash, created_at
        ) VALUES (%s, %s, 'observation', %s, %s, %s, %s, %s, %s, %s, %s,
                  'tabular', %s, 'synthetic-parser.v1', 'synthetic-mapping.v1',
                  'eligible', %s, %s)
        """,
        (
            dataset_version,
            evidence_id,
            source_id,
            entity_id,
            metric_id,
            Jsonb(tagged),
            Jsonb(tagged),
            unit,
            currency,
            applicable_date,
            f"synthetic://semantic-sql/{observation_id}",
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO evidence.evidence_observation_origin (
            dataset_version, evidence_id, observation_id
        ) VALUES (%s, %s, %s)
        """,
        (dataset_version, evidence_id, observation_id),
    )


def insert_relation_with_evidence(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    relation_id: str,
    subject_id: str,
    predicate_id: str,
    object_id: str,
    evidence_id: str,
    source_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO relation.relation_record (
            dataset_version, relation_id, subject_id, predicate_id, object_id,
            valid_from, record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, DATE '2026-08-24', %s, %s)
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
    tagged = {"type": "string", "value": object_id}
    connection.execute(
        """
        INSERT INTO evidence.evidence_record (
            dataset_version, evidence_id, evidence_kind, source_id,
            subject_id, predicate_id, value_or_object_id, normalized_value,
            applicable_date, valid_from, locator_type,
            locator_uri_or_object_key, parser_version, mapping_version,
            cutoff_status, record_hash, created_at
        ) VALUES (%s, %s, 'relation', %s, %s, %s, %s, %s,
                  DATE '2026-08-24', DATE '2026-08-24', 'tabular', %s,
                  'synthetic-parser.v1', 'synthetic-mapping.v1', 'eligible',
                  %s, %s)
        """,
        (
            dataset_version,
            evidence_id,
            source_id,
            subject_id,
            predicate_id,
            Jsonb(tagged),
            Jsonb(tagged),
            f"synthetic://semantic-sql/{relation_id}",
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


def insert_relation(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    relation_id: str,
    subject_id: str,
    predicate_id: str,
    object_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO relation.relation_record (
            dataset_version, relation_id, subject_id, predicate_id, object_id,
            record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
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


def insert_scope_evidence(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    evidence_id: str = "scope-one",
    source_id: str = "source-one",
    entity_id: str = "subject-one",
) -> None:
    tagged_value = {"type": "string", "value": "document coverage scope"}
    connection.execute(
        """
        INSERT INTO evidence.evidence_record (
            dataset_version, evidence_id, evidence_kind, source_id,
            subject_id, predicate_id, value_or_object_id, normalized_value,
            locator_type, locator_uri_or_object_key, parser_version,
            mapping_version, cutoff_status, record_hash, scope_completeness,
            created_at
        ) VALUES (%s, %s, 'query_scope', %s, %s,
                  'document_coverage_scope', %s, %s, 'tabular',
                  'synthetic://document/coverage', 'parser.v1', 'mapping.v1',
                  'eligible', %s, 'bounded_unknown', %s)
        """,
        (
            dataset_version,
            evidence_id,
            source_id,
            entity_id,
            Jsonb(tagged_value),
            Jsonb(tagged_value),
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
                  DATE '2026-08-24', %s, %s)
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
