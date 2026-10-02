"""Measured capacity guards for the explicitly isolated personal database."""

from dataclasses import dataclass
from pathlib import Path
import shutil

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from .writer import DatasetBuildWriter


def require_local_target(url: str) -> None:
    target = make_url(url)
    if (
        target.get_backend_name() != "postgresql"
        or target.host not in {"localhost", "127.0.0.1", "::1"}
        or target.database != "financial_agent_local"
        or target.query
    ):
        raise ValueError("LOCAL_DATABASE_TARGET_REQUIRED")


@dataclass(frozen=True)
class StorageBudget:
    initial_free_bytes: int
    database_limit_bytes: int = 18_000_000_000
    disk_growth_limit_bytes: int = 30_000_000_000
    minimum_free_bytes: int = 10 * 1024**3
    batch_headroom_bytes: int = 2_000_000_000

    def check(self, database_bytes: int, free_bytes: int) -> None:
        if database_bytes + self.batch_headroom_bytes > self.database_limit_bytes:
            raise RuntimeError("LOCAL_DATABASE_BUDGET_REACHED")
        if free_bytes - self.batch_headroom_bytes < self.minimum_free_bytes:
            raise RuntimeError("LOCAL_FREE_SPACE_RESERVE_REACHED")
        if (
            self.initial_free_bytes - free_bytes + self.batch_headroom_bytes
            > self.disk_growth_limit_bytes
        ):
            raise RuntimeError("LOCAL_DISK_GROWTH_BUDGET_REACHED")


class BudgetedWriter(DatasetBuildWriter):
    def __init__(self, engine, budget: StorageBudget, disk_path: Path):
        super().__init__(engine)
        self.budget = budget
        self.disk_path = disk_path
        self.rows_written = 0

    async def check_capacity(self) -> dict[str, int]:
        async with self._engine.connect() as connection:
            size = int(await connection.scalar(sa.text(
                "SELECT pg_database_size(current_database())"
            )))
        free = shutil.disk_usage(self.disk_path).free
        self.budget.check(size, free)
        return {"database_bytes": size, "free_bytes": free}

    async def write_rows(self, dataset_version_value, rows):
        await self.check_capacity()
        await super().write_rows(dataset_version_value, rows)
        self.rows_written += len(rows)
        sizes = await self.check_capacity()
        print({"mapped_rows_written": self.rows_written, **sizes}, flush=True)
