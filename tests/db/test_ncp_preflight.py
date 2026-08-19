from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import traceback

import psycopg
import pytest
from psycopg import sql

from financial_agent.db.preflight import (
    DEFAULT_DATABASE_OBJECT_MANIFEST,
    EXPECTED_APPLICATION_SCHEMAS,
    EXPECTED_SEARCH_PATH,
    PostMigrationSnapshot,
    PreflightFailure,
    PreflightSnapshot,
    collect_preflight_snapshot,
    collect_post_migration_snapshot,
    main,
    normalize_psycopg_url,
    run_post_migration_preflight,
    validate_pre_migration_snapshot,
    validate_post_migration_snapshot,
)
from scripts.export_database_objects import write_or_check_manifest


def _pre_migration_snapshot() -> PreflightSnapshot:
    roles = {name: False for name in ("fa_migration", "fa_build", "fa_runtime")}
    allowed = {name: True for name in roles}
    return PreflightSnapshot(
        current_user="financial_agent_test",
        postgres_major=15,
        server_encoding="UTF8",
        timezone="UTC",
        search_path=EXPECTED_SEARCH_PATH,
        extensions={
            "vector": "cdb_admin",
            "pg_stat_statements": "cdb_admin",
        },
        role_login=roles,
        role_public_usage=allowed,
        role_public_create={
            "fa_migration": True,
            "fa_build": False,
            "fa_runtime": False,
        },
        role_database_create={
            "fa_migration": True,
            "fa_build": False,
            "fa_runtime": False,
        },
        role_cdb_admin_usage=allowed,
        role_pg_stat_statements_select=allowed,
        vector_usable=True,
        pg_stat_statements_usable=True,
    )


def _post_migration_snapshot() -> PostMigrationSnapshot:
    return PostMigrationSnapshot(
        pre_migration=_pre_migration_snapshot(),
        extension_versions={
            "vector": "0.8.5",
            "pg_stat_statements": "1.10",
            "pg_trgm": "1.6",
            "unaccent": "1.1",
            "pgcrypto": "1.3",
        },
        extension_schemas={
            "vector": "cdb_admin",
            "pg_stat_statements": "cdb_admin",
            "pg_trgm": "public",
            "unaccent": "public",
            "pgcrypto": "public",
        },
        application_schemas=EXPECTED_APPLICATION_SCHEMAS,
        alembic_revision="0005",
        alembic_head="0005",
        cutoff_constraint_matches=True,
        active_dataset_consistent=True,
        parameterized_query_usable=True,
        public_tables=frozenset({"alembic_version"}),
        database_permissions_match=True,
        object_manifest_matches=True,
        permission_manifest_matches=True,
    )


def test_post_migration_cli_reports_connection_failure_without_leaking_url(
    monkeypatch,
    capsys,
) -> None:
    url = "postgresql://secret_user:secret_password@127.0.0.1:1/secret_db"
    monkeypatch.setenv("POST_MIGRATION_TEST_DATABASE_URL", url)

    exit_code = main(
        [
            "--phase",
            "post-migration",
            "--database-url-env",
            "POST_MIGRATION_TEST_DATABASE_URL",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == "DATABASE_UNREACHABLE: database connection failed\n"
    assert "secret_user" not in captured.err
    assert "secret_password" not in captured.err
    assert "secret_db" not in captured.err


def test_post_migration_exception_traceback_does_not_leak_connection_url() -> None:
    url = "postgresql://secret_user:secret_password@127.0.0.1:1/secret_db"

    with pytest.raises(PreflightFailure) as captured:
        run_post_migration_preflight(url)

    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
    rendered = "".join(
        traceback.format_exception(
            type(captured.value),
            captured.value,
            captured.value.__traceback__,
        )
    )
    assert "secret_user" not in rendered
    assert "secret_password" not in rendered
    assert "secret_db" not in rendered


def test_post_migration_snapshot_accepts_the_complete_storage_baseline() -> None:
    report = validate_post_migration_snapshot(_post_migration_snapshot())

    assert report.permission_layout == "group_roles"


@pytest.mark.parametrize(
    ("changes", "code"),
    (
        ({"application_schemas": frozenset({"operations"})}, "MIGRATION_BEHIND"),
        ({"alembic_revision": "0004"}, "MIGRATION_BEHIND"),
        ({"cutoff_constraint_matches": False}, "ACTIVE_DATASET_INCONSISTENT"),
        ({"active_dataset_consistent": False}, "ACTIVE_DATASET_INCONSISTENT"),
        ({"parameterized_query_usable": False}, "DATABASE_QUERY_FAILED"),
        (
            {"public_tables": frozenset({"alembic_version", "leaked_table"})},
            "MIGRATION_BEHIND",
        ),
        ({"database_permissions_match": False}, "DATABASE_PERMISSION_DRIFT"),
        ({"object_manifest_matches": False}, "OBJECT_DEFINITION_DRIFT"),
        ({"permission_manifest_matches": False}, "DATABASE_PERMISSION_DRIFT"),
    ),
)
def test_post_migration_snapshot_rejects_storage_drift_with_stable_codes(
    changes: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(PreflightFailure) as captured:
        validate_post_migration_snapshot(
            replace(_post_migration_snapshot(), **changes)
        )

    assert captured.value.code == code


def test_post_migration_snapshot_requires_installed_extension_versions() -> None:
    snapshot = replace(
        _post_migration_snapshot(),
        extension_versions={"vector": "0.8.5"},
    )

    with pytest.raises(PreflightFailure) as captured:
        validate_post_migration_snapshot(snapshot)

    assert captured.value.code == "MISSING_NCP_EXTENSION"


def test_post_migration_snapshot_requires_migration_managed_extensions() -> None:
    snapshot = _post_migration_snapshot()
    versions = dict(snapshot.extension_versions)
    versions.pop("unaccent")

    with pytest.raises(PreflightFailure) as captured:
        validate_post_migration_snapshot(
            replace(snapshot, extension_versions=versions)
        )

    assert captured.value.code == "MISSING_MIGRATION_EXTENSION"


def test_direct_user_preflight_rejects_runtime_database_create() -> None:
    snapshot = _pre_migration_snapshot()
    database_create = dict(snapshot.role_database_create)
    database_create["fa_runtime"] = True

    with pytest.raises(PreflightFailure) as captured:
        validate_pre_migration_snapshot(
            replace(
                snapshot,
                current_user="fa_migration",
                role_login={name: True for name in snapshot.role_login},
                role_database_create=database_create,
            )
        )

    assert captured.value.code == "DATABASE_PERMISSION_DRIFT"


def test_post_migration_snapshot_classifies_a_missing_role_before_permissions() -> None:
    pre_migration = _pre_migration_snapshot()
    role_login = dict(pre_migration.role_login)
    role_login.pop("fa_runtime")
    snapshot = replace(
        _post_migration_snapshot(),
        pre_migration=replace(pre_migration, role_login=role_login),
    )

    with pytest.raises(PreflightFailure) as captured:
        validate_post_migration_snapshot(snapshot)

    assert captured.value.code == "MISSING_DB_ROLE"


@pytest.mark.postgres
def test_post_migration_preflight_accepts_the_migrated_local_baseline(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "database-objects.json"
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        write_or_check_manifest(connection, manifest_path, check=False)

    report = run_post_migration_preflight(
        migrated_database_url,
        manifest_path=manifest_path,
    )

    assert report.permission_layout == "group_roles"


@pytest.mark.ncp_integration
def test_authorized_ncp_database_matches_the_post_migration_baseline(
    capsys,
) -> None:
    if not os.environ.get("FINANCIAL_AGENT_DATABASE_URL"):
        pytest.skip("the authorized NCP migration identity is not configured")
    exit_code = main(
        [
            "--phase",
            "post-migration",
            "--database-url-env",
            "FINANCIAL_AGENT_DATABASE_URL",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == (
        "PREFLIGHT_OK phase=post-migration permission_layout=direct_users\n"
    )
    assert captured.err == ""


@pytest.mark.postgres
@pytest.mark.parametrize(
    "permission_mutation",
    (
        "GRANT INSERT ON operations.request_subtask TO fa_runtime",
        "GRANT fa_build TO fa_runtime",
    ),
)
def test_post_migration_preflight_detects_direct_dml_or_role_membership_drift(
    migrated_database_url: str,
    tmp_path: Path,
    permission_mutation: str,
) -> None:
    manifest_path = tmp_path / "database-objects.json"
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        write_or_check_manifest(connection, manifest_path, check=False)
        try:
            connection.execute(permission_mutation)
            snapshot = collect_post_migration_snapshot(
                connection,
                manifest_path=manifest_path,
                alembic_head="0005",
            )
        finally:
            connection.rollback()

    assert snapshot.database_permissions_match is False


@pytest.mark.postgres
def test_public_table_inventory_is_independent_of_current_user_visibility(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        try:
            connection.execute(
                "CREATE TABLE public.task8_hidden_table (id integer)"
            )
            connection.execute(
                "ALTER TABLE public.task8_hidden_table OWNER TO fa_build"
            )
            connection.execute(
                "GRANT SELECT ON public.alembic_version, "
                "operations.dataset_readiness TO fa_runtime"
            )
            connection.execute("SET LOCAL ROLE fa_runtime")
            snapshot = collect_post_migration_snapshot(
                connection,
                manifest_path=DEFAULT_DATABASE_OBJECT_MANIFEST,
                alembic_head="0005",
            )
        finally:
            connection.rollback()

    assert "task8_hidden_table" in snapshot.public_tables


@pytest.mark.postgres
@pytest.mark.parametrize(
    "membership_mutation",
    (
        (
            "CREATE ROLE task8_external_group LOGIN; "
            "GRANT task8_external_group TO fa_runtime"
        ),
        (
            "ALTER ROLE fa_migration LOGIN; "
            "ALTER ROLE fa_build LOGIN; "
            "ALTER ROLE fa_runtime LOGIN; "
            "CREATE ROLE task8_external_member LOGIN; "
            "GRANT fa_build TO task8_external_member"
        ),
        (
            "CREATE ROLE task8_overlapping_member LOGIN; "
            "GRANT fa_build TO task8_overlapping_member; "
            "GRANT fa_runtime TO task8_overlapping_member"
        ),
    ),
)
def test_permission_layout_rejects_unapproved_external_membership_shape(
    migrated_database_url: str,
    membership_mutation: str,
) -> None:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        try:
            connection.execute(membership_mutation)
            snapshot = collect_post_migration_snapshot(
                connection,
                manifest_path=DEFAULT_DATABASE_OBJECT_MANIFEST,
                alembic_head="0005",
            )
        finally:
            connection.rollback()

    assert snapshot.database_permissions_match is False


@pytest.mark.postgres
def test_group_roles_allow_external_login_members_only_in_stable_roles(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        try:
            connection.execute("CREATE ROLE task8_approved_member LOGIN")
            connection.execute(
                "GRANT fa_build TO task8_approved_member"
            )
            snapshot = collect_post_migration_snapshot(
                connection,
                manifest_path=DEFAULT_DATABASE_OBJECT_MANIFEST,
                alembic_head="0005",
            )
        finally:
            connection.rollback()

    assert snapshot.database_permissions_match is True


@pytest.mark.postgres
def test_preflight_collects_role_database_create_and_rejects_runtime_drift(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url),
        options='-c timezone=UTC -c search_path="$user",public,cdb_admin',
    ) as connection:
        with connection.transaction(force_rollback=True):
            database_name = str(
                connection.execute("SELECT current_database()").fetchone()[0]
            )
            connection.execute(
                sql.SQL("GRANT CREATE ON DATABASE {} TO fa_runtime").format(
                    sql.Identifier(database_name)
                )
            )
            snapshot = collect_preflight_snapshot(connection)

    assert snapshot.role_database_create == {
        "fa_migration": True,
        "fa_build": False,
        "fa_runtime": True,
    }
    with pytest.raises(PreflightFailure) as captured:
        validate_pre_migration_snapshot(snapshot)

    assert captured.value.code == "DATABASE_PERMISSION_DRIFT"


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("extension_mutation", "expected_code"),
    (
        ("DROP EXTENSION unaccent", "MISSING_MIGRATION_EXTENSION"),
        (
            "CREATE SCHEMA task8_extension_drift; "
            "ALTER EXTENSION unaccent SET SCHEMA task8_extension_drift",
            "MIGRATION_EXTENSION_SCHEMA_MISMATCH",
        ),
    ),
)
def test_postflight_rejects_migration_extension_inventory_drift(
    migrated_database_url: str,
    tmp_path: Path,
    extension_mutation: str,
    expected_code: str,
) -> None:
    manifest_path = tmp_path / "database-objects.json"
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url),
        autocommit=True,
        options='-c timezone=UTC -c search_path="$user",public,cdb_admin',
    ) as connection:
        write_or_check_manifest(connection, manifest_path, check=False)
        with connection.transaction(force_rollback=True):
            connection.execute(extension_mutation)
            snapshot = collect_post_migration_snapshot(
                connection,
                manifest_path=manifest_path,
                alembic_head="0005",
            )
            with pytest.raises(PreflightFailure) as captured:
                validate_post_migration_snapshot(snapshot)

    assert captured.value.code == expected_code
    report = run_post_migration_preflight(
        migrated_database_url,
        manifest_path=manifest_path,
    )
    assert report.permission_layout == "group_roles"


class NcpRuntimeSmokeFailure(RuntimeError):
    pass


def _assert_ncp_runtime_permissions(connection: psycopg.Connection) -> None:
    current_user = str(
        connection.execute("SELECT current_user").fetchone()[0]
    )
    assert current_user == "fa_runtime"
    active_dataset = connection.execute(
        """
        SELECT singleton, dataset_version
        FROM operations.active_dataset
        WHERE singleton
        """
    ).fetchone()
    assert active_dataset is not None and active_dataset[0] is True
    try:
        with connection.transaction():
            connection.execute(
                "INSERT INTO operations.request_artifact "
                "(artifact_type, canonical_payload) "
                "VALUES ('tool_result', '{}')"
            )
    except psycopg.errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("runtime direct protected DML was allowed")
    assert connection.execute(
        "SELECT count(*) FROM operations.request_artifact"
    ).fetchone()[0] >= 0


def _run_authorized_ncp_runtime_smoke(database_url: str) -> None:
    try:
        with psycopg.connect(
            normalize_psycopg_url(database_url)
        ) as connection:
            _assert_ncp_runtime_permissions(connection)
    except Exception:
        raise NcpRuntimeSmokeFailure(
            "NCP_RUNTIME_SMOKE_FAILED: authorized runtime check failed"
        ) from None


def test_ncp_runtime_smoke_suppresses_connection_credentials(
    monkeypatch,
) -> None:
    database_url = (
        "postgresql://secret_user:secret_password@db.example/secret_db"
    )
    connection_attempted = False

    def fail_connect(*args: object, **kwargs: object) -> None:
        del args, kwargs
        nonlocal connection_attempted
        connection_attempted = True
        raise psycopg.OperationalError(database_url)

    monkeypatch.setattr(psycopg, "connect", fail_connect)

    with pytest.raises(NcpRuntimeSmokeFailure) as captured:
        _run_authorized_ncp_runtime_smoke(database_url)

    assert connection_attempted is True
    rendered = "".join(
        traceback.format_exception(
            type(captured.value),
            captured.value,
            captured.value.__traceback__,
        )
    )
    assert "secret_user" not in rendered
    assert "secret_password" not in rendered
    assert "secret_db" not in rendered


@pytest.mark.postgres
def test_runtime_smoke_reads_and_denies_direct_protected_dml_locally(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        connection.execute("SET LOCAL ROLE fa_runtime")
        _assert_ncp_runtime_permissions(connection)
        connection.rollback()


@pytest.mark.ncp_integration
def test_authorized_ncp_runtime_can_read_but_not_write_protected_tables() -> None:
    database_url = os.environ.get("FINANCIAL_AGENT_NCP_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("the authorized NCP runtime identity is not configured")

    _run_authorized_ncp_runtime_smoke(database_url)
