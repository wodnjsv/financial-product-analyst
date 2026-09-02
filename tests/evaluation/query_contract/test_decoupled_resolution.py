from pathlib import Path
import json

import pytest

from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.intent.query_contract_solver import (
    QueryContractCandidateSet,
    QueryContractFrameCandidateSet,
)
from financial_agent.intent.query_contracts import (
    ContractReadiness,
    ContractReadinessRecordV2,
)
from financial_agent.intent.proposal import FrameSemanticCoverage
from financial_agent.intent.types import (
    SemanticCoverageReason,
    SemanticCoverageState,
)
from financial_agent.intent.view import (
    ResolverViewSemanticCandidate,
    ResolverViewSemanticCandidateGroup,
)
from tests.evaluation.query_contract.decoupled import (
    DecoupledContractCase,
    REQUIRED_CANDIDATE_RECALL,
    REQUIRED_COMPILE_ELIGIBILITY,
    REQUIRED_EXACT_CONTRACT,
    _candidate_matches_adjudication,
    evaluate_decoupled_contract_resolution,
    evaluate_frozen_requirement_snapshot,
)
import tests.evaluation.query_contract.decoupled as decoupled_module
from tests.planning.fixtures import resolution, view


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class _ContractPayload:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self.payload


def _frozen_requirement(case_id: str, ordinal: int = 0) -> dict[str, object]:
    payload = json.loads(
        (
            PROJECT_ROOT
            / "tests/evaluation/query_contract/query_contract_requirements.v1.json"
        ).read_text(encoding="utf-8")
    )
    return next(
        item
        for item in payload["requirements"]
        if item.get("case_id") == case_id and item.get("frame_ordinal") == ordinal
    )


def test_hko_cmp_019_missing_value_cannot_accept_invented_is_present() -> None:
    requirement = _frozen_requirement("HKO-CMP-019")
    invented = _ContractPayload(
        {
            "action_id": "screen",
            "predicate": {
                "field_concept_id": "product_risk_grade",
                "operator_id": "is_present",
                "value": None,
                "values": [],
            },
        }
    )

    assert not _candidate_matches_adjudication(invented, requirement)


def test_hko_par_021_compare_requires_both_adjudicated_fields() -> None:
    requirement = _frozen_requirement("HKO-PAR-021")
    one_field = _ContractPayload(
        {
            "action_id": "compare",
            "comparison": {
                "subject_refs": ["alpha", "beta"],
                "metric_concept_ids": ["aum"],
                "basis_policy_id": "same-definition-period-unit.v1",
            },
            "qualifiers": {"period_id": "P1Y"},
        }
    )

    assert not _candidate_matches_adjudication(one_field, requirement)


@pytest.mark.parametrize(
    ("requirement", "payload"),
    (
        (
            {
                "action_id": "screen",
                "required_components": [],
                "source_slot_values": {
                    "metric": ["fee_rate"],
                    "filter_operator": ["less_than"],
                    "filter_value": ["1"],
                },
            },
            {
                "action_id": "screen",
                "predicate": {
                    "field_concept_id": "fee_rate",
                    "operator_id": "gt",
                    "value": {"value": "2"},
                    "values": [],
                },
            },
        ),
        (
            {
                "action_id": "rank",
                "required_components": [],
                "source_slot_values": {
                    "sort_key": ["aum"],
                    "sort_direction": ["desc"],
                    "result_limit": ["5"],
                    "period": ["P1Y"],
                },
            },
            {
                "action_id": "rank",
                "ordering": [
                    {"field_concept_id": "aum", "direction": "desc"}
                ],
                "limit": 1,
                "qualifiers": {"period_id": "P6M"},
            },
        ),
    ),
)
def test_role_mismatches_never_count_as_exact(
    requirement: dict[str, object], payload: dict[str, object]
) -> None:
    assert not _candidate_matches_adjudication(
        _ContractPayload(payload), requirement
    )


def test_predicate_exactness_preserves_field_operator_typed_value_pairing_and_unit() -> None:
    requirement = {
        "action_id": "screen",
        "required_components": [],
        "semantic_overrides": {
            "predicate": {
                "atoms": [
                    {
                        "field": "fee_rate",
                        "operator": "lte",
                        "value": {"kind": "decimal", "decimal": "1", "unit": "percent"},
                    },
                    {
                        "field": "aum",
                        "operator": "gte",
                        "value": {"kind": "decimal", "decimal": "100", "unit": "krw"},
                    },
                ]
            }
        },
        "source_slot_values": {},
    }
    swapped_values = _ContractPayload(
        {
            "action_id": "screen",
            "predicate": {
                "node_type": "all_of",
                "children": [
                    {
                        "node_type": "atom",
                        "field_concept_id": "fee_rate",
                        "operator_id": "lte",
                        "value": {"kind": "decimal", "decimal": "100", "unit_id": "krw"},
                        "values": [],
                    },
                    {
                        "node_type": "atom",
                        "field_concept_id": "aum",
                        "operator_id": "gte",
                        "value": {"kind": "decimal", "decimal": "1", "unit_id": "percent"},
                        "values": [],
                    },
                ],
            },
        }
    )
    correctly_paired = _ContractPayload(
        {
            "action_id": "screen",
            "predicate": {
                "node_type": "all_of",
                "children": [
                    {
                        "node_type": "atom",
                        "field_concept_id": "fee_rate",
                        "operator_id": "lte",
                        "value": {"kind": "decimal", "decimal": "1", "unit_id": "percent"},
                        "values": [],
                    },
                    {
                        "node_type": "atom",
                        "field_concept_id": "aum",
                        "operator_id": "gte",
                        "value": {"kind": "decimal", "decimal": "100", "unit_id": "krw"},
                        "values": [],
                    },
                ],
            },
        }
    )

    assert _candidate_matches_adjudication(correctly_paired, requirement)
    assert not _candidate_matches_adjudication(swapped_values, requirement)


def test_predicate_exactness_rejects_wrong_unit_on_the_correct_atom() -> None:
    requirement = {
        "action_id": "screen",
        "required_components": [],
        "semantic_overrides": {
            "predicate": {
                "field": "fee_rate",
                "operator": "lte",
                "value": {"kind": "decimal", "decimal": "1", "unit": "percent"},
            }
        },
        "source_slot_values": {},
    }
    wrong_unit = _ContractPayload(
        {
            "action_id": "screen",
            "predicate": {
                "field_concept_id": "fee_rate",
                "operator_id": "lte",
                "value": {"kind": "decimal", "decimal": "1", "unit_id": "ratio"},
                "values": [],
            },
        }
    )

    assert not _candidate_matches_adjudication(wrong_unit, requirement)


def test_incomplete_predicate_atom_gold_has_a_stable_unmeasured_reason() -> None:
    atoms, reason = decoupled_module._gold_predicate_atom_signatures(
        {
            "action_id": "screen",
            "required_components": [],
            "semantic_overrides": {},
            "source_slot_values": {
                "metric": ["fee_rate", "aum"],
                "filter_operator": ["less_than"],
                "filter_value": ["1", "100"],
            },
        },
        catalog=None,
    )

    assert atoms == ()
    assert reason == "GOLD_PREDICATE_ATOM_ASSOCIATION_MISSING"


def test_frozen_209_frame_snapshot_reports_strict_role_aware_gates() -> None:
    metrics = evaluate_frozen_requirement_snapshot(
        PROJECT_ROOT, load_query_contract_registry(PROJECT_ROOT)
    )

    assert metrics.total_frame_count == 209
    assert metrics.supported_frame_count == 199
    assert metrics.unsupported_frame_count == 10
    assert metrics.intentionally_blocked_frame_count == 5
    assert metrics.measured_frame_count == 43
    assert metrics.evaluation_unmeasured_frame_count == 151
    assert (
        metrics.measured_frame_count
        + metrics.evaluation_unmeasured_frame_count
        + metrics.intentionally_blocked_frame_count
        == metrics.supported_frame_count
    )
    assert metrics.candidate_recall_count == 43
    assert metrics.exact_contract_count == 43
    assert metrics.compile_eligible_count == 43
    assert REQUIRED_CANDIDATE_RECALL == 0.99
    assert REQUIRED_EXACT_CONTRACT == 0.95
    assert REQUIRED_COMPILE_ELIGIBILITY == 1.0
    assert metrics.false_complete_count == 0
    assert metrics.required_supported_coverage_count == 199
    assert metrics.measured_supported_coverage_count == 48
    assert metrics.gate_status == "deferred"
    assert "SUPPORTED_GOLD_COVERAGE_INCOMPLETE" in metrics.gate_reason_codes
    assert metrics.passes_required_gates is False
    assert metrics.unsupported_proof_count == 10
    assert dict(metrics.unsupported_rejection_reason_counts) == {
        "UNRESOLVED_SEMANTIC_REQUIREMENT": 10
    }
    reasons = dict(metrics.unmeasured_reason_counts)
    assert reasons["GOLD_PREDICATE_VALUE_MISSING"] == 3
    assert reasons["GOLD_COMPARISON_SUBJECTS_MISSING"] == 28
    assert reasons["GOLD_ORDERING_DIRECTION_MISSING"] == 52
    assert reasons["GOLD_RELATION_TARGET_MISSING"] == 21


def test_frozen_snapshot_gate_propagates_a_broken_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_solver(**_kwargs):
        raise RuntimeError("solver-broken")

    monkeypatch.setattr(decoupled_module, "solve_query_contracts", broken_solver)

    with pytest.raises(RuntimeError, match="solver-broken"):
        evaluate_frozen_requirement_snapshot(
            PROJECT_ROOT, load_query_contract_registry(PROJECT_ROOT)
        )


def test_frozen_snapshot_gate_cannot_pass_with_an_empty_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def empty_solver(**kwargs):
        return QueryContractCandidateSet(
            frames=tuple(
                QueryContractFrameCandidateSet(
                    frame_id=frame.frame_id,
                    complete_candidates=(),
                    rejections=(),
                    contract_readiness=ContractReadinessRecordV2(
                        readiness=ContractReadiness.BLOCKED,
                        reason_codes=("REQUIRED_SEMANTIC_INPUT_MISSING",),
                    ),
                )
                for frame in kwargs["resolution"].canonical_frames
            )
        )

    monkeypatch.setattr(decoupled_module, "solve_query_contracts", empty_solver)

    metrics = evaluate_frozen_requirement_snapshot(
        PROJECT_ROOT, load_query_contract_registry(PROJECT_ROOT)
    )

    assert metrics.candidate_recall < 0.99
    assert metrics.compile_eligibility < 1.0


def test_zero_measured_supported_frames_never_pass_or_score_as_perfect() -> None:
    metrics = decoupled_module.FrozenSnapshotContractMetrics(
        total_frame_count=1,
        supported_frame_count=1,
        unsupported_frame_count=0,
        intentionally_blocked_frame_count=0,
        measured_frame_count=0,
        evaluation_unmeasured_frame_count=1,
        unmeasured_reason_counts=(("GOLD_INCOMPLETE", 1),),
        candidate_recall_count=0,
        exact_contract_count=0,
        false_complete_count=0,
        compile_eligible_count=0,
        unsupported_proof_count=0,
        unsupported_rejection_reason_counts=(),
    )

    assert metrics.candidate_recall == 0.0
    assert metrics.exact_contract == 0.0
    assert metrics.compile_eligibility == 0.0
    assert metrics.passes_required_gates is False


@pytest.mark.parametrize(
    "case_id", ("HKO-OOD-VOC-006", "HKO-OOD-VOC-008", "HKO-OOD-VOC-010")
)
def test_unsupported_vocabulary_probes_exercise_resolved_axes_and_fail_closed(
    case_id: str,
) -> None:
    requirement = _frozen_requirement(case_id)
    payload = json.loads(
        (
            PROJECT_ROOT
            / "tests/evaluation/intent/intent_resolution_heldout_ko_v3.json"
        ).read_text(encoding="utf-8")
    )
    source_frame = next(
        case for case in payload["cases"] if case["case_id"] == case_id
    )["expected_frames"][0]
    injected, resolver_view, exact_locks = decoupled_module._adjudicated_solver_input(
        requirement,
        source_frame,
        decoupled_module.load_catalog(PROJECT_ROOT),
    )

    assert injected.canonical_frames[0].frame_status.value == "resolved"
    assert injected.canonical_frames[0].action_choice.selected_ids
    assert injected.canonical_frames[0].product_family_choice.selected_ids
    assert injected.canonical_frames[0].semantic_coverage == (
        FrameSemanticCoverage(
            state=SemanticCoverageState.PARTIAL,
            reason=SemanticCoverageReason.LEXICAL_OOD,
            evidence_ids=(f"unsupported-requirement-{case_id}",),
        ),
    )
    solved = decoupled_module.solve_query_contracts(
        resolution=injected,
        view=resolver_view,
        exact_locks=exact_locks,
        registry=load_query_contract_registry(PROJECT_ROOT),
    )

    assert solved.frames[0].complete_candidates == ()
    assert {item.reason_code for item in solved.frames[0].rejections} == {
        "UNRESOLVED_SEMANTIC_REQUIREMENT"
    }


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
