#!/usr/bin/env python3
"""Run strict, offline-separated intent resolver evaluation modes."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from pydantic import ValidationError

from financial_agent.contracts.canonical import (
    build_request_key,
    canonical_json_bytes,
)
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.candidates import (
    SemanticCandidateSet,
    generate_semantic_candidates,
)
from financial_agent.intent.catalog import SemanticCatalogSnapshot, load_catalog
from financial_agent.intent.evaluation import (
    EvaluationDataset,
    EvaluationPrediction,
    PredictionDataset,
    evaluate_candidates,
    evaluate_predictions,
)
from financial_agent.intent.normalization import (
    RequestNormalizationError,
    normalize_request,
)
from financial_agent.intent.view import (
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = (
    PROJECT_ROOT
    / "tests"
    / "evaluation"
    / "intent"
    / "intent_resolution_heldout_ko.json"
)
FIXTURE_DIRECTORY = DEFAULT_DATASET.parent
SYNTHETIC_DATASET_VERSION = "synthetic-intent-eval-v1"
FIXED_CREATED_AT = datetime(2026, 8, 31, tzinfo=UTC)


class EvaluationCliError(ValueError):
    def __init__(self, code: str, *, exit_code: int = 2) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(code)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        output = Path(args.output).resolve()
        _refuse_fixture_overwrite(
            output,
            tuple(
                Path(path).resolve()
                for path in (args.dataset, args.predictions)
                if path is not None
            ),
        )
        if args.mode == "live":
            raise EvaluationCliError("LIVE_EVALUATION_NOT_AUTHORIZED", exit_code=3)

        dataset_path = Path(args.dataset).resolve()
        dataset_bytes = dataset_path.read_bytes()
        dataset = _validate_json(dataset_bytes, EvaluationDataset)
        catalog = load_catalog(PROJECT_ROOT)
        if args.mode == "deterministic":
            prediction_bundle = None
            predictions = _deterministic_predictions(dataset, catalog)
            candidate = evaluate_candidates(dataset.cases, predictions)
            metrics: dict[str, object | None] = {
                "candidate": candidate.model_dump(mode="json"),
                "frame": None,
                "context": None,
                "ood": None,
                "validation": None,
                "runtime": None,
            }
        else:
            if args.predictions is None:
                raise EvaluationCliError("EVALUATION_PREDICTIONS_REQUIRED")
            prediction_bytes = Path(args.predictions).resolve().read_bytes()
            prediction_bundle = _validate_json(prediction_bytes, PredictionDataset)
            if (
                prediction_bundle.mode != args.mode
                or prediction_bundle.dataset_id != dataset.split_id
            ):
                raise EvaluationCliError("EVALUATION_INPUT_MISMATCH")
            metrics = evaluate_predictions(
                dataset.cases, prediction_bundle.predictions
            ).model_dump(mode="json")

        provenance = _provenance(
            mode=args.mode,
            dataset=dataset,
            dataset_bytes=dataset_bytes,
            catalog=catalog,
            prediction_bundle=prediction_bundle,
        )

        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "mode": args.mode,
            "provenance": provenance,
            "metrics": metrics,
        }
        payload["report_hash"] = hashlib.sha256(
            canonical_json_bytes(payload)
        ).hexdigest()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(canonical_json_bytes(payload) + b"\n")
        return 0
    except EvaluationCliError as error:
        print(error.code, file=sys.stderr)
        return error.exit_code
    except (OSError, ValidationError, ValueError, json.JSONDecodeError):
        print("EVALUATION_INPUT_INVALID", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("deterministic", "decoupled", "full", "live"),
        required=True,
    )
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--predictions")
    parser.add_argument("--output", required=True)
    return parser


def _validate_json(payload: bytes, model: Any) -> Any:
    json.loads(
        payload,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda _value: _reject_non_json_number(),
    )
    return model.model_validate_json(payload)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_non_json_number() -> None:
    raise ValueError("non-JSON number")


def _refuse_fixture_overwrite(output: Path, supplied_inputs: tuple[Path, ...]) -> None:
    fixtures = {path.resolve() for path in FIXTURE_DIRECTORY.glob("*.json")}
    fixtures.update(supplied_inputs)
    if output in fixtures:
        raise EvaluationCliError("EVALUATION_FIXTURE_OVERWRITE_REFUSED")


def _deterministic_predictions(
    dataset: EvaluationDataset, catalog: SemanticCatalogSnapshot
) -> tuple[EvaluationPrediction, ...]:
    predictions: list[EvaluationPrediction] = []
    for case in dataset.cases:
        context = RequestContext(
            request_key=build_request_key(
                case.case_id, case.question, SYNTHETIC_DATASET_VERSION, "1.0"
            ),
            run_id=f"eval-{case.case_id}",
            dataset_version=SYNTHETIC_DATASET_VERSION,
            producer="intent-evaluator",
            created_at=FIXED_CREATED_AT,
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
            deadline_at=FIXED_CREATED_AT + timedelta(seconds=55),
        )
        try:
            normalized = normalize_request(context)
            first = generate_semantic_candidates(normalized, catalog)
            second = generate_semantic_candidates(normalized, catalog)
            candidate_ids = _ranked_candidate_ids(first)
            reproducible = canonical_json_bytes(first) == canonical_json_bytes(second)
            stable_error_code = None
        except RequestNormalizationError:
            candidate_ids = ()
            reproducible = True
            stable_error_code = "REQUEST_CONTRACT_INVALID"
        predictions.append(
            EvaluationPrediction(
                case_id=case.case_id,
                candidate_ids=candidate_ids,
                candidate_reproducible=reproducible,
                frames=(),
                references=(),
                context_links=(),
                slot_mutations=(),
                resolution_status="unmapped",
                predicted_ood_type=None,
                tags=(),
                blocking_issue_codes=(stable_error_code,)
                if stable_error_code is not None
                else (),
                schema_valid=True,
                unknown_id_attempted=False,
                unknown_id_accepted=False,
                invalid_graph_attempted=False,
                invalid_graph_accepted=False,
                repair_attempted=False,
                latency_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
                stable_error_code=stable_error_code,
            )
        )
    return tuple(predictions)


def _ranked_candidate_ids(candidate_set: SemanticCandidateSet) -> tuple[str, ...]:
    ranked: list[str] = []
    seen: set[str] = set()
    for group in candidate_set.by_mention:
        for item in group.items:
            if item.semantic_id not in seen:
                seen.add(item.semantic_id)
                ranked.append(item.semantic_id)
    return tuple(ranked)


def _provenance(
    *,
    mode: str,
    dataset: EvaluationDataset,
    dataset_bytes: bytes,
    catalog: SemanticCatalogSnapshot,
    prediction_bundle: PredictionDataset | None,
) -> dict[str, object]:
    deterministic = mode == "deterministic"
    if prediction_bundle is not None:
        manifest = prediction_bundle.build_manifest
        manifest_hashes = {
            item.relative_path: item.sha256 for item in manifest.ontology_hashes
        }
        if (
            manifest.catalog_hash != catalog.catalog_hash
            or manifest.overlay_hash != catalog.overlay_hash
            or manifest_hashes != dict(catalog.ontology_hashes)
        ):
            raise EvaluationCliError("EVALUATION_INPUT_MISMATCH")
    return {
        "catalog_version": catalog.catalog_version,
        "catalog_hash": catalog.catalog_hash,
        "ontology_hashes": dict(sorted(catalog.ontology_hashes.items())),
        "overlay_version": catalog.overlay_version,
        "overlay_hash": catalog.overlay_hash,
        "normalizer_version": NORMALIZER_VERSION,
        "candidate_policy_version": CANDIDATE_POLICY_VERSION,
        "prompt_version": (
            None
            if prediction_bundle is None
            else prediction_bundle.build_manifest.prompt_version
        ),
        "adapter_version": (
            None
            if prediction_bundle is None
            else prediction_bundle.build_manifest.adapter_version
        ),
        "model_id": (
            None if prediction_bundle is None else prediction_bundle.model_id
        ),
        "dataset_id": dataset.split_id,
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "dataset_version": (
            SYNTHETIC_DATASET_VERSION
            if prediction_bundle is None
            else prediction_bundle.dataset_version
        ),
        "dataset_manifest_hash": (
            None
            if prediction_bundle is None
            else prediction_bundle.dataset_manifest_hash
        ),
        "bounded_view_hash": (
            None
            if prediction_bundle is None
            else prediction_bundle.bounded_view_hash
        ),
        "draft_hash": (
            None if prediction_bundle is None else prediction_bundle.draft_hash
        ),
        "resolution_hash": (
            None
            if prediction_bundle is None
            else prediction_bundle.resolution_hash
        ),
        "build_revision": _build_revision(),
        "not_applicable": (
            [
                "adapter_version",
                "bounded_view_hash",
                "dataset_manifest_hash",
                "draft_hash",
                "model_id",
                "prompt_version",
                "resolution_hash",
            ]
            if deterministic
            else []
        ),
    }


def _build_revision() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and len(revision) == 40 else None


if __name__ == "__main__":
    raise SystemExit(main())
