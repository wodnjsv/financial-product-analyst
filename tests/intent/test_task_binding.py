from pathlib import Path

import pytest

from financial_agent.contracts.enums import IntentType
from financial_agent.intent.task_binding import (
    BindingSource,
    TaskBindingError,
    TaskReadiness,
    bind_task_slots,
)
from financial_agent.intent.task_contracts import load_task_contract_registry
from financial_agent.intent.evidence import EvidenceCandidate, EvidenceSourceKind
from financial_agent.intent.types import (
    ChoiceState,
    ResolutionStatus,
    SemanticTag,
    SlotKind,
    SlotMutationKind,
)
from financial_agent.intent.view import (
    ResolverViewConcept,
    ResolverViewSemanticCandidate,
    ResolverViewSemanticCandidateGroup,
    ResolverViewRelationDefinition,
)
from tests.planning.fixtures import resolution, slot, view


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _axis_resolution():
    source = resolution()
    frame = source.canonical_frames[0].model_copy(update={"slot_assignments": ()})
    return source.model_copy(update={"canonical_frames": (frame,)})


def _view_with_semantics(*items: tuple[str, str]):
    source = view()
    groups = tuple(
        ResolverViewSemanticCandidateGroup(
            mention_id=f"mention-{index}",
            items=(
                ResolverViewSemanticCandidate(
                    semantic_id=semantic_id,
                    match_kind=match_kind,
                    score=1_000_000,
                ),
            ),
        )
        for index, (semantic_id, match_kind) in enumerate(items)
    )
    return source.model_copy(update={"semantic_candidates": groups})


def test_rank_binds_unique_direct_alias_and_native_result_limit() -> None:
    bound = bind_task_slots(
        _axis_resolution(),
        _view_with_semantics(("aum", "direct_alias")),
        load_task_contract_registry(PROJECT_ROOT),
    )

    contract = bound.task_contracts[0]
    assert contract.readiness is TaskReadiness.COMPLETE
    assert contract.missing_required_slot_kinds == ()
    assert [(item.slot_kind, item.value_ids, item.source) for item in contract.bindings] == [
        (SlotKind.SORT_KEY, ("aum",), BindingSource.DETERMINISTIC_EXACT),
        (
            SlotKind.RESULT_LIMIT,
            ("literal-limit-5",),
            BindingSource.DETERMINISTIC_LITERAL,
        ),
    ]
    assert {
        assignment.slot_kind: assignment.value_ids
        for assignment in bound.resolution.canonical_frames[0].slot_assignments
    } == {
        SlotKind.SORT_KEY: ("aum",),
        SlotKind.RESULT_LIMIT: ("literal-limit-5",),
    }


def test_two_exact_sort_candidates_remain_ambiguous() -> None:
    bound = bind_task_slots(
        _axis_resolution(),
        _view_with_semantics(
            ("aum", "direct_alias"),
            ("product_risk_grade", "direct_alias"),
        ),
        load_task_contract_registry(PROJECT_ROOT),
    )

    contract = bound.task_contracts[0]
    assert contract.readiness is TaskReadiness.AMBIGUOUS
    assert contract.missing_required_slot_kinds == (SlotKind.SORT_KEY,)
    assert contract.ambiguous_choices[0].value_ids == ("aum", "product_risk_grade")


def test_fuzzy_candidate_is_not_locked_and_blocks_without_exact_choices() -> None:
    bound = bind_task_slots(
        _axis_resolution(),
        _view_with_semantics(("aum", "trigram")),
        load_task_contract_registry(PROJECT_ROOT),
    )

    contract = bound.task_contracts[0]
    assert contract.readiness is TaskReadiness.BLOCKED
    assert contract.missing_required_slot_kinds == (SlotKind.SORT_KEY,)
    assert contract.ambiguous_choices == ()


def test_inapplicable_concept_is_not_locked() -> None:
    source = _view_with_semantics(("aum", "direct_alias"))
    aum = next(item for item in source.concept_definitions if item.concept_id == "aum")
    incompatible = aum.model_copy(update={"allowed_product_families": ("overseas_etf",)})
    changed = tuple(
        incompatible if item.concept_id == "aum" else item
        for item in source.concept_definitions
    )

    bound = bind_task_slots(
        _axis_resolution(),
        source.model_copy(update={"concept_definitions": changed}),
        load_task_contract_registry(PROJECT_ROOT),
    )

    assert bound.task_contracts[0].readiness is TaskReadiness.BLOCKED


def test_axis_resolution_rejects_model_authored_task_slot() -> None:
    source = _axis_resolution()
    frame = source.canonical_frames[0].model_copy(
        update={
            "slot_assignments": (
                slot("model-sort", SlotKind.SORT_KEY, ("aum",)),
            )
        }
    )

    with pytest.raises(TaskBindingError, match="AXIS_TASK_SLOT_NOT_EMPTY"):
        bind_task_slots(
            source.model_copy(update={"canonical_frames": (frame,)}),
            _view_with_semantics(("aum", "direct_alias")),
            load_task_contract_registry(PROJECT_ROOT),
        )


def test_relationship_tag_requires_and_binds_unique_exact_relation() -> None:
    source = _axis_resolution()
    frame = source.canonical_frames[0]
    lookup = frame.model_copy(
        update={
            "action_choice": frame.action_choice.model_copy(
                update={"selected_ids": (IntentType.LOOKUP,)}
            )
        }
    )
    axis = source.model_copy(
        update={
            "canonical_frames": (lookup,),
            "final_tags": (SemanticTag.RELATIONSHIP_REQUIRED,),
        }
    )
    resolver_view = _view_with_semantics(("managedBy", "direct_alias"))
    resolver_view = resolver_view.model_copy(
        update={
            "relation_definitions": (
                ResolverViewRelationDefinition(
                    relation_id="managedBy",
                    definition_ko="상품을 운용하는 기관",
                    allowed_product_families=("domestic_bond", "domestic_etf", "overseas_etf", "public_fund"),
                    subject_ontology_types=("FinancialProduct",),
                    compatible_subject_ontology_types=(
                        "Bond", "DomesticBond", "DomesticETF", "DomesticETN", "ETF",
                        "ETN", "ExchangeTradedProduct", "FinancialProduct",
                        "FixedRateBond", "FloatingRateBond", "FundShareClass",
                        "OverseasETF", "OverseasETN", "PublicFund",
                        "PublicOfferingFund", "RepresentativeFund",
                    ),
                    object_ontology_types=("AssetManager",),
                    required_qualifiers=(),
                ),
            )
        }
    )

    bound = bind_task_slots(
        axis,
        resolver_view,
        load_task_contract_registry(PROJECT_ROOT),
    )

    contract = bound.task_contracts[0]
    assert contract.required_slot_kinds == (SlotKind.RELATION,)
    assert contract.readiness is TaskReadiness.COMPLETE
    assert contract.bindings[0].value_ids == ("managedBy",)


def test_unmapped_action_returns_blocked_non_executable_contract() -> None:
    source = _axis_resolution()
    frame = source.canonical_frames[0]
    unmapped = frame.model_copy(
        update={
            "frame_status": ResolutionStatus.UNMAPPED,
            "action_choice": frame.action_choice.model_copy(
                update={"state": ChoiceState.UNMAPPED, "selected_ids": ()}
            ),
        }
    )

    bound = bind_task_slots(
        source.model_copy(
            update={
                "canonical_frames": (unmapped,),
                "resolution_status": ResolutionStatus.UNMAPPED,
            }
        ),
        _view_with_semantics(("aum", "direct_alias")),
        load_task_contract_registry(PROJECT_ROOT),
    )

    contract = bound.task_contracts[0]
    assert contract.contract_id == "unresolved.v1"
    assert contract.action_id is None
    assert contract.readiness is TaskReadiness.BLOCKED


def test_context_carryover_uses_prior_bound_slot_without_model_slot_choice() -> None:
    source = resolution(context=True)
    first, second = source.canonical_frames
    first = first.model_copy(update={"slot_assignments": ()})
    carryover = second.slot_mutations[0].model_copy(
        update={"mutation_kind": SlotMutationKind.CARRYOVER}
    )
    second = second.model_copy(
        update={"slot_assignments": (), "slot_mutations": (carryover,)}
    )
    axis = source.model_copy(update={"canonical_frames": (first, second)})
    resolver_view = view(context=True).model_copy(
        update={
            "semantic_candidates": (
                ResolverViewSemanticCandidateGroup(
                    mention_id="mention-aum",
                    items=(
                        ResolverViewSemanticCandidate(
                            semantic_id="aum",
                            match_kind="direct_alias",
                            score=1_000_000,
                        ),
                    ),
                ),
            ),
            "evidence_candidates": (
                EvidenceCandidate(
                    evidence_id="evidence-aum",
                    segment_id="s1",
                    start_char=0,
                    end_char=3,
                    text="AUM",
                    source_kinds=(EvidenceSourceKind.SEMANTIC,),
                    offered_semantic_ids=("aum",),
                ),
            ),
        }
    )

    bound = bind_task_slots(
        axis,
        resolver_view,
        load_task_contract_registry(PROJECT_ROOT),
    )

    assert all(
        contract.readiness is TaskReadiness.COMPLETE
        for contract in bound.task_contracts
    )
    second_sort = next(
        binding
        for binding in bound.task_contracts[1].bindings
        if binding.slot_kind is SlotKind.SORT_KEY
    )
    assert second_sort.value_ids == ("aum",)
    assert second_sort.source is BindingSource.CONTEXT
