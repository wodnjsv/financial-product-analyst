from __future__ import annotations

import os

import pytest


@pytest.fixture
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
