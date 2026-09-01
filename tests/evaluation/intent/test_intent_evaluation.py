from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import runpy
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
    IntentRunTrace,
    IntentRunTraceBundle,
    AttemptTrace,
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
    replay_validation_probes,
)
from financial_agent.contracts.canonical import (
    build_request_key,
    canonical_json_bytes,
    canonical_sha256,
)
from financial_agent.contracts.enums import (
    Cardinality,
    IntentType,
    ProductFamily,
    ReferenceMentionType,
)
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.candidates import generate_semantic_candidates
from financial_agent.intent.draft import (
    ActionChoice,
    ContextLinkHint,
    EvidenceSpan,
    IntentFrameDraft,
    IntentResolutionDraft,
    ProductFamilyChoice,
    ReferenceHint,
    SemanticFlagHint,
    SlotAssignment,
)
from financial_agent.intent.errors import ResolverContractError
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.context import (
    ResolutionFinalizationMetadata,
    finalize_resolution,
    validate_context_graph,
)
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.types import (
    ChoiceState,
    ContextLinkType,
    ReferenceForm,
    ReferenceTargetKind,
    Selector,
    SemanticTag,
    SlotKind,
    SourceRole,
)
from financial_agent.intent.validation import derive_semantic_tags, validate_semantics
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    ActiveDatasetPin,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ResolverView,
    ResolverViewConcept,
    ResolverViewSemanticCandidate,
    ResolverViewSemanticCandidateGroup,
    build_manifest,
)
from tests.intent.view_fixtures import complete_axis_definitions


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGRESSION_PATH = Path(__file__).with_name("intent_resolution_regression.json")
HELDOUT_V1_PATH = Path(__file__).with_name("intent_resolution_heldout_ko.json")
HELDOUT_V2_PATH = Path(__file__).with_name("intent_resolution_heldout_ko_v2.json")
HELDOUT_PATH = Path(__file__).with_name("intent_resolution_heldout_ko_v3.json")
GOLD_PATH = PROJECT_ROOT / "tests" / "gold" / "core_questions.json"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "evaluate_intent_resolver.py"
REGRESSION_SHA256 = "5f917cbd326d4b4a27d260aecaf63460dffa4302dcabd5e9599efe7c90b1b18b"
HELDOUT_V1_SHA256 = "d23eae797026ed66fa2f52ae49a602f991bd9b6d02b890c799342c0a6145f63e"
HELDOUT_V2_SHA256 = "de015673ad4fa327ed3369997120f8465fb9b14e4998a924a8b90eaf45c450fb"
HELDOUT_SHA256 = "f0cb6313d7954a9f75d1fe1c691a2021c0b2e53d6681f07eb0f3e2787a9944b4"


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
    assert HELDOUT_V2_SHA256 != "TO_BE_FROZEN"
    assert HELDOUT_SHA256 != "TO_BE_FROZEN"
    assert hashlib.sha256(REGRESSION_PATH.read_bytes()).hexdigest() == REGRESSION_SHA256
    assert (
        hashlib.sha256(HELDOUT_V1_PATH.read_bytes()).hexdigest()
        == HELDOUT_V1_SHA256
    )
    assert (
        hashlib.sha256(HELDOUT_V2_PATH.read_bytes()).hexdigest()
        == HELDOUT_V2_SHA256
    )
    assert hashlib.sha256(HELDOUT_PATH.read_bytes()).hexdigest() == HELDOUT_SHA256


def test_v2_preserves_v1_questions_and_candidate_gold_without_tuning() -> None:
    v1 = _load_json(HELDOUT_V1_PATH)
    v2 = parse_strict_json(HELDOUT_V2_PATH.read_bytes(), EvaluationDataset)
    v1_by_id = {case["case_id"]: case for case in v1["cases"]}

    assert set(v1_by_id) == {case.case_id for case in v2.cases}
    for case in v2.cases:
        assert case.question == v1_by_id[case.case_id]["question"]
        assert list(case.expected_candidate_ids) == v1_by_id[case.case_id][
            "expected_candidate_ids"
        ]


def test_v3_preserves_v2_candidate_gold_and_uses_representative_executable_probes(
) -> None:
    v2 = parse_strict_json(HELDOUT_V2_PATH.read_bytes(), EvaluationDataset)
    v3 = parse_strict_json(HELDOUT_PATH.read_bytes(), EvaluationDataset)
    v2_by_id = {case.case_id: case for case in v2.cases}

    assert v3.schema_version == "3.0"
    assert set(v2_by_id) == {case.case_id for case in v3.cases}
    assert all(
        case.question == v2_by_id[case.case_id].question
        and case.expected_candidate_ids
        == v2_by_id[case.case_id].expected_candidate_ids
        for case in v3.cases
    )
    assert Counter(
        probe.kind for case in v3.cases for probe in case.validation_probes
    ) == {"unknown_id": 10, "invalid_context_graph": 10}
    assert all(
        probe.executable for case in v3.cases for probe in case.validation_probes
    )
    assert all(
        not case.validation_probes
        for case in v3.cases
        if case.expected_pipeline_outcome == "pre_model_rejected"
    )


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
    dataset = parse_strict_json(HELDOUT_V2_PATH.read_bytes(), EvaluationDataset)
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
    dataset = parse_strict_json(HELDOUT_V2_PATH.read_bytes(), EvaluationDataset)
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
    dataset = parse_strict_json(HELDOUT_V2_PATH.read_bytes(), EvaluationDataset)
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


def _cli_namespace() -> dict[str, object]:
    return runpy.run_path(str(SCRIPT_PATH), run_name="intent_evaluation_cli_test")


def _resolver_manifest() -> object:
    catalog = load_catalog(PROJECT_ROOT)
    return build_manifest(
        catalog,
        {
            "normalizer_version": NORMALIZER_VERSION,
            "candidate_policy_version": CANDIDATE_POLICY_VERSION,
            "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "adapter_version": ADAPTER_VERSION,
        },
    )


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
    assert report["metrics"]["candidate"]["reproducibility"]["numerator"] == 155
    assert report["metrics"]["candidate"]["reproducibility"]["denominator"] == 155
    assert report["metrics"]["candidate"]["reproducibility_coverage"][
        "evidence_sufficient"
    ] is True
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


def test_round2_prediction_bundle_rejects_semantic_self_report() -> None:
    """A producer cannot smuggle perfect metrics beside unrelated sidecars."""

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
    payload = {
        "schema_version": "2.0",
        "mode": "decoupled",
        "dataset_id": "synthetic-cli",
        "evaluation_dataset_sha256": "a" * 64,
        "dataset_version": "synthetic-dataset-v3",
        "dataset_manifest_hash": "d" * 64,
        "build_manifest": manifest,
        "model_id": "stored-model-v3",
        "bounded_view_bundle_raw_sha256": "b" * 64,
        "bounded_view_bundle_canonical_sha256": "c" * 64,
        "draft_bundle_raw_sha256": "e" * 64,
        "draft_bundle_canonical_sha256": "f" * 64,
        "predictions": (_synthetic_predictions()[0],),
    }

    with pytest.raises(ValidationError, match="predictions"):
        PredictionDataset.model_validate(payload)


def test_round2_output_hardlink_cannot_modify_supplied_input(tmp_path: Path) -> None:
    report_dir = PROJECT_ROOT / "build" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    supplied = tmp_path / "hardlinked-dataset.json"
    supplied.write_bytes(HELDOUT_PATH.read_bytes())
    original = supplied.read_bytes()
    output = report_dir / f"pytest-{tmp_path.name}-hardlink.json"
    output.unlink(missing_ok=True)
    os.link(supplied, output)
    try:
        result = _run_cli(
            "--mode",
            "deterministic",
            "--dataset",
            str(supplied),
            "--output",
            str(output),
        )

        assert result.returncode == 2
        assert "EVALUATION_FIXTURE_OVERWRITE_REFUSED" in result.stderr
        assert supplied.read_bytes() == original
    finally:
        output.unlink(missing_ok=True)


def _stored_artifacts(
    manifest: object,
) -> tuple[
    EvaluationDataset,
    ResolverViewBundle,
    IntentDraftBundle,
    ValidatedResolutionBundle,
    IntentRunTraceBundle,
]:
    dataset_version = "synthetic-dataset-v3"
    dataset_manifest_hash = "d" * 64
    question = "국내 ETF 순자산을 비교해줘"
    case = _synthetic_cases()[0].model_copy(
        update={
            "case_id": "stored-001",
            "question": question,
            "segments": (
                EvaluationSegment(segment_id="s1", ordinal=0, text=question),
            ),
            "expected_candidate_ids": ("aum",),
            "expected_frames": (
                EvaluationFrame(
                    frame_id="f1",
                    ordinal=0,
                    action_ids=("compare",),
                    product_family_ids=("domestic_etf",),
                    entity_type_ids=("FinancialProduct",),
                    slots=(ExpectedSlot(slot_kind="metric", value_ids=("aum",)),),
                ),
            ),
            "expected_references": (),
            "expected_context_links": (),
            "expected_slot_mutations": (),
            "expected_resolution_status": "resolved",
            "expected_tags": (),
            "validation_probes": (
                EvaluationProbe(
                    probe_id="probe-unknown-stored",
                    kind="unknown_id",
                    subject_id="unknown:stored",
                    frame_ordinal=0,
                    slot_kind="metric",
                    expected_rejection_code="MODEL_UNKNOWN_ID",
                ),
            ),
            "ood_type": None,
        }
    )
    heldout = parse_strict_json(HELDOUT_PATH.read_bytes(), EvaluationDataset)
    pre_model_case = next(
        item for item in heldout.cases if item.case_id == "HKO-NEG-LEN-001"
    )
    dataset = EvaluationDataset(
        split_id="synthetic-cli", cases=(case, pre_model_case)
    )
    catalog = load_catalog(PROJECT_ROOT)
    concept = catalog.concepts_by_id["aum"]
    view = ResolverView(
        build_manifest=manifest,
        active_dataset_pin=ActiveDatasetPin(
            dataset_version=dataset_version,
            manifest_hash=dataset_manifest_hash,
        ),
        product_family_ids=("domestic_etf",),
        action_ids=("compare",),
        semantic_candidates=(
            ResolverViewSemanticCandidateGroup(
                mention_id="mention-aum",
                items=(
                    ResolverViewSemanticCandidate(
                        semantic_id="aum",
                        match_kind="direct_alias",
                        score=1_000_000,
                    ),
                ),
            ),
        ),
        concept_definitions=(
            ResolverViewConcept(
                concept_id=concept.id,
                kind=concept.kind,
                definition_ko=concept.definition_ko,
                value_kind=concept.value_kind,
                allowed_product_families=tuple(sorted(concept.allowed_product_families)),
                allowed_ontology_types=tuple(sorted(concept.allowed_ontology_types)),
                required_qualifiers=tuple(sorted(concept.required_qualifiers)),
                allowed_operators=tuple(sorted(concept.allowed_operators)),
                missingness_sensitive=concept.missingness_sensitive,
                normalization_rule=concept.normalization_rule,
            ),
        ),
        relation_definitions=(),
        literal_candidates=(),
        entity_candidates=(),
        axis_definitions=complete_axis_definitions(),
        evidence_candidates=(),
        reference_candidates=(),
    )
    span = EvidenceSpan(
        span_id="span-1", segment_id="s1", start_char=0, end_char=2, text="국내"
    )
    draft = IntentResolutionDraft(
        evidence_spans=(span,),
        intent_frames=(
            IntentFrameDraft(
                frame_id="f1",
                ordinal=0,
                segment_ids=("s1",),
                evidence_span_ids=("span-1",),
                normalized_intent_argument=question,
                action_choice=ActionChoice(
                    state=ChoiceState.SELECTED,
                    selected_ids=(IntentType.COMPARE,),
                    evidence_span_ids=("span-1",),
                    reason_code="explicit",
                ),
                product_family_choice=ProductFamilyChoice(
                    state=ChoiceState.SELECTED,
                    selected_ids=(ProductFamily.DOMESTIC_ETF,),
                    evidence_span_ids=("span-1",),
                    reason_code="explicit",
                ),
                entity_type_ids=("FinancialProduct",),
                entity_hint_ids=(),
                slot_assignments=(
                    SlotAssignment(
                        slot_assignment_id="slot-aum",
                        slot_kind=SlotKind.METRIC,
                        value_ids=("aum",),
                        evidence_span_ids=("span-1",),
                        reason_code="explicit",
                    ),
                ),
                produced_result_hints=(SourceRole.CANDIDATES,),
            ),
        ),
        entity_hints=(),
        reference_hints=(),
        context_link_hints=(),
        slot_mutations=(),
        semantic_flag_hints=(),
        frame_limit_exceeded=False,
    )
    created_at = datetime(2026, 8, 31, tzinfo=UTC)
    context = RequestContext(
        request_key=build_request_key(case.case_id, question, dataset_version, "1.0"),
        run_id="run-stored-001",
        dataset_version=dataset_version,
        producer="evaluation-test",
        created_at=created_at,
        question_id=case.case_id,
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=55),
    )
    semantic = validate_semantics(
        draft, context, normalize_request(context), view, catalog
    )
    resolution = finalize_resolution(
        validate_context_graph(semantic),
        ResolutionFinalizationMetadata(
            request_key=context.request_key,
            run_id=context.run_id,
            dataset_version=dataset_version,
            producer=context.producer,
            created_at=created_at,
            resolution_id="resolution-stored-001",
            draft_hash=canonical_sha256(draft),
            build_manifest=manifest,
            active_dataset_manifest_hash=dataset_manifest_hash,
        ),
    )
    trace = IntentRunTrace(
        case_id=case.case_id,
        model_event="model_called",
        first_attempt=AttemptTrace(
            payload_sha256="a" * 64,
            payload_size_bytes=128,
            parser_event="draft_parsed",
            validator_event="validated",
            stable_code="RESOLUTION_VALIDATED",
            parsed_draft_sha256=canonical_sha256(draft),
        ),
        repair_attempt=None,
        repair_event="not_attempted",
        latency_ms=12,
        prompt_tokens=40,
        completion_tokens=20,
        stable_error_codes=(),
    )
    pre_model_trace = IntentRunTrace(
        case_id=pre_model_case.case_id,
        model_event="model_not_called",
        first_attempt=None,
        repair_attempt=None,
        repair_event="not_attempted",
        latency_ms=1,
        prompt_tokens=0,
        completion_tokens=0,
        stable_error_codes=("REQUEST_CONTRACT_INVALID",),
    )
    return (
        dataset,
        ResolverViewBundle(
            dataset_id="synthetic-cli",
            cases=(
                ResolverViewCaseArtifact(case_id=case.case_id, artifact=view),
                ResolverViewCaseArtifact(
                    case_id=pre_model_case.case_id, artifact=None
                ),
            ),
        ),
        IntentDraftBundle(
            dataset_id="synthetic-cli",
            cases=(
                IntentDraftCaseArtifact(case_id=case.case_id, artifact=draft),
                IntentDraftCaseArtifact(
                    case_id=pre_model_case.case_id, artifact=None
                ),
            ),
        ),
        ValidatedResolutionBundle(
            dataset_id="synthetic-cli",
            cases=(
                ValidatedResolutionCaseArtifact(
                    case_id=case.case_id, artifact=resolution
                ),
                ValidatedResolutionCaseArtifact(
                    case_id=pre_model_case.case_id, artifact=None
                ),
            ),
        ),
        IntentRunTraceBundle(
            dataset_id="synthetic-cli", cases=(trace, pre_model_trace)
        ),
    )


def _write_contract(path: Path, value: object) -> bytes:
    payload = canonical_json_bytes(value) + b"\n"
    path.write_bytes(payload)
    return payload


def test_stored_modes_bind_dataset_predictions_and_real_strict_sidecars(
    tmp_path: Path,
) -> None:
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
    dataset, view_bundle, draft_bundle, resolution_bundle, trace_bundle = (
        _stored_artifacts(manifest)
    )
    dataset_path = tmp_path / "dataset.json"
    dataset_bytes = _write_contract(dataset_path, dataset)
    view_path = tmp_path / "views.json"
    draft_path = tmp_path / "drafts.json"
    resolution_path = tmp_path / "resolutions.json"
    trace_path = tmp_path / "traces.json"
    view_raw = _write_contract(view_path, view_bundle)
    draft_raw = _write_contract(draft_path, draft_bundle)
    resolution_raw = _write_contract(resolution_path, resolution_bundle)
    trace_raw = _write_contract(trace_path, trace_bundle)
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
        "run_trace_bundle_raw_sha256": hashlib.sha256(trace_raw).hexdigest(),
        "run_trace_bundle_canonical_sha256": hashlib.sha256(
            canonical_json_bytes(trace_bundle)
        ).hexdigest(),
    }
    for mode in ("decoupled", "full"):
        bundle = PredictionDataset(
            mode=mode,
            dataset_id="synthetic-cli",
            evaluation_dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
            dataset_version="synthetic-dataset-v3",
            dataset_manifest_hash="d" * 64,
            build_manifest=manifest,
            model_id="stored-model-v2",
            bounded_view_bundle_raw_sha256=sidecar_values[
                "bounded_view_bundle_raw_sha256"
            ],
            bounded_view_bundle_canonical_sha256=sidecar_values[
                "bounded_view_bundle_canonical_sha256"
            ],
            draft_bundle_raw_sha256=sidecar_values["draft_bundle_raw_sha256"],
            draft_bundle_canonical_sha256=sidecar_values[
                "draft_bundle_canonical_sha256"
            ],
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
            run_trace_bundle_raw_sha256=sidecar_values[
                "run_trace_bundle_raw_sha256"
            ],
            run_trace_bundle_canonical_sha256=sidecar_values[
                "run_trace_bundle_canonical_sha256"
            ],
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
            "--bounded-views",
            str(view_path),
            "--drafts",
            str(draft_path),
            "--run-traces",
            str(trace_path),
            "--output",
            str(output),
        ]
        if mode == "full":
            arguments.extend(["--resolutions", str(resolution_path)])
        result = _run_cli(*arguments)
        assert result.returncode == 0, result.stderr
        report = _load_json(output)
        assert report["mode"] == mode
        assert report["provenance"]["prompt_version"] == PROMPT_VERSION
        assert report["provenance"]["adapter_version"] == ADAPTER_VERSION
        assert report["provenance"]["model_id"] == "stored-model-v2"
        assert report["provenance"]["dataset_version"] == "synthetic-dataset-v3"
        assert report["provenance"]["dataset_manifest_hash"] == "d" * 64
        assert report["provenance"]["prediction_bundle_sha256"] == hashlib.sha256(
            prediction_raw
        ).hexdigest()
        assert report["provenance"]["producer_manifest_matches_current"] is True
        assert report["metrics"]["candidate"]["recall_at_1"]["numerator"] == 1
        assert report["metrics"]["candidate"]["reproducibility"]["denominator"] == 0
        assert report["metrics"]["candidate"]["reproducibility"]["defined"] is False
        assert report["metrics"]["candidate"]["reproducibility_coverage"][
            "evidence_sufficient"
        ] is False
        assert report["metrics"]["frame"]["joint_exact_match"]["numerator"] == 2
        assert report["metrics"]["validation"]["unknown_id_acceptance"][
            "denominator"
        ] == 1
        assert report["metrics"]["validation"]["schema_validity"]["denominator"] == 1
        assert report["metrics"]["diagnostics"]["pipeline_outcome_exact"][
            "numerator"
        ] == 2
        if mode == "decoupled":
            final_draft_hash = trace_bundle.cases[0].first_attempt.parsed_draft_sha256
            assert final_draft_hash is not None
            rejected_first = AttemptTrace(
                payload_sha256="e" * 64,
                payload_size_bytes=32,
                parser_event="draft_parsed",
                validator_event="validator_rejected",
                stable_code="MODEL_UNKNOWN_ID",
                parsed_draft_sha256="f" * 64,
            )
            rejected_repair = rejected_first.model_copy(
                update={
                    "payload_sha256": "9" * 64,
                    "parsed_draft_sha256": final_draft_hash,
                }
            )
            contradictory_trace = trace_bundle.cases[0].model_copy(
                update={
                    "first_attempt": rejected_first,
                    "repair_attempt": rejected_repair,
                    "repair_event": "failed",
                    "stable_error_codes": ("MODEL_UNKNOWN_ID",),
                }
            )
            contradictory_traces = trace_bundle.model_copy(
                update={
                    "cases": (contradictory_trace, *trace_bundle.cases[1:])
                }
            )
            contradictory_trace_path = tmp_path / "contradictory-traces.json"
            contradictory_trace_raw = _write_contract(
                contradictory_trace_path, contradictory_traces
            )
            contradictory_bundle = bundle.model_copy(
                update={
                    "run_trace_bundle_raw_sha256": hashlib.sha256(
                        contradictory_trace_raw
                    ).hexdigest(),
                    "run_trace_bundle_canonical_sha256": hashlib.sha256(
                        canonical_json_bytes(contradictory_traces)
                    ).hexdigest(),
                }
            )
            contradictory_path = tmp_path / "contradictory-predictions.json"
            _write_contract(contradictory_path, contradictory_bundle)
            contradictory_result = _run_cli(
                "--mode", "decoupled",
                "--dataset", str(dataset_path),
                "--predictions", str(contradictory_path),
                "--bounded-views", str(view_path),
                "--drafts", str(draft_path),
                "--run-traces", str(contradictory_trace_path),
                "--output", str(_report_path(tmp_path, "contradictory-trace")),
            )
            assert contradictory_result.returncode == 2
            assert "EVALUATION_TRACE_MISMATCH" in contradictory_result.stderr

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
        "--run-traces", str(trace_path),
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
    changed_trace = trace_bundle.cases[0].model_copy(update={"completion_tokens": 21})
    changed_trace_bundle = trace_bundle.model_copy(
        update={"cases": (changed_trace, *trace_bundle.cases[1:])}
    )
    changed_trace_raw = _write_contract(tmp_path / "changed-traces.json", changed_trace_bundle)
    changed_bundle = bundle.model_copy(
        update={
            "run_trace_bundle_raw_sha256": hashlib.sha256(changed_trace_raw).hexdigest(),
            "run_trace_bundle_canonical_sha256": hashlib.sha256(
                canonical_json_bytes(changed_trace_bundle)
            ).hexdigest(),
        }
    )
    changed_path = tmp_path / "changed-full-predictions.json"
    changed_raw = _write_contract(changed_path, changed_bundle)
    changed_output = _report_path(tmp_path, "changed-full-report")
    changed_result = _run_cli(
        "--mode", "full",
        "--dataset", str(dataset_path),
        "--predictions", str(changed_path),
        "--bounded-views", str(view_path),
        "--drafts", str(draft_path),
        "--resolutions", str(resolution_path),
        "--run-traces", str(tmp_path / "changed-traces.json"),
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
        "--bounded-views", str(view_path),
        "--drafts", str(draft_path),
        "--resolutions", str(resolution_path),
        "--run-traces", str(trace_path),
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
        "--bounded-views", str(view_path),
        "--drafts", str(draft_path),
        "--resolutions", str(resolution_path),
        "--run-traces", str(trace_path),
        "--output", str(_report_path(tmp_path, "wrong-manifest")),
    )
    assert wrong_manifest_result.returncode == 2
    assert "EVALUATION_INPUT_MISMATCH" in wrong_manifest_result.stderr


def test_round2_validation_probes_replay_production_validators() -> None:
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
    dataset, views, drafts, _, _ = _stored_artifacts(manifest)
    case = dataset.cases[0]
    view = views.cases[0].artifact
    draft = drafts.cases[0].artifact
    assert view is not None and draft is not None
    created_at = datetime(2026, 8, 31, tzinfo=UTC)
    context = RequestContext(
        request_key=build_request_key(
            case.case_id, case.question, "synthetic-dataset-v3", "1.0"
        ),
        run_id="run-stored-001",
        dataset_version="synthetic-dataset-v3",
        producer="evaluation-test",
        created_at=created_at,
        question_id=case.case_id,
        question=case.question,
        segments=(Segment(segment_id="s1", ordinal=0, text=case.question),),
        deadline_at=created_at + timedelta(seconds=55),
    )
    normalized = normalize_request(context)

    unknown = replay_validation_probes(
        case, draft, context, normalized, view, catalog
    )
    assert [(item.decision, item.stable_code) for item in unknown] == [
        ("rejected", "MODEL_UNKNOWN_ID")
    ]

    second = draft.intent_frames[0].model_copy(
        update={
            "frame_id": "f2",
            "ordinal": 1,
            "slot_assignments": (),
            "produced_result_hints": (),
        }
    )
    graph_draft = draft.model_copy(
        update={
            "intent_frames": (*draft.intent_frames, second),
            "reference_hints": (
                ReferenceHint(
                    reference_id="ref-1",
                    segment_id="s1",
                    evidence_span_ids=("span-1",),
                    surface_presence=ReferenceMentionType.EXPLICIT,
                    reference_form=ReferenceForm.DEMONSTRATIVE,
                    grammatical_number=("plural",),
                    expected_target_kind=(ReferenceTargetKind.RESULT_SET,),
                    expected_cardinality=(Cardinality.MANY,),
                    candidate_target_frame_ids=("f1",),
                    candidate_target_mention_ids=(),
                    status="resolved",
                    reason_code="explicit",
                ),
            ),
            "context_link_hints": (
                ContextLinkHint(
                    context_link_id="link-1",
                    reference_id="ref-1",
                    link_type=ContextLinkType.CONSUME_RESULT_SET,
                    source_role=SourceRole.CANDIDATES,
                    selector=(Selector.ALL,),
                    selector_literal_candidate_id=(),
                    producer_frame_id="f1",
                    consumer_frame_id="f2",
                    target_slot_kind=(),
                ),
            ),
        }
    )
    graph_case = case.model_copy(
        update={
            "validation_probes": (
                EvaluationProbe(
                    probe_id="probe-graph-stored",
                    kind="invalid_context_graph",
                    subject_id="dangling:stored",
                    link_ordinal=0,
                    graph_field="consumer_frame_id",
                    expected_rejection_code="INVALID_CONTEXT_GRAPH",
                ),
            )
        }
    )
    graph = replay_validation_probes(
        graph_case, graph_draft, context, normalized, view, catalog
    )
    assert [(item.decision, item.stable_code) for item in graph] == [
        ("rejected", "INVALID_CONTEXT_GRAPH")
    ]


def test_round2_validation_probe_rejects_noop_and_invalid_baseline() -> None:
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
    dataset, views, drafts, _, _ = _stored_artifacts(manifest)
    case = dataset.cases[0]
    view = views.cases[0].artifact
    draft = drafts.cases[0].artifact
    assert view is not None and draft is not None
    created_at = datetime(2026, 8, 31, tzinfo=UTC)
    context = RequestContext(
        request_key=build_request_key(
            case.case_id, case.question, "synthetic-dataset-v3", "1.0"
        ),
        run_id="run-stored-001",
        dataset_version="synthetic-dataset-v3",
        producer="evaluation-test",
        created_at=created_at,
        question_id=case.case_id,
        question=case.question,
        segments=(Segment(segment_id="s1", ordinal=0, text=case.question),),
        deadline_at=created_at + timedelta(seconds=55),
    )
    normalized = normalize_request(context)
    noop_case = case.model_copy(
        update={
            "validation_probes": (
                case.validation_probes[0].model_copy(update={"subject_id": "aum"}),
            )
        }
    )
    with pytest.raises(ValueError, match="EVALUATION_PROBE_MUTATION_INVALID"):
        replay_validation_probes(
            noop_case, draft, context, normalized, view, catalog
        )

    invalid_assignment = draft.intent_frames[0].slot_assignments[0].model_copy(
        update={"value_ids": ("unknown:unprobed",)}
    )
    invalid_frame = draft.intent_frames[0].model_copy(
        update={"slot_assignments": (invalid_assignment,)}
    )
    invalid_draft = draft.model_copy(update={"intent_frames": (invalid_frame,)})
    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        replay_validation_probes(
            case, invalid_draft, context, normalized, view, catalog
        )


def test_round2_run_trace_rejects_contradictory_repair_and_raw_payload() -> None:
    validated = AttemptTrace(
        payload_sha256="a" * 64,
        payload_size_bytes=12,
        parser_event="draft_parsed",
        validator_event="validated",
        stable_code="RESOLUTION_VALIDATED",
        parsed_draft_sha256="b" * 64,
    )
    with pytest.raises(ValidationError, match="repair"):
        IntentRunTrace(
            case_id="trace-1",
            model_event="model_called",
            first_attempt=validated,
            repair_attempt=validated.model_copy(
                update={"payload_sha256": "c" * 64}
            ),
            repair_event="succeeded",
            latency_ms=1,
            prompt_tokens=1,
            completion_tokens=1,
            stable_error_codes=(),
        )

    payload = validated.model_dump(mode="json")
    payload["raw_model_response"] = "forbidden"
    with pytest.raises(ValidationError):
        AttemptTrace.model_validate(payload)


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
        "--bounded-views", str(tmp_path / "view.json"),
        "--drafts", str(tmp_path / "draft.json"),
        "--resolutions", str(resolution_sidecar),
        "--run-traces", str(tmp_path / "traces.json"),
        "--output", str(protected_sidecar),
    )
    assert sidecar_result.returncode == 2
    assert "EVALUATION_FIXTURE_OVERWRITE_REFUSED" in sidecar_result.stderr
    assert protected_sidecar.read_text(encoding="utf-8") == "{}\n"

    protected_resolution = _report_path(tmp_path, "protected-resolution")
    protected_view = _report_path(tmp_path, "protected-view")
    protected_draft = _report_path(tmp_path, "protected-draft")
    protected_trace = _report_path(tmp_path, "protected-trace")
    for path in (
        protected_resolution,
        protected_view,
        protected_draft,
        protected_trace,
    ):
        path.write_text("{}\n", encoding="utf-8")
    protected_runs = (
        _run_cli(
            "--mode", "full",
            "--dataset", str(HELDOUT_PATH),
            "--predictions", str(tmp_path / "prediction.json"),
            "--bounded-views", str(tmp_path / "view.json"),
            "--drafts", str(tmp_path / "draft.json"),
            "--resolutions", str(protected_resolution),
            "--run-traces", str(tmp_path / "traces.json"),
            "--output", str(protected_resolution),
        ),
        _run_cli(
            "--mode", "decoupled",
            "--dataset", str(HELDOUT_PATH),
            "--predictions", str(tmp_path / "prediction.json"),
            "--bounded-views", str(protected_view),
            "--drafts", str(tmp_path / "draft.json"),
            "--run-traces", str(tmp_path / "traces.json"),
            "--output", str(protected_view),
        ),
        _run_cli(
            "--mode", "decoupled",
            "--dataset", str(HELDOUT_PATH),
            "--predictions", str(tmp_path / "prediction.json"),
            "--bounded-views", str(tmp_path / "view.json"),
            "--drafts", str(protected_draft),
            "--run-traces", str(tmp_path / "traces.json"),
            "--output", str(protected_draft),
        ),
        _run_cli(
            "--mode", "decoupled",
            "--dataset", str(HELDOUT_PATH),
            "--predictions", str(tmp_path / "prediction.json"),
            "--bounded-views", str(tmp_path / "view.json"),
            "--drafts", str(tmp_path / "draft.json"),
            "--run-traces", str(protected_trace),
            "--output", str(protected_trace),
        ),
    )
    assert all(result.returncode == 2 for result in protected_runs)
    assert all(
        "EVALUATION_FIXTURE_OVERWRITE_REFUSED" in result.stderr
        for result in protected_runs
    )
    assert all(
        path.read_text(encoding="utf-8") == "{}\n"
        for path in (
            protected_resolution,
            protected_view,
            protected_draft,
            protected_trace,
        )
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


def test_round3_report_directory_swap_cannot_write_through_new_symlink(
    tmp_path: Path,
) -> None:
    test_root = tmp_path / "project"
    report_dir = test_root / "build" / "reports"
    report_dir.mkdir(parents=True)
    held_directory = tmp_path / "held-reports"
    outside = tmp_path / "outside"
    outside.mkdir()
    output_name = "report.json"
    namespace = _cli_namespace()
    cli_main = namespace["main"]
    globals_ = cli_main.__globals__
    globals_["PROJECT_ROOT"] = test_root
    globals_["REPORT_DIRECTORY"] = report_dir.resolve()
    globals_["FIXTURE_DIRECTORY"] = HELDOUT_PATH.parent
    globals_["load_catalog"] = lambda _: load_catalog(PROJECT_ROOT)
    generate = globals_["_deterministic_predictions"]

    def swap_parent(dataset: object, catalog: object) -> object:
        report_dir.rename(held_directory)
        report_dir.symlink_to(outside, target_is_directory=True)
        return generate(dataset, catalog)

    globals_["_deterministic_predictions"] = swap_parent
    try:
        result = cli_main(
            [
                "--mode",
                "deterministic",
                "--dataset",
                str(HELDOUT_PATH),
                "--output",
                str(report_dir / output_name),
            ]
        )

        assert result == 0
        assert not (outside / output_name).exists()
        assert (held_directory / output_name).is_file()
    finally:
        (outside / output_name).unlink(missing_ok=True)
        if report_dir.is_symlink():
            report_dir.unlink()
        if held_directory.exists():
            held_directory.rename(report_dir)


def test_round3_repair_attempt_must_have_distinct_payload_and_draft_hashes() -> None:
    rejected = AttemptTrace(
        payload_sha256="a" * 64,
        payload_size_bytes=20,
        parser_event="draft_parsed",
        validator_event="validator_rejected",
        stable_code="MODEL_UNKNOWN_ID",
        parsed_draft_sha256="b" * 64,
    )
    accepted = rejected.model_copy(
        update={
            "validator_event": "validated",
            "stable_code": "RESOLUTION_VALIDATED",
        }
    )

    with pytest.raises(ValidationError, match="repair attempt evidence must differ"):
        IntentRunTrace(
            case_id="same-attempt",
            model_event="model_called",
            first_attempt=rejected,
            repair_attempt=accepted,
            repair_event="succeeded",
            latency_ms=2,
            prompt_tokens=2,
            completion_tokens=2,
            stable_error_codes=("MODEL_UNKNOWN_ID",),
        )


def test_round3_repaired_artifact_must_match_only_the_repair_attempt() -> None:
    manifest = _resolver_manifest()
    _, _, drafts, _, _ = _stored_artifacts(manifest)
    draft = drafts.cases[0].artifact
    assert draft is not None
    final_hash = canonical_sha256(draft)
    first = AttemptTrace(
        payload_sha256="a" * 64,
        payload_size_bytes=20,
        parser_event="draft_parsed",
        validator_event="validator_rejected",
        stable_code="MODEL_UNKNOWN_ID",
        parsed_draft_sha256="c" * 64,
    )
    repaired = AttemptTrace(
        payload_sha256="b" * 64,
        payload_size_bytes=21,
        parser_event="draft_parsed",
        validator_event="validated",
        stable_code="RESOLUTION_VALIDATED",
        parsed_draft_sha256=final_hash,
    )
    valid_trace = IntentRunTrace(
        case_id="stored-001",
        model_event="model_called",
        first_attempt=first,
        repair_attempt=repaired,
        repair_event="succeeded",
        latency_ms=2,
        prompt_tokens=2,
        completion_tokens=2,
        stable_error_codes=("MODEL_UNKNOWN_ID",),
    )
    spoofed = valid_trace.model_copy(
        update={
            "first_attempt": first.model_copy(
                update={"parsed_draft_sha256": final_hash}
            )
        }
    )
    check = _cli_namespace()["_validate_trace_against_artifacts"]

    with pytest.raises(ValueError, match="EVALUATION_TRACE_MISMATCH"):
        check(spoofed, draft, None)


def test_round3_candidate_reproducibility_scores_only_actual_second_views() -> None:
    first_case = _synthetic_cases()[0]
    second_case = _synthetic_cases()[1]
    measured = _synthetic_predictions()[0]
    payload = _synthetic_predictions()[1].model_dump(mode="json")
    payload["candidate_reproducible"] = None
    unmeasured = EvaluationPrediction.model_validate_json(json.dumps(payload))

    metrics = evaluate_candidates((first_case, second_case), (measured, unmeasured))

    assert (metrics.reproducibility.numerator, metrics.reproducibility.denominator) == (
        1,
        1,
    )
    assert (
        metrics.reproducibility_coverage.numerator,
        metrics.reproducibility_coverage.denominator,
    ) == (1, 2)
    assert metrics.reproducibility_coverage.evidence_sufficient is False


def test_round3_projection_deduplicates_repeated_production_issue_codes() -> None:
    manifest = _resolver_manifest()
    dataset, views, drafts, _, traces = _stored_artifacts(manifest)
    case = dataset.cases[0]
    view = views.cases[0].artifact
    draft = drafts.cases[0].artifact
    trace = traces.cases[0]
    assert view is not None and draft is not None
    references = tuple(
        ReferenceHint(
            reference_id=f"unresolved-{index}",
            segment_id="s1",
            evidence_span_ids=("span-1",),
            surface_presence=ReferenceMentionType.EXPLICIT,
            reference_form=ReferenceForm.DEMONSTRATIVE,
            grammatical_number=("plural",),
            expected_target_kind=(ReferenceTargetKind.RESULT_SET,),
            expected_cardinality=(Cardinality.MANY,),
            candidate_target_frame_ids=("f1",),
            candidate_target_mention_ids=(),
            status="unresolved",
            reason_code="explicit",
        )
        for index in range(2)
    )
    unresolved_draft = draft.model_copy(update={"reference_hints": references})
    created_at = datetime(2026, 8, 31, tzinfo=UTC)
    context = RequestContext(
        request_key=build_request_key(
            case.case_id, case.question, "synthetic-dataset-v3", "1.0"
        ),
        run_id=f"eval-{case.case_id}",
        dataset_version="synthetic-dataset-v3",
        producer="intent-evaluator",
        created_at=created_at,
        question_id=case.case_id,
        question=case.question,
        segments=(Segment(segment_id="s1", ordinal=0, text=case.question),),
        deadline_at=created_at + timedelta(seconds=55),
    )
    semantic = validate_semantics(
        unresolved_draft,
        context,
        normalize_request(context),
        view,
        load_catalog(PROJECT_ROOT),
    )
    state = validate_context_graph(semantic)
    assert [issue.code for issue in state.issues].count("REFERENCE_UNRESOLVED") == 2
    unresolved_drafts = drafts.model_copy(
        update={
            "cases": (
                drafts.cases[0].model_copy(update={"artifact": unresolved_draft}),
                *drafts.cases[1:],
            )
        }
    )
    changed_trace = trace.model_copy(
        update={
            "first_attempt": trace.first_attempt.model_copy(
                update={"parsed_draft_sha256": canonical_sha256(unresolved_draft)}
            )
        }
    )
    changed_traces = traces.model_copy(
        update={"cases": (changed_trace, *traces.cases[1:])}
    )
    project = _cli_namespace()["_project_stored_predictions"]

    projected = project(
        dataset=dataset,
        views=views,
        drafts=unresolved_drafts,
        traces=changed_traces,
        resolutions=None,
        catalog=load_catalog(PROJECT_ROOT),
        dataset_version="synthetic-dataset-v3",
    )

    assert projected[0].blocking_issue_codes == ("REFERENCE_UNRESOLVED",)


def test_round3_terminal_repair_failure_remains_in_all_metrics() -> None:
    manifest = _resolver_manifest()
    dataset, views, drafts, resolutions, traces = _stored_artifacts(manifest)
    failed_trace = IntentRunTrace(
        case_id=dataset.cases[0].case_id,
        model_event="model_called",
        first_attempt=AttemptTrace(
            payload_sha256="e" * 64,
            payload_size_bytes=40,
            parser_event="schema_rejected",
            validator_event="not_run",
            stable_code="MODEL_SCHEMA_INVALID",
            parsed_draft_sha256=None,
        ),
        repair_attempt=AttemptTrace(
            payload_sha256="f" * 64,
            payload_size_bytes=41,
            parser_event="schema_rejected",
            validator_event="not_run",
            stable_code="MODEL_SCHEMA_INVALID",
            parsed_draft_sha256=None,
        ),
        repair_event="failed",
        latency_ms=25,
        prompt_tokens=60,
        completion_tokens=30,
        stable_error_codes=("MODEL_SCHEMA_INVALID",),
    )
    failed_drafts = drafts.model_copy(
        update={
            "cases": (
                drafts.cases[0].model_copy(update={"artifact": None}),
                *drafts.cases[1:],
            )
        }
    )
    failed_resolutions = resolutions.model_copy(
        update={
            "cases": (
                resolutions.cases[0].model_copy(update={"artifact": None}),
                *resolutions.cases[1:],
            )
        }
    )
    failed_traces = traces.model_copy(
        update={"cases": (failed_trace, *traces.cases[1:])}
    )
    namespace = _cli_namespace()
    validate_presence = namespace["_validate_artifact_presence"]
    project = namespace["_project_stored_predictions"]

    for final_resolutions in (None, failed_resolutions):
        validate_presence(
            dataset, views, failed_drafts, failed_traces, final_resolutions
        )
        predictions = project(
            dataset=dataset,
            views=views,
            drafts=failed_drafts,
            traces=failed_traces,
            resolutions=final_resolutions,
            catalog=load_catalog(PROJECT_ROOT),
            dataset_version="synthetic-dataset-v3",
        )
        failed = predictions[0]
        report = evaluate_predictions(dataset.cases, predictions)

        assert failed.pipeline_outcome == "model_resolution_failed"
        assert failed.candidate_groups
        assert failed.candidate_reproducible is None
        assert failed.frames == failed.references == failed.context_links == ()
        assert failed.slot_mutations == failed.tags == ()
        assert failed.repair.status == "failed"
        assert failed.validation_probe_outcomes == ()
        assert report.candidate.recall_at_1.numerator == 1
        assert report.candidate.reproducibility.denominator == 0
        assert report.frame.joint_exact_match.numerator == 1
        assert report.context.reference_exact_match.numerator == 1
        assert report.context.link_exact_match.numerator == 1
        assert report.context.mutation_exact_match.numerator == 1
        assert report.diagnostics.resolution_status_exact.numerator == 1
        assert report.diagnostics.tags_exact.numerator == 1
        assert report.diagnostics.pipeline_outcome_exact.numerator == 1
        assert report.validation.unknown_id_acceptance.denominator == 0
        assert report.validation.unknown_id_acceptance.defined is False
        assert (
            report.validation.probe_coverage.numerator,
            report.validation.probe_coverage.denominator,
        ) == (0, 1)
        assert report.validation.probe_coverage.evidence_sufficient is False
        assert report.runtime.prompt_tokens == 60
        assert report.runtime.completion_tokens == 30


def test_round4_preexisting_build_symlink_is_not_a_report_trust_root(
    tmp_path: Path,
) -> None:
    test_root = tmp_path / "project"
    scripts = test_root / "scripts"
    scripts.mkdir(parents=True)
    copied_script = scripts / SCRIPT_PATH.name
    copied_script.write_bytes(SCRIPT_PATH.read_bytes())
    outside = tmp_path / "outside"
    outside.mkdir()
    (test_root / "build").symlink_to(outside, target_is_directory=True)
    namespace = runpy.run_path(
        str(copied_script), run_name="intent_evaluation_cli_symlink_test"
    )
    namespace["main"].__globals__["load_catalog"] = lambda _: load_catalog(
        PROJECT_ROOT
    )

    result = namespace["main"](
        [
            "--mode",
            "deterministic",
            "--dataset",
            str(HELDOUT_PATH),
            "--output",
            str(test_root / "build" / "reports" / "report.json"),
        ]
    )

    assert not (outside / "reports").exists()
    assert result == 2


def test_round4_no_repair_first_failure_is_retained_as_terminal_failure() -> None:
    manifest = _resolver_manifest()
    dataset, views, drafts, resolutions, traces = _stored_artifacts(manifest)
    failed_trace = IntentRunTrace(
        case_id=dataset.cases[0].case_id,
        model_event="model_called",
        first_attempt=AttemptTrace(
            payload_sha256="c" * 64,
            payload_size_bytes=42,
            parser_event="schema_rejected",
            validator_event="not_run",
            stable_code="MODEL_SCHEMA_INVALID",
            parsed_draft_sha256=None,
        ),
        repair_attempt=None,
        repair_event="not_attempted",
        latency_ms=15,
        prompt_tokens=50,
        completion_tokens=10,
        stable_error_codes=("MODEL_SCHEMA_INVALID",),
    )
    failed_drafts = drafts.model_copy(
        update={
            "cases": (
                drafts.cases[0].model_copy(update={"artifact": None}),
                *drafts.cases[1:],
            )
        }
    )
    failed_resolutions = resolutions.model_copy(
        update={
            "cases": (
                resolutions.cases[0].model_copy(update={"artifact": None}),
                *resolutions.cases[1:],
            )
        }
    )
    failed_traces = traces.model_copy(
        update={"cases": (failed_trace, *traces.cases[1:])}
    )
    namespace = _cli_namespace()

    for final_resolutions in (None, failed_resolutions):
        namespace["_validate_artifact_presence"](
            dataset, views, failed_drafts, failed_traces, final_resolutions
        )
        predictions = namespace["_project_stored_predictions"](
            dataset=dataset,
            views=views,
            drafts=failed_drafts,
            traces=failed_traces,
            resolutions=final_resolutions,
            catalog=load_catalog(PROJECT_ROOT),
            dataset_version="synthetic-dataset-v3",
        )
        failed = predictions[0]
        report = evaluate_predictions(dataset.cases, predictions)

        assert failed.pipeline_outcome == "model_resolution_failed"
        assert failed.candidate_groups
        assert failed.frames == failed.references == failed.context_links == ()
        assert failed.first_pass_schema.status == "invalid"
        assert failed.repair.status == "not_attempted"
        assert report.diagnostics.pipeline_outcome_exact.numerator == 1
        assert (
            report.validation.probe_coverage.numerator,
            report.validation.probe_coverage.denominator,
        ) == (0, 1)


def test_round4_trace_rejects_fabricated_error_codes() -> None:
    with pytest.raises(ValidationError, match="run trace error codes do not match"):
        IntentRunTrace(
            case_id="fabricated-error",
            model_event="model_called",
            first_attempt=AttemptTrace(
                payload_sha256="a" * 64,
                payload_size_bytes=20,
                parser_event="draft_parsed",
                validator_event="validated",
                stable_code="RESOLUTION_VALIDATED",
                parsed_draft_sha256="b" * 64,
            ),
            repair_attempt=None,
            repair_event="not_attempted",
            latency_ms=1,
            prompt_tokens=1,
            completion_tokens=1,
            stable_error_codes=("FABRICATED_ERROR",),
        )


def test_round4_trace_error_codes_match_each_model_called_outcome() -> None:
    schema_rejected = AttemptTrace(
        payload_sha256="a" * 64,
        payload_size_bytes=20,
        parser_event="schema_rejected",
        validator_event="not_run",
        stable_code="MODEL_SCHEMA_INVALID",
        parsed_draft_sha256=None,
    )
    validated = AttemptTrace(
        payload_sha256="b" * 64,
        payload_size_bytes=21,
        parser_event="draft_parsed",
        validator_event="validated",
        stable_code="RESOLUTION_VALIDATED",
        parsed_draft_sha256="c" * 64,
    )
    validator_rejected = AttemptTrace(
        payload_sha256="d" * 64,
        payload_size_bytes=22,
        parser_event="draft_parsed",
        validator_event="validator_rejected",
        stable_code="MODEL_UNKNOWN_ID",
        parsed_draft_sha256="e" * 64,
    )
    cases = (
        (validated, None, "not_attempted", ()),
        (
            schema_rejected,
            validated,
            "succeeded",
            ("MODEL_SCHEMA_INVALID",),
        ),
        (
            schema_rejected,
            validator_rejected,
            "failed",
            ("MODEL_SCHEMA_INVALID", "MODEL_UNKNOWN_ID"),
        ),
        (
            schema_rejected,
            None,
            "not_attempted",
            ("MODEL_SCHEMA_INVALID",),
        ),
    )

    traces = tuple(
        IntentRunTrace(
            case_id=f"trace-{index}",
            model_event="model_called",
            first_attempt=first,
            repair_attempt=repair,
            repair_event=repair_event,
            latency_ms=1,
            prompt_tokens=1,
            completion_tokens=1,
            stable_error_codes=error_codes,
        )
        for index, (first, repair, repair_event, error_codes) in enumerate(cases)
    )

    assert tuple(trace.stable_error_codes for trace in traces) == tuple(
        item[3] for item in cases
    )
