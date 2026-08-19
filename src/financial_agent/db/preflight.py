from __future__ import annotations

import argparse
import os
import json
from pathlib import Path
import sys
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Literal, Mapping

import psycopg


EXPECTED_SEARCH_PATH = '"$user", public, cdb_admin'
EXPECTED_EXTENSIONS = {
    "vector": "cdb_admin",
    "pg_stat_statements": "cdb_admin",
}
EXPECTED_APPLICATION_SCHEMAS = frozenset(
    {
        "catalog",
        "observation",
        "relation",
        "document",
        "search",
        "evidence",
        "operations",
    }
)
EXPECTED_ROLES = frozenset(
    {
        "fa_migration",
        "fa_build",
        "fa_runtime",
    }
)

PermissionLayout = Literal["group_roles", "direct_users"]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_OBJECT_MANIFEST = (
    PROJECT_ROOT / "schemas" / "postgresql" / "v1" / "database-objects.json"
)


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


@dataclass(frozen=True, slots=True)
class PostMigrationSnapshot:
    pre_migration: PreflightSnapshot
    extension_versions: Mapping[str, str]
    application_schemas: frozenset[str]
    alembic_revision: str | None
    alembic_head: str
    cutoff_constraint_matches: bool
    active_dataset_consistent: bool
    parameterized_query_usable: bool
    public_tables: frozenset[str]
    database_permissions_match: bool
    object_manifest_matches: bool
    permission_manifest_matches: bool


@dataclass(frozen=True, slots=True)
class DatabaseObjectComparison:
    object_drift: bool
    permission_drift: bool
    changed_sections: tuple[str, ...]


_PERMISSION_MANIFEST_SECTIONS = frozenset(
    {"owners", "table_grants", "routine_grants", "schema_grants"}
)


def compare_database_object_manifests(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> DatabaseObjectComparison:
    section_names = tuple(
        dict.fromkeys((*expected.keys(), *actual.keys()))
    )
    changed_sections = tuple(
        section
        for section in section_names
        if expected.get(section) != actual.get(section)
    )
    return DatabaseObjectComparison(
        object_drift=any(
            section not in _PERMISSION_MANIFEST_SECTIONS
            for section in changed_sections
        ),
        permission_drift=any(
            section in _PERMISSION_MANIFEST_SECTIONS
            for section in changed_sections
        ),
        changed_sections=changed_sections,
    )


def _normalize_sql(definition: str) -> str:
    return "\n".join(
        line.rstrip()
        for line in definition.replace("\r\n", "\n").strip().split("\n")
    )


def _normalize_owner(owner: str) -> str:
    if owner in EXPECTED_ROLES:
        return owner
    return "__environment_owner__"


def _sorted_manifest_entries(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda item: tuple(str(value) for value in item.values()),
    )


def collect_database_objects(
    connection: psycopg.Connection,
) -> dict[str, Any]:
    schemas = sorted(EXPECTED_APPLICATION_SCHEMAS)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                namespace.nspname,
                procedure.proname,
                pg_catalog.pg_get_function_identity_arguments(procedure.oid),
                pg_catalog.pg_get_functiondef(procedure.oid),
                COALESCE(procedure.proconfig, ARRAY[]::text[]),
                owner.rolname
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            JOIN pg_catalog.pg_roles AS owner
              ON owner.oid = procedure.proowner
            WHERE namespace.nspname = ANY(%s)
            ORDER BY namespace.nspname, procedure.proname,
                     pg_catalog.pg_get_function_identity_arguments(procedure.oid)
            """,
            (schemas,),
        )
        function_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                namespace.nspname,
                relation.relname,
                pg_catalog.pg_get_viewdef(relation.oid, true),
                owner.rolname
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles AS owner
              ON owner.oid = relation.relowner
            WHERE namespace.nspname = ANY(%s)
              AND relation.relkind IN ('v', 'm')
            ORDER BY namespace.nspname, relation.relname
            """,
            (schemas,),
        )
        view_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                namespace.nspname,
                relation.relname,
                trigger.tgname,
                pg_catalog.pg_get_triggerdef(trigger.oid, true)
            FROM pg_catalog.pg_trigger AS trigger
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = trigger.tgrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = ANY(%s)
              AND NOT trigger.tgisinternal
            ORDER BY namespace.nspname, relation.relname, trigger.tgname
            """,
            (schemas,),
        )
        trigger_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                namespace.nspname,
                relation.relname,
                constraint_record.conname,
                pg_catalog.pg_get_constraintdef(
                    constraint_record.oid, true
                )
            FROM pg_catalog.pg_constraint AS constraint_record
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = constraint_record.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = ANY(%s)
              AND constraint_record.contype = 'c'
            ORDER BY namespace.nspname, relation.relname,
                     constraint_record.conname
            """,
            (schemas,),
        )
        check_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                namespace.nspname,
                relation.relname,
                CASE relation.relkind
                    WHEN 'v' THEN 'view'
                    WHEN 'm' THEN 'materialized_view'
                    WHEN 'S' THEN 'sequence'
                    ELSE 'table'
                END,
                owner.rolname
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles AS owner
              ON owner.oid = relation.relowner
            WHERE namespace.nspname = ANY(%s)
              AND relation.relkind IN ('r', 'p', 'v', 'm', 'S')
            ORDER BY namespace.nspname, relation.relname
            """,
            (schemas,),
        )
        relation_owner_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                namespace.nspname,
                relation.relname,
                COALESCE(grantee.rolname, 'PUBLIC'),
                acl.privilege_type,
                acl.is_grantable
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    relation.relacl,
                    pg_catalog.acldefault(
                        CASE relation.relkind
                            WHEN 'S' THEN 'S'::"char"
                            ELSE 'r'::"char"
                        END,
                        relation.relowner
                    )
                )
            ) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee
              ON grantee.oid = acl.grantee
            WHERE namespace.nspname = ANY(%s)
              AND relation.relkind IN ('r', 'p', 'v', 'm', 'S')
              AND (
                  acl.grantee = 0
                  OR grantee.rolname = ANY(%s)
              )
            ORDER BY namespace.nspname, relation.relname,
                     COALESCE(grantee.rolname, 'PUBLIC'),
                     acl.privilege_type
            """,
            (schemas, sorted(EXPECTED_ROLES)),
        )
        table_grant_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                namespace.nspname,
                procedure.proname,
                pg_catalog.pg_get_function_identity_arguments(procedure.oid),
                COALESCE(grantee.rolname, 'PUBLIC'),
                acl.privilege_type,
                acl.is_grantable
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    procedure.proacl,
                    pg_catalog.acldefault('f', procedure.proowner)
                )
            ) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee
              ON grantee.oid = acl.grantee
            WHERE namespace.nspname = ANY(%s)
              AND (
                  acl.grantee = 0
                  OR grantee.rolname = ANY(%s)
              )
            ORDER BY namespace.nspname, procedure.proname,
                     pg_catalog.pg_get_function_identity_arguments(procedure.oid),
                     COALESCE(grantee.rolname, 'PUBLIC'),
                     acl.privilege_type
            """,
            (schemas, sorted(EXPECTED_ROLES)),
        )
        routine_grant_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                namespace.nspname,
                COALESCE(grantee.rolname, 'PUBLIC'),
                acl.privilege_type,
                acl.is_grantable
            FROM pg_catalog.pg_namespace AS namespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    namespace.nspacl,
                    pg_catalog.acldefault('n', namespace.nspowner)
                )
            ) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee
              ON grantee.oid = acl.grantee
            WHERE namespace.nspname = ANY(%s)
              AND (
                  acl.grantee = 0
                  OR grantee.rolname = ANY(%s)
              )
            ORDER BY namespace.nspname,
                     COALESCE(grantee.rolname, 'PUBLIC'),
                     acl.privilege_type
            """,
            (schemas, sorted(EXPECTED_ROLES)),
        )
        schema_grant_rows = cursor.fetchall()

    functions = [
        {
            "schema": str(schema),
            "name": str(name),
            "identity_arguments": str(arguments),
            "definition": _normalize_sql(str(definition)),
            "configuration": sorted(str(setting) for setting in configuration),
        }
        for schema, name, arguments, definition, configuration, _owner
        in function_rows
    ]
    views = [
        {
            "schema": str(schema),
            "name": str(name),
            "definition": _normalize_sql(str(definition)),
        }
        for schema, name, definition, _owner in view_rows
    ]
    triggers = [
        {
            "schema": str(schema),
            "table": str(table),
            "name": str(name),
            "definition": _normalize_sql(str(definition)),
        }
        for schema, table, name, definition in trigger_rows
    ]
    checks = [
        {
            "schema": str(schema),
            "table": str(table),
            "name": str(name),
            "definition": _normalize_sql(str(definition)),
        }
        for schema, table, name, definition in check_rows
    ]
    owners = [
        {
            "object_type": "function",
            "schema": str(schema),
            "name": f"{name}({arguments})",
            "owner": _normalize_owner(str(owner)),
        }
        for schema, name, arguments, _definition, _configuration, owner
        in function_rows
    ] + [
        {
            "object_type": str(object_type),
            "schema": str(schema),
            "name": str(name),
            "owner": _normalize_owner(str(owner)),
        }
        for schema, name, object_type, owner in relation_owner_rows
    ]
    table_grants = [
        {
            "schema": str(schema),
            "name": str(name),
            "grantee": str(grantee),
            "privilege": str(privilege),
            "grantable": bool(grantable),
        }
        for schema, name, grantee, privilege, grantable in table_grant_rows
    ]
    routine_grants = [
        {
            "schema": str(schema),
            "name": str(name),
            "identity_arguments": str(arguments),
            "grantee": str(grantee),
            "privilege": str(privilege),
            "grantable": bool(grantable),
        }
        for schema, name, arguments, grantee, privilege, grantable
        in routine_grant_rows
    ]
    schema_grants = [
        {
            "schema": str(schema),
            "grantee": str(grantee),
            "privilege": str(privilege),
            "grantable": bool(grantable),
        }
        for schema, grantee, privilege, grantable in schema_grant_rows
    ]
    return {
        "manifest_version": 1,
        "functions": _sorted_manifest_entries(functions),
        "views": _sorted_manifest_entries(views),
        "triggers": _sorted_manifest_entries(triggers),
        "checks": _sorted_manifest_entries(checks),
        "owners": _sorted_manifest_entries(owners),
        "table_grants": _sorted_manifest_entries(table_grants),
        "routine_grants": _sorted_manifest_entries(routine_grants),
        "schema_grants": _sorted_manifest_entries(schema_grants),
    }


def validate_post_migration_snapshot(
    snapshot: PostMigrationSnapshot,
) -> PreflightReport:
    report = validate_pre_migration_snapshot(snapshot.pre_migration)
    if EXPECTED_EXTENSIONS.keys() - snapshot.extension_versions.keys() or any(
        not snapshot.extension_versions[name]
        for name in EXPECTED_EXTENSIONS
        if name in snapshot.extension_versions
    ):
        raise PreflightFailure(
            "MISSING_NCP_EXTENSION",
            "required NCP-managed extension version is unavailable",
        )
    if (
        snapshot.application_schemas != EXPECTED_APPLICATION_SCHEMAS
        or snapshot.alembic_revision != snapshot.alembic_head
        or snapshot.public_tables != frozenset({"alembic_version"})
    ):
        raise PreflightFailure(
            "MIGRATION_BEHIND",
            "database objects do not match the Alembic head",
        )
    if (
        not snapshot.cutoff_constraint_matches
        or not snapshot.active_dataset_consistent
    ):
        raise PreflightFailure(
            "ACTIVE_DATASET_INCONSISTENT",
            "dataset cutoff or active-dataset state is inconsistent",
        )
    if not snapshot.parameterized_query_usable:
        raise PreflightFailure(
            "DATABASE_QUERY_FAILED",
            "parameterized query and rollback probe failed",
        )
    if not snapshot.object_manifest_matches:
        raise PreflightFailure(
            "OBJECT_DEFINITION_DRIFT",
            "database object definitions differ from the reviewed manifest",
        )
    if (
        not snapshot.database_permissions_match
        or not snapshot.permission_manifest_matches
    ):
        raise PreflightFailure(
            "DATABASE_PERMISSION_DRIFT",
            "database permissions differ from the reviewed baseline",
        )
    return report


def _expected_alembic_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(PROJECT_ROOT / "alembic.ini")
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise PreflightFailure(
            "MIGRATION_BEHIND",
            "exactly one Alembic head is required",
        )
    return str(heads[0])


def _parameterized_query_is_usable(
    connection: psycopg.Connection,
) -> bool:
    try:
        with connection.transaction(force_rollback=True):
            value = connection.execute(
                "SELECT %s::integer",
                (1,),
            ).fetchone()[0]
        return value == 1
    except psycopg.Error:
        return False


def _database_permissions_match(
    connection: psycopg.Connection,
    *,
    permission_layout: PermissionLayout,
) -> bool:
    protected_tables = (
        "operations.dataset_readiness",
        "operations.active_dataset",
        "operations.request_run",
        "operations.request_subtask",
        "operations.request_artifact",
        "operations.artifact_evidence_ref",
        "operations.artifact_calculation_ref",
        "operations.artifact_claim_ref",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_catalog.bool_and(
                pg_catalog.to_regclass(table_name) IS NOT NULL
            )
            FROM unnest(%s::text[]) AS table_name
            """,
            (list(protected_tables),),
        )
        if not bool(cursor.fetchone()[0]):
            return False
        cursor.execute(
            """
            SELECT NOT EXISTS (
                SELECT 1
                FROM unnest(%s::text[]) AS role_name
                CROSS JOIN unnest(%s::text[]) AS schema_name
                WHERE pg_catalog.has_schema_privilege(
                    role_name, schema_name, 'CREATE'
                )
            )
            """,
            (
                ["fa_build", "fa_runtime"],
                sorted(EXPECTED_APPLICATION_SCHEMAS),
            ),
        )
        schemas_are_protected = bool(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT NOT EXISTS (
                SELECT 1
                FROM unnest(%s::text[]) AS role_name
                CROSS JOIN unnest(%s::text[]) AS table_name
                CROSS JOIN unnest(%s::text[]) AS privilege_name
                WHERE pg_catalog.has_table_privilege(
                    role_name, table_name, privilege_name
                )
            )
            """,
            (
                ["fa_build", "fa_runtime"],
                list(protected_tables),
                ["INSERT", "UPDATE", "DELETE", "TRUNCATE"],
            ),
        )
        protected_dml_is_denied = bool(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT
                granted_role.rolname,
                granted_role.rolcanlogin,
                member_role.rolname,
                member_role.rolcanlogin,
                membership.admin_option
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted_role
              ON granted_role.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member_role
              ON member_role.oid = membership.member
            WHERE granted_role.rolname = ANY(%s)
               OR member_role.rolname = ANY(%s)
            """,
            (sorted(EXPECTED_ROLES), sorted(EXPECTED_ROLES)),
        )
        membership_rows = cursor.fetchall()
        if permission_layout == "direct_users":
            memberships_are_approved = not membership_rows
        else:
            memberships_are_approved = all(
                str(granted_role) in EXPECTED_ROLES
                and not bool(granted_can_login)
                and str(member_role) not in EXPECTED_ROLES
                and bool(member_can_login)
                and not bool(admin_option)
                for (
                    granted_role,
                    granted_can_login,
                    member_role,
                    member_can_login,
                    admin_option,
                ) in membership_rows
            )
    return (
        schemas_are_protected
        and protected_dml_is_denied
        and memberships_are_approved
    )


def collect_post_migration_snapshot(
    connection: psycopg.Connection,
    *,
    manifest_path: Path,
    alembic_head: str,
) -> PostMigrationSnapshot:
    pre_migration = collect_preflight_snapshot(connection)
    login_values = {
        pre_migration.role_login.get(role_name)
        for role_name in EXPECTED_ROLES
    }
    permission_layout: PermissionLayout = (
        "direct_users" if login_values == {True} else "group_roles"
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT extension.extname, extension.extversion
            FROM pg_catalog.pg_extension AS extension
            WHERE extension.extname IN ('vector', 'pg_stat_statements')
            ORDER BY extension.extname
            """
        )
        extension_versions = {
            str(name): str(version) for name, version in cursor.fetchall()
        }
        cursor.execute(
            """
            SELECT namespace.nspname
            FROM pg_catalog.pg_namespace AS namespace
            WHERE namespace.nspname = ANY(%s)
            ORDER BY namespace.nspname
            """,
            (sorted(EXPECTED_APPLICATION_SCHEMAS),),
        )
        application_schemas = frozenset(
            str(row[0]) for row in cursor.fetchall()
        )
        cursor.execute(
            "SELECT pg_catalog.to_regclass('public.alembic_version')"
        )
        if cursor.fetchone()[0] is not None:
            cursor.execute("SELECT version_num FROM public.alembic_version")
            revision_rows = cursor.fetchall()
            alembic_revision = (
                str(revision_rows[0][0]) if len(revision_rows) == 1 else None
            )
        else:
            alembic_revision = None
        cursor.execute(
            """
            SELECT pg_catalog.pg_get_constraintdef(constraint_record.oid, true)
            FROM pg_catalog.pg_constraint AS constraint_record
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = constraint_record.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'operations'
              AND relation.relname = 'dataset_version'
              AND constraint_record.conname = 'ck_dataset_version_cutoff_date'
            """
        )
        cutoff_row = cursor.fetchone()
        cutoff_constraint_matches = bool(
            cutoff_row
            and "cutoff_date = '2026-07-11'::date" in str(cutoff_row[0])
        )
        cursor.execute(
            """
            SELECT pg_catalog.bool_and(
                pg_catalog.to_regclass(table_name) IS NOT NULL
            )
            FROM unnest(%s::text[]) AS table_name
            """,
            (
                [
                    "operations.active_dataset",
                    "operations.dataset_version",
                    "operations.dataset_readiness",
                ],
            ),
        )
        if bool(cursor.fetchone()[0]):
            cursor.execute(
                """
                SELECT
                    NOT EXISTS (
                        SELECT 1
                        FROM operations.active_dataset AS active
                        LEFT JOIN operations.dataset_version AS dataset
                          ON dataset.dataset_version = active.dataset_version
                        WHERE active.dataset_version IS NOT NULL
                          AND (
                              dataset.status IS DISTINCT FROM 'active'
                              OR (
                                  SELECT count(DISTINCT readiness.component)
                                  FROM operations.dataset_readiness AS readiness
                                  WHERE readiness.dataset_version
                                      = active.dataset_version
                                    AND readiness.validation_status = 'pass'
                                    AND readiness.dataset_manifest_hash
                                        = dataset.manifest_hash
                                    AND readiness.component IN (
                                        'postgres', 'graph', 'vector', 'evidence'
                                    )
                              ) <> 4
                          )
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM operations.dataset_version AS dataset
                        WHERE dataset.status = 'active'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM operations.active_dataset AS active
                              WHERE active.dataset_version
                                  = dataset.dataset_version
                          )
                    )
                """
            )
            active_dataset_consistent = bool(cursor.fetchone()[0])
        else:
            active_dataset_consistent = False
        cursor.execute(
            """
            SELECT relation.relname
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p')
            ORDER BY relation.relname
            """
        )
        public_tables = frozenset(str(row[0]) for row in cursor.fetchall())

    try:
        expected_manifest = json.loads(manifest_path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        expected_manifest = {}
    actual_manifest = collect_database_objects(connection)
    comparison = compare_database_object_manifests(
        expected_manifest,
        actual_manifest,
    )
    required_roles_present = EXPECTED_ROLES <= pre_migration.role_login.keys()
    return PostMigrationSnapshot(
        pre_migration=pre_migration,
        extension_versions=extension_versions,
        application_schemas=application_schemas,
        alembic_revision=alembic_revision,
        alembic_head=alembic_head,
        cutoff_constraint_matches=cutoff_constraint_matches,
        active_dataset_consistent=active_dataset_consistent,
        parameterized_query_usable=_parameterized_query_is_usable(connection),
        public_tables=public_tables,
        database_permissions_match=(
            required_roles_present
            and _database_permissions_match(
                connection,
                permission_layout=permission_layout,
            )
        ),
        object_manifest_matches=not comparison.object_drift,
        permission_manifest_matches=not comparison.permission_drift,
    )


def run_post_migration_preflight(
    url: str,
    *,
    manifest_path: Path = DEFAULT_DATABASE_OBJECT_MANIFEST,
    connect_timeout_seconds: int = 5,
) -> PreflightReport:
    options = '-c timezone=UTC -c search_path="$user",public,cdb_admin'
    try:
        alembic_head = _expected_alembic_head()
        with psycopg.connect(
            normalize_psycopg_url(url),
            connect_timeout=connect_timeout_seconds,
            options=options,
            autocommit=True,
        ) as connection:
            snapshot = collect_post_migration_snapshot(
                connection,
                manifest_path=manifest_path,
                alembic_head=alembic_head,
            )
    except PreflightFailure:
        raise
    except psycopg.OperationalError:
        raise PreflightFailure(
            "DATABASE_UNREACHABLE",
            "database connection failed",
        ) from None
    except psycopg.Error:
        raise PreflightFailure(
            "DATABASE_QUERY_FAILED",
            "database post-migration preflight query failed",
        ) from None
    return validate_post_migration_snapshot(snapshot)


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
            "SELECT cdb_admin.vector_dims("
            "'[1,2,3]'::cdb_admin.vector(3)) = 3",
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
    except psycopg.OperationalError:
        raise PreflightFailure(
            "DATABASE_UNREACHABLE",
            "database connection failed",
        ) from None
    except psycopg.Error:
        raise PreflightFailure(
            "DATABASE_QUERY_FAILED",
            "database preflight query failed",
        ) from None
    return validate_pre_migration_snapshot(snapshot)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("pre-migration", "post-migration"),
        required=True,
    )
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
        if arguments.phase == "pre-migration":
            report = run_pre_migration_preflight(url)
        else:
            report = run_post_migration_preflight(url)
    except PreflightFailure as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    print(
        f"PREFLIGHT_OK phase={arguments.phase} "
        f"permission_layout={report.permission_layout}"
    )
    return 0
