"""One bounded HCX call for genuinely ambiguous required task slots."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Mapping, Protocol

from pydantic import Field, ValidationError

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.request import RequestContext

from .clova import ModelInvocationResult
from .draft import SlotAssignment
from .prompt import ResolverPromptEnvelope
from .task_binding import (
    BindingSource,
    ResolvedTaskContract,
    TaskBoundIntentResolution,
    TaskReadiness,
    TaskSlotBinding,
)
from .types import SlotKind


SYSTEM_MESSAGE = (
    "You resolve only the offered missing required task slots. Return one JSON "
    "object matching the supplied schema. Choose exactly one offered value for "
    "each offered frame and slot. Do not change intent axes, tags, entities, "
    "context, coverage, or create identifiers."
)


class SlotResolutionError(RuntimeError):
    pass


class _Adapter(Protocol):
    async def invoke(
        self, envelope: ResolverPromptEnvelope, timeout_seconds: float
    ) -> ModelInvocationResult: ...


class SlotSelection(ContractModel):
    frame_id: Identifier
    slot_kind: SlotKind
    selected_value_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=1)]


class SlotSelectionProposal(ContractModel):
    proposal_schema_version: Literal["1.0"] = "1.0"
    selections: tuple[SlotSelection, ...] = Field(min_length=1)


async def resolve_ambiguous_slots(
    *,
    adapter: _Adapter,
    context: RequestContext,
    bound: TaskBoundIntentResolution,
    timeout_seconds: float,
) -> tuple[TaskBoundIntentResolution, Mapping[str, int]]:
    if bound.resolution.repair_used or any(
        contract.readiness is TaskReadiness.BLOCKED
        for contract in bound.task_contracts
    ):
        raise SlotResolutionError("SLOT_SELECTION_NOT_ELIGIBLE")
    choices = tuple(
        (contract.frame_id, choice)
        for contract in bound.task_contracts
        if contract.readiness is TaskReadiness.AMBIGUOUS
        for choice in contract.ambiguous_choices
    )
    if not choices:
        raise SlotResolutionError("SLOT_SELECTION_NOT_ELIGIBLE")

    envelope = _build_prompt(context, bound, choices)
    result = await adapter.invoke(envelope, timeout_seconds)
    proposal = _parse_proposal(result.content)
    return _apply_proposal(bound, proposal), result.usage


def _build_prompt(
    context: RequestContext,
    bound: TaskBoundIntentResolution,
    choices,
) -> ResolverPromptEnvelope:
    variants = [
        _object(
            {
                "frame_id": _enum((frame_id,)),
                "slot_kind": _enum((choice.slot_kind.value,)),
                "selected_value_ids": {
                    "type": "array",
                    "items": _enum(choice.value_ids),
                    "minItems": 1,
                    "maxItems": 1,
                },
            }
        )
        for frame_id, choice in choices
    ]
    schema = _object(
        {
            "proposal_schema_version": _enum(("1.0",)),
            "selections": {
                "type": "array",
                "items": {"anyOf": variants},
                "minItems": len(choices),
                "maxItems": len(choices),
            },
        }
    )
    user_message = json.dumps(
        {
            "question": context.question,
            "resolved_frames": [
                {
                    "frame_id": contract.frame_id,
                    "action_id": (
                        contract.action_id.value
                        if contract.action_id is not None
                        else "unresolved"
                    ),
                    "missing_required_slot_kinds": [
                        item.value for item in contract.missing_required_slot_kinds
                    ],
                    "choices": [
                        {
                            "slot_kind": choice.slot_kind.value,
                            "value_ids": choice.value_ids,
                        }
                        for choice in contract.ambiguous_choices
                    ],
                }
                for contract in bound.task_contracts
                if contract.readiness is TaskReadiness.AMBIGUOUS
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return ResolverPromptEnvelope(
        system_message=SYSTEM_MESSAGE,
        user_message=user_message,
        response_schema=schema,
    )


def _parse_proposal(content: str) -> SlotSelectionProposal:
    try:
        json.loads(content, object_pairs_hook=_reject_duplicate_keys)
        return SlotSelectionProposal.model_validate_json(content)
    except (ValueError, ValidationError, json.JSONDecodeError):
        raise SlotResolutionError("SLOT_SELECTION_SCHEMA_INVALID") from None


def _apply_proposal(
    bound: TaskBoundIntentResolution,
    proposal: SlotSelectionProposal,
) -> TaskBoundIntentResolution:
    offered = {
        (contract.frame_id, choice.slot_kind): choice
        for contract in bound.task_contracts
        if contract.readiness is TaskReadiness.AMBIGUOUS
        for choice in contract.ambiguous_choices
    }
    selected = {(item.frame_id, item.slot_kind): item for item in proposal.selections}
    if len(selected) != len(proposal.selections) or set(selected) != set(offered):
        raise SlotResolutionError("SLOT_SELECTION_NOT_OFFERED")
    for key, item in selected.items():
        if item.selected_value_ids[0] not in offered[key].value_ids:
            raise SlotResolutionError("SLOT_SELECTION_NOT_OFFERED")

    contracts: list[ResolvedTaskContract] = []
    frames = []
    frame_by_id = {frame.frame_id: frame for frame in bound.resolution.canonical_frames}
    for contract in bound.task_contracts:
        new_bindings = list(contract.bindings)
        new_assignments: list[SlotAssignment] = []
        remaining_missing = list(contract.missing_required_slot_kinds)
        remaining_choices = []
        for choice in contract.ambiguous_choices:
            selection = selected[(contract.frame_id, choice.slot_kind)]
            value_id = selection.selected_value_ids[0]
            new_bindings.append(
                TaskSlotBinding(
                    slot_kind=choice.slot_kind,
                    value_ids=(value_id,),
                    source=BindingSource.AMBIGUITY_MODEL,
                    source_ids=(value_id,),
                    evidence_ids=choice.evidence_ids,
                )
            )
            new_assignments.append(
                SlotAssignment(
                    slot_assignment_id=(
                        f"task-slot-ambiguity-{contract.frame_id}-{choice.slot_kind.value}"
                    ),
                    slot_kind=choice.slot_kind,
                    value_ids=(value_id,),
                    evidence_span_ids=choice.evidence_ids,
                    reason_code=BindingSource.AMBIGUITY_MODEL.value,
                )
            )
            remaining_missing.remove(choice.slot_kind)
        contracts.append(
            contract.model_copy(
                update={
                    "bindings": tuple(new_bindings),
                    "missing_required_slot_kinds": tuple(remaining_missing),
                    "ambiguous_choices": tuple(remaining_choices),
                    "readiness": (
                        TaskReadiness.COMPLETE
                        if not remaining_missing
                        else TaskReadiness.BLOCKED
                    ),
                }
            )
        )
        frame = frame_by_id[contract.frame_id]
        frames.append(
            frame.model_copy(
                update={
                    "slot_assignments": (*frame.slot_assignments, *new_assignments)
                }
            )
        )

    resolution = bound.resolution.model_copy(
        update={"canonical_frames": tuple(frames), "repair_used": True}
    )
    return bound.model_copy(
        update={
            "resolution": resolution,
            "task_contracts": tuple(contracts),
            "conditional_slot_call_used": True,
        }
    )


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _enum(values: tuple[str, ...]) -> dict[str, object]:
    return {"type": "string", "enum": list(values)}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
