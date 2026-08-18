from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from financial_agent.db.config import DatabaseConfig
from financial_agent.db.metadata import metadata
from financial_agent.db.preflight import run_pre_migration_preflight
from financial_agent.db import schema as _schema  # noqa: F401


APPLICATION_SCHEMAS = {
    "catalog",
    "document",
    "evidence",
    "observation",
    "operations",
    "relation",
    "search",
}

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    url = os.environ.get("FINANCIAL_AGENT_DATABASE_URL")
    if url is None:
        url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("FINANCIAL_AGENT_DATABASE_URL is required")
    DatabaseConfig(url=url)
    return url


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],
) -> bool:
    if type_ == "schema":
        return name is None or name == "public" or name in APPLICATION_SCHEMAS
    schema_name = parent_names.get("schema_name")
    if schema_name in (None, "public"):
        if type_ == "table":
            return name == "alembic_version"
        return parent_names.get("table_name") == "alembic_version"
    return schema_name in APPLICATION_SCHEMAS


def run_migrations_offline() -> None:
    raise RuntimeError("offline migrations are not supported")


def run_migrations_online() -> None:
    url = _database_url()
    run_pre_migration_preflight(url)
    database_config = DatabaseConfig(url=url)
    compact_search_path = database_config.search_path.replace(" ", "")
    engine = create_engine(
        _sqlalchemy_url(url),
        poolclass=NullPool,
        connect_args={
            "application_name": database_config.application_name,
            "connect_timeout": database_config.connect_timeout_seconds,
            "options": (
                "-c timezone=UTC "
                f"-c statement_timeout={database_config.statement_timeout_ms} "
                f"-c search_path={compact_search_path}"
            ),
        },
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            compare_server_default=True,
            compare_type=True,
            include_name=_include_name,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
