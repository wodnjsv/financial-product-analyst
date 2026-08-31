from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

import pytest

from financial_agent.contracts.enums import Cardinality, IntentType, ProductFamily, ReferenceMentionType
from financial_agent.intent.context import (
    SLOT_PRECEDENCE,
    ResolutionFinalizationMetadata,
    finalize_resolution,
    validate_context_graph,
)
from financial_agent.intent.draft import (
    ActionChoice,
    ContextLinkHint,
    EvidenceSpan,
    IntentFrameDraft,
    IntentResolutionDraft,
    ProductFamilyChoice,
    ReferenceHint,
    SlotAssignment,
    SlotMutation,
)
from financial_agent.intent.errors import ResolverContractError
from financial_agent.intent.resolution import ContractFileHash, ResolverBuildManifest
from financial_agent.intent.types import (
    ChoiceState,
    ContextLinkType,
    ReferenceForm,
    ReferenceTargetKind,
    ResolutionStatus,
    Selector,
    SlotKind,
    SlotMutationKind,
    SourceRole,
)
from financial_agent.intent.validation import SemanticValidationState


def _choice(value: IntentType | ProductFamily) -> ActionChoice | ProductFamilyChoice:
    payload = {
        "state": ChoiceState.SELECTED,
        "selected_ids": (value,),
        "evidence_span_ids": ("span-1",),
        "reason_code": "explicit",
    }
    if isinstance(value, IntentType):
        return ActionChoice(**payload)
    return ProductFamilyChoice(**payload)


def _frame(
    frame_id: str,
    ordinal: int,
    *,
    action: IntentType = IntentType.RANK,
    roles: tuple[SourceRole, ...] = (SourceRole.CANDIDATES,),
    slots: tuple[SlotAssignment, ...] = (),
) -> IntentFrameDraft:
    return IntentFrameDraft(
        frame_id=frame_id,
        ordinal=ordinal,
        segment_ids=("s1",),
        evidence_span_ids=("span-1",),
        normalized_intent_argument="검증용 frame",
        action_choice=_choice(action),
        product_family_choice=_choice(ProductFamily.DOMESTIC_ETF),
        entity_type_ids=("FinancialProduct",),
        entity_hint_ids=(),
        slot_assignments=slots,
        produced_result_hints=roles,
    )


def _slot(slot_id: str, kind: SlotKind, value_id: str) -> SlotAssignment:
    return SlotAssignment(
        slot_assignment_id=slot_id,
        slot_kind=kind,
        value_ids=(value_id,),
        evidence_span_ids=("span-1",),
        reason_code="explicit",
    )


def _reference(
    reference_id: str = "ref-1",
    *,
    form: ReferenceForm = ReferenceForm.DEMONSTRATIVE,
    number: str = "plural",
    target_kind: ReferenceTargetKind = ReferenceTargetKind.RESULT_SET,
    cardinality: Cardinality = Cardinality.MANY,
    candidates: tuple[str, ...] = ("f1",),
    status: str = "resolved",
) -> ReferenceHint:
    return ReferenceHint(
        reference_id=reference_id,
        segment_id="s1",
        evidence_span_ids=("span-1",),
        surface_presence=ReferenceMentionType.EXPLICIT,
        reference_form=form,
        grammatical_number=(number,),
        expected_target_kind=(target_kind,),
        expected_cardinality=(cardinality,),
        candidate_target_frame_ids=candidates,
        candidate_target_mention_ids=(),
        status=status,
        reason_code="explicit",
    )


def _link(
    *,
    link_id: str = "link-1",
    reference_id: str = "ref-1",
    link_type: ContextLinkType = ContextLinkType.CONSUME_RESULT_SET,
    role: SourceRole = SourceRole.TOP_K_PRODUCTS,
    selector: tuple[Selector, ...] = (Selector.ALL,),
    selector_literal: tuple[str, ...] = (),
    producer: str = "f1",
    consumer: str = "f2",
    target_slot: tuple[SlotKind, ...] = (),
) -> ContextLinkHint:
    return ContextLinkHint(
        context_link_id=link_id,
        reference_id=reference_id,
        link_type=link_type,
        source_role=role,
        selector=selector,
        selector_literal_candidate_id=selector_literal,
        producer_frame_id=producer,
        consumer_frame_id=consumer,
        target_slot_kind=target_slot,
    )


def _mutation(
    kind: SlotMutationKind,
    *,
    mutation_id: str = "mutation-1",
    consumer: str = "f2",
    source: tuple[str, ...] = ("f1",),
    slot: SlotKind = SlotKind.METRIC,
) -> SlotMutation:
    return SlotMutation(
        slot_mutation_id=mutation_id,
        consumer_frame_id=consumer,
        slot_kind=slot,
        mutation_kind=kind,
        source_frame_id=source,
        evidence_span_ids=("span-1",),
        reason_code="explicit",
    )


@dataclass(frozen=True)
class ContextInputs:
    state: SemanticValidationState
    metadata: ResolutionFinalizationMetadata


def _state(
    *,
    frames: tuple[IntentFrameDraft, ...] | None = None,
    references: tuple[ReferenceHint, ...] = (),
    links: tuple[ContextLinkHint, ...] = (),
    mutations: tuple[SlotMutation, ...] = (),
) -> SemanticValidationState:
    draft_frames = frames or (
        _frame("f1", 0, roles=(SourceRole.TOP_K_PRODUCTS,)),
        _frame("f2", 1),
    )
    draft = IntentResolutionDraft(
        evidence_spans=(EvidenceSpan(span_id="span-1", segment_id="s1", start_char=0, end_char=2, text="검증"),),
        intent_frames=draft_frames,
        entity_hints=(),
        reference_hints=references,
        context_link_hints=links,
        slot_mutations=mutations,
        semantic_flag_hints=(),
        frame_limit_exceeded=False,
    )
    return SemanticValidationState(
        draft=draft,
        canonical_frames=draft_frames,
        final_tags=(),
        resolution_status=ResolutionStatus.RESOLVED,
        issues=(),
        validation_events=(),
    )


@pytest.fixture
def context_inputs() -> ContextInputs:
    metadata = ResolutionFinalizationMetadata(
        request_key="a" * 64,
        run_id="run-1",
        dataset_version="dataset-v1",
        producer="intent-resolver",
        created_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        resolution_id="resolution-1",
        draft_hash="b" * 64,
        build_manifest=ResolverBuildManifest(
            catalog_version="catalog-v1", catalog_hash="c" * 64,
            ontology_hashes=(ContractFileHash(relative_path="ontology.ttl", sha256="d" * 64),),
            overlay_version="overlay-v1", overlay_hash="e" * 64,
            normalizer_version="normalizer-v1", candidate_policy_version="policy-v1",
            resolver_schema_version="1.0", prompt_version="prompt-v1", adapter_version="adapter-v1",
        ),
        active_dataset_manifest_hash="f" * 64,
    )
    return ContextInputs(state=_state(), metadata=metadata)


def _finalize(state: SemanticValidationState, context_inputs: ContextInputs):
    return finalize_resolution(validate_context_graph(state), context_inputs.metadata)


def test_plural_followup_consumes_prior_top_k(context_inputs: ContextInputs) -> None:
    """Catches losing the typed all-products dependency in a top-k follow-up."""
    state = _state(references=(_reference(),), links=(_link(),))

    resolution = _finalize(state, context_inputs)

    link = resolution.context_links[0]
    assert link.link_type is ContextLinkType.CONSUME_RESULT_SET
    assert link.source_role is SourceRole.TOP_K_PRODUCTS
    assert link.selector == (Selector.ALL,)
    assert link.producer_frame_id == "f1"
    assert link.consumer_frame_id == "f2"
    assert resolution.repair_used is False
    assert resolution.invalid_attempt_hashes == ()


@pytest.mark.parametrize(
    ("surface", "reference", "link", "roles"),
    [
        ("연간수익률은?", _reference(form=ReferenceForm.ZERO_ANAPHORA), _link(), (SourceRole.TOP_K_PRODUCTS,)),
        ("위험등급도 보여줘", _reference(form=ReferenceForm.ZERO_ANAPHORA), _link(), (SourceRole.TOP_K_PRODUCTS,)),
        (
            "그 운용사는?",
            _reference(form=ReferenceForm.BRIDGING, number="singular", target_kind=ReferenceTargetKind.RELATED_ENTITY, cardinality=Cardinality.ONE),
            _link(link_type=ContextLinkType.DERIVE_ENTITY, role=SourceRole.RELATION_TARGET, selector=()),
            (SourceRole.RELATION_TARGET,),
        ),
        (
            "전자는?",
            _reference(number="singular", target_kind=ReferenceTargetKind.ENTITY, cardinality=Cardinality.ONE),
            _link(link_type=ContextLinkType.CONSUME_SINGLE_RESULT, role=SourceRole.CANDIDATES, selector=(Selector.FORMER,)),
            (SourceRole.CANDIDATES,),
        ),
        (
            "후자는?",
            _reference(number="singular", target_kind=ReferenceTargetKind.ENTITY, cardinality=Cardinality.ONE),
            _link(link_type=ContextLinkType.CONSUME_SINGLE_RESULT, role=SourceRole.CANDIDATES, selector=(Selector.LATTER,)),
            (SourceRole.CANDIDATES,),
        ),
        ("나머지 상품은?", _reference(), _link(role=SourceRole.CANDIDATES, selector=(Selector.REMAINING,)), (SourceRole.CANDIDATES,)),
        ("각 상품의 수익률은?", _reference(), _link(role=SourceRole.CANDIDATES, selector=(Selector.EACH,)), (SourceRole.CANDIDATES,)),
        (
            "그 결과의 근거는?",
            _reference(form=ReferenceForm.DISCOURSE_DEIXIS, target_kind=ReferenceTargetKind.EVIDENCE_RECORDS, cardinality=Cardinality.MANY),
            _link(link_type=ContextLinkType.REFER_EVIDENCE, role=SourceRole.EVIDENCE_RECORDS, selector=(Selector.ALL,)),
            (SourceRole.EVIDENCE_RECORDS,),
        ),
    ],
)
def test_korean_context_forms_preserve_registered_typed_dependencies(
    context_inputs: ContextInputs, surface: str, reference: ReferenceHint,
    link: ContextLinkHint, roles: tuple[SourceRole, ...],
) -> None:
    """Catches Korean reference forms being treated as free-text inference."""
    state = _state(frames=(_frame("f1", 0, roles=roles), _frame("f2", 1)), references=(reference,), links=(link,))

    resolution = _finalize(state, context_inputs)

    assert resolution.context_links[0].reference_id == "ref-1", surface
    assert resolution.resolution_status is ResolutionStatus.RESOLVED


def test_forward_link_is_contract_failure(context_inputs: ContextInputs) -> None:
    """Catches a consumer depending on a later producer frame."""
    state = _state(references=(_reference(candidates=("f2",)),), links=(_link(producer="f2", consumer="f1"),))

    with pytest.raises(ResolverContractError, match="INVALID_CONTEXT_GRAPH"):
        _finalize(state, context_inputs)


def test_cycle_is_contract_failure(context_inputs: ContextInputs) -> None:
    """Catches mutually dependent frames entering the execution boundary."""
    state = _state(
        references=(_reference(), _reference("ref-2", candidates=("f2",))),
        links=(_link(), _link(link_id="link-2", reference_id="ref-2", producer="f2", consumer="f1")),
    )

    with pytest.raises(ResolverContractError, match="INVALID_CONTEXT_GRAPH"):
        _finalize(state, context_inputs)


def test_many_source_requires_selector_for_single_target(context_inputs: ContextInputs) -> None:
    """Catches arbitrary selection from an ordered candidate collection."""
    state = _state(
        references=(_reference(number="singular", target_kind=ReferenceTargetKind.ENTITY, cardinality=Cardinality.ONE),),
        links=(_link(link_type=ContextLinkType.CONSUME_SINGLE_RESULT, role=SourceRole.CANDIDATES, selector=()),),
    )

    with pytest.raises(ResolverContractError, match="INVALID_CONTEXT_GRAPH"):
        _finalize(state, context_inputs)


@pytest.mark.parametrize(
    ("selector", "literal_id", "literal_kinds"),
    (
        ((Selector.RANK_POSITION,), (), {}),
        ((Selector.TOP_N,), ("lit-rank",), {"lit-rank": "rank_position"}),
    ),
)
def test_rank_selectors_require_matching_normalizer_literal_provenance(
    context_inputs: ContextInputs,
    selector: tuple[Selector, ...],
    literal_id: tuple[str, ...],
    literal_kinds: dict[str, str],
) -> None:
    """Catches rank selectors without their registered literal candidate kind."""
    state = replace(
        _state(references=(_reference(),), links=(_link(selector=selector, selector_literal=literal_id),)),
        literal_kinds_by_id=tuple(sorted(literal_kinds.items())),
    )

    with pytest.raises(ResolverContractError, match="INVALID_CONTEXT_GRAPH"):
        _finalize(state, context_inputs)


def test_rank_selector_accepts_matching_normalizer_literal(context_inputs: ContextInputs) -> None:
    """Catches rejecting a rank-position selector with registered provenance."""
    state = replace(
        _state(
            frames=(_frame("f1", 0, roles=(SourceRole.CANDIDATES,)), _frame("f2", 1)),
            references=(_reference(number="singular", target_kind=ReferenceTargetKind.ENTITY, cardinality=Cardinality.ONE),),
            links=(_link(link_type=ContextLinkType.CONSUME_SINGLE_RESULT, role=SourceRole.CANDIDATES, selector=(Selector.RANK_POSITION,), selector_literal=("lit-rank",)),),
        ),
        literal_kinds_by_id=(("lit-rank", "rank_position"),),
    )

    assert _finalize(state, context_inputs).context_links[0].selector == (Selector.RANK_POSITION,)


def test_producer_role_must_be_actually_produced(context_inputs: ContextInputs) -> None:
    """Catches a link inventing a top-k result that its producer never declared."""
    state = _state(frames=(_frame("f1", 0), _frame("f2", 1)), references=(_reference(),), links=(_link(),))

    with pytest.raises(ResolverContractError, match="INVALID_CONTEXT_GRAPH"):
        _finalize(state, context_inputs)


def test_singular_demonstrative_with_two_candidates_is_ambiguous(context_inputs: ContextInputs) -> None:
    """Catches choosing one antecedent for 이 상품 without a typed selector."""
    state = _state(references=(_reference(number="singular", target_kind=ReferenceTargetKind.ENTITY, cardinality=Cardinality.ONE, candidates=("f1", "f2")),))

    resolution = _finalize(state, context_inputs)

    assert resolution.context_links == ()
    assert resolution.resolution_status is ResolutionStatus.AMBIGUOUS
    assert {issue.code for issue in resolution.issues} == {"REFERENCE_AMBIGUOUS"}


def test_anchorless_similarity_is_context_unresolved(context_inputs: ContextInputs) -> None:
    """Catches marking a similarity request executable without an anchor."""
    state = _state(frames=(_frame("f1", 0, action=IntentType.SIMILAR, roles=()),))

    resolution = _finalize(state, context_inputs)

    assert resolution.resolution_status is ResolutionStatus.CONTEXT_UNRESOLVED
    assert {issue.code for issue in resolution.issues} == {"REFERENCE_UNRESOLVED"}


def test_explicit_slot_conflict_with_carryover_is_ambiguous(context_inputs: ContextInputs) -> None:
    """Catches precedence silently replacing current-frame evidence with carryover."""
    state = _state(
        frames=(
            _frame("f1", 0, slots=(_slot("slot-f1", SlotKind.METRIC, "aum"),)),
            _frame("f2", 1, slots=(_slot("slot-f2", SlotKind.METRIC, "return"),)),
        ),
        mutations=(_mutation(SlotMutationKind.CARRYOVER),),
    )

    resolution = _finalize(state, context_inputs)

    assert resolution.resolution_status is ResolutionStatus.AMBIGUOUS
    assert {issue.code for issue in resolution.issues} == {"AMBIGUITY_UNRESOLVED"}


@pytest.mark.parametrize("mutation_kind", (SlotMutationKind.CARRYOVER, SlotMutationKind.UPDATE, SlotMutationKind.DELETE, SlotMutationKind.DONTCARE))
def test_registered_slot_mutations_are_frozen_into_frames(context_inputs: ContextInputs, mutation_kind: SlotMutationKind) -> None:
    """Catches permitted mutation kinds being dropped before Phase 2 lowering."""
    source = ("f1",) if mutation_kind is SlotMutationKind.CARRYOVER else ()
    frames = (
        _frame("f1", 0, roles=(SourceRole.TOP_K_PRODUCTS,), slots=(_slot("slot-f1", SlotKind.METRIC, "aum"),)),
        _frame("f2", 1),
    )
    state = _state(frames=frames, mutations=(_mutation(mutation_kind, source=source),))

    resolution = _finalize(state, context_inputs)

    assert resolution.canonical_frames[1].slot_mutations[0].mutation_kind is mutation_kind


def test_slot_precedence_is_frozen_and_finalization_keeps_metadata_pins(context_inputs: ContextInputs) -> None:
    """Catches an unsafe Phase 1 default or loss of request provenance."""
    resolution = _finalize(_state(), context_inputs)

    assert SLOT_PRECEDENCE == (
        "explicit_current_evidence",
        "validated_context_link",
        "explicit_carryover",
        "phase2_default",
    )
    assert resolution.request_key == "a" * 64
    assert resolution.draft_hash == "b" * 64
    assert resolution.build_manifest.catalog_hash == "c" * 64
    assert resolution.active_dataset_manifest_hash == "f" * 64
