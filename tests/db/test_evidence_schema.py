from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
import time

import psycopg
import pytest
from psycopg.types.json import Jsonb

from financial_agent.db.preflight import normalize_psycopg_url
from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_RECORD_HASH,
    insert_building_dataset,
    insert_entity,
    insert_institution,
    insert_request_run,
    insert_source,
)


VALID_TAGGED_STRING = {"type": "string", "value": "synthetic-value"}
TASK5_VERSIONED_TABLES = (
    "atomic_claim",
    "calculation_dependency",
    "calculation_evidence_input",
    "calculation_exclusion",
    "calculation_parameter",
    "calculation_population",
    "calculation_population_filter",
    "calculation_record",
    "claim_qualifier",
    "claim_support",
    "evidence_document_origin",
    "evidence_observation_origin",
    "evidence_record",
    "evidence_relation_origin",
)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url),
        options="-c timezone=Asia/Seoul",
    ) as database_connection:
        yield database_connection
        database_connection.rollback()


def prepare_dataset(
    connection: psycopg.Connection,
    dataset_version: str = "ledger-v1",
    *,
    source_id: str = "source-one",
    eligible_for_claim: bool = True,
) -> None:
    insert_building_dataset(connection, dataset_version)
    insert_institution(connection, dataset_version=dataset_version)
    insert_source(
        connection,
        dataset_version=dataset_version,
        source_id=source_id,
        eligible_for_claim=eligible_for_claim,
    )
    insert_entity(
        connection,
        dataset_version=dataset_version,
        entity_id="subject-one",
    )
    insert_entity(
        connection,
        dataset_version=dataset_version,
        entity_id="object-one",
    )


def insert_evidence(
    connection: psycopg.Connection,
    *,
    dataset_version: str = "ledger-v1",
    evidence_id: str = "evidence-one",
    evidence_kind: str = "policy",
    source_id: str = "source-one",
    subject_id: str | None = "subject-one",
    value: object = VALID_TAGGED_STRING,
    normalized_value: object = VALID_TAGGED_STRING,
    applicable_date: date | None = date(2026, 8, 24),
    valid_from: date | None = None,
    valid_to: date | None = None,
    published_at: datetime | None = None,
    available_at: datetime | None = None,
    vintage_date: date | None = None,
    cutoff_status: str = "eligible",
    scope_completeness: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence.evidence_record (
            dataset_version, evidence_id, evidence_kind, source_id,
            subject_id, predicate_id, value_or_object_id, normalized_value,
            unit, currency, applicable_date, valid_from, valid_to,
            published_at, available_at, vintage_date, locator_type,
            locator_uri_or_object_key, locator_record_key, locator_sheet,
            locator_row, locator_column, locator_page, locator_section,
            locator_sentence_start, locator_sentence_end, raw_value_repr,
            parser_version, mapping_version, cutoff_status, record_hash,
            scope_completeness, created_at
        ) VALUES (
            %s, %s, %s, %s, %s, 'synthetic-predicate', %s, %s,
            'unit-one', 'KRW', %s, %s, %s, %s, %s, %s, 'tabular',
            'synthetic://ledger/source', 'record-7', 'products', 7, 'aum',
            3, 'risk', 11, 13, 'raw value', 'parser.v1', 'mapping.v1',
            %s, %s, %s, %s
        )
        """,
        (
            dataset_version,
            evidence_id,
            evidence_kind,
            source_id,
            subject_id,
            Jsonb(value),
            Jsonb(normalized_value),
            applicable_date,
            valid_from,
            valid_to,
            published_at,
            available_at,
            vintage_date,
            cutoff_status,
            VALID_RECORD_HASH,
            scope_completeness,
            CREATED_AT,
        ),
    )


@pytest.mark.postgres
def test_evidence_source_must_belong_to_the_same_dataset(
    connection: psycopg.Connection,
) -> None:
    insert_building_dataset(connection, "ledger-v1")
    insert_entity(
        connection,
        dataset_version="ledger-v1",
        entity_id="subject-one",
    )
    prepare_dataset(connection, "ledger-v2")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_evidence(connection, dataset_version="ledger-v1")


@pytest.mark.postgres
def test_evidence_rejects_a_reversed_validity_window(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_evidence(
            connection,
            valid_from=date(2026, 7, 11),
            valid_to=date(2026, 7, 10),
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("evidence_kind", "scope_completeness"),
    (("query_scope", None), ("policy", "closed_world")),
)
def test_scope_completeness_is_exclusive_to_query_scope_evidence(
    connection: psycopg.Connection,
    evidence_kind: str,
    scope_completeness: str | None,
) -> None:
    prepare_dataset(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_evidence(
            connection,
            evidence_kind=evidence_kind,
            scope_completeness=scope_completeness,
        )


@pytest.mark.postgres
def test_after_cutoff_evidence_is_retained_with_explicit_status(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection)
    insert_evidence(
        connection,
        applicable_date=date(2026, 8, 25),
        cutoff_status="after_cutoff",
    )

    assert connection.execute(
        """
        SELECT cutoff_status FROM evidence.evidence_record
        WHERE dataset_version = 'ledger-v1' AND evidence_id = 'evidence-one'
        """
    ).fetchone()[0] == "after_cutoff"


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("applicable_date", date(2026, 8, 25)),
        ("published_at", datetime(2026, 8, 25, tzinfo=UTC)),
        ("available_at", datetime(2026, 8, 25, tzinfo=UTC)),
        ("vintage_date", date(2026, 8, 25)),
    ),
)
def test_each_cutoff_bearing_field_rejects_eligible_after_cutoff(
    connection: psycopg.Connection,
    field: str,
    value: date | datetime,
) -> None:
    prepare_dataset(connection)
    values: dict[str, object] = {"applicable_date": None, field: value}

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_evidence(connection, **values)


@pytest.mark.postgres
def test_after_cutoff_status_requires_an_actual_after_cutoff_field(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_evidence(connection, cutoff_status="after_cutoff")


@pytest.mark.postgres
def test_timestamptz_cutoff_uses_utc_in_a_non_utc_session(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection)
    insert_evidence(
        connection,
        applicable_date=None,
        published_at=datetime(2026, 8, 24, 23, 30, tzinfo=UTC),
    )

    assert connection.execute(
        """
        SELECT evidence_id FROM evidence.claim_eligible_evidence
        WHERE dataset_version = 'ledger-v1' AND evidence_id = 'evidence-one'
        """
    ).fetchone() == ("evidence-one",)


@pytest.mark.postgres
def test_safe_view_repeats_all_cutoff_and_source_eligibility_filters(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection)
    insert_source(
        connection,
        dataset_version="ledger-v1",
        source_id="source-ineligible",
        eligible_for_claim=False,
    )
    insert_evidence(connection, evidence_id="eligible")
    insert_evidence(
        connection,
        evidence_id="after-cutoff",
        applicable_date=date(2026, 8, 25),
        cutoff_status="after_cutoff",
    )
    insert_evidence(
        connection,
        evidence_id="unknown-vintage",
        applicable_date=None,
        cutoff_status="unknown_vintage",
    )
    insert_evidence(
        connection,
        evidence_id="inapplicable",
        applicable_date=None,
        cutoff_status="inapplicable",
    )
    insert_evidence(
        connection,
        evidence_id="source-ineligible",
        source_id="source-ineligible",
    )

    rows = connection.execute(
        """
        SELECT evidence_id
        FROM evidence.claim_eligible_evidence
        WHERE dataset_version = 'ledger-v1'
        ORDER BY evidence_id
        """
    ).fetchall()

    assert rows == [("eligible",)]


@pytest.mark.postgres
def test_evidence_subject_must_be_a_same_dataset_entity(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection, "ledger-v1")
    prepare_dataset(connection, "ledger-v2")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection.transaction():
            insert_evidence(
                connection,
                dataset_version="ledger-v1",
                subject_id="missing-entity",
            )
    insert_entity(
        connection,
        dataset_version="ledger-v2",
        entity_id="cross-version-only",
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection.transaction():
            insert_evidence(
                connection,
                dataset_version="ledger-v1",
                evidence_id="cross-version",
                subject_id="cross-version-only",
            )


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("evidence_kind", "scope_completeness"),
    (
        ("query_scope", "bounded_unknown"),
        ("exclusion", None),
        ("policy", None),
    ),
)
def test_approved_evidence_kinds_may_be_explicitly_subjectless(
    connection: psycopg.Connection,
    evidence_kind: str,
    scope_completeness: str | None,
) -> None:
    prepare_dataset(connection)
    insert_evidence(
        connection,
        evidence_kind=evidence_kind,
        subject_id=None,
        scope_completeness=scope_completeness,
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
@pytest.mark.parametrize("evidence_kind", ("observation", "relation", "document_span"))
def test_origin_backed_evidence_requires_a_subject(
    connection: psycopg.Connection,
    evidence_kind: str,
) -> None:
    prepare_dataset(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_evidence(
            connection,
            evidence_kind=evidence_kind,
            subject_id=None,
        )


@pytest.mark.postgres
def test_source_locator_components_round_trip_as_columns(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection)
    insert_evidence(connection)

    row = connection.execute(
        """
        SELECT locator_type, locator_uri_or_object_key, locator_record_key,
               locator_sheet, locator_row, locator_column, locator_page,
               locator_section, locator_sentence_start, locator_sentence_end
        FROM evidence.evidence_record
        WHERE dataset_version = 'ledger-v1' AND evidence_id = 'evidence-one'
        """
    ).fetchone()
    columns = {
        str(column)
        for (column,) in connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'evidence' AND table_name = 'evidence_record'
            """
        ).fetchall()
    }

    assert row == (
        "tabular",
        "synthetic://ledger/source",
        "record-7",
        "products",
        7,
        "aum",
        3,
        "risk",
        11,
        13,
    )
    assert "source_locator" not in columns


@pytest.mark.postgres
@pytest.mark.parametrize(
    "tagged_value",
    (
        {"type": "null", "value": None},
        {"type": "string", "value": "2026-07-11"},
        {"type": "integer", "value": 7},
        {"type": "decimal", "value": "125000000.01"},
        {"type": "boolean", "value": True},
        {"type": "date", "value": "2026-07-11"},
        {"type": "datetime", "value": "2026-07-11T00:00:00Z"},
        {"type": "datetime", "value": "2026-07-11T00:00:00.123456Z"},
        {
            "type": "tuple",
            "items": [
                {"type": "date", "value": "2026-07-11"},
                {"type": "string", "value": "2026-07-11"},
            ],
        },
    ),
)
def test_tagged_value_function_accepts_exact_stage01_shapes(
    connection: psycopg.Connection,
    tagged_value: object,
) -> None:
    assert connection.execute(
        "SELECT evidence.is_valid_tagged_value(%s)",
        (Jsonb(tagged_value),),
    ).fetchone()[0] is True


@pytest.mark.postgres
@pytest.mark.parametrize(
    "tagged_value",
    (
        "untagged",
        {"type": "unknown", "value": "x"},
        {"type": "integer", "value": 1.0},
        {"type": "decimal", "value": "1.0"},
        {"type": "date", "value": "2026-02-30"},
        {"type": "datetime", "value": "2026-07-11T09:00:00+09:00"},
        {"type": "datetime", "value": "2026-07-11T00:00:00.1Z"},
        {"type": "datetime", "value": "2026-07-11T00:00:00.000000Z"},
        {"type": "datetime", "value": "2026-07-11T24:00:00Z"},
        {"type": "string", "value": "x", "extra": True},
        {
            "type": "tuple",
            "items": [{"type": "tuple", "items": []}],
        },
    ),
)
def test_tagged_value_function_rejects_lossy_or_noncontract_shapes(
    connection: psycopg.Connection,
    tagged_value: object,
) -> None:
    assert connection.execute(
        "SELECT evidence.is_valid_tagged_value(%s)",
        (Jsonb(tagged_value),),
    ).fetchone()[0] is False


@pytest.mark.postgres
def test_tagged_scalar_columns_enforce_the_validator(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_evidence(
            connection,
            value={"type": "decimal", "value": "1.0"},
        )


def insert_origin_fixtures(connection: psycopg.Connection) -> None:
    connection.execute(
        """
        INSERT INTO observation.metric_definition (
            metric_id, definition_version, semantic_family, value_kind,
            definition_hash, approved_at
        ) VALUES ('metric-one', '1', 'financial', 'numeric', %s, %s)
        """,
        ("e" * 64, CREATED_AT),
    )
    connection.execute(
        """
        INSERT INTO observation.observation_record (
            dataset_version, observation_id, entity_id, metric_id,
            metric_definition_version, value_status, numeric_value,
            record_hash, created_at
        ) VALUES ('ledger-v1', 'observation-one', 'subject-one', 'metric-one',
                  '1', 'present', 1, %s, %s)
        """,
        (VALID_RECORD_HASH, CREATED_AT),
    )
    connection.execute(
        """
        INSERT INTO relation.relation_record (
            dataset_version, relation_id, subject_id, predicate_id, object_id,
            record_hash, created_at
        ) VALUES ('ledger-v1', 'relation-one', 'subject-one', 'related-to',
                  'object-one', %s, %s)
        """,
        (VALID_RECORD_HASH, CREATED_AT),
    )
    connection.execute(
        """
        INSERT INTO document.document_record (
            dataset_version, document_id, source_id, document_title,
            document_type, object_key, content_checksum, record_hash, created_at
        ) VALUES ('ledger-v1', 'document-one', 'source-one', 'Synthetic doc',
                  'filing', 'synthetic/doc', %s, %s, %s)
        """,
        ("f" * 64, VALID_RECORD_HASH, CREATED_AT),
    )
    connection.execute(
        """
        INSERT INTO document.document_chunk (
            dataset_version, chunk_id, document_id, ordinal, exact_text,
            normalized_search_text, content_hash, record_hash, created_at,
            section_type, section_path, character_start, character_end
        ) VALUES ('ledger-v1', 'chunk-one', 'document-one', 0, 'Synthetic text',
                  'synthetic text', %s, %s, %s, 'legacy_unclassified',
                  'Synthetic doc', 0, 14)
        """,
        ("f" * 64, VALID_RECORD_HASH, CREATED_AT),
    )


@pytest.mark.postgres
def test_each_origin_backed_kind_requires_exactly_its_matching_origin(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection)
    insert_origin_fixtures(connection)
    for evidence_id, evidence_kind in (
        ("evidence-observation", "observation"),
        ("evidence-relation", "relation"),
        ("evidence-document", "document_span"),
    ):
        insert_evidence(
            connection,
            evidence_id=evidence_id,
            evidence_kind=evidence_kind,
        )
    connection.execute(
        """
        INSERT INTO evidence.evidence_observation_origin (
            dataset_version, evidence_id, observation_id
        ) VALUES ('ledger-v1', 'evidence-observation', 'observation-one')
        """
    )
    connection.execute(
        """
        INSERT INTO evidence.evidence_relation_origin (
            dataset_version, evidence_id, relation_id
        ) VALUES ('ledger-v1', 'evidence-relation', 'relation-one')
        """
    )
    connection.execute(
        """
        INSERT INTO evidence.evidence_document_origin (
            dataset_version, evidence_id, chunk_id
        ) VALUES ('ledger-v1', 'evidence-document', 'chunk-one')
        """
    )

    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
def test_deferred_origin_validation_rejects_missing_or_forbidden_origins(
    connection: psycopg.Connection,
) -> None:
    prepare_dataset(connection)
    insert_origin_fixtures(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        with connection.transaction():
            insert_evidence(
                connection,
                evidence_id="missing-origin",
                evidence_kind="observation",
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

    with pytest.raises(psycopg.errors.CheckViolation):
        with connection.transaction():
            insert_evidence(
                connection,
                evidence_id="forbidden-origin",
                evidence_kind="policy",
            )
            connection.execute(
                """
                INSERT INTO evidence.evidence_relation_origin (
                    dataset_version, evidence_id, relation_id
                ) VALUES ('ledger-v1', 'forbidden-origin', 'relation-one')
                """
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
def test_later_transaction_cannot_add_a_second_origin(
    migrated_database_url: str,
) -> None:
    from tests.db.test_foundation_migration import _truncate_foundation_tables

    database_url = normalize_psycopg_url(migrated_database_url)
    _truncate_foundation_tables(database_url)
    try:
        with psycopg.connect(database_url) as setup_connection:
            prepare_dataset(setup_connection)
            insert_origin_fixtures(setup_connection)
            insert_evidence(
                setup_connection,
                evidence_kind="observation",
            )
            setup_connection.execute(
                """
                INSERT INTO evidence.evidence_observation_origin (
                    dataset_version, evidence_id, observation_id
                ) VALUES ('ledger-v1', 'evidence-one', 'observation-one')
                """
            )
            setup_connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

        with pytest.raises(psycopg.errors.CheckViolation):
            with psycopg.connect(database_url) as later_connection:
                later_connection.execute(
                    """
                    INSERT INTO evidence.evidence_relation_origin (
                        dataset_version, evidence_id, relation_id
                    ) VALUES ('ledger-v1', 'evidence-one', 'relation-one')
                    """
                )
    finally:
        _truncate_foundation_tables(database_url)


@pytest.mark.postgres
def test_evidence_can_be_appended_after_its_source_dataset_is_active(
    connection: psycopg.Connection,
) -> None:
    from tests.db.test_foundation_migration import (
        finish_and_ready_dataset,
        insert_dataset_validation,
    )

    insert_dataset_validation(
        connection,
        dataset_version="ledger-active",
        validation_run_id="ledger-active-validation",
    )
    insert_institution(connection, dataset_version="ledger-active")
    insert_source(connection, dataset_version="ledger-active")
    insert_entity(
        connection,
        dataset_version="ledger-active",
        entity_id="subject-one",
    )
    finish_and_ready_dataset(
        connection,
        dataset_version="ledger-active",
        validation_run_id="ledger-active-validation",
    )
    connection.execute("SELECT operations.activate_dataset('ledger-active')")

    insert_evidence(connection, dataset_version="ledger-active")
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def prepare_request(
    connection: psycopg.Connection,
    dataset_version: str = "ledger-v1",
    *,
    run_id: str = "run-one",
    subtask_id: str = "subtask-one",
) -> None:
    prepare_dataset(connection, dataset_version)
    insert_request_run(
        connection,
        dataset_version=dataset_version,
        run_id=run_id,
        subtask_id=subtask_id,
    )


def insert_calculation(
    connection: psycopg.Connection,
    *,
    run_id: str = "run-one",
    dataset_version: str = "ledger-v1",
    calculation_id: str = "calculation-one",
    calculation_type: str = "conversion",
    tie_break_rule: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence.calculation_record (
            run_id, dataset_version, calculation_id, calculation_type,
            formula_id, formula_version, tie_break_rule, result_value,
            unit, currency, rounding_rule, calculation_hash, created_at
        ) VALUES (%s, %s, %s, %s, 'formula-one', '1', %s, %s,
                  'unit-one', 'KRW', 'half-even', %s, %s)
        """,
        (
            run_id,
            dataset_version,
            calculation_id,
            calculation_type,
            tie_break_rule,
            Jsonb({"type": "decimal", "value": "1.25"}),
            "1" * 64,
            CREATED_AT,
        ),
    )


def insert_calculation_evidence_input(
    connection: psycopg.Connection,
    *,
    run_id: str = "run-one",
    dataset_version: str = "ledger-v1",
    calculation_id: str = "calculation-one",
    evidence_id: str = "evidence-one",
    ordinal: int = 0,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence.calculation_evidence_input (
            run_id, dataset_version, calculation_id, evidence_id, ordinal
        ) VALUES (%s, %s, %s, %s, %s)
        """,
        (run_id, dataset_version, calculation_id, evidence_id, ordinal),
    )


def insert_population(
    connection: psycopg.Connection,
    *,
    run_id: str = "run-one",
    dataset_version: str = "ledger-v1",
    calculation_id: str = "calculation-one",
    scope_evidence_id: str = "scope-one",
    include_filter: bool = True,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence.calculation_population (
            run_id, dataset_version, calculation_id, population_id,
            scope_evidence_id, member_count, population_hash
        ) VALUES (%s, %s, %s, 'population-one', %s, 10, %s)
        """,
        (
            run_id,
            dataset_version,
            calculation_id,
            scope_evidence_id,
            "2" * 64,
        ),
    )
    if include_filter:
        connection.execute(
            """
            INSERT INTO evidence.calculation_population_filter (
                run_id, dataset_version, calculation_id, ordinal, filter_id
            ) VALUES (%s, %s, %s, 0, 'filter-one')
            """,
            (run_id, dataset_version, calculation_id),
        )


def insert_claim(
    connection: psycopg.Connection,
    *,
    run_id: str = "run-one",
    dataset_version: str = "ledger-v1",
    claim_id: str = "claim-one",
    claim_type: str = "direct_fact",
    subtask_id: str = "subtask-one",
    subject_id: str = "subject-one",
    subject_kind: str = "entity",
    subject_entity_id: str | None = "subject-one",
    request_subject_id: str | None = None,
    object_id: str | None = None,
    value: object | None = VALID_TAGGED_STRING,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence.atomic_claim (
            run_id, dataset_version, claim_id, claim_type, subtask_id,
            subject_id, subject_kind, subject_entity_id, request_subject_id,
            predicate_id, object_id, value, unit, currency, display_policy_id,
            claim_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                  'synthetic-predicate', %s, %s, 'unit-one', 'KRW',
                  'display.v1', %s, %s)
        """,
        (
            run_id,
            dataset_version,
            claim_id,
            claim_type,
            subtask_id,
            subject_id,
            subject_kind,
            subject_entity_id,
            request_subject_id,
            object_id,
            Jsonb(value) if value is not None else None,
            "3" * 64,
            CREATED_AT,
        ),
    )


def insert_claim_support(
    connection: psycopg.Connection,
    *,
    run_id: str = "run-one",
    dataset_version: str = "ledger-v1",
    claim_id: str = "claim-one",
    support_kind: str = "direct",
    evidence_id: str | None = "evidence-one",
    calculation_id: str | None = None,
    ordinal: int = 0,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence.claim_support (
            run_id, dataset_version, claim_id, support_kind, evidence_id,
            calculation_id, support_role, ordinal
        ) VALUES (%s, %s, %s, %s, %s, %s, 'value', %s)
        """,
        (
            run_id,
            dataset_version,
            claim_id,
            support_kind,
            evidence_id,
            calculation_id,
            ordinal,
        ),
    )


def prepare_calculation_input(connection: psycopg.Connection) -> None:
    prepare_request(connection)
    insert_evidence(connection)


@pytest.mark.postgres
def test_calculation_requires_an_evidence_input_or_dependency(
    connection: psycopg.Connection,
) -> None:
    prepare_calculation_input(connection)
    insert_calculation(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
def test_calculation_and_claim_dataset_must_equal_the_request_dataset(
    connection: psycopg.Connection,
) -> None:
    prepare_calculation_input(connection)
    prepare_dataset(connection, "ledger-v2")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection.transaction():
            insert_calculation(connection, dataset_version="ledger-v2")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection.transaction():
            insert_claim(connection, dataset_version="ledger-v2")


@pytest.mark.postgres
def test_every_task5_versioned_table_has_a_direct_restrict_dataset_fk(
    connection: psycopg.Connection,
) -> None:
    versioned_tables = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT column_row.table_name
            FROM information_schema.columns AS column_row
            JOIN information_schema.tables AS table_row
              ON table_row.table_schema = column_row.table_schema
             AND table_row.table_name = column_row.table_name
            WHERE column_row.table_schema = 'evidence'
              AND column_row.column_name = 'dataset_version'
              AND column_row.table_name <> 'source_record'
              AND table_row.table_type = 'BASE TABLE'
            """
        ).fetchall()
    }
    direct_dataset_fks = {
        str(table_name): (
            str(constraint_name),
            tuple(child_columns),
            str(parent_schema),
            str(parent_table),
            tuple(parent_columns),
            str(delete_action),
        )
        for (
            table_name,
            constraint_name,
            child_columns,
            parent_schema,
            parent_table,
            parent_columns,
            delete_action,
        ) in connection.execute(
            """
            SELECT child.relname, constraint_row.conname,
                   ARRAY(
                       SELECT attribute.attname
                       FROM unnest(constraint_row.conkey)
                            WITH ORDINALITY AS key(attnum, position)
                       JOIN pg_catalog.pg_attribute AS attribute
                         ON attribute.attrelid = child.oid
                        AND attribute.attnum = key.attnum
                       ORDER BY key.position
                   ),
                   parent_namespace.nspname, parent.relname,
                   ARRAY(
                       SELECT attribute.attname
                       FROM unnest(constraint_row.confkey)
                            WITH ORDINALITY AS key(attnum, position)
                       JOIN pg_catalog.pg_attribute AS attribute
                         ON attribute.attrelid = parent.oid
                        AND attribute.attnum = key.attnum
                       ORDER BY key.position
                   ),
                   constraint_row.confdeltype
            FROM pg_catalog.pg_constraint AS constraint_row
            JOIN pg_catalog.pg_class AS child
              ON child.oid = constraint_row.conrelid
            JOIN pg_catalog.pg_namespace AS child_namespace
              ON child_namespace.oid = child.relnamespace
            JOIN pg_catalog.pg_class AS parent
              ON parent.oid = constraint_row.confrelid
            JOIN pg_catalog.pg_namespace AS parent_namespace
              ON parent_namespace.oid = parent.relnamespace
            WHERE constraint_row.contype = 'f'
              AND child_namespace.nspname = 'evidence'
              AND child.relname = ANY(%s)
              AND parent_namespace.nspname = 'operations'
              AND parent.relname = 'dataset_version'
            """,
            (list(TASK5_VERSIONED_TABLES),),
        ).fetchall()
    }

    assert versioned_tables == set(TASK5_VERSIONED_TABLES)
    assert direct_dataset_fks == {
        table_name: (
            f"fk_{table_name}_dataset_version",
            ("dataset_version",),
            "operations",
            "dataset_version",
            ("dataset_version",),
            "r",
        )
        for table_name in TASK5_VERSIONED_TABLES
    }


@pytest.mark.postgres
def test_calculation_dependency_rejects_cross_run_and_self_references(
    connection: psycopg.Connection,
) -> None:
    prepare_calculation_input(connection)
    insert_request_run(
        connection,
        dataset_version="ledger-v1",
        run_id="run-two",
        subtask_id="subtask-two",
    )
    for run_id, calculation_id in (
        ("run-one", "calculation-one"),
        ("run-two", "calculation-two"),
    ):
        insert_calculation(
            connection,
            run_id=run_id,
            calculation_id=calculation_id,
        )
        insert_calculation_evidence_input(
            connection,
            run_id=run_id,
            calculation_id=calculation_id,
        )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO evidence.calculation_dependency (
                    run_id, dataset_version, calculation_id,
                    input_calculation_id, ordinal
                ) VALUES ('run-one', 'ledger-v1', 'calculation-one',
                          'calculation-two', 0)
                """
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            """
            INSERT INTO evidence.calculation_dependency (
                run_id, dataset_version, calculation_id,
                input_calculation_id, ordinal
            ) VALUES ('run-one', 'ledger-v1', 'calculation-one',
                      'calculation-one', 0)
            """
        )


@pytest.mark.postgres
@pytest.mark.parametrize("node_count", (2, 3))
def test_deferred_calculation_cycle_check_rejects_multi_node_cycles(
    connection: psycopg.Connection,
    node_count: int,
) -> None:
    prepare_calculation_input(connection)
    calculation_ids = [f"calculation-{index}" for index in range(node_count)]
    for calculation_id in calculation_ids:
        insert_calculation(connection, calculation_id=calculation_id)
        insert_calculation_evidence_input(
            connection,
            calculation_id=calculation_id,
        )
    for ordinal, (calculation_id, dependency_id) in enumerate(
        zip(calculation_ids, calculation_ids[1:] + calculation_ids[:1], strict=True)
    ):
        connection.execute(
            """
            INSERT INTO evidence.calculation_dependency (
                run_id, dataset_version, calculation_id,
                input_calculation_id, ordinal
            ) VALUES ('run-one', 'ledger-v1', %s, %s, %s)
            """,
            (calculation_id, dependency_id, ordinal),
        )

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
def test_concurrent_same_run_dependencies_serialize_and_leave_an_acyclic_graph(
    migrated_database_url: str,
) -> None:
    from tests.db.test_foundation_migration import _truncate_foundation_tables

    database_url = normalize_psycopg_url(migrated_database_url)
    _truncate_foundation_tables(database_url)
    first_connection: psycopg.Connection | None = None
    second_connection: psycopg.Connection | None = None
    try:
        with psycopg.connect(database_url) as setup_connection:
            prepare_calculation_input(setup_connection)
            for calculation_id in ("calculation-a", "calculation-b"):
                insert_calculation(
                    setup_connection,
                    calculation_id=calculation_id,
                )
                insert_calculation_evidence_input(
                    setup_connection,
                    calculation_id=calculation_id,
                )

        first_connection = psycopg.connect(database_url)
        second_connection = psycopg.connect(database_url)
        first_connection.execute(
            """
            INSERT INTO evidence.calculation_dependency (
                run_id, dataset_version, calculation_id,
                input_calculation_id, ordinal
            ) VALUES ('run-one', 'ledger-v1', 'calculation-a',
                      'calculation-b', 0)
            """
        )

        def insert_reverse_dependency() -> str:
            assert second_connection is not None
            try:
                second_connection.execute(
                    """
                    INSERT INTO evidence.calculation_dependency (
                        run_id, dataset_version, calculation_id,
                        input_calculation_id, ordinal
                    ) VALUES ('run-one', 'ledger-v1', 'calculation-b',
                              'calculation-a', 0)
                    """
                )
                second_connection.commit()
            except psycopg.errors.CheckViolation:
                second_connection.rollback()
                return "cycle_rejected"
            return "committed"

        with ThreadPoolExecutor(max_workers=1) as executor:
            reverse_result = executor.submit(insert_reverse_dependency)
            deadline = time.monotonic() + 2
            wait_event_type = None
            while time.monotonic() < deadline and not reverse_result.done():
                with psycopg.connect(database_url, autocommit=True) as observer:
                    wait_event_type = observer.execute(
                        """
                        SELECT wait_event_type
                        FROM pg_catalog.pg_stat_activity
                        WHERE pid = %s
                        """,
                        (second_connection.info.backend_pid,),
                    ).fetchone()[0]
                if wait_event_type == "Lock":
                    break
                time.sleep(0.01)

            assert wait_event_type == "Lock", (
                "the reverse dependency INSERT did not serialize on the run"
            )
            first_connection.commit()
            assert reverse_result.result(timeout=2) == "cycle_rejected"

        with psycopg.connect(database_url) as verification_connection:
            stored_edges = verification_connection.execute(
                """
                SELECT calculation_id, input_calculation_id
                FROM evidence.calculation_dependency
                WHERE run_id = 'run-one'
                ORDER BY calculation_id, input_calculation_id
                """
            ).fetchall()
            cycle_count = verification_connection.execute(
                """
                WITH RECURSIVE dependency_path(
                    origin_id, calculation_id, visited, is_cycle
                ) AS (
                    SELECT calculation_id, input_calculation_id,
                           ARRAY[calculation_id, input_calculation_id],
                           calculation_id = input_calculation_id
                    FROM evidence.calculation_dependency
                    WHERE run_id = 'run-one'
                    UNION ALL
                    SELECT path.origin_id, edge.input_calculation_id,
                           path.visited || edge.input_calculation_id,
                           edge.input_calculation_id = ANY(path.visited)
                    FROM dependency_path AS path
                    JOIN evidence.calculation_dependency AS edge
                      ON edge.run_id = 'run-one'
                     AND edge.calculation_id = path.calculation_id
                    WHERE NOT path.is_cycle
                )
                SELECT count(*) FROM dependency_path WHERE is_cycle
                """
            ).fetchone()[0]

        assert stored_edges == [("calculation-a", "calculation-b")]
        assert cycle_count == 0
    finally:
        if first_connection is not None:
            first_connection.close()
        if second_connection is not None:
            second_connection.close()
        _truncate_foundation_tables(database_url)


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("calculation_type", "include_population", "include_filter", "tie_break_rule"),
    (
        ("ranking", False, False, "entity-id"),
        ("ranking", True, False, "entity-id"),
        ("ranking", True, True, None),
        ("aggregation", False, False, None),
    ),
)
def test_ranking_and_aggregation_require_complete_population_metadata(
    connection: psycopg.Connection,
    calculation_type: str,
    include_population: bool,
    include_filter: bool,
    tie_break_rule: str | None,
) -> None:
    prepare_calculation_input(connection)
    insert_evidence(
        connection,
        evidence_id="scope-one",
        evidence_kind="query_scope",
        subject_id=None,
        scope_completeness="closed_world",
    )
    insert_calculation(
        connection,
        calculation_type=calculation_type,
        tie_break_rule=tie_break_rule,
    )
    insert_calculation_evidence_input(connection)
    if include_population:
        insert_population(connection, include_filter=include_filter)

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
def test_population_scope_evidence_must_match_the_request_dataset(
    connection: psycopg.Connection,
) -> None:
    prepare_calculation_input(connection)
    prepare_dataset(connection, "ledger-v2")
    insert_evidence(
        connection,
        dataset_version="ledger-v2",
        evidence_id="scope-other-version",
        evidence_kind="query_scope",
        subject_id=None,
        scope_completeness="closed_world",
    )
    insert_calculation(
        connection,
        calculation_type="ranking",
        tie_break_rule="entity-id",
    )
    insert_calculation_evidence_input(connection)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_population(
            connection,
            scope_evidence_id="scope-other-version",
        )


@pytest.mark.postgres
def test_valid_ranking_forces_all_deferred_calculation_rules(
    connection: psycopg.Connection,
) -> None:
    prepare_calculation_input(connection)
    insert_evidence(
        connection,
        evidence_id="scope-one",
        evidence_kind="query_scope",
        subject_id=None,
        scope_completeness="closed_world",
    )
    insert_calculation(
        connection,
        calculation_type="ranking",
        tie_break_rule="entity-id",
    )
    insert_calculation_evidence_input(connection)
    insert_population(connection)

    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("claim_type", "object_id", "value"),
    (
        ("direct_fact", "object-one", VALID_TAGGED_STRING),
        ("direct_fact", None, None),
        ("no_match", None, None),
    ),
)
def test_claim_object_and_value_rules_match_stage01(
    connection: psycopg.Connection,
    claim_type: str,
    object_id: str | None,
    value: object | None,
) -> None:
    prepare_calculation_input(connection)
    request_bound = claim_type == "no_match"

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_claim(
            connection,
            claim_type=claim_type,
            subject_id="subtask-one" if request_bound else "subject-one",
            subject_kind="request" if request_bound else "entity",
            subject_entity_id=None if request_bound else "subject-one",
            request_subject_id="subtask-one" if request_bound else None,
            object_id=object_id,
            value=value,
        )


@pytest.mark.postgres
@pytest.mark.parametrize("claim_type", ("data_limitation", "policy_boundary"))
def test_qualifier_only_claims_require_a_structured_qualifier(
    connection: psycopg.Connection,
    claim_type: str,
) -> None:
    prepare_calculation_input(connection)
    insert_claim(
        connection,
        claim_type=claim_type,
        subject_id="subtask-one",
        subject_kind="request",
        subject_entity_id=None,
        request_subject_id="subtask-one",
        value=None,
    )
    insert_claim_support(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
@pytest.mark.parametrize(
    "claim_type",
    ("direct_fact", "relation", "derived_metric", "rank", "similarity"),
)
def test_entity_bound_claims_require_same_dataset_subject_and_object(
    connection: psycopg.Connection,
    claim_type: str,
) -> None:
    prepare_calculation_input(connection)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection.transaction():
            insert_claim(
                connection,
                claim_type=claim_type,
                subject_id="missing-subject",
                subject_entity_id="missing-subject",
            )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection.transaction():
            insert_claim(
                connection,
                claim_type=claim_type,
                object_id="missing-object",
                value=None,
            )


@pytest.mark.postgres
@pytest.mark.parametrize("claim_type", ("no_match", "data_limitation", "policy_boundary"))
def test_request_bound_claim_subject_is_the_same_run_subtask(
    connection: psycopg.Connection,
    claim_type: str,
) -> None:
    prepare_calculation_input(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_claim(
            connection,
            claim_type=claim_type,
            subject_id="wrong-subtask",
            subject_kind="request",
            subject_entity_id=None,
            request_subject_id="wrong-subtask",
            value=VALID_TAGGED_STRING if claim_type == "no_match" else None,
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("claim_type", "subject_kind", "subject_entity_id", "request_subject_id"),
    (
        ("direct_fact", "entity", None, None),
        ("no_match", "request", None, None),
    ),
)
def test_claim_subject_scope_columns_cannot_be_omitted(
    connection: psycopg.Connection,
    claim_type: str,
    subject_kind: str,
    subject_entity_id: str | None,
    request_subject_id: str | None,
) -> None:
    prepare_calculation_input(connection)
    request_bound = subject_kind == "request"

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_claim(
            connection,
            claim_type=claim_type,
            subject_id="subtask-one" if request_bound else "subject-one",
            subject_kind=subject_kind,
            subject_entity_id=subject_entity_id,
            request_subject_id=request_subject_id,
        )


@pytest.mark.postgres
def test_request_bound_claim_requires_a_registered_same_run_subtask(
    connection: psycopg.Connection,
) -> None:
    prepare_calculation_input(connection)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_claim(
            connection,
            claim_type="no_match",
            subtask_id="unregistered-subtask",
            subject_id="unregistered-subtask",
            subject_kind="request",
            subject_entity_id=None,
            request_subject_id="unregistered-subtask",
        )


@pytest.mark.postgres
def test_every_claim_requires_support_when_constraints_are_forced(
    connection: psycopg.Connection,
) -> None:
    prepare_calculation_input(connection)
    insert_claim(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("support_kind", "evidence_id", "calculation_id"),
    (
        ("direct", None, None),
        ("direct", "evidence-one", "calculation-one"),
        ("calculation", "evidence-one", None),
    ),
)
def test_claim_support_accepts_exactly_one_compatible_target(
    connection: psycopg.Connection,
    support_kind: str,
    evidence_id: str | None,
    calculation_id: str | None,
) -> None:
    prepare_calculation_input(connection)
    insert_calculation(connection)
    insert_calculation_evidence_input(connection)
    insert_claim(connection)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_claim_support(
            connection,
            support_kind=support_kind,
            evidence_id=evidence_id,
            calculation_id=calculation_id,
        )


@pytest.mark.postgres
def test_claim_support_targets_stay_in_the_claim_run_and_dataset(
    connection: psycopg.Connection,
) -> None:
    prepare_calculation_input(connection)
    insert_request_run(
        connection,
        dataset_version="ledger-v1",
        run_id="run-two",
        subtask_id="subtask-two",
    )
    insert_calculation(
        connection,
        run_id="run-two",
        calculation_id="calculation-two",
    )
    insert_calculation_evidence_input(
        connection,
        run_id="run-two",
        calculation_id="calculation-two",
    )
    insert_claim(connection)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_claim_support(
            connection,
            support_kind="calculation",
            evidence_id=None,
            calculation_id="calculation-two",
        )


@pytest.mark.postgres
def test_valid_qualifier_only_claim_forces_support_and_qualifier_rules(
    connection: psycopg.Connection,
) -> None:
    prepare_calculation_input(connection)
    insert_claim(
        connection,
        claim_type="data_limitation",
        subject_id="subtask-one",
        subject_kind="request",
        subject_entity_id=None,
        request_subject_id="subtask-one",
        value=None,
    )
    connection.execute(
        """
        INSERT INTO evidence.claim_qualifier (
            run_id, dataset_version, claim_id, ordinal, qualifier_id, value
        ) VALUES ('run-one', 'ledger-v1', 'claim-one', 0,
                  'reason-code', %s)
        """,
        (Jsonb({"type": "string", "value": "missing-field"}),),
    )
    insert_claim_support(connection)

    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("table", "insert_statement", "ordinal_column"),
    (
        (
            "calculation_parameter",
            """INSERT INTO evidence.calculation_parameter
               (run_id,dataset_version,calculation_id,ordinal,parameter_id,value)
               VALUES ('run-one','ledger-v1','calculation-one',%s,'p',%s)""",
            True,
        ),
        (
            "calculation_exclusion",
            """INSERT INTO evidence.calculation_exclusion
               (run_id,dataset_version,calculation_id,evidence_id,ordinal)
               VALUES ('run-one','ledger-v1','calculation-one','evidence-one',%s)""",
            False,
        ),
        (
            "claim_qualifier",
            """INSERT INTO evidence.claim_qualifier
               (run_id,dataset_version,claim_id,ordinal,qualifier_id,value)
               VALUES ('run-one','ledger-v1','claim-one',%s,'q',%s)""",
            True,
        ),
    ),
)
def test_ordered_associations_reject_negative_ordinals(
    connection: psycopg.Connection,
    table: str,
    insert_statement: str,
    ordinal_column: bool,
) -> None:
    del table
    prepare_calculation_input(connection)
    insert_calculation(connection)
    insert_calculation_evidence_input(connection)
    insert_claim(connection)
    parameters: tuple[object, ...]
    if ordinal_column:
        parameters = (-1, Jsonb(VALID_TAGGED_STRING))
    else:
        parameters = (-1,)

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(insert_statement, parameters)


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("table", "key_column"),
    (
        ("calculation_parameter", "calculation_id"),
        ("calculation_evidence_input", "calculation_id"),
        ("calculation_dependency", "calculation_id"),
        ("calculation_exclusion", "calculation_id"),
        ("calculation_population_filter", "calculation_id"),
        ("claim_qualifier", "claim_id"),
        ("claim_support", "claim_id"),
    ),
)
def test_every_ordered_association_has_a_unique_nonnegative_ordinal_constraint(
    connection: psycopg.Connection,
    table: str,
    key_column: str,
) -> None:
    checks = connection.execute(
        """
        SELECT pg_get_constraintdef(constraint_record.oid)
        FROM pg_catalog.pg_constraint AS constraint_record
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = constraint_record.conrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'evidence'
          AND relation.relname = %s
        """,
        (table,),
    ).fetchall()
    definitions = " ".join(str(row[0]) for row in checks)

    assert "CHECK ((ordinal >= 0))" in definitions
    assert f"PRIMARY KEY (run_id, {key_column}, ordinal)" in definitions


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("table", "prepare_statement", "mutation"),
    (
        ("evidence_record", None, "UPDATE evidence.evidence_record SET unit='x' WHERE evidence_id='evidence-one'"),
        ("calculation_record", None, "DELETE FROM evidence.calculation_record WHERE calculation_id='calculation-one'"),
        ("atomic_claim", None, "UPDATE evidence.atomic_claim SET unit='x' WHERE claim_id='claim-one'"),
        ("claim_qualifier", "qualifier", "DELETE FROM evidence.claim_qualifier WHERE claim_id='claim-one'"),
        ("claim_support", "support", "DELETE FROM evidence.claim_support WHERE claim_id='claim-one'"),
    ),
)
def test_ledger_parent_and_association_rows_are_append_only(
    connection: psycopg.Connection,
    table: str,
    prepare_statement: str | None,
    mutation: str,
) -> None:
    del table
    prepare_calculation_input(connection)
    insert_calculation(connection)
    insert_calculation_evidence_input(connection)
    insert_claim(connection)
    if prepare_statement == "qualifier":
        connection.execute(
            """
            INSERT INTO evidence.claim_qualifier (
                run_id,dataset_version,claim_id,ordinal,qualifier_id,value
            ) VALUES ('run-one','ledger-v1','claim-one',0,'q',%s)
            """,
            (Jsonb(VALID_TAGGED_STRING),),
        )
    if prepare_statement == "support":
        insert_claim_support(connection)

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(mutation)


@pytest.mark.postgres
def test_task5_objects_follow_ownership_acl_and_hardened_function_rules(
    connection: psycopg.Connection,
) -> None:
    tables = {
        "evidence_record",
        "evidence_observation_origin",
        "evidence_relation_origin",
        "evidence_document_origin",
        "calculation_record",
        "calculation_parameter",
        "calculation_evidence_input",
        "calculation_dependency",
        "calculation_exclusion",
        "calculation_population",
        "calculation_population_filter",
        "atomic_claim",
        "claim_qualifier",
        "claim_support",
    }
    owners = dict(
        connection.execute(
            """
            SELECT relation.relname, owner.rolname
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles AS owner
              ON owner.oid = relation.relowner
            WHERE namespace.nspname = 'evidence'
              AND relation.relname = ANY(%s)
            """,
            (list(tables),),
        ).fetchall()
    )
    assert owners == {table: "fa_migration" for table in tables}

    for role in ("fa_build", "fa_runtime"):
        for table in tables:
            privileges = {
                privilege
                for (privilege,) in connection.execute(
                    """
                    SELECT privilege_type
                    FROM information_schema.role_table_grants
                    WHERE grantee = %s AND table_schema = 'evidence'
                      AND table_name = %s
                    """,
                    (role, table),
                ).fetchall()
            }
            assert privileges == {"SELECT", "INSERT"}

    functions = connection.execute(
        """
        SELECT procedure.proname, procedure.oid, procedure.prosecdef,
               owner.rolname, procedure.proconfig,
               has_function_privilege('public', procedure.oid, 'EXECUTE')
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        JOIN pg_catalog.pg_roles AS owner
          ON owner.oid = procedure.proowner
        WHERE namespace.nspname = 'evidence'
          AND procedure.proname = ANY(%s)
        """,
        (
            [
                "is_valid_tagged_value",
                "reject_mutation",
                "validate_cutoff_status",
                "validate_evidence_origin",
                "validate_calculation_aggregate",
                "reject_calculation_cycle",
                "validate_claim_aggregate",
            ],
        ),
    ).fetchall()
    assert len(functions) == 7
    for name, oid, security_definer, owner, settings, public_execute in functions:
        assert owner == "fa_migration"
        assert public_execute is False
        assert settings and any(
            setting.startswith("search_path=pg_catalog, evidence")
            for setting in settings
        )
        assert security_definer is (name != "is_valid_tagged_value")
        for role in ("fa_build", "fa_runtime"):
            can_execute = connection.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                (role, oid),
            ).fetchone()[0]
            assert can_execute is (name == "is_valid_tagged_value")


@pytest.mark.postgres
def test_task5_parent_rows_store_no_normalized_association_arrays(
    connection: psycopg.Connection,
) -> None:
    columns = {
        (str(table), str(column), str(data_type))
        for table, column, data_type in connection.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'evidence'
              AND table_name IN ('calculation_record', 'atomic_claim')
            """
        ).fetchall()
    }
    names = {column for _, column, _ in columns}

    assert not {
        "input_evidence_ids",
        "input_calculation_ids",
        "exclusion_evidence_ids",
        "filter_ids",
        "qualifiers",
        "support_ids",
    } & names
    assert all(data_type != "ARRAY" for _, _, data_type in columns)


@pytest.mark.postgres
def test_runtime_can_append_a_complete_ledger_on_an_active_dataset(
    connection: psycopg.Connection,
) -> None:
    from tests.db.test_foundation_migration import (
        finish_and_ready_dataset,
        insert_dataset_validation,
    )

    insert_dataset_validation(
        connection,
        dataset_version="ledger-runtime-active",
        validation_run_id="ledger-runtime-validation",
    )
    insert_institution(connection, dataset_version="ledger-runtime-active")
    insert_source(connection, dataset_version="ledger-runtime-active")
    insert_entity(
        connection,
        dataset_version="ledger-runtime-active",
        entity_id="subject-one",
    )
    insert_entity(
        connection,
        dataset_version="ledger-runtime-active",
        entity_id="object-one",
    )
    finish_and_ready_dataset(
        connection,
        dataset_version="ledger-runtime-active",
        validation_run_id="ledger-runtime-validation",
    )
    connection.execute(
        "SELECT operations.activate_dataset('ledger-runtime-active')"
    )
    insert_request_run(
        connection,
        dataset_version="ledger-runtime-active",
    )
    connection.execute("SET LOCAL ROLE fa_runtime")
    insert_evidence(connection, dataset_version="ledger-runtime-active")
    insert_calculation(connection, dataset_version="ledger-runtime-active")
    insert_calculation_evidence_input(
        connection,
        dataset_version="ledger-runtime-active",
    )
    insert_claim(connection, dataset_version="ledger-runtime-active")
    insert_claim_support(
        connection,
        dataset_version="ledger-runtime-active",
    )

    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
