from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

CONTRACT_SCHEMA_VERSION = "1.0"
SNAPSHOT_CUTOFF = date(2026, 7, 11)

Identifier = Annotated[
    str,
    Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must use UTC")
    return value


UtcDateTime = Annotated[datetime, AfterValidator(require_utc)]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class RuntimeArtifact(ContractModel):
    schema_version: Literal["1.0"] = CONTRACT_SCHEMA_VERSION
    request_key: Sha256Hex
    run_id: Identifier
    dataset_version: Identifier
    cutoff_date: date = SNAPSHOT_CUTOFF
    producer: Identifier
    created_at: UtcDateTime

    @field_validator("cutoff_date")
    @classmethod
    def validate_cutoff(cls, value: date) -> date:
        if value != SNAPSHOT_CUTOFF:
            raise ValueError("cutoff_date must be 2026-07-11")
        return value
