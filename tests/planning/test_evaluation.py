from pathlib import Path

from financial_agent.intent.catalog import load_catalog
from financial_agent.planning.compiler import QueryPlanCompiler
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.evaluation import (
    DecoupledPlanningCase,
    evaluate_decoupled_cases,
)
from financial_agent.planning.registry import load_planning_registry

from .fixtures import resolution, view


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def compiler() -> QueryPlanCompiler:
    return QueryPlanCompiler(
        catalog=load_catalog(PROJECT_ROOT),
        registry=load_planning_registry(PROJECT_ROOT),
    )


def test_evaluator_separates_route_exactness_losslessness_and_false_fast() -> None:
    """Catches one aggregate score hiding a dangerous OOD-to-Fast error."""
    rank_resolution = resolution()
    rank_view = view()
    expected = compiler().compile(rank_resolution, rank_view)
    report = evaluate_decoupled_cases(
        compiler(),
        (
            DecoupledPlanningCase(
                case_id="rank-fast",
                resolution=rank_resolution,
                view=rank_view,
                expected_route=CompilationRoute.FAST,
                expected_query_plan=expected.query_plan,
                expected_lowering_source_ids=frozenset(
                    item.source_id for item in expected.lowering_records
                ),
                is_ood=False,
            ),
            DecoupledPlanningCase(
                case_id="forced-route-mismatch",
                resolution=rank_resolution,
                view=rank_view,
                expected_route=CompilationRoute.ABSTAIN,
                expected_query_plan=None,
                expected_lowering_source_ids=frozenset(),
                is_ood=True,
            ),
        ),
    )

    assert report.total_cases == 2
    assert report.route_correct == 1
    assert report.query_plan_exact == 1
    assert report.deterministic_cases == 2
    assert report.lossless_cases == 1
    assert report.false_fast_count == 1
    assert report.promotion_eligible is False
    confusion = {
        (item.expected, item.predicted): item.count
        for item in report.route_confusion
    }
    assert confusion[(CompilationRoute.ABSTAIN, CompilationRoute.FAST)] == 1


def test_all_correct_decoupled_cases_pass_promotion_boundary() -> None:
    """Catches promotion staying blocked after every measured compiler gate passes."""
    source = resolution(context=True)
    source_view = view(context=True)
    expected = compiler().compile(source, source_view)
    report = evaluate_decoupled_cases(
        compiler(),
        (
            DecoupledPlanningCase(
                case_id="context-rerank",
                resolution=source,
                view=source_view,
                expected_route=CompilationRoute.FAST,
                expected_query_plan=expected.query_plan,
                expected_lowering_source_ids=frozenset(
                    item.source_id for item in expected.lowering_records
                ),
                is_ood=False,
            ),
        ),
    )

    assert report.route_accuracy == 1.0
    assert report.query_plan_exact_rate == 1.0
    assert report.lossless_rate == 1.0
    assert report.false_fast_rate == 0.0
    assert report.promotion_eligible is True
