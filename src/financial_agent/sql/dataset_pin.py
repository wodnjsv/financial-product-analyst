"""Check live dataset metadata inside the caller's read-only transaction."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection


class DatasetPinChanged(ValueError):
    code = "DATASET_PIN_CHANGED"


async def assert_dataset_pin(
    connection: AsyncConnection,
    dataset_version: str,
    manifest_hash: str,
    cutoff_date: date,
) -> None:
    result = await connection.execute(
        sa.text(
            "SELECT dataset_version, manifest_hash, cutoff_date "
            "FROM operations.dataset_version "
            "WHERE dataset_version = :dataset_version"
        ),
        {"dataset_version": dataset_version},
    )
    row = result.mappings().one_or_none()
    if (
        row is None
        or not manifest_hash
        or row.get("dataset_version") != dataset_version
        or row.get("manifest_hash") != manifest_hash
        or type(row.get("cutoff_date")) is not date
        or row.get("cutoff_date") != cutoff_date
    ):
        raise DatasetPinChanged(DatasetPinChanged.code)
