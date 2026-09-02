"""Deterministic four-path routing for V2 semantic contracts."""

from __future__ import annotations

from pydantic import ConfigDict

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.enums import AnswerDisposition, IntentType
from financial_agent.intent.query_contracts import AxisReadiness, ContractReadiness, PlanReadiness

from .contracts import CompilationRoute
from .primitive_contracts import CANONICAL_PRIMITIVES


_STAGE05_ONLY = frozenset({IntentType.CALCULATE, IntentType.SIMILAR})


class SemanticRouteDecision(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    route: CompilationRoute
    recommended_answer_disposition: AnswerDisposition
    issue_codes: tuple[Identifier, ...]


def route_semantic_query(
    *,
    action_ids: tuple[IntentType, ...],
    axis_readiness: tuple[AxisReadiness, ...],
    contract_readiness: tuple[ContractReadiness, ...],
    plan_readiness: tuple[PlanReadiness, ...],
    matched_archetype_id: str | None,
    primitive_ids: tuple[str, ...],
) -> SemanticRouteDecision:
    if not action_ids or not (
        len(action_ids) == len(axis_readiness) == len(contract_readiness) == len(plan_readiness)
    ):
        return _abstain("READINESS_CARDINALITY_MISMATCH")
    if set(primitive_ids) - set(CANONICAL_PRIMITIVES):
        return _abstain("EXECUTION_PRIMITIVE_NOT_REGISTERED")
    if any(item is not AxisReadiness.COMPLETE for item in axis_readiness):
        return _abstain("AXIS_NOT_COMPLETE")
    if any(item is not ContractReadiness.COMPLETE for item in contract_readiness):
        if any(item is ContractReadiness.BLOCKED for item in contract_readiness):
            return _limitation("CONTRACT_NOT_COMPLETE")
        return _abstain("CONTRACT_AMBIGUOUS")
    if any(item is PlanReadiness.BLOCKED for item in plan_readiness):
        return _abstain("PLAN_BLOCKED")
    if any(item in _STAGE05_ONLY for item in action_ids):
        return _limitation("STAGE05_EXECUTOR_NOT_IMPLEMENTED")
    if any(item in {PlanReadiness.EXPLORABLE, PlanReadiness.LIMITED} for item in plan_readiness):
        return _limitation("PLAN_NOT_EXECUTABLE")
    if not primitive_ids:
        return _abstain("EXECUTION_PRIMITIVE_REQUIRED")
    if matched_archetype_id:
        return SemanticRouteDecision(
            route=CompilationRoute.FAST,
            recommended_answer_disposition=AnswerDisposition.ANSWER,
            issue_codes=(),
        )
    return SemanticRouteDecision(
        route=CompilationRoute.COMPOSE,
        recommended_answer_disposition=AnswerDisposition.ANSWER,
        issue_codes=(),
    )


def _limitation(code: str) -> SemanticRouteDecision:
    return SemanticRouteDecision(
        route=CompilationRoute.EXPLORE,
        recommended_answer_disposition=AnswerDisposition.LIMITATION,
        issue_codes=(code,),
    )


def _abstain(code: str) -> SemanticRouteDecision:
    return SemanticRouteDecision(
        route=CompilationRoute.ABSTAIN,
        recommended_answer_disposition=AnswerDisposition.ABSTAIN,
        issue_codes=(code,),
    )
