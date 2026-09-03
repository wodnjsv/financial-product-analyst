#!/usr/bin/env python3
"""Build a fail-closed semantic-query promotion report and run paced HCX probes."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Literal, Mapping
import uuid

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from financial_agent.contracts.canonical import build_request_key, canonical_json_bytes
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.clova import ClovaStructuredOutputAdapter, ModelInvocationResult
from financial_agent.intent.config import ClovaResolverConfig
from financial_agent.intent.errors import ModelInvocationError, ResolverContractError
from financial_agent.intent.query_contract_registry import (
    assess_requirement_representability,
    load_query_contract_registry,
)
from financial_agent.intent.query_contract_judge import QueryContractJudgePromptEnvelope
from financial_agent.intent.service import IntentResolverService
from financial_agent.intent.types import SemanticTag
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ActiveDatasetPin,
    build_manifest,
)
from financial_agent.planning.physical_bindings import (
    load_physical_binding_registry,
    load_semantic_sql_policy_registry,
)
from financial_agent.planning.registry import load_planning_registry
from tests.evaluation.query_contract.coverage import (
    ACTION_IDS,
    load_requirement_snapshot,
)
from tests.evaluation.query_contract.decoupled import evaluate_frozen_requirement_snapshot


LIVE_BASE_URL = "https://clovastudio.stream.ntruss.com"
LIVE_DATASET_VERSION = "synthetic-semantic-query-benchmark-v1"
LIVE_CASE_COUNT = 16
REQUEST_DEADLINE_SECONDS = 55.0
SUPPORTED_ACTION_POPULATION: Mapping[str, int] = {
    "aggregate": 11,
    "calculate": 5,
    "compare": 28,
    "explain": 6,
    "lookup": 55,
    "rank": 70,
    "screen": 14,
    "similar": 10,
}
UNSUPPORTED_ACTION_POPULATION: Mapping[str, int] = {
    "aggregate": 0,
    "calculate": 0,
    "compare": 2,
    "explain": 0,
    "lookup": 3,
    "rank": 2,
    "screen": 3,
    "similar": 0,
}
SUPPORTED_ACTION_POPULATION_HASH = hashlib.sha256(
    canonical_json_bytes(SUPPORTED_ACTION_POPULATION)
).hexdigest()
UNSUPPORTED_ACTION_POPULATION_HASH = hashlib.sha256(
    canonical_json_bytes(UNSUPPORTED_ACTION_POPULATION)
).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CountEvidence(StrictModel):
    successes: int = Field(ge=0)
    total: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_count(self) -> "CountEvidence":
        if self.successes > self.total:
            raise ValueError("success count exceeds total")
        return self

    @property
    def ratio(self) -> Decimal | None:
        if self.total == 0:
            return None
        return Decimal(self.successes) / Decimal(self.total)


class SemanticQueryCounts(StrictModel):
    core_questions: int = Field(ge=0)
    heldout_cases: int = Field(ge=0)
    heldout_frames: int = Field(ge=0)
    supported_frames: int = Field(ge=0)
    unsupported_frames: int = Field(ge=0)
    intentionally_blocked_frames: int = Field(ge=0)
    contract_gold_measured_frames: int = Field(ge=0)
    contract_gold_unmeasured_frames: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_partition(self) -> "SemanticQueryCounts":
        if self.supported_frames + self.unsupported_frames != self.heldout_frames:
            raise ValueError("FRAME_COUNT_MISMATCH")
        if (
            self.contract_gold_measured_frames
            + self.contract_gold_unmeasured_frames
            + self.intentionally_blocked_frames
            != self.supported_frames
        ):
            raise ValueError("SUPPORTED_FRAME_PARTITION_MISMATCH")
        return self


class LivePathEvidence(StrictModel):
    path_id: Literal["production_one_axis", "parallel_three_axis_challenger"]
    case_count: int = Field(ge=1)
    provider_success: CountEvidence
    structured_validity: CountEvidence
    action_exact: CountEvidence | None = None
    family_exact: CountEvidence | None = None
    tag_exact: CountEvidence | None = None
    complete_contract: CountEvidence | None = None
    representative_contract_exact: CountEvidence | None = None
    repair_count: int = Field(ge=0)
    judge_count: int = Field(ge=0)
    provider_calls: int = Field(ge=0)
    successful_provider_calls: int = Field(ge=0)
    call_type_counts: Mapping[str, int]
    provider_error_counts: Mapping[str, int]
    semantic_error_counts: Mapping[str, int]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    p50_latency_ms: int | None = Field(default=None, ge=0)
    p95_latency_ms: int | None = Field(default=None, ge=0)
    rate_limit_count: int = Field(ge=0)
    @model_validator(mode="after")
    def validate_accounting(self) -> "LivePathEvidence":
        if self.provider_success.total != self.case_count:
            raise ValueError("LIVE_PROVIDER_DENOMINATOR_MISMATCH")
        if self.structured_validity.total != self.case_count:
            raise ValueError("LIVE_SCHEMA_DENOMINATOR_MISMATCH")
        for metric in (
            self.action_exact,
            self.family_exact,
            self.tag_exact,
            self.complete_contract,
        ):
            if metric is not None and metric.total != self.case_count:
                raise ValueError("LIVE_METRIC_DENOMINATOR_MISMATCH")
        semantic_metrics = tuple(
            metric
            for metric in (
                self.action_exact,
                self.family_exact,
                self.tag_exact,
                self.complete_contract,
            )
            if metric is not None
        )
        if any(
            metric.successes > self.structured_validity.successes
            for metric in semantic_metrics
        ):
            raise ValueError("LIVE_SEMANTIC_COUNTER_EXCEEDS_STRUCTURED")
        if self.structured_validity.successes > self.provider_success.successes:
            raise ValueError("LIVE_STRUCTURED_EXCEEDS_PROVIDER")
        if self.provider_success.successes > self.successful_provider_calls:
            raise ValueError("LIVE_PROVIDER_CASE_SUCCESS_EXCEEDS_CALL_SUCCESS")
        if self.representative_contract_exact is not None and (
            self.path_id != "production_one_axis"
            or self.representative_contract_exact.total != 5
            or self.representative_contract_exact.successes
            > self.structured_validity.successes
        ):
            raise ValueError("LIVE_REPRESENTATIVE_METRIC_INVALID")
        if any(value < 0 for value in self.call_type_counts.values()):
            raise ValueError("LIVE_CALL_TYPE_COUNT_INVALID")
        if any(value < 1 for value in self.provider_error_counts.values()):
            raise ValueError("LIVE_PROVIDER_ERROR_COUNT_INVALID")
        if any(value < 1 for value in self.semantic_error_counts.values()):
            raise ValueError("LIVE_SEMANTIC_ERROR_COUNT_INVALID")
        if sum(self.call_type_counts.values()) != self.provider_calls:
            raise ValueError("LIVE_PROVIDER_CALL_ACCOUNTING_MISMATCH")
        if self.successful_provider_calls + sum(self.provider_error_counts.values()) != self.provider_calls:
            raise ValueError("LIVE_PROVIDER_OUTCOME_ACCOUNTING_MISMATCH")
        if self.rate_limit_count != self.provider_error_counts.get("MODEL_RATE_LIMITED", 0):
            raise ValueError("LIVE_RATE_LIMIT_ACCOUNTING_MISMATCH")
        if sum(self.semantic_error_counts.values()) != self.case_count - self.structured_validity.successes:
            raise ValueError("LIVE_SEMANTIC_OUTCOME_ACCOUNTING_MISMATCH")
        if self.path_id == "production_one_axis":
            if self.call_type_counts.get("primary", 0) != self.case_count:
                raise ValueError("LIVE_PRIMARY_CALL_COUNT_MISMATCH")
            if self.call_type_counts.get("repair", 0) != self.repair_count:
                raise ValueError("LIVE_REPAIR_CALL_COUNT_MISMATCH")
            if self.call_type_counts.get("judge", 0) != self.judge_count:
                raise ValueError("LIVE_JUDGE_CALL_COUNT_MISMATCH")
            if set(self.call_type_counts) - {"primary", "repair", "judge"}:
                raise ValueError("LIVE_CALL_TYPE_INVALID")
            if self.repair_count + self.judge_count > self.case_count:
                raise ValueError("LIVE_PRODUCTION_RECOVERY_COUNT_INVALID")
        else:
            expected = {"challenger_action", "challenger_family", "challenger_tag"}
            if set(self.call_type_counts) != expected or any(
                self.call_type_counts[item] != self.case_count for item in expected
            ):
                raise ValueError("LIVE_CHALLENGER_CALL_COUNT_MISMATCH")
            if self.repair_count or self.judge_count:
                raise ValueError("LIVE_CHALLENGER_EXTRA_CALL_INVALID")
            complete_bundles = self.provider_success.successes
            failed_calls = self.provider_calls - self.successful_provider_calls
            incomplete_bundles = self.case_count - complete_bundles
            if (
                complete_bundles * 3 > self.successful_provider_calls
                or incomplete_bundles > failed_calls
            ):
                raise ValueError("LIVE_CHALLENGER_BUNDLE_ACCOUNTING_MISMATCH")
        if self.provider_calls and (
            self.p50_latency_ms is None
            or self.p95_latency_ms is None
            or self.p50_latency_ms > self.p95_latency_ms
        ):
            raise ValueError("LIVE_LATENCY_ACCOUNTING_INVALID")
        return self


class PromotionEvidence(StrictModel):
    source_hashes: Mapping[str, str]
    registry_hashes: Mapping[str, str]
    counts: SemanticQueryCounts
    per_action_representability: Mapping[str, CountEvidence]
    per_action_unsupported: Mapping[str, int]
    supported_representability: CountEvidence
    unsupported_reason_coverage: CountEvidence
    false_complete: CountEvidence
    exact_lock_precision: CountEvidence | None
    complete_contract_candidate_recall: CountEvidence | None
    decoupled_contract_exact_match: CountEvidence | None
    executable_compile_success: CountEvidence | None
    byte_equivalence: CountEvidence | None
    readiness_distribution: Mapping[str, int]
    adr_candidate_recall_at_5: CountEvidence | None
    adr_first_pass_structured_validity: CountEvidence | None
    adr_joint_frame_exact: CountEvidence | None
    adr_context_link_exact: CountEvidence | None
    ood_false_fast: CountEvidence | None
    postgres_conformance: CountEvidence | None
    public_fund_physical_definition: CountEvidence | None
    live_paths: tuple[LivePathEvidence, ...]

    @model_validator(mode="after")
    def validate_shape(self) -> "PromotionEvidence":
        if set(self.source_hashes) != {
            "core",
            "heldout",
            "representative_contract_expectations",
            "supported_action_population",
            "unsupported_action_population",
        }:
            raise ValueError("SOURCE_HASH_SET_INVALID")
        if set(self.registry_hashes) != {
            "physical_bindings",
            "physical_policies",
            "planning",
            "query_contract",
            "query_operator",
            "query_policy",
            "semantic_catalog",
        }:
            raise ValueError("REGISTRY_HASH_SET_INVALID")
        if set(self.per_action_representability) != set(ACTION_IDS):
            raise ValueError("PER_ACTION_COVERAGE_INCOMPLETE")
        if {
            action: evidence.total
            for action, evidence in self.per_action_representability.items()
        } != dict(SUPPORTED_ACTION_POPULATION):
            raise ValueError("SUPPORTED_ACTION_POPULATION_MISMATCH")
        if dict(self.per_action_unsupported) != dict(UNSUPPORTED_ACTION_POPULATION):
            raise ValueError("UNSUPPORTED_ACTION_POPULATION_MISMATCH")
        if sum(item.total for item in self.per_action_representability.values()) != self.counts.supported_frames:
            raise ValueError("PER_ACTION_DENOMINATOR_MISMATCH")
        if sum(item.successes for item in self.per_action_representability.values()) != self.supported_representability.successes:
            raise ValueError("PER_ACTION_NUMERATOR_MISMATCH")
        if self.supported_representability.total != self.counts.supported_frames:
            raise ValueError("SUPPORTED_DENOMINATOR_MISMATCH")
        if self.unsupported_reason_coverage.total != self.counts.unsupported_frames:
            raise ValueError("UNSUPPORTED_DENOMINATOR_MISMATCH")
        if self.false_complete.total != self.counts.unsupported_frames:
            raise ValueError("FALSE_COMPLETE_DENOMINATOR_MISMATCH")
        if any(not _is_sha256(value) for value in self.source_hashes.values()):
            raise ValueError("SOURCE_HASH_INVALID")
        if (
            self.source_hashes["representative_contract_expectations"]
            != REPRESENTATIVE_EXPECTATION_HASH
        ):
            raise ValueError("REPRESENTATIVE_EXPECTATION_HASH_MISMATCH")
        if (
            self.source_hashes["supported_action_population"]
            != SUPPORTED_ACTION_POPULATION_HASH
            or self.source_hashes["unsupported_action_population"]
            != UNSUPPORTED_ACTION_POPULATION_HASH
        ):
            raise ValueError("ACTION_POPULATION_HASH_MISMATCH")
        if any(not _is_sha256(value) for value in self.registry_hashes.values()):
            raise ValueError("REGISTRY_HASH_INVALID")
        if set(self.readiness_distribution) - {
            "executable",
            "explorable",
            "limited",
            "blocked",
        }:
            raise ValueError("READINESS_STATUS_INVALID")
        if any(value < 0 for value in self.readiness_distribution.values()):
            raise ValueError("READINESS_COUNT_INVALID")
        path_ids = tuple(path.path_id for path in self.live_paths)
        if len(path_ids) != len(set(path_ids)):
            raise ValueError("LIVE_PATH_DUPLICATE")
        return self


GateStatus = Literal["pass", "fail", "unmeasured"]


class PromotionGate(StrictModel):
    name: str = Field(min_length=1)
    status: GateStatus
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    comparison: Literal["equal", "at_least", "at_most"]
    threshold: Decimal
    reason_code: str | None = None


class SemanticQueryPromotionReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    source_hashes: Mapping[str, str]
    registry_hashes: Mapping[str, str]
    counts: SemanticQueryCounts
    per_action_representability: Mapping[str, CountEvidence]
    per_action_unsupported: Mapping[str, int]
    readiness_distribution: Mapping[str, int]
    live_paths: tuple[LivePathEvidence, ...]
    gates: tuple[PromotionGate, ...]
    blocking_reason_codes: tuple[str, ...]
    overall_status: Literal["promoted", "deferred"]
    residual_limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _GateDefinition:
    name: str
    attribute: str
    comparison: Literal["equal", "at_least", "at_most"]
    threshold: Decimal
    denominator: int | Literal["contract_gold", "positive", "undefined"]


_GATES = (
    _GateDefinition("supported_representability", "supported_representability", "equal", Decimal("1"), 199),
    _GateDefinition("unsupported_reason_coverage", "unsupported_reason_coverage", "equal", Decimal("1"), 10),
    _GateDefinition("false_complete", "false_complete", "equal", Decimal("0"), 10),
    _GateDefinition("exact_lock_precision", "exact_lock_precision", "equal", Decimal("1"), "undefined"),
    _GateDefinition("complete_contract_candidate_recall", "complete_contract_candidate_recall", "at_least", Decimal("0.99"), "contract_gold"),
    _GateDefinition("decoupled_contract_exact_match", "decoupled_contract_exact_match", "at_least", Decimal("0.95"), "contract_gold"),
    _GateDefinition("executable_compile_success", "executable_compile_success", "equal", Decimal("1"), "undefined"),
    _GateDefinition("byte_equivalence", "byte_equivalence", "equal", Decimal("1"), "undefined"),
    _GateDefinition("adr_candidate_recall_at_5", "adr_candidate_recall_at_5", "at_least", Decimal("0.99"), 196),
    _GateDefinition("adr_first_pass_structured_validity", "adr_first_pass_structured_validity", "at_least", Decimal("0.99"), 155),
    _GateDefinition("adr_joint_frame_exact", "adr_joint_frame_exact", "at_least", Decimal("0.90"), 155),
    _GateDefinition("adr_context_link_exact", "adr_context_link_exact", "at_least", Decimal("0.95"), 155),
    _GateDefinition("ood_false_fast", "ood_false_fast", "at_most", Decimal("0.02"), 30),
    _GateDefinition("postgres_conformance", "postgres_conformance", "equal", Decimal("1"), "positive"),
    _GateDefinition("public_fund_physical_definition", "public_fund_physical_definition", "equal", Decimal("1"), "positive"),
)


def build_promotion_report(
    evidence: PromotionEvidence,
    *,
    expected_source_hashes: Mapping[str, str],
    expected_registry_hashes: Mapping[str, str],
) -> SemanticQueryPromotionReport:
    """Revalidate all evidence and derive immutable fail-closed gate decisions."""

    evidence = PromotionEvidence.model_validate_json(evidence.model_dump_json())
    if dict(evidence.source_hashes) != dict(expected_source_hashes):
        raise ValueError("HASH_PIN_MISMATCH:SOURCE")
    if dict(evidence.registry_hashes) != dict(expected_registry_hashes):
        raise ValueError("HASH_PIN_MISMATCH:REGISTRY")
    if (
        evidence.counts.core_questions,
        evidence.counts.heldout_cases,
        evidence.counts.heldout_frames,
        evidence.counts.supported_frames,
        evidence.counts.unsupported_frames,
    ) != (52, 160, 209, 199, 10):
        raise ValueError("FRAME_COUNT_MISMATCH")

    gates: list[PromotionGate] = []
    reasons: list[str] = []
    for definition in _GATES:
        metric = getattr(evidence, definition.attribute)
        expected_denominator = _expected_denominator(definition, evidence.counts)
        gate = _assess_gate(definition, metric, expected_denominator)
        gates.append(gate)
        if gate.status != "pass" and gate.reason_code is not None:
            reasons.append(gate.reason_code)

    production = next(
        (item for item in evidence.live_paths if item.path_id == "production_one_axis"),
        None,
    )
    live_metric = None if production is None else production.provider_success
    live_definition = _GateDefinition(
        "live_production_provider_success",
        "live_paths",
        "equal",
        Decimal("1"),
        LIVE_CASE_COUNT,
    )
    live_gate = _assess_gate(live_definition, live_metric, LIVE_CASE_COUNT)
    gates.append(live_gate)
    if live_gate.status != "pass" and live_gate.reason_code is not None:
        reasons.append(live_gate.reason_code)

    representative_metric = (
        None if production is None else production.representative_contract_exact
    )
    representative_definition = _GateDefinition(
        "representative_contract_exact",
        "live_paths",
        "equal",
        Decimal("1"),
        5,
    )
    representative_gate = _assess_gate(
        representative_definition, representative_metric, 5
    )
    gates.append(representative_gate)
    if representative_gate.status != "pass" and representative_gate.reason_code:
        reasons.append(representative_gate.reason_code)

    if evidence.counts.contract_gold_unmeasured_frames:
        reasons.append("SUPPORTED_GOLD_COVERAGE_INCOMPLETE")
    reasons = sorted(set(reasons))
    promoted = all(gate.status == "pass" for gate in gates) and not reasons
    return SemanticQueryPromotionReport(
        source_hashes=dict(sorted(evidence.source_hashes.items())),
        registry_hashes=dict(sorted(evidence.registry_hashes.items())),
        counts=evidence.counts,
        per_action_representability=dict(
            sorted(evidence.per_action_representability.items())
        ),
        per_action_unsupported=dict(sorted(evidence.per_action_unsupported.items())),
        readiness_distribution=dict(sorted(evidence.readiness_distribution.items())),
        live_paths=tuple(sorted(evidence.live_paths, key=lambda item: item.path_id)),
        gates=tuple(gates),
        blocking_reason_codes=tuple(reasons),
        overall_status="promoted" if promoted else "deferred",
        residual_limitations=(
            "PUBLIC_FUND_FEE_RATE_PHYSICAL_DEFINITION_UNVERIFIED",
            "PUBLIC_FUND_REPRESENTATIVE_GRAIN_UNVERIFIED",
            "NON_SQL_PRODUCTION_EXECUTORS_OUT_OF_SCOPE",
        ),
    )


def _expected_denominator(
    definition: _GateDefinition, counts: SemanticQueryCounts
) -> int | Literal["positive", "undefined"]:
    if definition.denominator == "contract_gold":
        return counts.supported_frames - counts.intentionally_blocked_frames
    return definition.denominator


def _assess_gate(
    definition: _GateDefinition,
    metric: CountEvidence | None,
    expected_denominator: int | Literal["positive", "undefined"],
) -> PromotionGate:
    if expected_denominator == "undefined":
        return PromotionGate(
            name=definition.name,
            status="unmeasured",
            numerator=None if metric is None else metric.successes,
            denominator=None if metric is None else metric.total,
            comparison=definition.comparison,
            threshold=definition.threshold,
            reason_code=(
                f"{definition.name.upper()}_AUTHORITATIVE_POPULATION_UNDEFINED"
            ),
        )
    if metric is None or metric.total == 0:
        return PromotionGate(
            name=definition.name,
            status="unmeasured",
            comparison=definition.comparison,
            threshold=definition.threshold,
            reason_code=f"{definition.name.upper()}_UNMEASURED",
        )
    denominator_matches = (
        metric.total > 0
        if expected_denominator == "positive"
        else metric.total == expected_denominator
    )
    if not denominator_matches:
        reason = (
            "SUPPORTED_GOLD_COVERAGE_INCOMPLETE"
            if definition.name
            in {"complete_contract_candidate_recall", "decoupled_contract_exact_match"}
            else f"{definition.name.upper()}_DENOMINATOR_INCOMPLETE"
        )
        return PromotionGate(
            name=definition.name,
            status="unmeasured",
            numerator=metric.successes,
            denominator=metric.total,
            comparison=definition.comparison,
            threshold=definition.threshold,
            reason_code=reason,
        )
    assert metric.ratio is not None
    passed = {
        "equal": metric.ratio == definition.threshold,
        "at_least": metric.ratio >= definition.threshold,
        "at_most": metric.ratio <= definition.threshold,
    }[definition.comparison]
    return PromotionGate(
        name=definition.name,
        status="pass" if passed else "fail",
        numerator=metric.successes,
        denominator=metric.total,
        comparison=definition.comparison,
        threshold=definition.threshold,
        reason_code=None if passed else f"{definition.name.upper()}_THRESHOLD_FAILED",
    )


def canonical_report_bytes(report: SemanticQueryPromotionReport) -> bytes:
    return canonical_json_bytes(report)


def collect_static_evidence(project_root: Path) -> PromotionEvidence:
    """Collect repository-derived evidence without claiming runtime-only metrics."""

    root = project_root.resolve()
    snapshot = load_requirement_snapshot(root)
    query_registry = load_query_contract_registry(root)
    catalog = load_catalog(root)
    bindings = load_physical_binding_registry(root)
    policies = load_semantic_sql_policy_registry(root)
    planning = load_planning_registry(root)
    frozen = evaluate_frozen_requirement_snapshot(root, query_registry)
    from financial_agent.intent.evaluation import (
        EvaluationDataset,
        evaluate_candidates,
        parse_strict_json,
    )
    from scripts.evaluate_intent_resolver import _deterministic_predictions

    heldout_dataset_path = (
        root / "tests/evaluation/intent/intent_resolution_heldout_ko_v3.json"
    )
    heldout_dataset = parse_strict_json(
        heldout_dataset_path.read_bytes(), EvaluationDataset
    )
    deterministic_candidate_metrics = evaluate_candidates(
        heldout_dataset.cases,
        _deterministic_predictions(heldout_dataset, catalog),
    )
    requirements = json.loads(
        (
            root
            / "tests/evaluation/query_contract/query_contract_requirements.v1.json"
        ).read_text(encoding="utf-8")
    )["requirements"]
    heldout = [item for item in requirements if item["source"] == "heldout"]
    supported = [item for item in heldout if item["support_status"] == "supported"]
    unsupported = [item for item in heldout if item["support_status"] == "unsupported"]
    by_action_total: Counter[str] = Counter()
    by_action_represented: Counter[str] = Counter()
    heldout_frames_by_case = {
        case["case_id"]: case["expected_frames"]
        for case in heldout_dataset.model_dump(mode="json")["cases"]
    }
    by_action_unsupported: Counter[str] = Counter()
    for requirement in unsupported:
        frame = heldout_frames_by_case[requirement["case_id"]][
            requirement["frame_ordinal"]
        ]
        by_action_unsupported.update(frame["action_ids"])
    for requirement in supported:
        action = requirement["action_id"]
        by_action_total[action] += 1
        if assess_requirement_representability(
            query_registry,
            action_id=action,
            components=tuple(requirement["required_components"]),
            nonrepresentable_reason=None,
        ).variant_id is not None:
            by_action_represented[action] += 1
    unsupported_reason_count = sum(bool(item.get("reason_code")) for item in unsupported)
    return PromotionEvidence(
        source_hashes={
            "core": snapshot.core_source_hash,
            "heldout": snapshot.heldout_source_hash,
            "representative_contract_expectations": REPRESENTATIVE_EXPECTATION_HASH,
            "supported_action_population": SUPPORTED_ACTION_POPULATION_HASH,
            "unsupported_action_population": UNSUPPORTED_ACTION_POPULATION_HASH,
        },
        registry_hashes={
            "physical_bindings": bindings.registry_hash,
            "physical_policies": policies.registry_hash,
            "planning": planning.registry_hash,
            "query_contract": query_registry.contract_registry_hash,
            "query_operator": query_registry.operator_registry_hash,
            "query_policy": query_registry.policy_registry_hash,
            "semantic_catalog": catalog.catalog_hash,
        },
        counts=SemanticQueryCounts(
            core_questions=snapshot.core_question_count,
            heldout_cases=snapshot.heldout_case_count,
            heldout_frames=snapshot.heldout_frame_count,
            supported_frames=frozen.supported_frame_count,
            unsupported_frames=frozen.unsupported_frame_count,
            intentionally_blocked_frames=frozen.intentionally_blocked_frame_count,
            contract_gold_measured_frames=frozen.measured_frame_count,
            contract_gold_unmeasured_frames=frozen.evaluation_unmeasured_frame_count,
        ),
        per_action_representability={
            action: CountEvidence(
                successes=by_action_represented[action], total=by_action_total[action]
            )
            for action in ACTION_IDS
        },
        per_action_unsupported={
            action: by_action_unsupported[action]
            for action in ACTION_IDS
        },
        supported_representability=CountEvidence(
            successes=sum(by_action_represented.values()), total=len(supported)
        ),
        unsupported_reason_coverage=CountEvidence(
            successes=unsupported_reason_count, total=len(unsupported)
        ),
        false_complete=CountEvidence(
            successes=frozen.false_complete_count, total=frozen.unsupported_frame_count
        ),
        exact_lock_precision=None,
        complete_contract_candidate_recall=CountEvidence(
            successes=frozen.candidate_recall_count, total=frozen.measured_frame_count
        ),
        decoupled_contract_exact_match=CountEvidence(
            successes=frozen.exact_contract_count, total=frozen.measured_frame_count
        ),
        executable_compile_success=None,
        byte_equivalence=None,
        readiness_distribution={},
        adr_candidate_recall_at_5=CountEvidence(
            successes=deterministic_candidate_metrics.recall_at_5.numerator,
            total=deterministic_candidate_metrics.recall_at_5.denominator,
        ),
        adr_first_pass_structured_validity=None,
        adr_joint_frame_exact=None,
        adr_context_link_exact=None,
        ood_false_fast=None,
        postgres_conformance=None,
        public_fund_physical_definition=None,
        live_paths=(),
    )


@dataclass(frozen=True, slots=True)
class _BenchmarkCase:
    case_id: str
    question: str
    actions: tuple[str, ...]
    families: tuple[str, ...]


_LIVE_CASES = (
    _BenchmarkCase("fee-screen", "공모펀드 중 총보수가 1% 이하인 상품을 찾아줘", ("screen",), ("public_fund",)),
    _BenchmarkCase("public-aum-sum", "전체 공모펀드의 순자산 합계는?", ("aggregate",), ("public_fund",)),
    _BenchmarkCase("overseas-aum-rank", "해외 ETF 중 순자산 상위 5개 알려줘", ("rank",), ("overseas_etf",)),
    _BenchmarkCase("domestic-return-rank", "국내 ETF 중 1년 수익률 상위 3개 알려줘", ("rank",), ("domestic_etf",)),
    _BenchmarkCase("bond-risk-screen", "국내 채권 중 위험등급 3등급 이하만 보여줘", ("screen",), ("domestic_bond",)),
    _BenchmarkCase("exact-family", "공모펀드 상품 이름과 순자산을 알려줘", ("lookup",), ("public_fund",)),
    _BenchmarkCase("multi-predicate", "해외 ETF 중 총보수 0.5% 이하이고 순자산 100억원 이상인 상품", ("screen",), ("overseas_etf",)),
    _BenchmarkCase("qualitative-rank", "보수가 낮은 ETF 5개 알려줘", ("rank",), ("domestic_etf", "overseas_etf")),
    _BenchmarkCase("numeric-screen", "총보수가 0.5% 이하인 ETF를 찾아줘", ("screen",), ("domestic_etf", "overseas_etf")),
    _BenchmarkCase("count", "국내 ETF는 모두 몇 개인가?", ("aggregate",), ("domestic_etf",)),
    _BenchmarkCase("sum", "해외 ETF의 순자산 합계를 알려줘", ("aggregate",), ("overseas_etf",)),
    _BenchmarkCase("grouped-aggregate", "국내 ETF를 위험등급별로 몇 개인지 세어줘", ("aggregate",), ("domestic_etf",)),
    _BenchmarkCase("cross-family", "국내 ETF와 해외 ETF의 순자산을 비교해줘", ("compare",), ("domestic_etf", "overseas_etf")),
    _BenchmarkCase("prior-result", "ETF 중 순자산 상위 5개를 찾고, 그 상품 중 수익률 1위는?", ("rank", "rank"), ("domestic_etf", "overseas_etf")),
    _BenchmarkCase("lexical-ood", "ESG 등급이 높은 ETF를 알려줘", ("screen",), ("domestic_etf", "overseas_etf")),
    _BenchmarkCase("domain-ood", "요즘 시장 분위기가 어때?", (), ()),
)


def _scope(*families: str, prior: str | None = None) -> dict[str, object]:
    return {
        "product_family_ids": list(families),
        "entity_refs": [],
        "prior_result_binding": prior,
    }


def _qualifiers(*, period: str | None = None) -> dict[str, object]:
    return {
        "period_id": period,
        "currency_id": None,
        "unit_id": None,
        "as_of_date": None,
    }


def _value(decimal: str, unit: str | None) -> dict[str, object]:
    return {
        "kind": "decimal",
        "string": None,
        "integer": None,
        "decimal": decimal,
        "boolean": None,
        "date": None,
        "datetime": None,
        "identifier": None,
        "unit_id": unit,
    }


def _atom(
    field: str, operator: str, decimal: str, unit: str | None
) -> dict[str, object]:
    return {
        "node_type": "atom",
        "field_concept_id": field,
        "operator_id": operator,
        "value": _value(decimal, unit),
        "values": [],
        "null_policy_id": "exclude_missing.v1",
    }


def _contract_base(
    variant: str, action: str, families: tuple[str, ...], result_shape: str, *, prior: str | None = None
) -> dict[str, object]:
    return {
        "contract_variant_id": variant,
        "action_id": action,
        "scope": _scope(*families, prior=prior),
        "qualifiers": _qualifiers(),
        "result_shape": result_shape,
    }


def _screen_contract(families: tuple[str, ...], predicate: dict[str, object]) -> dict[str, object]:
    return {
        **_contract_base("screen.predicate.v2", "screen", families, "product_list"),
        "predicate": predicate,
    }


def _aggregate_contract(
    family: str,
    function: str,
    *,
    target: str | None = None,
    count_population: str | None = None,
    group_by: tuple[str, ...] = (),
    population_grain: str = "source-product.v1",
    dedup_policy: str = "no-dedup.v1",
) -> dict[str, object]:
    grouped = bool(group_by)
    return {
        **_contract_base(
            "aggregate.grouped.v2" if grouped else "aggregate.scalar.v2",
            "aggregate",
            (family,),
            "grouped_table" if grouped else "single_value",
        ),
        "aggregation": {
            "function_id": function,
            "target_field_concept_id": target,
            "count_population_id": count_population,
            "group_by_field_concept_ids": list(group_by),
            "bucket_policy_id": None,
            "population_grain_id": population_grain,
            "dedup_policy_id": dedup_policy,
        },
        "predicate": None,
    }


def _rank_contract(
    family: str,
    field: str,
    limit: int,
    *,
    period: str | None = None,
) -> dict[str, object]:
    contract = _contract_base(
        "rank.ordering.v2", "rank", (family,), "top_k"
    )
    contract["qualifiers"] = _qualifiers(period=period)
    contract.update({
        "ordering": [{
            "field_concept_id": field,
            "direction": "desc",
            "direction_policy_id": None,
            "nulls_policy_id": "exclude_missing.v1",
            "tie_break_policy_id": "stable-product-id.v1",
        }],
        "limit": limit,
        "limit_policy_id": None,
        "predicate": None,
    })
    return contract


_fee_screen = _screen_contract(
    ("public_fund",), _atom("fee_rate", "lte", "1", "percent")
)


# These are exactly the five previously accepted failures, with every semantic
# role authoritative and hashed. This gate is not a general smoke-case score.
REPRESENTATIVE_CASE_EXPECTATIONS: Mapping[str, object] = {
    "fee-screen": {
        "actions": ["screen"],
        "families": ["public_fund"],
        "contracts": [_fee_screen],
        "context_links": [],
    },
    "public-aum-sum": {
        "actions": ["aggregate"],
        "families": ["public_fund"],
        "contracts": [_aggregate_contract(
            "public_fund",
            "sum",
            target="aum",
            population_grain="representative-product.v1",
            dedup_policy="public-fund-representative-share.v1",
        )],
        "context_links": [],
    },
    "overseas-aum-rank": {
        "actions": ["rank"],
        "families": ["overseas_etf"],
        "contracts": [_rank_contract("overseas_etf", "aum", 5)],
        "context_links": [],
    },
    "domestic-return-rank": {
        "actions": ["rank"],
        "families": ["domestic_etf"],
        "contracts": [_rank_contract(
            "domestic_etf",
            "trailing_1y_historical_cumulative_return",
            3,
            period="P1Y",
        )],
        "context_links": [],
    },
    "bond-risk-screen": {
        "actions": ["screen"],
        "families": ["domestic_bond"],
        "contracts": [_screen_contract(
            ("domestic_bond",),
            _atom("credit_grade", "lte", "3", None),
        )],
        "context_links": [],
    },
}
REPRESENTATIVE_GROUPS = (
    ("fee-screen",),
    ("public-aum-sum",),
    ("overseas-aum-rank",),
    ("domestic-return-rank",),
    ("bond-risk-screen",),
)
REPRESENTATIVE_EXPECTATION_HASH = hashlib.sha256(
    canonical_json_bytes(REPRESENTATIVE_CASE_EXPECTATIONS)
).hexdigest()


def evaluate_representative_contracts(
    observations: Mapping[str, object],
) -> CountEvidence:
    """Score the five complete, pinned semantic groups; missing or extra data fails."""

    if set(observations) != set(REPRESENTATIVE_CASE_EXPECTATIONS):
        return CountEvidence(successes=0, total=len(REPRESENTATIVE_GROUPS))
    successes = sum(
        all(
            case_id in observations
            and canonical_json_bytes(observations[case_id])
            == canonical_json_bytes(REPRESENTATIVE_CASE_EXPECTATIONS[case_id])
            for case_id in group
        )
        for group in REPRESENTATIVE_GROUPS
    )
    return CountEvidence(successes=successes, total=len(REPRESENTATIVE_GROUPS))


def _representative_observation(attempt: object) -> dict[str, object]:
    resolution = attempt.resolution  # type: ignore[attr-defined]
    candidate_set = attempt.candidates  # type: ignore[attr-defined]
    frames = resolution.canonical_frames
    frame_ordinals = {frame.frame_id: frame.ordinal for frame in frames}
    contracts: list[dict[str, object]] = []
    for frame_candidates in candidate_set.frames:
        for candidate in frame_candidates.complete_candidates:
            payload = candidate.contract.model_dump(
                mode="json",
                exclude={"contract_schema_version", "frame_id", "provenance", "registry_pins"},
            )
            prior = payload["scope"]["prior_result_binding"]
            if prior is not None:
                producer_ordinal = frame_ordinals.get(prior)
                payload["scope"]["prior_result_binding"] = (
                    None
                    if producer_ordinal is None
                    else f"producer-frame-{producer_ordinal}"
                )
            contracts.append(payload)
    return {
        "actions": [
            action.value
            for frame in frames
            for action in frame.action_choice.selected_ids
        ],
        "families": sorted({
            family.value
            for frame in frames
            for family in frame.product_family_choice.selected_ids
        }),
        "contracts": contracts,
        "context_links": [{
            "link_type": link.link_type.value,
            "source_role": link.source_role.value,
            "selector": [item.value for item in link.selector],
            "producer_frame_ordinal": frame_ordinals.get(link.producer_frame_id),
            "consumer_frame_ordinal": frame_ordinals.get(link.consumer_frame_id),
            "target_kind": [item.value for item in link.target_kind],
            "target_cardinality": [item.value for item in link.target_cardinality],
            "target_slot_kind": [item.value for item in link.target_slot_kind],
        } for link in resolution.context_links],
    }


class _EmptyEntityRepository:
    async def search_batch(self, dataset_version: str, mentions: object) -> dict[str, object]:
        return {}


@dataclass(frozen=True, slots=True)
class _ProviderCallRecord:
    call_id: int
    call_type: str
    success: bool
    elapsed_ms: int
    prompt_tokens: int
    completion_tokens: int
    error_code: str | None


class _RecordingAdapter:
    def __init__(self, inner: ClovaStructuredOutputAdapter, raw_path: Path) -> None:
        self.inner = inner
        self.raw_path = raw_path
        self.calls = 0
        self.records: list[_ProviderCallRecord] = []

    async def invoke(self, envelope: object, timeout_seconds: float) -> ModelInvocationResult:
        self.calls += 1
        call_id = self.calls
        call_type = _call_type(envelope)
        started = time.perf_counter()
        try:
            result = await self.inner.invoke(envelope, timeout_seconds)
        except Exception as error:
            self.records.append(_ProviderCallRecord(
                call_id=call_id,
                call_type=call_type,
                success=False,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                prompt_tokens=0,
                completion_tokens=0,
                error_code=getattr(error, "code", type(error).__name__),
            ))
            raise
        self.records.append(_ProviderCallRecord(
            call_id=call_id,
            call_type=call_type,
            success=True,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=int(result.usage.get("promptTokens", 0)),
            completion_tokens=int(result.usage.get("completionTokens", 0)),
            error_code=None,
        ))
        _append_raw(
            self.raw_path,
            {"call": call_id, "call_type": call_type, "content": result.content},
        )
        return result


@dataclass(frozen=True, slots=True)
class _Envelope:
    axis: Literal["action", "family", "tag"]
    system_message: str
    user_message: str
    response_schema: dict[str, object]


def _axis_envelope(case: _BenchmarkCase, axis: str) -> _Envelope:
    if axis == "action":
        values = list(ACTION_IDS)
        schema: dict[str, object] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["ids"],
            "properties": {"ids": {"type": "array", "maxItems": len(values), "uniqueItems": True, "items": {"type": "string", "enum": values}}},
        }
    elif axis == "family":
        values = ["domestic_bond", "domestic_etf", "overseas_etf", "public_fund"]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["ids"],
            "properties": {"ids": {"type": "array", "maxItems": 4, "uniqueItems": True, "items": {"type": "string", "enum": values}}},
        }
    else:
        values = [item.value for item in SemanticTag]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["ids"],
            "properties": {"ids": {"type": "array", "maxItems": len(values), "uniqueItems": True, "items": {"type": "string", "enum": values}}},
        }
    return _Envelope(
        axis=axis,  # type: ignore[arg-type]
        system_message=(
            f"한국어 금융상품 질문에서 {axis} 축만 분류하세요. 제공된 ID만 사용하고 "
            "설명 없이 JSON으로 답하세요. 모르면 빈 배열을 반환하세요."
        ),
        user_message=case.question,
        response_schema=schema,
    )


def _call_type(envelope: object) -> str:
    if isinstance(envelope, _Envelope):
        return f"challenger_{envelope.axis}"
    if isinstance(envelope, QueryContractJudgePromptEnvelope):
        return "judge"
    if "Apply this correction only:" in str(getattr(envelope, "system_message", "")):
        return "repair"
    return "primary"


def parse_challenger_axis_payload(content: str, axis: str) -> tuple[str, ...]:
    allowed_by_axis = {
        "action": (set(ACTION_IDS), len(ACTION_IDS)),
        "family": (
            {"domestic_bond", "domestic_etf", "overseas_etf", "public_fund"},
            4,
        ),
        "tag": ({item.value for item in SemanticTag}, len(SemanticTag)),
    }
    if axis not in allowed_by_axis:
        raise ValueError("CHALLENGER_SCHEMA_INVALID")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("CHALLENGER_SCHEMA_INVALID")
            value[key] = item
        return value

    try:
        value = json.loads(content, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError("CHALLENGER_SCHEMA_INVALID") from error
    if not isinstance(value, dict) or set(value) != {"ids"}:
        raise ValueError("CHALLENGER_SCHEMA_INVALID")
    ids = value["ids"]
    allowed, maximum = allowed_by_axis[axis]
    if (
        not isinstance(ids, list)
        or len(ids) > maximum
        or any(type(item) is not str for item in ids)
        or len(ids) != len(set(ids))
        or any(item not in allowed for item in ids)
    ):
        raise ValueError("CHALLENGER_SCHEMA_INVALID")
    return tuple(ids)


async def run_live_benchmark(
    *,
    api_key: str,
    model: str,
    paced: bool,
    interval_seconds: float,
    raw_path: Path,
) -> tuple[LivePathEvidence, ...]:
    if model != "HCX-007":
        raise ValueError("LIVE_MODEL_NOT_AUTHORIZED")
    _prepare_raw(raw_path)
    adapter = _RecordingAdapter(
        ClovaStructuredOutputAdapter(
            ClovaResolverConfig(
                api_key=SecretStr(api_key),
                base_url=LIVE_BASE_URL,
                model_id=model,
                max_completion_tokens=4096,
                temperature=0.0,
                top_p=0.1,
                top_k=1,
                repetition_penalty=1.0,
            )
        ),
        raw_path,
    )
    catalog = load_catalog(PROJECT_ROOT)
    manifest = build_manifest(
        catalog,
        {
            "normalizer_version": NORMALIZER_VERSION,
            "candidate_policy_version": CANDIDATE_POLICY_VERSION,
            "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "adapter_version": ADAPTER_VERSION,
        },
    )
    service = IntentResolverService(
        adapter=adapter,
        entity_repository=_EmptyEntityRepository(),
        catalog=catalog,
        manifest=manifest,
        active_dataset_pin=ActiveDatasetPin(
            dataset_version=LIVE_DATASET_VERSION, manifest_hash="0" * 64
        ),
        query_contract_registry=load_query_contract_registry(PROJECT_ROOT),
    )
    baseline = await _run_production_path(service, adapter, paced, interval_seconds)
    challenger = await _run_challenger_path(adapter, paced, interval_seconds)
    return (baseline, challenger)


async def _run_production_path(
    service: IntentResolverService,
    adapter: _RecordingAdapter,
    paced: bool,
    interval: float,
) -> LivePathEvidence:
    provider_successes = valid = action_hits = family_hits = complete = 0
    semantic_errors: Counter[str] = Counter()
    observations: dict[str, object] = {}
    start_record = len(adapter.records)
    for index, case in enumerate(_LIVE_CASES):
        context = _request_context(case)
        case_record = len(adapter.records)
        try:
            attempt = await service.resolve_query_contract_candidates(context)
        except (ModelInvocationError, ResolverContractError, ValueError) as error:
            semantic_errors[getattr(error, "code", type(error).__name__)] += 1
        else:
            valid += 1
            actual_actions = tuple(
                action.value
                for frame in attempt.resolution.canonical_frames
                for action in frame.action_choice.selected_ids
            )
            actual_families = tuple(
                sorted(
                    {
                        family.value
                        for frame in attempt.resolution.canonical_frames
                        for family in frame.product_family_choice.selected_ids
                    }
                )
            )
            action_hits += int(actual_actions == case.actions)
            family_hits += int(actual_families == tuple(sorted(case.families)))
            complete += int(
                bool(attempt.candidates.frames)
                and all(frame.complete_candidates for frame in attempt.candidates.frames)
            )
            if case.case_id in REPRESENTATIVE_CASE_EXPECTATIONS:
                observations[case.case_id] = _representative_observation(attempt)
        provider_successes += int(
            any(record.success for record in adapter.records[case_record:])
        )
        if paced and index + 1 < len(_LIVE_CASES):
            await asyncio.sleep(interval)
    records = adapter.records[start_record:]
    provider_errors = Counter(
        record.error_code for record in records if record.error_code is not None
    )
    call_types = Counter(record.call_type for record in records)
    return LivePathEvidence(
        path_id="production_one_axis",
        case_count=len(_LIVE_CASES),
        provider_success=CountEvidence(
            successes=provider_successes, total=len(_LIVE_CASES)
        ),
        structured_validity=CountEvidence(successes=valid, total=len(_LIVE_CASES)),
        action_exact=CountEvidence(successes=action_hits, total=len(_LIVE_CASES)),
        family_exact=CountEvidence(successes=family_hits, total=len(_LIVE_CASES)),
        complete_contract=CountEvidence(successes=complete, total=len(_LIVE_CASES)),
        representative_contract_exact=evaluate_representative_contracts(observations),
        repair_count=call_types["repair"],
        judge_count=call_types["judge"],
        provider_calls=len(records),
        successful_provider_calls=sum(record.success for record in records),
        call_type_counts=dict(sorted(call_types.items())),
        provider_error_counts=dict(sorted(provider_errors.items())),
        semantic_error_counts=dict(sorted(semantic_errors.items())),
        input_tokens=sum(record.prompt_tokens for record in records),
        output_tokens=sum(record.completion_tokens for record in records),
        p50_latency_ms=_percentile([record.elapsed_ms for record in records], 50),
        p95_latency_ms=_percentile([record.elapsed_ms for record in records], 95),
        rate_limit_count=provider_errors["MODEL_RATE_LIMITED"],
    )


async def _run_challenger_path(
    adapter: _RecordingAdapter, paced: bool, interval: float
) -> LivePathEvidence:
    successes = valid = action_hits = family_hits = 0
    semantic_errors: Counter[str] = Counter()
    start_record = len(adapter.records)
    for index, case in enumerate(_LIVE_CASES):
        results = await asyncio.gather(
            *(
                adapter.invoke(_axis_envelope(case, axis), REQUEST_DEADLINE_SECONDS)
                for axis in ("action", "family", "tag")
            ),
            return_exceptions=True,
        )
        if all(isinstance(item, ModelInvocationResult) for item in results):
            successes += 1
            try:
                ids = [
                    parse_challenger_axis_payload(item.content, axis)  # type: ignore[union-attr]
                    for item, axis in zip(results, ("action", "family", "tag"), strict=True)
                ]
            except ValueError:
                semantic_errors["CHALLENGER_SCHEMA_INVALID"] += 1
            else:
                valid += 1
                action_hits += int(ids[0] == case.actions)
                family_hits += int(tuple(sorted(ids[1])) == tuple(sorted(case.families)))
        else:
            semantic_errors["CHALLENGER_PROVIDER_BUNDLE_INCOMPLETE"] += 1
        if paced and index + 1 < len(_LIVE_CASES):
            await asyncio.sleep(interval)
    records = adapter.records[start_record:]
    provider_errors = Counter(
        record.error_code for record in records if record.error_code is not None
    )
    call_types = Counter(record.call_type for record in records)
    return LivePathEvidence(
        path_id="parallel_three_axis_challenger",
        case_count=len(_LIVE_CASES),
        provider_success=CountEvidence(successes=successes, total=len(_LIVE_CASES)),
        structured_validity=CountEvidence(successes=valid, total=len(_LIVE_CASES)),
        action_exact=CountEvidence(successes=action_hits, total=len(_LIVE_CASES)),
        family_exact=CountEvidence(successes=family_hits, total=len(_LIVE_CASES)),
        repair_count=0,
        judge_count=0,
        provider_calls=len(records),
        successful_provider_calls=sum(record.success for record in records),
        call_type_counts=dict(sorted(call_types.items())),
        provider_error_counts=dict(sorted(provider_errors.items())),
        semantic_error_counts=dict(sorted(semantic_errors.items())),
        input_tokens=sum(record.prompt_tokens for record in records),
        output_tokens=sum(record.completion_tokens for record in records),
        p50_latency_ms=_percentile([record.elapsed_ms for record in records], 50),
        p95_latency_ms=_percentile([record.elapsed_ms for record in records], 95),
        rate_limit_count=provider_errors["MODEL_RATE_LIMITED"],
    )


def _request_context(case: _BenchmarkCase) -> RequestContext:
    created = datetime.now(UTC)
    return RequestContext(
        request_key=build_request_key(case.case_id, case.question, LIVE_DATASET_VERSION, "1.0"),
        run_id=f"live-{case.case_id}",
        dataset_version=LIVE_DATASET_VERSION,
        producer="semantic-query-benchmark",
        created_at=created,
        question_id=case.case_id,
        question=case.question,
        segments=(Segment(segment_id=f"segment-{case.case_id}", ordinal=0, text=case.question),),
        deadline_at=created + timedelta(seconds=REQUEST_DEADLINE_SECONDS),
    )


def _percentile(values: list[int], percentile: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = ((len(ordered) - 1) * percentile + 99) // 100
    return ordered[min(index, len(ordered) - 1)]


def _append_raw(path: Path, payload: Mapping[str, object]) -> None:
    if path.parent != Path("/private/tmp"):
        raise ValueError("RAW_OUTPUT_PATH_INVALID")
    flags = os.O_WRONLY | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.write(descriptor, canonical_json_bytes(payload) + b"\n")
    finally:
        os.close(descriptor)


def _prepare_raw(path: Path) -> None:
    if path.parent != Path("/private/tmp"):
        raise ValueError("RAW_OUTPUT_PATH_INVALID")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.close(descriptor)


def _write_sanitized(path: Path, payload: bytes) -> None:
    if path.parent != Path("/private/tmp") or path.suffix != ".json":
        raise ValueError("SANITIZED_REPORT_PATH_INVALID")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("SANITIZED_REPORT_PATH_INVALID")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _load_api_key() -> str | None:
    return os.environ.get("NCP_CLOVA_STUDIO_API") or os.environ.get(
        "FINANCIAL_AGENT_CLOVA_API_KEY"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="HCX-007")
    parser.add_argument("--paced", action="store_true")
    parser.add_argument("--request-interval-seconds", type=float, default=10.0)
    parser.add_argument("--sanitized-report", type=Path, required=True)
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    if args.model != "HCX-007" or args.request_interval_seconds < 0:
        print("SEMANTIC_BENCHMARK_ARGUMENT_INVALID", file=sys.stderr)
        return 2
    evidence = collect_static_evidence(PROJECT_ROOT)
    api_key = _load_api_key()
    live_paths: tuple[LivePathEvidence, ...] = ()
    live_reason = "LIVE_CREDENTIAL_MISSING"
    raw_path: Path | None = None
    if api_key:
        raw_path = Path(f"/private/tmp/semantic-query-benchmark-raw-{uuid.uuid4().hex}.jsonl")
        try:
            live_paths = await run_live_benchmark(
                api_key=api_key,
                model=args.model,
                paced=args.paced,
                interval_seconds=args.request_interval_seconds,
                raw_path=raw_path,
            )
        except (OSError, ModelInvocationError, ResolverContractError, ValueError) as error:
            live_reason = getattr(error, "code", type(error).__name__)
    evidence = evidence.model_copy(update={"live_paths": live_paths})
    report = build_promotion_report(
        evidence,
        expected_source_hashes=evidence.source_hashes,
        expected_registry_hashes=evidence.registry_hashes,
    )
    payload = report.model_dump(mode="json")
    payload["live_execution"] = {
        "status": "measured" if live_paths else "unmeasured",
        "reason_code": None if live_paths else live_reason,
        "raw_output_path": None if raw_path is None else str(raw_path),
    }
    payload["report_hash"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    _write_sanitized(args.sanitized_report.resolve(), canonical_json_bytes(payload) + b"\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
