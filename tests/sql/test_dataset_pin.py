from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from financial_agent.sql.dataset_pin import DatasetPinChanged, assert_dataset_pin

from .helpers import ACTIVE_DATASET


CUTOFF = date(2026, 8, 24)
PIN_ROW = {
    "dataset_version": ACTIVE_DATASET.dataset_version,
    "manifest_hash": ACTIVE_DATASET.manifest_hash,
    "cutoff_date": CUTOFF,
}


class RecordingConnection:
    def __init__(self, row):
        self.row = row
        self.executions = []

    async def execute(self, statement, parameters):
        self.executions.append((str(statement), parameters))
        return self

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ("building", "validated", "active"))
async def test_matches_live_pin_without_requiring_active_status(status) -> None:
    connection = RecordingConnection({**PIN_ROW, "status": status})

    await assert_dataset_pin(
        connection, ACTIVE_DATASET.dataset_version, ACTIVE_DATASET.manifest_hash, CUTOFF,
    )

    assert len(connection.executions) == 1
    statement, parameters = connection.executions[0]
    assert "FROM operations.dataset_version" in statement
    assert ":dataset_version" in statement
    assert ACTIVE_DATASET.dataset_version not in statement
    assert parameters == {"dataset_version": ACTIVE_DATASET.dataset_version}
    assert "status" not in statement


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    (
        None,
        {},
        {**PIN_ROW, "dataset_version": "another-dataset"},
        {**PIN_ROW, "manifest_hash": "f" * 64},
        {**PIN_ROW, "manifest_hash": None},
        {**PIN_ROW, "manifest_hash": ""},
        {**PIN_ROW, "cutoff_date": date(2026, 7, 11)},
        {**PIN_ROW, "cutoff_date": None},
        {**PIN_ROW, "cutoff_date": "2026-08-24"},
        {**PIN_ROW, "cutoff_date": datetime(2026, 8, 24, tzinfo=UTC)},
    ),
)
async def test_missing_or_changed_pin_fails_with_stable_code(row) -> None:
    connection = RecordingConnection(row)

    with pytest.raises(DatasetPinChanged, match="^DATASET_PIN_CHANGED$") as failure:
        await assert_dataset_pin(
            connection, ACTIVE_DATASET.dataset_version, ACTIVE_DATASET.manifest_hash, CUTOFF,
        )

    assert failure.value.code == "DATASET_PIN_CHANGED"
    assert len(connection.executions) == 1


@pytest.mark.asyncio
async def test_database_failure_is_distinct_from_a_changed_pin() -> None:
    class UnavailableConnection(RecordingConnection):
        async def execute(self, statement, parameters):
            raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await assert_dataset_pin(
            UnavailableConnection(None), ACTIVE_DATASET.dataset_version,
            ACTIVE_DATASET.manifest_hash, CUTOFF,
        )
