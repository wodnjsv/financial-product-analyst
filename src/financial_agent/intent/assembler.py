"""Deterministically assemble a bounded model proposal into the legacy draft."""

from __future__ import annotations

from collections.abc import Iterable

from financial_agent.contracts.enums import IntentType, ProductFamily

from .draft import (
    ActionChoice,
    ContextLinkHint,
    EntityHint,
    EvidenceSpan,
    IntentFrameDraft,
    IntentFrameDraftV2,
    IntentResolutionDraft,
    IntentResolutionDraftV2,
    ProductFamilyChoice,
    ReferenceHint,
    SemanticFlagHint,
    SlotAssignment,
    SlotMutation,
)
from .errors import (
    MODEL_INVALID_FRAME_REFERENCE,
    MODEL_INVALID_SEMANTIC_COVERAGE,
    MODEL_PROPOSAL_SCHEMA_INVALID,
    MODEL_UNKNOWN_EVIDENCE_ID,
    ResolverContractError,
)
from .proposal import (
    FrameSemanticCoverage,
    IntentResolutionProposalV2,
    ProposedIntentFrame,
)
from .types import (
    ChoiceState,
    SemanticCoverageReason,
    SemanticCoverageState,
    SlotKind,
)
from .normalization import NormalizedRequest
from .view import ResolverView


_CONCEPT_SLOTS = frozenset(
    {
        SlotKind.METRIC,
        SlotKind.SORT_KEY,
        SlotKind.COMPARISON_BASIS,
        SlotKind.SIMILARITY_ANCHOR,
        SlotKind.DOCUMENT_TOPIC,
    }
)
_LITERAL_KINDS_BY_SLOT = {
    SlotKind.FILTER_VALUE: frozenset(
        {"number", "percentage", "money", "currency", "date", "period"}
    ),
    SlotKind.PERIOD: frozenset({"period"}),
    SlotKind.CURRENCY: frozenset({"currency"}),
    SlotKind.SORT_DIRECTION: frozenset({"sort_direction"}),
    SlotKind.RESULT_LIMIT: frozenset({"result_limit"}),
    SlotKind.DATE_SCOPE: frozenset({"date"}),
}


def assemble_proposal(
    proposal: IntentResolutionProposalV2,
    normalized: NormalizedRequest,
    view: ResolverView,
) -> IntentResolutionDraft:
    """Translate only server-offered proposal choices into canonical draft IDs."""
    if not isinstance(proposal, IntentResolutionProposalV2):
        raise ResolverContractError(MODEL_PROPOSAL_SCHEMA_INVALID)

    _validate_offered_ids(proposal, view)
    _validate_ordinals(proposal)
    _validate_semantic_coverage(proposal)
    _validate_normalized_segments(proposal, normalized)

    frames = tuple(
        _assemble_frame(index, item, normalized)
        for index, item in enumerate(proposal.frames)
    )
    return IntentResolutionDraftV2(
        evidence_spans=_selected_evidence_spans(proposal, view),
        intent_frames=frames,
        entity_hints=_assemble_entity_hints(proposal),
        reference_hints=_assemble_references(proposal, view, frames),
        context_link_hints=_assemble_links(proposal, frames),
        slot_mutations=_assemble_mutations(proposal, frames),
        semantic_flag_hints=_assemble_flags(proposal),
        frame_limit_exceeded=proposal.frame_limit_exceeded,
    )


def _validate_offered_ids(proposal: IntentResolutionProposalV2, view: ResolverView) -> None:
    evidence_ids = {item.evidence_id for item in view.evidence_candidates}
    segment_ids = {
        item.segment_id
        for item in (
            *view.evidence_candidates,
            *view.literal_candidates,
            *view.reference_candidates,
        )
    }
    entity_ids_by_mention = {
        group.mention_id: {item.entity_id for item in group.items}
        for group in view.entity_candidates
    }
    entity_ids = (
        set().union(*entity_ids_by_mention.values())
        if entity_ids_by_mention
        else set()
    )
    literal_by_id = {item.literal_id: item for item in view.literal_candidates}
    concept_ids = {item.concept_id for item in view.concept_definitions}
    relation_ids = {item.relation_id for item in view.relation_definitions}
    operator_ids = {
        value
        for item in (*view.concept_definitions, *view.relation_definitions)
        for value in item.required_qualifiers
    } | {
        value for item in view.concept_definitions for value in item.allowed_operators
    }
    reference_by_id = {
        item.reference_id: item for item in view.reference_candidates
    }
    reference_ids = set(reference_by_id)
    evidence_coordinates = {
        (item.segment_id, item.start_char, item.end_char, item.text)
        for item in view.evidence_candidates
    }

    for frame in proposal.frames:
        _require_subset(frame.segment_ids, segment_ids)
        _validate_choice(frame.action_choice.state, frame.action_choice.selected_ids, view.action_ids)
        _validate_choice(
            frame.product_family_choice.state,
            frame.product_family_choice.selected_ids,
            view.product_family_ids,
        )
        _require_evidence(frame.action_choice.evidence_ids, evidence_ids)
        _require_evidence(frame.product_family_choice.evidence_ids, evidence_ids)
        _require_evidence(frame.semantic_coverage.evidence_ids, evidence_ids)
        for assignment in frame.slot_assignments:
            _require_evidence(assignment.evidence_ids, evidence_ids)
            _validate_slot_values(
                assignment.slot_kind,
                assignment.value_ids,
                entity_ids,
                literal_by_id,
                concept_ids,
                relation_ids,
                operator_ids,
            )
        for hint in frame.entity_hints:
            if hint.mention_id:
                mention_id = hint.mention_id[0]
                allowed = entity_ids_by_mention.get(mention_id)
                if allowed is None:
                    _schema_invalid()
                _require_subset(hint.candidate_entity_ids, allowed)
            elif hint.candidate_entity_ids:
                _schema_invalid()
            else:
                _require_subset(hint.candidate_entity_ids, entity_ids)

    if len({item.reference_id for item in proposal.references}) != len(proposal.references):
        _schema_invalid()
    for reference in proposal.references:
        _require_subset((reference.reference_id,), reference_ids)
        candidate = reference_by_id[reference.reference_id]
        if (
            candidate.segment_id,
            candidate.start_char,
            candidate.end_char,
            candidate.text,
        ) not in evidence_coordinates:
            raise ResolverContractError(MODEL_UNKNOWN_EVIDENCE_ID)
    for link in proposal.context_links:
        _require_subset((link.reference_id,), reference_ids)
        _require_subset(link.selector_literal_candidate_id, literal_by_id)
    for mutation in proposal.slot_mutations:
        _require_evidence(mutation.evidence_ids, evidence_ids)
    for flag in proposal.semantic_flag_hints:
        _require_evidence(flag.evidence_ids, evidence_ids)


def _validate_choice(
    state: ChoiceState, selected_ids: tuple[str, ...], offered: Iterable[str]
) -> None:
    if (state is ChoiceState.SELECTED) != bool(selected_ids):
        _schema_invalid()
    _require_subset(selected_ids, offered)


def _validate_slot_values(
    kind: SlotKind,
    values: tuple[str, ...],
    entity_ids: set[str],
    literal_by_id: dict[str, object],
    concept_ids: set[str],
    relation_ids: set[str],
    operator_ids: set[str],
) -> None:
    if kind is SlotKind.ENTITY:
        _require_subset(values, entity_ids)
    elif kind is SlotKind.RELATION:
        _require_subset(values, relation_ids)
    elif kind in _CONCEPT_SLOTS:
        _require_subset(values, concept_ids)
    elif kind is SlotKind.FILTER_OPERATOR:
        _require_subset(values, operator_ids)
    elif kind in _LITERAL_KINDS_BY_SLOT:
        allowed = {
            literal_id
            for literal_id, literal in literal_by_id.items()
            if getattr(literal, "kind") in _LITERAL_KINDS_BY_SLOT[kind]
        }
        _require_subset(values, allowed)
    else:
        _schema_invalid()


def _validate_ordinals(proposal: IntentResolutionProposalV2) -> None:
    frame_count = len(proposal.frames)
    reference_ordinals = {
        reference.reference_id: set(reference.producer_frame_ordinals)
        for reference in proposal.references
    }
    for reference in proposal.references:
        _require_ordinals(reference.producer_frame_ordinals, frame_count)
    for link in proposal.context_links:
        _require_ordinals(
            (link.producer_frame_ordinal, link.consumer_frame_ordinal), frame_count
        )
        if (
            link.producer_frame_ordinal >= link.consumer_frame_ordinal
            or link.reference_id not in reference_ordinals
            or link.producer_frame_ordinal not in reference_ordinals[link.reference_id]
            or link.source_role
            not in proposal.frames[link.producer_frame_ordinal].produced_result_hints
        ):
            raise ResolverContractError(MODEL_INVALID_FRAME_REFERENCE)
    for mutation in proposal.slot_mutations:
        _require_ordinals((mutation.consumer_frame_ordinal,), frame_count)
        if mutation.source_frame_ordinal:
            source = mutation.source_frame_ordinal[0]
            _require_ordinals((source,), frame_count)
            if source >= mutation.consumer_frame_ordinal:
                raise ResolverContractError(MODEL_INVALID_FRAME_REFERENCE)


def _validate_semantic_coverage(proposal: IntentResolutionProposalV2) -> None:
    for frame in proposal.frames:
        coverage = frame.semantic_coverage
        if coverage.state is SemanticCoverageState.COVERED:
            valid = coverage.reason is SemanticCoverageReason.NONE and not coverage.evidence_ids
        else:
            valid = (
                coverage.reason is not SemanticCoverageReason.NONE
                and bool(coverage.evidence_ids)
            )
        if not valid:
            raise ResolverContractError(MODEL_INVALID_SEMANTIC_COVERAGE)


def _validate_normalized_segments(
    proposal: IntentResolutionProposalV2, normalized: NormalizedRequest
) -> None:
    available = {segment.segment_id for segment in normalized.segments}
    for frame in proposal.frames:
        _require_subset(frame.segment_ids, available)


def _assemble_frame(
    index: int, item: ProposedIntentFrame, normalized: NormalizedRequest
) -> IntentFrameDraftV2:
    entity_hint_ids = tuple(
        f"entity-hint-{index:04d}-{entity_index:04d}"
        for entity_index, _ in enumerate(item.entity_hints)
    )
    normalized_by_id = {segment.segment_id: segment for segment in normalized.segments}
    return IntentFrameDraftV2(
        frame_id=f"frame-{index:04d}",
        ordinal=index,
        segment_ids=item.segment_ids,
        evidence_span_ids=_frame_evidence_ids(item),
        normalized_intent_argument=" ".join(
            normalized_by_id[segment_id].normalized_text for segment_id in item.segment_ids
        ),
        action_choice=ActionChoice(
            state=item.action_choice.state,
            selected_ids=tuple(IntentType(value) for value in item.action_choice.selected_ids),
            evidence_span_ids=item.action_choice.evidence_ids,
            reason_code=item.action_choice.reason_code,
        ),
        product_family_choice=ProductFamilyChoice(
            state=item.product_family_choice.state,
            selected_ids=tuple(
                ProductFamily(value) for value in item.product_family_choice.selected_ids
            ),
            evidence_span_ids=item.product_family_choice.evidence_ids,
            reason_code=item.product_family_choice.reason_code,
        ),
        entity_type_ids=(),
        entity_hint_ids=entity_hint_ids,
        slot_assignments=tuple(
            SlotAssignment(
                slot_assignment_id=f"slot-{index:04d}-{slot_index:04d}",
                slot_kind=assignment.slot_kind,
                value_ids=assignment.value_ids,
                evidence_span_ids=assignment.evidence_ids,
                reason_code=assignment.reason_code,
            )
            for slot_index, assignment in enumerate(item.slot_assignments)
        ),
        produced_result_hints=item.produced_result_hints,
        semantic_coverage=(item.semantic_coverage,),
    )


def _assemble_entity_hints(
    proposal: IntentResolutionProposalV2,
) -> tuple[EntityHint, ...]:
    return tuple(
        EntityHint(
            entity_hint_id=f"entity-hint-{frame_index:04d}-{hint_index:04d}",
            mention_id=hint.mention_id,
            evidence_span_ids=(),
            expected_entity_type_ids=(),
            candidate_entity_ids=hint.candidate_entity_ids,
            selected_candidate_ids=(),
            reason_code="implicit",
        )
        for frame_index, frame in enumerate(proposal.frames)
        for hint_index, hint in enumerate(frame.entity_hints)
    )


def _assemble_references(
    proposal: IntentResolutionProposalV2,
    view: ResolverView,
    frames: tuple[IntentFrameDraft, ...],
) -> tuple[ReferenceHint, ...]:
    evidence_by_coordinates = {
        (item.segment_id, item.start_char, item.end_char, item.text): item.evidence_id
        for item in view.evidence_candidates
    }
    candidates_by_id = {item.reference_id: item for item in view.reference_candidates}
    hints: list[ReferenceHint] = []
    for item in proposal.references:
        candidate = candidates_by_id[item.reference_id]
        evidence_id = evidence_by_coordinates.get(
            (candidate.segment_id, candidate.start_char, candidate.end_char, candidate.text)
        )
        if evidence_id is None:
            raise ResolverContractError(MODEL_UNKNOWN_EVIDENCE_ID)
        hints.append(
            ReferenceHint(
                reference_id=item.reference_id,
                segment_id=candidate.segment_id,
                evidence_span_ids=(evidence_id,),
                surface_presence=item.surface_presence,
                reference_form=item.reference_form,
                grammatical_number=item.grammatical_number,
                expected_target_kind=item.expected_target_kind,
                expected_cardinality=item.expected_cardinality,
                candidate_target_frame_ids=tuple(
                    frames[ordinal].frame_id for ordinal in item.producer_frame_ordinals
                ),
                candidate_target_mention_ids=(),
                status=item.status,
                reason_code=item.reason_code,
            )
        )
    return tuple(hints)


def _assemble_links(
    proposal: IntentResolutionProposalV2, frames: tuple[IntentFrameDraft, ...]
) -> tuple[ContextLinkHint, ...]:
    return tuple(
        ContextLinkHint(
            context_link_id=f"link-{index:04d}",
            reference_id=item.reference_id,
            link_type=item.link_type,
            source_role=item.source_role,
            selector=item.selector,
            selector_literal_candidate_id=item.selector_literal_candidate_id,
            producer_frame_id=frames[item.producer_frame_ordinal].frame_id,
            consumer_frame_id=frames[item.consumer_frame_ordinal].frame_id,
            target_slot_kind=item.target_slot_kind,
        )
        for index, item in enumerate(proposal.context_links)
    )


def _assemble_mutations(
    proposal: IntentResolutionProposalV2, frames: tuple[IntentFrameDraft, ...]
) -> tuple[SlotMutation, ...]:
    return tuple(
        SlotMutation(
            slot_mutation_id=f"mutation-{index:04d}",
            consumer_frame_id=frames[item.consumer_frame_ordinal].frame_id,
            slot_kind=item.slot_kind,
            mutation_kind=item.mutation_kind,
            source_frame_id=tuple(
                frames[ordinal].frame_id for ordinal in item.source_frame_ordinal
            ),
            evidence_span_ids=item.evidence_ids,
            reason_code=item.reason_code,
        )
        for index, item in enumerate(proposal.slot_mutations)
    )


def _assemble_flags(proposal: IntentResolutionProposalV2) -> tuple[SemanticFlagHint, ...]:
    return tuple(
        SemanticFlagHint(
            semantic_tag=item.semantic_tag,
            evidence_span_ids=item.evidence_ids,
            reason_code=item.reason_code,
        )
        for item in proposal.semantic_flag_hints
    )


def _selected_evidence_spans(
    proposal: IntentResolutionProposalV2, view: ResolverView
) -> tuple[EvidenceSpan, ...]:
    selected = set(_selected_evidence_ids(proposal, view))
    return tuple(
        EvidenceSpan(
            span_id=item.evidence_id,
            segment_id=item.segment_id,
            start_char=item.start_char,
            end_char=item.end_char,
            text=item.text,
        )
        for item in view.evidence_candidates
        if item.evidence_id in selected
    )


def _selected_evidence_ids(
    proposal: IntentResolutionProposalV2, view: ResolverView
) -> tuple[str, ...]:
    selected: set[str] = set()
    for frame in proposal.frames:
        selected.update(frame.action_choice.evidence_ids)
        selected.update(frame.product_family_choice.evidence_ids)
        selected.update(frame.semantic_coverage.evidence_ids)
        for slot in frame.slot_assignments:
            selected.update(slot.evidence_ids)
    for mutation in proposal.slot_mutations:
        selected.update(mutation.evidence_ids)
    for flag in proposal.semantic_flag_hints:
        selected.update(flag.evidence_ids)

    evidence_by_coordinates = {
        (item.segment_id, item.start_char, item.end_char, item.text): item.evidence_id
        for item in view.evidence_candidates
    }
    references_by_id = {item.reference_id: item for item in view.reference_candidates}
    for reference in proposal.references:
        candidate = references_by_id[reference.reference_id]
        evidence_id = evidence_by_coordinates.get(
            (candidate.segment_id, candidate.start_char, candidate.end_char, candidate.text)
        )
        if evidence_id is None:
            raise ResolverContractError(MODEL_UNKNOWN_EVIDENCE_ID)
        selected.add(evidence_id)
    return tuple(sorted(selected))


def _frame_evidence_ids(frame: ProposedIntentFrame) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *frame.action_choice.evidence_ids,
                *frame.product_family_choice.evidence_ids,
                *frame.semantic_coverage.evidence_ids,
                *(evidence_id for slot in frame.slot_assignments for evidence_id in slot.evidence_ids),
            )
        )
    )


def _require_evidence(values: Iterable[str], allowed: Iterable[str]) -> None:
    if not set(values) <= set(allowed):
        raise ResolverContractError(MODEL_UNKNOWN_EVIDENCE_ID)


def _require_subset(values: Iterable[str], allowed: Iterable[str]) -> None:
    if not set(values) <= set(allowed):
        _schema_invalid()


def _require_ordinals(values: Iterable[int], frame_count: int) -> None:
    if not all(0 <= value < frame_count for value in values):
        raise ResolverContractError(MODEL_INVALID_FRAME_REFERENCE)


def _schema_invalid() -> None:
    raise ResolverContractError(MODEL_PROPOSAL_SCHEMA_INVALID)
