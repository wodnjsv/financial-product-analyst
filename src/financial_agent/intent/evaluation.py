"""Strict, data-neutral contracts and metrics for offline resolver evaluation.

The production resolver never imports evaluation fixtures. Evaluation inputs are
provided at the offline boundary and validated before any metric is computed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
import json
from math import ceil
from typing import Any, Literal

from pydantic import Field, computed_field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex

from .draft import IntentResolutionDraft
from .resolution import ResolverBuildManifest, ValidatedIntentResolution
from .view import MAX_CANDIDATES_PER_MENTION, ResolverView


ResolutionStatusLabel = Literal[
    "resolved", "ambiguous", "unmapped", "context_unresolved"
]
PipelineOutcome = Literal["semantic_resolution", "pre_model_rejected"]
OodType = Literal["combination", "vocabulary", "domain", "context"]
EvaluationMode = Literal["decoupled", "full"]
ProbeKind = Literal["unknown_id", "invalid_context_graph"]
ProbeDecision = Literal["accepted", "rejected"]
_FALSE_FAST_OOD_TYPES = frozenset({"vocabulary", "domain", "context"})
_PROBE_CODES: dict[tuple[str, str], tuple[str, str]] = {
    ("unknown_id", "accepted"): ("UNKNOWN_ID_ACCEPTED", "UNKNOWN_ID_ACCEPTED"),
    ("unknown_id", "rejected"): ("UNKNOWN_ID_REJECTED", "MODEL_UNKNOWN_ID"),
    ("invalid_context_graph", "accepted"): (
        "INVALID_GRAPH_ACCEPTED",
        "INVALID_GRAPH_ACCEPTED",
    ),
    ("invalid_context_graph", "rejected"): (
        "INVALID_GRAPH_REJECTED",
        "INVALID_CONTEXT_GRAPH",
    ),
}


class EvaluationSegment(ContractModel):
    segment_id: Identifier
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)


class ExpectedSlot(ContractModel):
    slot_kind: Identifier
    value_ids: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> "ExpectedSlot":
        _require_sorted_unique(self.value_ids, "slot value IDs")
        return self


class EvaluationFrame(ContractModel):
    frame_id: Identifier
    ordinal: int = Field(ge=0)
    action_id: Identifier
    product_family_ids: tuple[Identifier, ...]
    entity_type_ids: tuple[Identifier, ...]
    slots: tuple[ExpectedSlot, ...]

    @model_validator(mode="after")
    def validate_semantic_sets(self) -> "EvaluationFrame":
        _require_sorted_unique(self.product_family_ids, "product family IDs")
        _require_sorted_unique(self.entity_type_ids, "entity type IDs")
        _require_unique((slot.slot_kind for slot in self.slots), "slot kinds")
        return self


class ExpectedReference(ContractModel):
    reference_id: Identifier
    reference_form: Identifier
    status: Literal["resolved", "ambiguous", "unresolved"]


class ExpectedContextLink(ContractModel):
    context_link_id: Identifier
    reference_id: Identifier
    link_type: Identifier
    source_role: Identifier
    selector: Identifier | None = None
    producer_frame_id: Identifier
    consumer_frame_id: Identifier
    target_cardinality: Identifier | None = None


class ExpectedSlotMutation(ContractModel):
    slot_mutation_id: Identifier
    consumer_frame_id: Identifier
    slot_kind: Identifier
    mutation_kind: Identifier
    source_frame_id: Identifier | None = None


class EvaluationProbe(ContractModel):
    probe_id: Identifier
    kind: ProbeKind
    subject_ids: tuple[Identifier, ...] = Field(min_length=1)
    expected_rejection_code: Identifier

    @model_validator(mode="after")
    def validate_probe(self) -> "EvaluationProbe":
        _require_sorted_unique(self.subject_ids, "probe subject IDs")
        expected = _PROBE_CODES[(self.kind, "rejected")][1]
        if self.expected_rejection_code != expected:
            raise ValueError("evaluation probe rejection code does not match kind")
        return self


class EvaluationCase(ContractModel):
    case_id: Identifier
    category: Identifier
    subcategory: Identifier
    question: str = Field(min_length=1)
    segments: tuple[EvaluationSegment, ...] = Field(min_length=1)
    expected_candidate_ids: tuple[Identifier, ...]
    expected_frames: tuple[EvaluationFrame, ...]
    expected_references: tuple[ExpectedReference, ...]
    expected_context_links: tuple[ExpectedContextLink, ...]
    expected_slot_mutations: tuple[ExpectedSlotMutation, ...]
    expected_resolution_status: ResolutionStatusLabel
    expected_tags: tuple[Identifier, ...]
    expected_pipeline_outcome: PipelineOutcome
    validation_probes: tuple[EvaluationProbe, ...]
    ood_type: OodType | None = None

    @model_validator(mode="after")
    def validate_case(self) -> "EvaluationCase":
        if tuple(segment.ordinal for segment in self.segments) != tuple(
            range(len(self.segments))
        ):
            raise ValueError("evaluation segment ordinals must be contiguous")
        if self.question != " ".join(segment.text for segment in self.segments):
            raise ValueError("evaluation question must preserve ordered segment text")
        _validate_frames(self.expected_frames, "evaluation")
        _require_unique(self.expected_candidate_ids, "expected candidate IDs")
        _require_unique(
            (item.reference_id for item in self.expected_references),
            "expected reference IDs",
        )
        _require_unique(
            (item.context_link_id for item in self.expected_context_links),
            "expected context link IDs",
        )
        _require_unique(
            (item.slot_mutation_id for item in self.expected_slot_mutations),
            "expected slot mutation IDs",
        )
        _require_sorted_unique(self.expected_tags, "expected tags")
        _require_unique((item.probe_id for item in self.validation_probes), "probe IDs")
        _validate_graph(
            self.expected_frames,
            self.expected_references,
            self.expected_context_links,
            self.expected_slot_mutations,
            allow_dangling=False,
        )
        return self


class EvaluationDataset(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    split_id: Identifier
    cases: tuple[EvaluationCase, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "EvaluationDataset":
        _require_unique((case.case_id for case in self.cases), "evaluation case IDs")
        return self


class CandidateGroup(ContractModel):
    mention_id: Identifier
    candidate_ids: tuple[Identifier, ...] = Field(
        max_length=MAX_CANDIDATES_PER_MENTION
    )

    @model_validator(mode="after")
    def validate_candidates(self) -> "CandidateGroup":
        _require_unique(self.candidate_ids, "candidate IDs within mention")
        return self


class FirstPassSchemaOutcome(ContractModel):
    status: Literal["valid", "invalid"]
    validator_event_code: Literal["SCHEMA_VALID", "SCHEMA_INVALID"]

    @model_validator(mode="after")
    def validate_pair(self) -> "FirstPassSchemaOutcome":
        expected = "SCHEMA_VALID" if self.status == "valid" else "SCHEMA_INVALID"
        if self.validator_event_code != expected:
            raise ValueError("schema status contradicts validator event")
        return self


class RepairOutcome(ContractModel):
    status: Literal["not_attempted", "succeeded", "failed"]
    validator_event_code: Literal[
        "REPAIR_NOT_ATTEMPTED", "REPAIR_SUCCEEDED", "REPAIR_FAILED"
    ]

    @model_validator(mode="after")
    def validate_pair(self) -> "RepairOutcome":
        expected = {
            "not_attempted": "REPAIR_NOT_ATTEMPTED",
            "succeeded": "REPAIR_SUCCEEDED",
            "failed": "REPAIR_FAILED",
        }[self.status]
        if self.validator_event_code != expected:
            raise ValueError("repair status contradicts validator event")
        return self


class ValidationProbeOutcome(ContractModel):
    probe_id: Identifier
    kind: ProbeKind
    subject_ids: tuple[Identifier, ...] = Field(min_length=1)
    decision: ProbeDecision
    validator_event_code: Identifier
    stable_code: Identifier

    @model_validator(mode="after")
    def validate_pair(self) -> "ValidationProbeOutcome":
        _require_sorted_unique(self.subject_ids, "probe outcome subject IDs")
        event_code, stable_code = _PROBE_CODES[(self.kind, self.decision)]
        if self.validator_event_code != event_code or self.stable_code != stable_code:
            raise ValueError("probe decision contradicts validator evidence")
        return self


class EvaluationPrediction(ContractModel):
    case_id: Identifier
    candidate_groups: tuple[CandidateGroup, ...]
    candidate_reproducible: bool
    frames: tuple[EvaluationFrame, ...]
    references: tuple[ExpectedReference, ...]
    context_links: tuple[ExpectedContextLink, ...]
    slot_mutations: tuple[ExpectedSlotMutation, ...]
    resolution_status: ResolutionStatusLabel
    pipeline_outcome: PipelineOutcome
    predicted_ood_type: OodType | None = None
    tags: tuple[Identifier, ...]
    blocking_issue_codes: tuple[Identifier, ...]
    first_pass_schema: FirstPassSchemaOutcome
    repair: RepairOutcome
    validation_probe_outcomes: tuple[ValidationProbeOutcome, ...]
    latency_ms: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    stable_error_codes: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_prediction(self) -> "EvaluationPrediction":
        _require_unique(
            (group.mention_id for group in self.candidate_groups),
            "prediction candidate mention IDs",
        )
        _validate_frames(self.frames, "prediction")
        _require_unique(
            (item.reference_id for item in self.references),
            "prediction reference IDs",
        )
        _require_unique(
            (item.context_link_id for item in self.context_links),
            "prediction context link IDs",
        )
        _require_unique(
            (item.slot_mutation_id for item in self.slot_mutations),
            "prediction slot mutation IDs",
        )
        _require_sorted_unique(self.tags, "prediction tags")
        _require_sorted_unique(
            self.blocking_issue_codes, "prediction blocking issue codes"
        )
        _require_sorted_unique(self.stable_error_codes, "prediction stable error codes")
        _require_unique(
            (item.probe_id for item in self.validation_probe_outcomes),
            "prediction probe outcome IDs",
        )
        return self


class ResolverViewCaseArtifact(ContractModel):
    case_id: Identifier
    artifact: ResolverView


class ResolverViewBundle(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Identifier
    cases: tuple[ResolverViewCaseArtifact, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "ResolverViewBundle":
        _require_unique((case.case_id for case in self.cases), "view bundle case IDs")
        return self


class IntentDraftCaseArtifact(ContractModel):
    case_id: Identifier
    artifact: IntentResolutionDraft


class IntentDraftBundle(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Identifier
    cases: tuple[IntentDraftCaseArtifact, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "IntentDraftBundle":
        _require_unique((case.case_id for case in self.cases), "draft bundle case IDs")
        return self


class ValidatedResolutionCaseArtifact(ContractModel):
    case_id: Identifier
    artifact: ValidatedIntentResolution


class ValidatedResolutionBundle(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Identifier
    cases: tuple[ValidatedResolutionCaseArtifact, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "ValidatedResolutionBundle":
        _require_unique(
            (case.case_id for case in self.cases), "resolution bundle case IDs"
        )
        return self


class PredictionDataset(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    mode: EvaluationMode
    dataset_id: Identifier
    evaluation_dataset_sha256: Sha256Hex
    dataset_version: Identifier
    dataset_manifest_hash: Sha256Hex
    build_manifest: ResolverBuildManifest
    model_id: Identifier
    bounded_view_bundle_raw_sha256: Sha256Hex | None = None
    bounded_view_bundle_canonical_sha256: Sha256Hex | None = None
    draft_bundle_raw_sha256: Sha256Hex | None = None
    draft_bundle_canonical_sha256: Sha256Hex | None = None
    resolution_bundle_raw_sha256: Sha256Hex | None = None
    resolution_bundle_canonical_sha256: Sha256Hex | None = None
    predictions: tuple[EvaluationPrediction, ...]

    @model_validator(mode="after")
    def validate_mode_evidence(self) -> "PredictionDataset":
        decoupled_values = (
            self.bounded_view_bundle_raw_sha256,
            self.bounded_view_bundle_canonical_sha256,
            self.draft_bundle_raw_sha256,
            self.draft_bundle_canonical_sha256,
        )
        full_values = (
            self.resolution_bundle_raw_sha256,
            self.resolution_bundle_canonical_sha256,
        )
        if self.mode == "decoupled":
            if any(value is None for value in decoupled_values) or any(
                value is not None for value in full_values
            ):
                raise ValueError("decoupled prediction evidence is incomplete")
        elif any(value is None for value in full_values) or any(
            value is not None for value in decoupled_values
        ):
            raise ValueError("full prediction evidence is incomplete")
        _require_unique(
            (prediction.case_id for prediction in self.predictions),
            "prediction case IDs",
        )
        return self


class RegressionAxes(ContractModel):
    intent_label: Identifier
    product_family_ids: tuple[Identifier, ...]
    entity_type_ids: tuple[Identifier, ...]
    semantic_ids: tuple[Identifier, ...]
    expected_disposition: Identifier


class RegressionContextLabel(ContractModel):
    mention: str = Field(min_length=1)
    binds_to: str | tuple[str, ...] | None
    expected: Identifier
    candidates: tuple[str, ...] = ()


class RegressionCase(ContractModel):
    case_id: Identifier
    expected_axes: RegressionAxes
    expected_context: tuple[RegressionContextLabel, ...]


class RegressionSource(ContractModel):
    relative_path: str = Field(min_length=1)
    sha256: Sha256Hex
    label_policy: Identifier


class RegressionDataset(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    split_id: Identifier
    source: RegressionSource
    cases: tuple[RegressionCase, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "RegressionDataset":
        _require_unique((case.case_id for case in self.cases), "regression case IDs")
        return self


class CountMetric(ContractModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_count(self) -> "CountMetric":
        if self.numerator > self.denominator:
            raise ValueError("metric numerator cannot exceed denominator")
        return self

    @computed_field
    @property
    def value(self) -> Decimal:
        """Exact ratio; zero denominator is numeric zero but explicitly undefined."""
        if self.denominator == 0:
            return Decimal("0")
        return Decimal(self.numerator) / Decimal(self.denominator)

    @computed_field
    @property
    def defined(self) -> bool:
        return self.denominator > 0

    @computed_field
    @property
    def evidence_sufficient(self) -> bool:
        return self.denominator > 0


class PrecisionRecallF1(ContractModel):
    precision: CountMetric
    recall: CountMetric
    f1: CountMetric


class CandidateMetrics(ContractModel):
    recall_at_1: CountMetric
    recall_at_3: CountMetric
    recall_at_5: CountMetric
    reproducibility: CountMetric


class FrameMetrics(ContractModel):
    joint_exact_match: CountMetric
    action: PrecisionRecallF1
    product_family: PrecisionRecallF1
    entity_type: PrecisionRecallF1
    slot: PrecisionRecallF1


class ContextMetrics(ContractModel):
    reference_exact_match: CountMetric
    link_exact_match: CountMetric
    selector_exact_match: CountMetric
    cardinality_exact_match: CountMetric
    mutation_exact_match: CountMetric


class OodConfusionCount(ContractModel):
    expected: Identifier
    predicted: Identifier
    count: int = Field(ge=0)


class OodMetrics(ContractModel):
    confusion: tuple[OodConfusionCount, ...]
    false_fast_rate: CountMetric


class ValidationMetrics(ContractModel):
    schema_validity: CountMetric
    unknown_id_acceptance: CountMetric
    invalid_graph_acceptance: CountMetric
    repair_rate: CountMetric


class DiagnosticMetrics(ContractModel):
    resolution_status_exact: CountMetric
    tags_exact: CountMetric
    tags: PrecisionRecallF1
    pipeline_outcome_exact: CountMetric


class StableErrorCount(ContractModel):
    code: Identifier
    count: int = Field(ge=1)


class RuntimeMetrics(ContractModel):
    p50_latency_ms: int | None = Field(default=None, ge=0)
    p95_latency_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    stable_error_counts: tuple[StableErrorCount, ...]


class EvaluationReport(ContractModel):
    candidate: CandidateMetrics
    frame: FrameMetrics
    context: ContextMetrics
    ood: OodMetrics
    validation: ValidationMetrics
    diagnostics: DiagnosticMetrics
    runtime: RuntimeMetrics

    @property
    def candidate_recall_at_5(self) -> Decimal:
        return self.candidate.recall_at_5.value

    @property
    def joint_frame_exact_match(self) -> Decimal:
        return self.frame.joint_exact_match.value

    @property
    def context_link_exact_match(self) -> Decimal:
        return self.context.link_exact_match.value

    @property
    def ood_false_fast_rate(self) -> Decimal:
        return self.ood.false_fast_rate.value


def parse_strict_json[T](payload: bytes, model: type[T]) -> T:
    """Reject duplicate keys/non-JSON numbers before strict model validation."""
    json.loads(
        payload,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda _value: _reject_non_json_number(),
    )
    validator = getattr(model, "model_validate_json")
    return validator(payload)


def evaluate_candidates(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> CandidateMetrics:
    aligned = _align(cases, predictions)
    total_gold = sum(len(case.expected_candidate_ids) for case, _ in aligned)

    def recall_at(limit: int) -> CountMetric:
        hits = 0
        for case, prediction in aligned:
            selected = {
                candidate_id
                for group in prediction.candidate_groups
                for candidate_id in group.candidate_ids[:limit]
            }
            hits += len(set(case.expected_candidate_ids) & selected)
        return CountMetric(numerator=hits, denominator=total_gold)

    return CandidateMetrics(
        recall_at_1=recall_at(1),
        recall_at_3=recall_at(3),
        recall_at_5=recall_at(5),
        reproducibility=CountMetric(
            numerator=sum(
                prediction.candidate_reproducible for _, prediction in aligned
            ),
            denominator=len(aligned),
        ),
    )


def evaluate_frames(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> FrameMetrics:
    aligned = _align(cases, predictions)
    return FrameMetrics(
        joint_exact_match=_exact_match(
            aligned,
            lambda case: _frame_signatures(case.expected_frames),
            lambda prediction: _frame_signatures(prediction.frames),
        ),
        action=_micro_prf(
            aligned,
            lambda case: _frame_axis(case.expected_frames, lambda frame: (frame.action_id,)),
            lambda prediction: _frame_axis(prediction.frames, lambda frame: (frame.action_id,)),
        ),
        product_family=_micro_prf(
            aligned,
            lambda case: _frame_axis(case.expected_frames, lambda frame: frame.product_family_ids),
            lambda prediction: _frame_axis(
                prediction.frames, lambda frame: frame.product_family_ids
            ),
        ),
        entity_type=_micro_prf(
            aligned,
            lambda case: _frame_axis(case.expected_frames, lambda frame: frame.entity_type_ids),
            lambda prediction: _frame_axis(prediction.frames, lambda frame: frame.entity_type_ids),
        ),
        slot=_micro_prf(
            aligned,
            lambda case: _slot_axis(case.expected_frames),
            lambda prediction: _slot_axis(prediction.frames),
        ),
    )


def evaluate_context(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> ContextMetrics:
    aligned = _align(cases, predictions)
    return ContextMetrics(
        reference_exact_match=_exact_match(
            aligned,
            lambda case: _reference_signatures(case.expected_references),
            lambda prediction: _reference_signatures(prediction.references),
        ),
        link_exact_match=_exact_match(
            aligned,
            lambda case: _context_link_signatures(
                case.expected_frames,
                case.expected_references,
                case.expected_context_links,
                include_selector=True,
                include_cardinality=True,
            ),
            lambda prediction: _context_link_signatures(
                prediction.frames,
                prediction.references,
                prediction.context_links,
                include_selector=True,
                include_cardinality=True,
            ),
        ),
        selector_exact_match=_exact_match(
            aligned,
            lambda case: _context_link_signatures(
                case.expected_frames,
                case.expected_references,
                case.expected_context_links,
                include_selector=True,
                include_cardinality=False,
            ),
            lambda prediction: _context_link_signatures(
                prediction.frames,
                prediction.references,
                prediction.context_links,
                include_selector=True,
                include_cardinality=False,
            ),
        ),
        cardinality_exact_match=_exact_match(
            aligned,
            lambda case: _context_link_signatures(
                case.expected_frames,
                case.expected_references,
                case.expected_context_links,
                include_selector=False,
                include_cardinality=True,
            ),
            lambda prediction: _context_link_signatures(
                prediction.frames,
                prediction.references,
                prediction.context_links,
                include_selector=False,
                include_cardinality=True,
            ),
        ),
        mutation_exact_match=_exact_match(
            aligned,
            lambda case: _mutation_signatures(case.expected_frames, case.expected_slot_mutations),
            lambda prediction: _mutation_signatures(prediction.frames, prediction.slot_mutations),
        ),
    )


def evaluate_ood(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> OodMetrics:
    aligned = _align(cases, predictions)
    confusion: Counter[tuple[str, str]] = Counter()
    false_fast = 0
    ood_total = 0
    for case, prediction in aligned:
        expected = case.ood_type or "in_domain"
        predicted = (
            "fast"
            if prediction.pipeline_outcome == "semantic_resolution"
            and prediction.resolution_status == "resolved"
            and not prediction.blocking_issue_codes
            else prediction.predicted_ood_type or prediction.pipeline_outcome
        )
        confusion[(expected, predicted)] += 1
        if case.ood_type in _FALSE_FAST_OOD_TYPES:
            ood_total += 1
            false_fast += int(predicted == "fast")
    return OodMetrics(
        confusion=tuple(
            OodConfusionCount(expected=expected, predicted=predicted, count=count)
            for (expected, predicted), count in sorted(confusion.items())
        ),
        false_fast_rate=CountMetric(numerator=false_fast, denominator=ood_total),
    )


def evaluate_predictions(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> EvaluationReport:
    aligned = _align(cases, predictions)
    for case, prediction in aligned:
        _validate_evidence_alignment(case, prediction)
    values = tuple(prediction for _, prediction in aligned)
    probes = tuple(
        (probe, _probe_index(prediction)[probe.probe_id])
        for case, prediction in aligned
        for probe in case.validation_probes
    )
    unknown = tuple(item for item in probes if item[0].kind == "unknown_id")
    invalid_graph = tuple(
        item for item in probes if item[0].kind == "invalid_context_graph"
    )
    errors = Counter(code for item in values for code in item.stable_error_codes)
    errors.update(
        outcome.stable_code
        for _, outcome in probes
        if outcome.decision == "accepted"
    )
    latencies = tuple(sorted(item.latency_ms for item in values))
    return EvaluationReport(
        candidate=evaluate_candidates(cases, predictions),
        frame=evaluate_frames(cases, predictions),
        context=evaluate_context(cases, predictions),
        ood=evaluate_ood(cases, predictions),
        validation=ValidationMetrics(
            schema_validity=CountMetric(
                numerator=sum(item.first_pass_schema.status == "valid" for item in values),
                denominator=len(values),
            ),
            unknown_id_acceptance=CountMetric(
                numerator=sum(outcome.decision == "accepted" for _, outcome in unknown),
                denominator=len(unknown),
            ),
            invalid_graph_acceptance=CountMetric(
                numerator=sum(outcome.decision == "accepted" for _, outcome in invalid_graph),
                denominator=len(invalid_graph),
            ),
            repair_rate=CountMetric(
                numerator=sum(item.repair.status != "not_attempted" for item in values),
                denominator=len(values),
            ),
        ),
        diagnostics=DiagnosticMetrics(
            resolution_status_exact=_exact_match(
                aligned,
                lambda case: case.expected_resolution_status,
                lambda prediction: prediction.resolution_status,
            ),
            tags_exact=_exact_match(
                aligned,
                lambda case: case.expected_tags,
                lambda prediction: prediction.tags,
            ),
            tags=_micro_prf(
                aligned,
                lambda case: frozenset(case.expected_tags),
                lambda prediction: frozenset(prediction.tags),
            ),
            pipeline_outcome_exact=_exact_match(
                aligned,
                lambda case: case.expected_pipeline_outcome,
                lambda prediction: prediction.pipeline_outcome,
            ),
        ),
        runtime=RuntimeMetrics(
            p50_latency_ms=_nearest_rank(latencies, 50),
            p95_latency_ms=_nearest_rank(latencies, 95),
            prompt_tokens=sum(item.prompt_tokens for item in values),
            completion_tokens=sum(item.completion_tokens for item in values),
            stable_error_counts=tuple(
                StableErrorCount(code=code, count=count)
                for code, count in sorted(errors.items())
            ),
        ),
    )


def _validate_evidence_alignment(
    case: EvaluationCase, prediction: EvaluationPrediction
) -> None:
    expected = {item.probe_id: item for item in case.validation_probes}
    actual = _probe_index(prediction)
    if set(expected) != set(actual):
        raise ValueError("EVALUATION_VALIDATION_PROBE_SET_MISMATCH")
    for probe_id, probe in expected.items():
        outcome = actual[probe_id]
        if (
            probe.kind != outcome.kind
            or probe.subject_ids != outcome.subject_ids
            or (
                outcome.decision == "rejected"
                and outcome.stable_code != probe.expected_rejection_code
            )
        ):
            raise ValueError("EVALUATION_VALIDATION_EVIDENCE_MISMATCH")

    dangling = _validate_graph(
        prediction.frames,
        prediction.references,
        prediction.context_links,
        prediction.slot_mutations,
        allow_dangling=True,
    )
    covered = {
        subject_id
        for outcome in prediction.validation_probe_outcomes
        if outcome.kind == "invalid_context_graph"
        for subject_id in outcome.subject_ids
    }
    if dangling and not dangling <= covered:
        raise ValueError("EVALUATION_VALIDATION_EVIDENCE_MISMATCH")


def _probe_index(prediction: EvaluationPrediction) -> dict[str, ValidationProbeOutcome]:
    return {item.probe_id: item for item in prediction.validation_probe_outcomes}


def _align(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> tuple[tuple[EvaluationCase, EvaluationPrediction], ...]:
    case_index = _unique_index(cases, lambda item: item.case_id)
    prediction_index = _unique_index(predictions, lambda item: item.case_id)
    if set(case_index) != set(prediction_index):
        raise ValueError("EVALUATION_CASE_SET_MISMATCH")
    return tuple(
        (case_index[case_id], prediction_index[case_id])
        for case_id in sorted(case_index)
    )


def _unique_index[T](items: Sequence[T], key: Callable[[T], str]) -> dict[str, T]:
    result = {key(item): item for item in items}
    if len(result) != len(items):
        raise ValueError("EVALUATION_DUPLICATE_CASE_ID")
    return result


def _exact_match[T, U, V](
    aligned: Sequence[tuple[T, U]],
    expected: Callable[[T], V],
    predicted: Callable[[U], V],
) -> CountMetric:
    return CountMetric(
        numerator=sum(expected(case) == predicted(prediction) for case, prediction in aligned),
        denominator=len(aligned),
    )


def _frame_axis(
    frames: Sequence[EvaluationFrame],
    values: Callable[[EvaluationFrame], Iterable[str]],
) -> frozenset[tuple[int, str]]:
    return frozenset(
        (frame.ordinal, value) for frame in frames for value in values(frame)
    )


def _frame_signatures(frames: Sequence[EvaluationFrame]) -> tuple[object, ...]:
    return tuple(
        (
            frame.ordinal,
            frame.action_id,
            frame.product_family_ids,
            frame.entity_type_ids,
            tuple(
                sorted(
                    ((slot.slot_kind, slot.value_ids) for slot in frame.slots),
                    key=lambda item: item[0],
                )
            ),
        )
        for frame in frames
    )


def _reference_signatures(
    references: Sequence[ExpectedReference],
) -> tuple[tuple[int, str, str], ...]:
    return tuple(
        (index, reference.reference_form, reference.status)
        for index, reference in enumerate(references)
    )


def _context_link_signatures(
    frames: Sequence[EvaluationFrame],
    references: Sequence[ExpectedReference],
    links: Sequence[ExpectedContextLink],
    *,
    include_selector: bool,
    include_cardinality: bool,
) -> tuple[object, ...]:
    frame_ordinals = {frame.frame_id: frame.ordinal for frame in frames}
    reference_ordinals = {
        reference.reference_id: index for index, reference in enumerate(references)
    }

    def local_ordinal(identifier: str, values: dict[str, int]) -> object:
        return values.get(identifier, ("unresolved-local-id", identifier))

    signatures = []
    for link in links:
        signature: list[object] = [
            local_ordinal(link.reference_id, reference_ordinals),
            link.link_type,
            link.source_role,
            local_ordinal(link.producer_frame_id, frame_ordinals),
            local_ordinal(link.consumer_frame_id, frame_ordinals),
        ]
        if include_selector:
            signature.append(link.selector)
        if include_cardinality:
            signature.append(link.target_cardinality)
        signatures.append(tuple(signature))
    return tuple(sorted(signatures, key=repr))


def _mutation_signatures(
    frames: Sequence[EvaluationFrame],
    mutations: Sequence[ExpectedSlotMutation],
) -> tuple[object, ...]:
    frame_ordinals = {frame.frame_id: frame.ordinal for frame in frames}

    def local_ordinal(identifier: str | None) -> object:
        if identifier is None:
            return None
        return frame_ordinals.get(identifier, ("unresolved-local-id", identifier))

    return tuple(
        sorted(
            (
                (
                    local_ordinal(mutation.consumer_frame_id),
                    mutation.slot_kind,
                    mutation.mutation_kind,
                    local_ordinal(mutation.source_frame_id),
                )
                for mutation in mutations
            ),
            key=repr,
        )
    )


def _slot_axis(
    frames: Sequence[EvaluationFrame],
) -> frozenset[tuple[int, str, str]]:
    return frozenset(
        (frame.ordinal, slot.slot_kind, value)
        for frame in frames
        for slot in frame.slots
        for value in slot.value_ids
    )


def _micro_prf[T, U, V](
    aligned: Sequence[tuple[T, U]],
    expected: Callable[[T], frozenset[V]],
    predicted: Callable[[U], frozenset[V]],
) -> PrecisionRecallF1:
    true_positive = false_positive = false_negative = 0
    for case, prediction in aligned:
        expected_items = expected(case)
        predicted_items = predicted(prediction)
        true_positive += len(expected_items & predicted_items)
        false_positive += len(predicted_items - expected_items)
        false_negative += len(expected_items - predicted_items)
    return PrecisionRecallF1(
        precision=CountMetric(
            numerator=true_positive, denominator=true_positive + false_positive
        ),
        recall=CountMetric(
            numerator=true_positive, denominator=true_positive + false_negative
        ),
        f1=CountMetric(
            numerator=2 * true_positive,
            denominator=2 * true_positive + false_positive + false_negative,
        ),
    )


def _nearest_rank(values: Sequence[int], percentile: int) -> int | None:
    if not values:
        return None
    index = ceil(Decimal(percentile) * Decimal(len(values)) / Decimal(100)) - 1
    return values[index]


def _validate_frames(frames: Sequence[EvaluationFrame], label: str) -> None:
    _require_unique((frame.frame_id for frame in frames), f"{label} frame IDs")
    if tuple(frame.ordinal for frame in frames) != tuple(range(len(frames))):
        raise ValueError(f"{label} frame ordinals must be contiguous")


def _validate_graph(
    frames: Sequence[EvaluationFrame],
    references: Sequence[ExpectedReference],
    links: Sequence[ExpectedContextLink],
    mutations: Sequence[ExpectedSlotMutation],
    *,
    allow_dangling: bool,
) -> set[str]:
    frame_ordinals = {frame.frame_id: frame.ordinal for frame in frames}
    reference_ids = {reference.reference_id for reference in references}
    dangling: set[str] = set()
    for link in links:
        if link.reference_id not in reference_ids:
            dangling.add(link.reference_id)
        if link.producer_frame_id not in frame_ordinals:
            dangling.add(link.producer_frame_id)
        if link.consumer_frame_id not in frame_ordinals:
            dangling.add(link.consumer_frame_id)
        if (
            link.producer_frame_id in frame_ordinals
            and link.consumer_frame_id in frame_ordinals
            and frame_ordinals[link.producer_frame_id]
            >= frame_ordinals[link.consumer_frame_id]
        ):
            raise ValueError("context links must point from earlier to later frames")
    for mutation in mutations:
        if mutation.consumer_frame_id not in frame_ordinals:
            dangling.add(mutation.consumer_frame_id)
        if mutation.source_frame_id is not None and mutation.source_frame_id not in frame_ordinals:
            dangling.add(mutation.source_frame_id)
    if dangling and not allow_dangling:
        raise ValueError("evaluation context graph contains dangling IDs")
    return dangling


def _require_unique(values: Iterable[str], label: str) -> None:
    materialized = tuple(values)
    if len(set(materialized)) != len(materialized):
        raise ValueError(f"{label} must be unique")


def _require_sorted_unique(values: Iterable[str], label: str) -> None:
    materialized = tuple(values)
    if materialized != tuple(sorted(set(materialized))):
        raise ValueError(f"{label} must be sorted and unique")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_non_json_number() -> Any:
    raise ValueError("non-JSON number")
