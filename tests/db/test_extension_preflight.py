from __future__ import annotations

from dataclasses import replace

import pytest

from financial_agent.db.preflight import (
    EXPECTED_SEARCH_PATH,
    EXPECTED_ROLES,
    PreflightFailure,
    PreflightSnapshot,
    normalize_psycopg_url,
    run_pre_migration_preflight,
    validate_pre_migration_snapshot,
)


@pytest.fixture
def valid_snapshot() -> PreflightSnapshot:
    return PreflightSnapshot(
        postgres_major=15,
        server_encoding="UTF8",
        timezone="UTC",
        search_path=EXPECTED_SEARCH_PATH,
        extensions={
            "vector": "cdb_admin",
            "pg_stat_statements": "cdb_admin",
        },
        role_login={
            "fa_migration": False,
            "fa_build": False,
            "fa_runtime": False,
        },
        vector_usable=True,
        pg_stat_statements_usable=True,
    )


def test_preflight_accepts_the_local_group_role_layout(
    valid_snapshot: PreflightSnapshot,
) -> None:
    report = validate_pre_migration_snapshot(valid_snapshot)

    assert report.permission_layout == "group_roles"


def test_logical_database_role_names_fit_the_ncp_user_id_limit() -> None:
    assert EXPECTED_ROLES == frozenset(
        {"fa_migration", "fa_build", "fa_runtime"}
    )
    assert all(len(name) <= 16 for name in EXPECTED_ROLES)


def test_preflight_accepts_the_ncp_direct_user_layout(
    valid_snapshot: PreflightSnapshot,
) -> None:
    snapshot = replace(
        valid_snapshot,
        role_login={name: True for name in valid_snapshot.role_login},
    )

    report = validate_pre_migration_snapshot(snapshot)

    assert report.permission_layout == "direct_users"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("postgres_major", 16, "DB_VERSION_MISMATCH"),
        ("server_encoding", "SQL_ASCII", "DB_ENCODING_MISMATCH"),
        ("timezone", "Asia/Seoul", "DB_TIMEZONE_MISMATCH"),
        ("search_path", '"$user", public', "DB_SEARCH_PATH_MISMATCH"),
    ),
)
def test_preflight_rejects_an_incompatible_database_session(
    valid_snapshot: PreflightSnapshot,
    field: str,
    value: object,
    code: str,
) -> None:
    with pytest.raises(PreflightFailure) as captured:
        validate_pre_migration_snapshot(
            replace(valid_snapshot, **{field: value})
        )

    assert captured.value.code == code


def test_preflight_rejects_a_missing_ncp_extension(
    valid_snapshot: PreflightSnapshot,
) -> None:
    snapshot = replace(valid_snapshot, extensions={"vector": "cdb_admin"})

    with pytest.raises(PreflightFailure) as captured:
        validate_pre_migration_snapshot(snapshot)

    assert captured.value.code == "MISSING_NCP_EXTENSION"


def test_preflight_rejects_an_extension_in_the_wrong_schema(
    valid_snapshot: PreflightSnapshot,
) -> None:
    snapshot = replace(
        valid_snapshot,
        extensions={
            "vector": "public",
            "pg_stat_statements": "cdb_admin",
        },
    )

    with pytest.raises(PreflightFailure) as captured:
        validate_pre_migration_snapshot(snapshot)

    assert captured.value.code == "NCP_EXTENSION_SCHEMA_MISMATCH"


@pytest.mark.parametrize(
    "field",
    ("vector_usable", "pg_stat_statements_usable"),
)
def test_preflight_rejects_an_unusable_ncp_extension(
    valid_snapshot: PreflightSnapshot,
    field: str,
) -> None:
    with pytest.raises(PreflightFailure) as captured:
        validate_pre_migration_snapshot(replace(valid_snapshot, **{field: False}))

    assert captured.value.code == "NCP_EXTENSION_UNUSABLE"


def test_preflight_rejects_a_missing_logical_role(
    valid_snapshot: PreflightSnapshot,
) -> None:
    roles = dict(valid_snapshot.role_login)
    roles.pop("fa_runtime")

    with pytest.raises(PreflightFailure) as captured:
        validate_pre_migration_snapshot(replace(valid_snapshot, role_login=roles))

    assert captured.value.code == "MISSING_DB_ROLE"


def test_preflight_rejects_a_mixed_role_layout(
    valid_snapshot: PreflightSnapshot,
) -> None:
    roles = dict(valid_snapshot.role_login)
    roles["fa_runtime"] = True

    with pytest.raises(PreflightFailure) as captured:
        validate_pre_migration_snapshot(replace(valid_snapshot, role_login=roles))

    assert captured.value.code == "DB_ROLE_LAYOUT_MISMATCH"


def test_preflight_normalizes_sqlalchemy_psycopg_urls() -> None:
    assert normalize_psycopg_url(
        "postgresql+psycopg://user:secret@db.invalid/financial_agent"
    ) == "postgresql://user:secret@db.invalid/financial_agent"


def test_preflight_reports_an_unreachable_database_without_leaking_its_url() -> None:
    url = "postgresql://secret_user:secret_password@127.0.0.1:1/secret_db"

    with pytest.raises(PreflightFailure) as captured:
        run_pre_migration_preflight(url, connect_timeout_seconds=1)

    assert captured.value.code == "DATABASE_UNREACHABLE"
    assert "secret_user" not in str(captured.value)
    assert "secret_password" not in str(captured.value)
    assert "secret_db" not in str(captured.value)


@pytest.mark.postgres
def test_local_postgres_exposes_the_ncp_compatible_preflight_layout(
    postgres_database_url: str,
) -> None:
    report = run_pre_migration_preflight(postgres_database_url)

    assert report.permission_layout == "group_roles"
