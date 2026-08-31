from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
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
    EvaluationCase,
    EvaluationDataset,
    EvaluationFrame,
    EvaluationPrediction,
    EvaluationSegment,
    ExpectedContextLink,
    ExpectedReference,
    ExpectedSlot,
    ExpectedSlotMutation,
    PredictionDataset,
    evaluate_candidates,
    evaluate_context,
    evaluate_frames,
    evaluate_ood,
    evaluate_predictions,
)
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.types import SemanticTag
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    build_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGRESSION_PATH = Path(__file__).with_name("intent_resolution_regression.json")
HELDOUT_PATH = Path(__file__).with_name("intent_resolution_heldout_ko.json")
GOLD_PATH = PROJECT_ROOT / "tests" / "gold" / "core_questions.json"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "evaluate_intent_resolver.py"
REGRESSION_SHA256 = "5f917cbd326d4b4a27d260aecaf63460dffa4302dcabd5e9599efe7c90b1b18b"
HELDOUT_SHA256 = "d23eae797026ed66fa2f52ae49a602f991bd9b6d02b890c799342c0a6145f63e"


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
        predictions.append(
            EvaluationPrediction(
                case_id=f"metric-{index:03d}",
                candidate_ids=candidates,
                candidate_reproducible=index < 100,
                frames=_frames(index, correct=frame_correct),
                references=(_reference(index, correct=context_correct),),
                context_links=(_link(index, correct=context_correct),),
                slot_mutations=(_mutation(index, correct=context_correct),),
                resolution_status="resolved" if index >= 98 else "unmapped",
                predicted_ood_type=None if index >= 98 else "vocabulary",
                tags=(),
                blocking_issue_codes=(
                    () if index >= 98 else ("SEMANTIC_CONCEPT_UNMAPPED",)
                ),
                schema_valid=index != 99,
                unknown_id_attempted=index < 4,
                unknown_id_accepted=index == 0,
                invalid_graph_attempted=index < 5,
                invalid_graph_accepted=index == 1,
                repair_attempted=index < 10,
                latency_ms=index + 1,
                prompt_tokens=10,
                completion_tokens=5,
                stable_error_code=(
                    "MODEL_UNKNOWN_ID"
                    if index < 2
                    else "INVALID_CONTEXT_GRAPH"
                    if index == 2
                    else None
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
        ("MODEL_UNKNOWN_ID", 2),
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
            "consumer_frame_id": "missing-frame",
        }
    )
    invalid = prediction.model_copy(
        update={
            "slot_mutations": (*prediction.slot_mutations, invalid_mutation),
            "invalid_graph_attempted": True,
            "invalid_graph_accepted": True,
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
    fixture = _load_json(REGRESSION_PATH)
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
        assert label["expected_context"] == source["reference_resolution"]


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
    assert HELDOUT_SHA256 != "TO_BE_FROZEN"
    assert hashlib.sha256(REGRESSION_PATH.read_bytes()).hexdigest() == REGRESSION_SHA256
    assert hashlib.sha256(HELDOUT_PATH.read_bytes()).hexdigest() == HELDOUT_SHA256


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


def test_deterministic_cli_is_reproducible_aggregate_only_and_provenanced(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
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


def test_decoupled_and_full_modes_require_matching_strict_stored_predictions(
    tmp_path: Path,
) -> None:
    cases = _synthetic_cases()[:2]
    predictions = _synthetic_predictions()[:2]
    dataset = EvaluationDataset(
        schema_version="1.0", split_id="synthetic-cli", cases=cases
    )
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(dataset.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
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
    for mode in ("decoupled", "full"):
        bundle = PredictionDataset(
            schema_version="1.0",
            mode=mode,
            dataset_id="synthetic-cli",
            dataset_version="synthetic-dataset-v1",
            dataset_manifest_hash="d" * 64,
            build_manifest=manifest,
            model_id="stored-model-v1",
            bounded_view_hash="a" * 64 if mode == "decoupled" else None,
            draft_hash="b" * 64 if mode == "decoupled" else None,
            resolution_hash="c" * 64 if mode == "full" else None,
            predictions=predictions,
        )
        predictions_path = tmp_path / f"{mode}-predictions.json"
        predictions_path.write_text(
            json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )
        output = tmp_path / f"{mode}-report.json"
        result = _run_cli(
            "--mode",
            mode,
            "--dataset",
            str(dataset_path),
            "--predictions",
            str(predictions_path),
            "--output",
            str(output),
        )
        assert result.returncode == 0, result.stderr
        report = _load_json(output)
        assert report["mode"] == mode
        assert report["provenance"]["prompt_version"] == PROMPT_VERSION
        assert report["provenance"]["adapter_version"] == ADAPTER_VERSION
        assert report["provenance"]["model_id"] == "stored-model-v1"
        assert report["provenance"]["dataset_version"] == "synthetic-dataset-v1"
        assert report["provenance"]["dataset_manifest_hash"] == "d" * 64

    malformed = dataset.model_dump(mode="json")
    malformed["unexpected"] = True
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text(json.dumps(malformed), encoding="utf-8")
    rejected = _run_cli(
        "--mode",
        "full",
        "--dataset",
        str(malformed_path),
        "--predictions",
        str(tmp_path / "full-predictions.json"),
        "--output",
        str(tmp_path / "rejected.json"),
    )
    assert rejected.returncode == 2
    assert "EVALUATION_INPUT_INVALID" in rejected.stderr
