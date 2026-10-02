"""Raw questions through the existing resolver and deterministic planning gates."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import uuid

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.enums import AnswerDisposition, Cardinality
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.physical_bindings import PhysicalReadinessFacts
from financial_agent.planning.primitive_contracts import RELATION_CONCEPT_IDS, required_primitive_roles
from financial_agent.planning.router import POLICY_TAGS
from financial_agent.planning.semantic_compiler import (
    PriorResultOwnershipV2, SemanticPlanningCompiler, SemanticQueryPlanCompilation,
)

from .entity_discovery import EntityMentionDiscovery
from .errors import MODEL_TIMEOUT, ModelInvocationError, ResolverContractError
from .normalization import MAX_QUESTION_CODE_POINTS
from .query_contracts import AxisReadiness, AxisReadinessRecordV2, ContractReadiness
from .service import IntentResolverService, QueryContractResolutionAttemptV3
from .types import EntitySemanticRole, ResolutionStatus
from .view import ActiveDatasetPin


class PersonalIntentInputError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PersonalIntentResult:
    context: RequestContext
    attempt: QueryContractResolutionAttemptV3
    model_id: str
    route: CompilationRoute
    disposition: AnswerDisposition
    issue_codes: tuple[str, ...]
    compilation: SemanticQueryPlanCompilation | None = None

    def to_dict(self) -> dict:
        resolution = self.attempt.resolution
        candidates = {item.frame_id: item for item in self.attempt.candidates.frames}
        plan = self.compilation.logical_query_plan if self.compilation else None
        frames = []
        for frame in resolution.canonical_frames:
            group = candidates[frame.frame_id]
            selected = group.complete_candidates[0].contract if len(group.complete_candidates) == 1 else None
            frames.append({
                "frame_id": frame.frame_id,
                "actions": [item.value for item in frame.action_choice.selected_ids],
                "product_families": [item.value for item in frame.product_family_choice.selected_ids],
                "status": frame.frame_status.value,
                "semantic_coverage": frame.semantic_coverage[0].model_dump(mode="json"),
                "semantic_links": [item.model_dump(mode="json") for item in resolution.semantic_links
                                   if item.frame_id == frame.frame_id],
                "entity_hints": [item.model_dump(mode="json") for item in resolution.entity_hints
                                 if item.entity_hint_id in frame.entity_hint_ids],
                "contract_readiness": group.contract_readiness.model_dump(mode="json"),
                "candidate_count": len(group.complete_candidates),
                "candidate_contract": selected.model_dump(mode="json") if selected else None,
                "selected_contract": selected.model_dump(mode="json")
                                     if selected and plan else None,
            })
        return {
            "question": self.context.question, "dataset_version": self.context.dataset_version,
            "dataset_manifest_hash": resolution.active_dataset_manifest_hash,
            "provider": "nvidia", "model_id": self.model_id,
            "adapter_version": resolution.build_manifest.adapter_version,
            "resolution_status": resolution.resolution_status.value,
            "interpreted_product_families": sorted({family for frame in frames
                                                   for family in frame["product_families"]}),
            "target_product_families": sorted({family for frame in frames
                                              for family in frame["product_families"]})
                                       if plan else [],
            "discovered_entities": [item.model_dump(mode="json") for item in self.context.named_entities],
            "frames": frames, "route": self.route.value,
            "disposition": self.disposition.value, "issue_codes": list(self.issue_codes),
            "policy_tags": [item.value for item in resolution.final_tags if item in POLICY_TAGS],
            "logical_query_plan": plan.model_dump(mode="json") if plan else None,
            "planning": self.compilation.model_dump(mode="json") if self.compilation else None,
            "telemetry": self.attempt.telemetry.model_dump(mode="json"),
            "execution_performed": False,
        }


class PersonalIntentService:
    def __init__(
        self, *, resolver: IntentResolverService, discovery: EntityMentionDiscovery,
        compiler: SemanticPlanningCompiler, pin: ActiveDatasetPin,
        cutoff_date: date, model_id: str,
        utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._resolver, self._discovery, self._compiler = resolver, discovery, compiler
        self._pin, self._cutoff, self._model_id, self._utcnow = pin, cutoff_date, model_id, utcnow

    async def resolve(self, question: str, question_id: str = "local-intent") -> PersonalIntentResult:
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CODE_POINTS:
            raise PersonalIntentInputError("QUESTION_INVALID")
        if not isinstance(question_id, str) or not question_id.strip():
            raise PersonalIntentInputError("QUESTION_ID_INVALID")
        now = self._utcnow()
        context = RequestContext(
            request_key=build_request_key(question_id, question, self._pin.dataset_version, "1.0"),
            run_id=f"intent-{uuid.uuid4()}", dataset_version=self._pin.dataset_version,
            producer="personal-nvidia-intent", created_at=now, question_id=question_id,
            question=question, segments=(Segment(segment_id="s1", ordinal=0, text=question),),
            deadline_at=now + timedelta(seconds=55),
        )
        try:
            async with asyncio.timeout(55):
                mentions = await self._discovery.discover(context)
                context = RequestContext.model_validate(context.model_dump() | {"named_entities": mentions})
                attempt = await self._resolver.resolve_hybrid_query_contract_candidates(context)
                return self._route(context, attempt)
        except TimeoutError:
            raise ModelInvocationError(MODEL_TIMEOUT) from None

    def _route(self, context: RequestContext, attempt: QueryContractResolutionAttemptV3) -> PersonalIntentResult:
        resolution, view = attempt.resolution, attempt.view
        if view is None:
            raise ResolverContractError("RESOLVER_VIEW_REQUIRED")

        def blocked(*codes: str, limitation: bool = False) -> PersonalIntentResult:
            return PersonalIntentResult(context, attempt, self._model_id,
                CompilationRoute.EXPLORE if limitation else CompilationRoute.ABSTAIN,
                AnswerDisposition.LIMITATION if limitation else AnswerDisposition.ABSTAIN,
                tuple(sorted(set(codes))))

        if POLICY_TAGS.intersection(resolution.final_tags):
            return blocked("POLICY_BLOCKED")
        if resolution.resolution_status is not ResolutionStatus.RESOLVED:
            return blocked("INTENT_NOT_RESOLVED", *(issue.code for issue in resolution.issues))
        groups = attempt.candidates.frames
        if any(len(group.complete_candidates) != 1 or
               group.contract_readiness.readiness is not ContractReadiness.COMPLETE for group in groups):
            codes = {code for group in groups for code in group.contract_readiness.reason_codes}
            codes.update(rejection.reason_code for group in groups for rejection in group.rejections)
            return blocked("QUERY_CONTRACT_NOT_COMPLETE", *codes)

        # Entity evidence may not disappear into a broad family-only query.
        mentioned = {item.mention_id for item in context.named_entities}
        hints = {item.entity_hint_id: item for item in resolution.entity_hints}
        grounded = {item.mention_id[0] for item in hints.values()
                    if item.mention_id and len(item.selected_candidate_ids) == 1}
        if mentioned - grounded:
            return blocked("ENTITY_SCOPE_UNRESOLVED")
        entities = {item.entity_id: item for group in view.entity_candidates for item in group.items}
        selected = tuple(group.complete_candidates[0] for group in groups)
        scopes = {item.contract.frame_id: set(item.contract.scope.entity_refs) for item in selected}
        for frame in resolution.canonical_frames:
            families = {item.value for item in frame.product_family_choice.selected_ids}
            for hint_id in frame.entity_hint_ids:
                hint = hints[hint_id]
                if hint.semantic_role is not EntitySemanticRole.FRAME_SUBJECT and (
                    set(hint.selected_candidate_ids) & scopes[frame.frame_id]
                ):
                    return blocked("ENTITY_RELATION_SCOPE_NOT_LOWERABLE", limitation=True)
                if hint.semantic_role is not EntitySemanticRole.FRAME_SUBJECT:
                    continue
                for entity_id in hint.selected_candidate_ids:
                    entity = entities[entity_id]
                    if entity.product_family and entity.product_family not in families:
                        return blocked("ENTITY_PRODUCT_FAMILY_MISMATCH")

        if any(candidate.contract.qualifiers.as_of_date and
               candidate.contract.qualifiers.as_of_date > self._cutoff for candidate in selected):
            return blocked("REQUEST_AFTER_DATASET_CUTOFF", limitation=True)
        # The contract solver admits only result-set (MANY) scope bindings.
        owners = tuple(PriorResultOwnershipV2(binding_id=binding, producer_frame_id=binding,
                                            cardinality=Cardinality.MANY)
                       for binding in sorted({candidate.contract.scope.prior_result_binding
                                              for candidate in selected
                                              if candidate.contract.scope.prior_result_binding}))
        facts = PhysicalReadinessFacts(known_entity_ids=frozenset(entities))
        assessments = self._compiler.assess_in_dependency_order(
            selected_candidates=selected,
            axis_readiness=tuple(AxisReadinessRecordV2(readiness=AxisReadiness.COMPLETE, reason_codes=())
                                 for _ in selected),
            contract_readiness=tuple(group.contract_readiness for group in groups),
            active_dataset_pin=self._pin, prior_result_ownership=owners, facts=facts,
        )
        primitives = set()
        for candidate in selected:
            fields = {semantic_id for link in resolution.semantic_links
                      if link.frame_id == candidate.contract.frame_id for semantic_id in link.semantic_ids}
            primitives.update(role.primitive_id for role in required_primitive_roles(
                candidate.contract.action_id,
                family_count=len(candidate.contract.scope.product_family_ids),
                relation_required=bool(fields & RELATION_CONCEPT_IDS),
            ))
        compilation = self._compiler.compile(
            request_key=context.request_key, run_id=context.run_id,
            dataset_version=context.dataset_version, dataset_pin=self._pin.manifest_hash,
            cutoff_date=self._cutoff, producer="personal-intent-planner", created_at=context.created_at,
            resolution_id=resolution.resolution_id, selected_candidates=selected,
            readiness_assessments=assessments, primitive_ids=tuple(sorted(primitives)),
            prior_result_ownership=owners,
        )
        codes = {issue.code for issue in compilation.blocking_issues}
        codes.update(code for item in assessments for code in item.plan.reason_codes)
        return PersonalIntentResult(context, attempt, self._model_id, compilation.route,
                                    compilation.recommended_answer_disposition,
                                    tuple(sorted(codes)), compilation)
