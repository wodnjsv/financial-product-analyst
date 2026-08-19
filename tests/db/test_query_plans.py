from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from time import perf_counter

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from financial_agent.db.preflight import normalize_psycopg_url


SCALE_DATASET_VERSION = "task8-scale-synthetic"
TARGET_ENTITY_ID = "entity-004242"
TARGET_ALIAS = "rare synthetic alias 004242"
TARGET_EVIDENCE_ID = "evidence-004242"
TARGET_CONTRACT_ID = "task-004242"
TARGET_PAYLOAD_HASH = "0" * 60 + "4242"
LARGE_TABLES = {
    "alias",
    "relation_record",
    "observation_record",
    "evidence_record",
    "claim_support",
    "request_artifact",
}


def _require_local_scale_run() -> None:
    if os.environ.get("RUN_DB_SCALE_TESTS") != "1":
        pytest.skip("set RUN_DB_SCALE_TESTS=1 to run synthetic scale tests")
    if os.environ.get("FINANCIAL_AGENT_NCP_TEST_DATABASE_URL"):
        pytest.skip("local plan-shape test does not write to the NCP database")
    database_url = os.environ.get("FINANCIAL_AGENT_TEST_DATABASE_URL")
    if database_url:
        parsed = make_url(normalize_psycopg_url(database_url))
        if parsed.host not in {"127.0.0.1", "localhost", "::1"}:
            pytest.fail("local scale tests refuse a non-loopback database")
        if parsed.database != "financial_agent_test":
            pytest.fail("local scale tests require the disposable test database")


def _load_synthetic_scale_data(connection: psycopg.Connection) -> None:
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES (
            %s, DATE '2026-07-11', 'building', repeat('a', 64),
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        )
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO catalog.entity (
            dataset_version, entity_id, entity_type, canonical_name,
            normalized_name, record_hash, created_at
        )
        SELECT
            %s,
            'entity-' || lpad(series::text, 6, '0'),
            'security',
            'Synthetic Entity ' || series,
            'synthetic entity ' || series,
            md5(series::text) || md5(series::text),
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        FROM generate_series(1, 100000) AS series
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO catalog.alias (
            dataset_version, alias_id, entity_id, alias_text,
            normalized_alias_text, valid_from, valid_to, record_hash,
            created_at
        )
        SELECT
            %s,
            'alias-' || lpad(series::text, 6, '0'),
            'entity-' || lpad(series::text, 6, '0'),
            CASE WHEN series = 4242 THEN %s ELSE 'Alias ' || series END,
            CASE WHEN series = 4242 THEN %s ELSE 'alias ' || series END,
            NULL,
            NULL,
            md5(('alias-' || series)::text) || md5(('alias-' || series)::text),
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        FROM generate_series(1, 100000) AS series
        """,
        (SCALE_DATASET_VERSION, TARGET_ALIAS, TARGET_ALIAS),
    )
    connection.execute(
        """
        INSERT INTO relation.relation_record (
            dataset_version, relation_id, subject_id, predicate_id, object_id,
            valid_from, valid_to, record_hash, created_at
        )
        SELECT
            %s,
            'relation-' || lpad(series::text, 6, '0'),
            'entity-' || lpad((((series - 1) %% 100000) + 1)::text, 6, '0'),
            'etf_constituent',
            'entity-' || lpad(((series %% 100000) + 1)::text, 6, '0'),
            NULL,
            NULL,
            md5(('relation-' || series)::text)
                || md5(('relation-' || series)::text),
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        FROM generate_series(1, 250000) AS series
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO observation.metric_definition (
            metric_id, definition_version, semantic_family, value_kind,
            default_unit, description, definition_hash, approved_at
        ) VALUES (
            'market_value', '1', 'market_value', 'numeric', 'KRW',
            'Synthetic plan-shape metric', repeat('b', 64),
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        ) ON CONFLICT DO NOTHING
        """
    )
    connection.execute(
        """
        INSERT INTO observation.observation_record (
            dataset_version, observation_id, entity_id, relation_id,
            metric_id, metric_definition_version, value_status,
            numeric_value, text_value, boolean_value, date_value,
            timestamp_value, unit, currency, period_start, period_end,
            applicable_date, published_at, available_at, vintage_date,
            reason_code, record_hash, created_at
        )
        SELECT
            %s,
            'observation-' || lpad(series::text, 6, '0'),
            'entity-' || lpad((((series - 1) %% 100000) + 1)::text, 6, '0'),
            NULL,
            'market_value',
            '1',
            'present',
            series::numeric,
            NULL,
            NULL,
            NULL,
            NULL,
            'KRW',
            'KRW',
            NULL,
            NULL,
            DATE '2025-01-01' + (series %% 365)::integer,
            NULL,
            NULL,
            NULL,
            NULL,
            md5(('observation-' || series)::text)
                || md5(('observation-' || series)::text),
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        FROM generate_series(1, 250000) AS series
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO catalog.entity (
            dataset_version, entity_id, entity_type, canonical_name,
            normalized_name, record_hash, created_at
        ) VALUES (
            %s, 'publisher-1', 'institution', 'Synthetic Publisher',
            'synthetic publisher', repeat('c', 64),
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        )
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO catalog.institution (
            dataset_version, entity_id, institution_kind
        ) VALUES (%s, 'publisher-1', 'synthetic')
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO evidence.source_record (
            dataset_version, source_id, publisher, publisher_type,
            source_title, source_type, authority_tier, source_locator_root,
            content_checksum, license_or_usage_note, eligible_for_claim,
            record_hash, created_at
        ) VALUES (
            %s, 'source-1', 'publisher-1', 'institution',
            'Synthetic source', 'synthetic', 'test', 'synthetic://task8',
            repeat('d', 64), NULL, true, repeat('e', 64),
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        )
        """,
        (SCALE_DATASET_VERSION,),
    )
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
        )
        SELECT
            %s,
            'evidence-' || lpad(series::text, 6, '0'),
            'query_scope',
            'source-1',
            NULL,
            'scope',
            jsonb_build_object('type', 'string', 'value', series::text),
            jsonb_build_object('type', 'string', 'value', series::text),
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            'synthetic',
            'synthetic://task8/' || series,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            '1',
            '1',
            'eligible',
            md5(('evidence-' || series)::text)
                || md5(('evidence-' || series)::text),
            'closed_world',
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        FROM generate_series(1, 20000) AS series
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO operations.request_run (
            run_id, request_key, question_id, question, schema_version,
            dataset_version, cutoff_date, created_at, deadline_at
        ) VALUES (
            'run-scale', repeat('f', 64), 'Q-SCALE', 'synthetic scale', '1.0.0',
            %s, DATE '2026-07-11',
            TIMESTAMPTZ '2026-08-19 00:00:00+00',
            TIMESTAMPTZ '2026-08-19 00:00:55+00'
        )
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO operations.request_subtask (
            run_id, subtask_id, importance, created_at
        ) VALUES (
            'run-scale', 'subtask-scale', 'critical',
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO evidence.atomic_claim (
            run_id, dataset_version, claim_id, claim_type, subtask_id,
            subject_id, subject_kind, subject_entity_id, request_subject_id,
            predicate_id, object_id, value, unit, currency, display_policy_id,
            claim_hash, created_at
        )
        SELECT
            'run-scale',
            %s,
            'claim-' || lpad(series::text, 6, '0'),
            'direct_fact',
            'subtask-scale',
            'entity-' || lpad((((series - 1) %% 100000) + 1)::text, 6, '0'),
            'entity',
            'entity-' || lpad((((series - 1) %% 100000) + 1)::text, 6, '0'),
            NULL,
            'synthetic_fact',
            NULL,
            jsonb_build_object('type', 'string', 'value', series::text),
            NULL,
            NULL,
            'default',
            md5(('claim-' || series)::text) || md5(('claim-' || series)::text),
            TIMESTAMPTZ '2026-08-19 00:00:00+00'
        FROM generate_series(1, 20000) AS series
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO evidence.claim_support (
            run_id, dataset_version, claim_id, support_kind, evidence_id,
            calculation_id, support_role, ordinal
        )
        SELECT
            'run-scale',
            %s,
            'claim-' || lpad(series::text, 6, '0'),
            'direct',
            'evidence-' || lpad(series::text, 6, '0'),
            NULL,
            'primary',
            0
        FROM generate_series(1, 20000) AS series
        """,
        (SCALE_DATASET_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO operations.request_artifact (
            artifact_record_id, contract_object_id, artifact_type,
            schema_version, request_key, run_id, dataset_version, cutoff_date,
            producer, model_id, prompt_version, created_at, canonical_payload,
            payload_jsonb, payload_hash
        )
        SELECT
            md5(('artifact-' || series)::text)::uuid,
            'task-' || lpad(series::text, 6, '0'),
            'tool_result',
            '1.0.0',
            repeat('f', 64),
            'run-scale',
            %s,
            DATE '2026-07-11',
            'synthetic-scale',
            NULL,
            NULL,
            TIMESTAMPTZ '2026-08-19 00:00:00+00',
            '{}'::text,
            '{}'::jsonb,
            CASE
                WHEN series = 4242 THEN %s
                ELSE md5(('payload-' || series)::text)
                    || md5(('payload-' || series)::text)
            END
        FROM generate_series(1, 20000) AS series
        """,
        (SCALE_DATASET_VERSION, TARGET_PAYLOAD_HASH),
    )
    for table in (
        "catalog.alias",
        "relation.relation_record",
        "observation.observation_record",
        "evidence.evidence_record",
        "evidence.claim_support",
        "operations.request_artifact",
    ):
        connection.execute(f"ANALYZE {table}")


@pytest.fixture(scope="module")
def scale_enabled() -> None:
    _require_local_scale_run()


@pytest.fixture(scope="module")
def scale_connection(
    scale_enabled: None,
    migrated_database_url: str,
) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        _load_synthetic_scale_data(connection)
        yield connection
        connection.rollback()


def _plan_nodes(plan: dict[str, object]) -> Iterator[dict[str, object]]:
    yield plan
    for child in plan.get("Plans", []):
        yield from _plan_nodes(child)


def _explain(
    connection: psycopg.Connection,
    statement: str,
    parameters: tuple[object, ...],
) -> dict[str, object]:
    payload = connection.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
        parameters,
    ).fetchone()[0][0]
    return payload


def _assert_plan_shape(
    report: dict[str, object],
    *,
    expected_indexes: set[str],
    protected_tables: set[str],
) -> None:
    nodes = tuple(_plan_nodes(report["Plan"]))
    indexes = {
        str(node["Index Name"])
        for node in nodes
        if node.get("Index Name") is not None
    }
    sequential_scans = {
        str(node.get("Relation Name"))
        for node in nodes
        if node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") in protected_tables
    }
    assert expected_indexes <= indexes
    assert sequential_scans == set()
    rows_examined = sum(int(node.get("Actual Rows", 0)) for node in nodes)
    print(
        json.dumps(
            {
                "indexes": sorted(indexes),
                "rows_examined": rows_examined,
                "planning_ms": report["Planning Time"],
                "execution_ms": report["Execution Time"],
            },
            sort_keys=True,
        )
    )


@pytest.mark.postgres
@pytest.mark.performance
@pytest.mark.skipif(
    os.environ.get("RUN_DB_SCALE_TESTS") != "1"
    or bool(os.environ.get("FINANCIAL_AGENT_NCP_TEST_DATABASE_URL")),
    reason=(
        "set RUN_DB_SCALE_TESTS=1 for local scale tests; "
        "the local suite never writes to NCP"
    ),
)
def test_synthetic_scale_queries_use_the_reviewed_indexes(
    scale_connection: psycopg.Connection,
) -> None:
    plans = (
        (
            _explain(
                scale_connection,
                """
                SELECT entity_id
                FROM catalog.alias
                WHERE normalized_alias_text %% %s
                ORDER BY similarity(normalized_alias_text, %s) DESC
                LIMIT 10
                """,
                (TARGET_ALIAS, TARGET_ALIAS),
            ),
            {"ix_alias_normalized_alias_text_trgm"},
            {"alias"},
        ),
        (
            _explain(
                scale_connection,
                """
                SELECT object_id
                FROM relation.relation_record
                WHERE dataset_version = %s
                  AND predicate_id = 'etf_constituent'
                  AND subject_id = %s
                """,
                (SCALE_DATASET_VERSION, TARGET_ENTITY_ID),
            ),
            {"ix_relation_record_lookup"},
            {"relation_record"},
        ),
        (
            _explain(
                scale_connection,
                """
                SELECT numeric_value, applicable_date
                FROM observation.observation_record
                WHERE dataset_version = %s
                  AND entity_id = %s
                  AND metric_id = 'market_value'
                ORDER BY applicable_date DESC
                LIMIT 1
                """,
                (SCALE_DATASET_VERSION, TARGET_ENTITY_ID),
            ),
            {"ix_observation_record_entity_metric_date"},
            {"observation_record"},
        ),
        (
            _explain(
                scale_connection,
                """
                SELECT claim.claim_id
                FROM evidence.evidence_record AS evidence_row
                JOIN evidence.claim_support AS support
                  ON support.dataset_version = evidence_row.dataset_version
                 AND support.evidence_id = evidence_row.evidence_id
                JOIN evidence.atomic_claim AS claim
                  ON claim.run_id = support.run_id
                 AND claim.claim_id = support.claim_id
                WHERE evidence_row.dataset_version = %s
                  AND evidence_row.evidence_id = %s
                """,
                (SCALE_DATASET_VERSION, TARGET_EVIDENCE_ID),
            ),
            {"pk_evidence_record", "ix_claim_support_evidence", "pk_atomic_claim"},
            {"evidence_record", "claim_support", "atomic_claim"},
        ),
        (
            _explain(
                scale_connection,
                """
                SELECT artifact_record_id
                FROM operations.request_artifact
                WHERE run_id = 'run-scale'
                  AND artifact_type = 'tool_result'
                  AND contract_object_id = %s
                """,
                (TARGET_CONTRACT_ID,),
            ),
            {"uq_request_artifact_contract_object"},
            {"request_artifact"},
        ),
        (
            _explain(
                scale_connection,
                """
                SELECT artifact_record_id
                FROM operations.request_artifact
                WHERE run_id = 'run-scale'
                  AND artifact_type = 'tool_result'
                  AND payload_hash = %s
                """,
                (TARGET_PAYLOAD_HASH,),
            ),
            {"uq_request_artifact_retry"},
            {"request_artifact"},
        ),
    )
    for report, expected_indexes, protected_tables in plans:
        _assert_plan_shape(
            report,
            expected_indexes=expected_indexes,
            protected_tables=protected_tables & LARGE_TABLES,
        )


def _percentile_95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


@pytest.mark.performance
@pytest.mark.ncp_integration
@pytest.mark.skipif(
    os.environ.get("RUN_DB_SCALE_TESTS") != "1"
    or not os.environ.get("FINANCIAL_AGENT_NCP_TEST_DATABASE_URL"),
    reason="authorized NCP scale benchmark is not configured",
)
def test_authorized_ncp_scale_p95_and_four_read_concurrency(
    ncp_database_url: str,
) -> None:
    normalized_url = normalize_psycopg_url(ncp_database_url)
    with psycopg.connect(normalized_url) as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM catalog.alias
                  WHERE dataset_version = %s),
                (SELECT count(*) FROM relation.relation_record
                  WHERE dataset_version = %s),
                (SELECT count(*) FROM observation.observation_record
                  WHERE dataset_version = %s)
            """,
            (
                SCALE_DATASET_VERSION,
                SCALE_DATASET_VERSION,
                SCALE_DATASET_VERSION,
            ),
        ).fetchone()
        assert counts[0] >= 100000
        assert counts[1] >= 250000
        assert counts[2] >= 250000
        benchmark_queries = (
            (
                """
                SELECT entity_id FROM catalog.alias
                WHERE normalized_alias_text %% %s
                ORDER BY similarity(normalized_alias_text, %s) DESC
                LIMIT 10
                """,
                (TARGET_ALIAS, TARGET_ALIAS),
            ),
            (
                """
                SELECT object_id FROM relation.relation_record
                WHERE dataset_version = %s
                  AND predicate_id = 'etf_constituent'
                  AND subject_id = %s
                """,
                (SCALE_DATASET_VERSION, TARGET_ENTITY_ID),
            ),
            (
                """
                SELECT numeric_value FROM observation.observation_record
                WHERE dataset_version = %s
                  AND entity_id = %s
                  AND metric_id = 'market_value'
                ORDER BY applicable_date DESC
                LIMIT 1
                """,
                (SCALE_DATASET_VERSION, TARGET_ENTITY_ID),
            ),
            (
                """
                SELECT claim_id FROM evidence.claim_support
                WHERE dataset_version = %s AND evidence_id = %s
                """,
                (SCALE_DATASET_VERSION, TARGET_EVIDENCE_ID),
            ),
            (
                """
                SELECT artifact_record_id FROM operations.request_artifact
                WHERE run_id = 'run-scale'
                  AND artifact_type = 'tool_result'
                  AND contract_object_id = %s
                """,
                (TARGET_CONTRACT_ID,),
            ),
        )
        latency_report: dict[str, float] = {}
        for query_number, (statement, parameters) in enumerate(
            benchmark_queries,
            start=1,
        ):
            for _ in range(5):
                connection.execute(statement, parameters).fetchall()
            samples = []
            for _ in range(30):
                started = perf_counter()
                connection.execute(statement, parameters).fetchall()
                samples.append((perf_counter() - started) * 1000)
            p95 = _percentile_95(samples)
            latency_report[f"query_{query_number}_p95_ms"] = p95
            assert p95 < 500

    sqlalchemy_url = normalized_url.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )
    engine = create_engine(
        sqlalchemy_url,
        pool_size=5,
        max_overflow=0,
        pool_timeout=5,
    )
    concurrent_statements = (
        (
            text(
                "SELECT entity_id FROM catalog.alias "
                "WHERE dataset_version = :dataset_version "
                "AND normalized_alias_text = :alias_text"
            ),
            {
                "dataset_version": SCALE_DATASET_VERSION,
                "alias_text": TARGET_ALIAS,
            },
        ),
        (
            text(
                "SELECT object_id FROM relation.relation_record "
                "WHERE dataset_version = :dataset_version "
                "AND predicate_id = 'etf_constituent' "
                "AND subject_id = :entity_id"
            ),
            {
                "dataset_version": SCALE_DATASET_VERSION,
                "entity_id": TARGET_ENTITY_ID,
            },
        ),
        (
            text(
                "SELECT numeric_value FROM observation.observation_record "
                "WHERE dataset_version = :dataset_version "
                "AND entity_id = :entity_id "
                "AND metric_id = 'market_value' "
                "ORDER BY applicable_date DESC LIMIT 1"
            ),
            {
                "dataset_version": SCALE_DATASET_VERSION,
                "entity_id": TARGET_ENTITY_ID,
            },
        ),
        (
            text(
                "SELECT claim_id FROM evidence.claim_support "
                "WHERE dataset_version = :dataset_version "
                "AND evidence_id = :evidence_id"
            ),
            {
                "dataset_version": SCALE_DATASET_VERSION,
                "evidence_id": TARGET_EVIDENCE_ID,
            },
        ),
    )

    def execute_read(statement, parameters) -> float:
        started = perf_counter()
        with engine.connect() as connection:
            connection.execute(statement, parameters).all()
        return (perf_counter() - started) * 1000

    round_samples = []
    individual_samples = []
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            for _ in range(30):
                round_started = perf_counter()
                futures = [
                    executor.submit(execute_read, statement, parameters)
                    for statement, parameters in concurrent_statements
                ]
                individual_samples.extend(future.result() for future in futures)
                round_samples.append((perf_counter() - round_started) * 1000)
    finally:
        engine.dispose()
    latency_report["concurrent_read_p95_ms"] = _percentile_95(individual_samples)
    latency_report["concurrent_round_p95_ms"] = _percentile_95(round_samples)
    print(json.dumps(latency_report, sort_keys=True))
