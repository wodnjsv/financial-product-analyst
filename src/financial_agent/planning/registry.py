from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from financial_agent.contracts.enums import (
    Capability,
    IntentType,
    ResultShape,
    ResultType,
)

from .primitive_contracts import CANONICAL_PRIMITIVES, validate_registry_primitive


REGISTRY_PATH = Path("config/planning/query-plan-registry.v1.json")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PrimitiveDefinition(_StrictModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    action_ids: tuple[IntentType, ...]
    capability: Capability
    required_slots: tuple[str, ...]
    parameter_ids: tuple[str, ...]
    result_type: ResultType
    required_evidence_fields: tuple[str, ...]
    budget_ms: int = Field(gt=0, le=55_000)


class ArchetypeDefinition(_StrictModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    action_ids: tuple[IntentType, ...]
    min_family_count: int = Field(ge=0, le=4)
    max_family_count: int = Field(ge=0, le=4)
    context_required: bool
    required_tags: tuple[str, ...]
    forbidden_tags: tuple[str, ...]
    required_slots: tuple[str, ...]
    primitive_ids: tuple[str, ...]
    result_shape: ResultShape


class _RegistryPayload(_StrictModel):
    registry_version: str = Field(min_length=1)
    compiler_version: str = Field(min_length=1)
    primitives: tuple[PrimitiveDefinition, ...]
    archetypes: tuple[ArchetypeDefinition, ...]


@dataclass(frozen=True, slots=True)
class PlanningRegistry:
    registry_version: str
    registry_hash: str
    compiler_version: str
    primitives_by_id: Mapping[str, PrimitiveDefinition]
    archetypes_by_id: Mapping[str, ArchetypeDefinition]


def load_planning_registry(project_root: Path) -> PlanningRegistry:
    path = project_root.resolve() / REGISTRY_PATH
    try:
        payload = _RegistryPayload.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ValueError("invalid planning registry") from error
    primitives = _unique_index(payload.primitives, "primitive")
    if set(primitives) != set(CANONICAL_PRIMITIVES):
        raise ValueError("planning primitive registry mismatch")
    for primitive_id, primitive in primitives.items():
        validate_registry_primitive(
            primitive_id,
            action_ids=primitive.action_ids,
            capability=primitive.capability,
        )
    archetypes = _unique_index(payload.archetypes, "archetype")
    primitive_ids = set(primitives)
    for archetype in archetypes.values():
        unknown = set(archetype.primitive_ids) - primitive_ids
        if unknown:
            raise ValueError(f"unknown primitive: {sorted(unknown)}")
        if archetype.min_family_count > archetype.max_family_count:
            raise ValueError("invalid archetype family count")
        for primitive_id in archetype.primitive_ids:
            primitive = primitives[primitive_id]
            if not set(primitive.action_ids) & set(archetype.action_ids):
                raise ValueError("archetype primitive action is incompatible")
            if not set(primitive.required_slots) <= set(archetype.required_slots):
                raise ValueError("archetype omits primitive required slots")
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return PlanningRegistry(
        registry_version=payload.registry_version,
        registry_hash=hashlib.sha256(canonical).hexdigest(),
        compiler_version=payload.compiler_version,
        primitives_by_id=MappingProxyType(dict(sorted(primitives.items()))),
        archetypes_by_id=MappingProxyType(dict(sorted(archetypes.items()))),
    )


def _unique_index(items: tuple[_StrictModel, ...], label: str) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for item in items:
        item_id = getattr(item, "id")
        if item_id in indexed:
            raise ValueError(f"duplicate {label}: {item_id}")
        indexed[item_id] = item
    return indexed
