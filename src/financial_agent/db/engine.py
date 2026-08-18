from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .config import DatabaseConfig


def create_database_engine(config: DatabaseConfig) -> AsyncEngine:
    url = config.url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    compact_search_path = config.search_path.replace(" ", "")
    options = (
        "-c timezone=UTC "
        f"-c statement_timeout={config.statement_timeout_ms} "
        f"-c search_path={compact_search_path}"
    )
    return create_async_engine(
        url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout_seconds,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": config.connect_timeout_seconds,
            "application_name": config.application_name,
            "options": options,
        },
    )
