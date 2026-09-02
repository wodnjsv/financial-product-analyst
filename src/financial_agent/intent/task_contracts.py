"""Versioned server-owned input contracts for resolved intent frames."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from pydantic import ConfigDict, Field, ValidationError, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.enums import IntentType, ResultShape

from .types import SemanticTag, SlotKind


REGISTRY_PATH = Path("config/intent/task-input-contracts.v1.json")


class TaskInputContractDefinition(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_id: Identifier
    action_id: IntentType
    required_slot_kinds: tuple[SlotKind, ...]
    optional_slot_kinds: tuple[SlotKind, ...]
    result_shape: ResultShape

    @model_validator(mode="after")
    def validate_roles(self) -> "TaskInputContractDefinition":
        if (
            len(set(self.required_slot_kinds)) != len(self.required_slot_kinds)
            or len(set(self.optional_slot_kinds)) != len(self.optional_slot_kinds)
            or set(self.required_slot_kinds) & set(self.optional_slot_kinds)
        ):
            raise ValueError("task contract slots must be unique and disjoint")
        return self


class _RegistryPayload(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    registry_version: Identifier
    contracts: tuple[TaskInputContractDefinition, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class TaskContractRegistry:
    registry_version: str
    registry_hash: str
    contracts_by_action: Mapping[IntentType, TaskInputContractDefinition]


class EffectiveTaskContract(ContractModel):
    contract_id: Identifier
    action_id: IntentType
    required_slot_kinds: tuple[SlotKind, ...]
    optional_slot_kinds: tuple[SlotKind, ...]
    result_shape: ResultShape


def load_task_contract_registry(project_root: Path) -> TaskContractRegistry:
    path = project_root.resolve() / REGISTRY_PATH
    try:
        payload = _RegistryPayload.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ValueError("invalid task contract registry") from error

    by_action: dict[IntentType, TaskInputContractDefinition] = {}
    contract_ids: set[str] = set()
    for contract in payload.contracts:
        if contract.action_id in by_action or contract.contract_id in contract_ids:
            raise ValueError("invalid task contract registry")
        by_action[contract.action_id] = contract
        contract_ids.add(contract.contract_id)
    if set(by_action) != set(IntentType):
        raise ValueError("invalid task contract registry")

    canonical = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return TaskContractRegistry(
        registry_version=payload.registry_version,
        registry_hash=hashlib.sha256(canonical).hexdigest(),
        contracts_by_action=MappingProxyType(dict(by_action)),
    )


def resolve_task_contract(
    registry: TaskContractRegistry,
    *,
    action: IntentType,
    tags: tuple[SemanticTag, ...],
    relation_required: bool,
) -> EffectiveTaskContract:
    definition = registry.contracts_by_action[action]
    conditional: list[SlotKind] = []
    if relation_required:
        conditional.append(SlotKind.RELATION)
    if SemanticTag.DOCUMENT_GROUNDED in tags:
        conditional.append(SlotKind.DOCUMENT_TOPIC)
    required = _unique((*definition.required_slot_kinds, *conditional))
    optional = tuple(
        slot for slot in definition.optional_slot_kinds if slot not in required
    )
    return EffectiveTaskContract(
        contract_id=definition.contract_id,
        action_id=definition.action_id,
        required_slot_kinds=required,
        optional_slot_kinds=optional,
        result_shape=definition.result_shape,
    )


def _unique(values: tuple[SlotKind, ...]) -> tuple[SlotKind, ...]:
    return tuple(dict.fromkeys(values))
