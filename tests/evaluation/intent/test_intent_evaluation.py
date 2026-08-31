from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from financial_agent.intent.evaluation import (
    CandidateGroup,
    EvaluationCase,
    EvaluationDataset,
    EvaluationFrame,
    EvaluationPrediction,
    EvaluationProbe,
    EvaluationSegment,
    ExpectedContextLink,
    ExpectedReference,
    ExpectedSlot,
    ExpectedSlotMutation,
    FirstPassSchemaOutcome,
    IntentDraftBundle,
    IntentDraftCaseArtifact,
    PredictionDataset,
    RegressionDataset,
    RepairOutcome,
    ResolverViewBundle,
    ResolverViewCaseArtifact,
    ValidatedResolutionBundle,
    ValidatedResolutionCaseArtifact,
    ValidationProbeOutcome,
    evaluate_candidates,
    evaluate_context,
    evaluate_frames,
    evaluate_ood,
    evaluate_predictions,
    parse_strict_json,
)
from financial_agent.contracts.canonical import build_request_key, canonical_json_bytes
from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.candidates import generate_semantic_candidates
from financial_agent.intent.draft import (
    ActionChoice,
    ContextLinkHint,
    EvidenceSpan,
    IntentFrameDraft,
    IntentResolutionDraft,
    ProductFamilyChoice,
    SemanticFlagHint,
    SlotAssignment,
)
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.resolution import ValidatedIntentResolution
from financial_agent.intent.types import (
    ChoiceState,
    ContextLinkType,
    ResolutionStatus,
    Selector,
    SemanticTag,
    SlotKind,
    SourceRole,
)
from financial_agent.intent.validation import derive_semantic_tags
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    ActiveDatasetPin,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ResolverView,
    build_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGRESSION_PATH = Path(__file__).with_name("intent_resolution_regression.json")
HELDOUT_V1_PATH = Path(__file__).with_name("intent_resolution_heldout_ko.json")
HELDOUT_PATH = Path(__file__).with_name("intent_resolution_heldout_ko_v2.json")
GOLD_PATH = PROJECT_ROOT / "tests" / "gold" / "core_questions.json"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "evaluate_intent_resolver.py"
REGRESSION_SHA256 = "5f917cbd326d4b4a27d260aecaf63460dffa4302dcabd5e9599efe7c90b1b18b"
HELDOUT_V1_SHA256 = "d23eae797026ed66fa2f52ae49a602f991bd9b6d02b890c799342c0a6145f63e"
HELDOUT_SHA256 = "de015673ad4fa327ed3369997120f8465fb9b14e4998a924a8b90eaf45c450fb"


def _frame(
    case_index: int,
    *,
    ordinal: int = 0,
    role: str = "producer",
    correct: bool = True,
) -> EvaluationFrame:
    suffix = str(case_index)
    return EvaluationFrame(
        frame_id=f"{role}-{suffix}",
        ordinal=ordinal,
        action_id="lookup" if correct else "rank",
        product_family_ids=("domestic_etf",) if correct else ("public_fund",),
        entity_type_ids=("ETF",) if correct else ("PublicFund",),
        slots=(
            ExpectedSlot(
                slot_kind="metric",
                value_ids=(f"metric-{suffix}-{ordinal}",)
                if correct
                else (f"wrong-metric-{ordinal}",),
            ),
        ),
    )


def _frames(case_index: int, *, correct: bool = True) -> tuple[EvaluationFrame, ...]:
    return (
        _frame(case_index, ordinal=0, role="producer", correct=correct),
        _frame(case_index, ordinal=1, role="consumer", correct=correct),
    )


def _reference(case_index: int, *, correct: bool = True) -> ExpectedReference:
    return ExpectedReference(
        reference_id=f"reference-{case_index}",
        reference_form="demonstrative" if correct else "bridging",
        status="resolved",
    )


def _link(case_index: int, *, correct: bool = True) -> ExpectedContextLink:
    return ExpectedContextLink(
        context_link_id=f"link-{case_index}",
        reference_id=f"reference-{case_index}",
        link_type="consume_result_set",
        source_role="top_k_products",
        selector="all" if correct else "first",
        producer_frame_id=f"producer-{case_index}",
        consumer_frame_id=f"consumer-{case_index}",
        target_cardinality="many",
    )


def _mutation(case_index: int, *, correct: bool = True) -> ExpectedSlotMutation:
    return ExpectedSlotMutation(
        slot_mutation_id=f"mutation-{case_index}",
        consumer_frame_id=f"consumer-{case_index}",
        slot_kind="metric",
        mutation_kind="carryover" if correct else "delete",
        source_frame_id=f"producer-{case_index}",
    )


def _probes(case_index: int) -> tuple[EvaluationProbe, ...]:
    probes: list[EvaluationProbe] = []
    if case_index < 4:
        probes.append(
            EvaluationProbe(
                probe_id=f"probe-unknown-{case_index}",
                kind="unknown_id",
                subject_ids=(f"unknown:metric-{case_index:03d}",),
                expected_rejection_code="MODEL_UNKNOWN_ID",
            )
        )
    if case_index < 5:
        probes.append(
            EvaluationProbe(
                probe_id=f"probe-graph-{case_index}",
                kind="invalid_context_graph",
                subject_ids=(f"dangling:metric-{case_index:03d}",),
                expected_rejection_code="INVALID_CONTEXT_GRAPH",
            )
        )
    return tuple(probes)


def _synthetic_cases() -> tuple[EvaluationCase, ...]:
    return tuple(
        EvaluationCase(
            case_id=f"metric-{index:03d}",
            category="ood",
            subcategory="vocabulary",
            question=f"합성 질문 {index}",
            segments=(
                EvaluationSegment(
                    segment_id="s1", ordinal=0, text=f"합성 질문 {index}"
                ),
            ),
            expected_candidate_ids=(f"gold-{index}",),
            expected_frames=_frames(index),
            expected_references=(_reference(index),),
            expected_context_links=(_link(index),),
            expected_slot_mutations=(_mutation(index),),
            expected_resolution_status="unmapped",
            expected_tags=(),
            expected_pipeline_outcome="semantic_resolution",
            validation_probes=_probes(index),
            ood_type="vocabulary",
        )
        for index in range(100)
    )


def _synthetic_predictions() -> tuple[EvaluationPrediction, ...]:
    predictions: list[EvaluationPrediction] = []
    for index in range(100):
        if index < 80:
            candidates = (f"gold-{index}", "other-a", "other-b", "other-c")
        elif index < 90:
            candidates = ("other-a", f"gold-{index}", "other-b", "other-c")
        elif index < 99:
            candidates = ("other-a", "other-b", "other-c", f"gold-{index}")
        else:
            candidates = ("other-a", "other-b", "other-c", "other-d")
        frame_correct = index < 90
        context_correct = index < 95
        outcomes = tuple(
            ValidationProbeOutcome(
                probe_id=probe.probe_id,
                kind=probe.kind,
                subject_ids=probe.subject_ids,
                decision=(
                    "accepted"
                    if (probe.kind == "unknown_id" and index == 0)
                    or (probe.kind == "invalid_context_graph" and index == 1)
                    else "rejected"
                ),
                validator_event_code=(
                    "UNKNOWN_ID_ACCEPTED"
                    if probe.kind == "unknown_id" and index == 0
                    else "UNKNOWN_ID_REJECTED"
                    if probe.kind == "unknown_id"
                    else "INVALID_GRAPH_ACCEPTED"
                    if index == 1
                    else "INVALID_GRAPH_REJECTED"
                ),
                stable_code=(
                    "UNKNOWN_ID_ACCEPTED"
                    if probe.kind == "unknown_id" and index == 0
                    else "MODEL_UNKNOWN_ID"
                    if probe.kind == "unknown_id"
                    else "INVALID_GRAPH_ACCEPTED"
                    if index == 1
                    else "INVALID_CONTEXT_GRAPH"
                ),
            )
            for probe in _probes(index)
        )
        predictions.append(
            EvaluationPrediction(
                case_id=f"metric-{index:03d}",
                candidate_groups=(
                    CandidateGroup(mention_id=f"mention-{index}", candidate_ids=candidates),
                ),
                candidate_reproducible=index < 100,
                frames=_frames(index, correct=frame_correct),
                references=(_reference(index, correct=context_correct),),
                context_links=(_link(index, correct=context_correct),),
                slot_mutations=(_mutation(index, correct=context_correct),),
                resolution_status="resolved" if index >= 98 else "unmapped",
                pipeline_outcome="semantic_resolution",
                predicted_ood_type=None if index >= 98 else "vocabulary",
                tags=(),
                blocking_issue_codes=(
                    () if index >= 98 else ("SEMANTIC_CONCEPT_UNMAPPED",)
                ),
                first_pass_schema=FirstPassSchemaOutcome(
                    status="invalid" if index == 99 else "valid",
                    validator_event_code=(
                        "SCHEMA_INVALID" if index == 99 else "SCHEMA_VALID"
                    ),
                ),
                repair=RepairOutcome(
                    status="succeeded" if index < 10 else "not_attempted",
                    validator_event_code=(
                        "REPAIR_SUCCEEDED"
                        if index < 10
                        else "REPAIR_NOT_ATTEMPTED"
                    ),
                ),
                validation_probe_outcomes=outcomes,
                latency_ms=index + 1,
                prompt_tokens=10,
                completion_tokens=5,
                stable_error_codes=(
                    ("MODEL_UNKNOWN_ID",)
                    if index < 2
                    else ("INVALID_CONTEXT_GRAPH",)
                    if index == 2
                    else ()
                ),
            )
        )
    return tuple(predictions)


def test_metrics_keep_candidate_frame_context_and_ood_denominators_separate() -> None:
    cases = _synthetic_cases()
    predictions = _synthetic_predictions()

    candidate = evaluate_candidates(cases, predictions)
    frame = evaluate_frames(cases, predictions)
    context = evaluate_context(cases, predictions)
    ood = evaluate_ood(cases, predictions)
    report = evaluate_predictions(cases, predictions)

    assert candidate.recall_at_1.value == Decimal("0.8")
    assert candidate.recall_at_3.value == Decimal("0.9")
    assert candidate.recall_at_5.value == Decimal("0.99")
    assert candidate.reproducibility.value == Decimal("1")
    assert frame.joint_exact_match.value == Decimal("0.9")
    assert frame.action.f1.value == Decimal("0.9")
    assert frame.product_family.f1.value == Decimal("0.9")
    assert frame.entity_type.f1.value == Decimal("0.9")
    assert frame.slot.f1.value == Decimal("0.9")
    assert context.reference_exact_match.value == Decimal("0.95")
    assert context.link_exact_match.value == Decimal("0.95")
    assert context.selector_exact_match.value == Decimal("0.95")
    assert context.cardinality_exact_match.value == Decimal("1")
    assert context.mutation_exact_match.value == Decimal("0.95")
    assert ood.false_fast_rate.value == Decimal("0.02")
    assert report.validation.schema_validity.value == Decimal("0.99")
    assert report.validation.unknown_id_acceptance.value == Decimal("0.25")
    assert report.validation.invalid_graph_acceptance.value == Decimal("0.2")
    assert report.validation.repair_rate.value == Decimal("0.1")
    assert report.runtime.p50_latency_ms == 50
    assert report.runtime.p95_latency_ms == 95
    assert report.runtime.prompt_tokens == 1000
    assert report.runtime.completion_tokens == 500
    assert [(item.code, item.count) for item in report.runtime.stable_error_counts] == [
        ("INVALID_CONTEXT_GRAPH", 1),
        ("INVALID_GRAPH_ACCEPTED", 1),
        ("MODEL_UNKNOWN_ID", 2),
        ("UNKNOWN_ID_ACCEPTED", 1),
    ]


def test_zero_denominator_policy_is_decimal_zero() -> None:
    candidate = evaluate_candidates((), ())
    frame = evaluate_frames((), ())
    context = evaluate_context((), ())
    ood = evaluate_ood((), ())

    assert candidate.recall_at_5.denominator == 0
    assert candidate.recall_at_5.value == Decimal("0")
    assert frame.joint_exact_match.value == Decimal("0")
    assert context.link_exact_match.value == Decimal("0")
    assert ood.false_fast_rate.value == Decimal("0")


def test_combination_ood_is_confused_separately_but_not_counted_as_false_fast() -> None:
    case_payload = _synthetic_cases()[0].model_dump()
    case_payload["ood_type"] = "combination"
    case_payload["expected_resolution_status"] = "resolved"
    case = EvaluationCase.model_validate(case_payload)
    prediction = _synthetic_predictions()[0].model_copy(
        update={
            "resolution_status": "resolved",
            "predicted_ood_type": None,
            "blocking_issue_codes": (),
        }
    )

    metrics = evaluate_ood((case,), (prediction,))

    assert [
        (item.expected, item.predicted, item.count) for item in metrics.confusion
    ] == [("combination", "fast", 1)]
    assert metrics.false_fast_rate.denominator == 0
    assert metrics.false_fast_rate.value == Decimal("0")


def test_exact_match_canonicalizes_case_local_frame_and_context_ids() -> None:
    case = _synthetic_cases()[0]
    prediction = _synthetic_predictions()[0]
    renamed_frames = (
        prediction.frames[0].model_copy(update={"frame_id": "renamed-producer"}),
        prediction.frames[1].model_copy(update={"frame_id": "renamed-consumer"}),
    )
    renamed_reference = prediction.references[0].model_copy(
        update={"reference_id": "renamed-reference"}
    )
    renamed_link = prediction.context_links[0].model_copy(
        update={
            "context_link_id": "renamed-link",
            "reference_id": "renamed-reference",
            "producer_frame_id": "renamed-producer",
            "consumer_frame_id": "renamed-consumer",
        }
    )
    renamed_mutation = prediction.slot_mutations[0].model_copy(
        update={
            "slot_mutation_id": "renamed-mutation",
            "consumer_frame_id": "renamed-consumer",
            "source_frame_id": "renamed-producer",
        }
    )
    renamed = prediction.model_copy(
        update={
            "frames": renamed_frames,
            "references": (renamed_reference,),
            "context_links": (renamed_link,),
            "slot_mutations": (renamed_mutation,),
        }
    )

    assert evaluate_frames((case,), (renamed,)).joint_exact_match.value == Decimal("1")
    context = evaluate_context((case,), (renamed,))
    assert context.reference_exact_match.value == Decimal("1")
    assert context.link_exact_match.value == Decimal("1")
    assert context.selector_exact_match.value == Decimal("1")
    assert context.cardinality_exact_match.value == Decimal("1")
    assert context.mutation_exact_match.value == Decimal("1")


def test_invalid_graph_attempt_is_counted_without_crashing_context_diagnostics(
) -> None:
    case = _synthetic_cases()[0]
    prediction = _synthetic_predictions()[0]
    invalid_mutation = prediction.slot_mutations[0].model_copy(
        update={
            "slot_mutation_id": "invalid-mutation",
            "consumer_frame_id": "dangling:metric-000",
        }
    )
    outcomes = tuple(
        outcome.model_copy(
            update={
                "decision": "accepted",
                "validator_event_code": "INVALID_GRAPH_ACCEPTED",
                "stable_code": "INVALID_GRAPH_ACCEPTED",
            }
        )
        if outcome.kind == "invalid_context_graph"
        else outcome
        for outcome in prediction.validation_probe_outcomes
    )
    invalid = prediction.model_copy(
        update={
            "slot_mutations": (*prediction.slot_mutations, invalid_mutation),
            "validation_probe_outcomes": outcomes,
        }
    )

    report = evaluate_predictions((case,), (invalid,))

    assert report.context.mutation_exact_match.value == Decimal("0")
    assert report.validation.invalid_graph_acceptance.value == Decimal("1")


def test_evaluation_contracts_reject_unknown_fields_and_misaligned_cases() -> None:
    payload = _synthetic_cases()[0].model_dump(mode="json")
    payload["unknown"] = "must fail"
    with pytest.raises(ValidationError):
        EvaluationCase.model_validate(payload)

    prediction_payload = _synthetic_predictions()[0].model_dump(mode="json")
    prediction_payload["raw_model_response"] = "must fail"
    with pytest.raises(ValidationError):
        EvaluationPrediction.model_validate(prediction_payload)

    with pytest.raises(ValueError, match="EVALUATION_CASE_SET_MISMATCH"):
        evaluate_predictions(_synthetic_cases()[:2], _synthetic_predictions()[:1])


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_regression_fixture_preserves_all_existing_labels_without_question_copy(
) -> None:
    regression = parse_strict_json(REGRESSION_PATH.read_bytes(), RegressionDataset)
    fixture = regression.model_dump(mode="json")
    gold = _load_json(GOLD_PATH)
    fixture_cases = fixture["cases"]
    gold_cases = gold["cases"]
    assert isinstance(fixture_cases, list)
    assert isinstance(gold_cases, list)
    assert len(fixture_cases) == len(gold_cases) == 52
    assert [item["case_id"] for item in fixture_cases] == [
        item["id"] for item in gold_cases
    ]
    assert all("question" not in item for item in fixture_cases)
    for label, source in zip(fixture_cases, gold_cases, strict=True):
        requirements = source["requirements"]
        semantic_ids = sorted(
            {
                *(item["id"] for item in requirements["attributes"]),
                *(item["id"] for item in requirements["metrics"]),
                *(item["predicate"] for item in requirements["relations"]),
                *(item["claim_type"] for item in requirements["document_claims"]),
            }
        )
        assert label["expected_axes"] == {
            "intent_label": source["intent"],
            "product_family_ids": sorted(source["product_families"]),
            "entity_type_ids": sorted(
                {item["type"] for item in requirements["entities"]}
            ),
            "semantic_ids": semantic_ids,
            "expected_disposition": source["expected_disposition"],
        }
        projected_context = [
            {key: value for key, value in item.items() if key != "candidates" or value}
            for item in label["expected_context"]
        ]
        assert projected_context == source["reference_resolution"]


def test_regression_loader_rejects_duplicate_keys_and_unknown_label_fields() -> None:
    duplicate = b'{"schema_version":"1.0","split_id":"a","split_id":"b","cases":[]}'
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_strict_json(duplicate, RegressionDataset)

    payload = parse_strict_json(REGRESSION_PATH.read_bytes(), RegressionDataset).model_dump(
        mode="json"
    )
    payload["cases"][0]["expected_axes"]["unexpected"] = True
    with pytest.raises(ValidationError):
        RegressionDataset.model_validate(payload)


def test_heldout_fixture_has_frozen_distribution_and_safe_synthetic_content() -> None:
    dataset = EvaluationDataset.model_validate_json(HELDOUT_PATH.read_bytes())
    cases = dataset.cases
    assert len(cases) == 160
    assert len({case.case_id for case in cases}) == 160
    assert Counter(case.category for case in cases) == {
        "paraphrase_spacing_particle": 40,
        "compound_no_punctuation_correction": 30,
        "context_resolution": 40,
        "ood": 30,
        "policy_injection_unicode_oversized": 20,
    }
    assert Counter(
        case.subcategory for case in cases if case.category == "context_resolution"
    ) == {
        "demonstrative": 8,
        "ellipsis": 8,
        "plural_singular": 8,
        "former_latter": 8,
        "bridging": 8,
    }
    assert Counter(case.ood_type for case in cases if case.category == "ood") == {
        "vocabulary": 10,
        "domain": 10,
        "context": 10,
    }
    assert Counter(
        case.subcategory
        for case in cases
        if case.category == "policy_injection_unicode_oversized"
    ) == {
        "policy": 5,
        "prompt_injection": 5,
        "unicode": 5,
        "oversized_boundary": 5,
    }
    gold_questions = {item["question"] for item in _load_json(GOLD_PATH)["cases"]}
    assert not gold_questions & {case.question for case in cases}
    forbidden = (
        "KODEX",
        "가람자산운용",
        "캠브리콘",
        "에코프로",
        "고객번호",
    )
    assert all(token not in case.question for case in cases for token in forbidden)
    oversized = [case for case in cases if case.subcategory == "oversized_boundary"]
    assert all(len(case.question) == 4097 for case in oversized)
    assert all(
        case.question == " ".join(segment.text for segment in case.segments)
        for case in cases
    )
    assert all(
        tuple(frame.ordinal for frame in case.expected_frames)
        == tuple(range(len(case.expected_frames)))
        for case in cases
    )
    assert all(
        case.expected_resolution_status != "resolved"
        for case in cases
        if case.ood_type in {"vocabulary", "domain", "context"}
    )
    catalog = load_catalog(PROJECT_ROOT)
    registered_candidates = (
        set(catalog.concepts_by_id)
        | set(catalog.action_ids)
        | set(catalog.product_family_ids)
        | set(catalog.entity_type_ids)
    )
    assert all(
        set(case.expected_candidate_ids) <= registered_candidates for case in cases
    )
    assert all(
        frame.action_id in catalog.action_ids
        and set(frame.product_family_ids) <= set(catalog.product_family_ids)
        and set(frame.entity_type_ids) <= set(catalog.entity_type_ids)
        for case in cases
        for frame in case.expected_frames
    )
    assert all(
        set(case.expected_tags) <= {tag.value for tag in SemanticTag} for case in cases
    )
    for case in cases:
        ordinals = {frame.frame_id: frame.ordinal for frame in case.expected_frames}
        assert all(
            ordinals[link.producer_frame_id] < ordinals[link.consumer_frame_id]
            for link in case.expected_context_links
        )


def test_fixture_hashes_are_literal_and_frozen() -> None:
    assert REGRESSION_SHA256 != "TO_BE_FROZEN"
    assert HELDOUT_V1_SHA256 != "TO_BE_FROZEN"
    assert HELDOUT_SHA256 != "TO_BE_FROZEN"
    assert hashlib.sha256(REGRESSION_PATH.read_bytes()).hexdigest() == REGRESSION_SHA256
    assert (
        hashlib.sha256(HELDOUT_V1_PATH.read_bytes()).hexdigest()
        == HELDOUT_V1_SHA256
    )
    assert hashlib.sha256(HELDOUT_PATH.read_bytes()).hexdigest() == HELDOUT_SHA256


def test_v2_preserves_v1_questions_and_candidate_gold_without_tuning() -> None:
    v1 = _load_json(HELDOUT_V1_PATH)
    v2 = parse_strict_json(HELDOUT_PATH.read_bytes(), EvaluationDataset)
    v1_by_id = {case["case_id"]: case for case in v1["cases"]}

    assert set(v1_by_id) == {case.case_id for case in v2.cases}
    for case in v2.cases:
        assert case.question == v1_by_id[case.case_id]["question"]
        assert list(case.expected_candidate_ids) == v1_by_id[case.case_id][
            "expected_candidate_ids"
        ]


_POLICY_TAGS_BY_CASE = {
    "HKO-NEG-POL-001": (SemanticTag.FUTURE_FORECAST,),
    "HKO-NEG-POL-002": (SemanticTag.PERSONALIZED_ADVICE,),
    "HKO-NEG-POL-003": (SemanticTag.ORDER_EXECUTION,),
    "HKO-NEG-POL-004": (SemanticTag.REALTIME_REQUIRED,),
    "HKO-NEG-POL-005": (
        SemanticTag.FUTURE_FORECAST,
        SemanticTag.PERSONALIZED_ADVICE,
    ),
}


def _tag_draft(case: EvaluationCase) -> IntentResolutionDraft:
    span = EvidenceSpan(
        span_id="span-1",
        segment_id=case.segments[0].segment_id,
        start_char=0,
        end_char=1,
        text=case.question[0],
    )
    frames = tuple(
        IntentFrameDraft(
            frame_id=frame.frame_id,
            ordinal=frame.ordinal,
            segment_ids=(
                case.segments[min(frame.ordinal, len(case.segments) - 1)].segment_id,
            ),
            evidence_span_ids=("span-1",),
            normalized_intent_argument="evaluation",
            action_choice=ActionChoice(
                state=ChoiceState.SELECTED,
                selected_ids=(IntentType(frame.action_id),),
                evidence_span_ids=("span-1",),
                reason_code="explicit",
            ),
            product_family_choice=ProductFamilyChoice(
                state=ChoiceState.SELECTED,
                selected_ids=tuple(ProductFamily(value) for value in frame.product_family_ids),
                evidence_span_ids=("span-1",),
                reason_code="explicit",
            ),
            entity_type_ids=frame.entity_type_ids,
            entity_hint_ids=(),
            slot_assignments=tuple(
                SlotAssignment(
                    slot_assignment_id=f"slot-{frame.ordinal}-{index}",
                    slot_kind=SlotKind(slot.slot_kind),
                    value_ids=slot.value_ids,
                    evidence_span_ids=("span-1",),
                    reason_code="explicit",
                )
                for index, slot in enumerate(frame.slots)
            ),
            produced_result_hints=(),
        )
        for frame in case.expected_frames
    )
    links = tuple(
        ContextLinkHint(
            context_link_id=link.context_link_id,
            reference_id=link.reference_id,
            link_type=ContextLinkType(link.link_type),
            source_role=SourceRole(link.source_role),
            selector=(Selector(link.selector),) if link.selector is not None else (),
            selector_literal_candidate_id=(),
            producer_frame_id=link.producer_frame_id,
            consumer_frame_id=link.consumer_frame_id,
            target_slot_kind=(),
        )
        for link in case.expected_context_links
    )
    flags = tuple(
        SemanticFlagHint(
            semantic_tag=tag,
            evidence_span_ids=("span-1",),
            reason_code="policy_explicit",
        )
        for tag in _POLICY_TAGS_BY_CASE.get(case.case_id, ())
    )
    return IntentResolutionDraft(
        evidence_spans=(span,),
        intent_frames=frames,
        entity_hints=(),
        reference_hints=(),
        context_link_hints=links,
        slot_mutations=(),
        semantic_flag_hints=flags,
        frame_limit_exceeded=False,
    )


def test_v2_tags_match_the_runtime_deterministic_authority_for_all_cases() -> None:
    dataset = parse_strict_json(HELDOUT_PATH.read_bytes(), EvaluationDataset)
    catalog = load_catalog(PROJECT_ROOT)
    for case in dataset.cases:
        if case.expected_pipeline_outcome == "pre_model_rejected":
            assert case.expected_tags == ()
        else:
            assert case.expected_tags == tuple(
                tag.value for tag in derive_semantic_tags(_tag_draft(case), catalog)
            ), case.case_id


def test_v2_compound_dependencies_and_literal_limits_are_independently_adjudicated(
) -> None:
    dataset = parse_strict_json(HELDOUT_PATH.read_bytes(), EvaluationDataset)
    cases = {case.case_id: case for case in dataset.cases}
    dependent = {
        *(f"HKO-CMP-{number:03d}" for number in range(1, 10)),
        *(f"HKO-CMP-{number:03d}" for number in range(22, 31)),
    }
    compound = {
        case.case_id: case
        for case in dataset.cases
        if case.category == "compound_no_punctuation_correction"
    }
    assert len(compound) == 30
    assert {
        case_id for case_id, case in compound.items() if case.expected_context_links
    } == dependent
    for case_id in dependent:
        case = compound[case_id]
        assert len(case.expected_context_links) == 1
        link = case.expected_context_links[0]
        assert (link.producer_frame_id, link.consumer_frame_id) == ("f1", "f2")
        assert any(
            mutation.source_frame_id == link.producer_frame_id
            and mutation.consumer_frame_id == link.consumer_frame_id
            for mutation in case.expected_slot_mutations
        )
        assert "CONTEXT_DEPENDENT" in case.expected_tags
    assert cases["HKO-CMP-001"].expected_context_links[0].source_role == "candidates"
    assert cases["HKO-CMP-028"].expected_context_links[0].source_role == "top_k_products"
    ctx37_slots = {
        slot.slot_kind: slot.value_ids for slot in cases["HKO-CTX-037"].expected_frames[1].slots
    }
    assert ctx37_slots["result_limit"] == ("3",)


def test_v2_oversized_cases_are_pre_model_rejections_not_semantic_ood() -> None:
    dataset = parse_strict_json(HELDOUT_PATH.read_bytes(), EvaluationDataset)
    oversized = [
        case for case in dataset.cases if case.subcategory == "oversized_boundary"
    ]
    assert len(oversized) == 5
    assert all(case.expected_pipeline_outcome == "pre_model_rejected" for case in oversized)
    assert all(case.expected_resolution_status == "unmapped" for case in oversized)
    assert all(
        case.expected_pipeline_outcome == "semantic_resolution"
        for case in dataset.cases
        if case.subcategory != "oversized_boundary"
    )
    prediction = _synthetic_predictions()[99].model_copy(
        update={
            "case_id": oversized[0].case_id,
            "validation_probe_outcomes": tuple(
                ValidationProbeOutcome(
                    probe_id=probe.probe_id,
                    kind=probe.kind,
                    subject_ids=probe.subject_ids,
                    decision="rejected",
                    validator_event_code=(
                        "UNKNOWN_ID_REJECTED"
                        if probe.kind == "unknown_id"
                        else "INVALID_GRAPH_REJECTED"
                    ),
                    stable_code=probe.expected_rejection_code,
                )
                for probe in oversized[0].validation_probes
            ),
            "pipeline_outcome": "semantic_resolution",
        }
    )
    assert (
        evaluate_predictions((oversized[0],), (prediction,))
        .diagnostics.pipeline_outcome_exact.value
        == Decimal("0")
    )


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _report_path(tmp_path: Path, name: str) -> Path:
    path = PROJECT_ROOT / "build" / "reports" / f"pytest-{tmp_path.name}-{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    return path


def test_deterministic_cli_is_reproducible_aggregate_only_and_provenanced(
    tmp_path: Path,
) -> None:
    first = _report_path(tmp_path, "first")
    second = _report_path(tmp_path, "second")
    first_run = _run_cli(
        "--mode",
        "deterministic",
        "--dataset",
        str(HELDOUT_PATH),
        "--output",
        str(first),
    )
    second_run = _run_cli(
        "--mode",
        "deterministic",
        "--dataset",
        str(HELDOUT_PATH),
        "--output",
        str(second),
    )

    assert first_run.returncode == second_run.returncode == 0, first_run.stderr
    assert first.read_bytes() == second.read_bytes()
    report = _load_json(first)
    assert report["mode"] == "deterministic"
    assert report["metrics"]["candidate"] is not None
    assert report["metrics"]["frame"] is None
    assert report["metrics"]["context"] is None
    assert report["metrics"]["ood"] is None
    assert report["provenance"]["catalog_hash"]
    assert report["provenance"]["ontology_hashes"]
    assert report["provenance"]["dataset_sha256"] == HELDOUT_SHA256
    assert report["provenance"]["prompt_version"] is None
    assert report["provenance"]["adapter_version"] is None
    assert report["provenance"]["model_id"] is None
    serialized = first.read_text(encoding="utf-8").lower()
    assert "question" not in serialized
    assert "raw_model" not in serialized
    assert "authorization" not in serialized
    assert "api_key" not in serialized
    assert "queryplan" not in serialized
    assert "sql" not in serialized


def test_cli_refuses_fixture_overwrite_and_live_execution() -> None:
    fixture_result = _run_cli(
        "--mode",
        "deterministic",
        "--dataset",
        str(HELDOUT_PATH),
        "--output",
        str(HELDOUT_PATH),
    )
    live_result = _run_cli(
        "--mode",
        "live",
        "--dataset",
        str(HELDOUT_PATH),
        "--output",
        str(PROJECT_ROOT / "build" / "reports" / "must-not-exist.json"),
    )

    assert fixture_result.returncode == 2
    assert "EVALUATION_FIXTURE_OVERWRITE_REFUSED" in fixture_result.stderr
    assert live_result.returncode == 3
    assert "LIVE_EVALUATION_NOT_AUTHORIZED" in live_result.stderr
    assert not (PROJECT_ROOT / "build" / "reports" / "must-not-exist.json").exists()


def test_cli_refuses_overwriting_a_supplied_dataset(tmp_path: Path) -> None:
    supplied = tmp_path / "supplied-fixture.json"
    supplied.write_bytes(HELDOUT_PATH.read_bytes())

    result = _run_cli(
        "--mode",
        "deterministic",
        "--dataset",
        str(supplied),
        "--output",
        str(supplied),
    )

    assert result.returncode == 2
    assert "EVALUATION_FIXTURE_OVERWRITE_REFUSED" in result.stderr
    assert supplied.read_bytes() == HELDOUT_PATH.read_bytes()


def _stored_artifacts(
    cases: tuple[EvaluationCase, ...],
    manifest: object,
) -> tuple[ResolverViewBundle, IntentDraftBundle, ValidatedResolutionBundle]:
    dataset_version = "synthetic-dataset-v2"
    dataset_manifest_hash = "d" * 64
    view = ResolverView(
        build_manifest=manifest,
        active_dataset_pin=ActiveDatasetPin(
            dataset_version=dataset_version,
            manifest_hash=dataset_manifest_hash,
        ),
        product_family_ids=(),
        action_ids=(),
        semantic_candidates=(),
        concept_definitions=(),
        relation_definitions=(),
        literal_candidates=(),
        entity_candidates=(),
    )
    draft = IntentResolutionDraft(
        evidence_spans=(),
        intent_frames=(),
        entity_hints=(),
        reference_hints=(),
        context_link_hints=(),
        slot_mutations=(),
        semantic_flag_hints=(),
        frame_limit_exceeded=False,
    )
    resolutions = tuple(
        ValidatedResolutionCaseArtifact(
            case_id=case.case_id,
            artifact=ValidatedIntentResolution(
                request_key="1" * 64,
                run_id=f"run-{case.case_id}",
                dataset_version=dataset_version,
                producer="evaluation-test",
                created_at=datetime(2026, 8, 31, tzinfo=UTC),
                resolution_id=f"resolution-{case.case_id}",
                draft_hash="e" * 64,
                canonical_frames=(),
                context_links=(),
                final_tags=(),
                resolution_status=ResolutionStatus.UNMAPPED,
                issues=(),
                validation_events=(),
                build_manifest=manifest,
                active_dataset_manifest_hash=dataset_manifest_hash,
                repair_used=False,
                invalid_attempt_hashes=(),
            ),
        )
        for case in cases
    )
    return (
        ResolverViewBundle(
            dataset_id="synthetic-cli",
            cases=tuple(
                ResolverViewCaseArtifact(case_id=case.case_id, artifact=view)
                for case in cases
            ),
        ),
        IntentDraftBundle(
            dataset_id="synthetic-cli",
            cases=tuple(
                IntentDraftCaseArtifact(case_id=case.case_id, artifact=draft)
                for case in cases
            ),
        ),
        ValidatedResolutionBundle(
            dataset_id="synthetic-cli", cases=resolutions
        ),
    )


def _write_contract(path: Path, value: object) -> bytes:
    payload = canonical_json_bytes(value) + b"\n"
    path.write_bytes(payload)
    return payload


def test_stored_modes_bind_dataset_predictions_and_real_strict_sidecars(
    tmp_path: Path,
) -> None:
    cases = _synthetic_cases()[:2]
    predictions = _synthetic_predictions()[:2]
    dataset = EvaluationDataset(split_id="synthetic-cli", cases=cases)
    dataset_path = tmp_path / "dataset.json"
    dataset_bytes = _write_contract(dataset_path, dataset)
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
    view_bundle, draft_bundle, resolution_bundle = _stored_artifacts(cases, manifest)
    view_path = tmp_path / "views.json"
    draft_path = tmp_path / "drafts.json"
    resolution_path = tmp_path / "resolutions.json"
    view_raw = _write_contract(view_path, view_bundle)
    draft_raw = _write_contract(draft_path, draft_bundle)
    resolution_raw = _write_contract(resolution_path, resolution_bundle)
    sidecar_values = {
        "bounded_view_bundle_raw_sha256": hashlib.sha256(view_raw).hexdigest(),
        "bounded_view_bundle_canonical_sha256": hashlib.sha256(
            canonical_json_bytes(view_bundle)
        ).hexdigest(),
        "draft_bundle_raw_sha256": hashlib.sha256(draft_raw).hexdigest(),
        "draft_bundle_canonical_sha256": hashlib.sha256(
            canonical_json_bytes(draft_bundle)
        ).hexdigest(),
        "resolution_bundle_raw_sha256": hashlib.sha256(resolution_raw).hexdigest(),
        "resolution_bundle_canonical_sha256": hashlib.sha256(
            canonical_json_bytes(resolution_bundle)
        ).hexdigest(),
    }
    for mode in ("decoupled", "full"):
        bundle = PredictionDataset(
            mode=mode,
            dataset_id="synthetic-cli",
            evaluation_dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
            dataset_version="synthetic-dataset-v2",
            dataset_manifest_hash="d" * 64,
            build_manifest=manifest,
            model_id="stored-model-v2",
            bounded_view_bundle_raw_sha256=(
                sidecar_values["bounded_view_bundle_raw_sha256"]
                if mode == "decoupled"
                else None
            ),
            bounded_view_bundle_canonical_sha256=(
                sidecar_values["bounded_view_bundle_canonical_sha256"]
                if mode == "decoupled"
                else None
            ),
            draft_bundle_raw_sha256=(
                sidecar_values["draft_bundle_raw_sha256"]
                if mode == "decoupled"
                else None
            ),
            draft_bundle_canonical_sha256=(
                sidecar_values["draft_bundle_canonical_sha256"]
                if mode == "decoupled"
                else None
            ),
            resolution_bundle_raw_sha256=(
                sidecar_values["resolution_bundle_raw_sha256"]
                if mode == "full"
                else None
            ),
            resolution_bundle_canonical_sha256=(
                sidecar_values["resolution_bundle_canonical_sha256"]
                if mode == "full"
                else None
            ),
            predictions=predictions,
        )
        predictions_path = tmp_path / f"{mode}-predictions.json"
        prediction_raw = _write_contract(predictions_path, bundle)
        output = _report_path(tmp_path, f"{mode}-report")
        arguments = [
            "--mode",
            mode,
            "--dataset",
            str(dataset_path),
            "--predictions",
            str(predictions_path),
            "--output",
            str(output),
        ]
        if mode == "decoupled":
            arguments.extend(
                ["--bounded-views", str(view_path), "--drafts", str(draft_path)]
            )
        else:
            arguments.extend(["--resolutions", str(resolution_path)])
        result = _run_cli(*arguments)
        assert result.returncode == 0, result.stderr
        report = _load_json(output)
        assert report["mode"] == mode
        assert report["provenance"]["prompt_version"] == PROMPT_VERSION
        assert report["provenance"]["adapter_version"] == ADAPTER_VERSION
        assert report["provenance"]["model_id"] == "stored-model-v2"
        assert report["provenance"]["dataset_version"] == "synthetic-dataset-v2"
        assert report["provenance"]["dataset_manifest_hash"] == "d" * 64
        assert report["provenance"]["prediction_bundle_sha256"] == hashlib.sha256(
            prediction_raw
        ).hexdigest()
        assert report["provenance"]["producer_manifest_matches_current"] is True

    missing_sidecars = _run_cli(
        "--mode", "decoupled",
        "--dataset",
        str(dataset_path),
        "--predictions",
        str(tmp_path / "decoupled-predictions.json"),
        "--output",
        str(_report_path(tmp_path, "missing-sidecars")),
    )
    assert missing_sidecars.returncode == 2
    assert "EVALUATION_MODE_ARGUMENT_INVALID" in missing_sidecars.stderr

    original = view_path.read_bytes()
    view_path.write_bytes(original + b"\n")
    tampered = _run_cli(
        "--mode", "decoupled",
        "--dataset", str(dataset_path),
        "--predictions", str(tmp_path / "decoupled-predictions.json"),
        "--bounded-views", str(view_path),
        "--drafts", str(draft_path),
        "--output", str(_report_path(tmp_path, "tampered-sidecar")),
    )
    assert tampered.returncode == 2
    assert "EVALUATION_EVIDENCE_HASH_MISMATCH" in tampered.stderr
    view_path.write_bytes(original)

    original_full_report = _load_json(
        PROJECT_ROOT
        / "build"
        / "reports"
        / f"pytest-{tmp_path.name}-full-report.json"
    )
    changed_prediction = predictions[0].model_copy(update={"completion_tokens": 6})
    changed_bundle = bundle.model_copy(
        update={"predictions": (changed_prediction, *predictions[1:])}
    )
    changed_path = tmp_path / "changed-full-predictions.json"
    changed_raw = _write_contract(changed_path, changed_bundle)
    changed_output = _report_path(tmp_path, "changed-full-report")
    changed_result = _run_cli(
        "--mode", "full",
        "--dataset", str(dataset_path),
        "--predictions", str(changed_path),
        "--resolutions", str(resolution_path),
        "--output", str(changed_output),
    )
    assert changed_result.returncode == 0, changed_result.stderr
    changed_report = _load_json(changed_output)
    assert changed_report["provenance"]["prediction_bundle_sha256"] == hashlib.sha256(
        changed_raw
    ).hexdigest()
    assert changed_report["provenance"]["prediction_bundle_sha256"] != original_full_report[
        "provenance"
    ]["prediction_bundle_sha256"]

    dataset_path.write_bytes(dataset_bytes + b"\n")
    repacked_dataset = _run_cli(
        "--mode", "full",
        "--dataset", str(dataset_path),
        "--predictions", str(tmp_path / "full-predictions.json"),
        "--resolutions", str(resolution_path),
        "--output", str(_report_path(tmp_path, "repacked-dataset")),
    )
    assert repacked_dataset.returncode == 2
    assert "EVALUATION_INPUT_MISMATCH" in repacked_dataset.stderr
    dataset_path.write_bytes(dataset_bytes)

    wrong_manifest = manifest.model_copy(update={"normalizer_version": "wrong-v1"})
    wrong_manifest_bundle = bundle.model_copy(update={"build_manifest": wrong_manifest})
    wrong_manifest_path = tmp_path / "wrong-manifest-predictions.json"
    _write_contract(wrong_manifest_path, wrong_manifest_bundle)
    wrong_manifest_result = _run_cli(
        "--mode", "full",
        "--dataset", str(dataset_path),
        "--predictions", str(wrong_manifest_path),
        "--resolutions", str(resolution_path),
        "--output", str(_report_path(tmp_path, "wrong-manifest")),
    )
    assert wrong_manifest_result.returncode == 2
    assert "EVALUATION_INPUT_MISMATCH" in wrong_manifest_result.stderr


def test_review_red_candidate_recall_keeps_later_mention_top_k() -> None:
    case = _synthetic_cases()[0].model_copy(
        update={"expected_candidate_ids": ("second-mention-gold",)}
    )
    prediction = _synthetic_predictions()[0].model_copy(
        update={
            "candidate_groups": (
                CandidateGroup(
                    mention_id="first-mention",
                    candidate_ids=(
                        "first-a",
                        "first-b",
                        "first-c",
                        "first-d",
                        "first-e",
                    ),
                ),
                CandidateGroup(
                    mention_id="second-mention",
                    candidate_ids=("second-mention-gold",),
                ),
            )
        }
    )

    assert evaluate_candidates((case,), (prediction,)).recall_at_5.value == Decimal("1")


def test_hko_ctx_010_later_mention_is_included_in_mention_group_recall() -> None:
    dataset = parse_strict_json(HELDOUT_PATH.read_bytes(), EvaluationDataset)
    case = next(case for case in dataset.cases if case.case_id == "HKO-CTX-010")
    created_at = datetime(2026, 8, 31, tzinfo=UTC)
    context = RequestContext(
        request_key=build_request_key(
            case.case_id, case.question, "synthetic-intent-eval-v2", "1.0"
        ),
        run_id="eval-HKO-CTX-010",
        dataset_version="synthetic-intent-eval-v2",
        producer="evaluation-test",
        created_at=created_at,
        question_id=case.case_id,
        question=case.question,
        segments=tuple(
            Segment(
                segment_id=segment.segment_id,
                ordinal=segment.ordinal,
                text=segment.text,
            )
            for segment in case.segments
        ),
        deadline_at=created_at + timedelta(seconds=10),
    )
    generated = generate_semantic_candidates(
        normalize_request(context), load_catalog(PROJECT_ROOT)
    )
    groups = tuple(
        CandidateGroup(
            mention_id=group.mention.mention_id,
            candidate_ids=tuple(item.semantic_id for item in group.items),
        )
        for group in generated.by_mention
    )
    prediction = _synthetic_predictions()[0].model_copy(
        update={"case_id": case.case_id, "candidate_groups": groups}
    )
    flattened_unique = tuple(
        dict.fromkeys(
            candidate_id for group in groups for candidate_id in group.candidate_ids
        )
    )

    assert "product_risk_grade" not in flattened_unique[:5]
    recall = evaluate_candidates((case,), (prediction,)).recall_at_5
    assert (recall.numerator, recall.denominator) == (2, 2)


def test_review_red_frame_joint_em_canonicalizes_semantic_sets() -> None:
    gold = EvaluationFrame(
        frame_id="gold",
        ordinal=0,
        action_id="compare",
        product_family_ids=("domestic_etf", "overseas_etf"),
        entity_type_ids=("ETF", "FinancialProduct"),
        slots=(
            ExpectedSlot(slot_kind="metric", value_ids=("aum", "return_1y")),
            ExpectedSlot(slot_kind="period", value_ids=("P1Y",)),
        ),
    )
    reordered = EvaluationFrame(
        frame_id="predicted",
        ordinal=0,
        action_id="compare",
        product_family_ids=("domestic_etf", "overseas_etf"),
        entity_type_ids=("ETF", "FinancialProduct"),
        slots=(
            ExpectedSlot(slot_kind="period", value_ids=("P1Y",)),
            ExpectedSlot(slot_kind="metric", value_ids=("aum", "return_1y")),
        ),
    )
    case = _synthetic_cases()[0].model_copy(update={"expected_frames": (gold,)})
    prediction = _synthetic_predictions()[0].model_copy(update={"frames": (reordered,)})

    assert evaluate_frames((case,), (prediction,)).joint_exact_match.value == Decimal("1")


def test_review_red_frame_contract_rejects_duplicate_semantics() -> None:
    with pytest.raises(ValidationError):
        EvaluationFrame(
            frame_id="duplicate",
            ordinal=0,
            action_id="lookup",
            product_family_ids=("domestic_etf", "domestic_etf"),
            entity_type_ids=("ETF",),
            slots=(
                ExpectedSlot(slot_kind="metric", value_ids=("aum",)),
                ExpectedSlot(slot_kind="metric", value_ids=("return_1y",)),
            ),
        )


def test_review_red_safety_cannot_be_hidden_by_omitting_typed_probe_outcomes() -> None:
    case = _synthetic_cases()[0]
    prediction = _synthetic_predictions()[0]
    spoofed_frame = prediction.frames[0].model_copy(
        update={
            "slots": (
                ExpectedSlot(
                    slot_kind="metric", value_ids=("unknown:metric-000",)
                ),
            )
        }
    )
    spoofed_mutation = prediction.slot_mutations[0].model_copy(
        update={"consumer_frame_id": "dangling:metric-000"}
    )
    spoofed = prediction.model_copy(
        update={
            "frames": (spoofed_frame, *prediction.frames[1:]),
            "slot_mutations": (spoofed_mutation,),
            "validation_probe_outcomes": (),
        }
    )

    with pytest.raises(ValueError, match="EVALUATION_VALIDATION_PROBE_SET_MISMATCH"):
        evaluate_predictions((case,), (spoofed,))


def test_probe_contract_rejects_missing_extra_mismatched_and_contradictory_evidence(
) -> None:
    case = _synthetic_cases()[0]
    prediction = _synthetic_predictions()[0]
    with pytest.raises(ValueError, match="EVALUATION_VALIDATION_PROBE_SET_MISMATCH"):
        evaluate_predictions(
            (case,),
            (prediction.model_copy(update={"validation_probe_outcomes": ()}),),
        )
    mismatched = prediction.validation_probe_outcomes[0].model_copy(
        update={"kind": "invalid_context_graph"}
    )
    with pytest.raises(ValueError, match="EVALUATION_VALIDATION_EVIDENCE_MISMATCH"):
        evaluate_predictions(
            (case,),
            (
                prediction.model_copy(
                    update={
                        "validation_probe_outcomes": (
                            mismatched,
                            *prediction.validation_probe_outcomes[1:],
                        )
                    }
                ),
            ),
        )
    with pytest.raises(ValidationError, match="contradicts validator evidence"):
        ValidationProbeOutcome(
            probe_id="probe",
            kind="unknown_id",
            subject_ids=("unknown:id",),
            decision="rejected",
            validator_event_code="UNKNOWN_ID_ACCEPTED",
            stable_code="MODEL_UNKNOWN_ID",
        )
    with pytest.raises(ValidationError, match="contradicts validator event"):
        FirstPassSchemaOutcome(status="valid", validator_event_code="SCHEMA_INVALID")
    with pytest.raises(ValidationError, match="contradicts validator event"):
        RepairOutcome(status="failed", validator_event_code="REPAIR_SUCCEEDED")


def test_candidate_and_frame_contracts_reject_duplicate_groups_values_and_ordinals(
) -> None:
    prediction_payload = _synthetic_predictions()[0].model_dump(mode="json")
    prediction_payload["candidate_groups"] = [
        {"mention_id": "same", "candidate_ids": ["a", "a"]},
        {"mention_id": "same", "candidate_ids": ["b"]},
    ]
    with pytest.raises(ValidationError):
        EvaluationPrediction.model_validate_json(json.dumps(prediction_payload))

    frame_payload = _synthetic_predictions()[0].model_dump(mode="json")
    frame_payload["frames"][1]["ordinal"] = 3
    with pytest.raises(ValidationError, match="frame ordinals must be contiguous"):
        EvaluationPrediction.model_validate_json(json.dumps(frame_payload))


def test_review_red_zero_denominator_is_not_promotion_evidence() -> None:
    metric = evaluate_predictions((), ()).validation.unknown_id_acceptance

    assert metric.value == Decimal("0")
    assert metric.defined is False
    assert metric.evidence_sufficient is False


def test_review_red_status_tags_and_pipeline_outcome_are_scored() -> None:
    case = _synthetic_cases()[0].model_copy(
        update={"expected_tags": ("CONTEXT_DEPENDENT", "MULTI_STEP")}
    )
    wrong = _synthetic_predictions()[0].model_copy(
        update={"resolution_status": "resolved", "tags": ("MULTI_STEP",)}
    )
    report = evaluate_predictions((case,), (wrong,))

    assert report.diagnostics.resolution_status_exact.value == Decimal("0")
    assert report.diagnostics.tags_exact.value == Decimal("0")
    assert report.diagnostics.tags.precision.value == Decimal("1")
    assert report.diagnostics.tags.recall.value == Decimal("0.5")
    assert report.diagnostics.tags.f1.value == Decimal(2) / Decimal(3)
    assert report.diagnostics.pipeline_outcome_exact.value == Decimal("1")


def test_review_red_cli_rejects_output_outside_build_reports(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"

    result = _run_cli(
        "--mode",
        "deterministic",
        "--dataset",
        str(HELDOUT_PATH),
        "--output",
        str(outside),
    )

    assert result.returncode == 2
    assert "EVALUATION_OUTPUT_PATH_INVALID" in result.stderr
    assert not outside.exists()


def test_cli_rejects_gold_sidecar_and_symlink_output_escapes(tmp_path: Path) -> None:
    gold_hash = hashlib.sha256(GOLD_PATH.read_bytes()).hexdigest()
    gold_result = _run_cli(
        "--mode", "deterministic",
        "--dataset", str(HELDOUT_PATH),
        "--output", str(GOLD_PATH),
    )
    assert gold_result.returncode == 2
    assert "EVALUATION_OUTPUT_PATH_INVALID" in gold_result.stderr
    assert hashlib.sha256(GOLD_PATH.read_bytes()).hexdigest() == gold_hash

    report_dir = PROJECT_ROOT / "build" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside-target.json"
    file_link = report_dir / f"pytest-{tmp_path.name}-file-link.json"
    file_link.unlink(missing_ok=True)
    file_link.symlink_to(target)
    symlink_result = _run_cli(
        "--mode", "deterministic",
        "--dataset", str(HELDOUT_PATH),
        "--output", str(file_link),
    )
    assert symlink_result.returncode == 2
    assert "EVALUATION_OUTPUT_PATH_INVALID" in symlink_result.stderr
    assert not target.exists()
    file_link.unlink()

    directory_link = report_dir / f"pytest-{tmp_path.name}-dir-link"
    directory_link.unlink(missing_ok=True)
    directory_link.symlink_to(tmp_path, target_is_directory=True)
    parent_escape = _run_cli(
        "--mode", "deterministic",
        "--dataset", str(HELDOUT_PATH),
        "--output", str(directory_link / "escaped.json"),
    )
    assert parent_escape.returncode == 2
    assert "EVALUATION_OUTPUT_PATH_INVALID" in parent_escape.stderr
    assert not (tmp_path / "escaped.json").exists()
    directory_link.unlink()

    protected_sidecar = _report_path(tmp_path, "protected-predictions")
    protected_sidecar.write_text("{}\n", encoding="utf-8")
    resolution_sidecar = tmp_path / "resolution.json"
    resolution_sidecar.write_text("{}\n", encoding="utf-8")
    sidecar_result = _run_cli(
        "--mode", "full",
        "--dataset", str(HELDOUT_PATH),
        "--predictions", str(protected_sidecar),
        "--resolutions", str(resolution_sidecar),
        "--output", str(protected_sidecar),
    )
    assert sidecar_result.returncode == 2
    assert "EVALUATION_FIXTURE_OVERWRITE_REFUSED" in sidecar_result.stderr
    assert protected_sidecar.read_text(encoding="utf-8") == "{}\n"

    protected_resolution = _report_path(tmp_path, "protected-resolution")
    protected_view = _report_path(tmp_path, "protected-view")
    protected_draft = _report_path(tmp_path, "protected-draft")
    for path in (protected_resolution, protected_view, protected_draft):
        path.write_text("{}\n", encoding="utf-8")
    protected_runs = (
        _run_cli(
            "--mode", "full",
            "--dataset", str(HELDOUT_PATH),
            "--predictions", str(tmp_path / "prediction.json"),
            "--resolutions", str(protected_resolution),
            "--output", str(protected_resolution),
        ),
        _run_cli(
            "--mode", "decoupled",
            "--dataset", str(HELDOUT_PATH),
            "--predictions", str(tmp_path / "prediction.json"),
            "--bounded-views", str(protected_view),
            "--drafts", str(tmp_path / "draft.json"),
            "--output", str(protected_view),
        ),
        _run_cli(
            "--mode", "decoupled",
            "--dataset", str(HELDOUT_PATH),
            "--predictions", str(tmp_path / "prediction.json"),
            "--bounded-views", str(tmp_path / "view.json"),
            "--drafts", str(protected_draft),
            "--output", str(protected_draft),
        ),
    )
    assert all(result.returncode == 2 for result in protected_runs)
    assert all(
        "EVALUATION_FIXTURE_OVERWRITE_REFUSED" in result.stderr
        for result in protected_runs
    )
    assert all(
        path.read_text(encoding="utf-8") == "{}\n"
        for path in (protected_resolution, protected_view, protected_draft)
    )


def test_cli_enforces_exact_mode_specific_arguments(tmp_path: Path) -> None:
    output = _report_path(tmp_path, "mode-arguments")
    deterministic_extra = _run_cli(
        "--mode", "deterministic",
        "--dataset", str(HELDOUT_PATH),
        "--predictions", str(tmp_path / "predictions.json"),
        "--output", str(output),
    )
    full_missing = _run_cli(
        "--mode", "full",
        "--dataset", str(HELDOUT_PATH),
        "--predictions", str(tmp_path / "predictions.json"),
        "--output", str(output),
    )
    full_extra = _run_cli(
        "--mode", "full",
        "--dataset", str(HELDOUT_PATH),
        "--predictions", str(tmp_path / "predictions.json"),
        "--resolutions", str(tmp_path / "resolutions.json"),
        "--drafts", str(tmp_path / "drafts.json"),
        "--output", str(output),
    )
    for result in (deterministic_extra, full_missing, full_extra):
        assert result.returncode == 2
        assert "EVALUATION_MODE_ARGUMENT_INVALID" in result.stderr
