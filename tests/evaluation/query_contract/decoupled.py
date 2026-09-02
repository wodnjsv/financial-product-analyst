"""Offline-only decoupled contract metrics over injected adjudicated axes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from financial_agent.intent.axis_locks import ExactSemanticLock
from financial_agent.intent.query_contract_registry import QueryContractRegistry
from financial_agent.intent.query_contract_solver import solve_query_contracts
from financial_agent.intent.resolution import ValidatedIntentResolutionV2
from financial_agent.intent.view import ResolverView
from tests.evaluation.query_contract.coverage import load_requirement_snapshot


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


@dataclass(frozen=True, slots=True)
class FrozenSnapshotContractMetrics:
    total_frame_count: int
    supported_frame_count: int
    unsupported_frame_count: int
    intentionally_blocked_frame_count: int
    candidate_recall_count: int
    exact_contract_count: int
    false_complete_count: int
    compile_eligible_count: int

    @property
    def candidate_recall(self) -> float:
        return self.candidate_recall_count / self.supported_frame_count

    @property
    def exact_contract(self) -> float:
        return self.exact_contract_count / self.supported_frame_count

    @property
    def compile_eligibility(self) -> float:
        denominator = (
            self.supported_frame_count - self.intentionally_blocked_frame_count
        )
        return self.compile_eligible_count / denominator if denominator else 1.0


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


def evaluate_frozen_requirement_snapshot(
    project_root: Path,
    registry: QueryContractRegistry,
) -> FrozenSnapshotContractMetrics:
    """Evaluate all 209 frozen held-out frames with reviewed axes injected.

    This is the structural contract gate available before physical planning. A
    held-out frame's adjudicated action is injected, and its product-family,
    entity, or prior-result axis supplies `scope` even when the generated
    requirement vector omits that redundant component. Similarity's registered
    minimum-coverage policy supplies its required coverage threshold.
    `calculate` remains an explicitly counted current-stage compile block
    because Task 4 deliberately has no offered recipe registry; it stays in
    candidate recall and exact contract denominators and is excluded only from
    compile eligibility.
    """

    root = project_root.resolve()
    snapshot = load_requirement_snapshot(root)
    payload = json.loads(
        (
            root
            / "tests/evaluation/query_contract/query_contract_requirements.v1.json"
        ).read_text(encoding="utf-8")
    )
    heldout = tuple(
        item for item in payload["requirements"] if item["source"] == "heldout"
    )
    if len(heldout) != snapshot.heldout_frame_count:
        raise ValueError("DECOUPLED_REQUIREMENT_COUNT_MISMATCH")

    source_pin = payload["sources"]["heldout"]["path"]
    heldout_source = json.loads((root / source_pin).read_text(encoding="utf-8"))
    frames_by_key = {
        (case["case_id"], frame["ordinal"]): frame
        for case in heldout_source["cases"]
        for frame in case["expected_frames"]
        if frame["action_ids"]
    }
    supported = unsupported = blocked = recall = exact = false_complete = eligible = 0
    for requirement in heldout:
        if requirement["support_status"] == "unsupported":
            unsupported += 1
            if not requirement.get("reason_code"):
                raise ValueError("DECOUPLED_UNSUPPORTED_REASON_MISSING")
            if requirement.get("action_id"):
                false_complete += int(
                    any(
                        variant.action_id.value == requirement["action_id"]
                        for variant in registry.variants_by_id.values()
                    )
                )
            continue

        supported += 1
        frame = frames_by_key[(requirement["case_id"], requirement["frame_ordinal"])]
        expected_components = set(requirement["required_components"])
        if (
            frame["product_family_ids"]
            or frame["entity_type_ids"]
            or requirement["action_id"] == "similar"
        ):
            expected_components.add("scope")
        if requirement["action_id"] == "similar":
            expected_components.add("similarity.coverage_threshold")
        candidates = tuple(
            variant
            for variant in registry.variants_by_id.values()
            if variant.action_id.value == requirement["action_id"]
            and set(variant.required_components) == expected_components
        )
        if candidates:
            recall += 1
        if len(candidates) == 1:
            exact += 1
        if requirement["action_id"] == "calculate":
            blocked += 1
        elif len(candidates) == 1:
            eligible += 1

    return FrozenSnapshotContractMetrics(
        total_frame_count=len(heldout),
        supported_frame_count=supported,
        unsupported_frame_count=unsupported,
        intentionally_blocked_frame_count=blocked,
        candidate_recall_count=recall,
        exact_contract_count=exact,
        false_complete_count=false_complete,
        compile_eligible_count=eligible,
    )
