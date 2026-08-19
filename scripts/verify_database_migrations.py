from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import sys

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from financial_agent.db.preflight import (
    DEFAULT_DATABASE_OBJECT_MANIFEST,
    EXPECTED_APPLICATION_SCHEMAS,
    EXPECTED_EXTENSIONS,
    EXPECTED_ROLES,
    normalize_psycopg_url,
    run_post_migration_preflight,
    run_pre_migration_preflight,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATABASE_NAME = "financial_agent_test"
DISPOSABLE_DATABASE_NAME = "financial_agent_migration_cycle_test"
LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
        ncp_extensions_preserved = extensions == EXPECTED_EXTENSIONS
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


def verify_migration_cycle(source_url: str) -> MigrationVerificationReport:
    with disposable_migration_database(source_url) as disposable_url:
        config = migration_alembic_config(disposable_url)
        run_pre_migration_preflight(disposable_url)
        command.upgrade(config, "head")
        command.check(config)
        first_report = run_post_migration_preflight(
            disposable_url,
            manifest_path=DEFAULT_DATABASE_OBJECT_MANIFEST,
        )
        first_inventory = _collect_inventory(disposable_url)

        command.downgrade(config, "base")
        ncp_extensions_preserved, bootstrap_roles_preserved = (
            _verify_base_state(disposable_url)
        )

        command.upgrade(config, "head")
        command.check(config)
        second_report = run_post_migration_preflight(
            disposable_url,
            manifest_path=DEFAULT_DATABASE_OBJECT_MANIFEST,
        )
        second_inventory = _collect_inventory(disposable_url)
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
            alembic_head="0005",
            application_schema_count=len(EXPECTED_APPLICATION_SCHEMAS),
            object_counts=second_inventory,
            ncp_extensions_preserved=ncp_extensions_preserved,
            bootstrap_roles_preserved=bootstrap_roles_preserved,
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
