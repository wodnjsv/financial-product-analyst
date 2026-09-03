"""Deterministically assemble and validate V3 source-mention semantic links."""

from __future__ import annotations

import hashlib

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import IntentType, ProductFamily

from .catalog import SemanticCatalogSnapshot
from .draft import (
    ActionChoice,
    ContextLinkHint,
    EntityHintV2,
    EvidenceSpan,
    IntentFrameDraftV2,
    IntentResolutionDraftV3,
    ProductFamilyChoice,
    ReferenceHint,
    SemanticFlagHint,
    SemanticLinkDraftV3,
    SlotAssignment,
    SlotMutation,
)
from .errors import ResolverContractError
from .hybrid_proposal import (
    IntentResolutionProposalV3,
    ProposedIntentFrameV3,
    ProposedSemanticLinkV3,
)
from .normalization import NormalizedRequest
from .proposal import FrameSemanticCoverage, require_valid_action_cardinality
from .types import (
    ChoiceState,
    EntitySemanticRole,
    SemanticCoverageReason,
    SemanticCoverageState,
    SlotKind,
)
from .view import ResolverViewV3, validate_resolver_view_catalog


def assemble_hybrid_proposal(
    proposal: IntentResolutionProposalV3,
    normalized: NormalizedRequest,
    view: ResolverViewV3,
    catalog: SemanticCatalogSnapshot,
) -> IntentResolutionDraftV3:
    """Produce a canonical V3 draft only from server-offered source identities."""
    if not isinstance(proposal, IntentResolutionProposalV3) or not isinstance(
        view, ResolverViewV3
    ):
        raise ResolverContractError("MODEL_PROPOSAL_SCHEMA_INVALID")
    validate_resolver_view_catalog(view, catalog)
    proposal_hash = canonical_sha256(proposal)
    _validate_offered_ids(proposal, normalized, view, catalog)
    links_by_frame = _reconcile_exact_locks(proposal, view)
    _validate_coverage(proposal, view, links_by_frame)
    _validate_applicability(proposal, links_by_frame, catalog)
    _validate_relation_endpoints(proposal, links_by_frame, view, catalog)
    frame_ids = tuple(
        _canonical_id("frame-v3", proposal_hash, str(ordinal))
        for ordinal in range(len(proposal.frames))
    )
    mention_evidence = _mention_evidence(view)
    evidence_spans = _evidence_spans(proposal, view, links_by_frame, mention_evidence)
    frames = tuple(
        _assemble_frame(
            ordinal,
            frame,
            frame_ids[ordinal],
            proposal_hash,
            normalized,
            links_by_frame[ordinal],
            mention_evidence,
            tuple(
                evidence_id
                for mutation in proposal.slot_mutations
                if mutation.consumer_frame_ordinal == ordinal
                for evidence_id in mutation.evidence_ids
            ),
        )
        for ordinal, frame in enumerate(proposal.frames)
    )
    semantic_links = tuple(
        _assemble_link(
            proposal_hash,
            ordinal,
            frame_ids[ordinal],
            link,
            mention_evidence[link.mention_id][0],
            any(
                proposed_link.mention_id == link.mention_id
                and proposed_link.semantic_ids == link.semantic_ids
                and proposed_link.state == link.state
                for proposed_link in proposal.frames[ordinal].semantic_links
            ),
        )
        for ordinal, links in enumerate(links_by_frame)
        for link in links
    )
    return IntentResolutionDraftV3(
        evidence_spans=evidence_spans,
        intent_frames=frames,
        entity_hints=_assemble_entity_hints(proposal, proposal_hash),
        reference_hints=_assemble_references(proposal, view, frame_ids),
        context_link_hints=_assemble_context_links(proposal, frame_ids, proposal_hash),
        slot_mutations=_assemble_mutations(proposal, frame_ids, proposal_hash),
        semantic_flag_hints=tuple(
            SemanticFlagHint(
                semantic_tag=flag.semantic_tag,
                evidence_span_ids=flag.evidence_ids,
                reason_code=flag.reason_code,
            )
            for flag in proposal.semantic_flag_hints
        ),
        frame_limit_exceeded=proposal.frame_limit_exceeded,
        semantic_links=semantic_links,
    )


def _validate_offered_ids(
    proposal: IntentResolutionProposalV3,
    normalized: NormalizedRequest,
    view: ResolverViewV3,
    catalog: SemanticCatalogSnapshot,
) -> None:
    segment_ids = {segment.segment_id for segment in normalized.segments}
    mentions = {item.mention_id: item for item in view.mention_spans.items}
    semantic_ids = {item.semantic_id for item in view.compact_semantic_catalog.concepts}
    if semantic_ids != set(catalog.concepts_by_id):
        raise ResolverContractError("MODEL_UNKNOWN_ID")
    evidence_ids = {item.evidence_id for item in view.evidence_candidates}
    evidence_segments = {
        item.evidence_id: item.segment_id for item in view.evidence_candidates
    }
    entity_types = set(view.entity_type_ids)
    entity_by_mention = {
        group.mention_id: {item.entity_id for item in group.items}
        for group in view.entity_candidates
    }
    reference_ids = {item.reference_id for item in view.reference_candidates}
    reference_evidence = {
        (item.segment_id, item.start_char, item.end_char, item.text)
        for item in view.evidence_candidates
    }
    for projection in view.exact_lock_projections:
        _require_subset((projection.mention_id,), mentions)
        if projection.role == "field":
            _require_subset((projection.canonical_semantic_id,), semantic_ids)
        else:
            _require_subset(
                (projection.canonical_semantic_id,), view.product_family_ids
            )
    if not view.entity_output_enabled and any(
        frame.entity_hints for frame in proposal.frames
    ):
        raise ResolverContractError("MODEL_OUTPUT_DISABLED")
    if not view.reference_output_enabled and (
        proposal.references or proposal.context_links or proposal.slot_mutations
    ):
        raise ResolverContractError("MODEL_OUTPUT_DISABLED")
    for frame in proposal.frames:
        _require_subset(frame.segment_ids, segment_ids)
        _validate_choice(
            frame.action_choice.state,
            frame.action_choice.selected_ids,
            view.action_ids,
        )
        _validate_choice(
            frame.product_family_choice.state,
            frame.product_family_choice.selected_ids,
            view.product_family_ids,
        )
        try:
            require_valid_action_cardinality(
                frame.action_choice.state,
                frame.action_choice.selected_ids,
                frame.semantic_coverage.state,
            )
        except ValueError as error:
            raise ResolverContractError("MODEL_SCHEMA_INVALID") from error
        _require_subset(frame.entity_type_ids, entity_types)
        _require_subset(frame.action_choice.evidence_ids, evidence_ids)
        _require_subset(frame.product_family_choice.evidence_ids, evidence_ids)
        frame_segments = set(frame.segment_ids)
        if any(
            evidence_segments[evidence_id] not in frame_segments
            for evidence_id in (
                *frame.action_choice.evidence_ids,
                *frame.product_family_choice.evidence_ids,
            )
        ):
            raise ResolverContractError("MODEL_UNKNOWN_EVIDENCE_ID")
        link_mentions: set[str] = set()
        for link in frame.semantic_links:
            _require_subset((link.mention_id,), mentions)
            _require_subset(link.semantic_ids, semantic_ids)
            if (
                link.mention_id in link_mentions
                or mentions[link.mention_id].segment_id not in frame_segments
                or (link.state == "selected" and len(link.semantic_ids) != 1)
                or (
                    link.state == "ambiguous"
                    and (
                        len(link.semantic_ids) < 2
                        or len(set(link.semantic_ids)) != len(link.semantic_ids)
                    )
                )
            ):
                raise ResolverContractError("MODEL_INVALID_SEMANTIC_COVERAGE")
            link_mentions.add(link.mention_id)
        _require_subset(frame.unmapped_mention_ids, mentions)
        if any(
            mentions[item].segment_id not in frame_segments
            for item in frame.unmapped_mention_ids
        ):
            raise ResolverContractError("MODEL_UNKNOWN_ID")
        for hint in frame.entity_hints:
            _require_subset(hint.expected_entity_type_ids, entity_types)
            if hint.mention_id:
                mention_id = hint.mention_id[0]
                mention = mentions.get(mention_id)
                if mention is None or mention.segment_id not in frame_segments:
                    raise ResolverContractError("MODEL_UNKNOWN_ID")
                candidates = entity_by_mention.get(mention_id)
                if candidates is None:
                    raise ResolverContractError("MODEL_UNKNOWN_ID")
                _require_subset(hint.candidate_entity_ids, candidates)
                _require_subset(hint.selected_candidate_ids, hint.candidate_entity_ids)
            elif hint.candidate_entity_ids or hint.selected_candidate_ids:
                raise ResolverContractError("MODEL_UNKNOWN_ID")
    _validate_reference_ordinals(proposal, reference_ids)
    for reference in proposal.references:
        candidate = next(
            item
            for item in view.reference_candidates
            if item.reference_id == reference.reference_id
        )
        if (
            candidate.segment_id,
            candidate.start_char,
            candidate.end_char,
            candidate.text,
        ) not in reference_evidence:
            raise ResolverContractError("MODEL_UNKNOWN_EVIDENCE_ID")
    literal_ids = {item.literal_id for item in view.literal_candidates}
    for link in proposal.context_links:
        _require_subset(link.selector_literal_candidate_id, literal_ids)
        if link.target_slot_kind == (SlotKind.UNIT,):
            raise ResolverContractError("MODEL_SCHEMA_INVALID")
    for mutation in proposal.slot_mutations:
        _require_subset(mutation.evidence_ids, evidence_ids)
        if mutation.slot_kind is SlotKind.UNIT:
            raise ResolverContractError("MODEL_SCHEMA_INVALID")
    for flag in proposal.semantic_flag_hints:
        _require_subset(flag.evidence_ids, evidence_ids)


def _validate_choice(state: ChoiceState, selected: tuple[str, ...], allowed: object) -> None:
    if (state is ChoiceState.SELECTED) != bool(selected):
        raise ResolverContractError("MODEL_SCHEMA_INVALID")
    _require_subset(selected, allowed)


def _validate_reference_ordinals(
    proposal: IntentResolutionProposalV3, reference_ids: set[str]
) -> None:
    frame_count = len(proposal.frames)
    proposed_reference_ids = tuple(
        reference.reference_id for reference in proposal.references
    )
    if len(set(proposed_reference_ids)) != len(proposed_reference_ids):
        raise ResolverContractError("MODEL_SCHEMA_INVALID")
    producer_ordinals = {
        reference.reference_id: set(reference.producer_frame_ordinals)
        for reference in proposal.references
    }
    for reference in proposal.references:
        _require_subset((reference.reference_id,), reference_ids)
        _require_ordinals(reference.producer_frame_ordinals, frame_count)
    for link in proposal.context_links:
        _require_subset((link.reference_id,), reference_ids)
        _require_ordinals((link.producer_frame_ordinal, link.consumer_frame_ordinal), frame_count)
        if (
            link.producer_frame_ordinal >= link.consumer_frame_ordinal
            or link.producer_frame_ordinal not in producer_ordinals.get(link.reference_id, set())
            or link.source_role
            not in proposal.frames[link.producer_frame_ordinal].produced_result_hints
        ):
            raise ResolverContractError("MODEL_INVALID_FRAME_REFERENCE")
    for mutation in proposal.slot_mutations:
        _require_ordinals((mutation.consumer_frame_ordinal,), frame_count)
        if mutation.source_frame_ordinal:
            source = mutation.source_frame_ordinal[0]
            _require_ordinals((source,), frame_count)
            if source >= mutation.consumer_frame_ordinal:
                raise ResolverContractError("MODEL_INVALID_FRAME_REFERENCE")


def _reconcile_exact_locks(
    proposal: IntentResolutionProposalV3, view: ResolverViewV3
) -> tuple[tuple[ProposedSemanticLinkV3, ...], ...]:
    links = [list(frame.semantic_links) for frame in proposal.frames]
    mention_segments = {
        item.mention_id: item.segment_id for item in view.mention_spans.items
    }
    for projection in view.exact_lock_projections:
        frame_indexes = [
            index
            for index, frame in enumerate(proposal.frames)
            if mention_segments[projection.mention_id] in frame.segment_ids
        ]
        matching = [
            (index, link)
            for index in frame_indexes
            for link in links[index]
            if link.mention_id == projection.mention_id
        ]
        if projection.role == "product_family":
            if not any(
                projection.canonical_semantic_id
                in proposal.frames[index].product_family_choice.selected_ids
                for index in frame_indexes
            ):
                raise ResolverContractError("MODEL_EXACT_LOCK_CONFLICT")
            continue
        if matching:
            if any(
                link.state != "selected"
                or link.semantic_ids != (projection.canonical_semantic_id,)
                for _, link in matching
            ):
                raise ResolverContractError("MODEL_EXACT_LOCK_CONFLICT")
            continue
        if len(frame_indexes) != 1:
            raise ResolverContractError("MODEL_EXACT_LOCK_CONFLICT")
        links[frame_indexes[0]].append(
            ProposedSemanticLinkV3(
                mention_id=projection.mention_id,
                state="selected",
                semantic_ids=(projection.canonical_semantic_id,),
                reason_code="explicit",
            )
        )
    return tuple(
        tuple(sorted(frame_links, key=lambda item: (item.mention_id, item.semantic_ids)))
        for frame_links in links
    )


def _validate_coverage(
    proposal: IntentResolutionProposalV3,
    view: ResolverViewV3,
    links_by_frame: tuple[tuple[ProposedSemanticLinkV3, ...], ...],
) -> None:
    offered = {item.mention_id for item in view.mention_spans.items}
    for frame, reconciled_links in zip(
        proposal.frames, links_by_frame, strict=True
    ):
        linked = [link.mention_id for link in reconciled_links]
        unmapped = tuple(frame.unmapped_mention_ids)
        if (
            len(linked) != len(set(linked))
            or len(unmapped) != len(set(unmapped))
            or set(linked) & set(unmapped)
            or not set(unmapped) <= offered
        ):
            raise ResolverContractError("MODEL_INVALID_SEMANTIC_COVERAGE")
        coverage = frame.semantic_coverage
        if coverage.state is SemanticCoverageState.COVERED:
            valid = coverage.reason is SemanticCoverageReason.NONE and not unmapped
        else:
            valid = coverage.reason is not SemanticCoverageReason.NONE and bool(unmapped)
        if not valid:
            raise ResolverContractError("MODEL_INVALID_SEMANTIC_COVERAGE")


def _validate_applicability(
    proposal: IntentResolutionProposalV3,
    links_by_frame: tuple[tuple[ProposedSemanticLinkV3, ...], ...],
    catalog: SemanticCatalogSnapshot,
) -> None:
    for frame, links in zip(proposal.frames, links_by_frame, strict=True):
        families = set(frame.product_family_choice.selected_ids)
        for link in links:
            for semantic_id in link.semantic_ids:
                concept = catalog.concepts_by_id[semantic_id]
                if not families <= set(concept.allowed_product_families):
                    raise ResolverContractError("MODEL_INAPPLICABLE_CONCEPT")
                allowed_types = (
                    set(concept.subject_ontology_types)
                    if concept.kind == "relation"
                    else set(concept.allowed_ontology_types)
                )
                if not all(
                    _type_is_compatible(type_id, allowed_types, catalog)
                    for type_id in frame.entity_type_ids
                ):
                    raise ResolverContractError("MODEL_INAPPLICABLE_CONCEPT")


def _validate_relation_endpoints(
    proposal: IntentResolutionProposalV3,
    links_by_frame: tuple[tuple[ProposedSemanticLinkV3, ...], ...],
    view: ResolverViewV3,
    catalog: SemanticCatalogSnapshot,
) -> None:
    candidates = {
        group.mention_id: {item.entity_id: item for item in group.items}
        for group in view.entity_candidates
    }
    for frame, links in zip(proposal.frames, links_by_frame, strict=True):
        relation_ids = {
            semantic_id
            for link in links
            for semantic_id in link.semantic_ids
            if catalog.concepts_by_id[semantic_id].kind == "relation"
        }
        if relation_ids and not frame.entity_type_ids:
            raise ResolverContractError("MODEL_INVALID_RELATION")
        for hint in frame.entity_hints:
            if hint.mention_id:
                by_id = candidates[hint.mention_id[0]]
                if any(
                    not any(
                        _type_is_compatible(
                            actual,
                            set(hint.expected_entity_type_ids),
                            catalog,
                        )
                        for actual in by_id[entity_id].ontology_type_ids
                    )
                    for entity_id in hint.selected_candidate_ids
                ):
                    raise ResolverContractError("MODEL_INVALID_ENTITY_TYPE")
            if hint.semantic_role is EntitySemanticRole.FRAME_SUBJECT:
                if hint.relation_id or not all(
                    _type_is_compatible(expected, set(frame.entity_type_ids), catalog)
                    for expected in hint.expected_entity_type_ids
                ):
                    raise ResolverContractError("MODEL_INVALID_ENTITY_TYPE")
                continue
            if len(hint.relation_id) != 1 or hint.relation_id[0] not in relation_ids:
                raise ResolverContractError("MODEL_INVALID_RELATION")
            relation = catalog.concepts_by_id[hint.relation_id[0]]
            allowed = set(relation.object_ontology_types)
            if not all(
                _type_is_compatible(expected, allowed, catalog)
                for expected in hint.expected_entity_type_ids
            ):
                raise ResolverContractError("MODEL_INVALID_RELATION")
            if hint.mention_id:
                by_id = candidates[hint.mention_id[0]]
                for entity_id in hint.selected_candidate_ids:
                    if not any(
                        _type_is_compatible(actual, allowed, catalog)
                        for actual in by_id[entity_id].ontology_type_ids
                    ):
                        raise ResolverContractError("MODEL_INVALID_RELATION")


def _assemble_frame(
    ordinal: int,
    frame: ProposedIntentFrameV3,
    frame_id: str,
    proposal_hash: str,
    normalized: NormalizedRequest,
    links: tuple[ProposedSemanticLinkV3, ...],
    mention_evidence: dict[str, tuple[str, EvidenceSpan]],
    mutation_evidence_ids: tuple[str, ...],
) -> IntentFrameDraftV2:
    hint_ids = tuple(
        _canonical_id("entity-hint-v3", proposal_hash, str(ordinal), str(index))
        for index, _ in enumerate(frame.entity_hints)
    )
    entity_slots = tuple(
        SlotAssignment(
            slot_assignment_id=_canonical_id(
                "slot-v3", proposal_hash, str(ordinal), str(index)
            ),
            slot_kind=SlotKind.ENTITY,
            value_ids=hint.selected_candidate_ids,
            evidence_span_ids=(),
            reason_code="implicit",
        )
        for index, hint in enumerate(frame.entity_hints)
        if hint.selected_candidate_ids
    )
    semantic_evidence = tuple(
        mention_evidence[link.mention_id][0] for link in links
    )
    unmapped_evidence = tuple(
        mention_evidence[mention_id][0] for mention_id in frame.unmapped_mention_ids
    )
    evidence_ids = tuple(
        sorted(
            set(
                (*frame.action_choice.evidence_ids, *frame.product_family_choice.evidence_ids,
                 *semantic_evidence, *unmapped_evidence)
                 + mutation_evidence_ids
            )
        )
    )
    normalized_by_id = {item.segment_id: item for item in normalized.segments}
    return IntentFrameDraftV2(
        frame_id=frame_id,
        ordinal=ordinal,
        segment_ids=frame.segment_ids,
        evidence_span_ids=evidence_ids,
        normalized_intent_argument=" ".join(
            normalized_by_id[segment_id].normalized_text
            for segment_id in frame.segment_ids
        ),
        action_choice=ActionChoice(
            state=frame.action_choice.state,
            selected_ids=tuple(IntentType(item) for item in frame.action_choice.selected_ids),
            evidence_span_ids=frame.action_choice.evidence_ids,
            reason_code=frame.action_choice.reason_code,
        ),
        product_family_choice=ProductFamilyChoice(
            state=frame.product_family_choice.state,
            selected_ids=tuple(
                ProductFamily(item)
                for item in frame.product_family_choice.selected_ids
            ),
            evidence_span_ids=frame.product_family_choice.evidence_ids,
            reason_code=frame.product_family_choice.reason_code,
        ),
        entity_type_ids=frame.entity_type_ids,
        entity_hint_ids=hint_ids,
        slot_assignments=entity_slots,
        produced_result_hints=frame.produced_result_hints,
        semantic_coverage=(
            FrameSemanticCoverage(
                state=frame.semantic_coverage.state,
                reason=frame.semantic_coverage.reason,
                evidence_ids=unmapped_evidence,
            ),
        ),
    )


def _assemble_link(
    proposal_hash: str,
    ordinal: int,
    frame_id: str,
    link: ProposedSemanticLinkV3,
    evidence_id: str,
    model_selected: bool,
) -> SemanticLinkDraftV3:
    return SemanticLinkDraftV3(
        semantic_link_id=_canonical_id(
            "semantic-link-v3",
            proposal_hash,
            str(ordinal),
            link.mention_id,
            *sorted(link.semantic_ids),
        ),
        frame_id=frame_id,
        mention_id=link.mention_id,
        semantic_ids=tuple(sorted(link.semantic_ids)),
        state=link.state,
        evidence_span_ids=(evidence_id,),
        reason_code=link.reason_code if model_selected else "exact_lock",
    )


def _mention_evidence(view: ResolverViewV3) -> dict[str, tuple[str, EvidenceSpan]]:
    result = {}
    for mention in view.mention_spans.items:
        evidence_id = _canonical_id(
            "evidence-v3",
            mention.segment_id,
            str(mention.start_char),
            str(mention.end_char),
            mention.text,
        )
        result[mention.mention_id] = (
            evidence_id,
            EvidenceSpan(
                span_id=evidence_id,
                segment_id=mention.segment_id,
                start_char=mention.start_char,
                end_char=mention.end_char,
                text=mention.text,
            ),
        )
    return result


def _evidence_spans(
    proposal: IntentResolutionProposalV3,
    view: ResolverViewV3,
    links_by_frame: tuple[tuple[ProposedSemanticLinkV3, ...], ...],
    mention_evidence: dict[str, tuple[str, EvidenceSpan]],
) -> tuple[EvidenceSpan, ...]:
    selected_mentions = {
        link.mention_id for links in links_by_frame for link in links
    } | {
        mention_id for frame in proposal.frames for mention_id in frame.unmapped_mention_ids
    }
    selected_evidence = {
        evidence_id
        for frame in proposal.frames
        for evidence_id in (
            *frame.action_choice.evidence_ids,
            *frame.product_family_choice.evidence_ids,
        )
    } | {
        evidence_id
        for mutation in proposal.slot_mutations
        for evidence_id in mutation.evidence_ids
    } | {
        evidence_id
        for flag in proposal.semantic_flag_hints
        for evidence_id in flag.evidence_ids
    }
    references = {
        item.reference_id: item for item in view.reference_candidates
    }
    evidence_by_coordinates = {
        (item.segment_id, item.start_char, item.end_char, item.text): item.evidence_id
        for item in view.evidence_candidates
    }
    selected_evidence.update(
        evidence_by_coordinates[
            (
                references[item.reference_id].segment_id,
                references[item.reference_id].start_char,
                references[item.reference_id].end_char,
                references[item.reference_id].text,
            )
        ]
        for item in proposal.references
    )
    spans = [mention_evidence[item][1] for item in sorted(selected_mentions)]
    spans.extend(
        EvidenceSpan(
            span_id=item.evidence_id,
            segment_id=item.segment_id,
            start_char=item.start_char,
            end_char=item.end_char,
            text=item.text,
        )
        for item in view.evidence_candidates
        if item.evidence_id in selected_evidence
    )
    return tuple(sorted(spans, key=lambda item: item.span_id))


def _assemble_entity_hints(
    proposal: IntentResolutionProposalV3, proposal_hash: str
) -> tuple[EntityHintV2, ...]:
    return tuple(
        EntityHintV2(
            entity_hint_id=_canonical_id(
                "entity-hint-v3", proposal_hash, str(frame_index), str(hint_index)
            ),
            semantic_role=hint.semantic_role,
            relation_id=hint.relation_id,
            mention_id=hint.mention_id,
            evidence_span_ids=(),
            expected_entity_type_ids=hint.expected_entity_type_ids,
            candidate_entity_ids=hint.candidate_entity_ids,
            selected_candidate_ids=hint.selected_candidate_ids,
            reason_code="implicit",
        )
        for frame_index, frame in enumerate(proposal.frames)
        for hint_index, hint in enumerate(frame.entity_hints)
    )


def _assemble_references(
    proposal: IntentResolutionProposalV3,
    view: ResolverViewV3,
    frame_ids: tuple[str, ...],
) -> tuple[ReferenceHint, ...]:
    candidates = {item.reference_id: item for item in view.reference_candidates}
    evidence_by_coordinates = {
        (item.segment_id, item.start_char, item.end_char, item.text): item.evidence_id
        for item in view.evidence_candidates
    }
    return tuple(
        ReferenceHint(
            reference_id=item.reference_id,
            segment_id=candidates[item.reference_id].segment_id,
            evidence_span_ids=(
                evidence_by_coordinates[
                    (
                        candidates[item.reference_id].segment_id,
                        candidates[item.reference_id].start_char,
                        candidates[item.reference_id].end_char,
                        candidates[item.reference_id].text,
                    )
                ],
            ),
            surface_presence=item.surface_presence,
            reference_form=item.reference_form,
            grammatical_number=item.grammatical_number,
            expected_target_kind=item.expected_target_kind,
            expected_cardinality=item.expected_cardinality,
            candidate_target_frame_ids=tuple(
                frame_ids[index] for index in item.producer_frame_ordinals
            ),
            candidate_target_mention_ids=(),
            status=item.status,
            reason_code=item.reason_code,
        )
        for item in proposal.references
    )


def _assemble_context_links(
    proposal: IntentResolutionProposalV3,
    frame_ids: tuple[str, ...],
    proposal_hash: str,
) -> tuple[ContextLinkHint, ...]:
    return tuple(
        ContextLinkHint(
            context_link_id=_canonical_id(
                "context-link-v3", proposal_hash, str(index), item.reference_id
            ),
            reference_id=item.reference_id,
            link_type=item.link_type,
            source_role=item.source_role,
            selector=item.selector,
            selector_literal_candidate_id=item.selector_literal_candidate_id,
            producer_frame_id=frame_ids[item.producer_frame_ordinal],
            consumer_frame_id=frame_ids[item.consumer_frame_ordinal],
            target_slot_kind=item.target_slot_kind,
        )
        for index, item in enumerate(proposal.context_links)
    )


def _assemble_mutations(
    proposal: IntentResolutionProposalV3,
    frame_ids: tuple[str, ...],
    proposal_hash: str,
) -> tuple[SlotMutation, ...]:
    return tuple(
        SlotMutation(
            slot_mutation_id=_canonical_id("mutation-v3", proposal_hash, str(index)),
            consumer_frame_id=frame_ids[item.consumer_frame_ordinal],
            slot_kind=item.slot_kind,
            mutation_kind=item.mutation_kind,
            source_frame_id=tuple(
                frame_ids[ordinal] for ordinal in item.source_frame_ordinal
            ),
            evidence_span_ids=item.evidence_ids,
            reason_code=item.reason_code,
        )
        for index, item in enumerate(proposal.slot_mutations)
    )


def _type_is_compatible(
    actual: str, allowed: set[str], catalog: SemanticCatalogSnapshot
) -> bool:
    return actual in allowed or bool(
        set(catalog.class_ancestor_ids.get(actual, ())) & allowed
    )


def _canonical_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _require_subset(values: object, allowed: object) -> None:
    if not set(values) <= set(allowed):
        raise ResolverContractError("MODEL_UNKNOWN_ID")


def _require_ordinals(values: object, frame_count: int) -> None:
    if not all(0 <= item < frame_count for item in values):
        raise ResolverContractError("MODEL_INVALID_FRAME_REFERENCE")
