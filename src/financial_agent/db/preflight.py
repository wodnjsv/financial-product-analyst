from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Literal, Mapping

import psycopg


EXPECTED_SEARCH_PATH = '"$user", public, cdb_admin'
EXPECTED_EXTENSIONS = {
    "vector": "cdb_admin",
    "pg_stat_statements": "cdb_admin",
}
EXPECTED_ROLES = frozenset(
    {
        "fa_migration",
        "fa_build",
        "fa_runtime",
    }
)

PermissionLayout = Literal["group_roles", "direct_users"]


def _search_path_entries(search_path: str) -> tuple[str, ...]:
    return tuple(entry.strip() for entry in search_path.split(","))


class PreflightFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PreflightSnapshot:
    current_user: str
    postgres_major: int
    server_encoding: str
    timezone: str
    search_path: str
    extensions: Mapping[str, str]
    role_login: Mapping[str, bool]
    role_public_usage: Mapping[str, bool]
    role_public_create: Mapping[str, bool]
    role_cdb_admin_usage: Mapping[str, bool]
    role_pg_stat_statements_select: Mapping[str, bool]
    vector_usable: bool
    pg_stat_statements_usable: bool


@dataclass(frozen=True, slots=True)
class PreflightReport:
    permission_layout: PermissionLayout


def validate_pre_migration_snapshot(
    snapshot: PreflightSnapshot,
) -> PreflightReport:
    if snapshot.postgres_major != 15:
        raise PreflightFailure(
            "DB_VERSION_MISMATCH",
            "PostgreSQL major version must be 15",
        )
    if snapshot.server_encoding != "UTF8":
        raise PreflightFailure(
            "DB_ENCODING_MISMATCH",
            "PostgreSQL server encoding must be UTF8",
        )
    if snapshot.timezone != "UTC":
        raise PreflightFailure(
            "DB_TIMEZONE_MISMATCH",
            "PostgreSQL session timezone must be UTC",
        )
    if _search_path_entries(snapshot.search_path) != _search_path_entries(
        EXPECTED_SEARCH_PATH
    ):
        raise PreflightFailure(
            "DB_SEARCH_PATH_MISMATCH",
            "PostgreSQL session search path is incompatible",
        )

    missing_extensions = EXPECTED_EXTENSIONS.keys() - snapshot.extensions.keys()
    if missing_extensions:
        raise PreflightFailure(
            "MISSING_NCP_EXTENSION",
            "required NCP-managed extension is missing",
        )
    if any(
        snapshot.extensions[name] != schema
        for name, schema in EXPECTED_EXTENSIONS.items()
    ):
        raise PreflightFailure(
            "NCP_EXTENSION_SCHEMA_MISMATCH",
            "NCP-managed extension is installed in an incompatible schema",
        )
    if not snapshot.vector_usable or not snapshot.pg_stat_statements_usable:
        raise PreflightFailure(
            "NCP_EXTENSION_UNUSABLE",
            "NCP-managed extension is installed but unusable",
        )

    missing_roles = EXPECTED_ROLES - snapshot.role_login.keys()
    if missing_roles:
        raise PreflightFailure(
            "MISSING_DB_ROLE",
            "required logical database role is missing",
        )
    login_values = {snapshot.role_login[name] for name in EXPECTED_ROLES}
    if login_values == {False}:
        permission_layout: PermissionLayout = "group_roles"
    elif login_values == {True}:
        permission_layout = "direct_users"
    else:
        raise PreflightFailure(
            "DB_ROLE_LAYOUT_MISMATCH",
            "logical database roles mix incompatible login modes",
        )
    if (
        permission_layout == "direct_users"
        and snapshot.current_user != "fa_migration"
    ):
        raise PreflightFailure(
            "MIGRATION_IDENTITY_MISMATCH",
            "direct-user migrations must connect as fa_migration",
        )
    expected_public_usage = {name: True for name in EXPECTED_ROLES}
    expected_public_create = {
        "fa_migration": True,
        "fa_build": False,
        "fa_runtime": False,
    }
    if (
        snapshot.role_public_usage != expected_public_usage
        or snapshot.role_public_create != expected_public_create
    ):
        raise PreflightFailure(
            "PUBLIC_SCHEMA_PERMISSION_MISMATCH",
            "public schema privileges are incompatible",
        )
    expected_extension_access = {name: True for name in EXPECTED_ROLES}
    if (
        snapshot.role_cdb_admin_usage != expected_extension_access
        or snapshot.role_pg_stat_statements_select
        != expected_extension_access
    ):
        raise PreflightFailure(
            "NCP_EXTENSION_PERMISSION_MISMATCH",
            "NCP extension read privileges are incompatible",
        )
    return PreflightReport(permission_layout=permission_layout)


def normalize_psycopg_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


def _extension_is_usable(
    connection: psycopg.Connection,
    statement: str,
) -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute(statement)
        return True
    except psycopg.Error:
        return False


def collect_preflight_snapshot(
    connection: psycopg.Connection,
) -> PreflightSnapshot:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        current_user = str(cursor.fetchone()[0])
        cursor.execute("SHOW server_version_num")
        postgres_major = int(cursor.fetchone()[0]) // 10_000
        cursor.execute("SHOW server_encoding")
        server_encoding = str(cursor.fetchone()[0])
        cursor.execute("SHOW TimeZone")
        timezone = str(cursor.fetchone()[0])
        cursor.execute("SHOW search_path")
        search_path = str(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT extension.extname, namespace.nspname
            FROM pg_catalog.pg_extension AS extension
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = extension.extnamespace
            WHERE extension.extname IN ('vector', 'pg_stat_statements')
            """
        )
        extensions = {str(name): str(schema) for name, schema in cursor.fetchall()}
        cursor.execute(
            """
            SELECT rolname, rolcanlogin
            FROM pg_catalog.pg_roles
            WHERE rolname IN (
                'fa_migration',
                'fa_build',
                'fa_runtime'
            )
            """
        )
        role_login = {str(name): bool(can_login) for name, can_login in cursor.fetchall()}
        cursor.execute(
            """
            SELECT
                role_name,
                pg_catalog.has_schema_privilege(
                    role_name, 'public', 'USAGE'
                ),
                pg_catalog.has_schema_privilege(
                    role_name, 'public', 'CREATE'
                ),
                CASE
                    WHEN pg_catalog.to_regnamespace('cdb_admin') IS NULL
                    THEN false
                    ELSE pg_catalog.has_schema_privilege(
                        role_name, 'cdb_admin', 'USAGE'
                    )
                END,
                CASE
                    WHEN pg_catalog.to_regclass(
                        'cdb_admin.pg_stat_statements'
                    ) IS NULL
                    THEN false
                    ELSE pg_catalog.has_table_privilege(
                        role_name,
                        'cdb_admin.pg_stat_statements',
                        'SELECT'
                    )
                END
            FROM unnest(ARRAY[
                'fa_migration', 'fa_build', 'fa_runtime'
            ]) AS role_name
            WHERE role_name IN (
                SELECT role_record.rolname
                FROM pg_catalog.pg_roles AS role_record
            )
            """
        )
        permission_rows = cursor.fetchall()
        role_public_usage = {
            str(row[0]): bool(row[1]) for row in permission_rows
        }
        role_public_create = {
            str(row[0]): bool(row[2]) for row in permission_rows
        }
        role_cdb_admin_usage = {
            str(row[0]): bool(row[3]) for row in permission_rows
        }
        role_pg_stat_statements_select = {
            str(row[0]): bool(row[4]) for row in permission_rows
        }

    return PreflightSnapshot(
        current_user=current_user,
        postgres_major=postgres_major,
        server_encoding=server_encoding,
        timezone=timezone,
        search_path=search_path,
        extensions=extensions,
        role_login=role_login,
        role_public_usage=role_public_usage,
        role_public_create=role_public_create,
        role_cdb_admin_usage=role_cdb_admin_usage,
        role_pg_stat_statements_select=role_pg_stat_statements_select,
        vector_usable=_extension_is_usable(
            connection,
            "SELECT '[1,2,3]'::cdb_admin.vector(3)::text",
        ),
        pg_stat_statements_usable=_extension_is_usable(
            connection,
            "SELECT 1 FROM cdb_admin.pg_stat_statements LIMIT 1",
        ),
    )


def run_pre_migration_preflight(
    url: str,
    *,
    connect_timeout_seconds: int = 5,
) -> PreflightReport:
    options = '-c timezone=UTC -c search_path="$user",public,cdb_admin'
    try:
        with psycopg.connect(
            normalize_psycopg_url(url),
            connect_timeout=connect_timeout_seconds,
            options=options,
            autocommit=True,
        ) as connection:
            snapshot = collect_preflight_snapshot(connection)
    except psycopg.OperationalError as error:
        raise PreflightFailure(
            "DATABASE_UNREACHABLE",
            "database connection failed",
        ) from error
    except psycopg.Error as error:
        raise PreflightFailure(
            "DATABASE_QUERY_FAILED",
            "database preflight query failed",
        ) from error
    return validate_pre_migration_snapshot(snapshot)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("pre-migration",), required=True)
    parser.add_argument("--database-url-env", required=True)
    arguments = parser.parse_args(argv)

    url = os.environ.get(arguments.database_url_env)
    if not url:
        print(
            "MISSING_DATABASE_URL: requested environment variable is unset",
            file=sys.stderr,
        )
        return 2
    try:
        report = run_pre_migration_preflight(url)
    except PreflightFailure as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    print(f"PREFLIGHT_OK permission_layout={report.permission_layout}")
    return 0
