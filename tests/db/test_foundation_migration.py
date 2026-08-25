from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
import time

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from financial_agent.db.preflight import normalize_psycopg_url


REQUIRED_SCHEMAS = {
    "catalog",
    "observation",
    "relation",
    "document",
    "search",
    "evidence",
    "operations",
}

NCP_MANAGED_EXTENSIONS = {
    "vector": "cdb_admin",
    "pg_stat_statements": "cdb_admin",
}

MIGRATION_MANAGED_EXTENSIONS = {
    "pg_trgm": "public",
    "unaccent": "public",
    "pgcrypto": "public",
}

VALID_MANIFEST_HASH = "a" * 64
VALID_REPORT_HASH = "b" * 64
VALID_COMPONENT_HASH = "c" * 64
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as database_connection:
        yield database_connection
        database_connection.rollback()


def insert_dataset_validation(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    validation_run_id: str,
    validation_status: str = "pass",
    manifest_hash: str = VALID_MANIFEST_HASH,
    cutoff_date: str = "2026-08-24",
) -> None:
    started_at = datetime(2026, 8, 18, tzinfo=UTC)
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES (%s, %s, 'building', %s, %s)
        """,
        (dataset_version, cutoff_date, manifest_hash, started_at),
    )
    connection.execute(
        """
        INSERT INTO operations.dataset_validation_run (
            validation_run_id, dataset_version, dataset_manifest_hash,
            validator_id, validator_version, started_at, finished_at,
            status, report_hash
        ) VALUES (%s, %s, %s, 'validator', '1', %s, %s, %s, %s)
        """,
        (
            validation_run_id,
            dataset_version,
            manifest_hash,
            started_at,
            started_at + timedelta(seconds=1),
            validation_status,
            VALID_REPORT_HASH,
        ),
    )


def finish_and_ready_dataset(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    validation_run_id: str,
) -> None:
    connection.execute(
        "SELECT operations.finish_dataset_validation(%s)",
        (validation_run_id,),
    )
    for component in ("postgres", "graph", "vector", "evidence"):
        connection.execute(
            """
            SELECT operations.record_dataset_readiness(
                %s, %s, %s, %s, %s, %s
            )
            """,
            (
                dataset_version,
                component,
                validation_run_id,
                VALID_COMPONENT_HASH,
                datetime(2026, 8, 18, 0, 0, 2, tzinfo=UTC),
                "1",
            ),
        )


@pytest.mark.postgres
def test_foundation_creates_only_its_schemas_and_extensions(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        postgres_major = int(
            connection.execute("SHOW server_version_num").fetchone()[0]
        ) // 10_000
        schemas = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT nspname
                FROM pg_catalog.pg_namespace
                WHERE nspname = ANY(%s)
                """,
                (list(REQUIRED_SCHEMAS),),
            ).fetchall()
        }
        extensions = {
            str(name): str(schema)
            for name, schema in connection.execute(
                """
                SELECT extension.extname, namespace.nspname
                FROM pg_catalog.pg_extension AS extension
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = extension.extnamespace
                WHERE extension.extname = ANY(%s)
                """,
                (
                    list(
                        NCP_MANAGED_EXTENSIONS
                        | MIGRATION_MANAGED_EXTENSIONS
                    ),
                ),
            ).fetchall()
        }

    assert postgres_major == 15
    assert schemas == REQUIRED_SCHEMAS
    assert extensions == {
        **NCP_MANAGED_EXTENSIONS,
        **MIGRATION_MANAGED_EXTENSIONS,
    }


@pytest.mark.postgres
def test_dataset_preserves_legacy_and_current_approved_cutoffs(
    connection: psycopg.Connection,
) -> None:
    created_at = datetime(2026, 8, 25, tzinfo=UTC)
    for suffix, cutoff_date, manifest_hash in (
        ("legacy", "2026-07-11", "1" * 64),
        ("current", "2026-08-24", "2" * 64),
    ):
        connection.execute(
            """
            INSERT INTO operations.dataset_version (
                dataset_version, cutoff_date, status, manifest_hash, created_at
            ) VALUES (%s, %s, 'building', %s, %s)
            """,
            (
                f"dataset-approved-{suffix}",
                cutoff_date,
                manifest_hash,
                created_at,
            ),
        )

    assert connection.execute(
        """
        SELECT dataset_version, cutoff_date::text
        FROM operations.dataset_version
        WHERE dataset_version LIKE 'dataset-approved-%'
        ORDER BY dataset_version
        """
    ).fetchall() == [
        ("dataset-approved-current", "2026-08-24"),
        ("dataset-approved-legacy", "2026-07-11"),
    ]


@pytest.mark.postgres
@pytest.mark.parametrize("cutoff_date", ("2026-07-12", "2026-08-23", "2026-08-25"))
def test_dataset_rejects_a_cutoff_outside_the_approved_set(
    connection: psycopg.Connection,
    cutoff_date: str,
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            """
            INSERT INTO operations.dataset_version (
                dataset_version, cutoff_date, status, manifest_hash, created_at
            ) VALUES (%s, %s, 'building', %s, %s)
            """,
            (
                f"dataset-invalid-cutoff-{cutoff_date}",
                cutoff_date,
                VALID_MANIFEST_HASH,
                datetime(2026, 8, 18, tzinfo=UTC),
            ),
        )


@pytest.mark.postgres
def test_dataset_rejects_a_malformed_manifest_hash(
    connection: psycopg.Connection,
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            """
            INSERT INTO operations.dataset_version (
                dataset_version, cutoff_date, status, manifest_hash, created_at
            ) VALUES (%s, DATE '2026-08-24', 'building', %s, %s)
            """,
            (
                "dataset-invalid-hash",
                "not-a-sha256",
                datetime(2026, 8, 18, tzinfo=UTC),
            ),
        )


@pytest.mark.postgres
def test_readiness_requires_a_successful_matching_validation_run(
    connection: psycopg.Connection,
) -> None:
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES (%s, DATE '2026-08-24', 'building', %s, %s)
        """,
        (
            "dataset-failed-validation",
            VALID_MANIFEST_HASH,
            datetime(2026, 8, 18, tzinfo=UTC),
        ),
    )
    connection.execute(
        """
        INSERT INTO operations.dataset_validation_run (
            validation_run_id, dataset_version, dataset_manifest_hash,
            validator_id, validator_version, started_at, finished_at,
            status, report_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'fail', %s)
        """,
        (
            "validation-failed",
            "dataset-failed-validation",
            VALID_MANIFEST_HASH,
            "validator",
            "1",
            datetime(2026, 8, 18, tzinfo=UTC),
            datetime(2026, 8, 18, 0, 0, 1, tzinfo=UTC),
            VALID_REPORT_HASH,
        ),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        connection.execute(
            """
            INSERT INTO operations.dataset_readiness (
                dataset_version, component, validation_run_id,
                validation_status, dataset_manifest_hash,
                component_manifest_hash, validated_at, validator_version
            ) VALUES (%s, 'postgres', %s, 'pass', %s, %s, %s, '1')
            """,
            (
                "dataset-failed-validation",
                "validation-failed",
                VALID_MANIFEST_HASH,
                VALID_COMPONENT_HASH,
                datetime(2026, 8, 18, 0, 0, 1, tzinfo=UTC),
            ),
        )


@pytest.mark.postgres
def test_request_deadline_and_storage_columns_match_the_runtime_contract(
    connection: psycopg.Connection,
) -> None:
    columns = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'operations' AND table_name = 'request_run'
            """
        ).fetchall()
    }

    assert {
        "execution_outcome",
        "verification_status",
        "answer_disposition",
    } <= columns
    assert "think_trace" not in columns
    assert "chain_of_thought" not in columns

    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES (%s, DATE '2026-08-24', 'building', %s, %s)
        """,
        (
            "dataset-request-deadline",
            VALID_MANIFEST_HASH,
            datetime(2026, 8, 18, tzinfo=UTC),
        ),
    )
    created_at = datetime(2026, 8, 18, tzinfo=UTC)
    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            """
            INSERT INTO operations.request_run (
                run_id, request_key, question_id, question, schema_version,
                dataset_version, cutoff_date, created_at, deadline_at
            ) VALUES (%s, %s, %s, %s, %s, %s, DATE '2026-08-24', %s, %s)
            """,
            (
                "run-too-long",
                "d" * 64,
                "Q-001",
                "question",
                "1.0.0",
                "dataset-request-deadline",
                created_at,
                created_at + timedelta(seconds=56),
            ),
        )


@pytest.mark.postgres
def test_validation_finish_is_the_only_supported_build_transition(
    connection: psycopg.Connection,
) -> None:
    insert_dataset_validation(
        connection,
        dataset_version="dataset-validation-pass",
        validation_run_id="validation-pass",
    )

    status = connection.execute(
        "SELECT operations.finish_dataset_validation(%s)",
        ("validation-pass",),
    ).fetchone()[0]

    assert status == "validated"
    assert connection.execute(
        """
        SELECT status FROM operations.dataset_version
        WHERE dataset_version = %s
        """,
        ("dataset-validation-pass",),
    ).fetchone()[0] == "validated"
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(
            """
            UPDATE operations.dataset_validation_run
            SET report_hash = %s
            WHERE validation_run_id = %s
            """,
            ("e" * 64, "validation-pass"),
        )


@pytest.mark.postgres
def test_failed_validation_moves_the_dataset_to_a_terminal_failure(
    connection: psycopg.Connection,
) -> None:
    insert_dataset_validation(
        connection,
        dataset_version="dataset-validation-fail",
        validation_run_id="validation-fail",
        validation_status="fail",
    )

    status = connection.execute(
        "SELECT operations.finish_dataset_validation(%s)",
        ("validation-fail",),
    ).fetchone()[0]

    assert status == "failed"
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(
            """
            UPDATE operations.dataset_version
            SET status = 'building'
            WHERE dataset_version = %s
            """,
            ("dataset-validation-fail",),
        )


@pytest.mark.postgres
def test_activation_requires_all_four_readiness_components(
    connection: psycopg.Connection,
) -> None:
    insert_dataset_validation(
        connection,
        dataset_version="dataset-incomplete-readiness",
        validation_run_id="validation-incomplete-readiness",
    )
    connection.execute(
        "SELECT operations.finish_dataset_validation(%s)",
        ("validation-incomplete-readiness",),
    )
    connection.execute(
        """
        SELECT operations.record_dataset_readiness(
            %s, 'postgres', %s, %s, %s, '1'
        )
        """,
        (
            "dataset-incomplete-readiness",
            "validation-incomplete-readiness",
            VALID_COMPONENT_HASH,
            datetime(2026, 8, 18, 0, 0, 2, tzinfo=UTC),
        ),
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "SELECT operations.activate_dataset(%s)",
            ("dataset-incomplete-readiness",),
        )


@pytest.mark.postgres
def test_legacy_dataset_can_be_validated_but_cannot_be_activated(
    connection: psycopg.Connection,
) -> None:
    insert_dataset_validation(
        connection,
        dataset_version="dataset-legacy-preserved",
        validation_run_id="validation-legacy-preserved",
        cutoff_date="2026-07-11",
    )
    finish_and_ready_dataset(
        connection,
        dataset_version="dataset-legacy-preserved",
        validation_run_id="validation-legacy-preserved",
    )

    with pytest.raises(
        psycopg.errors.CheckViolation,
        match="LEGACY_DATASET_CANNOT_ACTIVATE",
    ):
        with connection.transaction():
            connection.execute(
                "SELECT operations.activate_dataset(%s)",
                ("dataset-legacy-preserved",),
            )

    assert connection.execute(
        """
        SELECT status FROM operations.dataset_version
        WHERE dataset_version = 'dataset-legacy-preserved'
        """
    ).fetchone()[0] == "validated"


@pytest.mark.postgres
def test_second_activation_retires_the_previous_dataset_atomically(
    connection: psycopg.Connection,
) -> None:
    insert_dataset_validation(
        connection,
        dataset_version="dataset-active-first",
        validation_run_id="validation-active-first",
    )
    finish_and_ready_dataset(
        connection,
        dataset_version="dataset-active-first",
        validation_run_id="validation-active-first",
    )
    assert connection.execute(
        "SELECT operations.activate_dataset(%s)",
        ("dataset-active-first",),
    ).fetchone()[0] == "dataset-active-first"

    insert_dataset_validation(
        connection,
        dataset_version="dataset-active-second",
        validation_run_id="validation-active-second",
    )
    finish_and_ready_dataset(
        connection,
        dataset_version="dataset-active-second",
        validation_run_id="validation-active-second",
    )
    assert connection.execute(
        "SELECT operations.activate_dataset(%s)",
        ("dataset-active-second",),
    ).fetchone()[0] == "dataset-active-second"

    states = dict(
        connection.execute(
            """
            SELECT dataset_version, status
            FROM operations.dataset_version
            WHERE dataset_version IN (%s, %s)
            """,
            ("dataset-active-first", "dataset-active-second"),
        ).fetchall()
    )
    pointer = connection.execute(
        """
        SELECT dataset_version FROM operations.active_dataset
        WHERE singleton
        """
    ).fetchone()[0]

    assert states == {
        "dataset-active-first": "retired",
        "dataset-active-second": "active",
    }
    assert pointer == "dataset-active-second"


@pytest.mark.postgres
def test_start_request_is_idempotent_and_rejects_conflicting_run_reuse(
    connection: psycopg.Connection,
) -> None:
    insert_dataset_validation(
        connection,
        dataset_version="dataset-request-active",
        validation_run_id="validation-request-active",
    )
    finish_and_ready_dataset(
        connection,
        dataset_version="dataset-request-active",
        validation_run_id="validation-request-active",
    )
    connection.execute(
        "SELECT operations.activate_dataset(%s)",
        ("dataset-request-active",),
    )
    created_at = datetime(2026, 8, 18, tzinfo=UTC)
    parameters = (
        "run-idempotent",
        "f" * 64,
        "Q-001",
        "question",
        "1.0.0",
        "dataset-request-active",
        "2026-08-24",
        created_at,
        created_at + timedelta(seconds=55),
    )
    statement = """
        SELECT (operations.start_request_run(
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        )).run_id
    """

    assert connection.execute(statement, parameters).fetchone()[0] == "run-idempotent"
    assert connection.execute(statement, parameters).fetchone()[0] == "run-idempotent"
    assert connection.execute(
        "SELECT count(*) FROM operations.request_run WHERE run_id = %s",
        ("run-idempotent",),
    ).fetchone()[0] == 1

    separate_attempt = ("run-second-attempt", *parameters[1:])
    assert connection.execute(statement, separate_attempt).fetchone()[0] == (
        "run-second-attempt"
    )
    assert connection.execute(
        "SELECT count(*) FROM operations.request_run WHERE request_key = %s",
        ("f" * 64,),
    ).fetchone()[0] == 2

    conflicting_values = {
        1: "0" * 64,
        2: "Q-002",
        3: "different question",
        4: "2.0.0",
        5: "different-dataset",
        6: "2026-07-10",
        7: created_at + timedelta(seconds=1),
        8: created_at + timedelta(seconds=54),
    }
    for index, conflicting_value in conflicting_values.items():
        conflicting_parameters = list(parameters)
        conflicting_parameters[index] = conflicting_value
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="REQUEST_RUN_CONFLICT",
        ):
            with connection.transaction():
                connection.execute(statement, conflicting_parameters)


def _prepare_active_request_dataset(database_url: str) -> None:
    with psycopg.connect(database_url) as setup_connection:
        insert_dataset_validation(
            setup_connection,
            dataset_version="dataset-request-concurrent",
            validation_run_id="validation-request-concurrent",
        )
        finish_and_ready_dataset(
            setup_connection,
            dataset_version="dataset-request-concurrent",
            validation_run_id="validation-request-concurrent",
        )
        setup_connection.execute(
            "SELECT operations.activate_dataset(%s)",
            ("dataset-request-concurrent",),
        )


def _concurrent_request_parameters(question: str) -> tuple[object, ...]:
    created_at = datetime(2026, 8, 18, tzinfo=UTC)
    return (
        "run-concurrent",
        "e" * 64,
        "Q-concurrent",
        question,
        "1.0.0",
        "dataset-request-concurrent",
        "2026-08-24",
        created_at,
        created_at + timedelta(seconds=55),
    )


@pytest.mark.postgres
def test_concurrent_identical_request_starts_converge_on_one_row(
    migrated_database_url: str,
) -> None:
    normalized_url = normalize_psycopg_url(migrated_database_url)
    _truncate_foundation_tables(normalized_url)
    try:
        _prepare_active_request_dataset(normalized_url)
        barrier = Barrier(2)
        parameters = _concurrent_request_parameters("same question")

        def start_request() -> str:
            with psycopg.connect(normalized_url) as request_connection:
                barrier.wait()
                return str(
                    request_connection.execute(
                        """
                        SELECT (operations.start_request_run(
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )).run_id
                        """,
                        parameters,
                    ).fetchone()[0]
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: start_request(), range(2)))

        with psycopg.connect(normalized_url) as verification_connection:
            count = verification_connection.execute(
                "SELECT count(*) FROM operations.request_run "
                "WHERE run_id = 'run-concurrent'"
            ).fetchone()[0]
        assert results == ["run-concurrent", "run-concurrent"]
        assert count == 1
    finally:
        _truncate_foundation_tables(normalized_url)


@pytest.mark.postgres
def test_concurrent_conflicting_request_starts_keep_only_one_payload(
    migrated_database_url: str,
) -> None:
    normalized_url = normalize_psycopg_url(migrated_database_url)
    _truncate_foundation_tables(normalized_url)
    try:
        _prepare_active_request_dataset(normalized_url)
        barrier = Barrier(2)
        questions = ("first question", "different question")

        def start_request(question: str) -> str:
            with psycopg.connect(normalized_url) as request_connection:
                barrier.wait()
                try:
                    request_connection.execute(
                        """
                        SELECT (operations.start_request_run(
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )).run_id
                        """,
                        _concurrent_request_parameters(question),
                    )
                except psycopg.errors.RaiseException as error:
                    return str(error.diag.message_primary)
                return "inserted"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = set(executor.map(start_request, questions))

        with psycopg.connect(normalized_url) as verification_connection:
            stored_questions = verification_connection.execute(
                "SELECT question FROM operations.request_run "
                "WHERE run_id = 'run-concurrent'"
            ).fetchall()
        assert results == {"inserted", "REQUEST_RUN_CONFLICT"}
        assert stored_questions in [
            [("first question",)],
            [("different question",)],
        ]
    finally:
        _truncate_foundation_tables(normalized_url)


@pytest.mark.postgres
@pytest.mark.parametrize("offset_seconds", (0, -1))
def test_request_deadline_must_be_after_creation(
    connection: psycopg.Connection,
    offset_seconds: int,
) -> None:
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES (%s, DATE '2026-08-24', 'building', %s, %s)
        """,
        (
            f"dataset-deadline-order-{offset_seconds}",
            VALID_MANIFEST_HASH,
            datetime(2026, 8, 18, tzinfo=UTC),
        ),
    )
    created_at = datetime(2026, 8, 18, tzinfo=UTC)

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            """
            INSERT INTO operations.request_run (
                run_id, request_key, question_id, question, schema_version,
                dataset_version, cutoff_date, created_at, deadline_at
            ) VALUES (%s, %s, 'Q', 'question', '1', %s,
                      DATE '2026-08-24', %s, %s)
            """,
            (
                f"run-deadline-order-{offset_seconds}",
                "1" * 64,
                f"dataset-deadline-order-{offset_seconds}",
                created_at,
                created_at + timedelta(seconds=offset_seconds),
            ),
        )


@pytest.mark.postgres
def test_failed_execution_cannot_store_an_answer_disposition(
    connection: psycopg.Connection,
) -> None:
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES ('dataset-failed-run', DATE '2026-08-24', 'building', %s, %s)
        """,
        (VALID_MANIFEST_HASH, datetime(2026, 8, 18, tzinfo=UTC)),
    )
    created_at = datetime(2026, 8, 18, tzinfo=UTC)

    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            """
            INSERT INTO operations.request_run (
                run_id, request_key, question_id, question, schema_version,
                dataset_version, cutoff_date, created_at, deadline_at,
                execution_outcome, answer_disposition
            ) VALUES (
                'run-failed-with-answer', %s, 'Q', 'question', '1',
                'dataset-failed-run', DATE '2026-08-24', %s, %s,
                'failed', 'answer'
            )
            """,
            ("2" * 64, created_at, created_at + timedelta(seconds=55)),
        )


@pytest.mark.postgres
def test_failure_events_preserve_every_attempt_and_are_immutable(
    connection: psycopg.Connection,
) -> None:
    created_at = datetime(2026, 8, 18, tzinfo=UTC)
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES ('dataset-failure-events', DATE '2026-08-24', 'building', %s, %s)
        """,
        (VALID_MANIFEST_HASH, created_at),
    )
    connection.execute(
        """
        INSERT INTO operations.request_run (
            run_id, request_key, question_id, question, schema_version,
            dataset_version, cutoff_date, created_at, deadline_at
        ) VALUES (
            'run-failure-events', %s, 'Q', 'question', '1',
            'dataset-failure-events', DATE '2026-08-24', %s, %s
        )
        """,
        ("3" * 64, created_at, created_at + timedelta(seconds=55)),
    )
    for attempt, remaining_budget in ((1, 40_000), (2, 35_000)):
        connection.execute(
            """
            INSERT INTO operations.failure_event (
                event_id, run_id, task_id, stage, code, category,
                retryable, attempt, remaining_budget_ms, duration_ms,
                dependency, occurred_at
            ) VALUES (%s, 'run-failure-events', 'task-1', 'retrieval',
                      'UPSTREAM_TIMEOUT', 'transient', true, %s, %s, 1000,
                      'official-api', %s)
            """,
            (
                f"event-{attempt}",
                attempt,
                remaining_budget,
                created_at + timedelta(seconds=attempt),
            ),
        )

    assert connection.execute(
        """
        SELECT attempt, remaining_budget_ms
        FROM operations.failure_event
        WHERE run_id = 'run-failure-events'
        ORDER BY attempt
        """
    ).fetchall() == [(1, 40_000), (2, 35_000)]
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        connection.execute(
            """
            UPDATE operations.failure_event
            SET remaining_budget_ms = 0
            WHERE event_id = 'event-1'
            """
        )


def _truncate_foundation_tables(database_url: str) -> None:
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        connection.execute(
            """
            TRUNCATE TABLE
                operations.artifact_evidence_ref,
                operations.artifact_calculation_ref,
                operations.artifact_claim_ref,
                operations.request_artifact,
                evidence.claim_support,
                evidence.claim_qualifier,
                evidence.atomic_claim,
                evidence.calculation_population_filter,
                evidence.calculation_population,
                evidence.calculation_exclusion,
                evidence.calculation_dependency,
                evidence.calculation_evidence_input,
                evidence.calculation_parameter,
                evidence.calculation_record,
                evidence.evidence_document_origin,
                evidence.evidence_relation_origin,
                evidence.evidence_observation_origin,
                evidence.evidence_record,
                search.document_embedding,
                search.embedding_model,
                document.document_chunk,
                document.document_record,
                observation.observation_record,
                observation.metric_definition,
                relation.relation_record,
                evidence.source_record,
                catalog.alias,
                catalog.identifier,
                catalog.product,
                catalog.security,
                catalog.institution,
                catalog.entity,
                operations.failure_event,
                operations.request_subtask,
                operations.request_run,
                operations.active_dataset,
                operations.dataset_readiness,
                operations.dataset_validation_run,
                operations.dataset_version
            """
        )
        connection.execute(
            "INSERT INTO operations.active_dataset (singleton) VALUES (true)"
        )


@pytest.mark.postgres
def test_concurrent_first_activations_leave_one_matching_active_pointer(
    migrated_database_url: str,
) -> None:
    normalized_url = normalize_psycopg_url(migrated_database_url)
    _truncate_foundation_tables(normalized_url)
    versions = ("dataset-concurrent-a", "dataset-concurrent-b")
    try:
        with psycopg.connect(normalized_url) as setup_connection:
            for suffix, dataset_version in zip(("a", "b"), versions, strict=True):
                validation_run_id = f"validation-concurrent-{suffix}"
                insert_dataset_validation(
                    setup_connection,
                    dataset_version=dataset_version,
                    validation_run_id=validation_run_id,
                )
                finish_and_ready_dataset(
                    setup_connection,
                    dataset_version=dataset_version,
                    validation_run_id=validation_run_id,
                )

        barrier = Barrier(2)

        def activate(dataset_version: str) -> str:
            with psycopg.connect(normalized_url) as activation_connection:
                barrier.wait()
                return str(
                    activation_connection.execute(
                        "SELECT operations.activate_dataset(%s)",
                        (dataset_version,),
                    ).fetchone()[0]
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = set(executor.map(activate, versions))

        with psycopg.connect(normalized_url) as verification_connection:
            states = dict(
                verification_connection.execute(
                    """
                    SELECT dataset_version, status
                    FROM operations.dataset_version
                    WHERE dataset_version = ANY(%s)
                    """,
                    (list(versions),),
                ).fetchall()
            )
            pointer = verification_connection.execute(
                """
                SELECT dataset_version FROM operations.active_dataset
                WHERE singleton
                """
            ).fetchone()[0]

        assert results == set(versions)
        assert list(states.values()).count("active") == 1
        assert list(states.values()).count("retired") == 1
        assert states[str(pointer)] == "active"
    finally:
        _truncate_foundation_tables(normalized_url)


@pytest.mark.postgres
def test_validation_insert_serializes_with_dataset_finish(
    migrated_database_url: str,
) -> None:
    normalized_url = normalize_psycopg_url(migrated_database_url)
    _truncate_foundation_tables(normalized_url)
    try:
        with psycopg.connect(normalized_url) as setup_connection:
            insert_dataset_validation(
                setup_connection,
                dataset_version="dataset-validation-race",
                validation_run_id="validation-race-finish",
            )

        with psycopg.connect(normalized_url) as insert_connection:
            started_at = datetime(2026, 8, 18, tzinfo=UTC)
            insert_connection.execute(
                """
                INSERT INTO operations.dataset_validation_run (
                    validation_run_id, dataset_version, dataset_manifest_hash,
                    validator_id, validator_version, started_at, finished_at,
                    status, report_hash
                ) VALUES (
                    'validation-race-insert', 'dataset-validation-race', %s,
                    'validator', '1', %s, %s, 'pass', %s
                )
                """,
                (
                    VALID_MANIFEST_HASH,
                    started_at,
                    started_at + timedelta(seconds=1),
                    VALID_REPORT_HASH,
                ),
            )
            with psycopg.connect(normalized_url) as transition_connection:
                transition_connection.execute("SET LOCAL lock_timeout = '200ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    transition_connection.execute(
                        """
                        UPDATE operations.dataset_version
                        SET status = 'validated'
                        WHERE dataset_version = 'dataset-validation-race'
                        """
                    )
            insert_connection.rollback()
    finally:
        _truncate_foundation_tables(normalized_url)


@pytest.mark.postgres
def test_readiness_uses_validation_before_dataset_lock_order(
    migrated_database_url: str,
) -> None:
    normalized_url = normalize_psycopg_url(migrated_database_url)
    _truncate_foundation_tables(normalized_url)
    try:
        with psycopg.connect(normalized_url) as setup_connection:
            insert_dataset_validation(
                setup_connection,
                dataset_version="dataset-readiness-lock-order",
                validation_run_id="validation-readiness-lock-order",
            )

        with psycopg.connect(normalized_url) as dataset_blocker:
            dataset_blocker.execute(
                """
                SELECT 1 FROM operations.dataset_version
                WHERE dataset_version = 'dataset-readiness-lock-order'
                FOR UPDATE
                """
            )

            def record_readiness() -> None:
                with psycopg.connect(
                    normalized_url,
                    application_name="readiness-lock-order-test",
                ) as readiness_connection:
                    readiness_connection.execute(
                        """
                        SELECT operations.record_dataset_readiness(
                            'dataset-readiness-lock-order', 'postgres',
                            'validation-readiness-lock-order', %s, %s, '1'
                        )
                        """,
                        (
                            VALID_COMPONENT_HASH,
                            datetime(2026, 8, 18, 0, 0, 2, tzinfo=UTC),
                        ),
                    )

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(record_readiness)
                with psycopg.connect(normalized_url) as observer:
                    for _ in range(50):
                        wait_type = observer.execute(
                            """
                            SELECT wait_event_type
                            FROM pg_catalog.pg_stat_activity
                            WHERE application_name = 'readiness-lock-order-test'
                            """
                        ).fetchone()
                        if wait_type is not None and wait_type[0] == "Lock":
                            break
                        time.sleep(0.02)
                    else:
                        pytest.fail("readiness call did not reach its dataset lock")

                validation_lock_observed = False
                with psycopg.connect(
                    normalized_url,
                    autocommit=True,
                ) as validation_probe:
                    try:
                        validation_probe.execute(
                            """
                            SELECT 1 FROM operations.dataset_validation_run
                            WHERE validation_run_id =
                                  'validation-readiness-lock-order'
                            FOR UPDATE NOWAIT
                            """
                        )
                    except psycopg.errors.LockNotAvailable:
                        validation_lock_observed = True
                dataset_blocker.rollback()
                future.result(timeout=2)
                assert validation_lock_observed is True
    finally:
        _truncate_foundation_tables(normalized_url)


@pytest.mark.postgres
def test_alembic_ignores_nonowned_public_objects(
    migrated_database_url: str,
) -> None:
    normalized_url = normalize_psycopg_url(migrated_database_url)
    with psycopg.connect(normalized_url, autocommit=True) as connection:
        connection.execute(
            "CREATE TABLE public.external_object_probe (id integer PRIMARY KEY)"
        )
    try:
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", migrated_database_url)
        command.check(config)
    finally:
        with psycopg.connect(normalized_url, autocommit=True) as connection:
            connection.execute("DROP TABLE public.external_object_probe")
