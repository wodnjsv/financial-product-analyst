import pytest

from financial_agent.ingestion.local_budget import StorageBudget, require_local_target


def test_small_build_fits_without_filling_budget():
    StorageBudget(43 * 1024**3).check(7_000_000_000, 35 * 1024**3)


@pytest.mark.parametrize("size,free,reason", [
    (17_000_000_000, 30 * 1024**3, "DATABASE_BUDGET"),
    (5_000_000_000, 11 * 1024**3, "FREE_SPACE"),
    (5_000_000_000, 40 * 1024**3 - 29_000_000_000, "DISK_GROWTH"),
])
def test_stops_before_the_next_batch_exhausts_budget(size, free, reason):
    with pytest.raises(RuntimeError, match=reason):
        StorageBudget(40 * 1024**3).check(size, free)


@pytest.mark.parametrize("url", [
    "postgresql://localhost/palantiny_db",
    "postgresql://remote/financial_agent_local",
    "postgresql://localhost/financial_agent_local?host=remote",
    "sqlite:///financial_agent_local",
])
def test_rejects_other_targets(url):
    with pytest.raises(ValueError, match="LOCAL_DATABASE_TARGET"):
        require_local_target(url)


def test_accepts_the_approved_database():
    require_local_target("postgresql+psycopg://localhost/financial_agent_local")


@pytest.mark.asyncio
async def test_capacity_failure_prevents_database_mutation(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    from financial_agent.ingestion.local_budget import BudgetedWriter
    from financial_agent.ingestion.writer import DatasetBuildWriter

    write = AsyncMock()
    monkeypatch.setattr(DatasetBuildWriter, "write_rows", write)
    writer = BudgetedWriter(None, StorageBudget(40 * 1024**3), tmp_path)
    monkeypatch.setattr(writer, "check_capacity", AsyncMock(
        side_effect=RuntimeError("LOCAL_FREE_SPACE_RESERVE_REACHED")))
    with pytest.raises(RuntimeError, match="FREE_SPACE"):
        await writer.write_rows("personal", ())
    write.assert_not_awaited()
