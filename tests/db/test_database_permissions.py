from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from financial_agent.contracts import QueryPlan, canonical_json_bytes
from financial_agent.db.preflight import normalize_psycopg_url

from .conftest import PROJECT_ROOT
from .test_foundation_migration import (
    VALID_MANIFEST_HASH,
    finish_and_ready_dataset,
    insert_dataset_validation,
)


PROTECTED_FUNCTION_GRANTS = {
    "reject_nonbuilding_dataset_mutation": set(),
    "lock_building_dataset": {"fa_build"},
    "finish_dataset_validation": {"fa_build"},
    "record_dataset_readiness": {"fa_build"},
    "activate_dataset": {"fa_build"},
    "start_request_run": {"fa_runtime"},
    "append_request_artifact": {"fa_runtime"},
    "finish_request_run": {"fa_runtime"},
}


@pytest.mark.postgres
def test_build_locks_building_dataset_only_through_protected_function(
    connection: psycopg.Connection,
) -> None:
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, manifest_hash, created_at
        ) VALUES (
            'document-build-lock', DATE '2026-08-24', %s, %s
        )
        """,
        (VALID_MANIFEST_HASH, datetime(2026, 8, 31, tzinfo=UTC)),
    )
    connection.execute("SET LOCAL ROLE fa_build")
    assert connection.execute(
        "SELECT operations.lock_building_dataset(%s)",
        ("document-build-lock",),
    ).fetchone()[0] is True
    connection.execute("RESET ROLE")
    assert_statement_denied(
        connection,
        role="fa_runtime",
        statement=(
            "SELECT operations.lock_building_dataset("
            "'document-build-lock')"
        ),
    )


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as database_connection:
        yield database_connection
        database_connection.rollback()


def assert_statement_denied(
    connection: psycopg.Connection,
    *,
    role: str,
    statement: str,
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connection.transaction():
            connection.execute(f"SET LOCAL ROLE {role}")
            connection.execute(statement)


def role_database_url(database_url: str, role: str, password: str) -> str:
    return make_url(normalize_psycopg_url(database_url)).set(
        username=role,
        password=password,
    ).render_as_string(hide_password=False)


def named_database_url(database_url: str, database_name: str) -> str:
    return make_url(normalize_psycopg_url(database_url)).set(
        database=database_name,
    ).render_as_string(hide_password=False)


@pytest.mark.postgres
def test_protected_functions_have_hardened_ownership_and_acl(
    connection: psycopg.Connection,
) -> None:
    rows = connection.execute(
        """
        SELECT
            procedure.proname,
            procedure.oid,
            procedure.prosecdef,
            owner.rolname,
            procedure.proconfig,
            EXISTS (
                SELECT 1
                FROM pg_catalog.aclexplode(
                    COALESCE(
                        procedure.proacl,
                        pg_catalog.acldefault('f', procedure.proowner)
                    )
                ) AS acl
                WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
            ) AS public_execute
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        JOIN pg_catalog.pg_roles AS owner
          ON owner.oid = procedure.proowner
        WHERE namespace.nspname = 'operations'
          AND procedure.proname = ANY(%s)
        ORDER BY procedure.proname
        """,
        (list(PROTECTED_FUNCTION_GRANTS),),
    ).fetchall()

    assert {str(row[0]) for row in rows} == set(PROTECTED_FUNCTION_GRANTS)
    for name, oid, security_definer, owner, settings, public_execute in rows:
        assert security_definer is True
        assert owner == "fa_migration"
        assert "search_path=pg_catalog, operations, pg_temp" in settings
        assert public_execute is False
        for role in ("fa_build", "fa_runtime"):
            has_execute = connection.execute(
                "SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')",
                (role, oid),
            ).fetchone()[0]
            assert has_execute is (role in PROTECTED_FUNCTION_GRANTS[str(name)])


@pytest.mark.postgres
@pytest.mark.parametrize("role", ("fa_build", "fa_runtime"))
def test_nonmigration_roles_cannot_create_in_application_schemas(
    connection: psycopg.Connection,
    role: str,
) -> None:
    assert_statement_denied(
        connection,
        role=role,
        statement="CREATE TABLE operations.forbidden_object (id integer)",
    )
    assert_statement_denied(
        connection,
        role=role,
        statement="CREATE TABLE public.forbidden_object (id integer)",
    )
    assert connection.execute(
        "SELECT pg_catalog.has_schema_privilege(%s, 'public', 'CREATE')",
        (role,),
    ).fetchone()[0] is False
    assert_statement_denied(
        connection,
        role=role,
        statement="""
            CREATE OR REPLACE FUNCTION operations.activate_dataset(text)
            RETURNS text LANGUAGE sql AS 'SELECT $1'
        """,
    )


@pytest.mark.postgres
def test_build_cannot_bypass_readiness_or_dataset_transitions(
    connection: psycopg.Connection,
) -> None:
    assert_statement_denied(
        connection,
        role="fa_build",
        statement="""
            INSERT INTO operations.dataset_readiness (
                dataset_version, component, validation_run_id,
                dataset_manifest_hash, component_manifest_hash,
                validated_at, validator_version
            ) VALUES (
                'forbidden', 'postgres', 'forbidden',
                repeat('a', 64), repeat('b', 64), clock_timestamp(), '1'
            )
        """,
    )
    assert_statement_denied(
        connection,
        role="fa_build",
        statement="""
            UPDATE operations.dataset_version
            SET status = 'active'
            WHERE dataset_version = 'forbidden'
        """,
    )


@pytest.mark.postgres
def test_build_can_create_only_a_building_dataset_version(
    connection: psycopg.Connection,
) -> None:
    created_at = datetime(2026, 8, 18, tzinfo=UTC)
    connection.execute("SET LOCAL ROLE fa_build")
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, manifest_hash, created_at
        ) VALUES (
            'dataset-build-default', DATE '2026-08-24', %s, %s
        )
        """,
        (VALID_MANIFEST_HASH, created_at),
    )
    assert connection.execute(
        """
        SELECT status FROM operations.dataset_version
        WHERE dataset_version = 'dataset-build-default'
        """
    ).fetchone()[0] == "building"
    connection.execute(
        """
        INSERT INTO operations.dataset_validation_run (
            validation_run_id, dataset_version, dataset_manifest_hash,
            validator_id, validator_version, started_at, finished_at,
            status, report_hash
        ) VALUES (
            'validation-build-default', 'dataset-build-default', %s,
            'validator', '1', %s, %s, 'pass', %s
        )
        """,
        (
            VALID_MANIFEST_HASH,
            created_at,
            created_at + timedelta(seconds=1),
            "b" * 64,
        ),
    )
    connection.execute("RESET ROLE")

    assert_statement_denied(
        connection,
        role="fa_build",
        statement="""
            INSERT INTO operations.dataset_version (
                dataset_version, cutoff_date, status, manifest_hash, created_at
            ) VALUES (
                'dataset-build-active', DATE '2026-08-24', 'active',
                repeat('a', 64), clock_timestamp()
            )
        """,
    )


@pytest.mark.postgres
def test_build_cannot_append_validation_to_a_nonbuilding_dataset(
    connection: psycopg.Connection,
) -> None:
    insert_dataset_validation(
        connection,
        dataset_version="dataset-no-late-validation",
        validation_run_id="validation-initial",
    )
    connection.execute(
        "SELECT operations.finish_dataset_validation(%s)",
        ("validation-initial",),
    )

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        with connection.transaction():
            connection.execute("SET LOCAL ROLE fa_build")
            connection.execute(
                """
                INSERT INTO operations.dataset_validation_run (
                    validation_run_id, dataset_version, dataset_manifest_hash,
                    validator_id, validator_version, started_at, finished_at,
                    status, report_hash
                ) VALUES (
                    'validation-too-late', 'dataset-no-late-validation', %s,
                    'validator', '1', %s, %s, 'pass', %s
                )
                """,
                (
                    VALID_MANIFEST_HASH,
                    datetime(2026, 8, 18, tzinfo=UTC),
                    datetime(2026, 8, 18, 0, 0, 1, tzinfo=UTC),
                    "b" * 64,
                ),
            )


@pytest.mark.postgres
def test_runtime_cannot_insert_request_runs_directly(
    connection: psycopg.Connection,
) -> None:
    assert_statement_denied(
        connection,
        role="fa_runtime",
        statement="""
            INSERT INTO operations.request_run (
                run_id, request_key, question_id, question, schema_version,
                dataset_version, cutoff_date, created_at, deadline_at
            ) VALUES (
                'forbidden', repeat('a', 64), 'Q', 'question', '1',
                'forbidden', DATE '2026-08-24',
                clock_timestamp(), clock_timestamp() + interval '1 second'
            )
        """,
    )


@pytest.mark.postgres
def test_runtime_cannot_insert_request_subtasks_directly(
    connection: psycopg.Connection,
) -> None:
    for table_name in (
        "operations.request_subtask",
        "operations.request_artifact",
        "operations.artifact_evidence_ref",
        "operations.artifact_calculation_ref",
        "operations.artifact_claim_ref",
    ):
        for privilege in ("INSERT", "UPDATE", "DELETE"):
            assert connection.execute(
                "SELECT pg_catalog.has_table_privilege(%s, %s, %s)",
                ("fa_runtime", table_name, privilege),
            ).fetchone()[0] is False
    assert_statement_denied(
        connection,
        role="fa_runtime",
        statement="""
            INSERT INTO operations.request_subtask (
                run_id, subtask_id, importance
            ) VALUES ('forbidden', 'forbidden', 'critical')
        """,
    )


@pytest.mark.postgres
def test_build_and_runtime_can_use_only_their_approved_functions(
    connection: psycopg.Connection,
) -> None:
    insert_dataset_validation(
        connection,
        dataset_version="dataset-permission-path",
        validation_run_id="validation-permission-path",
    )
    connection.execute("SET LOCAL ROLE fa_build")
    assert connection.execute(
        "SELECT operations.finish_dataset_validation(%s)",
        ("validation-permission-path",),
    ).fetchone()[0] == "validated"
    for component in ("postgres", "graph", "vector", "evidence"):
        connection.execute(
            """
            SELECT operations.record_dataset_readiness(
                %s, %s, %s, %s, %s, '1'
            )
            """,
            (
                "dataset-permission-path",
                component,
                "validation-permission-path",
                "c" * 64,
                datetime(2026, 8, 18, 0, 0, 2, tzinfo=UTC),
            ),
        )
    assert connection.execute(
        "SELECT operations.activate_dataset(%s)",
        ("dataset-permission-path",),
    ).fetchone()[0] == "dataset-permission-path"
    connection.execute("RESET ROLE")

    created_at = datetime(2026, 8, 18, tzinfo=UTC)
    connection.execute("SET LOCAL ROLE fa_runtime")
    assert connection.execute(
        """
        SELECT (operations.start_request_run(
            %s, %s, %s, %s, %s, %s, DATE '2026-08-24', %s, %s
        )).run_id
        """,
        (
            "run-permission-path",
            "d" * 64,
            "Q-001",
            "question",
            "1.0",
            "dataset-permission-path",
            created_at,
            created_at + timedelta(seconds=55),
        ),
    ).fetchone()[0] == "run-permission-path"
    query_plan = QueryPlan.model_validate_json(
        json.dumps({
            "schema_version": "1.0",
            "request_key": "d" * 64,
            "run_id": "run-permission-path",
            "dataset_version": "dataset-permission-path",
            "cutoff_date": "2026-08-24",
            "producer": "intent-resolver",
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "intent_types": ["lookup"],
            "product_families": ["domestic_etf"],
            "subtasks": [
                {
                    "subtask_id": "subtask-1",
                    "intent_type": "lookup",
                    "importance": "critical",
                    "operation_ids": ["operation-1"],
                }
            ],
            "operations": [
                {
                    "subtask_id": "subtask-1",
                    "operation_id": "operation-1",
                    "parameter_ids": [],
                }
            ],
            "result_shape": "single_value",
            "requested_capabilities": ["rdb_lookup"],
            "initial_answerability": "supported",
        })
    )
    connection.execute(
        "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
        (
            "query_plan",
            None,
            None,
            canonical_json_bytes(query_plan).decode("utf-8"),
        ),
    )
    assert connection.execute(
        """
        SELECT subtask_id, importance FROM operations.request_subtask
        WHERE run_id = 'run-permission-path'
        """
    ).fetchone() == ("subtask-1", "critical")
    connection.execute(
        """
        INSERT INTO operations.failure_event (
            event_id, run_id, task_id, stage, code, category, retryable,
            attempt, remaining_budget_ms, duration_ms, occurred_at
        ) VALUES (
            'event-permission-path', 'run-permission-path', 'task-1',
            'retrieval', 'UPSTREAM_TIMEOUT', 'transient', true,
            1, 40000, 1000, %s
        )
        """,
        (created_at + timedelta(seconds=1),),
    )
    assert connection.execute(
        """
        SELECT count(*) FROM operations.failure_event
        WHERE run_id = 'run-permission-path'
        """
    ).fetchone()[0] == 1
    connection.execute("RESET ROLE")


@pytest.mark.postgres
def test_application_foreign_keys_never_cascade_deletes(
    connection: psycopg.Connection,
) -> None:
    cascade_count = connection.execute(
        """
        SELECT count(*)
        FROM pg_catalog.pg_constraint AS constraint_record
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = constraint_record.connamespace
        WHERE namespace.nspname = ANY(%s)
          AND constraint_record.contype = 'f'
          AND constraint_record.confdeltype = 'c'
        """,
        (
            [
                "catalog",
                "observation",
                "relation",
                "document",
                "search",
                "evidence",
                "operations",
            ],
        ),
    ).fetchone()[0]

    assert cascade_count == 0


@pytest.mark.postgres
def test_direct_login_users_apply_0001_and_preserve_permissions(
    postgres_database_url: str,
) -> None:
    normalized_url = normalize_psycopg_url(postgres_database_url)
    database_name = "financial_agent_direct_users_test"
    administrator_database_url = named_database_url(
        normalized_url,
        database_name,
    )
    test_password = "stage02-disposable-login"
    roles = ("fa_migration", "fa_build", "fa_runtime")
    with psycopg.connect(normalized_url, autocommit=True) as administrator:
        administrator.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database_name)
            )
        )
        administrator.execute(
            sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(database_name)
            )
        )
        for role in roles:
            administrator.execute(
                sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role),
                    sql.Literal(test_password),
                )
            )

    try:
        with psycopg.connect(
            administrator_database_url,
            autocommit=True,
        ) as bootstrap_connection:
            bootstrap_connection.execute("CREATE SCHEMA cdb_admin")
            bootstrap_connection.execute(
                "CREATE EXTENSION vector WITH SCHEMA cdb_admin"
            )
            bootstrap_connection.execute(
                "CREATE EXTENSION pg_stat_statements WITH SCHEMA cdb_admin"
            )
            bootstrap_connection.execute(
                sql.SQL("GRANT CREATE ON DATABASE {} TO fa_migration").format(
                    sql.Identifier(database_name)
                )
            )
            bootstrap_connection.execute(
                "REVOKE CREATE ON SCHEMA public "
                "FROM PUBLIC, fa_build, fa_runtime"
            )
            bootstrap_connection.execute(
                "GRANT USAGE, CREATE ON SCHEMA public TO fa_migration"
            )
            bootstrap_connection.execute(
                "GRANT USAGE ON SCHEMA public TO fa_build, fa_runtime"
            )
            bootstrap_connection.execute(
                "GRANT USAGE ON SCHEMA cdb_admin "
                "TO fa_migration, fa_build, fa_runtime"
            )
            bootstrap_connection.execute(
                "GRANT SELECT ON cdb_admin.pg_stat_statements "
                "TO fa_migration, fa_build, fa_runtime"
            )

        migration_url = role_database_url(
            administrator_database_url,
            "fa_migration",
            test_password,
        )
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", migration_url)
        command.upgrade(config, "head")
        command.check(config)

        for role in ("fa_build", "fa_runtime"):
            with psycopg.connect(
                role_database_url(
                    administrator_database_url,
                    role,
                    test_password,
                )
            ) as role_connection:
                assert role_connection.execute(
                    "SELECT current_user, session_user"
                ).fetchone() == (role, role)
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with role_connection.transaction():
                        role_connection.execute(
                            "CREATE TABLE public.forbidden_direct_login "
                            "(id integer)"
                        )
                assert role_connection.execute(
                    "SELECT count(*) FROM operations.dataset_version"
                ).fetchone()[0] == 0

        command.downgrade(config, "base")
        with psycopg.connect(administrator_database_url) as verification_connection:
            assert set(
                verification_connection.execute(
                    """
                    SELECT extname FROM pg_catalog.pg_extension
                    WHERE extname IN ('vector', 'pg_stat_statements')
                    """
                ).fetchall()
            ) == {("vector",), ("pg_stat_statements",)}
    finally:
        with psycopg.connect(normalized_url, autocommit=True) as administrator:
            for role in roles:
                administrator.execute(
                    sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(
                        sql.Identifier(role)
                    )
                )
            administrator.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
