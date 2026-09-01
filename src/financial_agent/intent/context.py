"""Fail-closed validation and finalization of typed intent context."""

from __future__ import annotations

from dataclasses import dataclass

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex, UtcDateTime
from financial_agent.contracts.enums import Cardinality, IntentType

from .draft import (
    ContextLinkHint,
    IntentFrameDraft,
    IntentFrameDraftV2,
    IntentResolutionDraftV2,
    ReferenceHint,
    SlotMutation,
)
from .errors import ResolverContractError
from .resolution import (
    ResolverBuildManifest,
    ResolutionIssue,
    ValidatedContextLink,
    ValidatedIntentFrame,
    ValidatedIntentFrameV2,
    ValidatedIntentResolution,
    ValidatedIntentResolutionV2,
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
    frame_statuses: tuple[tuple[str, ResolutionStatus], ...]


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
    blocked_reference_ids = _validate_reference_targets(
        references_by_id.values(),
        frames_by_id,
        set(state.offered_target_mention_ids),
    )
    raw_links = tuple(
        _validate_link(hint, references_by_id, frames_by_id, dict(state.literal_kinds_by_id))
        for hint in state.draft.context_link_hints
    )
    _validate_acyclic(raw_links)
    links = tuple(
        link for link in raw_links if link.reference_id not in blocked_reference_ids
    )
    _validate_mutations(state.draft.slot_mutations, frames_by_id)

    issues = _append_context_issues(
        state,
        links,
        frames_by_id,
        references_by_id,
        blocked_reference_ids,
    )
    return ContextValidationState(
        semantic_state=state,
        context_links=tuple(sorted(links, key=lambda link: link.context_link_id)),
        issues=issues,
        resolution_status=_resolution_status(issues),
        validation_events=(*state.validation_events, *_context_events()),
        frame_statuses=_frame_statuses(state, issues, frames_by_id, references_by_id),
    )


def finalize_resolution(
    context_state: ContextValidationState,
    metadata: ResolutionFinalizationMetadata,
) -> ValidatedIntentResolution | ValidatedIntentResolutionV2:
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
        _validated_frame(
            frame,
            mutations_by_frame.get(frame.frame_id, ()),
            dict(context_state.frame_statuses).get(frame.frame_id, ResolutionStatus.RESOLVED),
        )
        for frame in context_state.semantic_state.canonical_frames
    )
    is_v2 = isinstance(context_state.semantic_state.draft, IntentResolutionDraftV2)
    if is_v2 and metadata.build_manifest.resolver_schema_version != "2.0":
        raise ResolverContractError("MODEL_INVALID_SEMANTIC_COVERAGE")
    resolution_type = ValidatedIntentResolutionV2 if is_v2 else ValidatedIntentResolution
    resolution_payload: dict[str, object] = {
        "request_key": metadata.request_key,
        "run_id": metadata.run_id,
        "dataset_version": metadata.dataset_version,
        "producer": metadata.producer,
        "created_at": metadata.created_at,
        "resolution_id": metadata.resolution_id,
        "draft_hash": metadata.draft_hash,
        "canonical_frames": canonical_frames,
        "context_links": context_state.context_links,
        "final_tags": context_state.semantic_state.final_tags,
        "resolution_status": context_state.resolution_status,
        "issues": context_state.issues,
        "validation_events": context_state.validation_events,
        "build_manifest": metadata.build_manifest,
        "active_dataset_manifest_hash": metadata.active_dataset_manifest_hash,
        "repair_used": False,
        "invalid_attempt_hashes": (),
    }
    if is_v2:
        resolution_payload["entity_hints"] = context_state.semantic_state.draft.entity_hints
    return resolution_type(**resolution_payload)


def _validate_reference_targets(
    references: object,
    frames_by_id: dict[str, IntentFrameDraft],
    offered_target_mention_ids: set[str],
) -> frozenset[str]:
    blocked: set[str] = set()
    for reference in references:  # type: ignore[union-attr]
        if not set(reference.candidate_target_frame_ids) <= set(frames_by_id):
            _invalid_graph()
        if not set(reference.candidate_target_mention_ids) <= offered_target_mention_ids:
            _invalid_graph()
        if reference.status != "resolved":
            blocked.add(reference.reference_id)
        if (
            reference.status == "resolved"
            and reference.grammatical_number == ("singular",)
            and len(
                (*reference.candidate_target_frame_ids, *reference.candidate_target_mention_ids)
            ) > 1
        ):
            blocked.add(reference.reference_id)
    return frozenset(blocked)


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
    if hint.producer_frame_id not in reference.candidate_target_frame_ids:
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
        if source != _RoleShape(ReferenceTargetKind.RESULT_SET, Cardinality.MANY):
            _invalid_graph()
        return ReferenceTargetKind.ENTITY, Cardinality.ONE
    if hint.link_type is ContextLinkType.CONSUME_RESULT_SET:
        if source != _RoleShape(ReferenceTargetKind.RESULT_SET, Cardinality.MANY):
            _invalid_graph()
        return ReferenceTargetKind.RESULT_SET, Cardinality.MANY
    if hint.link_type is ContextLinkType.DERIVE_ENTITY:
        if source != _RoleShape(ReferenceTargetKind.RELATED_ENTITY, Cardinality.ONE):
            _invalid_graph()
        return ReferenceTargetKind.RELATED_ENTITY, Cardinality.ONE
    if hint.link_type is ContextLinkType.DERIVE_METRIC_VALUE:
        if source != _RoleShape(ReferenceTargetKind.METRIC_VALUE, Cardinality.ONE):
            _invalid_graph()
        return ReferenceTargetKind.METRIC_VALUE, Cardinality.ONE
    if hint.link_type is ContextLinkType.INHERIT_SCOPE:
        if source not in {
            _RoleShape(ReferenceTargetKind.ENTITY, Cardinality.ONE),
            _RoleShape(ReferenceTargetKind.RESULT_SET, Cardinality.MANY),
        }:
            _invalid_graph()
        return source.target_kind, source.cardinality
    if hint.link_type is ContextLinkType.REFER_EXCLUSION_SET:
        if source != _RoleShape(ReferenceTargetKind.EXCLUSION_SET, Cardinality.MANY):
            _invalid_graph()
        return ReferenceTargetKind.EXCLUSION_SET, Cardinality.MANY
    if hint.link_type is ContextLinkType.REFER_EVIDENCE:
        if source != _RoleShape(ReferenceTargetKind.EVIDENCE_RECORDS, Cardinality.MANY):
            _invalid_graph()
        return ReferenceTargetKind.EVIDENCE_RECORDS, Cardinality.MANY
    if hint.link_type is ContextLinkType.REPLACE_SLOT:
        if not hint.target_slot_kind:
            _invalid_graph()
        if (
            hint.target_slot_kind == (SlotKind.ENTITY,)
            and source
            in {
                _RoleShape(ReferenceTargetKind.ENTITY, Cardinality.ONE),
                _RoleShape(ReferenceTargetKind.RELATED_ENTITY, Cardinality.ONE),
            }
        ):
            return source.target_kind, source.cardinality
        if (
            hint.target_slot_kind == (SlotKind.METRIC,)
            and source == _RoleShape(ReferenceTargetKind.METRIC_VALUE, Cardinality.ONE)
        ):
            return source.target_kind, source.cardinality
        if (
            hint.target_slot_kind == (SlotKind.SIMILARITY_ANCHOR,)
            and source
            in {
                _RoleShape(ReferenceTargetKind.ENTITY, Cardinality.ONE),
                _RoleShape(ReferenceTargetKind.RELATED_ENTITY, Cardinality.ONE),
            }
        ):
            return source.target_kind, source.cardinality
        _invalid_graph()
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
    mutated_slots: set[tuple[str, SlotKind]] = set()
    for mutation in mutations:
        consumer = frames_by_id.get(mutation.consumer_frame_id)
        source_id = mutation.source_frame_id[0] if mutation.source_frame_id else None
        source = frames_by_id.get(source_id) if source_id is not None else None
        key = (mutation.consumer_frame_id, mutation.slot_kind)
        if (
            consumer is None
            or not mutation.evidence_span_ids
            or not set(mutation.evidence_span_ids) <= set(consumer.evidence_span_ids)
            or key in mutated_slots
        ):
            _invalid_graph()
        mutated_slots.add(key)
        if source_id is not None:
            if source is None or source.ordinal >= consumer.ordinal:
                _invalid_graph()
            if not _has_explicit_slot(source, mutation.slot_kind):
                _invalid_graph()
        if mutation.mutation_kind is SlotMutationKind.CARRYOVER and source is None:
            _invalid_graph()
        if mutation.mutation_kind is SlotMutationKind.UPDATE and not _has_explicit_slot(
            consumer, mutation.slot_kind
        ):
            _invalid_graph()


def _has_explicit_slot(frame: IntentFrameDraft, slot_kind: SlotKind) -> bool:
    return any(
        assignment.slot_kind is slot_kind
        and bool(assignment.value_ids)
        and bool(assignment.evidence_span_ids)
        for assignment in frame.slot_assignments
    )


def _append_context_issues(
    state: SemanticValidationState,
    links: tuple[ValidatedContextLink, ...],
    frames_by_id: dict[str, IntentFrameDraft],
    references_by_id: dict[str, ReferenceHint],
    blocked_reference_ids: frozenset[str],
) -> tuple[ResolutionIssue, ...]:
    records: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    linked_reference_ids = {link.reference_id for link in links}
    for reference in references_by_id.values():
        if reference.reference_id in blocked_reference_ids:
            records.append(
                (
                    "REFERENCE_AMBIGUOUS"
                    if reference.status == "ambiguous"
                    or (
                        reference.status == "resolved"
                        and reference.grammatical_number == ("singular",)
                    )
                    else "REFERENCE_UNRESOLVED",
                    (reference.reference_id,),
                    reference.evidence_span_ids,
                )
            )
        elif (
            reference.status == "resolved"
            and reference.reference_id not in linked_reference_ids
        ):
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
        consumer = frames_by_id[mutation.consumer_frame_id]
        current_slots = [
            slot for slot in consumer.slot_assignments if slot.slot_kind is mutation.slot_kind
        ]
        if mutation.mutation_kind is SlotMutationKind.CARRYOVER:
            source = frames_by_id[mutation.source_frame_id[0]]
            source_slots = [
                slot for slot in source.slot_assignments if slot.slot_kind is mutation.slot_kind
            ]
            if current_slots and source_slots and any(
                current.value_ids != source_slots[0].value_ids for current in current_slots
            ):
                records.append(
                    (
                        "AMBIGUITY_UNRESOLVED",
                        (mutation.slot_mutation_id, consumer.frame_id),
                        mutation.evidence_span_ids,
                    )
                )
        elif mutation.mutation_kind in {SlotMutationKind.DELETE, SlotMutationKind.DONTCARE} and current_slots:
            records.append(
                (
                    "AMBIGUITY_UNRESOLVED",
                    (mutation.slot_mutation_id, consumer.frame_id),
                    mutation.evidence_span_ids,
                )
            )
    for link in links:
        if (
            link.link_type is ContextLinkType.REPLACE_SLOT
            and link.target_slot_kind
            and _has_explicit_slot(frames_by_id[link.consumer_frame_id], link.target_slot_kind[0])
        ):
            records.append(
                (
                    "AMBIGUITY_UNRESOLVED",
                    (link.context_link_id, link.consumer_frame_id),
                    references_by_id[link.reference_id].evidence_span_ids,
                )
            )
    for link in links:
        if link.link_type is not ContextLinkType.REPLACE_SLOT or not link.target_slot_kind:
            continue
        if any(
            mutation.consumer_frame_id == link.consumer_frame_id
            and mutation.slot_kind is link.target_slot_kind[0]
            and mutation.mutation_kind is SlotMutationKind.CARRYOVER
            for mutation in state.draft.slot_mutations
        ):
            records.append(
                (
                    "AMBIGUITY_UNRESOLVED",
                    (link.context_link_id, link.consumer_frame_id),
                    references_by_id[link.reference_id].evidence_span_ids,
                )
            )
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
    return _has_explicit_slot(frame, SlotKind.SIMILARITY_ANCHOR)


def _resolution_status(issues: tuple[ResolutionIssue, ...]) -> ResolutionStatus:
    codes = {issue.code for issue in issues}
    active = {ResolutionStatus.RESOLVED}
    if {
        "SEMANTIC_CONCEPT_UNMAPPED",
        "SEMANTIC_DOMAIN_UNMAPPED",
        "SEMANTIC_OPERATION_UNSUPPORTED",
        "SEMANTIC_CRITICAL_SLOT_MISSING",
    } & codes:
        active.add(ResolutionStatus.UNMAPPED)
    if "REFERENCE_UNRESOLVED" in codes:
        active.add(ResolutionStatus.CONTEXT_UNRESOLVED)
    if {"AMBIGUITY_UNRESOLVED", "REFERENCE_AMBIGUOUS"} & codes:
        active.add(ResolutionStatus.AMBIGUOUS)
    return next(status for status in STATUS_PRECEDENCE if status in active)


def _validated_frame(
    frame: IntentFrameDraft,
    mutations: list[ValidatedSlotMutation] | tuple[ValidatedSlotMutation, ...],
    frame_status: ResolutionStatus,
) -> ValidatedIntentFrame | ValidatedIntentFrameV2:
    values = {
        "frame_id": frame.frame_id,
        "ordinal": frame.ordinal,
        "frame_status": frame_status,
        "segment_ids": frame.segment_ids,
        "evidence_span_ids": frame.evidence_span_ids,
        "action_choice": frame.action_choice,
        "product_family_choice": frame.product_family_choice,
        "entity_type_ids": frame.entity_type_ids,
        "entity_hint_ids": frame.entity_hint_ids,
        "slot_assignments": frame.slot_assignments,
        "produced_result_roles": frame.produced_result_hints,
        "slot_mutations": tuple(sorted(mutations, key=lambda mutation: mutation.slot_mutation_id)),
    }
    if isinstance(frame, IntentFrameDraftV2):
        return ValidatedIntentFrameV2(
            **values,
            semantic_coverage=frame.semantic_coverage,
        )
    return ValidatedIntentFrame(
        **values,
    )


def _frame_statuses(
    state: SemanticValidationState,
    issues: tuple[ResolutionIssue, ...],
    frames_by_id: dict[str, IntentFrameDraft],
    references_by_id: dict[str, ReferenceHint],
) -> tuple[tuple[str, ResolutionStatus], ...]:
    codes_by_frame: dict[str, set[str]] = {frame_id: set() for frame_id in frames_by_id}
    raw_links_by_reference: dict[str, set[str]] = {}
    for link in state.draft.context_link_hints:
        if link.consumer_frame_id in frames_by_id:
            raw_links_by_reference.setdefault(link.reference_id, set()).add(
                link.consumer_frame_id
            )
    mutations_by_id = {
        mutation.slot_mutation_id: mutation for mutation in state.draft.slot_mutations
    }
    for issue in issues:
        affected = {related_id for related_id in issue.related_ids if related_id in frames_by_id}
        for related_id in issue.related_ids:
            affected.update(raw_links_by_reference.get(related_id, ()))
            mutation = mutations_by_id.get(related_id)
            if mutation is not None:
                affected.add(mutation.consumer_frame_id)
        if issue.code in {"REFERENCE_UNRESOLVED", "REFERENCE_AMBIGUOUS"}:
            for related_id in issue.related_ids:
                reference = references_by_id.get(related_id)
                if reference is not None and not raw_links_by_reference.get(related_id):
                    affected.update(
                        frame.frame_id
                        for frame in frames_by_id.values()
                        if reference.segment_id in frame.segment_ids
                    )
        for frame_id in affected:
            codes_by_frame[frame_id].add(issue.code)
    return tuple(
        (
            frame_id,
            _resolution_status(
                tuple(
                    ResolutionIssue(
                        issue_id=f"frame-status-{frame_id}-{code.lower()}",
                        code=code,
                        related_ids=(frame_id,),
                        evidence_span_ids=(),
                    )
                    for code in sorted(codes)
                )
            ),
        )
        for frame_id, codes in sorted(codes_by_frame.items())
    )


def _context_events() -> tuple[ValidationEvent, ...]:
    return (
        ValidationEvent(event_id="validation-frame-order", stage="frame_order", code="VALIDATED", related_ids=()),
        ValidationEvent(event_id="validation-slot-mutations", stage="slot_mutations", code="VALIDATED", related_ids=()),
    )


def _invalid_graph() -> None:
    raise ResolverContractError("INVALID_CONTEXT_GRAPH")
