"""One-call assembly of the ontology-grounded intent resolver pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from time import perf_counter
from typing import Protocol

from pydantic import Field, ValidationError, model_validator

from financial_agent.contracts.base import ContractModel
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import ProductFamily
from financial_agent.contracts.request import RequestContext

from .candidates import (
    MAX_ENTITY_MENTIONS,
    EntityCandidate,
    Mention,
    SemanticCandidateSet,
    generate_semantic_candidates,
)
from .assembler import assemble_proposal
from .hybrid_assembler import assemble_hybrid_proposal
from .hybrid_prompt import build_hybrid_prompt
from .hybrid_proposal import IntentResolutionProposalV3
from .axis_locks import ExactSemanticLock, build_exact_semantic_locks
from .catalog import SemanticCatalogSnapshot
from .clova import ModelInvocationResult
from .context import (
    ResolutionFinalizationMetadata,
    finalize_resolution,
    validate_context_graph,
)
from .draft import ProductFamilyChoice
from .errors import (
    MODEL_INVALID_FRAME_REFERENCE,
    MODEL_INVALID_SEMANTIC_COVERAGE,
    MODEL_PROPOSAL_SCHEMA_INVALID,
    MODEL_SCHEMA_INVALID,
    MODEL_TIMEOUT,
    MODEL_UNKNOWN_EVIDENCE_ID,
    ModelInvocationError,
    ResolverContractError,
)
from .literals import LiteralCandidate, extract_literals
from .mention_spans import MentionSpanSetV1, generate_mention_spans
from .normalization import (
    NormalizedRequest,
    RequestNormalizationError,
    normalize_request,
    normalize_segment,
)
from .prompt import ResolverPromptEnvelope, build_prompt, model_safe_view_payload
from .proposal import IntentResolutionProposalV2
from .query_contract_judge import QueryContractJudge, QueryContractJudgeResult
from .query_contract_registry import QueryContractRegistry
from .query_contract_solver import (
    QueryContractCandidate,
    QueryContractCandidateSet,
    QueryContractFrameCandidateSet,
    solve_query_contracts,
)
from .query_contracts import (
    ContractReadiness,
    ContractReadinessRecordV2,
    ProvenanceSourceKind,
)
from .resolution import (
    ResolutionIssue,
    ResolverBuildManifest,
    ValidatedIntentFrameV2,
    ValidatedIntentResolutionV2,
    ValidatedIntentResolutionV3,
    ValidationEvent,
)
from .slot_resolution import resolve_ambiguous_slots
from .task_binding import (
    TaskBindingError,
    TaskBoundIntentResolution,
    TaskReadiness,
    bind_task_slots,
)
from .task_contracts import TaskContractRegistry
from .types import ChoiceState, ResolutionStatus, SemanticTag
from .validation import validate_semantics
from .view import (
    ActiveDatasetPin,
    ResolverView,
    ResolverViewV3,
    build_resolver_view,
    build_resolver_view_v3,
    validate_hybrid_resolver_pins,
    validate_resolver_pins,
    model_safe_resolver_view_v3_payload,
)


_SUCCESS_CODE = "RESOLUTION_VALIDATED"
_TASK_SUCCESS_CODE = "TASK_RESOLUTION_VALIDATED"
_QUERY_CONTRACT_SUCCESS_CODE = "QUERY_CONTRACT_RESOLUTION_VALIDATED"
_REPAIR_INSTRUCTIONS = {
    MODEL_PROPOSAL_SCHEMA_INVALID: (
        "Return a ProposalV2 with the exact schema shape. Select only offered "
        "identifiers and valid frame ordinals."
    ),
    MODEL_UNKNOWN_EVIDENCE_ID: (
        "Select only offered evidence identifiers and valid frame ordinals."
    ),
    MODEL_INVALID_FRAME_REFERENCE: (
        "Select only offered reference identifiers and valid backward frame ordinals."
    ),
    MODEL_INVALID_SEMANTIC_COVERAGE: (
        "Select only offered identifiers and valid frame ordinals for semantic coverage."
    ),
}
_HYBRID_REPAIR_INSTRUCTIONS = {
    **_REPAIR_INSTRUCTIONS,
    "MODEL_UNKNOWN_ID": (
        "Select only offered mention, semantic, entity, reference, and evidence IDs."
    ),
    "MODEL_EXACT_LOCK_CONFLICT": (
        "Preserve every exact-lock projection exactly as offered."
    ),
    "MODEL_OUTPUT_DISABLED": (
        "Leave every request-disabled entity or reference branch empty."
    ),
    "MODEL_INAPPLICABLE_CONCEPT": (
        "Select only concepts applicable to the selected product families and types."
    ),
    "MODEL_INVALID_RELATION": (
        "Use only relation endpoints compatible with the registered relation."
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


class TaskBoundResolutionTelemetry(ResolutionTelemetry):
    model_call_count: int = Field(ge=1, le=2)
    conditional_slot_call_used: bool


class QueryContractResolutionTelemetry(ContractModel):
    normalization_ms: int = Field(ge=0)
    candidate_ms: int = Field(ge=0)
    axis_model_ms: int = Field(ge=0)
    repair_ms: int = Field(default=0, ge=0)
    validation_ms: int = Field(ge=0)
    exact_lock_reconciliation_ms: int = Field(ge=0)
    candidate_solve_ms: int = Field(ge=0)
    tie_break_ms: int = Field(ge=0)
    candidate_judge_ms: int = Field(ge=0)
    model_call_count: int = Field(ge=1, le=2)
    repair_used: bool
    candidate_judge_used: bool
    offered_candidate_count: int = Field(ge=0)
    complete_candidate_count: int = Field(ge=0)
    rejection_count: int = Field(ge=0)
    frame_count: int = Field(ge=1, le=16)
    usage: ModelUsageTelemetry
    stable_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_model_allowance(self) -> "QueryContractResolutionTelemetry":
        if self.repair_used and self.candidate_judge_used:
            raise ValueError("MODEL_CALL_ALLOWANCE_CONFLICT")
        expected_calls = 1 + int(self.repair_used or self.candidate_judge_used)
        if self.model_call_count != expected_calls:
            raise ValueError("MODEL_CALL_COUNT_MISMATCH")
        return self


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
class PreparedHybridResolutionRequest:
    """V3 construction result, intentionally before any HCX invocation."""

    context: RequestContext
    normalized: NormalizedRequest
    literals: tuple[LiteralCandidate, ...]
    semantic_candidates: SemanticCandidateSet
    entity_candidates: Mapping[str, tuple[EntityCandidate, ...]]
    mention_spans: MentionSpanSetV1
    view: ResolverViewV3
    prompt: ResolverPromptEnvelope
    telemetry: _PreparationTelemetry


@dataclass(frozen=True, slots=True)
class ResolutionAttempt:
    resolution: ValidatedIntentResolutionV2
    telemetry: ResolutionTelemetry


@dataclass(frozen=True, slots=True)
class TaskBoundResolutionAttempt:
    resolution: TaskBoundIntentResolution
    telemetry: TaskBoundResolutionTelemetry


@dataclass(frozen=True, slots=True)
class QueryContractResolutionAttempt:
    resolution: ValidatedIntentResolutionV2
    candidates: QueryContractCandidateSet
    telemetry: QueryContractResolutionTelemetry


@dataclass(frozen=True, slots=True)
class QueryContractResolutionAttemptV3:
    resolution: ValidatedIntentResolutionV3
    candidates: QueryContractCandidateSet
    telemetry: QueryContractResolutionTelemetry


class IntentResolverService:
    def __init__(
        self,
        *,
        adapter: _ModelAdapter,
        entity_repository: _EntityRepository,
        catalog: SemanticCatalogSnapshot,
        manifest: ResolverBuildManifest,
        active_dataset_pin: ActiveDatasetPin,
        task_contract_registry: TaskContractRegistry | None = None,
        query_contract_registry: QueryContractRegistry | None = None,
        utcnow: Callable[[], datetime] | None = None,
        timer: Callable[[], float] | None = None,
    ) -> None:
        self._adapter = adapter
        self._entity_repository = entity_repository
        self._catalog = catalog
        self._manifest = manifest
        self._active_dataset_pin = active_dataset_pin
        self._task_contract_registry = task_contract_registry
        self._query_contract_registry = query_contract_registry
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._timer = timer or perf_counter

    async def prepare(self, context: RequestContext) -> PreparedResolutionRequest:
        normalization_started = self._timer()
        normalized = normalize_request(context)
        if len(context.named_entities) > MAX_ENTITY_MENTIONS:
            raise RequestNormalizationError(
                "REQUEST_CONTRACT_INVALID: entity mention limit exceeded"
            )
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
        exact_semantic_locks = build_exact_semantic_locks(
            normalized,
            self._catalog,
            semantic_candidates=semantic_candidates,
            literals=literals,
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
            exact_semantic_locks=exact_semantic_locks,
        )
        prompt = build_prompt(context, view, self._catalog)
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

    async def prepare_hybrid(
        self, context: RequestContext
    ) -> PreparedHybridResolutionRequest:
        """Prepare the shadow V3 request without invoking or validating HCX."""
        normalization_started = self._timer()
        normalized = normalize_request(context)
        if len(context.named_entities) > MAX_ENTITY_MENTIONS:
            raise RequestNormalizationError(
                "REQUEST_CONTRACT_INVALID: entity mention limit exceeded"
            )
        validate_hybrid_resolver_pins(
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
        entity_mentions = _hybrid_entity_mentions(context, normalized)
        entity_candidates = await self._entity_repository.search_batch(
            context.dataset_version,
            entity_mentions,
        )
        exact_semantic_locks = build_exact_semantic_locks(
            normalized,
            self._catalog,
            semantic_candidates=semantic_candidates,
            literals=literals,
        )
        mention_spans = generate_mention_spans(
            normalized,
            tuple(
                group.mention
                for group in semantic_candidates.by_mention
                if any(
                    item.match_kind in {"canonical_id", "direct_alias"}
                    for item in group.items
                )
            ),
            literals,
            entity_mentions,
            normalized.reference_candidates,
        )
        view = build_resolver_view_v3(
            context=context,
            normalized=normalized,
            literals=literals,
            semantic_candidates=semantic_candidates,
            entity_candidates=entity_candidates,
            manifest=self._manifest,
            active_dataset_pin=self._active_dataset_pin,
            catalog=self._catalog,
            mention_spans=mention_spans,
            exact_semantic_locks=exact_semantic_locks,
        )
        prompt = build_hybrid_prompt(context, view, self._catalog)
        candidate_ms = _duration_ms(candidates_started, self._timer())
        return PreparedHybridResolutionRequest(
            context=context,
            normalized=normalized,
            literals=literals,
            semantic_candidates=semantic_candidates,
            entity_candidates=entity_candidates,
            mention_spans=mention_spans,
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

    async def resolve_task_bound(
        self, context: RequestContext
    ) -> TaskBoundResolutionAttempt:
        """Resolve axes once, then bind the selected server task contract."""
        if self._task_contract_registry is None:
            raise TaskBindingError("TASK_CONTRACT_REGISTRY_MISSING")
        prepared = await self.prepare(context)
        model_started = self._timer()
        first_result = await self._adapter.invoke(
            prepared.prompt,
            timeout_seconds=self._remaining_model_seconds(context),
        )
        resolution = self.validate_axis_response(prepared, first_result.content)
        bound = bind_task_slots(
            resolution,
            prepared.view,
            self._task_contract_registry,
        )
        usage = dict(first_result.usage)
        model_call_count = 1
        if (
            not any(
                contract.readiness is TaskReadiness.BLOCKED
                for contract in bound.task_contracts
            )
            and any(
                contract.readiness is TaskReadiness.AMBIGUOUS
                for contract in bound.task_contracts
            )
        ):
            bound, second_usage = await resolve_ambiguous_slots(
                adapter=self._adapter,
                context=context,
                bound=bound,
                timeout_seconds=self._remaining_model_seconds(context),
            )
            usage = _merge_usage(usage, second_usage)
            model_call_count = 2
        model_ms = _duration_ms(model_started, self._timer())

        telemetry = TaskBoundResolutionTelemetry(
            normalization_ms=prepared.telemetry.normalization_ms,
            candidate_ms=prepared.telemetry.candidate_ms,
            model_ms=model_ms,
            validation_ms=0,
            semantic_candidate_count=prepared.telemetry.semantic_candidate_count,
            entity_candidate_count=prepared.telemetry.entity_candidate_count,
            frame_count=len(bound.resolution.canonical_frames),
            context_link_count=len(bound.resolution.context_links),
            usage=_usage_telemetry(usage),
            stable_code=_TASK_SUCCESS_CODE,
            model_call_count=model_call_count,
            conditional_slot_call_used=bound.conditional_slot_call_used,
        )
        return TaskBoundResolutionAttempt(resolution=bound, telemetry=telemetry)

    async def resolve_query_contract_candidates(
        self, context: RequestContext
    ) -> QueryContractResolutionAttempt:
        """Resolve axes and bounded V2 contracts under one shared extra-call allowance."""

        if self._query_contract_registry is None:
            raise ResolverContractError("QUERY_CONTRACT_REGISTRY_MISSING")
        prepared = await self.prepare(context)

        axis_started = self._timer()
        first_result = await self._adapter.invoke(
            prepared.prompt,
            timeout_seconds=self._remaining_model_seconds(context),
        )
        axis_model_ms = _duration_ms(axis_started, self._timer())
        usage = dict(first_result.usage)
        repair_used = False

        validation_started = self._timer()
        validation_ms = 0
        try:
            resolution = self.validate_axis_response(prepared, first_result.content)
        except ResolverContractError as failure:
            validation_ms += _duration_ms(validation_started, self._timer())
            if failure.code not in _REPAIR_INSTRUCTIONS:
                raise
            repair_envelope = build_repair_envelope(prepared, failure)
            repair_started = self._timer()
            repaired_result = await self._adapter.invoke(
                repair_envelope,
                timeout_seconds=self._remaining_model_seconds(context),
            )
            axis_model_ms += _duration_ms(repair_started, self._timer())
            validation_started = self._timer()
            resolution = self.validate_axis_response(prepared, repaired_result.content)
            validation_ms += _duration_ms(validation_started, self._timer())
            resolution = resolution.model_copy(
                update={
                    "repair_used": True,
                    "invalid_attempt_hashes": tuple(
                        sorted(
                            {
                                *resolution.invalid_attempt_hashes,
                                canonical_sha256(
                                    {"invalid_model_content": first_result.content}
                                ),
                            }
                        )
                    ),
                }
            )
            usage = _merge_usage(usage, repaired_result.usage)
            repair_used = True
        else:
            validation_ms += _duration_ms(validation_started, self._timer())

        reconciliation_started = self._timer()
        resolution = reconcile_exact_axis_locks(
            resolution,
            prepared.view.exact_semantic_locks,
            prepared.semantic_candidates,
            prepared.view,
        )
        exact_lock_reconciliation_ms = _duration_ms(
            reconciliation_started, self._timer()
        )

        solve_started = self._timer()
        candidates = solve_query_contracts(
            resolution=resolution,
            view=prepared.view,
            exact_locks=prepared.view.exact_semantic_locks,
            registry=self._query_contract_registry,
        )
        candidate_solve_ms = _duration_ms(solve_started, self._timer())
        offered_candidate_count = len(candidates.complete_candidates)

        tie_break_started = self._timer()
        candidates = _apply_deterministic_tie_break(candidates)
        tie_break_ms = _duration_ms(tie_break_started, self._timer())

        judge_ms = 0
        judge_used = False
        ambiguous_frames = tuple(
            frame
            for frame in candidates.frames
            if len(frame.complete_candidates) > 1
            and "CANDIDATE_BOUND_REACHED"
            not in frame.contract_readiness.reason_codes
        )
        if not repair_used and len(ambiguous_frames) == 1:
            ambiguous = ambiguous_frames[0]
            frame = next(
                item
                for item in resolution.canonical_frames
                if item.frame_id == ambiguous.frame_id
            )
            judge_started = self._timer()
            judged = await QueryContractJudge(self._adapter).select_offered_id(
                question=context.question,
                frame=frame,
                view=prepared.view,
                candidates=ambiguous.complete_candidates,
                timeout_seconds=max(
                    0.0, (context.deadline_at - self._utcnow()).total_seconds()
                ),
            )
            judge_ms = _duration_ms(judge_started, self._timer())
            judge_used = judged.model_call_used
            if judged.usage:
                usage = _merge_usage(usage, judged.usage)
            candidates = _apply_judge_result(candidates, ambiguous.frame_id, judged)

        telemetry = QueryContractResolutionTelemetry(
            normalization_ms=prepared.telemetry.normalization_ms,
            candidate_ms=prepared.telemetry.candidate_ms,
            axis_model_ms=axis_model_ms,
            validation_ms=validation_ms,
            exact_lock_reconciliation_ms=exact_lock_reconciliation_ms,
            candidate_solve_ms=candidate_solve_ms,
            tie_break_ms=tie_break_ms,
            candidate_judge_ms=judge_ms,
            model_call_count=1 + int(repair_used or judge_used),
            repair_used=repair_used,
            candidate_judge_used=judge_used,
            offered_candidate_count=offered_candidate_count,
            complete_candidate_count=len(candidates.complete_candidates),
            rejection_count=len(candidates.rejections),
            frame_count=len(resolution.canonical_frames),
            usage=_usage_telemetry(usage),
            stable_code=_QUERY_CONTRACT_SUCCESS_CODE,
        )
        return QueryContractResolutionAttempt(
            resolution=resolution,
            candidates=candidates,
            telemetry=telemetry,
        )

    async def resolve_hybrid_query_contract_candidates(
        self, context: RequestContext
    ) -> QueryContractResolutionAttemptV3:
        """Resolve the complete V3 shadow path under one shared extra-call allowance."""

        if self._query_contract_registry is None:
            raise ResolverContractError("QUERY_CONTRACT_REGISTRY_MISSING")
        prepared = await self.prepare_hybrid(context)

        model_started = self._timer()
        first_result = await self._adapter.invoke(
            prepared.prompt,
            timeout_seconds=self._remaining_model_seconds(context),
        )
        model_ms = _duration_ms(model_started, self._timer())
        repair_ms = 0
        usage = dict(first_result.usage)
        repair_used = False

        validation_started = self._timer()
        validation_ms = 0
        try:
            resolution = self.validate_hybrid_response(prepared, first_result.content)
        except ResolverContractError as failure:
            validation_ms += _duration_ms(validation_started, self._timer())
            if failure.code not in _HYBRID_REPAIR_INSTRUCTIONS:
                raise
            repair_envelope = build_hybrid_repair_envelope(prepared, failure)
            repair_started = self._timer()
            repaired_result = await self._adapter.invoke(
                repair_envelope,
                timeout_seconds=self._remaining_model_seconds(context),
            )
            repair_ms = _duration_ms(repair_started, self._timer())
            validation_started = self._timer()
            resolution = self.validate_hybrid_response(
                prepared, repaired_result.content
            )
            validation_ms += _duration_ms(validation_started, self._timer())
            resolution = resolution.model_copy(
                update={
                    "repair_used": True,
                    "invalid_attempt_hashes": tuple(
                        sorted(
                            {
                                *resolution.invalid_attempt_hashes,
                                canonical_sha256(
                                    {"invalid_model_content": first_result.content}
                                ),
                            }
                        )
                    ),
                }
            )
            usage = _merge_usage(usage, repaired_result.usage)
            repair_used = True
        else:
            validation_ms += _duration_ms(validation_started, self._timer())

        solve_started = self._timer()
        candidates = solve_query_contracts(
            resolution=resolution,
            view=prepared.view,
            exact_locks=prepared.view.exact_semantic_locks,
            registry=self._query_contract_registry,
            semantic_catalog=self._catalog,
        )
        candidate_solve_ms = _duration_ms(solve_started, self._timer())
        offered_candidate_count = len(candidates.complete_candidates)

        tie_break_started = self._timer()
        candidates = _apply_deterministic_tie_break(candidates)
        tie_break_ms = _duration_ms(tie_break_started, self._timer())

        judge_ms = 0
        judge_used = False
        ambiguous_frames = tuple(
            frame
            for frame in candidates.frames
            if len(frame.complete_candidates) > 1
            and "CANDIDATE_BOUND_REACHED"
            not in frame.contract_readiness.reason_codes
        )
        if not repair_used and len(ambiguous_frames) == 1:
            ambiguous = ambiguous_frames[0]
            frame = next(
                item
                for item in resolution.canonical_frames
                if item.frame_id == ambiguous.frame_id
            )
            judge_started = self._timer()
            judged = await QueryContractJudge(self._adapter).select_offered_id(
                question=context.question,
                frame=frame,
                view=prepared.view,
                candidates=ambiguous.complete_candidates,
                timeout_seconds=max(
                    0.0, (context.deadline_at - self._utcnow()).total_seconds()
                ),
            )
            judge_ms = _duration_ms(judge_started, self._timer())
            judge_used = judged.model_call_used
            if judged.usage:
                usage = _merge_usage(usage, judged.usage)
            candidates = _apply_judge_result(
                candidates, ambiguous.frame_id, judged
            )

        telemetry = QueryContractResolutionTelemetry(
            normalization_ms=prepared.telemetry.normalization_ms,
            candidate_ms=prepared.telemetry.candidate_ms,
            axis_model_ms=model_ms,
            repair_ms=repair_ms,
            validation_ms=validation_ms,
            exact_lock_reconciliation_ms=0,
            candidate_solve_ms=candidate_solve_ms,
            tie_break_ms=tie_break_ms,
            candidate_judge_ms=judge_ms,
            model_call_count=1 + int(repair_used or judge_used),
            repair_used=repair_used,
            candidate_judge_used=judge_used,
            offered_candidate_count=offered_candidate_count,
            complete_candidate_count=len(candidates.complete_candidates),
            rejection_count=len(candidates.rejections),
            frame_count=len(resolution.canonical_frames),
            usage=_usage_telemetry(usage),
            stable_code=_QUERY_CONTRACT_SUCCESS_CODE,
        )
        return QueryContractResolutionAttemptV3(
            resolution=resolution,
            candidates=candidates,
            telemetry=telemetry,
        )

    def validate_axis_response(
        self,
        prepared: PreparedResolutionRequest,
        content: str,
    ) -> ValidatedIntentResolutionV2:
        _reject_non_strict_json(content)
        try:
            proposal = IntentResolutionProposalV2.model_validate_json(content)
        except ValidationError:
            raise ResolverContractError(MODEL_PROPOSAL_SCHEMA_INVALID) from None
        if any(frame.slot_assignments for frame in proposal.frames):
            raise ResolverContractError(MODEL_PROPOSAL_SCHEMA_INVALID)
        return self.validate_response(prepared, content)

    def validate_hybrid_response(
        self,
        prepared: PreparedHybridResolutionRequest,
        content: str,
    ) -> ValidatedIntentResolutionV3:
        _reject_non_strict_json(content)
        try:
            proposal = IntentResolutionProposalV3.model_validate_json(content)
        except ValidationError:
            raise ResolverContractError(MODEL_PROPOSAL_SCHEMA_INVALID) from None
        draft = assemble_hybrid_proposal(
            proposal, prepared.normalized, prepared.view, self._catalog
        )
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
        resolution = finalize_resolution(
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
        if not isinstance(resolution, ValidatedIntentResolutionV3):
            raise RuntimeError("assembled hybrid proposal did not finalize as v3")
        return resolution

    def validate_response(
        self,
        prepared: PreparedResolutionRequest,
        content: str,
    ) -> ValidatedIntentResolutionV2:
        _reject_non_strict_json(content)
        try:
            proposal = IntentResolutionProposalV2.model_validate_json(content)
        except ValidationError:
            raise ResolverContractError(MODEL_PROPOSAL_SCHEMA_INVALID) from None
        draft = assemble_proposal(
            proposal, prepared.normalized, prepared.view, self._catalog
        )

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
        resolution = finalize_resolution(
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
        if not isinstance(resolution, ValidatedIntentResolutionV2):
            raise RuntimeError("assembled proposal did not finalize as v2")
        return resolution

    def _remaining_model_seconds(self, context: RequestContext) -> float:
        remaining = (context.deadline_at - self._utcnow()).total_seconds()
        if remaining <= 0:
            raise ModelInvocationError(MODEL_TIMEOUT)
        return remaining


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
                "context": prepared.context.model_dump(mode="json"),
                "view": model_safe_view_payload(prepared.view),
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


def build_hybrid_repair_envelope(
    prepared: PreparedHybridResolutionRequest,
    failure: ResolverContractError,
) -> ResolverPromptEnvelope:
    instruction = _HYBRID_REPAIR_INSTRUCTIONS.get(failure.code)
    if instruction is None:
        raise ValueError("REPAIR_CODE_NOT_ALLOWED")
    if failure.code == MODEL_PROPOSAL_SCHEMA_INVALID:
        instruction = (
            "Return a ProposalV3 with the exact schema shape. Link only offered "
            "mention IDs to registered compact-catalog semantic IDs."
        )
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
                "context": prepared.context.model_dump(mode="json"),
                "view": model_safe_resolver_view_v3_payload(prepared.view),
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


def reconcile_exact_axis_locks(
    resolution: ValidatedIntentResolutionV2,
    locks: tuple[ExactSemanticLock, ...],
    semantic_candidates: SemanticCandidateSet,
    view: ResolverView,
) -> ValidatedIntentResolutionV2:
    """Make exact family evidence authoritative after model semantic validation."""

    mentions_by_id = {
        group.mention.mention_id: group.mention
        for group in semantic_candidates.by_mention
    }
    family_locks = tuple(item for item in locks if item.role == "product_family")
    if not family_locks:
        return resolution

    exact_evidence_by_lock = {
        lock.lock_id: tuple(
            sorted(
                {
                    evidence.evidence_id
                    for source_ref in lock.evidence_span_ids
                    if (mention := mentions_by_id.get(source_ref)) is not None
                    for evidence in view.evidence_candidates
                    if evidence.segment_id == mention.segment_id
                    and evidence.start_char == mention.start_char
                    and evidence.end_char == mention.end_char
                    and lock.canonical_id in evidence.offered_semantic_ids
                }
            )
        )
        for lock in family_locks
    }
    locks_by_frame: dict[str, list[ExactSemanticLock]] = {
        frame.frame_id: [] for frame in resolution.canonical_frames
    }
    for lock in family_locks:
        exact_evidence = set(exact_evidence_by_lock[lock.lock_id])
        owners = tuple(
            frame
            for frame in resolution.canonical_frames
            if exact_evidence
            & set(frame.product_family_choice.evidence_span_ids)
        )
        if len(owners) != 1:
            owners = tuple(
                frame
                for frame in resolution.canonical_frames
                if exact_evidence & set(frame.evidence_span_ids)
            )
        if len(owners) != 1 and len(resolution.canonical_frames) == 1:
            owners = resolution.canonical_frames
        if len(owners) != 1:
            raise ResolverContractError("EXACT_FAMILY_LOCK_UNATTRIBUTED")
        locks_by_frame[owners[0].frame_id].append(lock)

    changed_frame_ids: list[str] = []
    old_choices: dict[str, ProductFamilyChoice] = {}
    frames: list[ValidatedIntentFrameV2] = []
    for frame in resolution.canonical_frames:
        applicable = tuple(locks_by_frame[frame.frame_id])
        if not applicable:
            frames.append(frame)
            continue
        locked_families = tuple(
            sorted(
                {ProductFamily(item.canonical_id) for item in applicable},
                key=lambda item: item.value,
            )
        )
        exact_evidence_ids = tuple(
            sorted(
                {
                    evidence_id
                    for lock in applicable
                    for evidence_id in exact_evidence_by_lock[lock.lock_id]
                }
            )
        )
        if (
            frame.product_family_choice.state is ChoiceState.SELECTED
            and frame.product_family_choice.selected_ids == locked_families
        ):
            frames.append(frame)
            continue
        if frame.product_family_choice.state is ChoiceState.SELECTED:
            raise ResolverContractError("EXACT_LOCK_CONFLICT")
        old_choices[frame.frame_id] = frame.product_family_choice
        changed_frame_ids.append(frame.frame_id)
        frames.append(
            frame.model_copy(
                update={
                    "product_family_choice": ProductFamilyChoice(
                        state=ChoiceState.SELECTED,
                        selected_ids=locked_families,
                        evidence_span_ids=(
                            exact_evidence_ids
                            or frame.product_family_choice.evidence_span_ids
                        ),
                        reason_code="exact_lock",
                    ),
                }
            )
        )
    if not changed_frame_ids:
        return resolution

    changed = set(changed_frame_ids)
    issues = tuple(
        issue
        for issue in resolution.issues
        if not _is_reconciled_family_issue(
            issue, changed, old_choices, resolution
        )
    )
    frames = [
        frame.model_copy(
            update={
                "frame_status": _reconciled_frame_status(
                    frame, issues, resolution, view
                )
            }
        )
        for frame in frames
    ]
    events = (
        *resolution.validation_events,
        *(
            ValidationEvent(
                event_id=f"event-exact-family-{frame_id}",
                stage="exact-lock-reconciliation",
                code="EXACT_FAMILY_LOCK_APPLIED",
                related_ids=(frame_id,),
            )
            for frame_id in sorted(changed)
        ),
    )
    resolution_status = _resolution_status_from_frames(frames)
    selected_families = {
        family
        for frame in frames
        for family in frame.product_family_choice.selected_ids
    }
    final_tags = set(resolution.final_tags)
    if len(selected_families) > 1:
        final_tags.add(SemanticTag.CROSS_FAMILY)
    else:
        final_tags.discard(SemanticTag.CROSS_FAMILY)
    reconciliation_hash = canonical_sha256(
        {
            "prior_resolution_id": resolution.resolution_id,
            "frames": [item.model_dump(mode="json") for item in frames],
            "events": [item.model_dump(mode="json") for item in events],
        }
    )
    resolution_id = f"resolution-{reconciliation_hash}"
    return resolution.model_copy(
        update={
            "resolution_id": resolution_id,
            "canonical_frames": tuple(frames),
            "issues": issues,
            "validation_events": events,
            "resolution_status": resolution_status,
            "final_tags": tuple(sorted(final_tags, key=lambda item: item.value)),
        }
    )


def _reconciled_frame_status(
    frame: ValidatedIntentFrameV2,
    issues: tuple[ResolutionIssue, ...],
    resolution: ValidatedIntentResolutionV2,
    view: ResolverView,
) -> ResolutionStatus:
    codes: set[str] = set()
    unowned_issue = False
    for issue in issues:
        affected = _issue_owner_frame_ids(issue, resolution, view)
        if not affected:
            unowned_issue = True
        elif frame.frame_id in affected:
            codes.add(issue.code)
    if codes & {
        "SEMANTIC_CONCEPT_UNMAPPED",
        "SEMANTIC_DOMAIN_UNMAPPED",
        "SEMANTIC_OPERATION_UNSUPPORTED",
        "SEMANTIC_CRITICAL_SLOT_MISSING",
    }:
        return ResolutionStatus.UNMAPPED
    if codes & {"REFERENCE_UNRESOLVED", "CONTEXT_UNRESOLVED"}:
        return ResolutionStatus.CONTEXT_UNRESOLVED
    if codes:
        return ResolutionStatus.AMBIGUOUS
    if unowned_issue and frame.frame_status is not ResolutionStatus.RESOLVED:
        return frame.frame_status
    return ResolutionStatus.RESOLVED


def _is_reconciled_family_issue(
    issue: ResolutionIssue,
    changed_frame_ids: set[str],
    old_choices: dict[str, ProductFamilyChoice],
    resolution: ValidatedIntentResolutionV2,
) -> bool:
    if len(issue.related_ids) != 1 or issue.related_ids[0] not in changed_frame_ids:
        return False
    frame_id = issue.related_ids[0]
    old_choice = old_choices[frame_id]
    expected_code = {
        ChoiceState.AMBIGUOUS: "AMBIGUITY_UNRESOLVED",
        ChoiceState.UNMAPPED: "SEMANTIC_CONCEPT_UNMAPPED",
    }.get(old_choice.state)
    if issue.code != expected_code or issue.evidence_span_ids != old_choice.evidence_span_ids:
        return False
    original = next(item for item in resolution.canonical_frames if item.frame_id == frame_id)
    return not (
        original.action_choice.state is old_choice.state
        and original.action_choice.evidence_span_ids == issue.evidence_span_ids
    )


def _issue_owner_frame_ids(
    issue: ResolutionIssue,
    resolution: ValidatedIntentResolutionV2,
    view: ResolverView,
) -> set[str]:
    frame_ids = {item.frame_id for item in resolution.canonical_frames}
    link_frames = {
        link.context_link_id: link.consumer_frame_id for link in resolution.context_links
    }
    reference_frames: dict[str, set[str]] = {}
    for link in resolution.context_links:
        reference_frames.setdefault(link.reference_id, set()).add(link.consumer_frame_id)
    affected = set(issue.related_ids) & frame_ids
    affected.update(
        link_frames[related_id]
        for related_id in issue.related_ids
        if related_id in link_frames
    )
    for related_id in issue.related_ids:
        affected.update(reference_frames.get(related_id, ()))

    issue_evidence = set(issue.evidence_span_ids)
    if issue_evidence:
        affected.update(
            frame.frame_id
            for frame in resolution.canonical_frames
            if issue_evidence & set(frame.evidence_span_ids)
        )

    references = {
        item.reference_id: item
        for item in view.reference_candidates
        if item.reference_id in issue.related_ids
    }
    evidence_by_reference = {
        reference_id: {
            evidence.evidence_id
            for evidence in view.evidence_candidates
            if evidence.segment_id == reference.segment_id
            and evidence.start_char == reference.start_char
            and evidence.end_char == reference.end_char
            and evidence.text == reference.text
        }
        for reference_id, reference in references.items()
    }
    for reference_id, reference in references.items():
        evidence_ids = evidence_by_reference[reference_id]
        evidence_owners = {
            frame.frame_id
            for frame in resolution.canonical_frames
            if evidence_ids & set(frame.evidence_span_ids)
        }
        if evidence_owners:
            affected.update(evidence_owners)
            continue
        segment_owners = {
            frame.frame_id
            for frame in resolution.canonical_frames
            if reference.segment_id in frame.segment_ids
        }
        if len(segment_owners) == 1:
            affected.update(segment_owners)
    return affected


def _resolution_status_from_frames(
    frames: Sequence[ValidatedIntentFrameV2],
) -> ResolutionStatus:
    active = {frame.frame_status for frame in frames}
    for status in (
        ResolutionStatus.UNMAPPED,
        ResolutionStatus.CONTEXT_UNRESOLVED,
        ResolutionStatus.AMBIGUOUS,
        ResolutionStatus.RESOLVED,
    ):
        if status in active:
            return status
    return ResolutionStatus.AMBIGUOUS


def _apply_deterministic_tie_break(
    candidates: QueryContractCandidateSet,
) -> QueryContractCandidateSet:
    frames = tuple(_tie_break_frame(frame) for frame in candidates.frames)
    return candidates.model_copy(update={"frames": frames})


def _tie_break_frame(
    frame: QueryContractFrameCandidateSet,
) -> QueryContractFrameCandidateSet:
    if (
        len(frame.complete_candidates) < 2
        or "CANDIDATE_BOUND_REACHED" in frame.contract_readiness.reason_codes
    ):
        return frame
    ranked: dict[tuple[int, int, int, int], list[QueryContractCandidate]] = {}
    for candidate in frame.complete_candidates:
        counts = {
            kind: sum(
                item.source_kind is kind for item in candidate.contract.provenance
            )
            for kind in ProvenanceSourceKind
        }
        quality = (
            -counts[ProvenanceSourceKind.EXACT_LOCK],
            -counts[ProvenanceSourceKind.PRIOR_RESULT],
            -counts[ProvenanceSourceKind.AXIS_RESOLUTION],
            counts[ProvenanceSourceKind.REGISTRY_DEFAULT],
        )
        ranked.setdefault(quality, []).append(candidate)
    best = ranked[min(ranked)]
    if len(best) != 1:
        return frame
    return frame.model_copy(
        update={
            "complete_candidates": (best[0],),
            "contract_readiness": ContractReadinessRecordV2(
                readiness=ContractReadiness.COMPLETE,
                reason_codes=(),
            ),
        }
    )


def _apply_judge_result(
    candidates: QueryContractCandidateSet,
    frame_id: str,
    judged: QueryContractJudgeResult,
) -> QueryContractCandidateSet:
    frames: list[QueryContractFrameCandidateSet] = []
    for frame in candidates.frames:
        if frame.frame_id != frame_id:
            frames.append(frame)
            continue
        selected = tuple(
            item
            for item in frame.complete_candidates
            if item.candidate_id == judged.candidate_id
        )
        frames.append(
            frame.model_copy(
                update={
                    "complete_candidates": selected or frame.complete_candidates,
                    "contract_readiness": judged.contract_readiness,
                }
            )
        )
    return candidates.model_copy(update={"frames": tuple(frames)})


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


def _hybrid_entity_mentions(
    context: RequestContext,
    normalized: NormalizedRequest,
) -> tuple[Mention, ...]:
    """Convert V3 entity evidence only when it has one unambiguous source range."""
    segments = {segment.segment_id: segment for segment in normalized.segments}
    mentions: list[Mention] = []
    for source in context.named_entities:
        segment = segments[source.segment_id]
        if not source.text:
            raise RequestNormalizationError("ENTITY_MENTION_RANGE_AMBIGUOUS")
        starts = [
            start
            for start in range(len(segment.original_text) - len(source.text) + 1)
            if segment.original_text.startswith(source.text, start)
        ]
        if len(starts) != 1:
            raise RequestNormalizationError("ENTITY_MENTION_RANGE_AMBIGUOUS")
        start = starts[0]
        mentions.append(
            Mention(
                mention_id=source.mention_id,
                segment_id=source.segment_id,
                text=source.text,
                normalized_text=normalize_segment(
                    source.mention_id, source.text
                ).normalized_text,
                start_char=start,
                end_char=start + len(source.text),
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
        raise ResolverContractError(MODEL_PROPOSAL_SCHEMA_INVALID) from None


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


def _merge_usage(
    first: Mapping[str, int], second: Mapping[str, int]
) -> dict[str, int]:
    keys = ("promptTokens", "completionTokens", "totalTokens")
    try:
        return {key: first[key] + second[key] for key in keys}
    except KeyError:
        raise ResolverContractError(MODEL_SCHEMA_INVALID) from None


def _duration_ms(started: float, completed: float) -> int:
    return max(0, round((completed - started) * 1_000))
