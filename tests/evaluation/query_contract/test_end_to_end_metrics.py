from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType

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
    representative_population_integrity,
    parse_challenger_axis_payload,
    REPRESENTATIVE_CASE_EXPECTATIONS,
    REPRESENTATIVE_EXPECTATION_HASH,
    SUPPORTED_ACTION_POPULATION_HASH,
    UNSUPPORTED_ACTION_POPULATION_HASH,
    _parser,
    REQUEST_DEADLINE_SECONDS,
)
import scripts.run_semantic_query_benchmark as benchmark_module


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
        "supported_action_population": SUPPORTED_ACTION_POPULATION_HASH,
        "unsupported_action_population": UNSUPPORTED_ACTION_POPULATION_HASH,
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
        representative_population_integrity=True,
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
        per_action_unsupported={
            "aggregate": 0,
            "calculate": 0,
            "compare": 2,
            "explain": 0,
            "lookup": 3,
            "rank": 2,
            "screen": 3,
            "similar": 0,
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


@pytest.mark.parametrize("population", ("supported", "unsupported"))
def test_per_action_population_buckets_cannot_shift_with_same_total(
    population: str,
) -> None:
    payload = _evidence().model_dump(mode="json")
    if population == "supported":
        payload["per_action_representability"]["lookup"] = {
            "successes": 54,
            "total": 54,
        }
        payload["per_action_representability"]["screen"] = {
            "successes": 15,
            "total": 15,
        }
        reason = "SUPPORTED_ACTION_POPULATION_MISMATCH"
    else:
        payload["per_action_unsupported"]["compare"] = 1
        payload["per_action_unsupported"]["lookup"] = 4
        reason = "UNSUPPORTED_ACTION_POPULATION_MISMATCH"

    with pytest.raises(ValidationError, match=reason):
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


def test_challenger_complete_bundles_require_three_successful_calls_each() -> None:
    payload = {
        **_live().model_dump(mode="json"),
        "path_id": "parallel_three_axis_challenger",
        "provider_success": {"successes": 16, "total": 16},
        "structured_validity": {"successes": 16, "total": 16},
        "representative_contract_exact": None,
        "representative_population_integrity": None,
        "provider_calls": 48,
        "successful_provider_calls": 47,
        "call_type_counts": {
            "challenger_action": 16,
            "challenger_family": 16,
            "challenger_tag": 16,
        },
        "provider_error_counts": {"MODEL_PROVIDER_ERROR": 1},
    }

    with pytest.raises(ValidationError, match="LIVE_CHALLENGER_BUNDLE_ACCOUNTING_MISMATCH"):
        LivePathEvidence.model_validate(payload)


def test_production_cannot_attempt_more_than_one_repair_or_judge_per_case() -> None:
    payload = _live().model_dump(mode="json")
    payload.update(
        repair_count=9,
        judge_count=8,
        provider_calls=33,
        successful_provider_calls=33,
        call_type_counts={"primary": 16, "repair": 9, "judge": 8},
    )

    with pytest.raises(ValidationError, match="LIVE_PRODUCTION_RECOVERY_COUNT_INVALID"):
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


def test_representative_contract_population_is_exactly_the_accepted_five() -> None:
    assert set(REPRESENTATIVE_CASE_EXPECTATIONS) == {
        "fee-screen",
        "public-aum-sum",
        "overseas-aum-rank",
        "domestic-return-rank",
        "bond-risk-screen",
    }


def test_representative_contract_gate_rejects_unpinned_population_members() -> None:
    observations = _authoritative_observations()
    observations["not-authoritative"] = observations["fee-screen"]

    assert evaluate_representative_contracts(observations).successes == 5
    assert representative_population_integrity(observations) is False


def test_representative_cases_score_independently_when_one_is_missing() -> None:
    observations = _authoritative_observations()
    observations.pop("bond-risk-screen")

    metric = evaluate_representative_contracts(observations)

    assert metric.successes == 4
    assert metric.total == 5
    assert representative_population_integrity(observations) is False


def test_representative_population_integrity_is_a_separate_strict_gate() -> None:
    live = _live().model_copy(update={"representative_population_integrity": False})
    report = build_promotion_report(
        _evidence().model_copy(update={"live_paths": (live,)}),
        expected_source_hashes=_source_hashes(),
        expected_registry_hashes=_registry_hashes(),
    )
    gates = {gate.name: gate for gate in report.gates}

    assert gates["representative_contract_exact"].status == "pass"
    assert gates["representative_population_integrity"].status == "fail"


@pytest.mark.parametrize(
    ("case_id", "mutation"),
    (
        ("fee-screen", lambda value: value["contracts"][0]["predicate"].update(operator_id="gt")),
        ("public-aum-sum", lambda value: value["contracts"][0]["aggregation"].update(dedup_policy_id="no-dedup.v1")),
        ("overseas-aum-rank", lambda value: value["contracts"][0]["ordering"][0].update(field_concept_id="fee_rate")),
        ("domestic-return-rank", lambda value: value["contracts"][0]["qualifiers"].update(period_id=None)),
        ("bond-risk-screen", lambda value: value["contracts"][0]["predicate"].update(field_concept_id="product_risk_grade")),
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


def test_offline_mode_forbids_live_calls_and_can_include_separate_hybrid_v3_path() -> None:
    args = _parser().parse_args(
        [
            "--offline",
            "--include-hybrid-v3",
            "--sanitized-report",
            "/private/tmp/report.json",
        ]
    )

    assert args.offline is True
    assert args.include_hybrid_v3 is True


def test_offline_hybrid_report_never_calls_provider_even_with_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = Path("/private/tmp/pytest-semantic-offline-hybrid.json")
    output.unlink(missing_ok=True)

    async def forbidden_provider_call(**_kwargs):
        raise AssertionError("offline mode called the provider")

    monkeypatch.setattr(benchmark_module, "_load_api_key", lambda: "credential-present")
    monkeypatch.setattr(benchmark_module, "run_live_benchmark", forbidden_provider_call)
    args = _parser().parse_args(
        [
            "--offline",
            "--include-hybrid-v3",
            "--sanitized-report",
            str(output),
        ]
    )

    assert asyncio.run(benchmark_module._main_async(args)) == 0
    payload = json.loads(output.read_bytes())
    paths = {item["path_id"]: item for item in payload["resolver_paths"]}
    assert set(paths) == {"deterministic-v2", "hybrid-deterministic-v3"}
    assert paths["deterministic-v2"]["hint_recall_at_5"] == {
        "successes": 123,
        "total": 196,
    }
    assert paths["hybrid-deterministic-v3"]["compact_catalog_selectability"][
        "numerator"
    ] == 196
    assert payload["live_execution"]["reason_code"] == (
        "LIVE_EXECUTION_DISABLED_OFFLINE"
    )
    output.unlink()


class _SyntheticHybridRecordingAdapter:
    def __init__(self, *, invalid_primary: bool = False) -> None:
        self.records: list[object] = []
        self.invalid_primary = invalid_primary

    async def invoke(self, envelope: object, timeout_seconds: float):
        call_type = benchmark_module._call_type(envelope)
        if call_type == "primary" and self.invalid_primary:
            content = "{}"
            self.invalid_primary = False
        elif call_type == "judge":
            candidate_ids = envelope.response_schema["properties"]["candidate_id"][
                "enum"
            ]
            content = json.dumps({"candidate_id": candidate_ids[0]})
        else:
            payload = json.loads(envelope.user_message)
            view = payload["view"]
            question = payload["context"]["question"]
            is_link_fixture = "비용 부담" in question
            mention_text = "비용 부담" if is_link_fixture else "총보수"
            mention_id = next(
                item["mention_id"]
                for item in view["mention_spans"]["items"]
                if item["text"] == mention_text
            )
            segment_id = payload["context"]["segments"][0]["segment_id"]
            content = json.dumps(
                {
                    "proposal_schema_version": "3.0",
                    "frames": [
                        {
                            "segment_ids": [segment_id],
                            "action_choice": {
                                "state": "selected",
                                "selected_ids": [
                                    "rank" if is_link_fixture else "screen"
                                ],
                                "evidence_ids": [],
                                "reason_code": "explicit",
                            },
                            "product_family_choice": {
                                "state": "selected",
                                "selected_ids": (
                                    ["domestic_etf", "overseas_etf"]
                                    if is_link_fixture
                                    else ["public_fund"]
                                ),
                                "evidence_ids": [],
                                "reason_code": "explicit",
                            },
                            "entity_type_ids": ["FinancialProduct"],
                            "semantic_links": [
                                {
                                    "mention_id": mention_id,
                                    "state": "selected",
                                    "semantic_ids": ["fee_rate"],
                                    "reason_code": "implicit",
                                }
                            ],
                            "unmapped_mention_ids": [],
                            "semantic_coverage": {
                                "state": "covered",
                                "reason": "none",
                            },
                            "entity_hints": [],
                            "produced_result_hints": ["candidates"],
                        }
                    ],
                    "references": [],
                    "context_links": [],
                    "slot_mutations": [],
                    "semantic_flag_hints": [],
                    "frame_limit_exceeded": False,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        self.records.append(
            benchmark_module._ProviderCallRecord(
                call_id=len(self.records) + 1,
                call_type=call_type,
                success=True,
                elapsed_ms=10,
                prompt_tokens=11,
                completion_tokens=7,
                error_code=None,
            )
        )
        return benchmark_module.ModelInvocationResult(
            content=content,
            usage=MappingProxyType(
                {"promptTokens": 11, "completionTokens": 7, "totalTokens": 18}
            ),
        )


@pytest.mark.asyncio
async def test_opt_in_live_hybrid_path_executes_v3_and_emits_runtime_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = Path("/private/tmp/pytest-semantic-live-hybrid.json")
    output.unlink(missing_ok=True)
    hybrid_case = benchmark_module._load_hybrid_semantic_link_cases()[0]
    monkeypatch.setattr(benchmark_module, "_LIVE_CASES", ())
    adapter = _SyntheticHybridRecordingAdapter()
    service = benchmark_module._build_hybrid_live_service(adapter)
    prepared = await service.prepare_hybrid(
        benchmark_module._request_context(hybrid_case)
    )
    assert prepared.view.build_manifest.resolver_schema_version == "3.0"

    hybrid_path = await benchmark_module._run_hybrid_path(
        service,
        adapter,
        paced=False,
        interval=0,
        hybrid_cases=(hybrid_case,),
    )

    assert hybrid_path.path_id == "hybrid_shadow_v3"
    assert hybrid_path.metrics.provider.provider_calls == 1
    assert hybrid_path.metrics.first_pass_structured_validity.numerator == 1
    assert hybrid_path.metrics.action_exact_match.numerator == 1
    assert hybrid_path.metrics.semantic_link_exact_match.numerator == 1
    assert hybrid_path.metrics.compact_catalog_selectability.status == "unmeasured"
    assert hybrid_path.provider_error_counts == {}
    invalid_provider = hybrid_path.metrics.provider.model_copy(
        update={"successful_provider_calls": 0}
    )
    invalid_metrics = hybrid_path.metrics.model_copy(
        update={"provider": invalid_provider}
    )
    with pytest.raises(
        ValidationError, match="HYBRID_PROVIDER_OUTCOME_ACCOUNTING_MISMATCH"
    ):
        benchmark_module.HybridRuntimePathEvidence(
            case_count=hybrid_path.case_count,
            metrics=invalid_metrics,
            call_type_counts=hybrid_path.call_type_counts,
            provider_error_counts=hybrid_path.provider_error_counts,
        )

    async def one_hybrid_path(**kwargs):
        assert kwargs["include_hybrid_v3"] is True
        return (hybrid_path,)

    monkeypatch.setattr(benchmark_module, "_load_api_key", lambda: "test-only")
    monkeypatch.setattr(benchmark_module, "run_live_benchmark", one_hybrid_path)
    args = _parser().parse_args(
        ["--include-hybrid-v3", "--sanitized-report", str(output)]
    )

    assert await benchmark_module._main_async(args) == 0
    payload = json.loads(output.read_bytes())
    paths = {item["path_id"]: item for item in payload["resolver_paths"]}
    assert "hybrid_shadow_v3" in paths
    assert paths["hybrid_shadow_v3"]["metrics"][
        "first_pass_structured_validity"
    ]["numerator"] == 1
    output.unlink()


@pytest.mark.asyncio
async def test_hybrid_runtime_keeps_repair_and_judge_accounting_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hybrid_case = benchmark_module._load_hybrid_semantic_link_cases()[0]
    monkeypatch.setattr(benchmark_module, "_LIVE_CASES", ())
    adapter = _SyntheticHybridRecordingAdapter(invalid_primary=True)
    service = benchmark_module._build_hybrid_live_service(adapter)

    path = await benchmark_module._run_hybrid_path(
        service,
        adapter,
        paced=False,
        interval=0,
        hybrid_cases=(hybrid_case,),
    )

    assert path.call_type_counts == {"primary": 1, "repair": 1}
    assert path.metrics.first_pass_structured_validity.numerator == 0
    assert path.metrics.repaired_structured_validity.numerator == 1
    assert path.metrics.repaired_structured_validity.denominator == 1
    assert path.metrics.provider.repair_calls == 1
    assert path.metrics.provider.candidate_judge_calls == 0


def test_default_benchmark_payload_is_byte_identical_without_hybrid_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = Path("/private/tmp/pytest-semantic-default-v2.json")
    output.unlink(missing_ok=True)
    monkeypatch.setattr(benchmark_module, "_load_api_key", lambda: None)
    evidence = collect_static_evidence(PROJECT_ROOT)
    report = build_promotion_report(
        evidence,
        expected_source_hashes=evidence.source_hashes,
        expected_registry_hashes=evidence.registry_hashes,
    )
    expected = report.model_dump(mode="json")
    expected["live_execution"] = {
        "status": "unmeasured",
        "reason_code": "LIVE_EXECUTION_DISABLED_OFFLINE",
        "raw_output_path": None,
    }
    expected["report_hash"] = hashlib.sha256(
        benchmark_module.canonical_json_bytes(expected)
    ).hexdigest()

    args = _parser().parse_args(
        ["--offline", "--sanitized-report", str(output)]
    )
    assert asyncio.run(benchmark_module._main_async(args)) == 0

    assert output.read_bytes() == (
        benchmark_module.canonical_json_bytes(expected) + b"\n"
    )
    assert "resolver_paths" not in json.loads(output.read_bytes())
    output.unlink()


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
