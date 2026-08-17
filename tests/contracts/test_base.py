from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from financial_agent.contracts.base import RuntimeArtifact


class ExampleArtifact(RuntimeArtifact):
    value: str


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "request_key": "a" * 64,
        "run_id": "run-001",
        "dataset_version": "2026-07-11-v1",
        "cutoff_date": "2026-07-11",
        "producer": "test",
        "created_at": "2026-08-17T00:00:00Z",
        "value": "ok",
    }


def test_runtime_artifact_rejects_unknown_fields() -> None:
    payload = valid_payload() | {"unknown": True}
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(payload)


def test_runtime_artifact_is_frozen() -> None:
    artifact = ExampleArtifact.model_validate(valid_payload())
    with pytest.raises(ValidationError):
        artifact.value = "changed"


@pytest.mark.parametrize("bad_cutoff", ["2026-07-10", "2026-07-12"])
def test_runtime_artifact_requires_fixed_cutoff(bad_cutoff: str) -> None:
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(valid_payload() | {"cutoff_date": bad_cutoff})


def test_runtime_artifact_rejects_naive_created_at() -> None:
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(
            valid_payload() | {"created_at": datetime(2026, 8, 17)}
        )


def test_runtime_artifact_rejects_non_utc_created_at() -> None:
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(
            valid_payload() | {"created_at": "2026-08-17T09:00:00+09:00"}
        )


def test_runtime_artifact_accepts_utc_created_at() -> None:
    artifact = ExampleArtifact.model_validate(valid_payload())
    assert artifact.created_at == datetime(2026, 8, 17, tzinfo=UTC)
    assert artifact.cutoff_date == date(2026, 7, 11)
