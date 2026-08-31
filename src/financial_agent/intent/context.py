"""Fail-closed validation and finalization of typed intent context."""

from __future__ import annotations

from dataclasses import dataclass

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex, UtcDateTime
from financial_agent.contracts.enums import Cardinality, IntentType

from .draft import ContextLinkHint, IntentFrameDraft, ReferenceHint, SlotMutation
from .errors import ResolverContractError
from .resolution import (
    ResolverBuildManifest,
    ResolutionIssue,
    ValidatedContextLink,
    ValidatedIntentFrame,
    ValidatedIntentResolution,
    ValidatedSlotMutation,
    ValidationEvent,
)
from .types import (
    ContextLinkType,
    ReferenceTargetKind,
    ResolutionStatus,
    Selector,
    SlotKind,
    SlotMutationKind,
    SourceRole,
)
from .validation import STATUS_PRECEDENCE, SemanticValidationState


SLOT_PRECEDENCE = (
    "explicit_current_evidence",
    "validated_context_link",
    "explicit_carryover",
    "phase2_default",
)


class ResolutionFinalizationMetadata(ContractModel):
    """Trusted request and build pins supplied by the Task 9 service boundary."""

    request_key: Sha256Hex
    run_id: Identifier
    dataset_version: Identifier
    producer: Identifier
    created_at: UtcDateTime
    resolution_id: Identifier
    draft_hash: Sha256Hex
    build_manifest: ResolverBuildManifest
    active_dataset_manifest_hash: Sha256Hex


@dataclass(frozen=True, slots=True)
class ContextValidationState:
    """Validated context semantics ready for immutable artifact finalization."""

    semantic_state: SemanticValidationState
    context_links: tuple[ValidatedContextLink, ...]
    issues: tuple[ResolutionIssue, ...]
    resolution_status: ResolutionStatus
    validation_events: tuple[ValidationEvent, ...]


@dataclass(frozen=True, slots=True)
class _RoleShape:
    target_kind: ReferenceTargetKind
    cardinality: Cardinality


_ROLE_SHAPES = {
    SourceRole.CANDIDATES: _RoleShape(ReferenceTargetKind.RESULT_SET, Cardinality.MANY),
    SourceRole.SELECTED_PRODUCT: _RoleShape(ReferenceTargetKind.ENTITY, Cardinality.ONE),
    SourceRole.TOP_K_PRODUCTS: _RoleShape(ReferenceTargetKind.RESULT_SET, Cardinality.MANY),
    SourceRole.EXCLUDED_PRODUCTS: _RoleShape(ReferenceTargetKind.EXCLUSION_SET, Cardinality.MANY),
    SourceRole.METRIC_VALUE: _RoleShape(ReferenceTargetKind.METRIC_VALUE, Cardinality.ONE),
    SourceRole.RELATION_TARGET: _RoleShape(ReferenceTargetKind.RELATED_ENTITY, Cardinality.ONE),
    SourceRole.COMPARISON_DECISION: _RoleShape(ReferenceTargetKind.PRIOR_OPERATION, Cardinality.ONE),
    SourceRole.EVIDENCE_RECORDS: _RoleShape(ReferenceTargetKind.EVIDENCE_RECORDS, Cardinality.MANY),
}

_SINGLE_SELECTORS = frozenset(
    {Selector.FIRST, Selector.LAST, Selector.RANK_POSITION, Selector.FORMER, Selector.LATTER}
)
_SET_SELECTORS = frozenset({Selector.ALL, Selector.TOP_N, Selector.EACH, Selector.REMAINING})


def validate_context_graph(state: SemanticValidationState) -> ContextValidationState:
    """Validate only explicit, backward context dependencies and slot mutations."""

    frames_by_id = {frame.frame_id: frame for frame in state.canonical_frames}
    references_by_id = {hint.reference_id: hint for hint in state.draft.reference_hints}
    _validate_reference_frame_ids(references_by_id.values(), frames_by_id)
    links = tuple(
        _validate_link(hint, references_by_id, frames_by_id, dict(state.literal_kinds_by_id))
        for hint in state.draft.context_link_hints
    )
    _validate_acyclic(links)
    _validate_mutations(state.draft.slot_mutations, frames_by_id)

    issues = _append_context_issues(state, links, frames_by_id, references_by_id)
    return ContextValidationState(
        semantic_state=state,
        context_links=tuple(sorted(links, key=lambda link: link.context_link_id)),
        issues=issues,
        resolution_status=_resolution_status(issues),
        validation_events=(*state.validation_events, *_context_events()),
    )


def finalize_resolution(
    context_state: ContextValidationState,
    metadata: ResolutionFinalizationMetadata,
) -> ValidatedIntentResolution:
    """Freeze context validation into the richer, immutable internal artifact."""

    mutations_by_frame: dict[str, list[ValidatedSlotMutation]] = {}
    for mutation in context_state.semantic_state.draft.slot_mutations:
        mutations_by_frame.setdefault(mutation.consumer_frame_id, []).append(
            ValidatedSlotMutation(
                slot_mutation_id=mutation.slot_mutation_id,
                consumer_frame_id=mutation.consumer_frame_id,
                slot_kind=mutation.slot_kind,
                mutation_kind=mutation.mutation_kind,
                source_frame_id=mutation.source_frame_id,
            )
        )
    canonical_frames = tuple(
        _validated_frame(frame, mutations_by_frame.get(frame.frame_id, ()), context_state.issues)
        for frame in context_state.semantic_state.canonical_frames
    )
    return ValidatedIntentResolution(
        request_key=metadata.request_key,
        run_id=metadata.run_id,
        dataset_version=metadata.dataset_version,
        producer=metadata.producer,
        created_at=metadata.created_at,
        resolution_id=metadata.resolution_id,
        draft_hash=metadata.draft_hash,
        canonical_frames=canonical_frames,
        context_links=context_state.context_links,
        final_tags=context_state.semantic_state.final_tags,
        resolution_status=context_state.resolution_status,
        issues=context_state.issues,
        validation_events=context_state.validation_events,
        build_manifest=metadata.build_manifest,
        active_dataset_manifest_hash=metadata.active_dataset_manifest_hash,
        repair_used=False,
        invalid_attempt_hashes=(),
    )


def _validate_reference_frame_ids(
    references: object, frames_by_id: dict[str, IntentFrameDraft]
) -> None:
    for reference in references:  # type: ignore[union-attr]
        if not set(reference.candidate_target_frame_ids) <= set(frames_by_id):
            _invalid_graph()


def _validate_link(
    hint: ContextLinkHint,
    references_by_id: dict[str, ReferenceHint],
    frames_by_id: dict[str, IntentFrameDraft],
    literal_kinds_by_id: dict[str, str],
) -> ValidatedContextLink:
    reference = references_by_id.get(hint.reference_id)
    producer = frames_by_id.get(hint.producer_frame_id)
    consumer = frames_by_id.get(hint.consumer_frame_id)
    if reference is None or producer is None or consumer is None:
        _invalid_graph()
    assert reference is not None and producer is not None and consumer is not None
    if reference.status != "resolved" or hint.producer_frame_id not in reference.candidate_target_frame_ids:
        _invalid_graph()
    if producer.ordinal >= consumer.ordinal or hint.source_role not in producer.produced_result_hints:
        _invalid_graph()

    source = _ROLE_SHAPES[hint.source_role]
    target_kind, target_cardinality = _link_target(hint, source)
    if (
        reference.expected_target_kind != (target_kind,)
        or reference.expected_cardinality != (target_cardinality,)
    ):
        _invalid_graph()
    _validate_selector(hint, source.cardinality, literal_kinds_by_id)
    return ValidatedContextLink(
        context_link_id=hint.context_link_id,
        reference_id=hint.reference_id,
        link_type=hint.link_type,
        source_role=hint.source_role,
        selector=hint.selector,
        selector_literal_candidate_id=hint.selector_literal_candidate_id,
        producer_frame_id=hint.producer_frame_id,
        consumer_frame_id=hint.consumer_frame_id,
        target_kind=(target_kind,),
        target_cardinality=(target_cardinality,),
        target_slot_kind=hint.target_slot_kind,
    )


def _link_target(
    hint: ContextLinkHint, source: _RoleShape
) -> tuple[ReferenceTargetKind, Cardinality]:
    if hint.link_type is ContextLinkType.CONSUME_SINGLE_RESULT:
        if source.target_kind is not ReferenceTargetKind.RESULT_SET:
            _invalid_graph()
        return ReferenceTargetKind.ENTITY, Cardinality.ONE
    if hint.link_type in {ContextLinkType.CONSUME_RESULT_SET, ContextLinkType.INHERIT_SCOPE}:
        if source.cardinality is not Cardinality.MANY:
            _invalid_graph()
        return source.target_kind, Cardinality.MANY
    if hint.link_type is ContextLinkType.DERIVE_ENTITY:
        if source.target_kind not in {ReferenceTargetKind.RELATED_ENTITY, ReferenceTargetKind.ENTITY}:
            _invalid_graph()
        return source.target_kind, Cardinality.ONE
    if hint.link_type is ContextLinkType.DERIVE_METRIC_VALUE:
        if source.target_kind is not ReferenceTargetKind.METRIC_VALUE:
            _invalid_graph()
        return source.target_kind, Cardinality.ONE
    if hint.link_type is ContextLinkType.REFER_EXCLUSION_SET:
        if source.target_kind is not ReferenceTargetKind.EXCLUSION_SET:
            _invalid_graph()
        return source.target_kind, Cardinality.MANY
    if hint.link_type is ContextLinkType.REFER_EVIDENCE:
        if source.target_kind is not ReferenceTargetKind.EVIDENCE_RECORDS:
            _invalid_graph()
        return source.target_kind, Cardinality.MANY
    if hint.link_type is ContextLinkType.REPLACE_SLOT:
        if not hint.target_slot_kind:
            _invalid_graph()
        return source.target_kind, source.cardinality
    _invalid_graph()
    raise AssertionError("unreachable")


def _validate_selector(
    hint: ContextLinkHint,
    source_cardinality: Cardinality,
    literal_kinds_by_id: dict[str, str],
) -> None:
    selector = hint.selector[0] if hint.selector else None
    literal_id = hint.selector_literal_candidate_id[0] if hint.selector_literal_candidate_id else None
    if source_cardinality is Cardinality.ONE:
        if selector is not None or literal_id is not None:
            _invalid_graph()
        return
    if hint.link_type is ContextLinkType.CONSUME_SINGLE_RESULT:
        if selector not in _SINGLE_SELECTORS:
            _invalid_graph()
    elif selector is not None and selector not in _SET_SELECTORS:
        _invalid_graph()
    if selector is Selector.RANK_POSITION:
        _require_literal_kind(literal_id, "rank_position", literal_kinds_by_id)
    elif selector is Selector.TOP_N:
        _require_literal_kind(literal_id, "result_limit", literal_kinds_by_id)
    elif literal_id is not None:
        _invalid_graph()


def _require_literal_kind(
    literal_id: str | None, expected_kind: str, literal_kinds_by_id: dict[str, str]
) -> None:
    if literal_id is None or literal_kinds_by_id.get(literal_id) != expected_kind:
        _invalid_graph()


def _validate_acyclic(links: tuple[ValidatedContextLink, ...]) -> None:
    edges: dict[str, set[str]] = {}
    for link in links:
        edges.setdefault(link.producer_frame_id, set()).add(link.consumer_frame_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(frame_id: str) -> None:
        if frame_id in visiting:
            _invalid_graph()
        if frame_id in visited:
            return
        visiting.add(frame_id)
        for child in sorted(edges.get(frame_id, ())):
            visit(child)
        visiting.remove(frame_id)
        visited.add(frame_id)

    for frame_id in sorted(edges):
        visit(frame_id)


def _validate_mutations(
    mutations: tuple[SlotMutation, ...], frames_by_id: dict[str, IntentFrameDraft]
) -> None:
    for mutation in mutations:
        consumer = frames_by_id.get(mutation.consumer_frame_id)
        source_id = mutation.source_frame_id[0] if mutation.source_frame_id else None
        source = frames_by_id.get(source_id) if source_id is not None else None
        if consumer is None:
            _invalid_graph()
        if mutation.mutation_kind is SlotMutationKind.CARRYOVER:
            if source is None or source.ordinal >= consumer.ordinal:
                _invalid_graph()
            if not any(slot.slot_kind is mutation.slot_kind for slot in source.slot_assignments):
                _invalid_graph()
        elif source is not None:
            _invalid_graph()


def _append_context_issues(
    state: SemanticValidationState,
    links: tuple[ValidatedContextLink, ...],
    frames_by_id: dict[str, IntentFrameDraft],
    references_by_id: dict[str, ReferenceHint],
) -> tuple[ResolutionIssue, ...]:
    records: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    linked_reference_ids = {link.reference_id for link in links}
    for reference in references_by_id.values():
        candidate_ids = reference.candidate_target_frame_ids
        if reference.status == "resolved" and reference.grammatical_number == ("singular",) and len(candidate_ids) > 1:
            records.append(("REFERENCE_AMBIGUOUS", (reference.reference_id, *candidate_ids), reference.evidence_span_ids))
        elif reference.status == "resolved" and not candidate_ids and reference.reference_id not in linked_reference_ids:
            records.append(("REFERENCE_UNRESOLVED", (reference.reference_id,), reference.evidence_span_ids))
    linked_anchor_frames = {
        link.consumer_frame_id
        for link in links
        if link.target_slot_kind == (SlotKind.SIMILARITY_ANCHOR,)
    }
    for frame in frames_by_id.values():
        if frame.action_choice.selected_ids == (IntentType.SIMILAR,) and not _has_similarity_anchor(frame) and frame.frame_id not in linked_anchor_frames:
            records.append(("REFERENCE_UNRESOLVED", (frame.frame_id,), frame.evidence_span_ids))
    for mutation in state.draft.slot_mutations:
        if mutation.mutation_kind is not SlotMutationKind.CARRYOVER:
            continue
        consumer = frames_by_id[mutation.consumer_frame_id]
        source = frames_by_id[mutation.source_frame_id[0]]
        current_slots = [slot for slot in consumer.slot_assignments if slot.slot_kind is mutation.slot_kind]
        source_slots = [slot for slot in source.slot_assignments if slot.slot_kind is mutation.slot_kind]
        if current_slots and source_slots and any(current.value_ids != source_slots[0].value_ids for current in current_slots):
            records.append(("AMBIGUITY_UNRESOLVED", (mutation.slot_mutation_id, consumer.frame_id, source.frame_id), mutation.evidence_span_ids))
    existing = {(issue.code, issue.related_ids, issue.evidence_span_ids) for issue in state.issues}
    appended = [record for record in records if record not in existing]
    return (*state.issues, *(
        ResolutionIssue(
            issue_id=f"issue-context-{index}-{code.lower()}",
            code=code,
            related_ids=related_ids,
            evidence_span_ids=evidence_span_ids,
        )
        for index, (code, related_ids, evidence_span_ids) in enumerate(appended, start=1)
    ))


def _has_similarity_anchor(frame: IntentFrameDraft) -> bool:
    return any(slot.slot_kind is SlotKind.SIMILARITY_ANCHOR for slot in frame.slot_assignments)


def _resolution_status(issues: tuple[ResolutionIssue, ...]) -> ResolutionStatus:
    codes = {issue.code for issue in issues}
    active = {ResolutionStatus.RESOLVED}
    if "SEMANTIC_CONCEPT_UNMAPPED" in codes:
        active.add(ResolutionStatus.UNMAPPED)
    if "REFERENCE_UNRESOLVED" in codes:
        active.add(ResolutionStatus.CONTEXT_UNRESOLVED)
    if {"AMBIGUITY_UNRESOLVED", "REFERENCE_AMBIGUOUS"} & codes:
        active.add(ResolutionStatus.AMBIGUOUS)
    return next(status for status in STATUS_PRECEDENCE if status in active)


def _validated_frame(
    frame: IntentFrameDraft,
    mutations: list[ValidatedSlotMutation] | tuple[ValidatedSlotMutation, ...],
    issues: tuple[ResolutionIssue, ...],
) -> ValidatedIntentFrame:
    frame_status = _frame_status(frame.frame_id, issues)
    return ValidatedIntentFrame(
        frame_id=frame.frame_id,
        ordinal=frame.ordinal,
        frame_status=frame_status,
        segment_ids=frame.segment_ids,
        evidence_span_ids=frame.evidence_span_ids,
        action_choice=frame.action_choice,
        product_family_choice=frame.product_family_choice,
        entity_type_ids=frame.entity_type_ids,
        entity_hint_ids=frame.entity_hint_ids,
        slot_assignments=frame.slot_assignments,
        produced_result_roles=frame.produced_result_hints,
        slot_mutations=tuple(sorted(mutations, key=lambda mutation: mutation.slot_mutation_id)),
    )


def _frame_status(frame_id: str, issues: tuple[ResolutionIssue, ...]) -> ResolutionStatus:
    relevant = tuple(issue for issue in issues if frame_id in issue.related_ids)
    return _resolution_status(relevant)


def _context_events() -> tuple[ValidationEvent, ...]:
    return (
        ValidationEvent(event_id="validation-frame-order", stage="frame_order", code="VALIDATED", related_ids=()),
        ValidationEvent(event_id="validation-slot-mutations", stage="slot_mutations", code="VALIDATED", related_ids=()),
    )


def _invalid_graph() -> None:
    raise ResolverContractError("INVALID_CONTEXT_GRAPH")
