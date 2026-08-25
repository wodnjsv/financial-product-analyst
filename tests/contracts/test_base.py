import json
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from financial_agent.contracts.base import RuntimeArtifact
from financial_agent.contracts.enums import InteractionMode


class ExampleArtifact(RuntimeArtifact):
    value: str
    count: int
    mode: InteractionMode
    labels: tuple[str, ...]


def valid_json_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "request_key": "a" * 64,
        "run_id": "run-001",
        "dataset_version": "2026-08-24-v1",
        "cutoff_date": "2026-08-24",
        "producer": "test",
        "created_at": "2026-08-17T00:00:00Z",
        "value": "ok",
        "count": 1,
        "mode": "competition",
        "labels": ["one", "two"],
    }


def valid_python_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "request_key": "a" * 64,
        "run_id": "run-001",
        "dataset_version": "2026-08-24-v1",
        "cutoff_date": date(2026, 8, 24),
        "producer": "test",
        "created_at": datetime(2026, 8, 17, tzinfo=UTC),
        "value": "ok",
        "count": 1,
        "mode": InteractionMode.COMPETITION,
        "labels": ("one", "two"),
    }


def test_raw_json_accepts_iso_temporal_enum_and_array_shapes() -> None:
    artifact = ExampleArtifact.model_validate_json(json.dumps(valid_json_payload()))

    assert artifact.created_at == datetime(2026, 8, 17, tzinfo=UTC)
    assert artifact.cutoff_date == date(2026, 8, 24)
    assert artifact.mode is InteractionMode.COMPETITION
    assert artifact.labels == ("one", "two")


@pytest.mark.parametrize(
    "payload_update",
    [
        {"count": "1"},
        {"count": True},
        {"cutoff_date": "2026-08-24"},
        {"created_at": "2026-08-17T00:00:00Z"},
        {"mode": "competition"},
        {"labels": ["one", "two"]},
    ],
)
def test_python_ingress_rejects_coercible_values(
    payload_update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(valid_python_payload() | payload_update)


def test_runtime_artifact_rejects_unknown_fields() -> None:
    payload = valid_python_payload() | {"unknown": True}
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(payload)


def test_runtime_artifact_is_frozen() -> None:
    artifact = ExampleArtifact.model_validate(valid_python_payload())
    with pytest.raises(ValidationError):
        artifact.value = "changed"


@pytest.mark.parametrize(
    "bad_cutoff",
    ["2026-07-11", "2026-08-23", "2026-08-25"],
)
def test_runtime_artifact_requires_fixed_cutoff(bad_cutoff: str) -> None:
    payload = valid_json_payload() | {"cutoff_date": bad_cutoff}
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate_json(json.dumps(payload))


def test_runtime_artifact_rejects_naive_created_at() -> None:
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(
            valid_python_payload() | {"created_at": datetime(2026, 8, 17)}
        )


def test_runtime_artifact_rejects_non_utc_created_at() -> None:
    non_utc = datetime(
        2026,
        8,
        17,
        9,
        tzinfo=timezone(timedelta(hours=9)),
    )
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(
            valid_python_payload() | {"created_at": non_utc}
        )


def test_runtime_artifact_accepts_typed_python_values() -> None:
    artifact = ExampleArtifact.model_validate(valid_python_payload())
    assert artifact.created_at == datetime(2026, 8, 17, tzinfo=UTC)
    assert artifact.cutoff_date == date(2026, 8, 24)
