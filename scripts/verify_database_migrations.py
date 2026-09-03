from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from threading import Barrier

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from financial_agent.db.preflight import (
    DEFAULT_DATABASE_OBJECT_MANIFEST,
    EXPECTED_APPLICATION_SCHEMAS,
    EXPECTED_NCP_MANAGED_EXTENSIONS,
    EXPECTED_ROLES,
    normalize_psycopg_url,
    run_post_migration_preflight,
    run_pre_migration_preflight,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATABASE_NAME = "financial_agent_test"
DISPOSABLE_DATABASE_NAME = "financial_agent_migration_cycle_test"
LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
ALEMBIC_DATABASE_URL_ENV = "FINANCIAL_AGENT_DATABASE_URL"


class MigrationVerificationFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MigrationVerificationReport:
    alembic_head: str
    application_schema_count: int
    object_counts: Mapping[str, int]
    ncp_extensions_preserved: bool
    bootstrap_roles_preserved: bool
    foundation_cutoff_enforced: bool
    foundation_legacy_activation_rejected: bool
    foundation_transition_enforced: bool
    foundation_incomplete_readiness_rejected: bool
    foundation_readiness_activation_enforced: bool
    foundation_request_start_idempotent: bool
    foundation_request_conflict_rejected: bool
    foundation_append_only_enforced: bool
    foundation_intent_provenance_enforced: bool
    foundation_failure_payload_audit_enforced: bool
    foundation_concurrent_request_idempotent: bool
    foundation_concurrent_request_conflict_rejected: bool


def _assert_safe_source_url(url: str) -> None:
    parsed = make_url(normalize_psycopg_url(url))
    compose_database = (
        parsed.host == "postgres"
        and os.environ.get("FINANCIAL_AGENT_COMPOSE_DATABASE_CHECK") == "1"
    )
    if (
        parsed.get_backend_name() != "postgresql"
        or (parsed.host not in LOCAL_DATABASE_HOSTS and not compose_database)
        or parsed.database != SOURCE_DATABASE_NAME
    ):
        raise MigrationVerificationFailure(
            "UNSAFE_DATABASE_TARGET",
            "migration verification requires the local disposable test cluster",
        )


def _named_database_url(url: str, database_name: str) -> str:
    return make_url(normalize_psycopg_url(url)).set(
        database=database_name
    ).render_as_string(hide_password=False)


def migration_alembic_config(database_url: str) -> Config:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@contextmanager
def configured_alembic_target_only() -> Iterator[None]:
    ambient_url = os.environ.pop(ALEMBIC_DATABASE_URL_ENV, None)
    try:
        yield
    finally:
        os.environ.pop(ALEMBIC_DATABASE_URL_ENV, None)
        if ambient_url is not None:
            os.environ[ALEMBIC_DATABASE_URL_ENV] = ambient_url


def _recreate_disposable_database(source_url: str) -> str:
    disposable_url = _named_database_url(
        source_url,
        DISPOSABLE_DATABASE_NAME,
    )
    with psycopg.connect(
        normalize_psycopg_url(source_url),
        autocommit=True,
    ) as administrator:
        administrator.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(DISPOSABLE_DATABASE_NAME)
            )
        )
        administrator.execute(
            sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(DISPOSABLE_DATABASE_NAME)
            )
        )

    with psycopg.connect(disposable_url, autocommit=True) as bootstrap:
        bootstrap.execute("CREATE SCHEMA cdb_admin")
        bootstrap.execute("CREATE EXTENSION vector WITH SCHEMA cdb_admin")
        bootstrap.execute(
            "CREATE EXTENSION pg_stat_statements WITH SCHEMA cdb_admin"
        )
        bootstrap.execute(
            sql.SQL("GRANT CREATE ON DATABASE {} TO fa_migration").format(
                sql.Identifier(DISPOSABLE_DATABASE_NAME)
            )
        )
        bootstrap.execute(
            "REVOKE CREATE ON SCHEMA public "
            "FROM PUBLIC, fa_build, fa_runtime"
        )
        bootstrap.execute(
            "GRANT USAGE, CREATE ON SCHEMA public TO fa_migration"
        )
        bootstrap.execute(
            "GRANT USAGE ON SCHEMA public TO fa_build, fa_runtime"
        )
        bootstrap.execute(
            "GRANT USAGE ON SCHEMA cdb_admin "
            "TO fa_migration, fa_build, fa_runtime"
        )
        bootstrap.execute(
            "GRANT SELECT ON cdb_admin.pg_stat_statements "
            "TO fa_migration, fa_build, fa_runtime"
        )
    return disposable_url


def _drop_disposable_database(source_url: str) -> None:
    with psycopg.connect(
        normalize_psycopg_url(source_url),
        autocommit=True,
    ) as administrator:
        administrator.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(DISPOSABLE_DATABASE_NAME)
            )
        )


@contextmanager
def disposable_migration_database(source_url: str) -> Iterator[str]:
    _assert_safe_source_url(source_url)
    database_url = _recreate_disposable_database(source_url)
    try:
        yield database_url
    finally:
        _drop_disposable_database(source_url)


def _collect_inventory(database_url: str) -> dict[str, int]:
    schemas = sorted(EXPECTED_APPLICATION_SCHEMAS)
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        queries = {
            "tables": """
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = ANY(%s)
                  AND relation.relkind IN ('r', 'p')
            """,
            "checks": """
                SELECT count(*)
                FROM pg_catalog.pg_constraint AS constraint_record
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = constraint_record.connamespace
                WHERE namespace.nspname = ANY(%s)
                  AND constraint_record.contype = 'c'
            """,
            "foreign_keys": """
                SELECT count(*)
                FROM pg_catalog.pg_constraint AS constraint_record
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = constraint_record.connamespace
                WHERE namespace.nspname = ANY(%s)
                  AND constraint_record.contype = 'f'
            """,
            "indexes": """
                SELECT count(*)
                FROM pg_catalog.pg_index AS index_record
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = index_record.indrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = ANY(%s)
            """,
            "functions": """
                SELECT count(*)
                FROM pg_catalog.pg_proc AS procedure
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = ANY(%s)
            """,
            "views": """
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = ANY(%s)
                  AND relation.relkind IN ('v', 'm')
            """,
            "triggers": """
                SELECT count(*)
                FROM pg_catalog.pg_trigger AS trigger
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = trigger.tgrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = ANY(%s)
                  AND NOT trigger.tgisinternal
            """,
        }
        return {
            name: int(connection.execute(statement, (schemas,)).fetchone()[0])
            for name, statement in queries.items()
        }


def _verify_base_state(database_url: str) -> tuple[bool, bool]:
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        schema_count = int(
            connection.execute(
                """
                SELECT count(*)
                FROM pg_catalog.pg_namespace
                WHERE nspname = ANY(%s)
                """,
                (sorted(EXPECTED_APPLICATION_SCHEMAS),),
            ).fetchone()[0]
        )
        if schema_count != 0:
            raise MigrationVerificationFailure(
                "MIGRATION_DOWNGRADE_INCOMPLETE",
                "application schemas remain after downgrade to base",
            )
        extensions = {
            str(name): str(schema)
            for name, schema in connection.execute(
                """
                SELECT extension.extname, namespace.nspname
                FROM pg_catalog.pg_extension AS extension
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = extension.extnamespace
                WHERE extension.extname IN (
                    'vector', 'pg_stat_statements',
                    'pg_trgm', 'pgcrypto', 'unaccent'
                )
                """
            ).fetchall()
        }
        ncp_extensions_preserved = (
            extensions == EXPECTED_NCP_MANAGED_EXTENSIONS
        )
        roles = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT rolname
                FROM pg_catalog.pg_roles
                WHERE rolname = ANY(%s)
                """,
                (sorted(EXPECTED_ROLES),),
            ).fetchall()
        }
        bootstrap_roles_preserved = roles == EXPECTED_ROLES
    if not ncp_extensions_preserved:
        raise MigrationVerificationFailure(
            "MISSING_NCP_EXTENSION",
            "downgrade changed the NCP-managed extensions",
        )
    if not bootstrap_roles_preserved:
        raise MigrationVerificationFailure(
            "MISSING_DB_ROLE",
            "downgrade changed the bootstrap roles",
        )
    return ncp_extensions_preserved, bootstrap_roles_preserved


def _verify_foundation_behavior(
    database_url: str,
) -> tuple[
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
]:
    cutoff_enforced = False
    legacy_activation_rejected = False
    transition_enforced = False
    incomplete_readiness_rejected = False
    readiness_activation_enforced = False
    request_start_idempotent = False
    request_conflict_rejected = False
    append_only_enforced = False
    intent_provenance_enforced = False
    failure_payload_audit_enforced = False
    concurrent_request_idempotent = False
    concurrent_request_conflict_rejected = False
    normalized_url = normalize_psycopg_url(database_url)
    with psycopg.connect(normalized_url) as connection:
        with connection.transaction(force_rollback=True):
            connection.execute(
                """
                INSERT INTO operations.dataset_version (
                    dataset_version, cutoff_date, status, manifest_hash,
                    created_at
                ) VALUES (
                    'task8-foundation-probe', DATE '2026-08-24', 'building',
                    repeat('1', 64), TIMESTAMPTZ '2026-08-19 00:00:00+00'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO operations.dataset_version (
                    dataset_version, cutoff_date, status, manifest_hash,
                    created_at
                ) VALUES (
                    'task8-legacy-cutoff-probe', DATE '2026-07-11', 'building',
                    repeat('9', 64), TIMESTAMPTZ '2026-08-19 00:00:00+00'
                )
                """
            )
            try:
                with connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO operations.dataset_version (
                            dataset_version, cutoff_date, status,
                            manifest_hash, created_at
                        ) VALUES (
                            'task8-invalid-cutoff', DATE '2026-08-25',
                            'building', repeat('2', 64),
                            TIMESTAMPTZ '2026-08-19 00:00:00+00'
                        )
                        """
                    )
            except psycopg.errors.CheckViolation as error:
                cutoff_enforced = (
                    error.diag.constraint_name
                    == "ck_dataset_version_cutoff_date"
                    and connection.execute(
                        """
                        SELECT count(*)
                        FROM operations.dataset_version
                        WHERE dataset_version IN (
                            'task8-foundation-probe',
                            'task8-legacy-cutoff-probe'
                        )
                        """
                    ).fetchone()[0]
                    == 2
                )
            try:
                with connection.transaction():
                    connection.execute(
                        """
                        UPDATE operations.dataset_version
                           SET status = 'active'
                         WHERE dataset_version = 'task8-foundation-probe'
                        """
                    )
            except psycopg.Error as error:
                transition_enforced = (
                    error.sqlstate == "55000"
                    and "INVALID_DATASET_TRANSITION" in str(error)
                )

        connection.execute(
            """
            INSERT INTO operations.dataset_version (
                dataset_version, cutoff_date, status, manifest_hash, created_at
            ) VALUES (
                'task8-second-head-active', DATE '2026-08-24', 'building',
                repeat('3', 64), TIMESTAMPTZ '2026-08-19 00:00:00+00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO operations.dataset_validation_run (
                validation_run_id, dataset_version, dataset_manifest_hash,
                validator_id, validator_version, started_at, finished_at,
                status, report_hash
            ) VALUES (
                'task8-second-head-validation', 'task8-second-head-active',
                repeat('3', 64), 'task8-verifier', '1',
                TIMESTAMPTZ '2026-08-19 00:00:00+00',
                TIMESTAMPTZ '2026-08-19 00:00:01+00', 'pass', repeat('4', 64)
            )
            """
        )
        connection.execute(
            "SELECT operations.finish_dataset_validation(%s)",
            ("task8-second-head-validation",),
        )
        connection.execute(
            """
            SELECT operations.record_dataset_readiness(
                %s, %s, %s, %s,
                TIMESTAMPTZ '2026-08-19 00:00:02+00', '1'
            )
            """,
            (
                "task8-second-head-active",
                "postgres",
                "task8-second-head-validation",
                "5" * 64,
            ),
        )
        try:
            with connection.transaction():
                connection.execute(
                    "SELECT operations.activate_dataset(%s)",
                    ("task8-second-head-active",),
                )
        except psycopg.errors.CheckViolation as error:
            incomplete_readiness_rejected = (
                error.diag.message_primary == "DATASET_READINESS_INCOMPLETE"
            )
        if not incomplete_readiness_rejected:
            raise MigrationVerificationFailure(
                "FOUNDATION_INVARIANT_FAILED",
                "second-head incomplete readiness was not rejected",
            )

        for component in ("graph", "vector", "evidence"):
            connection.execute(
                """
                SELECT operations.record_dataset_readiness(
                    %s, %s, %s, %s,
                    TIMESTAMPTZ '2026-08-19 00:00:02+00', '1'
                )
                """,
                (
                    "task8-second-head-active",
                    component,
                    "task8-second-head-validation",
                    "5" * 64,
                ),
            )
        activated = connection.execute(
            "SELECT operations.activate_dataset(%s)",
            ("task8-second-head-active",),
        ).fetchone()[0]
        active_state = connection.execute(
            """
            SELECT dataset.status, active.dataset_version
            FROM operations.dataset_version AS dataset
            CROSS JOIN operations.active_dataset AS active
            WHERE dataset.dataset_version = 'task8-second-head-active'
              AND active.singleton
            """
        ).fetchone()
        readiness_activation_enforced = (
            activated == "task8-second-head-active"
            and active_state
            == ("active", "task8-second-head-active")
        )
        if not readiness_activation_enforced:
            raise MigrationVerificationFailure(
                "FOUNDATION_INVARIANT_FAILED",
                "second-head readiness or activation behavior is incompatible",
            )

        connection.execute(
            """
            INSERT INTO operations.dataset_version (
                dataset_version, cutoff_date, status, manifest_hash, created_at
            ) VALUES (
                'task8-legacy-not-active', DATE '2026-07-11', 'building',
                repeat('9', 64), TIMESTAMPTZ '2026-08-19 00:00:00+00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO operations.dataset_validation_run (
                validation_run_id, dataset_version, dataset_manifest_hash,
                validator_id, validator_version, started_at, finished_at,
                status, report_hash
            ) VALUES (
                'task8-legacy-validation', 'task8-legacy-not-active',
                repeat('9', 64), 'task8-verifier', '1',
                TIMESTAMPTZ '2026-08-19 00:00:00+00',
                TIMESTAMPTZ '2026-08-19 00:00:01+00', 'pass', repeat('8', 64)
            )
            """
        )
        connection.execute(
            "SELECT operations.finish_dataset_validation(%s)",
            ("task8-legacy-validation",),
        )
        for component in ("postgres", "graph", "vector", "evidence"):
            connection.execute(
                """
                SELECT operations.record_dataset_readiness(
                    %s, %s, %s, %s,
                    TIMESTAMPTZ '2026-08-19 00:00:02+00', '1'
                )
                """,
                (
                    "task8-legacy-not-active",
                    component,
                    "task8-legacy-validation",
                    "7" * 64,
                ),
            )
        try:
            with connection.transaction():
                connection.execute(
                    "SELECT operations.activate_dataset(%s)",
                    ("task8-legacy-not-active",),
                )
        except psycopg.errors.CheckViolation as error:
            legacy_activation_rejected = (
                error.diag.message_primary
                == "LEGACY_DATASET_CANNOT_ACTIVATE"
            )
        if not legacy_activation_rejected:
            raise MigrationVerificationFailure(
                "FOUNDATION_INVARIANT_FAILED",
                "legacy dataset activation was not rejected",
            )

        request_statement = """
            SELECT (operations.start_request_run(
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )).run_id
        """
        request_parameters = (
            "task8-second-head-run",
            "6" * 64,
            "Q-TASK8",
            "second-head behavior probe",
            "1.0.0",
            "task8-second-head-active",
            "2026-08-24",
            "2026-08-19T00:00:03+00:00",
            "2026-08-19T00:00:58+00:00",
        )
        first_run = connection.execute(
            request_statement, request_parameters
        ).fetchone()[0]
        second_run = connection.execute(
            request_statement, request_parameters
        ).fetchone()[0]
        request_count = connection.execute(
            "SELECT count(*) FROM operations.request_run WHERE run_id = %s",
            ("task8-second-head-run",),
        ).fetchone()[0]
        request_start_idempotent = (
            first_run == second_run == "task8-second-head-run"
            and request_count == 1
        )
        if not request_start_idempotent:
            raise MigrationVerificationFailure(
                "FOUNDATION_INVARIANT_FAILED",
                "second-head request-start behavior is incompatible",
            )
        conflicting_parameters = list(request_parameters)
        conflicting_parameters[3] = "divergent second-head behavior probe"
        try:
            with connection.transaction():
                connection.execute(
                    request_statement,
                    tuple(conflicting_parameters),
                )
        except psycopg.errors.RaiseException as error:
            request_conflict_rejected = (
                error.diag.message_primary == "REQUEST_RUN_CONFLICT"
            )
        if not request_conflict_rejected:
            raise MigrationVerificationFailure(
                "FOUNDATION_INVARIANT_FAILED",
                "second-head conflicting request reuse was not rejected",
            )

        canonical_payload = json.dumps(
            {
                "schema_version": "1.0.0",
                "request_key": "6" * 64,
                "run_id": "task8-second-head-run",
                "dataset_version": "task8-second-head-active",
                "cutoff_date": "2026-08-24",
                "producer": "task8-migration-verifier",
                "created_at": "2026-08-19T00:00:03+00:00",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        first_artifact = connection.execute(
            "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
            ("request_context", None, None, canonical_payload),
        ).fetchone()[0]
        second_artifact = connection.execute(
            "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
            ("request_context", None, None, canonical_payload),
        ).fetchone()[0]
        artifact_count = connection.execute(
            "SELECT count(*) FROM operations.request_artifact "
            "WHERE run_id = %s AND artifact_type = 'request_context'",
            ("task8-second-head-run",),
        ).fetchone()[0]
        immutable_update_rejected = False
        try:
            with connection.transaction():
                connection.execute(
                    "UPDATE operations.request_artifact SET producer = 'changed' "
                    "WHERE artifact_record_id = %s",
                    (first_artifact,),
                )
        except psycopg.errors.ObjectNotInPrerequisiteState:
            immutable_update_rejected = True
        append_only_enforced = (
            first_artifact == second_artifact
            and artifact_count == 1
            and immutable_update_rejected
        )

        intent_payload = json.dumps(
            {
                "schema_version": "1.0.0",
                "request_key": "6" * 64,
                "run_id": "task8-second-head-run",
                "dataset_version": "task8-second-head-active",
                "cutoff_date": "2026-08-24",
                "producer": "task10-intent-resolver",
                "created_at": "2026-08-19T00:00:03+00:00",
                "resolution_id": "task10-resolution",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        missing_intent_provenance_rejected = False
        try:
            with connection.transaction():
                connection.execute(
                    "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
                    ("intent_resolution", None, None, intent_payload),
                )
        except psycopg.errors.CheckViolation:
            missing_intent_provenance_rejected = True
        first_intent_artifact = connection.execute(
            "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
            (
                "intent_resolution",
                "task10-model",
                "task10-prompt",
                intent_payload,
            ),
        ).fetchone()[0]
        second_intent_artifact = connection.execute(
            "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
            (
                "intent_resolution",
                "task10-model",
                "task10-prompt",
                intent_payload,
            ),
        ).fetchone()[0]
        provenance_conflict_rejected = False
        try:
            with connection.transaction():
                connection.execute(
                    "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
                    (
                        "intent_resolution",
                        "different-model",
                        "task10-prompt",
                        intent_payload,
                    ),
                )
        except psycopg.errors.RaiseException as error:
            provenance_conflict_rejected = (
                error.diag.message_primary == "ARTIFACT_CONFLICT"
            )

        query_plan_artifact = connection.execute(
            "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
            ("query_plan", None, None, canonical_payload),
        ).fetchone()[0]
        query_plan_provenance_rejected = False
        try:
            with connection.transaction():
                connection.execute(
                    "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
                    ("query_plan", "task10-model", "task10-prompt", canonical_payload),
                )
        except psycopg.errors.CheckViolation:
            query_plan_provenance_rejected = True
        intent_contract_id = connection.execute(
            """
            SELECT contract_object_id
            FROM operations.request_artifact
            WHERE artifact_record_id = %s
            """,
            (first_intent_artifact,),
        ).fetchone()[0]
        intent_provenance_enforced = (
            missing_intent_provenance_rejected
            and first_intent_artifact == second_intent_artifact
            and provenance_conflict_rejected
            and query_plan_artifact is not None
            and query_plan_provenance_rejected
            and intent_contract_id == "task10-resolution"
        )

        connection.execute(
            """
            INSERT INTO operations.failure_event (
                event_id, run_id, stage, code, category, retryable, attempt,
                remaining_budget_ms, duration_ms, occurred_at, payload_hash,
                payload_size_bytes
            ) VALUES (
                'task10-payload-audit', 'task8-second-head-run',
                'intent_resolution', 'MODEL_SCHEMA_INVALID',
                'planner_contract', false, 1, 1000, 10,
                TIMESTAMPTZ '2026-08-19 00:00:04+00', repeat('a', 64), 128
            )
            """
        )
        payload_hash_rejected = False
        try:
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO operations.failure_event (
                        event_id, run_id, stage, code, category, retryable,
                        attempt, remaining_budget_ms, duration_ms, occurred_at,
                        payload_hash, payload_size_bytes
                    ) VALUES (
                        'task10-bad-payload-hash', 'task8-second-head-run',
                        'intent_resolution', 'MODEL_SCHEMA_INVALID',
                        'planner_contract', false, 1, 1000, 10,
                        TIMESTAMPTZ '2026-08-19 00:00:04+00', 'bad', 1
                    )
                    """
                )
        except psycopg.errors.CheckViolation:
            payload_hash_rejected = True
        payload_size_rejected = False
        try:
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO operations.failure_event (
                        event_id, run_id, stage, code, category, retryable,
                        attempt, remaining_budget_ms, duration_ms, occurred_at,
                        payload_hash, payload_size_bytes
                    ) VALUES (
                        'task10-bad-payload-size', 'task8-second-head-run',
                        'intent_resolution', 'MODEL_SCHEMA_INVALID',
                        'planner_contract', false, 1, 1000, 10,
                        TIMESTAMPTZ '2026-08-19 00:00:04+00', repeat('b', 64), -1
                    )
                    """
                )
        except psycopg.errors.CheckViolation:
            payload_size_rejected = True
        raw_payload_column_count = connection.execute(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_schema = 'operations'
              AND table_name = 'failure_event'
              AND column_name IN (
                  'raw_payload', 'raw_question', 'raw_model_output'
              )
            """
        ).fetchone()[0]
        failure_payload_audit_enforced = (
            payload_hash_rejected
            and payload_size_rejected
            and raw_payload_column_count == 0
        )
        connection.commit()

        concurrent_parameters = (
            "task8-second-head-concurrent",
            "7" * 64,
            "Q-TASK8-CONCURRENT",
            "second-head concurrent probe",
            "1.0.0",
            "task8-second-head-active",
            "2026-08-24",
            "2026-08-19T00:00:04+00:00",
            "2026-08-19T00:00:59+00:00",
        )
        barrier = Barrier(2)

        def start_concurrent_request() -> str:
            with psycopg.connect(normalized_url) as concurrent_connection:
                barrier.wait()
                return str(
                    concurrent_connection.execute(
                        request_statement,
                        concurrent_parameters,
                    ).fetchone()[0]
                )

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(
                    executor.map(
                        lambda _: start_concurrent_request(),
                        range(2),
                    )
                )
        except psycopg.Error:
            results = []
        concurrent_count = connection.execute(
            "SELECT count(*) FROM operations.request_run WHERE run_id = %s",
            ("task8-second-head-concurrent",),
        ).fetchone()[0]
        concurrent_request_idempotent = (
            results
            == [
                "task8-second-head-concurrent",
                "task8-second-head-concurrent",
            ]
            and concurrent_count == 1
        )
        if not concurrent_request_idempotent:
            raise MigrationVerificationFailure(
                "FOUNDATION_INVARIANT_FAILED",
                "second-head concurrent request convergence is incompatible",
            )

        conflicting_run_id = "task8-second-head-concurrent-conflict"
        conflicting_questions = (
            "second-head concurrent conflict probe A",
            "second-head concurrent conflict probe B",
        )
        conflict_barrier = Barrier(2)

        def start_conflicting_request(question: str) -> str:
            parameters = (
                conflicting_run_id,
                "8" * 64,
                "Q-TASK8-CONCURRENT-CONFLICT",
                question,
                "1.0.0",
                "task8-second-head-active",
                "2026-08-24",
                "2026-08-19T00:00:05+00:00",
                "2026-08-19T00:01:00+00:00",
            )
            with psycopg.connect(normalized_url) as concurrent_connection:
                conflict_barrier.wait()
                try:
                    with concurrent_connection.transaction():
                        return str(
                            concurrent_connection.execute(
                                request_statement,
                                parameters,
                            ).fetchone()[0]
                        )
                except psycopg.errors.RaiseException as error:
                    if error.diag.message_primary == "REQUEST_RUN_CONFLICT":
                        return "REQUEST_RUN_CONFLICT"
                    raise

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                conflict_results = list(
                    executor.map(
                        start_conflicting_request,
                        conflicting_questions,
                    )
                )
        except psycopg.Error:
            conflict_results = []
        conflict_row = connection.execute(
            """
            SELECT count(*), min(question)
            FROM operations.request_run
            WHERE run_id = %s
            """,
            (conflicting_run_id,),
        ).fetchone()
        concurrent_request_conflict_rejected = (
            set(conflict_results)
            == {conflicting_run_id, "REQUEST_RUN_CONFLICT"}
            and conflict_row is not None
            and conflict_row[0] == 1
            and conflict_row[1] in conflicting_questions
        )
    if not all(
        (
            cutoff_enforced,
            legacy_activation_rejected,
            transition_enforced,
            incomplete_readiness_rejected,
            readiness_activation_enforced,
            request_start_idempotent,
            request_conflict_rejected,
            append_only_enforced,
            intent_provenance_enforced,
            failure_payload_audit_enforced,
            concurrent_request_idempotent,
            concurrent_request_conflict_rejected,
        )
    ):
        raise MigrationVerificationFailure(
            "FOUNDATION_INVARIANT_FAILED",
            "second-head foundation behavior is incompatible",
        )
    return (
        cutoff_enforced,
        legacy_activation_rejected,
        transition_enforced,
        incomplete_readiness_rejected,
        readiness_activation_enforced,
        request_start_idempotent,
        request_conflict_rejected,
        append_only_enforced,
        intent_provenance_enforced,
        failure_payload_audit_enforced,
        concurrent_request_idempotent,
        concurrent_request_conflict_rejected,
    )


def verify_migration_cycle(source_url: str) -> MigrationVerificationReport:
    with disposable_migration_database(source_url) as disposable_url:
        config = migration_alembic_config(disposable_url)
        run_pre_migration_preflight(disposable_url)
        with configured_alembic_target_only():
            command.upgrade(config, "head")
        with configured_alembic_target_only():
            command.check(config)
        first_report = run_post_migration_preflight(
            disposable_url,
            manifest_path=DEFAULT_DATABASE_OBJECT_MANIFEST,
        )
        first_inventory = _collect_inventory(disposable_url)

        with configured_alembic_target_only():
            command.downgrade(config, "base")
        ncp_extensions_preserved, bootstrap_roles_preserved = (
            _verify_base_state(disposable_url)
        )

        with configured_alembic_target_only():
            command.upgrade(config, "head")
        with configured_alembic_target_only():
            command.check(config)
        second_report = run_post_migration_preflight(
            disposable_url,
            manifest_path=DEFAULT_DATABASE_OBJECT_MANIFEST,
        )
        second_inventory = _collect_inventory(disposable_url)
        (
            foundation_cutoff_enforced,
            foundation_legacy_activation_rejected,
            foundation_transition_enforced,
            foundation_incomplete_readiness_rejected,
            foundation_readiness_activation_enforced,
            foundation_request_start_idempotent,
            foundation_request_conflict_rejected,
            foundation_append_only_enforced,
            foundation_intent_provenance_enforced,
            foundation_failure_payload_audit_enforced,
            foundation_concurrent_request_idempotent,
            foundation_concurrent_request_conflict_rejected,
        ) = _verify_foundation_behavior(disposable_url)
        if first_inventory != second_inventory:
            raise MigrationVerificationFailure(
                "MIGRATION_CYCLE_DRIFT",
                "database inventory changed across the migration cycle",
            )
        if first_report != second_report:
            raise MigrationVerificationFailure(
                "MIGRATION_CYCLE_DRIFT",
                "preflight result changed across the migration cycle",
            )
        return MigrationVerificationReport(
            alembic_head="0011",
            application_schema_count=len(EXPECTED_APPLICATION_SCHEMAS),
            object_counts=second_inventory,
            ncp_extensions_preserved=ncp_extensions_preserved,
            bootstrap_roles_preserved=bootstrap_roles_preserved,
            foundation_cutoff_enforced=foundation_cutoff_enforced,
            foundation_legacy_activation_rejected=(
                foundation_legacy_activation_rejected
            ),
            foundation_transition_enforced=foundation_transition_enforced,
            foundation_incomplete_readiness_rejected=(
                foundation_incomplete_readiness_rejected
            ),
            foundation_readiness_activation_enforced=(
                foundation_readiness_activation_enforced
            ),
            foundation_request_start_idempotent=(
                foundation_request_start_idempotent
            ),
            foundation_request_conflict_rejected=(
                foundation_request_conflict_rejected
            ),
            foundation_append_only_enforced=foundation_append_only_enforced,
            foundation_intent_provenance_enforced=(
                foundation_intent_provenance_enforced
            ),
            foundation_failure_payload_audit_enforced=(
                foundation_failure_payload_audit_enforced
            ),
            foundation_concurrent_request_idempotent=(
                foundation_concurrent_request_idempotent
            ),
            foundation_concurrent_request_conflict_rejected=(
                foundation_concurrent_request_conflict_rejected
            ),
        )


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser().parse_args(argv)
    database_url = os.environ.get("FINANCIAL_AGENT_TEST_DATABASE_URL")
    if not database_url:
        print(
            "MISSING_DATABASE_URL: FINANCIAL_AGENT_TEST_DATABASE_URL is unset",
            file=sys.stderr,
        )
        return 2
    try:
        report = verify_migration_cycle(database_url)
    except MigrationVerificationFailure as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    except Exception:
        print(
            "MIGRATION_VERIFICATION_FAILED: disposable migration cycle failed",
            file=sys.stderr,
        )
        return 2
    counts = ",".join(
        f"{name}={count}" for name, count in sorted(report.object_counts.items())
    )
    print(
        f"MIGRATION_VERIFICATION_OK head={report.alembic_head} {counts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
