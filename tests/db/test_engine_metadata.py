from __future__ import annotations

import pytest

from financial_agent.db.config import DatabaseConfig
from financial_agent.db.engine import create_database_engine
from financial_agent.db.metadata import metadata
from financial_agent.db.schema.operations import dataset_version


@pytest.mark.asyncio
async def test_database_engine_uses_psycopg_and_the_bounded_pool() -> None:
    config = DatabaseConfig(
        url="postgresql://db_user:db_password@db.invalid/financial_agent"
    )

    engine = create_database_engine(config)
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 0
        assert engine.pool._timeout == 5
    finally:
        await engine.dispose()


def test_database_metadata_uses_deterministic_constraint_names() -> None:
    assert metadata.naming_convention == {
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }


def test_dataset_metadata_preserves_only_the_approved_cutoff_dates() -> None:
    cutoff_constraint = next(
        constraint
        for constraint in dataset_version.constraints
        if constraint.name == "ck_dataset_version_cutoff_date"
    )

    assert str(cutoff_constraint.sqltext) == (
        "cutoff_date IN (DATE '2026-07-11', DATE '2026-08-24')"
    )
