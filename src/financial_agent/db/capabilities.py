from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

import psycopg
from psycopg import sql

from .preflight import normalize_psycopg_url


PermissionLayout = Literal["group_roles", "direct_users"]


class CapabilityProbeFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    create_nologin_role: bool
    drop_role: bool
    create_schema: bool
    transfer_schema_owner: bool
    create_security_definer: bool
    grant_revoke: bool
    manage_role_membership: bool


def choose_permission_layout(
    capabilities: CapabilityResult,
) -> PermissionLayout:
    core_capabilities = (
        capabilities.create_schema,
        capabilities.create_security_definer,
        capabilities.grant_revoke,
    )
    if not all(core_capabilities):
        raise CapabilityProbeFailure(
            "NCP_CAPABILITY_INSUFFICIENT",
            "database user lacks a required migration capability",
        )
    role_capabilities = (
        capabilities.create_nologin_role,
        capabilities.drop_role,
        capabilities.transfer_schema_owner,
        capabilities.manage_role_membership,
    )
    return "group_roles" if all(role_capabilities) else "direct_users"


def _attempt(
    connection: psycopg.Connection,
    operation: Callable[[], None],
) -> bool:
    try:
        with connection.transaction():
            operation()
        return True
    except psycopg.Error:
        return False


def _run_capability_probe(connection: psycopg.Connection) -> CapabilityResult:
    token = uuid.uuid4().hex[:16]
    role_name = f"fa_probe_role_{token}"
    schema_name = f"fa_probe_schema_{token}"
    function_name = "probe_security_definer"

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        current_user = str(cursor.fetchone()[0])

    create_role = _attempt(
        connection,
        lambda: connection.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role_name))
        ),
    )
    create_schema = _attempt(
        connection,
        lambda: connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        ),
    )

    def create_function() -> None:
        connection.execute(
            sql.SQL(
                """
                CREATE FUNCTION {}.{}() RETURNS integer
                LANGUAGE sql
                SECURITY DEFINER
                SET search_path = pg_catalog, pg_temp
                AS 'SELECT 1'
                """
            ).format(
                sql.Identifier(schema_name),
                sql.Identifier(function_name),
            )
        )

    create_security_definer = create_schema and _attempt(
        connection,
        create_function,
    )

    def exercise_grants() -> None:
        function = sql.SQL("{}.{}()").format(
            sql.Identifier(schema_name),
            sql.Identifier(function_name),
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON FUNCTION {} FROM PUBLIC").format(function)
        )
        connection.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {} TO PUBLIC").format(function)
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON FUNCTION {} FROM PUBLIC").format(function)
        )

    grant_revoke = create_security_definer and _attempt(
        connection,
        exercise_grants,
    )

    def grant_membership() -> None:
        connection.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(role_name),
                sql.Identifier(current_user),
            )
        )

    manage_membership = create_role and _attempt(connection, grant_membership)

    def transfer_schema_owner() -> None:
        connection.execute(
            sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(
                sql.Identifier(schema_name),
                sql.Identifier(role_name),
            )
        )
        connection.execute(
            sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(
                sql.Identifier(schema_name),
                sql.Identifier(current_user),
            )
        )

    transfer_owner = (
        create_schema
        and manage_membership
        and _attempt(connection, transfer_schema_owner)
    )

    def revoke_membership_and_drop_role() -> None:
        connection.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(role_name),
                sql.Identifier(current_user),
            )
        )
        connection.execute(
            sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name))
        )

    drop_role = (
        create_role
        and manage_membership
        and _attempt(connection, revoke_membership_and_drop_role)
    )

    return CapabilityResult(
        create_nologin_role=create_role,
        drop_role=drop_role,
        create_schema=create_schema,
        transfer_schema_owner=transfer_owner,
        create_security_definer=create_security_definer,
        grant_revoke=grant_revoke,
        manage_role_membership=manage_membership,
    )


def probe_ncp_capabilities(
    url: str,
    *,
    connect_timeout_seconds: int = 5,
) -> CapabilityResult:
    try:
        with psycopg.connect(
            normalize_psycopg_url(url),
            connect_timeout=connect_timeout_seconds,
        ) as connection:
            try:
                capabilities = _run_capability_probe(connection)
            finally:
                connection.rollback()
    except psycopg.OperationalError as error:
        raise CapabilityProbeFailure(
            "DATABASE_UNREACHABLE",
            "database connection failed",
        ) from error
    except psycopg.Error as error:
        raise CapabilityProbeFailure(
            "NCP_CAPABILITY_PROBE_FAILED",
            "database capability probe failed",
        ) from error
    choose_permission_layout(capabilities)
    return capabilities


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
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
        capabilities = probe_ncp_capabilities(url)
        permission_layout = choose_permission_layout(capabilities)
    except CapabilityProbeFailure as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    result = {**asdict(capabilities), "permission_layout": permission_layout}
    print(json.dumps(result, sort_keys=True))
    return 0
