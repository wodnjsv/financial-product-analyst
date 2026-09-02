"""Deterministic binding of validated intent axes to server task contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.enums import IntentType

from .draft import SlotAssignment
from .resolution import ValidatedIntentFrameV2, ValidatedIntentResolutionV2
from .task_contracts import (
    EffectiveTaskContract,
    TaskContractRegistry,
    resolve_task_contract,
)
from .types import (
    ChoiceState,
    EntitySemanticRole,
    SemanticTag,
    SlotKind,
    SlotMutationKind,
)
from .view import ResolverView, ResolverViewLiteralCandidate


_LOCK_MATCH_KINDS = frozenset({"canonical_id", "direct_alias"})


class TaskBindingError(RuntimeError):
    pass


class BindingSource(str, Enum):
    DETERMINISTIC_EXACT = "deterministic_exact"
    DETERMINISTIC_LITERAL = "deterministic_literal"
    AXIS_SEMANTIC = "axis_semantic"
    CONTEXT = "context"
    AMBIGUITY_MODEL = "ambiguity_model"


class TaskReadiness(str, Enum):
    COMPLETE = "complete"
    AMBIGUOUS = "ambiguous"
    BLOCKED = "blocked"


class TaskSlotBinding(ContractModel):
    slot_kind: SlotKind
    value_ids: tuple[Identifier, ...] = Field(min_length=1)
    source: BindingSource
    source_ids: tuple[Identifier, ...]
    evidence_ids: tuple[Identifier, ...]


class AmbiguousSlotChoice(ContractModel):
    slot_kind: SlotKind
    value_ids: tuple[Identifier, ...] = Field(min_length=2)
    evidence_ids: tuple[Identifier, ...]


class ResolvedTaskContract(ContractModel):
    frame_id: Identifier
    contract_id: Identifier
    action_id: IntentType | None
    required_slot_kinds: tuple[SlotKind, ...]
    optional_slot_kinds: tuple[SlotKind, ...]
    bindings: tuple[TaskSlotBinding, ...]
    missing_required_slot_kinds: tuple[SlotKind, ...]
    ambiguous_choices: tuple[AmbiguousSlotChoice, ...]
    readiness: TaskReadiness


class TaskBoundIntentResolution(ContractModel):
    resolution: ValidatedIntentResolutionV2
    task_contract_registry_version: Identifier
    task_contract_registry_hash: Sha256Hex
    task_contracts: tuple[ResolvedTaskContract, ...]
    conditional_slot_call_used: bool = False

    @model_validator(mode="after")
    def validate_frame_coverage(self) -> "TaskBoundIntentResolution":
        frame_ids = tuple(frame.frame_id for frame in self.resolution.canonical_frames)
        contract_ids = tuple(item.frame_id for item in self.task_contracts)
        if frame_ids != contract_ids:
            raise ValueError("task contracts must exactly follow canonical frame order")
        return self


def bind_task_slots(
    resolution: ValidatedIntentResolutionV2,
    view: ResolverView,
    registry: TaskContractRegistry,
) -> TaskBoundIntentResolution:
    """Bind only explicit server-offered values after axes are validated."""
    contracts: list[ResolvedTaskContract] = []
    frames: list[ValidatedIntentFrameV2] = []
    hints_by_id = {hint.entity_hint_id: hint for hint in resolution.entity_hints}
    contracts_by_frame: dict[str, ResolvedTaskContract] = {}

    for frame in resolution.canonical_frames:
        model_task_slots = tuple(
            assignment
            for assignment in frame.slot_assignments
            if assignment.slot_kind not in {SlotKind.ENTITY, SlotKind.RELATION}
        )
        if model_task_slots:
            raise TaskBindingError("AXIS_TASK_SLOT_NOT_EMPTY")
        if frame.action_choice.state is not ChoiceState.SELECTED:
            if frame.action_choice.selected_ids:
                raise TaskBindingError("AXIS_UNRESOLVED")
            contracts.append(
                ResolvedTaskContract(
                    frame_id=frame.frame_id,
                    contract_id="unresolved.v1",
                    action_id=None,
                    required_slot_kinds=(),
                    optional_slot_kinds=(),
                    bindings=(),
                    missing_required_slot_kinds=(),
                    ambiguous_choices=(),
                    readiness=TaskReadiness.BLOCKED,
                )
            )
            frames.append(frame)
            continue
        if len(frame.action_choice.selected_ids) != 1:
            raise TaskBindingError("AXIS_UNRESOLVED")

        action = frame.action_choice.selected_ids[0]
        frame_hints = tuple(hints_by_id[item] for item in frame.entity_hint_ids)
        relation_ids = tuple(
            relation_id
            for assignment in frame.slot_assignments
            if assignment.slot_kind is SlotKind.RELATION
            for relation_id in assignment.value_ids
        ) + tuple(
            relation_id
            for hint in frame_hints
            if hint.semantic_role is EntitySemanticRole.RELATION_OBJECT
            for relation_id in hint.relation_id
        )
        contract = resolve_task_contract(
            registry,
            action=action,
            tags=resolution.final_tags,
            relation_required=(
                bool(relation_ids)
                or SemanticTag.RELATIONSHIP_REQUIRED in resolution.final_tags
            ),
        )
        resolved_contract, task_assignments = _bind_frame(
            frame,
            contract,
            view,
            relation_ids=relation_ids,
            suppressed_roles={
                mutation.slot_kind
                for mutation in frame.slot_mutations
                if mutation.mutation_kind
                in {SlotMutationKind.DELETE, SlotMutationKind.DONTCARE}
            },
        )
        resolved_contract, carryover_assignments = _apply_context_carryover(
            frame,
            resolved_contract,
            contracts_by_frame,
            assignment_offset=len(task_assignments),
        )
        task_assignments = (*task_assignments, *carryover_assignments)
        contracts.append(resolved_contract)
        contracts_by_frame[frame.frame_id] = resolved_contract
        frames.append(
            frame.model_copy(
                update={
                    "slot_assignments": (
                        *(
                            assignment
                            for assignment in frame.slot_assignments
                            if assignment.slot_kind is SlotKind.ENTITY
                        ),
                        *task_assignments,
                    )
                }
            )
        )

    enriched = resolution.model_copy(update={"canonical_frames": tuple(frames)})
    return TaskBoundIntentResolution(
        resolution=enriched,
        task_contract_registry_version=registry.registry_version,
        task_contract_registry_hash=registry.registry_hash,
        task_contracts=tuple(contracts),
    )


def _bind_frame(
    frame: ValidatedIntentFrameV2,
    contract: EffectiveTaskContract,
    view: ResolverView,
    *,
    relation_ids: tuple[str, ...],
    suppressed_roles: set[SlotKind],
) -> tuple[ResolvedTaskContract, tuple[SlotAssignment, ...]]:
    allowed_roles = (*contract.required_slot_kinds, *contract.optional_slot_kinds)
    candidates: dict[SlotKind, dict[str, tuple[BindingSource, tuple[str, ...], tuple[str, ...]]]] = {
        role: {} for role in allowed_roles if role not in suppressed_roles
    }

    _collect_literal_candidates(
        frame, view, candidates, required_roles=set(contract.required_slot_kinds)
    )
    _collect_semantic_candidates(frame, contract.action_id, view, candidates)
    if SlotKind.RELATION in candidates:
        for relation_id in relation_ids:
            candidates[SlotKind.RELATION][relation_id] = (
                BindingSource.AXIS_SEMANTIC,
                (relation_id,),
                _semantic_evidence_ids(frame, relation_id, view),
            )

    bindings: list[TaskSlotBinding] = []
    assignments: list[SlotAssignment] = []
    ambiguous: list[AmbiguousSlotChoice] = []
    for role in allowed_roles:
        values = candidates.get(role, {})
        if len(values) == 1:
            value_id, (source, source_ids, evidence_ids) = next(iter(values.items()))
            binding = TaskSlotBinding(
                slot_kind=role,
                value_ids=(value_id,),
                source=source,
                source_ids=source_ids,
                evidence_ids=evidence_ids,
            )
            bindings.append(binding)
            assignments.append(
                SlotAssignment(
                    slot_assignment_id=(
                        f"task-slot-{frame.ordinal:04d}-{len(assignments):04d}"
                    ),
                    slot_kind=role,
                    value_ids=(value_id,),
                    evidence_span_ids=evidence_ids,
                    reason_code=source.value,
                )
            )
        elif len(values) > 1 and role in contract.required_slot_kinds:
            evidence_ids = tuple(
                sorted(
                    {
                        evidence_id
                        for _, (_, _, item_evidence) in values.items()
                        for evidence_id in item_evidence
                    }
                )
            )
            ambiguous.append(
                AmbiguousSlotChoice(
                    slot_kind=role,
                    value_ids=tuple(sorted(values)),
                    evidence_ids=evidence_ids,
                )
            )

    bound_roles = {item.slot_kind for item in bindings}
    missing = tuple(
        role for role in contract.required_slot_kinds if role not in bound_roles
    )
    ambiguous_roles = {item.slot_kind for item in ambiguous}
    readiness = (
        TaskReadiness.COMPLETE
        if not missing
        else TaskReadiness.AMBIGUOUS
        if set(missing) <= ambiguous_roles
        else TaskReadiness.BLOCKED
    )
    return (
        ResolvedTaskContract(
            frame_id=frame.frame_id,
            contract_id=contract.contract_id,
            action_id=contract.action_id,
            required_slot_kinds=contract.required_slot_kinds,
            optional_slot_kinds=contract.optional_slot_kinds,
            bindings=tuple(bindings),
            missing_required_slot_kinds=missing,
            ambiguous_choices=tuple(ambiguous),
            readiness=readiness,
        ),
        tuple(assignments),
    )


def _apply_context_carryover(
    frame: ValidatedIntentFrameV2,
    contract: ResolvedTaskContract,
    contracts_by_frame: dict[str, ResolvedTaskContract],
    *,
    assignment_offset: int,
) -> tuple[ResolvedTaskContract, tuple[SlotAssignment, ...]]:
    bindings = list(contract.bindings)
    assignments: list[SlotAssignment] = []
    bound_roles = {item.slot_kind for item in bindings}
    for mutation in frame.slot_mutations:
        if (
            mutation.mutation_kind is not SlotMutationKind.CARRYOVER
            or len(mutation.source_frame_id) != 1
            or mutation.slot_kind in bound_roles
        ):
            continue
        source = contracts_by_frame.get(mutation.source_frame_id[0])
        if source is None:
            continue
        source_bindings = tuple(
            item for item in source.bindings if item.slot_kind is mutation.slot_kind
        )
        if len(source_bindings) != 1:
            continue
        source_binding = source_bindings[0]
        binding = TaskSlotBinding(
            slot_kind=mutation.slot_kind,
            value_ids=source_binding.value_ids,
            source=BindingSource.CONTEXT,
            source_ids=(source.frame_id, *source_binding.source_ids),
            evidence_ids=source_binding.evidence_ids,
        )
        bindings.append(binding)
        bound_roles.add(mutation.slot_kind)
        assignments.append(
            SlotAssignment(
                slot_assignment_id=(
                    f"task-slot-{frame.ordinal:04d}-"
                    f"{assignment_offset + len(assignments):04d}"
                ),
                slot_kind=mutation.slot_kind,
                value_ids=source_binding.value_ids,
                evidence_span_ids=source_binding.evidence_ids,
                reason_code=BindingSource.CONTEXT.value,
            )
        )

    missing = tuple(
        role for role in contract.required_slot_kinds if role not in bound_roles
    )
    ambiguous_roles = {item.slot_kind for item in contract.ambiguous_choices}
    readiness = (
        TaskReadiness.COMPLETE
        if not missing
        else TaskReadiness.AMBIGUOUS
        if set(missing) <= ambiguous_roles
        else TaskReadiness.BLOCKED
    )
    return (
        contract.model_copy(
            update={
                "bindings": tuple(bindings),
                "missing_required_slot_kinds": missing,
                "readiness": readiness,
            }
        ),
        tuple(assignments),
    )


def _collect_literal_candidates(
    frame: ValidatedIntentFrameV2,
    view: ResolverView,
    candidates: dict[SlotKind, dict[str, tuple[BindingSource, tuple[str, ...], tuple[str, ...]]]],
    *,
    required_roles: set[SlotKind],
) -> None:
    kind_roles = {
        "result_limit": (SlotKind.RESULT_LIMIT,),
        "sort_direction": (SlotKind.SORT_DIRECTION,),
        "period": (SlotKind.PERIOD,),
        "currency": (SlotKind.CURRENCY,),
        "date": (SlotKind.DATE_SCOPE,),
        "number": (SlotKind.FILTER_VALUE,),
        "percentage": (SlotKind.FILTER_VALUE,),
        "money": (SlotKind.FILTER_VALUE,),
    }
    for literal in view.literal_candidates:
        if literal.segment_id not in frame.segment_ids:
            continue
        evidence_ids = _literal_evidence_ids(literal, view)
        for role in kind_roles.get(literal.kind, ()):
            if role is SlotKind.FILTER_VALUE and role not in required_roles:
                continue
            if role in candidates:
                candidates[role][literal.literal_id] = (
                    BindingSource.DETERMINISTIC_LITERAL,
                    (literal.literal_id,),
                    evidence_ids,
                )


def _collect_semantic_candidates(
    frame: ValidatedIntentFrameV2,
    action: IntentType,
    view: ResolverView,
    candidates: dict[SlotKind, dict[str, tuple[BindingSource, tuple[str, ...], tuple[str, ...]]]],
) -> None:
    concepts = {item.concept_id: item for item in view.concept_definitions}
    relation_ids = {item.relation_id for item in view.relation_definitions}
    families = {item.value for item in frame.product_family_choice.selected_ids}
    for group in view.semantic_candidates:
        for candidate in group.items:
            if candidate.match_kind not in _LOCK_MATCH_KINDS:
                continue
            if candidate.semantic_id in relation_ids:
                if SlotKind.RELATION not in candidates:
                    continue
                evidence_ids = _semantic_evidence_ids(
                    frame, candidate.semantic_id, view
                )
                if _semantic_has_other_frame_evidence(
                    frame, candidate.semantic_id, view
                ):
                    continue
                candidates[SlotKind.RELATION][candidate.semantic_id] = (
                    BindingSource.DETERMINISTIC_EXACT,
                    (group.mention_id, candidate.semantic_id),
                    evidence_ids,
                )
                continue
            concept = concepts.get(candidate.semantic_id)
            if concept is None or not families <= set(concept.allowed_product_families):
                continue
            evidence_ids = _semantic_evidence_ids(frame, candidate.semantic_id, view)
            if _semantic_has_other_frame_evidence(frame, candidate.semantic_id, view):
                continue
            role = _semantic_role(action, concept.kind)
            if role is None or role not in candidates:
                continue
            candidates[role][candidate.semantic_id] = (
                BindingSource.DETERMINISTIC_EXACT,
                (group.mention_id, candidate.semantic_id),
                evidence_ids,
            )


def _semantic_role(action: IntentType, concept_kind: str) -> SlotKind | None:
    if concept_kind == "document_topic":
        return SlotKind.DOCUMENT_TOPIC
    if concept_kind not in {"metric", "attribute"}:
        return None
    if action is IntentType.RANK:
        return SlotKind.SORT_KEY
    if action in {IntentType.COMPARE, IntentType.AGGREGATE, IntentType.CALCULATE}:
        return SlotKind.METRIC
    if action is IntentType.SCREEN:
        return SlotKind.METRIC
    if action is IntentType.SIMILAR:
        return SlotKind.SIMILARITY_ANCHOR
    return None


def _semantic_evidence_ids(
    frame: ValidatedIntentFrameV2, semantic_id: str, view: ResolverView
) -> tuple[str, ...]:
    return tuple(
        item.evidence_id
        for item in view.evidence_candidates
        if item.segment_id in frame.segment_ids
        and semantic_id in item.offered_semantic_ids
    )


def _semantic_has_other_frame_evidence(
    frame: ValidatedIntentFrameV2, semantic_id: str, view: ResolverView
) -> bool:
    evidence = tuple(
        item for item in view.evidence_candidates if semantic_id in item.offered_semantic_ids
    )
    return bool(evidence) and not any(
        item.segment_id in frame.segment_ids for item in evidence
    )


def _literal_evidence_ids(
    literal: ResolverViewLiteralCandidate, view: ResolverView
) -> tuple[str, ...]:
    return tuple(
        item.evidence_id
        for item in view.evidence_candidates
        if (
            item.segment_id,
            item.start_char,
            item.end_char,
            item.text,
        )
        == (
            literal.segment_id,
            literal.start_char,
            literal.end_char,
            literal.original_text,
        )
    )
