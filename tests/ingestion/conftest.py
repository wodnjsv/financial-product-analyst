from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def ingestion_migrated_database_url() -> Iterator[str]:
    database_url = os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail(
            "FINANCIAL_AGENT_TEST_DATABASE_URL is required for ingestion "
            "PostgreSQL tests"
        )

    previous_database_url = os.environ.pop("FINANCIAL_AGENT_DATABASE_URL", None)
    try:
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        yield database_url
    finally:
        if previous_database_url is not None:
            os.environ["FINANCIAL_AGENT_DATABASE_URL"] = previous_database_url


def _async_url(database_url: str) -> str:
    normalized = normalize_psycopg_url(database_url)
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    return normalized


def _role_engine(database_url: str, role: str | None) -> AsyncEngine:
    options = "-c timezone=UTC"
    if role is not None:
        options = f"-c role={role} {options}"
    return create_async_engine(
        _async_url(database_url),
        pool_size=5,
        max_overflow=0,
        connect_args={"options": options},
    )


@pytest_asyncio.fixture
async def ingestion_admin_engine(
    ingestion_migrated_database_url: str,
) -> AsyncIterator[AsyncEngine]:
    engine = _role_engine(ingestion_migrated_database_url, None)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def ingestion_build_engine(
    ingestion_migrated_database_url: str,
) -> AsyncIterator[AsyncEngine]:
    engine = _role_engine(ingestion_migrated_database_url, "fa_build")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def ingestion_runtime_engine(
    ingestion_migrated_database_url: str,
) -> AsyncIterator[AsyncEngine]:
    engine = _role_engine(ingestion_migrated_database_url, "fa_runtime")
    yield engine
    await engine.dispose()
