from pathlib import Path

from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.intent.view import (
    ResolverViewSemanticCandidate,
    ResolverViewSemanticCandidateGroup,
)
from tests.evaluation.query_contract.decoupled import (
    DecoupledContractCase,
    evaluate_decoupled_contract_resolution,
)
from tests.planning.fixtures import resolution, view


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _view_with_aum_candidate():
    return view().model_copy(
        update={
            "semantic_candidates": (
                ResolverViewSemanticCandidateGroup(
                    mention_id="mention-s1-0-3",
                    items=(
                        ResolverViewSemanticCandidate(
                            semantic_id="aum",
                            match_kind="direct_alias",
                            score=1_000_000,
                        ),
                    ),
                ),
            )
        }
    )


def test_decoupled_metrics_measure_contracts_with_injected_axes_only() -> None:
    registry = load_query_contract_registry(PROJECT_ROOT)
    injected = resolution()
    resolver_view = _view_with_aum_candidate()
    adjudicated_candidate_id = (
        "query-contract-"
        "10b14ecd356b782e5f0c8bc1a42115c9fb1ecd56c60f7455026df17a4b702e56"
    )

    metrics = evaluate_decoupled_contract_resolution(
        (
            DecoupledContractCase(
                case_id="rank-aum",
                injected_axes=injected,
                view=resolver_view,
                exact_locks=(),
                expected_candidate_ids_by_frame=((adjudicated_candidate_id,),),
            ),
        ),
        registry,
    )

    assert metrics.candidate_recall >= 0.99
    assert metrics.exact_contract >= 0.95
    assert metrics.false_complete_count == 0
    assert metrics.compile_eligibility == 1.0


def test_decoupled_metrics_expose_false_complete_without_blaming_axes() -> None:
    registry = load_query_contract_registry(PROJECT_ROOT)
    injected = resolution()
    resolver_view = _view_with_aum_candidate()

    metrics = evaluate_decoupled_contract_resolution(
        (
            DecoupledContractCase(
                case_id="unsupported-contract",
                injected_axes=injected,
                view=resolver_view,
                exact_locks=(),
                expected_candidate_ids_by_frame=((),),
            ),
        ),
        registry,
    )

    assert metrics.false_complete_count == 1
    assert metrics.candidate_recall_count == 0
    assert metrics.exact_contract_count == 0
