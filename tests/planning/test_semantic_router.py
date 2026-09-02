from __future__ import annotations

import pytest

from financial_agent.contracts.enums import AnswerDisposition, IntentType
from financial_agent.intent.query_contracts import (
    AxisReadiness,
    ContractReadiness,
    PlanReadiness,
)
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.semantic_router import route_semantic_query


@pytest.mark.parametrize(
    ("archetype", "expected"),
    [("rank-etf-aum.v1", CompilationRoute.FAST), (None, CompilationRoute.COMPOSE)],
)
def test_executable_sql_routes_fast_or_compose(archetype, expected) -> None:
    decision = route_semantic_query(
        action_ids=(IntentType.RANK,),
        axis_readiness=(AxisReadiness.COMPLETE,),
        contract_readiness=(ContractReadiness.COMPLETE,),
        plan_readiness=(PlanReadiness.EXECUTABLE,),
        matched_archetype_id=archetype,
        primitive_ids=("lookup-products", "rank-products"),
    )

    assert decision.route is expected
    assert decision.recommended_answer_disposition is AnswerDisposition.ANSWER
    assert decision.issue_codes == ()


@pytest.mark.parametrize("readiness", [PlanReadiness.EXPLORABLE, PlanReadiness.LIMITED])
def test_non_executable_grounded_plan_routes_to_limitation(readiness) -> None:
    decision = route_semantic_query(
        action_ids=(IntentType.AGGREGATE,),
        axis_readiness=(AxisReadiness.COMPLETE,),
        contract_readiness=(ContractReadiness.COMPLETE,),
        plan_readiness=(readiness,),
        matched_archetype_id=None,
        primitive_ids=("lookup-products", "aggregate-products"),
    )

    assert decision.route is CompilationRoute.EXPLORE
    assert decision.recommended_answer_disposition is AnswerDisposition.LIMITATION
    assert decision.issue_codes


def test_unresolved_axis_abstains_and_non_sql_stage05_capabilities_do_not_execute() -> None:
    unresolved = route_semantic_query(
        action_ids=(IntentType.RANK,),
        axis_readiness=(AxisReadiness.AMBIGUOUS,),
        contract_readiness=(ContractReadiness.COMPLETE,),
        plan_readiness=(PlanReadiness.EXECUTABLE,),
        matched_archetype_id=None,
        primitive_ids=("lookup-products", "rank-products"),
    )
    similarity = route_semantic_query(
        action_ids=(IntentType.SIMILAR,),
        axis_readiness=(AxisReadiness.COMPLETE,),
        contract_readiness=(ContractReadiness.COMPLETE,),
        plan_readiness=(PlanReadiness.EXECUTABLE,),
        matched_archetype_id=None,
        primitive_ids=("lookup-products", "similar-products"),
    )

    assert unresolved.route is CompilationRoute.ABSTAIN
    assert unresolved.recommended_answer_disposition is AnswerDisposition.ABSTAIN
    assert similarity.route is CompilationRoute.EXPLORE
    assert similarity.recommended_answer_disposition is AnswerDisposition.LIMITATION
    assert similarity.issue_codes == ("STAGE05_EXECUTOR_NOT_IMPLEMENTED",)


def test_any_blocked_plan_overrides_other_limited_or_stage05_frames() -> None:
    decision = route_semantic_query(
        action_ids=(IntentType.SIMILAR, IntentType.RANK),
        axis_readiness=(AxisReadiness.COMPLETE, AxisReadiness.COMPLETE),
        contract_readiness=(ContractReadiness.COMPLETE, ContractReadiness.COMPLETE),
        plan_readiness=(PlanReadiness.LIMITED, PlanReadiness.BLOCKED),
        matched_archetype_id=None,
        primitive_ids=("similar-products", "rank-products"),
    )

    assert decision.route is CompilationRoute.ABSTAIN
    assert decision.issue_codes == ("PLAN_BLOCKED",)
