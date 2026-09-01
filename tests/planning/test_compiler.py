from pathlib import Path

from financial_agent.contracts.enums import (
    Capability,
    InitialAnswerability,
    ReferenceTargetKind,
)
from financial_agent.contracts.values import decode_contract_value
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.types import (
    ResolutionStatus,
    SemanticCoverageState,
    SemanticTag,
)
from financial_agent.planning.compiler import QueryPlanCompiler
from financial_agent.planning.compiler import CompilerInvariantError
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.registry import load_planning_registry

from .fixtures import resolution, screen_resolution, view


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def compiler() -> QueryPlanCompiler:
    return QueryPlanCompiler(
        catalog=load_catalog(PROJECT_ROOT),
        registry=load_planning_registry(PROJECT_ROOT),
    )


def test_single_family_rank_lowers_literals_and_uses_fast_archetype() -> None:
    """Catches loss of the AUM sort key or top-five literal during lowering."""
    result = compiler().compile(resolution(), view())

    assert result.route is CompilationRoute.FAST
    assert result.matched_archetype_id == "rank.single-family.v1"
    assert result.query_plan is not None
    assert result.query_plan.requested_capabilities == (
        Capability.RDB_LOOKUP,
        Capability.RANKING,
    )
    assert [item.metric_id for item in result.query_plan.metrics] == ["aum"]
    limit = next(
        item for item in result.query_plan.filters if item.field_id == "result_limit"
    )
    assert decode_contract_value(limit.value) == 5
    assert result.query_plan.initial_answerability is InitialAnswerability.SUPPORTED


def test_context_rerank_lowers_binding_reference_and_dependency() -> None:
    """Catches '그 상품 중' being re-run against the entire ETF universe."""
    result = compiler().compile(resolution(context=True), view(context=True))

    assert result.route is CompilationRoute.FAST
    assert result.matched_archetype_id == "rank.context-rerank.v1"
    assert result.query_plan is not None
    assert result.query_plan.binding_specs[0].binding_name == (
        "binding:frame-1:top_k_products"
    )
    assert result.query_plan.dependency_edges[0].upstream_subtask_id == "frame-1"
    assert result.query_plan.dependency_edges[0].downstream_subtask_id == "frame-2"
    assert result.query_plan.resolved_references[0].target_kind is (
        ReferenceTargetKind.BINDING
    )
    assert result.query_plan.resolved_references[0].target_id == (
        "binding:frame-1:top_k_products"
    )
    assert [item.metric_id for item in result.query_plan.metrics] == [
        "aum",
        "trailing_1y_historical_cumulative_return",
    ]


def test_policy_and_context_boundaries_never_reach_fast() -> None:
    """Catches policy or unresolved context questions escaping as executable work."""
    policy = compiler().compile(
        resolution(tags=(SemanticTag.PERSONALIZED_ADVICE,)),
        view(),
    )
    unresolved = compiler().compile(
        resolution(status=ResolutionStatus.CONTEXT_UNRESOLVED),
        view(),
    )

    assert policy.route is CompilationRoute.ABSTAIN
    assert policy.query_plan is None
    assert policy.blocking_issues[0].code == "POLICY_BLOCKED"
    assert unresolved.route is CompilationRoute.ABSTAIN
    assert unresolved.blocking_issues[0].code == "CONTEXT_UNRESOLVED"


def test_lexical_ood_uses_bounded_explore_plan() -> None:
    """Catches an unknown property becoming Fast or unrestricted free-form SQL."""
    result = compiler().compile(
        resolution(
            status=ResolutionStatus.UNMAPPED,
            coverage=SemanticCoverageState.PARTIAL,
        ),
        view(),
    )

    assert result.route is CompilationRoute.EXPLORE
    assert result.query_plan is not None
    assert result.primitive_ids == ("explore-catalog",)
    assert result.query_plan.requested_capabilities == (Capability.KEYWORD_SEARCH,)
    assert [operation.operation_id for operation in result.query_plan.operations] == [
        "operation:frame-1:explore-catalog"
    ]


def test_compilation_is_byte_deterministic() -> None:
    """Catches collection ordering or process state changing a persisted plan."""
    from financial_agent.contracts.canonical import canonical_json_bytes

    first = compiler().compile(resolution(context=True), view(context=True))
    second = compiler().compile(resolution(context=True), view(context=True))

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_screen_filter_groups_field_operator_and_literal_without_loss() -> None:
    """Catches a screen operation running without its risk-grade predicate."""
    result = compiler().compile(screen_resolution(), view())

    assert result.route is CompilationRoute.FAST
    assert result.matched_archetype_id == "screen.single-family.v1"
    assert result.query_plan is not None
    predicate = next(
        item
        for item in result.query_plan.filters
        if item.field_id == "product_risk_grade"
    )
    assert predicate.operator_id == "less_than"
    assert str(decode_contract_value(predicate.value)) == "3"
    assert {
        item.source_id
        for item in result.lowering_records
        if item.target_kind == "filter"
    } >= {"slot-filter-field", "slot-filter-op", "slot-filter-value"}


def test_ambiguous_filter_group_fails_closed() -> None:
    """Catches two operators being paired with one value by arbitrary ordering."""
    result = compiler().compile(screen_resolution(ambiguous_filter=True), view())

    assert result.route is CompilationRoute.ABSTAIN
    assert result.blocking_issues[0].code == "AMBIGUOUS_FILTER_GROUP"


def test_valid_unregistered_action_combination_uses_compose() -> None:
    """Catches the archetype catalog being mistaken for total intent coverage."""
    source = resolution(context=True)
    second = source.canonical_frames[1].model_copy(
        update={
            "action_choice": source.canonical_frames[1].action_choice.model_copy(
                update={"selected_ids": (source.canonical_frames[1].action_choice.selected_ids[0].COMPARE,)}
            )
        }
    )
    composed = source.model_copy(
        update={
            "canonical_frames": (source.canonical_frames[0], second),
            "context_links": (),
            "final_tags": (SemanticTag.MULTI_STEP,),
        }
    )

    result = compiler().compile(composed, view(context=True))

    assert result.route is CompilationRoute.COMPOSE
    assert result.matched_archetype_id is None
    assert result.query_plan is not None
    assert [item.intent_type.value for item in result.query_plan.subtasks] == [
        "rank",
        "compare",
    ]


def test_compiler_rejects_resolution_and_view_pin_mismatch() -> None:
    """Catches request candidates from another dataset being replayed."""
    mismatched = view().model_copy(
        update={
            "active_dataset_pin": view().active_dataset_pin.model_copy(
                update={"dataset_version": "dataset-v2"}
            )
        }
    )

    import pytest

    with pytest.raises(CompilerInvariantError, match="DATASET_PIN_MISMATCH"):
        compiler().compile(resolution(), mismatched)
