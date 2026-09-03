from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.run_semantic_query_benchmark import (
    CountEvidence,
    LivePathEvidence,
    PromotionEvidence,
    SemanticQueryCounts,
    build_promotion_report,
    canonical_report_bytes,
    collect_static_evidence,
    evaluate_representative_contracts,
    parse_challenger_axis_payload,
    REPRESENTATIVE_CASE_EXPECTATIONS,
    REPRESENTATIVE_EXPECTATION_HASH,
    _parser,
    REQUEST_DEADLINE_SECONDS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHA_A = "a" * 64
SHA_B = "b" * 64


def _registry_hashes() -> dict[str, str]:
    return {
        "physical_bindings": SHA_A,
        "physical_policies": SHA_A,
        "planning": SHA_A,
        "query_contract": SHA_A,
        "query_operator": SHA_A,
        "query_policy": SHA_A,
        "semantic_catalog": SHA_B,
    }


def _source_hashes() -> dict[str, str]:
    return {
        "core": SHA_A,
        "heldout": SHA_B,
        "representative_contract_expectations": REPRESENTATIVE_EXPECTATION_HASH,
    }


def _counts() -> SemanticQueryCounts:
    return SemanticQueryCounts(
        core_questions=52,
        heldout_cases=160,
        heldout_frames=209,
        supported_frames=199,
        unsupported_frames=10,
        intentionally_blocked_frames=5,
        contract_gold_measured_frames=43,
        contract_gold_unmeasured_frames=151,
    )


def _live() -> LivePathEvidence:
    return LivePathEvidence(
        path_id="production_one_axis",
        case_count=16,
        provider_success=CountEvidence(successes=16, total=16),
        structured_validity=CountEvidence(successes=16, total=16),
        representative_contract_exact=CountEvidence(successes=5, total=5),
        repair_count=0,
        judge_count=0,
        provider_calls=16,
        successful_provider_calls=16,
        call_type_counts={"primary": 16},
        provider_error_counts={},
        semantic_error_counts={},
        input_tokens=100,
        output_tokens=40,
        p50_latency_ms=100,
        p95_latency_ms=200,
        rate_limit_count=0,
    )


def _evidence() -> PromotionEvidence:
    return PromotionEvidence(
        source_hashes=_source_hashes(),
        registry_hashes=_registry_hashes(),
        counts=_counts(),
        per_action_representability={
            action: CountEvidence(successes=count, total=count)
            for action, count in {
                "aggregate": 11,
                "calculate": 5,
                "compare": 28,
                "explain": 6,
                "lookup": 55,
                "rank": 70,
                "screen": 14,
                "similar": 10,
            }.items()
        },
        supported_representability=CountEvidence(successes=199, total=199),
        unsupported_reason_coverage=CountEvidence(successes=10, total=10),
        false_complete=CountEvidence(successes=0, total=10),
        exact_lock_precision=CountEvidence(successes=100, total=100),
        complete_contract_candidate_recall=CountEvidence(successes=43, total=43),
        decoupled_contract_exact_match=CountEvidence(successes=43, total=43),
        executable_compile_success=CountEvidence(successes=20, total=20),
        byte_equivalence=CountEvidence(successes=20, total=20),
        readiness_distribution={
            "executable": 20,
            "explorable": 2,
            "limited": 2,
            "blocked": 1,
        },
        adr_candidate_recall_at_5=CountEvidence(successes=196, total=196),
        adr_first_pass_structured_validity=CountEvidence(successes=155, total=155),
        adr_joint_frame_exact=CountEvidence(successes=140, total=155),
        adr_context_link_exact=CountEvidence(successes=148, total=155),
        ood_false_fast=CountEvidence(successes=0, total=30),
        postgres_conformance=None,
        public_fund_physical_definition=None,
        live_paths=(_live(),),
    )


def test_incomplete_contract_gold_denominator_is_unmeasured_and_defers_promotion() -> None:
    report = build_promotion_report(
        _evidence(),
        expected_source_hashes=_source_hashes(),
        expected_registry_hashes=_registry_hashes(),
    )
    gates = {gate.name: gate for gate in report.gates}

    assert gates["supported_representability"].status == "pass"
    assert gates["complete_contract_candidate_recall"].status == "unmeasured"
    assert gates["decoupled_contract_exact_match"].status == "unmeasured"
    assert gates["postgres_conformance"].status == "unmeasured"
    assert gates["public_fund_physical_definition"].status == "unmeasured"
    assert gates["representative_contract_exact"].status == "pass"
    assert report.overall_status == "deferred"
    assert "SUPPORTED_GOLD_COVERAGE_INCOMPLETE" in report.blocking_reason_codes


def test_missing_required_metric_cannot_validate_or_promote() -> None:
    payload = _evidence().model_dump(mode="json")
    del payload["false_complete"]

    with pytest.raises(ValidationError):
        PromotionEvidence.model_validate(payload)


def test_zero_denominator_is_unmeasured_not_perfect() -> None:
    evidence = _evidence().model_copy(
        update={"exact_lock_precision": CountEvidence(successes=0, total=0)}
    )

    report = build_promotion_report(
        evidence,
        expected_source_hashes=_source_hashes(),
        expected_registry_hashes=_registry_hashes(),
    )

    gate = next(item for item in report.gates if item.name == "exact_lock_precision")
    assert gate.status == "unmeasured"
    assert report.overall_status == "deferred"


def test_arbitrary_positive_subsets_cannot_pass_population_gates() -> None:
    report = build_promotion_report(
        _evidence(),
        expected_source_hashes=_source_hashes(),
        expected_registry_hashes=_registry_hashes(),
    )
    gates = {gate.name: gate for gate in report.gates}

    assert gates["exact_lock_precision"].status == "unmeasured"
    assert gates["executable_compile_success"].status == "unmeasured"
    assert gates["byte_equivalence"].status == "unmeasured"
    assert gates["exact_lock_precision"].reason_code == "EXACT_LOCK_PRECISION_AUTHORITATIVE_POPULATION_UNDEFINED"


@pytest.mark.parametrize("pin_group", ("source_hashes", "registry_hashes"))
def test_hash_changes_are_detected(pin_group: str) -> None:
    evidence = _evidence()
    expected_sources = _source_hashes()
    expected_registries = _registry_hashes()
    if pin_group == "source_hashes":
        expected_sources["heldout"] = "c" * 64
    else:
        expected_registries["query_contract"] = "c" * 64

    with pytest.raises(ValueError, match="HASH_PIN_MISMATCH"):
        build_promotion_report(
            evidence,
            expected_source_hashes=expected_sources,
            expected_registry_hashes=expected_registries,
        )


def test_representative_expectation_hash_cannot_be_self_pinned() -> None:
    payload = _evidence().model_dump(mode="json")
    payload["source_hashes"]["representative_contract_expectations"] = "c" * 64

    with pytest.raises(ValidationError, match="REPRESENTATIVE_EXPECTATION_HASH_MISMATCH"):
        PromotionEvidence.model_validate_json(json.dumps(payload))


def test_count_changes_are_rejected_fail_closed() -> None:
    evidence = _evidence().model_copy(
        update={"counts": _counts().model_copy(update={"heldout_frames": 208})}
    )

    with pytest.raises(ValueError, match="FRAME_COUNT_MISMATCH"):
        build_promotion_report(
            evidence,
            expected_source_hashes=_source_hashes(),
            expected_registry_hashes=_registry_hashes(),
        )


def test_report_serialization_is_byte_deterministic() -> None:
    kwargs = {
        "expected_source_hashes": dict(reversed(tuple(_source_hashes().items()))),
        "expected_registry_hashes": dict(reversed(tuple(_registry_hashes().items()))),
    }
    first = build_promotion_report(_evidence(), **kwargs)
    second = build_promotion_report(_evidence(), **kwargs)

    assert canonical_report_bytes(first) == canonical_report_bytes(second)
    assert hashlib.sha256(canonical_report_bytes(first)).hexdigest() == hashlib.sha256(
        canonical_report_bytes(second)
    ).hexdigest()


def test_live_path_rejects_inconsistent_provider_call_accounting() -> None:
    with pytest.raises(ValidationError):
        _live().model_copy(update={"provider_calls": 15}).__class__.model_validate(
            _live().model_copy(update={"provider_calls": 15}).model_dump(mode="json")
        )


@pytest.mark.parametrize(
    "updates",
    (
        {"structured_validity": {"successes": 15, "total": 16}, "action_exact": {"successes": 16, "total": 16}},
        {"provider_success": {"successes": 15, "total": 16}, "structured_validity": {"successes": 16, "total": 16}},
        {"provider_calls": 17, "successful_provider_calls": 16, "provider_error_counts": {}},
        {"successful_provider_calls": 15, "provider_error_counts": {"MODEL_PROVIDER_ERROR": 1}},
        {"provider_calls": 16, "successful_provider_calls": 15, "provider_error_counts": {"MODEL_RATE_LIMITED": 1}, "rate_limit_count": 0},
        {"repair_count": 1, "call_type_counts": {"primary": 16}},
        {"p50_latency_ms": 201, "p95_latency_ms": 200},
        {"semantic_error_counts": {"MODEL_SCHEMA_INVALID": 1}},
    ),
)
def test_live_path_rejects_contradictory_metrics(updates: dict[str, object]) -> None:
    payload = _live().model_dump(mode="json")
    payload.update(updates)

    with pytest.raises(ValidationError):
        LivePathEvidence.model_validate(payload)


@pytest.mark.parametrize(
    ("axis", "payload"),
    (
        ("action", '{"ids":[1]}'),
        ("action", '{"ids":["invented"]}'),
        ("family", '{"ids":["public_fund","public_fund"]}'),
        ("family", '{"ids":["public_fund","domestic_etf","overseas_etf","domestic_bond","public_fund"]}'),
        ("tag", '{"ids":"CROSS_FAMILY"}'),
        ("tag", '{"ids":["INVENTED_TAG"]}'),
        ("action", '{"ids":["rank"],"extra":true}'),
        ("action", '{"ids":["rank"],"ids":["screen"]}'),
    ),
)
def test_challenger_axis_payload_is_strict_and_bounded(axis: str, payload: str) -> None:
    with pytest.raises(ValueError, match="CHALLENGER_SCHEMA_INVALID"):
        parse_challenger_axis_payload(payload, axis)


def test_challenger_axis_payload_accepts_only_known_unique_string_ids() -> None:
    assert parse_challenger_axis_payload('{"ids":["screen"]}', "action") == (
        "screen",
    )


def _authoritative_observations() -> dict[str, object]:
    return {
        case_id: deepcopy(expectation)
        for case_id, expectation in REPRESENTATIVE_CASE_EXPECTATIONS.items()
    }


def test_representative_contract_gate_requires_all_five_authoritative_groups() -> None:
    evidence = evaluate_representative_contracts(_authoritative_observations())

    assert evidence == CountEvidence(successes=5, total=5)
    assert len(REPRESENTATIVE_EXPECTATION_HASH) == 64


def test_representative_contract_gate_rejects_unpinned_population_members() -> None:
    observations = _authoritative_observations()
    observations["not-authoritative"] = observations["fee-screen"]

    assert evaluate_representative_contracts(observations).successes == 0


@pytest.mark.parametrize(
    ("case_id", "mutation"),
    (
        ("fee-screen", lambda value: value["contracts"][0]["predicate"].update(operator_id="gt")),
        ("multi-predicate", lambda value: value["contracts"][0]["predicate"]["children"].pop()),
        ("count", lambda value: value["contracts"][0]["aggregation"].update(function_id="sum")),
        ("sum", lambda value: value["contracts"][0]["aggregation"].update(function_id="count")),
        ("grouped-aggregate", lambda value: value["contracts"][0]["aggregation"].update(group_by_field_concept_ids=[])),
        ("prior-result", lambda value: value["contracts"][1]["scope"].update(prior_result_binding=None)),
    ),
)
def test_representative_gate_rejects_wrong_or_missing_contract_roles(
    case_id: str, mutation
) -> None:
    observations = _authoritative_observations()
    mutation(observations[case_id])

    assert evaluate_representative_contracts(observations).successes == 4


def test_live_benchmark_uses_full_request_deadline_and_conservative_default_pacing() -> None:
    args = _parser().parse_args(
        ["--paced", "--sanitized-report", "/private/tmp/report.json"]
    )

    assert REQUEST_DEADLINE_SECONDS == 55.0
    assert args.request_interval_seconds == 10.0


def test_static_repository_evidence_is_pinned_and_truthfully_deferred() -> None:
    evidence = collect_static_evidence(PROJECT_ROOT)
    report = build_promotion_report(
        evidence,
        expected_source_hashes=evidence.source_hashes,
        expected_registry_hashes=evidence.registry_hashes,
    )

    assert evidence.counts == _counts()
    assert evidence.supported_representability == CountEvidence(
        successes=199, total=199
    )
    assert evidence.unsupported_reason_coverage == CountEvidence(
        successes=10, total=10
    )
    assert evidence.false_complete == CountEvidence(successes=0, total=10)
    assert evidence.complete_contract_candidate_recall == CountEvidence(
        successes=43, total=43
    )
    assert evidence.decoupled_contract_exact_match == CountEvidence(
        successes=43, total=43
    )
    assert evidence.adr_candidate_recall_at_5 == CountEvidence(
        successes=123, total=196
    )
    assert next(
        gate for gate in report.gates if gate.name == "adr_candidate_recall_at_5"
    ).status == "fail"
    assert report.overall_status == "deferred"
    assert json.loads(canonical_report_bytes(report))["schema_version"] == "1.0"
