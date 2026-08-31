#!/usr/bin/env python3
"""Run strict, offline-separated intent-resolver evaluation modes."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import subprocess
import sys
from typing import Any

from pydantic import ValidationError

from financial_agent.contracts.canonical import build_request_key, canonical_json_bytes
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.candidates import SemanticCandidateSet, generate_semantic_candidates
from financial_agent.intent.catalog import SemanticCatalogSnapshot, load_catalog
from financial_agent.intent.evaluation import (
    CandidateGroup,
    EvaluationDataset,
    EvaluationPrediction,
    FirstPassSchemaOutcome,
    IntentDraftBundle,
    PredictionDataset,
    RepairOutcome,
    ResolverViewBundle,
    ValidatedResolutionBundle,
    evaluate_candidates,
    evaluate_predictions,
    parse_strict_json,
)
from financial_agent.intent.normalization import RequestNormalizationError, normalize_request
from financial_agent.intent.resolution import ResolverBuildManifest
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    build_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIRECTORY = (PROJECT_ROOT / "build" / "reports").resolve()
DEFAULT_DATASET = (
    PROJECT_ROOT
    / "tests"
    / "evaluation"
    / "intent"
    / "intent_resolution_heldout_ko_v2.json"
)
FIXTURE_DIRECTORY = DEFAULT_DATASET.parent
SYNTHETIC_DATASET_VERSION = "synthetic-intent-eval-v2"
FIXED_CREATED_AT = datetime(2026, 8, 31, tzinfo=UTC)


class EvaluationCliError(ValueError):
    def __init__(self, code: str, *, exit_code: int = 2) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(code)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate_mode_arguments(args)
        supplied_inputs = _supplied_inputs(args)
        output = _safe_output_path(Path(args.output), supplied_inputs)
        if args.mode == "live":
            raise EvaluationCliError("LIVE_EVALUATION_NOT_AUTHORIZED", exit_code=3)

        dataset_path = Path(args.dataset).resolve()
        dataset_bytes = dataset_path.read_bytes()
        dataset = parse_strict_json(dataset_bytes, EvaluationDataset)
        catalog = load_catalog(PROJECT_ROOT)
        current_manifest = _current_manifest(catalog)
        prediction_bundle: PredictionDataset | None = None
        prediction_bytes: bytes | None = None
        evidence_hashes: dict[str, str | None] = {
            "bounded_view_bundle_raw_sha256": None,
            "bounded_view_bundle_canonical_sha256": None,
            "draft_bundle_raw_sha256": None,
            "draft_bundle_canonical_sha256": None,
            "resolution_bundle_raw_sha256": None,
            "resolution_bundle_canonical_sha256": None,
        }

        if args.mode == "deterministic":
            predictions = _deterministic_predictions(dataset, catalog)
            metrics: dict[str, object | None] = {
                "candidate": evaluate_candidates(
                    dataset.cases, predictions
                ).model_dump(mode="json"),
                "frame": None,
                "context": None,
                "ood": None,
                "validation": None,
                "diagnostics": None,
                "runtime": None,
            }
        else:
            prediction_path = Path(args.predictions).resolve()
            prediction_bytes = prediction_path.read_bytes()
            prediction_bundle = parse_strict_json(prediction_bytes, PredictionDataset)
            _validate_prediction_bundle(
                mode=args.mode,
                dataset=dataset,
                dataset_bytes=dataset_bytes,
                prediction_bundle=prediction_bundle,
                current_manifest=current_manifest,
            )
            if args.mode == "decoupled":
                view_raw, view_bundle, view_canonical = _read_bundle(
                    Path(args.bounded_views), ResolverViewBundle
                )
                draft_raw, draft_bundle, draft_canonical = _read_bundle(
                    Path(args.drafts), IntentDraftBundle
                )
                _validate_decoupled_evidence(
                    dataset,
                    prediction_bundle,
                    view_bundle,
                    draft_bundle,
                    view_raw,
                    view_canonical,
                    draft_raw,
                    draft_canonical,
                )
                evidence_hashes.update(
                    {
                        "bounded_view_bundle_raw_sha256": _sha256(view_raw),
                        "bounded_view_bundle_canonical_sha256": _sha256(view_canonical),
                        "draft_bundle_raw_sha256": _sha256(draft_raw),
                        "draft_bundle_canonical_sha256": _sha256(draft_canonical),
                    }
                )
            else:
                resolution_raw, resolution_bundle, resolution_canonical = _read_bundle(
                    Path(args.resolutions), ValidatedResolutionBundle
                )
                _validate_full_evidence(
                    dataset,
                    prediction_bundle,
                    resolution_bundle,
                    resolution_raw,
                    resolution_canonical,
                )
                evidence_hashes.update(
                    {
                        "resolution_bundle_raw_sha256": _sha256(resolution_raw),
                        "resolution_bundle_canonical_sha256": _sha256(resolution_canonical),
                    }
                )
            metrics = evaluate_predictions(
                dataset.cases, prediction_bundle.predictions
            ).model_dump(mode="json")

        payload: dict[str, Any] = {
            "schema_version": "2.0",
            "mode": args.mode,
            "provenance": _provenance(
                mode=args.mode,
                dataset=dataset,
                dataset_bytes=dataset_bytes,
                current_manifest=current_manifest,
                prediction_bundle=prediction_bundle,
                prediction_bytes=prediction_bytes,
                evidence_hashes=evidence_hashes,
            ),
            "metrics": metrics,
        }
        payload["report_hash"] = _sha256(canonical_json_bytes(payload))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(canonical_json_bytes(payload) + b"\n")
        return 0
    except EvaluationCliError as error:
        print(error.code, file=sys.stderr)
        return error.exit_code
    except (OSError, ValidationError, ValueError):
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
    parser.add_argument("--bounded-views")
    parser.add_argument("--drafts")
    parser.add_argument("--resolutions")
    parser.add_argument("--output", required=True)
    return parser


def _validate_mode_arguments(args: argparse.Namespace) -> None:
    supplied = {
        "predictions": args.predictions is not None,
        "bounded_views": args.bounded_views is not None,
        "drafts": args.drafts is not None,
        "resolutions": args.resolutions is not None,
    }
    expected = {
        "deterministic": set(),
        "live": set(),
        "decoupled": {"predictions", "bounded_views", "drafts"},
        "full": {"predictions", "resolutions"},
    }[args.mode]
    if {name for name, present in supplied.items() if present} != expected:
        raise EvaluationCliError("EVALUATION_MODE_ARGUMENT_INVALID")


def _supplied_inputs(args: argparse.Namespace) -> tuple[Path, ...]:
    return tuple(
        Path(value).resolve()
        for value in (
            args.dataset,
            args.predictions,
            args.bounded_views,
            args.drafts,
            args.resolutions,
        )
        if value is not None
    )


def _safe_output_path(output: Path, supplied_inputs: tuple[Path, ...]) -> Path:
    absolute = output if output.is_absolute() else PROJECT_ROOT / output
    if absolute.is_symlink():
        raise EvaluationCliError("EVALUATION_OUTPUT_PATH_INVALID")
    resolved = absolute.resolve(strict=False)
    if resolved in supplied_inputs:
        raise EvaluationCliError("EVALUATION_FIXTURE_OVERWRITE_REFUSED")
    fixtures = {path.resolve() for path in FIXTURE_DIRECTORY.glob("*.json")}
    if resolved in fixtures:
        raise EvaluationCliError("EVALUATION_FIXTURE_OVERWRITE_REFUSED")
    try:
        resolved.relative_to(REPORT_DIRECTORY)
    except ValueError as error:
        raise EvaluationCliError("EVALUATION_OUTPUT_PATH_INVALID") from error
    if resolved.suffix != ".json" or (resolved.exists() and not resolved.is_file()):
        raise EvaluationCliError("EVALUATION_OUTPUT_PATH_INVALID")
    return resolved


def _read_bundle[T](path: Path, model: type[T]) -> tuple[bytes, T, bytes]:
    raw = path.resolve().read_bytes()
    bundle = parse_strict_json(raw, model)
    return raw, bundle, canonical_json_bytes(bundle)


def _validate_prediction_bundle(
    *,
    mode: str,
    dataset: EvaluationDataset,
    dataset_bytes: bytes,
    prediction_bundle: PredictionDataset,
    current_manifest: ResolverBuildManifest,
) -> None:
    if (
        prediction_bundle.mode != mode
        or prediction_bundle.dataset_id != dataset.split_id
        or prediction_bundle.evaluation_dataset_sha256 != _sha256(dataset_bytes)
        or prediction_bundle.build_manifest != current_manifest
    ):
        raise EvaluationCliError("EVALUATION_INPUT_MISMATCH")
    _require_case_set(dataset, prediction_bundle.predictions)


def _validate_decoupled_evidence(
    dataset: EvaluationDataset,
    predictions: PredictionDataset,
    views: ResolverViewBundle,
    drafts: IntentDraftBundle,
    view_raw: bytes,
    view_canonical: bytes,
    draft_raw: bytes,
    draft_canonical: bytes,
) -> None:
    if (
        views.dataset_id != dataset.split_id
        or drafts.dataset_id != dataset.split_id
        or _sha256(view_raw) != predictions.bounded_view_bundle_raw_sha256
        or _sha256(view_canonical) != predictions.bounded_view_bundle_canonical_sha256
        or _sha256(draft_raw) != predictions.draft_bundle_raw_sha256
        or _sha256(draft_canonical) != predictions.draft_bundle_canonical_sha256
    ):
        raise EvaluationCliError("EVALUATION_EVIDENCE_HASH_MISMATCH")
    _require_case_set(dataset, views.cases)
    _require_case_set(dataset, drafts.cases)
    if any(
        item.artifact.build_manifest != predictions.build_manifest
        or item.artifact.active_dataset_pin.dataset_version != predictions.dataset_version
        or item.artifact.active_dataset_pin.manifest_hash
        != predictions.dataset_manifest_hash
        for item in views.cases
    ):
        raise EvaluationCliError("EVALUATION_INPUT_MISMATCH")


def _validate_full_evidence(
    dataset: EvaluationDataset,
    predictions: PredictionDataset,
    resolutions: ValidatedResolutionBundle,
    resolution_raw: bytes,
    resolution_canonical: bytes,
) -> None:
    if (
        resolutions.dataset_id != dataset.split_id
        or _sha256(resolution_raw) != predictions.resolution_bundle_raw_sha256
        or _sha256(resolution_canonical)
        != predictions.resolution_bundle_canonical_sha256
    ):
        raise EvaluationCliError("EVALUATION_EVIDENCE_HASH_MISMATCH")
    _require_case_set(dataset, resolutions.cases)
    if any(
        item.artifact.build_manifest != predictions.build_manifest
        or item.artifact.dataset_version != predictions.dataset_version
        or item.artifact.active_dataset_manifest_hash
        != predictions.dataset_manifest_hash
        for item in resolutions.cases
    ):
        raise EvaluationCliError("EVALUATION_INPUT_MISMATCH")


def _require_case_set(dataset: EvaluationDataset, items: Any) -> None:
    expected = {case.case_id for case in dataset.cases}
    actual = {item.case_id for item in items}
    if expected != actual or len(actual) != len(items):
        raise EvaluationCliError("EVALUATION_CASE_SET_MISMATCH")


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
            candidate_groups = _candidate_groups(first)
            reproducible = canonical_json_bytes(first) == canonical_json_bytes(second)
            stable_error_codes: tuple[str, ...] = ()
            pipeline_outcome = "semantic_resolution"
        except RequestNormalizationError:
            candidate_groups = ()
            reproducible = True
            stable_error_codes = ("REQUEST_CONTRACT_INVALID",)
            pipeline_outcome = "pre_model_rejected"
        predictions.append(
            EvaluationPrediction(
                case_id=case.case_id,
                candidate_groups=candidate_groups,
                candidate_reproducible=reproducible,
                frames=(),
                references=(),
                context_links=(),
                slot_mutations=(),
                resolution_status="unmapped",
                pipeline_outcome=pipeline_outcome,
                predicted_ood_type=None,
                tags=(),
                blocking_issue_codes=stable_error_codes,
                first_pass_schema=FirstPassSchemaOutcome(
                    status="valid", validator_event_code="SCHEMA_VALID"
                ),
                repair=RepairOutcome(
                    status="not_attempted",
                    validator_event_code="REPAIR_NOT_ATTEMPTED",
                ),
                validation_probe_outcomes=(),
                latency_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
                stable_error_codes=stable_error_codes,
            )
        )
    return tuple(predictions)


def _candidate_groups(candidate_set: SemanticCandidateSet) -> tuple[CandidateGroup, ...]:
    return tuple(
        CandidateGroup(
            mention_id=group.mention.mention_id,
            candidate_ids=tuple(item.semantic_id for item in group.items),
        )
        for group in candidate_set.by_mention
    )


def _current_manifest(catalog: SemanticCatalogSnapshot) -> ResolverBuildManifest:
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


def _provenance(
    *,
    mode: str,
    dataset: EvaluationDataset,
    dataset_bytes: bytes,
    current_manifest: ResolverBuildManifest,
    prediction_bundle: PredictionDataset | None,
    prediction_bytes: bytes | None,
    evidence_hashes: dict[str, str | None],
) -> dict[str, object]:
    manifest = (
        current_manifest
        if prediction_bundle is None
        else prediction_bundle.build_manifest
    )
    deterministic = prediction_bundle is None
    manifest_bytes = canonical_json_bytes(manifest)
    current_manifest_bytes = canonical_json_bytes(current_manifest)
    result: dict[str, object] = {
        "catalog_version": manifest.catalog_version,
        "catalog_hash": manifest.catalog_hash,
        "ontology_hashes": {
            item.relative_path: item.sha256 for item in manifest.ontology_hashes
        },
        "overlay_version": manifest.overlay_version,
        "overlay_hash": manifest.overlay_hash,
        "normalizer_version": manifest.normalizer_version,
        "candidate_policy_version": manifest.candidate_policy_version,
        "resolver_schema_version": manifest.resolver_schema_version,
        "prompt_version": None if deterministic else manifest.prompt_version,
        "adapter_version": None if deterministic else manifest.adapter_version,
        "model_id": None if deterministic else prediction_bundle.model_id,
        "dataset_id": dataset.split_id,
        "dataset_sha256": _sha256(dataset_bytes),
        "dataset_version": (
            SYNTHETIC_DATASET_VERSION
            if deterministic
            else prediction_bundle.dataset_version
        ),
        "dataset_manifest_hash": (
            None if deterministic else prediction_bundle.dataset_manifest_hash
        ),
        "prediction_bundle_sha256": (
            None if prediction_bytes is None else _sha256(prediction_bytes)
        ),
        "producer_build_manifest_sha256": _sha256(manifest_bytes),
        "current_build_manifest_sha256": _sha256(current_manifest_bytes),
        "producer_manifest_matches_current": manifest == current_manifest,
        "build_revision": _build_revision(),
        **evidence_hashes,
    }
    result["not_applicable"] = (
        [
            "adapter_version",
            "bounded_view_bundle_canonical_sha256",
            "bounded_view_bundle_raw_sha256",
            "dataset_manifest_hash",
            "draft_bundle_canonical_sha256",
            "draft_bundle_raw_sha256",
            "model_id",
            "prediction_bundle_sha256",
            "prompt_version",
            "resolution_bundle_canonical_sha256",
            "resolution_bundle_raw_sha256",
        ]
        if deterministic
        else []
    )
    return result


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
