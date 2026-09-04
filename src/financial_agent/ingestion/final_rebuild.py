from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.db.metadata import metadata
from financial_agent.db.schema import (
    catalog,
    document,
    evidence,
    observation,
    operations,
    relation,
    search,
)


del catalog, document, evidence, observation, relation, search

FINAL_DATASET_VERSION = "competition-2026-08-24-final-v1"


class FinalRebuildError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class IncompleteDatasetCleanupReport:
    dataset_version: str
    deleted_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "deleted_counts",
            MappingProxyType(dict(sorted(self.deleted_counts.items()))),
        )


async def remove_incomplete_final_dataset(
    engine: AsyncEngine,
    *,
    dataset_version: str,
) -> IncompleteDatasetCleanupReport:
    if dataset_version != FINAL_DATASET_VERSION:
        raise FinalRebuildError("TARGET_VERSION_NOT_ALLOWED")

    try:
        async with engine.begin() as connection:
            target = (
                await connection.execute(
                    sa.select(
                        operations.dataset_version.c.status,
                    )
                    .where(
                        operations.dataset_version.c.dataset_version
                        == dataset_version
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if target is None:
                raise FinalRebuildError("TARGET_NOT_FOUND")
            if target.status != "building":
                raise FinalRebuildError("TARGET_NOT_BUILDING")

            is_active = (
                await connection.execute(
                    sa.select(sa.literal(True)).where(
                        sa.exists(
                            sa.select(1)
                            .select_from(operations.active_dataset)
                            .where(
                                operations.active_dataset.c.dataset_version
                                == dataset_version
                            )
                        )
                    )
                )
            ).scalar_one_or_none()
            if is_active:
                raise FinalRebuildError("TARGET_IS_ACTIVE")

            has_successful_validation = (
                await connection.execute(
                    sa.select(sa.literal(True)).where(
                        sa.exists(
                            sa.select(1)
                            .select_from(operations.dataset_validation_run)
                            .where(
                                operations.dataset_validation_run.c.dataset_version
                                == dataset_version,
                                operations.dataset_validation_run.c.status == "pass",
                            )
                        )
                    )
                )
            ).scalar_one_or_none()
            if has_successful_validation:
                raise FinalRebuildError("TARGET_HAS_SUCCESSFUL_VALIDATION")

            await connection.execute(
                sa.text("SET LOCAL session_replication_role = replica")
            )
            deleted_counts: dict[str, int] = {}
            target_table = operations.dataset_version
            scoped_tables = [
                table
                for table in reversed(metadata.sorted_tables)
                if table is not target_table and "dataset_version" in table.c
            ]
            for table in scoped_tables:
                result = await connection.execute(
                    sa.delete(table).where(table.c.dataset_version == dataset_version)
                )
                if result.rowcount:
                    deleted_counts[table.fullname] = result.rowcount

            result = await connection.execute(
                sa.delete(target_table).where(
                    target_table.c.dataset_version == dataset_version
                )
            )
            if result.rowcount != 1:
                raise FinalRebuildError("TARGET_DELETE_CONFLICT")
            deleted_counts[target_table.fullname] = result.rowcount

            for table in scoped_tables:
                remaining = (
                    await connection.execute(
                        sa.select(sa.func.count())
                        .select_from(table)
                        .where(table.c.dataset_version == dataset_version)
                    )
                ).scalar_one()
                if remaining:
                    raise FinalRebuildError("TARGET_DELETE_INCOMPLETE")
    except IntegrityError as error:
        raise FinalRebuildError("TARGET_STILL_REFERENCED") from error

    return IncompleteDatasetCleanupReport(dataset_version, deleted_counts)
