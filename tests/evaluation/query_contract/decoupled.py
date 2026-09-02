"""Offline-only decoupled contract metrics over injected adjudicated axes."""

from __future__ import annotations

from dataclasses import dataclass

from financial_agent.intent.axis_locks import ExactSemanticLock
from financial_agent.intent.query_contract_registry import QueryContractRegistry
from financial_agent.intent.query_contract_solver import solve_query_contracts
from financial_agent.intent.resolution import ValidatedIntentResolutionV2
from financial_agent.intent.view import ResolverView


@dataclass(frozen=True, slots=True)
class DecoupledContractCase:
    case_id: str
    injected_axes: ValidatedIntentResolutionV2
    view: ResolverView
    exact_locks: tuple[ExactSemanticLock, ...]
    expected_candidate_ids_by_frame: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class DecoupledContractMetrics:
    frame_count: int
    supported_frame_count: int
    candidate_recall_count: int
    exact_contract_count: int
    false_complete_count: int
    compile_eligible_count: int

    @property
    def candidate_recall(self) -> float:
        return (
            self.candidate_recall_count / self.supported_frame_count
            if self.supported_frame_count
            else 1.0
        )

    @property
    def exact_contract(self) -> float:
        return (
            self.exact_contract_count / self.supported_frame_count
            if self.supported_frame_count
            else 1.0
        )

    @property
    def compile_eligibility(self) -> float:
        return (
            self.compile_eligible_count / self.supported_frame_count
            if self.supported_frame_count
            else 1.0
        )


def evaluate_decoupled_contract_resolution(
    cases: tuple[DecoupledContractCase, ...],
    registry: QueryContractRegistry,
) -> DecoupledContractMetrics:
    """Measure contract solving only; callers must inject reviewed axis artifacts."""

    frame_count = supported = recall = exact = false_complete = compile_eligible = 0
    for case in cases:
        solved = solve_query_contracts(
            resolution=case.injected_axes,
            view=case.view,
            exact_locks=case.exact_locks,
            registry=registry,
        )
        if len(solved.frames) != len(case.expected_candidate_ids_by_frame):
            raise ValueError(f"DECOUPLED_FRAME_COUNT_MISMATCH:{case.case_id}")
        for frame, expected_ids in zip(
            solved.frames, case.expected_candidate_ids_by_frame, strict=True
        ):
            frame_count += 1
            actual_ids = tuple(item.candidate_id for item in frame.complete_candidates)
            if expected_ids:
                supported += 1
                if set(expected_ids) <= set(actual_ids):
                    recall += 1
                if actual_ids == expected_ids:
                    exact += 1
                if len(actual_ids) == 1 and actual_ids == expected_ids:
                    compile_eligible += 1
            elif len(actual_ids) == 1:
                false_complete += 1
    return DecoupledContractMetrics(
        frame_count=frame_count,
        supported_frame_count=supported,
        candidate_recall_count=recall,
        exact_contract_count=exact,
        false_complete_count=false_complete,
        compile_eligible_count=compile_eligible,
    )
