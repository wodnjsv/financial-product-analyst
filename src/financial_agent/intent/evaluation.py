"""Data-neutral, deterministic metrics for offline intent-resolver evaluation.

This module intentionally knows no fixture paths and imports no evaluation data.
Callers supply strict case and prediction contracts at the offline boundary.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from math import ceil
from typing import Literal

from pydantic import Field, computed_field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex

from .resolution import ResolverBuildManifest


ResolutionStatusLabel = Literal[
    "resolved", "ambiguous", "unmapped", "context_unresolved"
]
OodType = Literal["combination", "vocabulary", "domain", "context"]
EvaluationMode = Literal["decoupled", "full"]
_FALSE_FAST_OOD_TYPES = frozenset({"vocabulary", "domain", "context"})


class EvaluationSegment(ContractModel):
    segment_id: Identifier
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)


class ExpectedSlot(ContractModel):
    slot_kind: Identifier
    value_ids: tuple[Identifier, ...]


class EvaluationFrame(ContractModel):
    frame_id: Identifier
    ordinal: int = Field(ge=0)
    action_id: Identifier
    product_family_ids: tuple[Identifier, ...]
    entity_type_ids: tuple[Identifier, ...]
    slots: tuple[ExpectedSlot, ...]


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
    ood_type: OodType | None = None

    @model_validator(mode="after")
    def validate_case(self) -> "EvaluationCase":
        if tuple(segment.ordinal for segment in self.segments) != tuple(
            range(len(self.segments))
        ):
            raise ValueError("evaluation segment ordinals must be contiguous")
        if self.question != " ".join(segment.text for segment in self.segments):
            raise ValueError("evaluation question must preserve ordered segment text")
        if tuple(frame.ordinal for frame in self.expected_frames) != tuple(
            range(len(self.expected_frames))
        ):
            raise ValueError("evaluation frame ordinals must be contiguous")
        _require_unique(self.expected_candidate_ids, "expected candidate IDs")
        _require_unique(
            (frame.frame_id for frame in self.expected_frames), "expected frame IDs"
        )
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
        _require_unique(self.expected_tags, "expected tags")
        return self


class EvaluationDataset(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    split_id: Identifier
    cases: tuple[EvaluationCase, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "EvaluationDataset":
        _require_unique((case.case_id for case in self.cases), "evaluation case IDs")
        return self


class EvaluationPrediction(ContractModel):
    case_id: Identifier
    candidate_ids: tuple[Identifier, ...]
    candidate_reproducible: bool
    frames: tuple[EvaluationFrame, ...]
    references: tuple[ExpectedReference, ...]
    context_links: tuple[ExpectedContextLink, ...]
    slot_mutations: tuple[ExpectedSlotMutation, ...]
    resolution_status: ResolutionStatusLabel
    predicted_ood_type: OodType | None = None
    tags: tuple[Identifier, ...]
    blocking_issue_codes: tuple[Identifier, ...]
    schema_valid: bool
    unknown_id_attempted: bool
    unknown_id_accepted: bool
    invalid_graph_attempted: bool
    invalid_graph_accepted: bool
    repair_attempted: bool
    latency_ms: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    stable_error_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_prediction(self) -> "EvaluationPrediction":
        _require_unique(self.candidate_ids, "prediction candidate IDs")
        _require_unique(
            (frame.frame_id for frame in self.frames), "prediction frame IDs"
        )
        if self.unknown_id_accepted and not self.unknown_id_attempted:
            raise ValueError("unknown ID acceptance requires an attempt")
        if self.invalid_graph_accepted and not self.invalid_graph_attempted:
            raise ValueError("invalid graph acceptance requires an attempt")
        return self


class PredictionDataset(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: EvaluationMode
    dataset_id: Identifier
    dataset_version: Identifier
    dataset_manifest_hash: Sha256Hex
    build_manifest: ResolverBuildManifest
    model_id: Identifier
    bounded_view_hash: Sha256Hex | None = None
    draft_hash: Sha256Hex | None = None
    resolution_hash: Sha256Hex | None = None
    predictions: tuple[EvaluationPrediction, ...]

    @model_validator(mode="after")
    def validate_mode_evidence(self) -> "PredictionDataset":
        if self.mode == "decoupled":
            if self.bounded_view_hash is None or self.draft_hash is None:
                raise ValueError("decoupled predictions require view and draft hashes")
            if self.resolution_hash is not None:
                raise ValueError("decoupled predictions cannot carry a resolution hash")
        elif (
            self.resolution_hash is None
            or self.bounded_view_hash is not None
            or self.draft_hash is not None
        ):
            raise ValueError("full predictions require only a resolution hash")
        _require_unique(
            (prediction.case_id for prediction in self.predictions),
            "prediction case IDs",
        )
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
        """Return exact decimal ratio; an undefined zero denominator is policy-zero."""
        if self.denominator == 0:
            return Decimal("0")
        return Decimal(self.numerator) / Decimal(self.denominator)


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


def evaluate_candidates(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> CandidateMetrics:
    aligned = _align(cases, predictions)
    total_gold = sum(len(case.expected_candidate_ids) for case, _ in aligned)

    def recall_at(limit: int) -> CountMetric:
        hits = sum(
            len(
                set(case.expected_candidate_ids)
                & set(prediction.candidate_ids[:limit])
            )
            for case, prediction in aligned
        )
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
            lambda case: _frame_axis(
                case.expected_frames, lambda frame: (frame.action_id,)
            ),
            lambda prediction: _frame_axis(
                prediction.frames, lambda frame: (frame.action_id,)
            ),
        ),
        product_family=_micro_prf(
            aligned,
            lambda case: _frame_axis(
                case.expected_frames, lambda frame: frame.product_family_ids
            ),
            lambda prediction: _frame_axis(
                prediction.frames, lambda frame: frame.product_family_ids
            ),
        ),
        entity_type=_micro_prf(
            aligned,
            lambda case: _frame_axis(
                case.expected_frames, lambda frame: frame.entity_type_ids
            ),
            lambda prediction: _frame_axis(
                prediction.frames, lambda frame: frame.entity_type_ids
            ),
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
            lambda case: _mutation_signatures(
                case.expected_frames, case.expected_slot_mutations
            ),
            lambda prediction: _mutation_signatures(
                prediction.frames, prediction.slot_mutations
            ),
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
            if prediction.resolution_status == "resolved"
            and not prediction.blocking_issue_codes
            else prediction.predicted_ood_type or prediction.resolution_status
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
    prediction_values = tuple(prediction for _, prediction in aligned)
    unknown_attempts = sum(item.unknown_id_attempted for item in prediction_values)
    invalid_graph_attempts = sum(
        item.invalid_graph_attempted for item in prediction_values
    )
    errors = Counter(
        item.stable_error_code
        for item in prediction_values
        if item.stable_error_code is not None
    )
    latencies = tuple(sorted(item.latency_ms for item in prediction_values))
    return EvaluationReport(
        candidate=evaluate_candidates(cases, predictions),
        frame=evaluate_frames(cases, predictions),
        context=evaluate_context(cases, predictions),
        ood=evaluate_ood(cases, predictions),
        validation=ValidationMetrics(
            schema_validity=CountMetric(
                numerator=sum(item.schema_valid for item in prediction_values),
                denominator=len(prediction_values),
            ),
            unknown_id_acceptance=CountMetric(
                numerator=sum(item.unknown_id_accepted for item in prediction_values),
                denominator=unknown_attempts,
            ),
            invalid_graph_acceptance=CountMetric(
                numerator=sum(
                    item.invalid_graph_accepted for item in prediction_values
                ),
                denominator=invalid_graph_attempts,
            ),
            repair_rate=CountMetric(
                numerator=sum(item.repair_attempted for item in prediction_values),
                denominator=len(prediction_values),
            ),
        ),
        runtime=RuntimeMetrics(
            p50_latency_ms=_nearest_rank(latencies, 50),
            p95_latency_ms=_nearest_rank(latencies, 95),
            prompt_tokens=sum(item.prompt_tokens for item in prediction_values),
            completion_tokens=sum(item.completion_tokens for item in prediction_values),
            stable_error_counts=tuple(
                StableErrorCount(code=code, count=count)
                for code, count in sorted(errors.items())
            ),
        ),
    )


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
        numerator=sum(
            expected(case) == predicted(prediction)
            for case, prediction in aligned
        ),
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
            tuple((slot.slot_kind, slot.value_ids) for slot in frame.slots),
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


def _require_unique(values: Iterable[str], label: str) -> None:
    materialized = tuple(values)
    if len(set(materialized)) != len(materialized):
        raise ValueError(f"{label} must be unique")
