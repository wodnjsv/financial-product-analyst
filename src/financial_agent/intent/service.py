"""One-call assembly of the ontology-grounded intent resolver pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from time import perf_counter
from typing import Protocol

from pydantic import Field, ValidationError

from financial_agent.contracts.base import ContractModel
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.request import RequestContext

from .candidates import (
    EntityCandidate,
    Mention,
    SemanticCandidateSet,
    generate_semantic_candidates,
)
from .catalog import SemanticCatalogSnapshot
from .clova import ModelInvocationResult
from .context import (
    ResolutionFinalizationMetadata,
    finalize_resolution,
    validate_context_graph,
)
from .draft import IntentResolutionDraft
from .errors import (
    MODEL_SCHEMA_INVALID,
    MODEL_TIMEOUT,
    ModelInvocationError,
    ResolverContractError,
)
from .literals import LiteralCandidate, extract_literals
from .normalization import (
    NormalizedRequest,
    RequestNormalizationError,
    normalize_request,
    normalize_segment,
)
from .prompt import ResolverPromptEnvelope, build_prompt
from .resolution import ResolverBuildManifest, ValidatedIntentResolution
from .validation import validate_semantics
from .view import (
    ActiveDatasetPin,
    ResolverView,
    build_resolver_view,
    validate_resolver_pins,
)


MAX_MODEL_TIMEOUT_SECONDS = 20.0
_SUCCESS_CODE = "RESOLUTION_VALIDATED"
_REPAIR_INSTRUCTIONS = {
    "MODEL_SCHEMA_INVALID": "Return every required field with the exact schema shape.",
    "MODEL_UNKNOWN_ID": "Select only identifiers offered in the resolver view.",
    "LITERAL_SPAN_MISMATCH": (
        "Copy evidence spans exactly from the original segment text."
    ),
    "INVALID_CONTEXT_GRAPH": (
        "Use only backward acyclic links with compatible cardinality."
    ),
}


class _ModelAdapter(Protocol):
    async def invoke(
        self, envelope: ResolverPromptEnvelope, timeout_seconds: float
    ) -> ModelInvocationResult: ...


class _EntityRepository(Protocol):
    async def search_batch(
        self, dataset_version: str, mentions: Sequence[Mention]
    ) -> Mapping[str, tuple[EntityCandidate, ...]]: ...


class ModelUsageTelemetry(ContractModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ResolutionTelemetry(ContractModel):
    normalization_ms: int = Field(ge=0)
    candidate_ms: int = Field(ge=0)
    model_ms: int = Field(ge=0)
    validation_ms: int = Field(ge=0)
    semantic_candidate_count: int = Field(ge=0)
    entity_candidate_count: int = Field(ge=0)
    frame_count: int = Field(ge=0)
    context_link_count: int = Field(ge=0)
    usage: ModelUsageTelemetry
    stable_code: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class _PreparationTelemetry:
    normalization_ms: int
    candidate_ms: int
    semantic_candidate_count: int
    entity_candidate_count: int


@dataclass(frozen=True, slots=True)
class PreparedResolutionRequest:
    context: RequestContext
    normalized: NormalizedRequest
    literals: tuple[LiteralCandidate, ...]
    semantic_candidates: SemanticCandidateSet
    entity_candidates: Mapping[str, tuple[EntityCandidate, ...]]
    view: ResolverView
    prompt: ResolverPromptEnvelope
    telemetry: _PreparationTelemetry


@dataclass(frozen=True, slots=True)
class ResolutionAttempt:
    resolution: ValidatedIntentResolution
    telemetry: ResolutionTelemetry


class IntentResolverService:
    def __init__(
        self,
        *,
        adapter: _ModelAdapter,
        entity_repository: _EntityRepository,
        catalog: SemanticCatalogSnapshot,
        manifest: ResolverBuildManifest,
        active_dataset_pin: ActiveDatasetPin,
        utcnow: Callable[[], datetime] | None = None,
        timer: Callable[[], float] | None = None,
    ) -> None:
        self._adapter = adapter
        self._entity_repository = entity_repository
        self._catalog = catalog
        self._manifest = manifest
        self._active_dataset_pin = active_dataset_pin
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._timer = timer or perf_counter

    async def prepare(self, context: RequestContext) -> PreparedResolutionRequest:
        normalization_started = self._timer()
        normalized = normalize_request(context)
        validate_resolver_pins(
            self._catalog,
            context,
            normalized,
            self._manifest,
            self._active_dataset_pin,
        )
        normalization_ms = _duration_ms(normalization_started, self._timer())

        candidates_started = self._timer()
        literals = extract_literals(normalized)
        semantic_candidates = generate_semantic_candidates(normalized, self._catalog)
        entity_mentions = _entity_mentions(context, normalized)
        entity_candidates = await self._entity_repository.search_batch(
            context.dataset_version,
            entity_mentions,
        )
        view = build_resolver_view(
            context=context,
            normalized=normalized,
            literals=literals,
            semantic_candidates=semantic_candidates,
            entity_candidates=entity_candidates,
            manifest=self._manifest,
            active_dataset_pin=self._active_dataset_pin,
            catalog=self._catalog,
        )
        prompt = build_prompt(context, view)
        candidate_ms = _duration_ms(candidates_started, self._timer())
        return PreparedResolutionRequest(
            context=context,
            normalized=normalized,
            literals=literals,
            semantic_candidates=semantic_candidates,
            entity_candidates=entity_candidates,
            view=view,
            prompt=prompt,
            telemetry=_PreparationTelemetry(
                normalization_ms=normalization_ms,
                candidate_ms=candidate_ms,
                semantic_candidate_count=semantic_candidates.total_count,
                entity_candidate_count=sum(
                    len(items) for items in entity_candidates.values()
                ),
            ),
        )

    async def resolve_once(self, context: RequestContext) -> ResolutionAttempt:
        prepared = await self.prepare(context)
        model_started = self._timer()
        model_result = await self._adapter.invoke(
            prepared.prompt,
            timeout_seconds=self._remaining_model_seconds(context),
        )
        model_ms = _duration_ms(model_started, self._timer())

        validation_started = self._timer()
        resolution = self.validate_response(prepared, model_result.content)
        validation_ms = _duration_ms(validation_started, self._timer())
        usage = _usage_telemetry(model_result.usage)
        return ResolutionAttempt(
            resolution=resolution,
            telemetry=ResolutionTelemetry(
                normalization_ms=prepared.telemetry.normalization_ms,
                candidate_ms=prepared.telemetry.candidate_ms,
                model_ms=model_ms,
                validation_ms=validation_ms,
                semantic_candidate_count=prepared.telemetry.semantic_candidate_count,
                entity_candidate_count=prepared.telemetry.entity_candidate_count,
                frame_count=len(resolution.canonical_frames),
                context_link_count=len(resolution.context_links),
                usage=usage,
                stable_code=_SUCCESS_CODE,
            ),
        )

    def validate_response(
        self,
        prepared: PreparedResolutionRequest,
        content: str,
    ) -> ValidatedIntentResolution:
        _reject_non_strict_json(content)
        try:
            draft = IntentResolutionDraft.model_validate_json(content)
        except ValidationError:
            raise ResolverContractError(MODEL_SCHEMA_INVALID) from None

        semantic_state = validate_semantics(
            draft,
            prepared.context,
            prepared.normalized,
            prepared.view,
            self._catalog,
        )
        context_state = validate_context_graph(semantic_state)
        draft_hash = canonical_sha256(draft)
        resolution_seed = canonical_sha256(
            {
                "active_dataset_manifest_hash": (
                    prepared.view.active_dataset_pin.manifest_hash
                ),
                "build_manifest": prepared.view.build_manifest.model_dump(mode="json"),
                "draft_hash": draft_hash,
                "request_key": prepared.context.request_key,
                "run_id": prepared.context.run_id,
            }
        )
        return finalize_resolution(
            context_state,
            ResolutionFinalizationMetadata(
                request_key=prepared.context.request_key,
                run_id=prepared.context.run_id,
                dataset_version=prepared.context.dataset_version,
                producer="intent-resolver",
                created_at=prepared.context.created_at,
                resolution_id=f"resolution-{resolution_seed}",
                draft_hash=draft_hash,
                build_manifest=prepared.view.build_manifest,
                active_dataset_manifest_hash=(
                    prepared.view.active_dataset_pin.manifest_hash
                ),
            ),
        )

    def _remaining_model_seconds(self, context: RequestContext) -> float:
        remaining = (context.deadline_at - self._utcnow()).total_seconds()
        if remaining <= 0:
            raise ModelInvocationError(MODEL_TIMEOUT)
        return min(MAX_MODEL_TIMEOUT_SECONDS, remaining)


def build_repair_envelope(
    prepared: PreparedResolutionRequest,
    failure: ResolverContractError,
) -> ResolverPromptEnvelope:
    instruction = _REPAIR_INSTRUCTIONS.get(failure.code)
    if instruction is None:
        raise ValueError("REPAIR_CODE_NOT_ALLOWED")
    original_prompt_hash = canonical_sha256(
        {
            "response_schema": prepared.prompt.response_schema,
            "system_message": prepared.prompt.system_message,
            "user_message": prepared.prompt.user_message,
        }
    )
    return ResolverPromptEnvelope(
        system_message=(
            f"{prepared.prompt.system_message} Apply this correction only: {instruction}"
        ),
        user_message=json.dumps(
            {
                "view": prepared.view.model_dump(mode="json"),
                "original_prompt_hash": original_prompt_hash,
                "failure_code": failure.code,
                "correction_instruction": instruction,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        response_schema=prepared.prompt.response_schema,
    )


def _entity_mentions(
    context: RequestContext,
    normalized: NormalizedRequest,
) -> tuple[Mention, ...]:
    segments = {segment.segment_id: segment for segment in normalized.segments}
    mentions: list[Mention] = []
    for source in context.named_entities:
        segment = segments[source.segment_id]
        start = segment.original_text.find(source.text)
        if start < 0:
            raise RequestNormalizationError(
                "REQUEST_CONTRACT_INVALID: named entity text is absent from its segment"
            )
        end = start + len(source.text)
        normalized_text = normalize_segment(
            source.mention_id, source.text
        ).normalized_text
        mentions.append(
            Mention(
                mention_id=source.mention_id,
                segment_id=source.segment_id,
                text=source.text,
                normalized_text=normalized_text,
                start_char=start,
                end_char=end,
            )
        )
    return tuple(mentions)


def _reject_non_strict_json(content: str) -> None:
    try:
        parsed = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _value: _raise_non_json_number(),
        )
        if not isinstance(parsed, dict):
            raise ValueError
    except (json.JSONDecodeError, TypeError, ValueError):
        raise ResolverContractError(MODEL_SCHEMA_INVALID) from None


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _raise_non_json_number() -> None:
    raise ValueError("non-JSON numeric constant")


def _usage_telemetry(usage: Mapping[str, int]) -> ModelUsageTelemetry:
    try:
        return ModelUsageTelemetry(
            prompt_tokens=usage["promptTokens"],
            completion_tokens=usage["completionTokens"],
            total_tokens=usage["totalTokens"],
        )
    except (KeyError, ValidationError):
        raise ResolverContractError(MODEL_SCHEMA_INVALID) from None


def _duration_ms(started: float, completed: float) -> int:
    return max(0, round((completed - started) * 1_000))
