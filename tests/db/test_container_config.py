from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker" / "postgres.compose.yml"
INIT_SQL = ROOT / "docker" / "initdb" / "001-ncp-extension-layout.sql"

POSTGRES_IMAGE = (
    "pgvector/pgvector:0.8.5-pg15-bookworm@"
    "sha256:cea4dd461a72371e7e98ebd7dfba976e14a7defec86aac13a1c555b4ce28509e"
)


def test_postgres_compose_pins_the_linux_amd64_image_and_local_port() -> None:
    compose = COMPOSE.read_text("utf-8")

    assert f"image: {POSTGRES_IMAGE}" in compose
    assert "platform: linux/amd64" in compose
    assert "shared_preload_libraries=pg_stat_statements" in compose
    assert '127.0.0.1:${FINANCIAL_AGENT_TEST_DB_PORT:-55432}:5432' in compose
    assert "pg_isready" in compose


def test_postgres_compose_mounts_only_the_ncp_layout_script_read_only() -> None:
    compose = COMPOSE.read_text("utf-8")

    assert (
        "./initdb/001-ncp-extension-layout.sql:"
        "/docker-entrypoint-initdb.d/001-ncp-extension-layout.sql:ro"
    ) in compose
    assert "/Users/" not in compose
    assert "${HOME}" not in compose


def test_local_init_models_the_ncp_extension_and_role_layout() -> None:
    init_sql = INIT_SQL.read_text("utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS cdb_admin" in init_sql
    assert "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA cdb_admin" in init_sql
    assert (
        "CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA cdb_admin"
        in init_sql
    )
    for role_name in (
        "financial_agent_migration",
        "financial_agent_build",
        "financial_agent_runtime",
    ):
        assert f"CREATE ROLE {role_name} NOLOGIN" in init_sql
