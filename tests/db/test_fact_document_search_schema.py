from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import psycopg
import pytest
from psycopg.types.json import Jsonb

from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_RECORD_HASH,
    insert_building_dataset,
    insert_entity,
)


VALID_CHECKSUM = "c" * 64
VALID_DEFINITION_HASH = "d" * 64
VALID_MODEL_HASH = "e" * 64


def test_document_corpus_metadata_is_registered() -> None:
    from financial_agent.db.schema.document import (
        BINDING_ROLES,
        COVERAGE_STATUSES,
        DOCUMENT_ROLES,
        document_chunk,
        document_coverage,
        document_entity_binding,
        document_profile,
    )

    assert DOCUMENT_ROLES == (
        "product_summary",
        "product_full",
        "index_methodology",
        "official_update",
        "policy_base",
    )
    assert COVERAGE_STATUSES == (
        "indexed",
        "document_not_found",
        "ambiguous_entity_binding",
        "after_cutoff_only",
        "version_unknown",
        "unreadable_document",
        "publisher_not_approved",
        "section_missing",
        "not_applicable_current_scope",
        "review_required_chunk_budget",
    )
    assert BINDING_ROLES == (
        "subject_product",
        "subject_index",
        "subject_policy",
    )
    assert {
        "dataset_version",
        "document_id",
        "document_version",
        "publisher_role",
        "jurisdiction",
        "original_language",
        "effective_from",
        "effective_to",
        "amends_document_id",
        "extraction_method",
        "cutoff_eligible",
        "record_hash",
        "created_at",
    } == set(document_profile.c.keys())
    assert {
        "dataset_version",
        "binding_id",
        "document_id",
        "entity_id",
        "binding_role",
        "record_hash",
        "created_at",
    } == set(document_entity_binding.c.keys())
    assert {
        "dataset_version",
        "coverage_id",
        "entity_id",
        "required_document_role",
        "coverage_status",
        "document_id",
        "scope_evidence_id",
        "reason_code",
        "record_hash",
        "created_at",
    } == set(document_coverage.c.keys())
    assert {
        "section_type",
        "section_path",
        "character_start",
        "character_end",
    } <= set(document_chunk.c.keys())


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[psycopg.Connection]:
    from financial_agent.db.preflight import normalize_psycopg_url

    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as database_connection:
        yield database_connection
        database_connection.rollback()


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


def insert_relation(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    relation_id: str = "relation-one",
    subject_id: str = "subject-one",
    object_id: str = "object-one",
    valid_from: str = "2026-01-01",
    valid_to: str = "2026-07-11",
) -> None:
    connection.execute(
        """
        INSERT INTO relation.relation_record (
            dataset_version, relation_id, subject_id, predicate_id,
            object_id, valid_from, valid_to, record_hash, created_at
        ) VALUES (%s, %s, %s, 'issued_by', %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            relation_id,
            subject_id,
            object_id,
            valid_from,
            valid_to,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def insert_metric(
    connection: psycopg.Connection,
    *,
    metric_id: str = "metric-one",
    definition_version: str = "1",
    value_kind: str = "numeric",
) -> None:
    connection.execute(
        """
        INSERT INTO observation.metric_definition (
            metric_id, definition_version, semantic_family, value_kind,
            default_unit, description, definition_hash, approved_at
        ) VALUES (%s, %s, 'financial', %s, 'percent', 'Synthetic metric',
                  %s, %s)
        """,
        (
            metric_id,
            definition_version,
            value_kind,
            VALID_DEFINITION_HASH,
            CREATED_AT,
        ),
    )


def insert_source(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    source_id: str = "source-one",
    publisher: str = "publisher-one",
    content_checksum: str = VALID_CHECKSUM,
    record_hash: str = VALID_RECORD_HASH,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence.source_record (
            dataset_version, source_id, publisher, publisher_type,
            source_title, source_type, authority_tier, source_locator_root,
            content_checksum, license_or_usage_note, eligible_for_claim,
            record_hash, created_at
        ) VALUES (%s, %s, %s, 'organizer', 'Synthetic source', 'dataset',
                  'organizer', 'synthetic/source', %s, 'test use', true,
                  %s, %s)
        """,
        (
            dataset_version,
            source_id,
            publisher,
            content_checksum,
            record_hash,
            CREATED_AT,
        ),
    )


def insert_document(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    document_id: str = "document-one",
    source_id: str = "source-one",
    content_checksum: str = VALID_CHECKSUM,
) -> None:
    connection.execute(
        """
        INSERT INTO document.document_record (
            dataset_version, document_id, source_id, document_title,
            document_type, object_key, content_checksum, published_at,
            available_at, record_hash, created_at
        ) VALUES (%s, %s, %s, 'Synthetic document', 'filing',
                  'synthetic/document.pdf', %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            document_id,
            source_id,
            content_checksum,
            CREATED_AT,
            CREATED_AT,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def insert_chunk(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    chunk_id: str = "chunk-one",
    document_id: str = "document-one",
    parent_chunk_id: str | None = None,
    ordinal: int = 0,
    page_start: int = 1,
    page_end: int = 1,
    sentence_start: int = 0,
    sentence_end: int = 0,
    section_type: str = "risk_factor",
    section_path: str = "risk",
    character_start: int = 0,
    character_end: int = 9,
    content_hash: str = VALID_CHECKSUM,
) -> None:
    connection.execute(
        """
        INSERT INTO document.document_chunk (
            dataset_version, chunk_id, document_id, parent_chunk_id,
            ordinal, page_start, page_end, section, sentence_start,
            sentence_end, exact_text, normalized_search_text, content_hash,
            record_hash, created_at, section_type, section_path,
            character_start, character_end
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'risk', %s, %s,
                  '정확한 합성 원문', '정확한 합성 원문', %s, %s, %s,
                  %s, %s, %s, %s)
        """,
        (
            dataset_version,
            chunk_id,
            document_id,
            parent_chunk_id,
            ordinal,
            page_start,
            page_end,
            sentence_start,
            sentence_end,
            content_hash,
            VALID_RECORD_HASH,
            CREATED_AT,
            section_type,
            section_path,
            character_start,
            character_end,
        ),
    )


def insert_document_profile(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    document_id: str = "document-one",
    effective_from: str = "2026-01-01",
    effective_to: str | None = "2026-08-24",
) -> None:
    connection.execute(
        """
        INSERT INTO document.document_profile (
            dataset_version, document_id, document_version, publisher_role,
            jurisdiction, original_language, effective_from, effective_to,
            amends_document_id, extraction_method, cutoff_eligible,
            record_hash, created_at
        ) VALUES (%s, %s, 'v1', 'issuer', 'KR', 'ko', %s, %s, NULL,
                  'text_layer', true, %s, %s)
        """,
        (
            dataset_version,
            document_id,
            effective_from,
            effective_to,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def insert_document_binding(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    binding_id: str = "binding-one",
    document_id: str = "document-one",
    entity_id: str = "subject-one",
    binding_role: str = "subject_product",
) -> None:
    connection.execute(
        """
        INSERT INTO document.document_entity_binding (
            dataset_version, binding_id, document_id, entity_id,
            binding_role, record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            binding_id,
            document_id,
            entity_id,
            binding_role,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def insert_scope_evidence(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    evidence_id: str = "scope-one",
    evidence_kind: str = "query_scope",
) -> None:
    scope_completeness = (
        "bounded_unknown" if evidence_kind == "query_scope" else None
    )
    tagged_value = {"type": "string", "value": "document coverage scope"}
    connection.execute(
        """
        INSERT INTO evidence.evidence_record (
            dataset_version, evidence_id, evidence_kind, source_id,
            subject_id, predicate_id, value_or_object_id, normalized_value,
            locator_type, locator_uri_or_object_key, parser_version,
            mapping_version, cutoff_status, record_hash, scope_completeness,
            created_at
        ) VALUES (%s, %s, %s, 'source-one', 'subject-one',
                  'document_coverage_scope', %s, %s, 'tabular',
                  'synthetic://document/coverage', 'parser.v1', 'mapping.v1',
                  'eligible', %s, %s, %s)
        """,
        (
            dataset_version,
            evidence_id,
            evidence_kind,
            Jsonb(tagged_value),
            Jsonb(tagged_value),
            VALID_RECORD_HASH,
            scope_completeness,
            CREATED_AT,
        ),
    )


def insert_document_coverage(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    coverage_id: str = "coverage-one",
    entity_id: str = "subject-one",
    required_document_role: str = "product_summary",
    coverage_status: str = "indexed",
    document_id: str | None = "document-one",
    scope_evidence_id: str | None = None,
    reason_code: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO document.document_coverage (
            dataset_version, coverage_id, entity_id, required_document_role,
            coverage_status, document_id, scope_evidence_id, reason_code,
            record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            coverage_id,
            entity_id,
            required_document_role,
            coverage_status,
            document_id,
            scope_evidence_id,
            reason_code,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def prepare_document_graph(
    connection: psycopg.Connection,
    *,
    dataset_version: str = "facts-v1",
) -> None:
    insert_building_dataset(connection, dataset_version)
    insert_institution(connection, dataset_version=dataset_version)
    insert_source(connection, dataset_version=dataset_version)
    insert_document(connection, dataset_version=dataset_version)


@pytest.mark.postgres
def test_relation_entities_must_belong_to_the_same_dataset_version(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_building_dataset(connection, "facts-v2")
    insert_entity(connection, dataset_version="facts-v1", entity_id="subject-one")
    insert_entity(connection, dataset_version="facts-v2", entity_id="object-one")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_relation(connection, dataset_version="facts-v1")


@pytest.mark.postgres
def test_relation_rejects_a_reversed_validity_range(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_entity(connection, dataset_version="facts-v1", entity_id="subject-one")
    insert_entity(connection, dataset_version="facts-v1", entity_id="object-one")

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_relation(
            connection,
            dataset_version="facts-v1",
            valid_from="2026-07-11",
            valid_to="2026-01-01",
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("entity_id", "relation_id"),
    (("target-one", "relation-one"), (None, None)),
)
def test_observation_requires_exactly_one_entity_or_relation_target(
    connection: psycopg.Connection,
    entity_id: str | None,
    relation_id: str | None,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_entity(connection, dataset_version="facts-v1", entity_id="target-one")
    insert_entity(connection, dataset_version="facts-v1", entity_id="object-one")
    insert_relation(
        connection,
        dataset_version="facts-v1",
        subject_id="target-one",
    )
    insert_metric(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            """
            INSERT INTO observation.observation_record (
                dataset_version, observation_id, entity_id, relation_id,
                metric_id, metric_definition_version, value_status,
                numeric_value, record_hash, created_at
            ) VALUES ('facts-v1', 'observation-one', %s, %s,
                      'metric-one', '1', 'present', 1, %s, %s)
            """,
            (entity_id, relation_id, VALID_RECORD_HASH, CREATED_AT),
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    (
        "status",
        "numeric_value",
        "text_value",
        "boolean_value",
        "date_value",
        "timestamp_value",
        "reason_code",
    ),
    (
        ("present", None, None, None, None, None, None),
        ("present", Decimal("1"), "duplicate", None, None, None, None),
        ("missing", Decimal("1"), None, None, None, None, "not-reported"),
        (
            "placeholder",
            Decimal("1"),
            None,
            None,
            None,
            None,
            "source-placeholder",
        ),
        ("unavailable", Decimal("1"), None, None, None, None, "unavailable"),
        (
            "inapplicable",
            Decimal("1"),
            None,
            None,
            None,
            None,
            "not-applicable",
        ),
        ("unknown", Decimal("1"), None, None, None, None, "unknown"),
        ("zero", Decimal("0.01"), None, None, None, None, None),
        ("zero", None, "0", None, None, None, None),
        ("zero", None, None, True, None, None, None),
        ("zero", None, None, None, date(2026, 7, 11), None, None),
        ("zero", None, None, None, None, CREATED_AT, None),
        ("present", Decimal("0"), None, None, None, None, None),
    ),
)
def test_observation_rejects_value_status_and_typed_value_conflicts(
    connection: psycopg.Connection,
    status: str,
    numeric_value: Decimal | None,
    text_value: str | None,
    boolean_value: bool | None,
    date_value: date | None,
    timestamp_value: datetime | None,
    reason_code: str | None,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_entity(connection, dataset_version="facts-v1", entity_id="target-one")
    insert_metric(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            """
            INSERT INTO observation.observation_record (
                dataset_version, observation_id, entity_id, metric_id,
                metric_definition_version, value_status, numeric_value,
                text_value, boolean_value, date_value, timestamp_value,
                reason_code, record_hash, created_at
            ) VALUES ('facts-v1', 'observation-one', 'target-one',
                      'metric-one', '1', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                status,
                numeric_value,
                text_value,
                boolean_value,
                date_value,
                timestamp_value,
                reason_code,
                VALID_RECORD_HASH,
                CREATED_AT,
            ),
        )


@pytest.mark.postgres
def test_observation_preserves_true_numeric_zero_as_distinct_from_missing(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_entity(connection, dataset_version="facts-v1", entity_id="target-one")
    insert_metric(connection)

    connection.execute(
        """
        INSERT INTO observation.observation_record (
            dataset_version, observation_id, entity_id, metric_id,
            metric_definition_version, value_status, numeric_value,
            record_hash, created_at
        ) VALUES ('facts-v1', 'observation-zero', 'target-one',
                  'metric-one', '1', 'zero', 0, %s, %s)
        """,
        (VALID_RECORD_HASH, CREATED_AT),
    )

    assert connection.execute(
        """
        SELECT value_status, numeric_value
        FROM observation.observation_record
        WHERE dataset_version = 'facts-v1'
          AND observation_id = 'observation-zero'
        """
    ).fetchone() == ("zero", Decimal("0E-12"))


@pytest.mark.postgres
def test_observation_requires_a_registered_metric_version(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_entity(connection, dataset_version="facts-v1", entity_id="target-one")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        connection.execute(
            """
            INSERT INTO observation.observation_record (
                dataset_version, observation_id, entity_id, metric_id,
                metric_definition_version, value_status, numeric_value,
                record_hash, created_at
            ) VALUES ('facts-v1', 'observation-one', 'target-one',
                      'unregistered', '1', 'present', 1, %s, %s)
            """,
            (VALID_RECORD_HASH, CREATED_AT),
        )


@pytest.mark.postgres
def test_observation_value_kind_must_match_exact_metric_definition_version(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_entity(connection, dataset_version="facts-v1", entity_id="target-one")
    insert_metric(connection, value_kind="text")
    connection.execute(
        """
        INSERT INTO observation.observation_record (
            dataset_version, observation_id, entity_id, metric_id,
            metric_definition_version, value_status, numeric_value,
            record_hash, created_at
        ) VALUES ('facts-v1', 'observation-one', 'target-one',
                  'metric-one', '1', 'present', 1, %s, %s)
        """,
        (VALID_RECORD_HASH, CREATED_AT),
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
def test_source_identity_is_unique_only_within_dataset_version(
    connection: psycopg.Connection,
) -> None:
    for dataset_version in ("facts-v1", "facts-v2"):
        insert_building_dataset(connection, dataset_version)
        insert_institution(connection, dataset_version=dataset_version)
        insert_source(connection, dataset_version=dataset_version)

    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_source(connection, dataset_version="facts-v1")


@pytest.mark.postgres
@pytest.mark.parametrize("hash_column", ("content_checksum", "record_hash"))
def test_source_requires_lowercase_sha256_hashes(
    connection: psycopg.Connection,
    hash_column: str,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_institution(connection, dataset_version="facts-v1")
    values = {
        "content_checksum": VALID_CHECKSUM,
        "record_hash": VALID_RECORD_HASH,
    }
    values[hash_column] = "A" * 64

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_source(
            connection,
            dataset_version="facts-v1",
            content_checksum=values["content_checksum"],
            record_hash=values["record_hash"],
        )


@pytest.mark.postgres
def test_source_publisher_must_be_a_same_version_institution(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_building_dataset(connection, "facts-v2")
    insert_institution(connection, dataset_version="facts-v2")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_source(connection, dataset_version="facts-v1")


@pytest.mark.postgres
def test_source_deferred_check_rejects_a_noninstitution_publisher_type(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_entity(
        connection,
        dataset_version="facts-v1",
        entity_id="publisher-one",
        entity_type="company",
    )
    connection.execute(
        """
        INSERT INTO catalog.institution (
            dataset_version, entity_id, institution_kind
        ) VALUES ('facts-v1', 'publisher-one', 'organizer')
        """
    )
    insert_source(connection, dataset_version="facts-v1")

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "SET CONSTRAINTS evidence.validate_source_publisher_type IMMEDIATE"
        )


@pytest.mark.postgres
def test_document_requires_an_existing_same_version_source(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_building_dataset(connection, "facts-v2")
    insert_institution(connection, dataset_version="facts-v2")
    insert_source(connection, dataset_version="facts-v2")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_document(connection, dataset_version="facts-v1")


@pytest.mark.postgres
def test_document_profile_rejects_a_reversed_effective_range(
    connection: psycopg.Connection,
) -> None:
    prepare_document_graph(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_document_profile(
            connection,
            dataset_version="facts-v1",
            effective_from="2026-08-24",
            effective_to="2026-01-01",
        )


@pytest.mark.postgres
def test_document_binding_entity_must_belong_to_the_same_dataset_version(
    connection: psycopg.Connection,
) -> None:
    prepare_document_graph(connection)
    insert_building_dataset(connection, "facts-v2")
    insert_entity(
        connection,
        dataset_version="facts-v2",
        entity_id="subject-one",
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_document_binding(connection, dataset_version="facts-v1")


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("document_id", "scope_evidence_id", "reason_code"),
    (
        (None, None, None),
        ("document-one", None, "unexpected-reason"),
        ("document-one", "scope-one", None),
    ),
)
def test_indexed_coverage_requires_only_a_document_reference(
    connection: psycopg.Connection,
    document_id: str | None,
    scope_evidence_id: str | None,
    reason_code: str | None,
) -> None:
    prepare_document_graph(connection)
    insert_entity(connection, dataset_version="facts-v1", entity_id="subject-one")
    insert_scope_evidence(connection, dataset_version="facts-v1")

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_document_coverage(
            connection,
            dataset_version="facts-v1",
            document_id=document_id,
            scope_evidence_id=scope_evidence_id,
            reason_code=reason_code,
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("document_id", "scope_evidence_id", "reason_code"),
    (
        ("document-one", "scope-one", "document-not-found"),
        (None, None, "document-not-found"),
        (None, "scope-one", None),
        (None, "scope-one", ""),
    ),
)
def test_nonindexed_coverage_requires_scope_evidence_and_a_reason(
    connection: psycopg.Connection,
    document_id: str | None,
    scope_evidence_id: str | None,
    reason_code: str | None,
) -> None:
    prepare_document_graph(connection)
    insert_entity(connection, dataset_version="facts-v1", entity_id="subject-one")
    insert_scope_evidence(connection, dataset_version="facts-v1")

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_document_coverage(
            connection,
            dataset_version="facts-v1",
            coverage_status="document_not_found",
            document_id=document_id,
            scope_evidence_id=scope_evidence_id,
            reason_code=reason_code,
        )


@pytest.mark.postgres
def test_nonindexed_coverage_rejects_non_scope_evidence(
    connection: psycopg.Connection,
) -> None:
    prepare_document_graph(connection)
    insert_entity(connection, dataset_version="facts-v1", entity_id="subject-one")
    insert_scope_evidence(
        connection,
        dataset_version="facts-v1",
        evidence_kind="exclusion",
    )
    insert_document_coverage(
        connection,
        dataset_version="facts-v1",
        coverage_status="document_not_found",
        document_id=None,
        scope_evidence_id="scope-one",
        reason_code="document-not-found",
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("required_document_role", "coverage_status", "binding_role"),
    (
        ("unsupported_role", "indexed", "subject_product"),
        ("product_summary", "unsupported_status", "subject_product"),
        ("product_summary", "indexed", "unsupported_binding"),
    ),
)
def test_document_corpus_rejects_unregistered_vocabulary_values(
    connection: psycopg.Connection,
    required_document_role: str,
    coverage_status: str,
    binding_role: str,
) -> None:
    prepare_document_graph(connection)
    insert_entity(connection, dataset_version="facts-v1", entity_id="subject-one")

    with pytest.raises(psycopg.errors.CheckViolation):
        if binding_role == "unsupported_binding":
            insert_document_binding(
                connection,
                dataset_version="facts-v1",
                binding_role=binding_role,
            )
        else:
            insert_document_coverage(
                connection,
                dataset_version="facts-v1",
                required_document_role=required_document_role,
                coverage_status=coverage_status,
            )


@pytest.mark.postgres
def test_parent_chunk_must_belong_to_the_same_document_and_dataset(
    connection: psycopg.Connection,
) -> None:
    prepare_document_graph(connection)
    insert_document(
        connection,
        dataset_version="facts-v1",
        document_id="document-two",
    )
    insert_chunk(connection, dataset_version="facts-v1")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_chunk(
            connection,
            dataset_version="facts-v1",
            chunk_id="child-one",
            document_id="document-two",
            parent_chunk_id="chunk-one",
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("page_start", "page_end", "sentence_start", "sentence_end"),
    ((2, 1, 0, 0), (1, 1, 2, 1)),
)
def test_chunk_rejects_reversed_page_or_sentence_ranges(
    connection: psycopg.Connection,
    page_start: int,
    page_end: int,
    sentence_start: int,
    sentence_end: int,
) -> None:
    prepare_document_graph(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_chunk(
            connection,
            dataset_version="facts-v1",
            page_start=page_start,
            page_end=page_end,
            sentence_start=sentence_start,
            sentence_end=sentence_end,
        )


@pytest.mark.postgres
def test_chunk_rejects_a_reversed_character_range(
    connection: psycopg.Connection,
) -> None:
    prepare_document_graph(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_chunk(
            connection,
            dataset_version="facts-v1",
            character_start=10,
            character_end=9,
        )


@pytest.mark.postgres
@pytest.mark.parametrize("target", ("document", "chunk"))
def test_document_and_chunk_require_lowercase_sha256_content_hashes(
    connection: psycopg.Connection,
    target: str,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_institution(connection, dataset_version="facts-v1")
    insert_source(connection, dataset_version="facts-v1")

    with pytest.raises(psycopg.errors.CheckViolation):
        if target == "document":
            insert_document(
                connection,
                dataset_version="facts-v1",
                content_checksum="not-a-sha256",
            )
        else:
            insert_document(connection, dataset_version="facts-v1")
            insert_chunk(
                connection,
                dataset_version="facts-v1",
                content_hash="not-a-sha256",
            )


@pytest.mark.postgres
def test_embedding_references_the_exact_chunk_content_hash(
    connection: psycopg.Connection,
) -> None:
    prepare_document_graph(connection)
    insert_chunk(connection, dataset_version="facts-v1")
    connection.execute(
        """
        INSERT INTO search.embedding_model (
            model_id, model_version, dimension, distance_metric,
            approval_record_id, approved_at, model_hash
        ) VALUES ('model-one', '1', 3, 'cosine', 'approval-001', %s, %s)
        """,
        (CREATED_AT, VALID_MODEL_HASH),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        connection.execute(
            """
            INSERT INTO search.document_embedding (
                dataset_version, embedding_id, document_id, chunk_id,
                chunk_content_hash, model_id, model_version, dimension,
                embedding, created_at
            ) VALUES ('facts-v1', 'embedding-one', 'document-one', 'chunk-one',
                      %s, 'model-one', '1', 3,
                      '[1,2,3]'::cdb_admin.vector, %s)
            """,
            ("f" * 64, CREATED_AT),
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("stored_dimension", "vector_literal"),
    ((2, "[1,2]"), (3, "[1,2]")),
)
def test_embedding_dimension_matches_vector_and_exact_model_version(
    connection: psycopg.Connection,
    stored_dimension: int,
    vector_literal: str,
) -> None:
    prepare_document_graph(connection)
    insert_chunk(connection, dataset_version="facts-v1")
    connection.execute(
        """
        INSERT INTO search.embedding_model (
            model_id, model_version, dimension, distance_metric,
            approval_record_id, approved_at, model_hash
        ) VALUES ('model-one', '1', 3, 'cosine', 'approval-001', %s, %s)
        """,
        (CREATED_AT, VALID_MODEL_HASH),
    )
    connection.execute(
        f"""
        INSERT INTO search.document_embedding (
            dataset_version, embedding_id, document_id, chunk_id,
            chunk_content_hash, model_id, model_version, dimension,
            embedding, created_at
        ) VALUES ('facts-v1', 'embedding-one', 'document-one', 'chunk-one',
                  %s, 'model-one', '1', %s,
                  '{vector_literal}'::cdb_admin.vector, %s)
        """,
        (VALID_CHECKSUM, stored_dimension, CREATED_AT),
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
def test_embedding_accepts_the_exact_chunk_hash_and_registered_dimension(
    connection: psycopg.Connection,
) -> None:
    prepare_document_graph(connection)
    insert_chunk(connection, dataset_version="facts-v1")
    connection.execute(
        """
        INSERT INTO search.embedding_model (
            model_id, model_version, dimension, distance_metric,
            approval_record_id, approved_at, model_hash
        ) VALUES ('model-one', '1', 3, 'cosine', 'approval-001', %s, %s)
        """,
        (CREATED_AT, VALID_MODEL_HASH),
    )
    connection.execute(
        """
        INSERT INTO search.document_embedding (
            dataset_version, embedding_id, document_id, chunk_id,
            chunk_content_hash, model_id, model_version, dimension,
            embedding, created_at
        ) VALUES ('facts-v1', 'embedding-one', 'document-one', 'chunk-one',
                  %s, 'model-one', '1', 3,
                  '[1,2,3]'::cdb_admin.vector, %s)
        """,
        (VALID_CHECKSUM, CREATED_AT),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

    assert connection.execute(
        """
        SELECT dimension, cdb_admin.vector_dims(embedding)
        FROM search.document_embedding
        WHERE dataset_version = 'facts-v1' AND embedding_id = 'embedding-one'
        """
    ).fetchone() == (3, 3)


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("approval_record_id", "approved_at"),
    (("", CREATED_AT), ("approval-001", None)),
)
def test_embedding_model_requires_a_nonempty_completed_approval(
    connection: psycopg.Connection,
    approval_record_id: str,
    approved_at: datetime | None,
) -> None:
    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.NotNullViolation)):
        connection.execute(
            """
            INSERT INTO search.embedding_model (
                model_id, model_version, dimension, distance_metric,
                approval_record_id, approved_at, model_hash
            ) VALUES ('model-one', '1', 3, 'cosine', %s, %s, %s)
            """,
            (approval_record_id, approved_at, VALID_MODEL_HASH),
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("table_name", "insert_sql", "mutation_sql"),
    (
        (
            "metric_definition",
            """
            INSERT INTO observation.metric_definition (
                metric_id, definition_version, semantic_family, value_kind,
                definition_hash, approved_at
            ) VALUES ('metric-one', '1', 'financial', 'numeric', %s, %s)
            """,
            """
            UPDATE observation.metric_definition
            SET description = 'changed'
            WHERE metric_id = 'metric-one' AND definition_version = '1'
            """,
        ),
        (
            "metric_definition",
            """
            INSERT INTO observation.metric_definition (
                metric_id, definition_version, semantic_family, value_kind,
                definition_hash, approved_at
            ) VALUES ('metric-one', '1', 'financial', 'numeric', %s, %s)
            """,
            """
            DELETE FROM observation.metric_definition
            WHERE metric_id = 'metric-one' AND definition_version = '1'
            """,
        ),
        (
            "embedding_model",
            """
            INSERT INTO search.embedding_model (
                model_id, model_version, dimension, distance_metric,
                approval_record_id, model_hash, approved_at
            ) VALUES ('model-one', '1', 3, 'cosine', 'approval-001', %s, %s)
            """,
            """
            UPDATE search.embedding_model
            SET dimension = 4
            WHERE model_id = 'model-one' AND model_version = '1'
            """,
        ),
        (
            "embedding_model",
            """
            INSERT INTO search.embedding_model (
                model_id, model_version, dimension, distance_metric,
                approval_record_id, model_hash, approved_at
            ) VALUES ('model-one', '1', 3, 'cosine', 'approval-001', %s, %s)
            """,
            """
            DELETE FROM search.embedding_model
            WHERE model_id = 'model-one' AND model_version = '1'
            """,
        ),
    ),
)
def test_registries_reject_updates_and_deletes(
    connection: psycopg.Connection,
    table_name: str,
    insert_sql: str,
    mutation_sql: str,
) -> None:
    hash_value = (
        VALID_DEFINITION_HASH
        if table_name == "metric_definition"
        else VALID_MODEL_HASH
    )
    connection.execute(insert_sql, (hash_value, CREATED_AT))

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(mutation_sql)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "mutation_sql",
    (
        """
        UPDATE evidence.source_record
        SET source_title = 'Changed'
        WHERE dataset_version = 'facts-v1' AND source_id = 'source-one'
        """,
        """
        DELETE FROM evidence.source_record
        WHERE dataset_version = 'facts-v1' AND source_id = 'source-one'
        """,
    ),
)
def test_source_is_append_only(
    connection: psycopg.Connection,
    mutation_sql: str,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_institution(connection, dataset_version="facts-v1")
    insert_source(connection, dataset_version="facts-v1")

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(mutation_sql)


@pytest.mark.postgres
def test_source_insert_requires_a_building_dataset(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "facts-v1")
    insert_institution(connection, dataset_version="facts-v1")
    connection.execute(
        """
        UPDATE operations.dataset_version
        SET status = 'validated'
        WHERE dataset_version = 'facts-v1'
        """
    )

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        insert_source(connection, dataset_version="facts-v1")


@pytest.mark.postgres
@pytest.mark.parametrize(
    "mutation_sql",
    (
        """
        UPDATE relation.relation_record
        SET predicate_id = 'changed'
        WHERE dataset_version = 'facts-v1' AND relation_id = 'relation-one'
        """,
        """
        UPDATE observation.observation_record
        SET unit = 'changed'
        WHERE dataset_version = 'facts-v1' AND observation_id = 'observation-one'
        """,
        """
        UPDATE document.document_record
        SET document_title = 'Changed'
        WHERE dataset_version = 'facts-v1' AND document_id = 'document-one'
        """,
        """
        UPDATE document.document_chunk
        SET section = 'changed'
        WHERE dataset_version = 'facts-v1' AND chunk_id = 'chunk-one'
        """,
        """
        UPDATE search.document_embedding
        SET dimension = 4
        WHERE dataset_version = 'facts-v1' AND embedding_id = 'embedding-one'
        """,
    ),
)
def test_versioned_fact_document_and_embedding_rows_freeze_after_validation(
    connection: psycopg.Connection,
    mutation_sql: str,
) -> None:
    prepare_document_graph(connection)
    insert_entity(connection, dataset_version="facts-v1", entity_id="subject-one")
    insert_entity(connection, dataset_version="facts-v1", entity_id="object-one")
    insert_relation(connection, dataset_version="facts-v1")
    insert_metric(connection)
    connection.execute(
        """
        INSERT INTO observation.observation_record (
            dataset_version, observation_id, entity_id, metric_id,
            metric_definition_version, value_status, numeric_value,
            record_hash, created_at
        ) VALUES ('facts-v1', 'observation-one', 'subject-one',
                  'metric-one', '1', 'present', 1, %s, %s)
        """,
        (VALID_RECORD_HASH, CREATED_AT),
    )
    insert_chunk(connection, dataset_version="facts-v1")
    connection.execute(
        """
        INSERT INTO search.embedding_model (
            model_id, model_version, dimension, distance_metric,
            approval_record_id, approved_at, model_hash
        ) VALUES ('model-one', '1', 3, 'cosine', 'approval-001', %s, %s)
        """,
        (CREATED_AT, VALID_MODEL_HASH),
    )
    connection.execute(
        """
        INSERT INTO search.document_embedding (
            dataset_version, embedding_id, document_id, chunk_id,
            chunk_content_hash, model_id, model_version, dimension,
            embedding, created_at
        ) VALUES ('facts-v1', 'embedding-one', 'document-one', 'chunk-one',
                  %s, 'model-one', '1', 3,
                  '[1,2,3]'::cdb_admin.vector, %s)
        """,
        (VALID_CHECKSUM, CREATED_AT),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.execute(
        """
        UPDATE operations.dataset_version
        SET status = 'validated'
        WHERE dataset_version = 'facts-v1'
        """
    )

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(mutation_sql)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "mutation_sql",
    (
        """
        UPDATE document.document_profile
        SET extraction_method = 'changed'
        WHERE dataset_version = 'facts-v1' AND document_id = 'document-one'
        """,
        """
        UPDATE document.document_entity_binding
        SET binding_role = 'subject_index'
        WHERE dataset_version = 'facts-v1' AND binding_id = 'binding-one'
        """,
        """
        UPDATE document.document_coverage
        SET reason_code = 'changed'
        WHERE dataset_version = 'facts-v1' AND coverage_id = 'coverage-one'
        """,
    ),
)
def test_document_corpus_rows_freeze_after_validation(
    connection: psycopg.Connection,
    mutation_sql: str,
) -> None:
    prepare_document_graph(connection)
    insert_entity(connection, dataset_version="facts-v1", entity_id="subject-one")
    insert_document_profile(connection, dataset_version="facts-v1")
    insert_document_binding(connection, dataset_version="facts-v1")
    insert_document_coverage(connection, dataset_version="facts-v1")
    connection.execute(
        """
        UPDATE operations.dataset_version
        SET status = 'validated'
        WHERE dataset_version = 'facts-v1'
        """
    )

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(mutation_sql)


@pytest.mark.postgres
def test_task4_table_privileges_match_mutability_policy(
    connection: psycopg.Connection,
) -> None:
    tables = {
        ("evidence", "source_record"): {"SELECT", "INSERT"},
        ("observation", "metric_definition"): {"SELECT", "INSERT"},
        ("search", "embedding_model"): {"SELECT", "INSERT"},
        ("relation", "relation_record"): {
            "SELECT", "INSERT", "UPDATE", "DELETE"
        },
        ("observation", "observation_record"): {
            "SELECT", "INSERT", "UPDATE", "DELETE"
        },
        ("document", "document_record"): {
            "SELECT", "INSERT", "UPDATE", "DELETE"
        },
        ("document", "document_chunk"): {
            "SELECT", "INSERT", "UPDATE", "DELETE"
        },
        ("document", "document_profile"): {
            "SELECT", "INSERT", "UPDATE", "DELETE"
        },
        ("document", "document_entity_binding"): {
            "SELECT", "INSERT", "UPDATE", "DELETE"
        },
        ("document", "document_coverage"): {
            "SELECT", "INSERT", "UPDATE", "DELETE"
        },
        ("search", "document_embedding"): {
            "SELECT", "INSERT", "UPDATE", "DELETE"
        },
    }
    for (schema_name, table_name), expected_build in tables.items():
        build_privileges = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT privilege_type
                FROM information_schema.role_table_grants
                WHERE grantee = 'fa_build'
                  AND table_schema = %s AND table_name = %s
                """,
                (schema_name, table_name),
            ).fetchall()
        }
        runtime_privileges = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT privilege_type
                FROM information_schema.role_table_grants
                WHERE grantee = 'fa_runtime'
                  AND table_schema = %s AND table_name = %s
                """,
                (schema_name, table_name),
            ).fetchall()
        }
        assert build_privileges == expected_build
        assert runtime_privileges == {"SELECT"}


@pytest.mark.postgres
def test_task4_objects_have_migration_ownership_and_hardened_trigger_functions(
    connection: psycopg.Connection,
) -> None:
    expected_functions = {
        ("evidence", "validate_source_publisher_type"): (
            "search_path=pg_catalog, evidence, catalog, pg_temp"
        ),
        ("observation", "validate_metric_value_kind"): (
            "search_path=pg_catalog, observation, pg_temp"
        ),
        ("search", "validate_document_embedding"): (
            "search_path=pg_catalog, search, cdb_admin, pg_temp"
        ),
        ("document", "validate_document_coverage_scope_evidence"): (
            "search_path=pg_catalog, document, evidence, pg_temp"
        ),
    }
    function_rows = connection.execute(
        """
        SELECT namespace.nspname, procedure.proname, procedure.oid,
               owner.rolname, procedure.prosecdef, procedure.proconfig,
               EXISTS (
                   SELECT 1
                   FROM pg_catalog.aclexplode(
                       COALESCE(
                           procedure.proacl,
                           pg_catalog.acldefault('f', procedure.proowner)
                       )
                   ) AS acl
                   WHERE acl.grantee = 0
                     AND acl.privilege_type = 'EXECUTE'
               ) AS public_execute
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        JOIN pg_catalog.pg_roles AS owner
          ON owner.oid = procedure.proowner
        WHERE (namespace.nspname, procedure.proname) IN (
            ('evidence', 'validate_source_publisher_type'),
            ('observation', 'validate_metric_value_kind'),
            ('search', 'validate_document_embedding'),
            ('document', 'validate_document_coverage_scope_evidence')
        )
        """
    ).fetchall()
    assert {(str(row[0]), str(row[1])) for row in function_rows} == set(
        expected_functions
    )
    for (
        schema_name,
        function_name,
        oid,
        owner,
        security_definer,
        settings,
        public_execute,
    ) in function_rows:
        assert owner == "fa_migration"
        assert security_definer is True
        assert expected_functions[(str(schema_name), str(function_name))] in settings
        assert public_execute is False
        for role in ("fa_build", "fa_runtime"):
            assert connection.execute(
                "SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')",
                (role, oid),
            ).fetchone()[0] is False

    table_owners = connection.execute(
        """
        SELECT namespace.nspname, relation.relname, owner.rolname
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner
          ON owner.oid = relation.relowner
        WHERE relation.relkind = 'r'
          AND (namespace.nspname, relation.relname) IN (
              ('evidence', 'source_record'),
              ('observation', 'metric_definition'),
              ('observation', 'observation_record'),
              ('relation', 'relation_record'),
              ('document', 'document_record'),
              ('document', 'document_chunk'),
              ('document', 'document_profile'),
              ('document', 'document_entity_binding'),
              ('document', 'document_coverage'),
              ('search', 'embedding_model'),
              ('search', 'document_embedding')
          )
        """
    ).fetchall()
    assert len(table_owners) == 11
    assert {str(row[2]) for row in table_owners} == {"fa_migration"}


@pytest.mark.postgres
def test_task4_application_foreign_keys_never_cascade_deletes(
    connection: psycopg.Connection,
) -> None:
    rows = connection.execute(
        """
        SELECT constraint_name, delete_rule
        FROM information_schema.referential_constraints
        WHERE constraint_schema IN (
            'relation', 'observation', 'evidence', 'document', 'search'
        )
        """
    ).fetchall()

    assert rows
    assert {str(row[1]) for row in rows} <= {"RESTRICT", "NO ACTION"}


@pytest.mark.postgres
def test_embedding_uses_managed_vector_type_without_an_ann_index(
    connection: psycopg.Connection,
) -> None:
    assert connection.execute(
        """
        SELECT type_namespace.nspname, type.typname
        FROM pg_catalog.pg_attribute AS attribute
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = attribute.attrelid
        JOIN pg_catalog.pg_namespace AS table_namespace
          ON table_namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_type AS type
          ON type.oid = attribute.atttypid
        JOIN pg_catalog.pg_namespace AS type_namespace
          ON type_namespace.oid = type.typnamespace
        WHERE table_namespace.nspname = 'search'
          AND relation.relname = 'document_embedding'
          AND attribute.attname = 'embedding'
        """
    ).fetchone() == ("cdb_admin", "vector")

    index_methods = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT access_method.amname
            FROM pg_catalog.pg_index AS index
            JOIN pg_catalog.pg_class AS table_relation
              ON table_relation.oid = index.indrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = table_relation.relnamespace
            JOIN pg_catalog.pg_class AS index_relation
              ON index_relation.oid = index.indexrelid
            JOIN pg_catalog.pg_am AS access_method
              ON access_method.oid = index_relation.relam
            WHERE namespace.nspname = 'search'
              AND table_relation.relname = 'document_embedding'
            """
        ).fetchall()
    }
    assert index_methods == {"btree"}
