from __future__ import annotations

from pathlib import Path

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.draft import EntityHintV2
from financial_agent.intent.axis_locks import ExactSemanticLock
from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.intent.query_contract_solver import (
    MAX_COMPLETE_CANDIDATES_PER_FRAME,
    MAX_CANDIDATES_PER_ROLE,
    solve_query_contracts,
)
from financial_agent.intent.query_contracts import (
    ContractReadiness,
    ProvenanceSourceKind,
    QueryOperatorId,
)
from financial_agent.intent.types import EntitySemanticRole
from financial_agent.intent.view import (
    ResolverViewConcept,
    ResolverViewSemanticCandidate,
    ResolverViewSemanticCandidateGroup,
)
from tests.planning.fixtures import frame, resolution, view


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = load_query_contract_registry(PROJECT_ROOT)


def _axis(action: IntentType = IntentType.RANK, *, family: ProductFamily = ProductFamily.DOMESTIC_ETF):
    source = resolution()
    source_frame = frame(
        "frame-1",
        0,
        metric_id="aum",
        limit_id="literal-limit-5",
        action=action,
        assignments=(),
    )
    source_frame = source_frame.model_copy(
        update={
            "product_family_choice": source_frame.product_family_choice.model_copy(
                update={"selected_ids": (family,)}
            )
        }
    )
    return source.model_copy(update={"canonical_frames": (source_frame,)})


def _semantic_view(*concept_ids: str):
    source = view()
    definitions = {item.concept_id: item for item in source.concept_definitions}
    definitions.setdefault(
        "fee_rate",
        ResolverViewConcept(
            concept_id="fee_rate",
            kind="metric",
            definition_ko="보수율",
            value_kind="decimal",
            allowed_product_families=("domestic_etf", "overseas_etf", "public_fund"),
            allowed_ontology_types=("FinancialProduct",),
            required_qualifiers=(),
            allowed_operators=("equals", "greater_than", "less_than"),
            missingness_sensitive=True,
            normalization_rule="percentage",
        ),
    )
    return source.model_copy(
        update={
            "semantic_candidates": tuple(
                ResolverViewSemanticCandidateGroup(
                    mention_id=f"mention-s1-{index}-{index + 1}",
                    items=(
                        ResolverViewSemanticCandidate(
                            semantic_id=concept_id,
                            match_kind="direct_alias",
                            score=1_000_000,
                        ),
                    ),
                )
                for index, concept_id in enumerate(concept_ids)
            ),
            "concept_definitions": tuple(definitions.values()),
        }
    )


def _lock(role: str, canonical_id: str, *, span: str = "mention-s1-0-1"):
    return ExactSemanticLock(
        lock_id=f"lock-{role}-{canonical_id}",
        role=role,
        canonical_id=canonical_id,
        evidence_span_ids=(span,),
        source="literal" if role == "literal" else "direct_alias" if role == "field" else "canonical",
    )


def test_unique_rank_candidate_uses_exact_field_and_registered_defaults() -> None:
    result = solve_query_contracts(
        resolution=_axis(),
        view=_semantic_view("aum"),
        exact_locks=(_lock("field", "aum"),),
        registry=REGISTRY,
    )

    solved = result.frames[0]
    assert solved.contract_readiness.readiness is ContractReadiness.COMPLETE
    assert len(solved.complete_candidates) == 1
    contract = solved.complete_candidates[0].contract
    assert contract.ordering[0].field_concept_id == "aum"
    assert contract.ordering[0].direction_policy_id == "default-direction-descending.v1"
    assert contract.limit == 5


def test_ambiguous_rank_candidates_have_content_derived_ids_and_dedupe_equivalents() -> None:
    first = solve_query_contracts(
        resolution=_axis(),
        view=_semantic_view("aum", "fee_rate", "aum"),
        exact_locks=(),
        registry=REGISTRY,
    )
    second = solve_query_contracts(
        resolution=_axis(),
        view=_semantic_view("fee_rate", "aum"),
        exact_locks=(),
        registry=REGISTRY,
    )

    assert first.frames[0].contract_readiness.readiness is ContractReadiness.AMBIGUOUS
    assert len(first.frames[0].complete_candidates) == 2
    assert {item.candidate_id for item in first.frames[0].complete_candidates} == {
        item.candidate_id for item in second.frames[0].complete_candidates
    }


def test_candidate_id_ignores_evidence_source_but_provenance_preserves_exact_lock() -> None:
    resolver_view = _semantic_view("aum")
    exact = solve_query_contracts(
        resolution=_axis(),
        view=resolver_view,
        exact_locks=(_lock("field", "aum"),),
        registry=REGISTRY,
    )
    offered = solve_query_contracts(
        resolution=_axis(),
        view=resolver_view,
        exact_locks=(),
        registry=REGISTRY,
    )

    exact_candidate = exact.frames[0].complete_candidates[0]
    assert exact_candidate.candidate_id == offered.frames[0].complete_candidates[0].candidate_id
    field_provenance = next(
        item
        for item in exact_candidate.contract.provenance
        if item.semantic_input_id == "ordering.0.field_concept_id"
    )
    assert field_provenance.source_kind is ProvenanceSourceKind.EXACT_LOCK
    assert field_provenance.source_ref == "lock-field-aum"


def test_family_inapplicable_exact_field_is_blocked_with_stable_rejection() -> None:
    resolver_view = _semantic_view("aum")
    aum = next(item for item in resolver_view.concept_definitions if item.concept_id == "aum")
    resolver_view = resolver_view.model_copy(
        update={
            "concept_definitions": tuple(
                aum.model_copy(update={"allowed_product_families": ("public_fund",)})
                if item.concept_id == "aum"
                else item
                for item in resolver_view.concept_definitions
            )
        }
    )

    result = solve_query_contracts(
        resolution=_axis(),
        view=resolver_view,
        exact_locks=(_lock("field", "aum"),),
        registry=REGISTRY,
    )

    assert result.frames[0].contract_readiness.readiness is ContractReadiness.BLOCKED
    assert "FIELD_NOT_APPLICABLE_TO_FAMILY" in {
        item.reason_code for item in result.frames[0].rejections
    }


def test_screen_prunes_operator_value_kind_mismatch_instead_of_false_complete() -> None:
    resolver_view = _semantic_view("fee_rate")
    text_field = next(
        item for item in resolver_view.concept_definitions if item.concept_id == "fee_rate"
    ).model_copy(update={"value_kind": "text"})
    resolver_view = resolver_view.model_copy(
        update={
            "concept_definitions": tuple(
                text_field if item.concept_id == "fee_rate" else item
                for item in resolver_view.concept_definitions
            )
        }
    )

    result = solve_query_contracts(
        resolution=_axis(IntentType.SCREEN),
        view=resolver_view,
        exact_locks=(
            _lock("field", "fee_rate"),
            _lock("operator", QueryOperatorId.LTE.value, span="operator-s1-5-7"),
            _lock("literal", "literal-risk-3", span="literal-risk-3"),
        ),
        registry=REGISTRY,
    )

    assert result.frames[0].contract_readiness.readiness is ContractReadiness.BLOCKED
    assert "FIELD_OPERATOR_VALUE_INCOMPATIBLE" in {
        item.reason_code for item in result.frames[0].rejections
    }


def test_rank_preserves_a_complete_exact_predicate_instead_of_dropping_locks() -> None:
    result = solve_query_contracts(
        resolution=_axis(IntentType.RANK),
        view=_semantic_view("fee_rate"),
        exact_locks=(
            _lock("field", "fee_rate"),
            _lock("operator", QueryOperatorId.LTE.value, span="operator-s1-5-7"),
            _lock("literal", "literal-risk-3", span="literal-risk-3"),
        ),
        registry=REGISTRY,
    )

    assert result.frames[0].complete_candidates
    assert {
        item.contract.predicate.operator_id
        for item in result.frames[0].complete_candidates
    } == {QueryOperatorId.LTE}


def test_role_incompatible_exact_literal_blocks_instead_of_being_dropped() -> None:
    result = solve_query_contracts(
        resolution=_axis(IntentType.LOOKUP),
        view=_semantic_view("aum"),
        exact_locks=(_lock("literal", "literal-risk-3", span="literal-risk-3"),),
        registry=REGISTRY,
    )

    assert result.frames[0].complete_candidates == ()
    assert result.frames[0].contract_readiness.reason_codes == (
        "EXACT_LOCK_ROLE_INCOMPATIBLE",
    )


def test_context_result_set_becomes_typed_prior_result_scope() -> None:
    source = resolution(context=True)
    frames = tuple(item.model_copy(update={"slot_assignments": ()}) for item in source.canonical_frames)
    source = source.model_copy(update={"canonical_frames": frames})
    resolver_view = _semantic_view("aum", "trailing_1y_historical_cumulative_return")
    second_group = resolver_view.semantic_candidates[1].model_copy(
        update={"mention_id": "mention-s2-0-3"}
    )
    resolver_view = resolver_view.model_copy(
        update={
            "semantic_candidates": (resolver_view.semantic_candidates[0], second_group),
            "reference_candidates": view(context=True).reference_candidates,
        }
    )

    result = solve_query_contracts(
        resolution=source,
        view=resolver_view,
        exact_locks=(),
        registry=REGISTRY,
    )

    assert result.frames[1].complete_candidates
    assert {
        item.contract.scope.prior_result_binding
        for item in result.frames[1].complete_candidates
    } == {"frame-1"}


def test_unresolved_entity_role_enumerates_only_offered_candidate_ids() -> None:
    source = _axis(IntentType.SIMILAR)
    source_frame = source.canonical_frames[0].model_copy(
        update={"entity_hint_ids": ("hint-anchor",)}
    )
    hint = EntityHintV2(
        entity_hint_id="hint-anchor",
        mention_id=("mention-anchor",),
        evidence_span_ids=("evidence-anchor",),
        expected_entity_type_ids=("ETF",),
        candidate_entity_ids=("entity-a", "entity-b"),
        selected_candidate_ids=(),
        reason_code="ambiguous",
        semantic_role=EntitySemanticRole.FRAME_SUBJECT,
        relation_id=(),
    )
    source = source.model_copy(
        update={"canonical_frames": (source_frame,), "entity_hints": (hint,)}
    )

    result = solve_query_contracts(
        resolution=source,
        view=_semantic_view("aum"),
        exact_locks=(_lock("field", "aum"),),
        registry=REGISTRY,
    )

    assert result.frames[0].contract_readiness.readiness is ContractReadiness.AMBIGUOUS
    assert {
        item.contract.similarity.anchor_ref
        for item in result.frames[0].complete_candidates
    } == {"entity-a", "entity-b"}


def test_role_bound_is_visible_and_never_truncated_to_unique() -> None:
    source = _semantic_view("aum")
    aum = next(item for item in source.concept_definitions if item.concept_id == "aum")
    concept_ids = tuple(f"metric-{index}" for index in range(MAX_CANDIDATES_PER_ROLE + 1))
    source = source.model_copy(
        update={
            "semantic_candidates": tuple(
                ResolverViewSemanticCandidateGroup(
                    mention_id=f"mention-s1-{index}-{index + 1}",
                    items=(ResolverViewSemanticCandidate(semantic_id=item, match_kind="trigram", score=900_000),),
                )
                for index, item in enumerate(concept_ids)
            ),
            "concept_definitions": tuple(
                aum.model_copy(update={"concept_id": item, "required_qualifiers": ()})
                for item in concept_ids
            ),
        }
    )

    result = solve_query_contracts(
        resolution=_axis(), view=source, exact_locks=(), registry=REGISTRY
    )

    assert result.frames[0].contract_readiness.readiness is ContractReadiness.AMBIGUOUS
    assert result.frames[0].contract_readiness.reason_codes == ("CANDIDATE_BOUND_REACHED",)
    assert len(result.frames[0].complete_candidates) != 1


def test_complete_candidate_bound_is_visible() -> None:
    source = _semantic_view("aum")
    aum = next(item for item in source.concept_definitions if item.concept_id == "aum")
    concept_ids = tuple(f"metric-{index}" for index in range(MAX_CANDIDATES_PER_ROLE))
    source = source.model_copy(
        update={
            "semantic_candidates": tuple(
                ResolverViewSemanticCandidateGroup(
                    mention_id=f"mention-s1-{index}-{index + 1}",
                    items=(ResolverViewSemanticCandidate(semantic_id=item, match_kind="trigram", score=900_000),),
                )
                for index, item in enumerate(concept_ids)
            ),
            "concept_definitions": tuple(
                aum.model_copy(update={"concept_id": item, "required_qualifiers": ()})
                for item in concept_ids
            ),
        }
    )

    result = solve_query_contracts(
        resolution=_axis(IntentType.AGGREGATE),
        view=source,
        exact_locks=(),
        registry=REGISTRY,
    )

    assert MAX_COMPLETE_CANDIDATES_PER_FRAME == 64
    assert len(result.frames[0].complete_candidates) == MAX_COMPLETE_CANDIDATES_PER_FRAME
    assert result.frames[0].contract_readiness.readiness is ContractReadiness.AMBIGUOUS
    assert result.frames[0].contract_readiness.reason_codes == ("CANDIDATE_BOUND_REACHED",)


def test_public_fund_aggregate_candidates_use_registered_population_policy() -> None:
    result = solve_query_contracts(
        resolution=_axis(IntentType.AGGREGATE, family=ProductFamily.PUBLIC_FUND),
        view=_semantic_view("aum"),
        exact_locks=(_lock("field", "aum"),),
        registry=REGISTRY,
    )

    assert result.frames[0].complete_candidates
    assert {
        item.contract.aggregation.population_grain_id
        for item in result.frames[0].complete_candidates
    } == {"representative-product.v1"}
    assert {
        item.contract.aggregation.dedup_policy_id
        for item in result.frames[0].complete_candidates
    } == {"public-fund-representative-share.v1"}


def test_calculation_without_an_offered_recipe_fails_closed() -> None:
    result = solve_query_contracts(
        resolution=_axis(IntentType.CALCULATE),
        view=_semantic_view("aum"),
        exact_locks=(_lock("field", "aum"),),
        registry=REGISTRY,
    )

    assert result.frames[0].complete_candidates == ()
    assert result.frames[0].contract_readiness.readiness is ContractReadiness.BLOCKED
    assert result.frames[0].contract_readiness.reason_codes == ("RECIPE_NOT_OFFERED",)
