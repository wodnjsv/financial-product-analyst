from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from financial_agent.contracts.base import ContractModel
from financial_agent.contracts.canonical import canonical_json_bytes
from financial_agent.contracts.query import QueryPlan
from financial_agent.intent.resolution import ValidatedIntentResolutionV2
from financial_agent.intent.view import ResolverView

from .compiler import QueryPlanCompiler
from .contracts import CompilationRoute


@dataclass(frozen=True, slots=True)
class DecoupledPlanningCase:
    case_id: str
    resolution: ValidatedIntentResolutionV2
    view: ResolverView
    expected_route: CompilationRoute
    expected_query_plan: QueryPlan | None
    expected_lowering_source_ids: frozenset[str]
    is_ood: bool


class RouteConfusion(ContractModel):
    expected: CompilationRoute
    predicted: CompilationRoute
    count: int


class PlanningEvaluationReport(ContractModel):
    total_cases: int
    route_correct: int
    route_accuracy: float
    query_plan_exact: int
    query_plan_exact_rate: float
    deterministic_cases: int
    lossless_denominator: int
    lossless_cases: int
    lossless_rate: float
    false_fast_count: int
    ood_denominator: int
    false_fast_rate: float
    route_confusion: tuple[RouteConfusion, ...]
    promotion_eligible: bool


def evaluate_decoupled_cases(
    compiler: QueryPlanCompiler,
    cases: tuple[DecoupledPlanningCase, ...],
) -> PlanningEvaluationReport:
    confusion: Counter[tuple[CompilationRoute, CompilationRoute]] = Counter()
    route_correct = 0
    exact = 0
    deterministic = 0
    lossless = 0
    lossless_denominator = 0
    false_fast = 0
    ood_denominator = 0
    for case in cases:
        first = compiler.compile(case.resolution, case.view)
        second = compiler.compile(case.resolution, case.view)
        confusion[(case.expected_route, first.route)] += 1
        route_correct += int(first.route is case.expected_route)
        deterministic += int(canonical_json_bytes(first) == canonical_json_bytes(second))
        if case.expected_query_plan is None:
            exact += int(first.query_plan is None)
        elif first.query_plan is not None:
            exact += int(
                canonical_json_bytes(first.query_plan)
                == canonical_json_bytes(case.expected_query_plan)
            )
        if case.expected_lowering_source_ids:
            lossless_denominator += 1
            actual_sources = {item.source_id for item in first.lowering_records}
            lossless += int(case.expected_lowering_source_ids <= actual_sources)
        if case.is_ood:
            ood_denominator += 1
            false_fast += int(first.route is CompilationRoute.FAST)

    total = len(cases)
    route_accuracy = _rate(route_correct, total)
    exact_rate = _rate(exact, total)
    deterministic_rate = _rate(deterministic, total)
    lossless_rate = _rate(lossless, lossless_denominator)
    false_fast_rate = _rate(false_fast, ood_denominator, empty=0.0)
    return PlanningEvaluationReport(
        total_cases=total,
        route_correct=route_correct,
        route_accuracy=route_accuracy,
        query_plan_exact=exact,
        query_plan_exact_rate=exact_rate,
        deterministic_cases=deterministic,
        lossless_denominator=lossless_denominator,
        lossless_cases=lossless,
        lossless_rate=lossless_rate,
        false_fast_count=false_fast,
        ood_denominator=ood_denominator,
        false_fast_rate=false_fast_rate,
        route_confusion=tuple(
            RouteConfusion(expected=expected, predicted=predicted, count=count)
            for (expected, predicted), count in sorted(
                confusion.items(), key=lambda item: (item[0][0].value, item[0][1].value)
            )
        ),
        promotion_eligible=(
            total > 0
            and route_accuracy >= 0.90
            and exact_rate >= 0.90
            and deterministic_rate == 1.0
            and lossless_denominator > 0
            and lossless_rate == 1.0
            and false_fast_rate <= 0.02
        ),
    )


def _rate(numerator: int, denominator: int, *, empty: float = 1.0) -> float:
    return numerator / denominator if denominator else empty
