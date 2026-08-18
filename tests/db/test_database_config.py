from __future__ import annotations

import pytest

from financial_agent.db.config import (
    DatabaseConfig,
    DatabaseConfigurationError,
)


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINANCIAL_AGENT_DATABASE_URL", raising=False)

    with pytest.raises(
        DatabaseConfigurationError,
        match="FINANCIAL_AGENT_DATABASE_URL is required",
    ):
        DatabaseConfig.from_env()


@pytest.mark.parametrize(
    "url",
    (
        "sqlite:///financial-agent.db",
        "mysql+pymysql://user:secret@db.invalid/financial_agent",
        "https://db.invalid/financial_agent",
    ),
)
def test_database_config_rejects_non_postgresql_urls(url: str) -> None:
    with pytest.raises(
        DatabaseConfigurationError,
        match="database URL must use PostgreSQL",
    ):
        DatabaseConfig(url=url)


def test_database_config_hides_the_complete_url_and_credentials() -> None:
    url = (
        "postgresql+psycopg://db_login_credential:secret_credential"
        "@db.invalid/financial_agent"
    )

    rendered = repr(DatabaseConfig(url=url))

    assert url not in rendered
    assert "db_login_credential" not in rendered
    assert "secret_credential" not in rendered
    assert "db.invalid" not in rendered


def test_database_config_uses_the_approved_pool_and_session_defaults() -> None:
    config = DatabaseConfig(
        url="postgresql+psycopg://user:secret@db.invalid/financial_agent"
    )

    assert config.db_read_concurrency_limit == 4
    assert config.pool_size == 5
    assert config.max_overflow == 0
    assert config.pool_timeout_seconds > 0
    assert config.connect_timeout_seconds > 0
    assert config.statement_timeout_ms > 0
    assert config.search_path == '"$user", public, cdb_admin'


def test_database_config_rejects_a_pool_without_a_control_connection() -> None:
    with pytest.raises(
        DatabaseConfigurationError,
        match=r"pool_size must be at least db_read_concurrency_limit \+ 1",
    ):
        DatabaseConfig(
            url="postgresql+psycopg://user:secret@db.invalid/financial_agent",
            db_read_concurrency_limit=4,
            pool_size=4,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("db_read_concurrency_limit", 0),
        ("pool_size", 0),
        ("max_overflow", -1),
        ("pool_timeout_seconds", 0),
        ("connect_timeout_seconds", 0),
        ("statement_timeout_ms", 0),
    ),
)
def test_database_config_rejects_invalid_numeric_settings(
    field: str,
    value: int,
) -> None:
    kwargs = {
        "url": "postgresql+psycopg://user:secret@db.invalid/financial_agent",
        field: value,
    }

    with pytest.raises(DatabaseConfigurationError, match=field):
        DatabaseConfig(**kwargs)
