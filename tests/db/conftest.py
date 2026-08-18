from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def postgres_database_url() -> str:
    database_url = os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail(
            "FINANCIAL_AGENT_TEST_DATABASE_URL is required for @pytest.mark.postgres "
            "tests. Start docker/postgres.compose.yml or provide a dedicated "
            "non-production PostgreSQL 15 database URL."
        )
    return database_url


@pytest.fixture
def ncp_database_url() -> str:
    database_url = os.getenv("FINANCIAL_AGENT_NCP_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip(
            "FINANCIAL_AGENT_NCP_TEST_DATABASE_URL is not configured for the explicit "
            "NCP integration test."
        )
    return database_url


@pytest.fixture(scope="session")
def migrated_database_url(postgres_database_url: str) -> str:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_database_url)
    command.upgrade(config, "head")
    return postgres_database_url
