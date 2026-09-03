"""Pinned, caller-supplied semantic qualifier defaults."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping, Self

from pydantic import Field, ValidationError, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.canonical import canonical_sha256


SEMANTIC_DEFAULT_POLICY_REGISTRY_PATH = Path(
    "config/intent/semantic-default-policy-registry.v1.json"
)
SEMANTIC_DEFAULT_POLICY_REGISTRY_VERSION = "semantic-default-policy-registry.v1"
ACTIVE_DATASET_AS_OF_POLICY_ID = "active-dataset-as-of.v1"


class SemanticAsOfDefaultV1(ContractModel):
    default_record_id: Identifier
    product_family_id: Identifier
    semantic_id: Identifier
    as_of_date: date


class DatasetSemanticDefaultsV1(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_version: Identifier
    manifest_hash: Sha256Hex
    defaults: tuple[SemanticAsOfDefaultV1, ...]

    @model_validator(mode="after")
    def require_unique_record_ids(self) -> Self:
        record_ids = tuple(item.default_record_id for item in self.defaults)
        if len(set(record_ids)) != len(record_ids):
            raise ValueError("DUPLICATE_SEMANTIC_DEFAULT_RECORD_ID")
        return self


class SemanticDefaultPolicyDefinition(ContractModel):
    id: Identifier
    kind: Literal["default"]
    eligible_semantic_ids: tuple[Identifier, ...] = Field(min_length=1)
    eligible_product_family_ids: tuple[Identifier, ...] = Field(min_length=1)


class _SemanticDefaultPolicyRegistryPayload(ContractModel):
    registry_version: Identifier
    policies: tuple[SemanticDefaultPolicyDefinition, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class SemanticDefaultPolicyRegistry:
    registry_version: str
    registry_hash: str
    policies_by_id: Mapping[str, SemanticDefaultPolicyDefinition]


def load_semantic_default_policy_registry(
    project_root: Path,
) -> SemanticDefaultPolicyRegistry:
    """Load the date-free allowlist for caller-supplied semantic defaults."""

    try:
        payload = _SemanticDefaultPolicyRegistryPayload.model_validate_json(
            (project_root.resolve() / SEMANTIC_DEFAULT_POLICY_REGISTRY_PATH).read_bytes()
        )
    except (OSError, ValidationError) as error:
        raise ValueError("invalid semantic default policy registry") from error

    if payload.registry_version != SEMANTIC_DEFAULT_POLICY_REGISTRY_VERSION:
        raise ValueError("unsupported semantic default policy registry version")
    policies = {item.id: item for item in payload.policies}
    if len(policies) != len(payload.policies):
        raise ValueError("invalid semantic default policy registry")
    if tuple(policies) != (ACTIVE_DATASET_AS_OF_POLICY_ID,):
        raise ValueError("semantic default policy registry definition mismatch")
    policy = policies[ACTIVE_DATASET_AS_OF_POLICY_ID]
    if (
        policy.kind != "default"
        or policy.eligible_semantic_ids != ("aum",)
        or policy.eligible_product_family_ids
        != ("domestic_etf", "overseas_etf", "public_fund")
    ):
        raise ValueError("semantic default policy registry definition mismatch")

    return SemanticDefaultPolicyRegistry(
        registry_version=payload.registry_version,
        registry_hash=canonical_sha256(payload),
        policies_by_id=MappingProxyType(policies),
    )
