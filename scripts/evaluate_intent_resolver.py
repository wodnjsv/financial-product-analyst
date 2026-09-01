#!/usr/bin/env python3
"""Run strict, offline-separated intent-resolver evaluation modes."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from typing import Any
import uuid

from pydantic import SecretStr, ValidationError

from financial_agent.contracts.canonical import (
    build_request_key,
    canonical_json_bytes,
    canonical_sha256,
)
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.candidates import generate_semantic_candidates
from financial_agent.intent.catalog import SemanticCatalogSnapshot, load_catalog
from financial_agent.intent.evaluation import (
    CandidateGroup,
    EvaluationDataset,
    EvaluationFrame,
    EvaluationPrediction,
    ExpectedContextLink,
    ExpectedReference,
    ExpectedSlot,
    ExpectedSlotMutation,
    FirstPassSchemaOutcome,
    IntentDraftBundle,
    IntentRunTrace,
    IntentRunTraceBundle,
    PredictionDataset,
    RepairOutcome,
    ResolverViewBundle,
    ValidatedResolutionBundle,
    evaluate_candidates,
    evaluate_predictions,
    parse_strict_json,
    replay_validation_probes,
)
from financial_agent.intent.assembler import assemble_proposal
from financial_agent.intent.clova import ClovaStructuredOutputAdapter
from financial_agent.intent.config import ClovaResolverConfig
from financial_agent.intent.context import (
    ResolutionFinalizationMetadata,
    finalize_resolution,
    validate_context_graph,
)
from financial_agent.intent.errors import (
    MODEL_PROPOSAL_SCHEMA_INVALID,
    ModelInvocationError,
    ResolverContractError,
)
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.normalization import RequestNormalizationError, normalize_request
from financial_agent.intent.resolution import ResolverBuildManifest
from financial_agent.intent.service import IntentResolverService
from financial_agent.intent.validation import validate_semantics
from financial_agent.intent.proposal import IntentResolutionProposalV2
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ActiveDatasetPin,
    ResolverView,
    build_manifest,
    build_resolver_view,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIRECTORY = PROJECT_ROOT / "build" / "reports"
DEFAULT_DATASET = (
    PROJECT_ROOT
    / "tests"
    / "evaluation"
    / "intent"
    / "intent_resolution_heldout_ko_v3.json"
)
FIXTURE_DIRECTORY = DEFAULT_DATASET.parent
SYNTHETIC_DATASET_VERSION = "synthetic-intent-eval-v3"
FIXED_CREATED_AT = datetime(2026, 8, 31, tzinfo=UTC)
LIVE_BASE_URL = "https://clovastudio.stream.ntruss.com"
LIVE_DATASET_VERSION = "synthetic-intent-eval-v3"
LIVE_REPORT_DIRECTORY = Path("/private/tmp")
LIVE_SMOKE_CASE_IDS = (
    "HKO-PAR-001",
    "HKO-PAR-002",
    "HKO-PAR-003",
    "HKO-CMP-001",
    "HKO-CMP-002",
    "HKO-CMP-003",
    "HKO-CTX-001",
    "HKO-CTX-002",
    "HKO-CTX-003",
    "HKO-OOD-VOC-001",
    "HKO-OOD-DOM-001",
    "HKO-OOD-CTX-001",
)


class EvaluationCliError(ValueError):
    def __init__(self, code: str, *, exit_code: int = 2) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(code)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "live":
        return _run_live(argv[1:])
    args = _parser().parse_args(argv)
    report_directory_fd: int | None = None
    try:
        _validate_mode_arguments(args)
        supplied_inputs = _supplied_inputs(args)
        report_directory_fd, output_name = _safe_output_path(
            Path(args.output), supplied_inputs
        )
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
            "run_trace_bundle_raw_sha256": None,
            "run_trace_bundle_canonical_sha256": None,
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
                "coverage": None,
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
            view_raw, view_bundle, view_canonical = _read_bundle(
                Path(args.bounded_views), ResolverViewBundle
            )
            draft_raw, draft_bundle, draft_canonical = _read_bundle(
                Path(args.drafts), IntentDraftBundle
            )
            trace_raw, trace_bundle, trace_canonical = _read_bundle(
                Path(args.run_traces), IntentRunTraceBundle
            )
            resolution_bundle: ValidatedResolutionBundle | None = None
            resolution_raw: bytes | None = None
            resolution_canonical: bytes | None = None
            if args.mode == "decoupled":
                _validate_decoupled_evidence(
                    dataset,
                    prediction_bundle,
                    view_bundle,
                    draft_bundle,
                    view_raw,
                    view_canonical,
                    draft_raw,
                    draft_canonical,
                    trace_bundle,
                    trace_raw,
                    trace_canonical,
                )
            else:
                resolution_raw, resolution_bundle, resolution_canonical = _read_bundle(
                    Path(args.resolutions), ValidatedResolutionBundle
                )
                _validate_full_evidence(
                    dataset,
                    prediction_bundle,
                    view_bundle,
                    draft_bundle,
                    resolution_bundle,
                    trace_bundle,
                    view_raw,
                    view_canonical,
                    draft_raw,
                    draft_canonical,
                    resolution_raw,
                    resolution_canonical,
                    trace_raw,
                    trace_canonical,
                )
            evidence_hashes.update(
                {
                    "bounded_view_bundle_raw_sha256": _sha256(view_raw),
                    "bounded_view_bundle_canonical_sha256": _sha256(view_canonical),
                    "draft_bundle_raw_sha256": _sha256(draft_raw),
                    "draft_bundle_canonical_sha256": _sha256(draft_canonical),
                    "resolution_bundle_raw_sha256": (
                        None if resolution_raw is None else _sha256(resolution_raw)
                    ),
                    "resolution_bundle_canonical_sha256": (
                        None
                        if resolution_canonical is None
                        else _sha256(resolution_canonical)
                    ),
                    "run_trace_bundle_raw_sha256": _sha256(trace_raw),
                    "run_trace_bundle_canonical_sha256": _sha256(trace_canonical),
                }
            )
            predictions = _project_stored_predictions(
                dataset=dataset,
                views=view_bundle,
                drafts=draft_bundle,
                traces=trace_bundle,
                resolutions=resolution_bundle,
                catalog=catalog,
                dataset_version=prediction_bundle.dataset_version,
            )
            metrics = evaluate_predictions(dataset.cases, predictions).model_dump(
                mode="json"
            )

        payload: dict[str, Any] = {
            "schema_version": "3.0",
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
        _atomic_write(
            report_directory_fd, output_name, canonical_json_bytes(payload) + b"\n"
        )
        return 0
    except EvaluationCliError as error:
        print(error.code, file=sys.stderr)
        return error.exit_code
    except (OSError, ValidationError, ValueError):
        print("EVALUATION_INPUT_INVALID", file=sys.stderr)
        return 2
    finally:
        if report_directory_fd is not None:
            os.close(report_directory_fd)


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
    parser.add_argument("--run-traces")
    parser.add_argument("--output", required=True)
    return parser


def _live_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a sanitized HCX intent preflight.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--request-interval-seconds", type=float, default=1.0)
    parser.add_argument("--report-path", required=True)
    return parser


class _EmptyEntityRepository:
    async def search_batch(self, dataset_version: str, mentions: object) -> dict[str, object]:
        return {}


def _run_live(argv: list[str]) -> int:
    args = _live_parser().parse_args(argv)
    if args.request_interval_seconds < 0:
        print("LIVE_EVALUATION_ARGUMENT_INVALID", file=sys.stderr)
        return 2
    report_path = Path(args.report_path)
    if report_path.parent != LIVE_REPORT_DIRECTORY or report_path.suffix != ".json":
        print("LIVE_EVALUATION_REPORT_PATH_INVALID", file=sys.stderr)
        return 2
    api_key = os.environ.get("NCP_CLOVA_STUDIO_API")
    if not api_key:
        print("LIVE_EVALUATION_CREDENTIAL_MISSING", file=sys.stderr)
        return 3
    try:
        return asyncio.run(_run_live_cases(args, api_key))
    except (OSError, ValidationError, ValueError):
        print("LIVE_EVALUATION_INPUT_INVALID", file=sys.stderr)
        return 2


async def _run_live_cases(args: argparse.Namespace, api_key: str) -> int:
    dataset_bytes = DEFAULT_DATASET.read_bytes()
    dataset = parse_strict_json(dataset_bytes, EvaluationDataset)
    cases = _live_smoke_cases(dataset)
    catalog = load_catalog(PROJECT_ROOT)
    manifest = _current_manifest(catalog)
    adapter = ClovaStructuredOutputAdapter(
        ClovaResolverConfig(
            api_key=SecretStr(api_key),
            base_url=LIVE_BASE_URL,
            model_id=args.model,
        )
    )
    service = IntentResolverService(
        adapter=adapter,
        entity_repository=_EmptyEntityRepository(),
        catalog=catalog,
        manifest=manifest,
        active_dataset_pin=ActiveDatasetPin(
            dataset_version=LIVE_DATASET_VERSION,
            manifest_hash="0" * 64,
        ),
    )
    predictions: list[EvaluationPrediction] = []
    for index, case in enumerate(cases):
        predictions.append(await _live_prediction(case, service, adapter, catalog))
        if index + 1 < len(cases):
            await asyncio.sleep(args.request_interval_seconds)
    report = evaluate_predictions(cases, predictions)
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "mode": "live",
        "model_id": args.model,
        "case_ids": [case.case_id for case in cases],
        "metrics": report.model_dump(mode="json"),
    }
    payload["report_hash"] = _sha256(canonical_json_bytes(payload))
    _write_live_report(Path(args.report_path), canonical_json_bytes(payload) + b"\n")
    return 0


def _live_smoke_cases(dataset: EvaluationDataset) -> tuple[Any, ...]:
    by_id = {case.case_id: case for case in dataset.cases}
    if set(by_id) != {case.case_id for case in dataset.cases}:
        raise ValueError("LIVE_EVALUATION_CASE_SET_INVALID")
    try:
        return tuple(by_id[case_id] for case_id in LIVE_SMOKE_CASE_IDS)
    except KeyError as error:
        raise ValueError("LIVE_EVALUATION_CASE_SET_INVALID") from error


async def _live_prediction(
    case: Any,
    service: IntentResolverService,
    adapter: ClovaStructuredOutputAdapter,
    catalog: SemanticCatalogSnapshot,
) -> EvaluationPrediction:
    created_at = datetime.now(UTC)
    context = RequestContext(
        request_key=build_request_key(
            case.case_id, case.question, LIVE_DATASET_VERSION, "1.0"
        ),
        run_id=f"live-{case.case_id}",
        dataset_version=LIVE_DATASET_VERSION,
        producer="intent-evaluator",
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
        deadline_at=created_at + timedelta(seconds=55),
    )
    started = time.perf_counter()
    try:
        prepared = await service.prepare(context)
    except (RequestNormalizationError, ResolverContractError, ValueError):
        return _live_pre_model_prediction(case.case_id, _elapsed_ms(started))
    try:
        model_result = await adapter.invoke(prepared.prompt, timeout_seconds=20.0)
    except ModelInvocationError as error:
        return _live_failed_prediction(
            case.case_id,
            _candidate_groups_from_view(prepared.view),
            provider_success=False,
            stable_code=error.code,
            latency_ms=_elapsed_ms(started),
        )
    try:
        proposal = IntentResolutionProposalV2.model_validate_json(model_result.content)
        draft = assemble_proposal(proposal, prepared.normalized, prepared.view)
        resolution = service.validate_response(prepared, model_result.content)
        probes = replay_validation_probes(
            case,
            draft,
            context,
            prepared.normalized,
            prepared.view,
            catalog,
        )
    except (ResolverContractError, ValidationError) as error:
        stable_code = (
            error.code if isinstance(error, ResolverContractError) else MODEL_PROPOSAL_SCHEMA_INVALID
        )
        return _live_failed_prediction(
            case.case_id,
            _candidate_groups_from_view(prepared.view),
            provider_success=True,
            stable_code=stable_code,
            latency_ms=_elapsed_ms(started),
            prompt_tokens=model_result.usage["promptTokens"],
            completion_tokens=model_result.usage["completionTokens"],
            schema_valid=stable_code != MODEL_PROPOSAL_SCHEMA_INVALID,
        )
    return EvaluationPrediction(
        case_id=case.case_id,
        candidate_groups=_candidate_groups_from_view(prepared.view),
        candidate_reproducible=None,
        frames=_frames_from_resolution(resolution),
        references=_references_from_draft(draft),
        context_links=_links_from_resolution(resolution),
        slot_mutations=_mutations_from_resolution(resolution),
        resolution_status=resolution.resolution_status.value,
        pipeline_outcome="semantic_resolution",
        provider_success=True,
        predicted_ood_type=_predicted_ood_type(resolution),
        tags=tuple(sorted(tag.value for tag in resolution.final_tags)),
        blocking_issue_codes=tuple(sorted({issue.code for issue in resolution.issues})),
        first_pass_schema=FirstPassSchemaOutcome(
            status="valid", validator_event_code="SCHEMA_VALID"
        ),
        repair=RepairOutcome(
            status="not_attempted", validator_event_code="REPAIR_NOT_ATTEMPTED"
        ),
        validation_probe_outcomes=probes,
        latency_ms=_elapsed_ms(started),
        prompt_tokens=model_result.usage["promptTokens"],
        completion_tokens=model_result.usage["completionTokens"],
        stable_error_codes=(),
    )


def _live_pre_model_prediction(case_id: str, latency_ms: int) -> EvaluationPrediction:
    return EvaluationPrediction(
        case_id=case_id,
        candidate_groups=(), candidate_reproducible=None, frames=(), references=(),
        context_links=(), slot_mutations=(), resolution_status="unmapped",
        pipeline_outcome="pre_model_rejected", provider_success=None,
        predicted_ood_type=None, tags=(), blocking_issue_codes=("REQUEST_CONTRACT_INVALID",),
        first_pass_schema=FirstPassSchemaOutcome(status="not_attempted", validator_event_code="SCHEMA_NOT_ATTEMPTED"),
        repair=RepairOutcome(status="not_attempted", validator_event_code="REPAIR_NOT_ATTEMPTED"),
        validation_probe_outcomes=(), latency_ms=latency_ms, prompt_tokens=0,
        completion_tokens=0, stable_error_codes=("REQUEST_CONTRACT_INVALID",),
    )


def _live_failed_prediction(
    case_id: str,
    candidate_groups: tuple[CandidateGroup, ...],
    *,
    provider_success: bool,
    stable_code: str,
    latency_ms: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    schema_valid: bool = False,
) -> EvaluationPrediction:
    schema_status = (
        "invalid"
        if stable_code == MODEL_PROPOSAL_SCHEMA_INVALID
        else "valid"
        if schema_valid
        else "not_attempted"
    )
    return EvaluationPrediction(
        case_id=case_id,
        candidate_groups=candidate_groups, candidate_reproducible=None, frames=(),
        references=(), context_links=(), slot_mutations=(), resolution_status="unmapped",
        pipeline_outcome="model_resolution_failed", provider_success=provider_success,
        predicted_ood_type=None, tags=(), blocking_issue_codes=(stable_code,),
        first_pass_schema=FirstPassSchemaOutcome(
            status=schema_status,
            validator_event_code={
                "invalid": "SCHEMA_INVALID",
                "valid": "SCHEMA_VALID",
                "not_attempted": "SCHEMA_NOT_ATTEMPTED",
            }[schema_status],
        ),
        repair=RepairOutcome(status="not_attempted", validator_event_code="REPAIR_NOT_ATTEMPTED"),
        validation_probe_outcomes=(), latency_ms=latency_ms,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        stable_error_codes=(stable_code,),
    )


def _predicted_ood_type(resolution: Any) -> str | None:
    if resolution.resolution_status.value == "context_unresolved":
        return "context"
    reasons = {
        frame.semantic_coverage[0].reason.value
        for frame in resolution.canonical_frames
        if frame.semantic_coverage[0].state.value != "covered"
    }
    if "lexical_ood" in reasons:
        return "vocabulary"
    if "domain_ood" in reasons:
        return "domain"
    return None


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _write_live_report(path: Path, payload: bytes) -> None:
    if path.parent != LIVE_REPORT_DIRECTORY or path.suffix != ".json":
        raise ValueError("LIVE_EVALUATION_REPORT_PATH_INVALID")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _validate_mode_arguments(args: argparse.Namespace) -> None:
    supplied = {
        "predictions": args.predictions is not None,
        "bounded_views": args.bounded_views is not None,
        "drafts": args.drafts is not None,
        "resolutions": args.resolutions is not None,
        "run_traces": args.run_traces is not None,
    }
    expected = {
        "deterministic": set(),
        "live": set(),
        "decoupled": {"predictions", "bounded_views", "drafts", "run_traces"},
        "full": {
            "predictions",
            "bounded_views",
            "drafts",
            "resolutions",
            "run_traces",
        },
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
            args.run_traces,
        )
        if value is not None
    )


def _safe_output_path(
    output: Path, supplied_inputs: tuple[Path, ...]
) -> tuple[int, str]:
    absolute = output if output.is_absolute() else PROJECT_ROOT / output
    candidate = Path(os.path.normpath(os.fspath(absolute)))
    protected = (*supplied_inputs, *FIXTURE_DIRECTORY.glob("*.json"))
    if any(_same_file_if_present(candidate, path) for path in protected):
        raise EvaluationCliError("EVALUATION_FIXTURE_OVERWRITE_REFUSED")
    if candidate.parent != REPORT_DIRECTORY:
        raise EvaluationCliError("EVALUATION_OUTPUT_PATH_INVALID")
    if candidate.suffix != ".json":
        raise EvaluationCliError("EVALUATION_OUTPUT_PATH_INVALID")
    try:
        directory_fd = _open_report_directory()
    except OSError as error:
        raise EvaluationCliError("EVALUATION_OUTPUT_PATH_INVALID") from error
    try:
        output_stat = _entry_stat(candidate.name, directory_fd)
        if output_stat is not None and not stat.S_ISREG(output_stat.st_mode):
            raise EvaluationCliError("EVALUATION_OUTPUT_PATH_INVALID")
        if output_stat is not None and any(
            _same_inode(output_stat, path) for path in protected
        ):
            raise EvaluationCliError("EVALUATION_FIXTURE_OVERWRITE_REFUSED")
        return directory_fd, candidate.name
    except BaseException:
        os.close(directory_fd)
        raise


def _open_report_directory() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(PROJECT_ROOT, flags)
    build_fd: int | None = None
    try:
        build_fd = _open_or_create_directory(root_fd, "build", flags)
        return _open_or_create_directory(build_fd, "reports", flags)
    finally:
        if build_fd is not None:
            os.close(build_fd)
        os.close(root_fd)


def _open_or_create_directory(parent_fd: int, name: str, flags: int) -> int:
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, mode=0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
        return os.open(name, flags, dir_fd=parent_fd)


def _entry_stat(name: str, directory_fd: int) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _same_inode(output_stat: os.stat_result, path: Path) -> bool:
    try:
        return os.path.samestat(output_stat, path.stat())
    except OSError:
        return False


def _same_file_if_present(left: Path, right: Path) -> bool:
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def _atomic_write(directory_fd: int, output_name: str, payload: bytes) -> None:
    temporary_name = f".intent-eval-{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary_name,
            output_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


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


def _validate_decoupled_evidence(
    dataset: EvaluationDataset,
    predictions: PredictionDataset,
    views: ResolverViewBundle,
    drafts: IntentDraftBundle,
    view_raw: bytes,
    view_canonical: bytes,
    draft_raw: bytes,
    draft_canonical: bytes,
    traces: IntentRunTraceBundle,
    trace_raw: bytes,
    trace_canonical: bytes,
) -> None:
    if (
        views.dataset_id != dataset.split_id
        or drafts.dataset_id != dataset.split_id
        or traces.dataset_id != dataset.split_id
        or _sha256(view_raw) != predictions.bounded_view_bundle_raw_sha256
        or _sha256(view_canonical) != predictions.bounded_view_bundle_canonical_sha256
        or _sha256(draft_raw) != predictions.draft_bundle_raw_sha256
        or _sha256(draft_canonical) != predictions.draft_bundle_canonical_sha256
        or _sha256(trace_raw) != predictions.run_trace_bundle_raw_sha256
        or _sha256(trace_canonical) != predictions.run_trace_bundle_canonical_sha256
    ):
        raise EvaluationCliError("EVALUATION_EVIDENCE_HASH_MISMATCH")
    _require_case_set(dataset, views.cases)
    _require_case_set(dataset, drafts.cases)
    _require_case_set(dataset, traces.cases)
    if any(
        item.artifact is not None
        and (
            item.artifact.build_manifest != predictions.build_manifest
            or item.artifact.active_dataset_pin.dataset_version
            != predictions.dataset_version
            or item.artifact.active_dataset_pin.manifest_hash
            != predictions.dataset_manifest_hash
        )
        for item in views.cases
    ):
        raise EvaluationCliError("EVALUATION_INPUT_MISMATCH")
    _validate_artifact_presence(dataset, views, drafts, traces, None)


def _validate_full_evidence(
    dataset: EvaluationDataset,
    predictions: PredictionDataset,
    views: ResolverViewBundle,
    drafts: IntentDraftBundle,
    resolutions: ValidatedResolutionBundle,
    traces: IntentRunTraceBundle,
    view_raw: bytes,
    view_canonical: bytes,
    draft_raw: bytes,
    draft_canonical: bytes,
    resolution_raw: bytes,
    resolution_canonical: bytes,
    trace_raw: bytes,
    trace_canonical: bytes,
) -> None:
    if (
        views.dataset_id != dataset.split_id
        or drafts.dataset_id != dataset.split_id
        or resolutions.dataset_id != dataset.split_id
        or traces.dataset_id != dataset.split_id
        or _sha256(view_raw) != predictions.bounded_view_bundle_raw_sha256
        or _sha256(view_canonical) != predictions.bounded_view_bundle_canonical_sha256
        or _sha256(draft_raw) != predictions.draft_bundle_raw_sha256
        or _sha256(draft_canonical) != predictions.draft_bundle_canonical_sha256
        or _sha256(resolution_raw) != predictions.resolution_bundle_raw_sha256
        or _sha256(resolution_canonical)
        != predictions.resolution_bundle_canonical_sha256
        or _sha256(trace_raw) != predictions.run_trace_bundle_raw_sha256
        or _sha256(trace_canonical) != predictions.run_trace_bundle_canonical_sha256
    ):
        raise EvaluationCliError("EVALUATION_EVIDENCE_HASH_MISMATCH")
    _require_case_set(dataset, views.cases)
    _require_case_set(dataset, drafts.cases)
    _require_case_set(dataset, resolutions.cases)
    _require_case_set(dataset, traces.cases)
    if any(
        item.artifact is not None
        and (
            item.artifact.build_manifest != predictions.build_manifest
            or item.artifact.dataset_version != predictions.dataset_version
            or item.artifact.active_dataset_manifest_hash
            != predictions.dataset_manifest_hash
        )
        for item in resolutions.cases
    ):
        raise EvaluationCliError("EVALUATION_INPUT_MISMATCH")
    if any(
        item.artifact is not None
        and (
            item.artifact.build_manifest != predictions.build_manifest
            or item.artifact.active_dataset_pin.dataset_version
            != predictions.dataset_version
            or item.artifact.active_dataset_pin.manifest_hash
            != predictions.dataset_manifest_hash
        )
        for item in views.cases
    ):
        raise EvaluationCliError("EVALUATION_INPUT_MISMATCH")
    _validate_artifact_presence(dataset, views, drafts, traces, resolutions)


def _validate_artifact_presence(
    dataset: EvaluationDataset,
    views: ResolverViewBundle,
    drafts: IntentDraftBundle,
    traces: IntentRunTraceBundle,
    resolutions: ValidatedResolutionBundle | None,
) -> None:
    view_index = {item.case_id: item.artifact for item in views.cases}
    draft_index = {item.case_id: item.artifact for item in drafts.cases}
    trace_index = {item.case_id: item for item in traces.cases}
    resolution_index = (
        None
        if resolutions is None
        else {item.case_id: item.artifact for item in resolutions.cases}
    )
    for case in dataset.cases:
        pre_model = case.expected_pipeline_outcome == "pre_model_rejected"
        view = view_index[case.case_id]
        draft = draft_index[case.case_id]
        resolution = (
            None if resolution_index is None else resolution_index[case.case_id]
        )
        trace = trace_index[case.case_id]
        if pre_model:
            if (
                view is not None
                or draft is not None
                or resolution is not None
                or trace.model_event != "model_not_called"
            ):
                raise EvaluationCliError("EVALUATION_PIPELINE_OUTCOME_MISMATCH")
        elif trace.terminal_model_failure:
            if view is None or trace.model_event != "model_called":
                raise EvaluationCliError("EVALUATION_PIPELINE_OUTCOME_MISMATCH")
            if draft is not None or resolution is not None:
                raise EvaluationCliError("EVALUATION_TRACE_MISMATCH")
        elif (
            view is None
            or draft is None
            or (resolution_index is not None and resolution is None)
            or trace.model_event != "model_called"
        ):
            raise EvaluationCliError("EVALUATION_PIPELINE_OUTCOME_MISMATCH")


def _require_case_set(dataset: EvaluationDataset, items: Any) -> None:
    expected = {case.case_id for case in dataset.cases}
    actual = {item.case_id for item in items}
    if expected != actual or len(actual) != len(items):
        raise EvaluationCliError("EVALUATION_CASE_SET_MISMATCH")


def _project_stored_predictions(
    *,
    dataset: EvaluationDataset,
    views: ResolverViewBundle,
    drafts: IntentDraftBundle,
    traces: IntentRunTraceBundle,
    resolutions: ValidatedResolutionBundle | None,
    catalog: SemanticCatalogSnapshot,
    dataset_version: str,
) -> tuple[EvaluationPrediction, ...]:
    view_index = {item.case_id: item.artifact for item in views.cases}
    draft_index = {item.case_id: item.artifact for item in drafts.cases}
    trace_index = {item.case_id: item for item in traces.cases}
    resolution_index = (
        {} if resolutions is None else {item.case_id: item.artifact for item in resolutions.cases}
    )
    projected: list[EvaluationPrediction] = []
    for case in dataset.cases:
        trace = trace_index[case.case_id]
        if case.expected_pipeline_outcome == "pre_model_rejected":
            projected.append(_pre_model_prediction(case.case_id, trace))
            continue
        view = view_index[case.case_id]
        draft = draft_index[case.case_id]
        if trace.terminal_model_failure:
            if (
                view is None
                or draft is not None
                or resolution_index.get(case.case_id) is not None
            ):
                raise EvaluationCliError("EVALUATION_PIPELINE_OUTCOME_MISMATCH")
            projected.append(_failed_prediction(case.case_id, view, trace))
            continue
        if view is None or draft is None:
            raise EvaluationCliError("EVALUATION_PIPELINE_OUTCOME_MISMATCH")
        resolution = resolution_index.get(case.case_id)
        context = _case_context(case, dataset_version, resolution)
        try:
            normalized = normalize_request(context)
            semantic = validate_semantics(draft, context, normalized, view, catalog)
            context_state = validate_context_graph(semantic)
        except (RequestNormalizationError, ResolverContractError, ValueError) as error:
            raise EvaluationCliError("EVALUATION_ARTIFACT_VALIDATION_FAILED") from error
        if resolution is not None:
            _validate_resolution_projection(
                draft=draft,
                context_state=context_state,
                resolution=resolution,
            )
            frames = _frames_from_resolution(resolution)
            links = _links_from_resolution(resolution)
            mutations = _mutations_from_resolution(resolution)
            tags = tuple(sorted(tag.value for tag in resolution.final_tags))
            status = resolution.resolution_status.value
            blocking = tuple(sorted({issue.code for issue in resolution.issues}))
        else:
            frames = _frames_from_drafts(context_state.semantic_state.canonical_frames)
            links = _links_from_context_state(context_state.context_links)
            mutations = _mutations_from_draft(draft)
            tags = tuple(sorted(tag.value for tag in semantic.final_tags))
            status = context_state.resolution_status.value
            blocking = tuple(sorted({issue.code for issue in context_state.issues}))
        _validate_trace_against_artifacts(trace, draft, resolution)
        probes = replay_validation_probes(
            case, draft, context, normalized, view, catalog
        )
        projected.append(
            EvaluationPrediction(
                case_id=case.case_id,
                candidate_groups=_candidate_groups_from_view(view),
                candidate_reproducible=None,
                frames=frames,
                references=_references_from_draft(draft),
                context_links=links,
                slot_mutations=mutations,
                resolution_status=status,
                pipeline_outcome="semantic_resolution",
                predicted_ood_type=None,
                tags=tags,
                blocking_issue_codes=blocking,
                first_pass_schema=_first_pass_outcome(trace),
                repair=_repair_outcome(trace),
                validation_probe_outcomes=probes,
                latency_ms=trace.latency_ms,
                prompt_tokens=trace.prompt_tokens,
                completion_tokens=trace.completion_tokens,
                stable_error_codes=trace.stable_error_codes,
            )
        )
    return tuple(projected)


def _case_context(
    case: Any,
    dataset_version: str,
    resolution: Any | None,
) -> RequestContext:
    request_key = build_request_key(case.case_id, case.question, dataset_version, "1.0")
    if resolution is not None and resolution.request_key != request_key:
        raise EvaluationCliError("EVALUATION_INPUT_MISMATCH")
    created_at = FIXED_CREATED_AT if resolution is None else resolution.created_at
    return RequestContext(
        request_key=request_key,
        run_id=f"eval-{case.case_id}" if resolution is None else resolution.run_id,
        dataset_version=dataset_version,
        producer="intent-evaluator" if resolution is None else resolution.producer,
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
        deadline_at=created_at + timedelta(seconds=55),
    )


def _validate_resolution_projection(
    *, draft: Any, context_state: Any, resolution: Any
) -> None:
    draft_hash = canonical_sha256(draft)
    if resolution.draft_hash != draft_hash:
        raise EvaluationCliError("EVALUATION_ARTIFACT_MISMATCH")
    expected = finalize_resolution(
        context_state,
        ResolutionFinalizationMetadata(
            request_key=resolution.request_key,
            run_id=resolution.run_id,
            dataset_version=resolution.dataset_version,
            producer=resolution.producer,
            created_at=resolution.created_at,
            resolution_id=resolution.resolution_id,
            draft_hash=draft_hash,
            build_manifest=resolution.build_manifest,
            active_dataset_manifest_hash=resolution.active_dataset_manifest_hash,
        ),
    )
    fields = (
        "canonical_frames",
        "context_links",
        "final_tags",
        "resolution_status",
        "issues",
        "validation_events",
    )
    if any(getattr(expected, field) != getattr(resolution, field) for field in fields):
        raise EvaluationCliError("EVALUATION_ARTIFACT_MISMATCH")


def _validate_trace_against_artifacts(
    trace: IntentRunTrace, draft: Any, resolution: Any | None
) -> None:
    draft_hash = canonical_sha256(draft)
    if trace.terminal_model_failure:
        raise EvaluationCliError("EVALUATION_TRACE_MISMATCH")
    if trace.repair_event == "not_attempted":
        if (
            trace.first_attempt is None
            or trace.first_attempt.validator_event != "validated"
            or trace.first_attempt.parsed_draft_sha256 != draft_hash
        ):
            raise EvaluationCliError("EVALUATION_TRACE_MISMATCH")
    else:
        if (
            trace.first_attempt is None
            or trace.repair_attempt is None
            or trace.repair_attempt.parsed_draft_sha256 != draft_hash
            or trace.first_attempt.payload_sha256
            == trace.repair_attempt.payload_sha256
            or trace.first_attempt.parsed_draft_sha256 == draft_hash
        ):
            raise EvaluationCliError("EVALUATION_TRACE_MISMATCH")
    if resolution is not None:
        repair_used = trace.repair_event == "succeeded"
        expected_hashes = (
            (trace.first_attempt.payload_sha256,)
            if repair_used and trace.first_attempt is not None
            else ()
        )
        if (
            resolution.repair_used != repair_used
            or resolution.invalid_attempt_hashes != expected_hashes
        ):
            raise EvaluationCliError("EVALUATION_TRACE_MISMATCH")


def _pre_model_prediction(case_id: str, trace: IntentRunTrace) -> EvaluationPrediction:
    return EvaluationPrediction(
        case_id=case_id,
        candidate_groups=(),
        candidate_reproducible=None,
        frames=(),
        references=(),
        context_links=(),
        slot_mutations=(),
        resolution_status="unmapped",
        pipeline_outcome="pre_model_rejected",
        provider_success=None,
        predicted_ood_type="context",
        tags=(),
        blocking_issue_codes=("REQUEST_CONTRACT_INVALID",),
        first_pass_schema=FirstPassSchemaOutcome(
            status="not_attempted", validator_event_code="SCHEMA_NOT_ATTEMPTED"
        ),
        repair=RepairOutcome(
            status="not_attempted", validator_event_code="REPAIR_NOT_ATTEMPTED"
        ),
        validation_probe_outcomes=(),
        latency_ms=trace.latency_ms,
        prompt_tokens=0,
        completion_tokens=0,
        stable_error_codes=trace.stable_error_codes,
    )


def _failed_prediction(
    case_id: str, view: ResolverView, trace: IntentRunTrace
) -> EvaluationPrediction:
    return EvaluationPrediction(
        case_id=case_id,
        candidate_groups=_candidate_groups_from_view(view),
        candidate_reproducible=None,
        frames=(),
        references=(),
        context_links=(),
        slot_mutations=(),
        resolution_status="unmapped",
        pipeline_outcome="model_resolution_failed",
        provider_success=True,
        predicted_ood_type=None,
        tags=(),
        blocking_issue_codes=trace.stable_error_codes,
        first_pass_schema=_first_pass_outcome(trace),
        repair=_repair_outcome(trace),
        validation_probe_outcomes=(),
        latency_ms=trace.latency_ms,
        prompt_tokens=trace.prompt_tokens,
        completion_tokens=trace.completion_tokens,
        stable_error_codes=trace.stable_error_codes,
    )


def _candidate_groups_from_view(view: ResolverView) -> tuple[CandidateGroup, ...]:
    return tuple(
        CandidateGroup(
            mention_id=group.mention_id,
            candidate_ids=tuple(item.semantic_id for item in group.items),
        )
        for group in view.semantic_candidates
    )


def _frames_from_drafts(frames: Any) -> tuple[EvaluationFrame, ...]:
    return tuple(
        EvaluationFrame(
            frame_id=frame.frame_id,
            ordinal=frame.ordinal,
            action_ids=tuple(sorted(item.value for item in frame.action_choice.selected_ids)),
            product_family_ids=tuple(
                sorted(item.value for item in frame.product_family_choice.selected_ids)
            ),
            entity_type_ids=tuple(sorted(frame.entity_type_ids)),
            slots=tuple(
                ExpectedSlot(
                    slot_kind=assignment.slot_kind.value,
                    value_ids=tuple(sorted(assignment.value_ids)),
                )
                for assignment in sorted(
                    frame.slot_assignments, key=lambda item: item.slot_kind.value
                )
            ),
            semantic_coverage={
                "state": frame.semantic_coverage[0].state.value,
                "reason": frame.semantic_coverage[0].reason.value,
            }
            if getattr(frame, "semantic_coverage", ())
            else {"state": "covered", "reason": "none"},
        )
        for frame in frames
    )


def _frames_from_resolution(resolution: Any) -> tuple[EvaluationFrame, ...]:
    return _frames_from_drafts(resolution.canonical_frames)


def _references_from_draft(draft: Any) -> tuple[ExpectedReference, ...]:
    return tuple(
        ExpectedReference(
            reference_id=item.reference_id,
            reference_form=item.reference_form.value,
            status=item.status,
        )
        for item in draft.reference_hints
    )


def _links_from_context_state(links: Any) -> tuple[ExpectedContextLink, ...]:
    return tuple(
        ExpectedContextLink(
            context_link_id=item.context_link_id,
            reference_id=item.reference_id,
            link_type=item.link_type.value,
            source_role=item.source_role.value,
            selector=_single_enum(item.selector),
            producer_frame_id=item.producer_frame_id,
            consumer_frame_id=item.consumer_frame_id,
            target_cardinality=_single_enum(item.target_cardinality),
        )
        for item in links
    )


def _links_from_resolution(resolution: Any) -> tuple[ExpectedContextLink, ...]:
    return _links_from_context_state(resolution.context_links)


def _mutations_from_draft(draft: Any) -> tuple[ExpectedSlotMutation, ...]:
    return tuple(
        ExpectedSlotMutation(
            slot_mutation_id=item.slot_mutation_id,
            consumer_frame_id=item.consumer_frame_id,
            slot_kind=item.slot_kind.value,
            mutation_kind=item.mutation_kind.value,
            source_frame_id=_single_value(item.source_frame_id),
        )
        for item in draft.slot_mutations
    )


def _mutations_from_resolution(resolution: Any) -> tuple[ExpectedSlotMutation, ...]:
    items = tuple(
        mutation
        for frame in resolution.canonical_frames
        for mutation in frame.slot_mutations
    )
    return tuple(
        ExpectedSlotMutation(
            slot_mutation_id=item.slot_mutation_id,
            consumer_frame_id=item.consumer_frame_id,
            slot_kind=item.slot_kind.value,
            mutation_kind=item.mutation_kind.value,
            source_frame_id=_single_value(item.source_frame_id),
        )
        for item in items
    )


def _single_enum(values: tuple[Any, ...]) -> str | None:
    value = _single_value(values)
    return None if value is None else value.value


def _single_value(values: tuple[Any, ...]) -> Any | None:
    return None if not values else values[0]


def _first_pass_outcome(trace: IntentRunTrace) -> FirstPassSchemaOutcome:
    assert trace.first_attempt is not None
    if trace.first_attempt.parser_event == "schema_rejected":
        return FirstPassSchemaOutcome(
            status="invalid", validator_event_code="SCHEMA_INVALID"
        )
    return FirstPassSchemaOutcome(status="valid", validator_event_code="SCHEMA_VALID")


def _repair_outcome(trace: IntentRunTrace) -> RepairOutcome:
    event = {
        "not_attempted": "REPAIR_NOT_ATTEMPTED",
        "succeeded": "REPAIR_SUCCEEDED",
        "failed": "REPAIR_FAILED",
    }[trace.repair_event]
    return RepairOutcome(status=trace.repair_event, validator_event_code=event)


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
            first = _deterministic_view(context, normalized, catalog)
            second = _deterministic_view(context, normalized, catalog)
            candidate_groups = _candidate_groups_from_view(first)
            reproducible = canonical_json_bytes(first) == canonical_json_bytes(second)
            stable_error_codes: tuple[str, ...] = ()
            pipeline_outcome = "semantic_resolution"
        except RequestNormalizationError:
            candidate_groups = ()
            reproducible = None
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
                provider_success=(
                    True if pipeline_outcome == "semantic_resolution" else None
                ),
                predicted_ood_type=None,
                tags=(),
                blocking_issue_codes=stable_error_codes,
                first_pass_schema=FirstPassSchemaOutcome(
                    status="not_attempted",
                    validator_event_code="SCHEMA_NOT_ATTEMPTED",
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


def _deterministic_view(
    context: RequestContext,
    normalized: Any,
    catalog: SemanticCatalogSnapshot,
) -> ResolverView:
    return build_resolver_view(
        context=context,
        normalized=normalized,
        literals=extract_literals(normalized),
        semantic_candidates=generate_semantic_candidates(normalized, catalog),
        entity_candidates={},
        manifest=_current_manifest(catalog),
        active_dataset_pin=ActiveDatasetPin(
            dataset_version=SYNTHETIC_DATASET_VERSION,
            manifest_hash="0" * 64,
        ),
        catalog=catalog,
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
            "run_trace_bundle_canonical_sha256",
            "run_trace_bundle_raw_sha256",
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
