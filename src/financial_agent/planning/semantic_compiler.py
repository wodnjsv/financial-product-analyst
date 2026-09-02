"""Deterministic finalization and lossless lowering of V2 semantic contracts."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from financial_agent.contracts.base import (
    ContractModel,
    Identifier,
    RuntimeArtifact,
    Sha256Hex,
)
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import (
    AnswerDisposition,
    Capability,
    Cardinality,
    IntentType,
)
from financial_agent.intent.query_contract_solver import QueryContractCandidate
from financial_agent.intent.query_contracts import (
    AxisReadiness,
    AxisReadinessRecordV2,
    ContractReadiness,
    ContractReadinessRecordV2,
    PlanReadiness,
    PlanReadinessRecordV2,
    QueryRegistryPinsV2,
    ResolvedQueryContractBundleV2,
    ResolvedQueryContractV2,
    SolvedQueryContractCandidateV2,
)

from .contracts import CompilationIssue, CompilationRoute
from .logical_query import (
    LogicalAggregateOperationV2,
    LogicalCalculateOperationV2,
    LogicalCompareOperationV2,
    LogicalDependencyV2,
    LogicalExplainOperationV2,
    LogicalExecutionRoute,
    LogicalLookupOperationV2,
    LogicalPrimitiveStepV2,
    LogicalQueryPlanV2,
    LogicalQueryTaskV2,
    LogicalRankOperationV2,
    LogicalScreenOperationV2,
    LogicalSimilarOperationV2,
    PriorResultInputV2,
    ProducedResultBindingV2,
    SemanticLoweringRecordV2,
    logical_query_plan_id,
)
from .physical_bindings import PhysicalBindingRegistry, SemanticSqlPolicyRegistry
from .readiness import PlanReadinessResult
from .registry import PlanningRegistry
from .semantic_router import route_semantic_query


_RESOLVED_ADAPTER = TypeAdapter(ResolvedQueryContractV2)
_CANDIDATE_ADAPTER = TypeAdapter(SolvedQueryContractCandidateV2)
_SQL_EXECUTION_BUNDLES = {
    IntentType.LOOKUP: (
        ("lookup-products", Capability.RDB_LOOKUP, "lookup"),
    ),
    IntentType.SCREEN: (
        ("lookup-products", Capability.RDB_LOOKUP, "lookup"),
        ("screen-products", Capability.RDB_LOOKUP, "screen"),
    ),
    IntentType.RANK: (
        ("lookup-products", Capability.RDB_LOOKUP, "lookup"),
        ("rank-products", Capability.RANKING, "rank"),
    ),
    IntentType.COMPARE: (
        ("lookup-products", Capability.RDB_LOOKUP, "lookup"),
        ("compare-products", Capability.COMPARISON, "compare"),
    ),
    IntentType.AGGREGATE: (
        ("lookup-products", Capability.RDB_LOOKUP, "lookup"),
        ("aggregate-products", Capability.FINANCIAL_CALCULATION, "aggregate"),
    ),
    IntentType.EXPLAIN: (
        ("lookup-products", Capability.RDB_LOOKUP, "explanation_source_lookup"),
        ("search-documents", Capability.KEYWORD_SEARCH, "search_explanation_source"),
    ),
}
_RELATION_CONCEPT_IDS = frozenset(
    {
        "associatedWithTheme",
        "classifiedAsIndustry",
        "containsSecurity",
        "controlsCompany",
        "documentedBy",
        "hasRiskFactor",
        "hasShareClass",
        "holdsSecurity",
        "issuedBy",
        "listedOn",
        "managedBy",
        "securityOfCompany",
        "tracksIndex",
    }
)
_ACTION_PATHS = {
    IntentType.LOOKUP: ("scope", "qualifiers", "result_shape", "projections"),
    IntentType.SCREEN: ("scope", "qualifiers", "result_shape", "predicate"),
    IntentType.RANK: (
        "scope", "qualifiers", "result_shape", "ordering", "limit",
        "limit_policy_id", "predicate",
    ),
    IntentType.COMPARE: ("scope", "qualifiers", "result_shape", "comparison"),
    IntentType.AGGREGATE: (
        "scope", "qualifiers", "result_shape", "aggregation", "predicate",
    ),
    IntentType.CALCULATE: ("scope", "qualifiers", "result_shape", "calculation"),
    IntentType.SIMILAR: ("scope", "qualifiers", "result_shape", "similarity"),
    IntentType.EXPLAIN: ("scope", "qualifiers", "result_shape", "explanation"),
}


class _StrictModel(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PriorResultOwnershipV2(_StrictModel):
    binding_id: Identifier
    producer_frame_id: Identifier
    cardinality: Cardinality = Field(strict=False)


class SemanticReadinessAssessmentV2(_StrictModel):
    """Server-owned readiness evidence bound to one exact solved candidate."""

    frame_id: Identifier
    candidate_id: Identifier
    contract_hash: Sha256Hex
    semantic_registry_pins: QueryRegistryPinsV2
    binding_registry_version: Identifier
    binding_registry_hash: Sha256Hex
    physical_policy_registry_version: Identifier
    physical_policy_registry_hash: Sha256Hex
    axis: AxisReadinessRecordV2
    contract: ContractReadinessRecordV2
    plan: PlanReadinessResult


class SemanticQueryPlanCompilation(RuntimeArtifact):
    compilation_version: Literal["semantic-query-plan-compilation.v2"] = (
        "semantic-query-plan-compilation.v2"
    )
    compilation_id: Identifier
    resolution_id: Identifier
    resolved_query_contracts: ResolvedQueryContractBundleV2
    logical_query_plan: LogicalQueryPlanV2 | None
    route: CompilationRoute = Field(strict=False)
    archetype_cache_hit: bool
    matched_archetype_id: Identifier | None
    primitive_ids: tuple[Identifier, ...]
    readiness_assessments: tuple[SemanticReadinessAssessmentV2, ...]
    planning_registry_version: Identifier
    planning_registry_hash: Sha256Hex
    recommended_answer_disposition: AnswerDisposition = Field(strict=False)
    blocking_issues: tuple[CompilationIssue, ...]

    @model_validator(mode="after")
    def validate_compilation(self):
        executable = self.route in {CompilationRoute.FAST, CompilationRoute.COMPOSE}
        if executable != (self.logical_query_plan is not None):
            raise ValueError("EXECUTABLE_ROUTE_PLAN_MISMATCH")
        if executable and self.blocking_issues:
            raise ValueError("EXECUTABLE_ROUTE_CANNOT_HAVE_BLOCKING_ISSUES")
        if not executable and not self.blocking_issues:
            raise ValueError("NON_EXECUTABLE_ROUTE_REQUIRES_ISSUE")
        if self.route is CompilationRoute.FAST:
            if not self.archetype_cache_hit or self.matched_archetype_id is None:
                raise ValueError("FAST_ROUTE_REQUIRES_ARCHETYPE")
        elif self.archetype_cache_hit or self.matched_archetype_id is not None:
            raise ValueError("ONLY_FAST_ROUTE_MAY_USE_ARCHETYPE")
        if executable and not self.primitive_ids:
            raise ValueError("EXECUTABLE_ROUTE_REQUIRES_PRIMITIVE")
        if len(set(self.primitive_ids)) != len(self.primitive_ids):
            raise ValueError("DUPLICATE_EXECUTION_PRIMITIVE")
        assessments_by_frame = {item.frame_id: item for item in self.readiness_assessments}
        contracts_by_frame = {
            item.frame_id: item for item in self.resolved_query_contracts.contracts
        }
        if (
            len(assessments_by_frame) != len(self.readiness_assessments)
            or set(assessments_by_frame) != set(contracts_by_frame)
            or any(
                item.plan.dataset_version != self.dataset_version
                for item in self.readiness_assessments
            )
            or len({item.plan.dataset_pin for item in self.readiness_assessments}) != 1
        ):
            raise ValueError("COMPILATION_READINESS_OWNERSHIP_MISMATCH")
        candidate_contracts = {}
        for frame_id, resolved_contract in contracts_by_frame.items():
            assessment = assessments_by_frame[frame_id]
            candidate_payload = resolved_contract.model_dump(
                mode="python",
                exclude={"axis_readiness", "contract_readiness", "plan_readiness"},
            )
            candidate_contract = _CANDIDATE_ADAPTER.validate_python(candidate_payload)
            candidate_contracts[frame_id] = candidate_contract
            contract_hash = canonical_sha256(candidate_contract)
            if (
                resolved_contract.axis_readiness != assessment.axis
                or resolved_contract.contract_readiness != assessment.contract
                or resolved_contract.plan_readiness.readiness is not assessment.plan.readiness
                or resolved_contract.plan_readiness.reason_codes != assessment.plan.reason_codes
                or assessment.frame_id != candidate_contract.frame_id
                or assessment.contract_hash != contract_hash
                or assessment.semantic_registry_pins != candidate_contract.registry_pins
                or assessment.plan.frame_id != frame_id
                or assessment.plan.contract_hash != contract_hash
                or assessment.binding_registry_version
                != assessment.plan.binding_registry_version
                or assessment.binding_registry_hash != assessment.plan.binding_registry_hash
                or assessment.physical_policy_registry_version
                != assessment.plan.policy_registry_version
                or assessment.physical_policy_registry_hash
                != assessment.plan.policy_registry_hash
            ):
                raise ValueError("COMPILATION_READINESS_OWNERSHIP_MISMATCH")
        if executable and any(
            item.axis.readiness is not AxisReadiness.COMPLETE
            or item.contract.readiness is not ContractReadiness.COMPLETE
            or item.plan.readiness is not PlanReadiness.EXECUTABLE
            for item in self.readiness_assessments
        ):
            raise ValueError("EXECUTABLE_READINESS_MISMATCH")
        restored_decision = route_semantic_query(
            action_ids=tuple(
                candidate_contracts[item.frame_id].action_id
                for item in self.resolved_query_contracts.contracts
            ),
            axis_readiness=tuple(
                assessments_by_frame[item.frame_id].axis.readiness
                for item in self.resolved_query_contracts.contracts
            ),
            contract_readiness=tuple(
                assessments_by_frame[item.frame_id].contract.readiness
                for item in self.resolved_query_contracts.contracts
            ),
            plan_readiness=tuple(
                assessments_by_frame[item.frame_id].plan.readiness
                for item in self.resolved_query_contracts.contracts
            ),
            matched_archetype_id=self.matched_archetype_id,
            primitive_ids=self.primitive_ids,
        )
        expected_issue_owners = tuple(contracts_by_frame)
        if (
            self.route is not restored_decision.route
            or self.recommended_answer_disposition
            is not restored_decision.recommended_answer_disposition
            or tuple(item.code for item in self.blocking_issues)
            != restored_decision.issue_codes
            or any(
                item.related_ids != expected_issue_owners
                for item in self.blocking_issues
            )
        ):
            raise ValueError("SEMANTIC_ROUTE_DECISION_MISMATCH")
        bundle_id = resolved_query_contract_bundle_id(self.resolved_query_contracts)
        if self.logical_query_plan is not None and (
            self.logical_query_plan.request_key != self.request_key
            or self.logical_query_plan.run_id != self.run_id
            or self.logical_query_plan.dataset_version != self.dataset_version
            or self.logical_query_plan.cutoff_date != self.cutoff_date
            or self.logical_query_plan.resolution_id != self.resolution_id
            or self.logical_query_plan.route is not self.route
            or self.logical_query_plan.dataset_pin
            != self.readiness_assessments[0].plan.dataset_pin
            or self.logical_query_plan.query_contract_id != bundle_id
            or self.logical_query_plan.primitive_ids != self.primitive_ids
            or self.logical_query_plan.planning_registry_version
            != self.planning_registry_version
            or self.logical_query_plan.planning_registry_hash != self.planning_registry_hash
        ):
            raise ValueError("LOGICAL_PLAN_COMPILATION_PIN_MISMATCH")
        if self.logical_query_plan is not None:
            tasks_by_frame = {
                item.frame_id: item for item in self.logical_query_plan.tasks
            }
            if set(tasks_by_frame) != set(contracts_by_frame):
                raise ValueError("LOSSY_COMPILATION_ARTIFACT")
            first_assessment = self.readiness_assessments[0]
            first_pins = candidate_contracts[first_assessment.frame_id].registry_pins
            if (
                any(
                    item.registry_pins != first_pins
                    for item in candidate_contracts.values()
                )
                or any(
                    assessment.plan.binding_registry_version
                    != first_assessment.plan.binding_registry_version
                    or assessment.plan.binding_registry_hash
                    != first_assessment.plan.binding_registry_hash
                    or assessment.plan.policy_registry_version
                    != first_assessment.plan.policy_registry_version
                    or assessment.plan.policy_registry_hash
                    != first_assessment.plan.policy_registry_hash
                    for assessment in self.readiness_assessments
                )
                or self.logical_query_plan.binding_registry_version
                != first_assessment.plan.binding_registry_version
                or self.logical_query_plan.binding_registry_hash
                != first_assessment.plan.binding_registry_hash
                or self.logical_query_plan.physical_policy_registry_version
                != first_assessment.plan.policy_registry_version
                or self.logical_query_plan.physical_policy_registry_hash
                != first_assessment.plan.policy_registry_hash
                or self.logical_query_plan.contract_registry_version
                != first_pins.contract_registry_version
                or self.logical_query_plan.contract_registry_hash
                != first_pins.contract_registry_hash
                or self.logical_query_plan.operator_registry_version
                != first_pins.operator_registry_version
                or self.logical_query_plan.operator_registry_hash
                != first_pins.operator_registry_hash
                or self.logical_query_plan.semantic_policy_registry_version
                != first_pins.policy_registry_version
                or self.logical_query_plan.semantic_policy_registry_hash
                != first_pins.policy_registry_hash
            ):
                raise ValueError("LOGICAL_PLAN_COMPILATION_PIN_MISMATCH")
            for frame_id, resolved_contract in contracts_by_frame.items():
                assessment = assessments_by_frame[frame_id]
                candidate_contract = candidate_contracts[frame_id]
                task = tasks_by_frame[frame_id]
                expected_resolved_id = resolved_contract_id(
                    frame_id,
                    assessment.candidate_id,
                    assessment.contract_hash,
                )
                expected_task_id = _stable_id(
                    "logical-task",
                    (
                        frame_id,
                        assessment.candidate_id,
                        assessment.contract_hash,
                    ),
                )
                if (
                    task.task_id != expected_task_id
                    or task.candidate_id != assessment.candidate_id
                    or task.contract_hash != assessment.contract_hash
                    or task.resolved_contract_id != expected_resolved_id
                    or task.contract_variant_id != candidate_contract.contract_variant_id
                    or canonical_sha256(candidate_contract) != assessment.contract_hash
                    or task.execution_steps
                    != _execution_steps(candidate_contract)
                    or task.binding_ids != assessment.plan.binding_ids
                    or reverse_semantic_loss_report(candidate_contract, task)
                ):
                    raise ValueError("LOSSY_COMPILATION_ARTIFACT")
        if self.compilation_id != semantic_compilation_id(self):
            raise ValueError("COMPILATION_ID_MISMATCH")
        return self


class SemanticPlanningCompiler:
    """Finalize independently-owned readiness evidence and lower without SQL."""

    def __init__(
        self,
        bindings: PhysicalBindingRegistry,
        policies: SemanticSqlPolicyRegistry,
        planning: PlanningRegistry,
    ) -> None:
        self._bindings = bindings
        self._policies = policies
        self._planning = planning

    def compile(
        self,
        *,
        request_key: str,
        run_id: str,
        dataset_version: str,
        dataset_pin: str,
        cutoff_date: date,
        producer: str,
        created_at: datetime,
        resolution_id: str,
        selected_candidates: tuple[QueryContractCandidate, ...],
        readiness_assessments: tuple[SemanticReadinessAssessmentV2, ...],
        primitive_ids: tuple[str, ...],
        matched_archetype_id: str | None = None,
        prior_result_ownership: tuple[PriorResultOwnershipV2, ...] = (),
    ) -> SemanticQueryPlanCompilation:
        if not selected_candidates or len(selected_candidates) > 16:
            raise ValueError("SELECTED_CANDIDATE_CARDINALITY_INVALID")
        if len(set(primitive_ids)) != len(primitive_ids):
            raise ValueError("DUPLICATE_EXECUTION_PRIMITIVE")
        if len({item.contract.frame_id for item in selected_candidates}) != len(
            selected_candidates
        ):
            raise ValueError("DUPLICATE_SELECTED_FRAME")
        assessments = {item.frame_id: item for item in readiness_assessments}
        if len(assessments) != len(readiness_assessments) or set(assessments) != {
            item.contract.frame_id for item in selected_candidates
        }:
            raise ValueError("READINESS_OWNERSHIP_MISMATCH")

        ordered_assessments: list[SemanticReadinessAssessmentV2] = []
        resolved = []
        for candidate in selected_candidates:
            assessment = assessments[candidate.contract.frame_id]
            self._validate_ownership(
                candidate,
                assessment,
                dataset_version=dataset_version,
                dataset_pin=dataset_pin,
            )
            ordered_assessments.append(assessment)
            payload = candidate.contract.model_dump(mode="python")
            payload.update(
                axis_readiness=assessment.axis,
                contract_readiness=assessment.contract,
                plan_readiness=PlanReadinessRecordV2(
                    readiness=assessment.plan.readiness,
                    reason_codes=assessment.plan.reason_codes,
                ),
            )
            resolved.append(_RESOLVED_ADAPTER.validate_python(payload))

        _validate_prior_result_ownership(selected_candidates, prior_result_ownership)
        canonical_primitive_ids = tuple(sorted(primitive_ids))
        self._validate_offered_primitives(
            selected_candidates,
            primitive_ids=canonical_primitive_ids,
        )

        decision = route_semantic_query(
            action_ids=tuple(item.contract.action_id for item in selected_candidates),
            axis_readiness=tuple(item.axis.readiness for item in ordered_assessments),
            contract_readiness=tuple(item.contract.readiness for item in ordered_assessments),
            plan_readiness=tuple(item.plan.readiness for item in ordered_assessments),
            matched_archetype_id=matched_archetype_id,
            primitive_ids=canonical_primitive_ids,
        )
        self._validate_execution_registry(
            selected_candidates,
            primitive_ids=canonical_primitive_ids,
            matched_archetype_id=matched_archetype_id,
            route=decision.route,
        )
        contract_bundle = ResolvedQueryContractBundleV2(contracts=tuple(resolved))
        contract_bundle_id = resolved_query_contract_bundle_id(contract_bundle)
        plan = None
        if decision.route in {CompilationRoute.FAST, CompilationRoute.COMPOSE}:
            plan = self._lower_plan(
                request_key=request_key,
                run_id=run_id,
                dataset_version=dataset_version,
                dataset_pin=dataset_pin,
                cutoff_date=cutoff_date,
                producer=producer,
                created_at=created_at,
                resolution_id=resolution_id,
                route=decision.route,
                contract_bundle_id=contract_bundle_id,
                candidates=selected_candidates,
                assessments=tuple(ordered_assessments),
                primitive_ids=canonical_primitive_ids,
                prior_result_ownership=prior_result_ownership,
            )
        issues = tuple(
            CompilationIssue(
                code=code,
                related_ids=tuple(
                    item.contract.frame_id for item in selected_candidates
                ),
            )
            for code in decision.issue_codes
        )
        compilation_kwargs = dict(
            request_key=request_key,
            run_id=run_id,
            dataset_version=dataset_version,
            cutoff_date=cutoff_date,
            producer=producer,
            created_at=created_at,
            resolution_id=resolution_id,
            resolved_query_contracts=contract_bundle,
            logical_query_plan=plan,
            route=decision.route,
            archetype_cache_hit=decision.route is CompilationRoute.FAST,
            matched_archetype_id=(
                matched_archetype_id
                if decision.route is CompilationRoute.FAST
                else None
            ),
            primitive_ids=canonical_primitive_ids,
            readiness_assessments=tuple(ordered_assessments),
            planning_registry_version=self._planning.registry_version,
            planning_registry_hash=self._planning.registry_hash,
            recommended_answer_disposition=decision.recommended_answer_disposition,
            blocking_issues=issues,
        )
        draft = SemanticQueryPlanCompilation.model_construct(
            compilation_id="pending",
            **compilation_kwargs,
        )
        return SemanticQueryPlanCompilation(
            compilation_id=semantic_compilation_id(draft),
            **compilation_kwargs,
        )

    def _validate_ownership(
        self,
        candidate: QueryContractCandidate,
        assessment: SemanticReadinessAssessmentV2,
        *,
        dataset_version: str,
        dataset_pin: str,
    ) -> None:
        contract_hash = canonical_sha256(candidate.contract)
        plan = assessment.plan
        if any(
            (
                assessment.frame_id != candidate.contract.frame_id,
                assessment.candidate_id != candidate.candidate_id,
                assessment.contract_hash != contract_hash,
                assessment.semantic_registry_pins != candidate.contract.registry_pins,
                assessment.semantic_registry_pins != self._bindings.semantic_registry_pins,
                assessment.binding_registry_version != self._bindings.registry_version,
                assessment.binding_registry_hash != self._bindings.registry_hash,
                assessment.physical_policy_registry_version != self._policies.registry_version,
                assessment.physical_policy_registry_hash != self._policies.registry_hash,
                plan.frame_id != candidate.contract.frame_id,
                plan.contract_hash != contract_hash,
                plan.dataset_version != dataset_version,
                plan.dataset_pin != dataset_pin,
                plan.binding_registry_version != self._bindings.registry_version,
                plan.binding_registry_hash != self._bindings.registry_hash,
                plan.policy_registry_version != self._policies.registry_version,
                plan.policy_registry_hash != self._policies.registry_hash,
            )
        ):
            raise ValueError("READINESS_OWNERSHIP_MISMATCH")
        readiness_pairs = (
            (assessment.axis.readiness is AxisReadiness.COMPLETE, assessment.axis.reason_codes),
            (
                assessment.contract.readiness is ContractReadiness.COMPLETE,
                assessment.contract.reason_codes,
            ),
            (plan.readiness is PlanReadiness.EXECUTABLE, plan.reason_codes),
        )
        if any(success == bool(reasons) for success, reasons in readiness_pairs):
            raise ValueError("READINESS_STATE_MISMATCH")

    def _lower_plan(
        self,
        *,
        request_key: str,
        run_id: str,
        dataset_version: str,
        dataset_pin: str,
        cutoff_date: date,
        producer: str,
        created_at: datetime,
        resolution_id: str,
        route: CompilationRoute,
        contract_bundle_id: str,
        candidates: tuple[QueryContractCandidate, ...],
        assessments: tuple[SemanticReadinessAssessmentV2, ...],
        primitive_ids: tuple[str, ...],
        prior_result_ownership: tuple[PriorResultOwnershipV2, ...],
    ) -> LogicalQueryPlanV2:
        owners = {item.binding_id: item for item in prior_result_ownership}
        task_ids_by_frame = {
            candidate.contract.frame_id: _stable_id(
                "logical-task",
                (
                    candidate.contract.frame_id,
                    candidate.candidate_id,
                    canonical_sha256(candidate.contract),
                ),
            )
            for candidate in candidates
        }
        tasks: list[LogicalQueryTaskV2] = []
        dependencies: list[LogicalDependencyV2] = []
        lowering: list[SemanticLoweringRecordV2] = []
        all_policies: set[str] = set()
        for candidate, assessment in zip(candidates, assessments, strict=True):
            contract = candidate.contract
            task_id = task_ids_by_frame[contract.frame_id]
            contract_hash = canonical_sha256(contract)
            resolved_id = resolved_contract_id(
                contract.frame_id,
                candidate.candidate_id,
                contract_hash,
            )
            execution_steps = _execution_steps(contract)
            prior_inputs: tuple[PriorResultInputV2, ...] = ()
            produced_outputs = tuple(
                ProducedResultBindingV2(
                    binding_id=item.binding_id,
                    cardinality=item.cardinality,
                )
                for item in prior_result_ownership
                if item.producer_frame_id == contract.frame_id
            )
            if contract.scope.prior_result_binding:
                owner = owners.get(contract.scope.prior_result_binding)
                if owner is None or owner.producer_frame_id not in task_ids_by_frame:
                    raise ValueError("PRIOR_RESULT_OWNERSHIP_MISMATCH")
                producer_task_id = task_ids_by_frame[owner.producer_frame_id]
                if producer_task_id == task_id:
                    raise ValueError("PRIOR_RESULT_OWNERSHIP_MISMATCH")
                prior_inputs = (
                    PriorResultInputV2(
                        binding_id=owner.binding_id,
                        producer_task_id=producer_task_id,
                        cardinality=owner.cardinality,
                    ),
                )
                dependencies.append(
                    LogicalDependencyV2(
                        upstream_task_id=producer_task_id,
                        downstream_task_id=task_id,
                        binding_id=owner.binding_id,
                    )
                )
            policy_ids = _contract_policy_ids(contract) | set(assessment.plan.policy_ids) | set(
                assessment.plan.unit_conversion_policy_ids
            )
            all_policies.update(policy_ids)
            evidence = self._evidence_requirements(
                assessment.plan.binding_ids, tuple(sorted(policy_ids))
            )
            task = LogicalQueryTaskV2(
                task_id=task_id,
                frame_id=contract.frame_id,
                candidate_id=candidate.candidate_id,
                contract_hash=contract_hash,
                resolved_contract_id=resolved_id,
                contract_variant_id=contract.contract_variant_id,
                action_id=contract.action_id,
                capability=execution_steps[-1].capability,
                execution_steps=execution_steps,
                scope=contract.scope,
                qualifiers=contract.qualifiers,
                result_shape=contract.result_shape,
                operation=lower_semantic_operation(contract),
                binding_ids=assessment.plan.binding_ids,
                policy_ids=tuple(sorted(policy_ids)),
                evidence_requirements=evidence,
                prior_result_inputs=prior_inputs,
                produced_result_bindings=produced_outputs,
            )
            losses = reverse_semantic_loss_report(contract, task)
            if losses:
                raise ValueError(f"LOSSY_SEMANTIC_LOWERING:{','.join(losses)}")
            tasks.append(task)
            lowering.append(
                SemanticLoweringRecordV2(
                    frame_id=contract.frame_id,
                    candidate_id=candidate.candidate_id,
                    resolved_contract_id=resolved_id,
                    task_id=task_id,
                    preserved_semantic_paths=_ACTION_PATHS[contract.action_id],
                    binding_ids=assessment.plan.binding_ids,
                    policy_ids=tuple(sorted(policy_ids)),
                )
            )
        pins = self._bindings.semantic_registry_pins
        plan_kwargs = dict(
            request_key=request_key,
            run_id=run_id,
            dataset_version=dataset_version,
            cutoff_date=cutoff_date,
            producer=producer,
            created_at=created_at,
            query_contract_id=contract_bundle_id,
            resolution_id=resolution_id,
            route=route,
            tasks=tuple(tasks),
            dependencies=tuple(dependencies),
            applied_policy_ids=tuple(sorted(all_policies)),
            primitive_ids=primitive_ids,
            binding_registry_version=self._bindings.registry_version,
            binding_registry_hash=self._bindings.registry_hash,
            physical_policy_registry_version=self._policies.registry_version,
            physical_policy_registry_hash=self._policies.registry_hash,
            contract_registry_version=pins.contract_registry_version,
            contract_registry_hash=pins.contract_registry_hash,
            operator_registry_version=pins.operator_registry_version,
            operator_registry_hash=pins.operator_registry_hash,
            semantic_policy_registry_version=pins.policy_registry_version,
            semantic_policy_registry_hash=pins.policy_registry_hash,
            planning_registry_version=self._planning.registry_version,
            planning_registry_hash=self._planning.registry_hash,
            dataset_pin=dataset_pin,
            lowering_records=tuple(lowering),
        )
        draft = LogicalQueryPlanV2.model_construct(
            logical_plan_id="pending",
            **plan_kwargs,
        )
        return LogicalQueryPlanV2(
            logical_plan_id=logical_query_plan_id(draft),
            **plan_kwargs,
        )

    def _evidence_requirements(
        self, binding_ids: tuple[str, ...], policy_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        locators: set[str] = set()
        for binding_id in binding_ids:
            binding = self._bindings.bindings_by_id.get(binding_id)
            if binding is None:
                raise ValueError("READINESS_BINDING_NOT_REGISTERED")
            locators.update(item.value for item in binding.required_evidence_locators)
        for policy_id in policy_ids:
            policy = self._policies.policies_by_id.get(policy_id)
            if policy is None:
                raise ValueError("READINESS_POLICY_NOT_REGISTERED")
            locators.update(item.value for item in policy.required_evidence_locators)
        return tuple(sorted(locators))

    def _validate_offered_primitives(
        self,
        candidates: tuple[QueryContractCandidate, ...],
        *,
        primitive_ids: tuple[str, ...],
    ) -> None:
        unknown = set(primitive_ids) - set(self._planning.primitives_by_id)
        if unknown:
            raise ValueError("EXECUTION_PRIMITIVE_NOT_REGISTERED")
        if not primitive_ids:
            return
        actions = tuple(item.contract.action_id for item in candidates)
        if any(
            not any(
                action in self._planning.primitives_by_id[primitive_id].action_ids
                for primitive_id in primitive_ids
            )
            for action in actions
        ):
            raise ValueError("EXECUTION_PRIMITIVE_ACTION_MISMATCH")

    def _validate_execution_registry(
        self,
        candidates: tuple[QueryContractCandidate, ...],
        *,
        primitive_ids: tuple[str, ...],
        matched_archetype_id: str | None,
        route: CompilationRoute,
    ) -> None:
        actions = tuple(item.contract.action_id for item in candidates)
        if route in {CompilationRoute.FAST, CompilationRoute.COMPOSE}:
            required_steps = tuple(
                step
                for candidate in candidates
                for step in _execution_steps(candidate.contract)
            )
            required_ids = {step.primitive_id for step in required_steps}
            if set(primitive_ids) != required_ids:
                raise ValueError("EXECUTION_PRIMITIVE_BUNDLE_MISMATCH")
            for step in required_steps:
                primitive = self._planning.primitives_by_id[step.primitive_id]
                if (
                    primitive.capability is not step.capability
                    or step.action_id not in primitive.action_ids
                ):
                    raise ValueError("EXECUTION_PRIMITIVE_DECLARATION_MISMATCH")
        if matched_archetype_id is None:
            return
        archetype = self._planning.archetypes_by_id.get(matched_archetype_id)
        if archetype is None:
            raise ValueError("ARCHETYPE_NOT_REGISTERED")
        families = {
            family
            for candidate in candidates
            for family in candidate.contract.scope.product_family_ids
        }
        has_context = any(
            candidate.contract.scope.prior_result_binding is not None
            for candidate in candidates
        )
        if (
            archetype.action_ids != actions
            or not archetype.min_family_count <= len(families) <= archetype.max_family_count
            or archetype.context_required != has_context
        ):
            raise ValueError("ARCHETYPE_CONTRACT_MISMATCH")
        if set(archetype.primitive_ids) != set(primitive_ids):
            raise ValueError("ARCHETYPE_PRIMITIVE_MISMATCH")


def reverse_semantic_loss_report(
    contract: SolvedQueryContractCandidateV2,
    task: LogicalQueryTaskV2,
) -> tuple[str, ...]:
    """Return exact semantic paths whose values changed during lowering."""

    expected = _semantic_contract_payload(contract)
    actual = _semantic_task_payload(task)
    expected_flat = _flatten(expected)
    actual_flat = _flatten(actual)
    return tuple(
        sorted(
            path
            for path in set(expected_flat) | set(actual_flat)
            if expected_flat.get(path) != actual_flat.get(path)
        )
    )


def _semantic_contract_payload(contract: SolvedQueryContractCandidateV2) -> dict[str, Any]:
    payload = contract.model_dump(mode="json")
    return {path: payload.get(path) for path in _ACTION_PATHS[contract.action_id]}


def _semantic_task_payload(task: LogicalQueryTaskV2) -> dict[str, Any]:
    operation = task.operation.model_dump(mode="json", exclude={"operation_type"})
    return {
        "scope": task.scope.model_dump(mode="json"),
        "qualifiers": task.qualifiers.model_dump(mode="json"),
        "result_shape": task.result_shape.value,
        **operation,
    }


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            child_path = f"{path}.{key}" if path else key
            result.update(_flatten(value[key], child_path))
        return result
    if isinstance(value, list):
        result = {}
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{path}.{index}"))
        if not value:
            result[path] = []
        return result
    return {path: value}


def lower_semantic_operation(contract: SolvedQueryContractCandidateV2):
    """Copy one complete action body into its strict logical operation variant."""
    if contract.action_id is IntentType.LOOKUP:
        return LogicalLookupOperationV2(projections=contract.projections)
    if contract.action_id is IntentType.SCREEN:
        return LogicalScreenOperationV2(predicate=contract.predicate)
    if contract.action_id is IntentType.RANK:
        return LogicalRankOperationV2(
            ordering=contract.ordering,
            limit=contract.limit,
            limit_policy_id=contract.limit_policy_id,
            predicate=contract.predicate,
        )
    if contract.action_id is IntentType.COMPARE:
        return LogicalCompareOperationV2(comparison=contract.comparison)
    if contract.action_id is IntentType.AGGREGATE:
        return LogicalAggregateOperationV2(
            aggregation=contract.aggregation, predicate=contract.predicate
        )
    if contract.action_id is IntentType.CALCULATE:
        return LogicalCalculateOperationV2(calculation=contract.calculation)
    if contract.action_id is IntentType.SIMILAR:
        return LogicalSimilarOperationV2(similarity=contract.similarity)
    return LogicalExplainOperationV2(explanation=contract.explanation)


def _contract_policy_ids(contract: SolvedQueryContractCandidateV2) -> set[str]:
    policy_ids: set[str] = set()
    action = contract.action_id
    if action is IntentType.LOOKUP and contract.projections.default_profile_id:
        policy_ids.add(contract.projections.default_profile_id)
    elif action is IntentType.SCREEN:
        policy_ids.update(_predicate_policy_ids(contract.predicate))
    elif action is IntentType.RANK:
        for item in contract.ordering:
            policy_ids.update((item.nulls_policy_id, item.tie_break_policy_id))
            if item.direction_policy_id:
                policy_ids.add(item.direction_policy_id)
        if contract.limit_policy_id:
            policy_ids.add(contract.limit_policy_id)
        if contract.predicate:
            policy_ids.update(_predicate_policy_ids(contract.predicate))
    elif action is IntentType.COMPARE:
        policy_ids.add(contract.comparison.basis_policy_id)
        for item in (
            contract.comparison.normalization_policy_id,
            contract.comparison.projection_profile_id,
        ):
            if item:
                policy_ids.add(item)
    elif action is IntentType.AGGREGATE:
        policy_ids.update(
            (contract.aggregation.population_grain_id, contract.aggregation.dedup_policy_id)
        )
        if contract.aggregation.bucket_policy_id:
            policy_ids.add(contract.aggregation.bucket_policy_id.value)
        if contract.predicate:
            policy_ids.update(_predicate_policy_ids(contract.predicate))
    elif action is IntentType.CALCULATE:
        policy_ids.add(contract.calculation.recipe_id)
    elif action is IntentType.SIMILAR:
        policy_ids.update((contract.similarity.policy_id, "minimum-dimension-coverage.v1"))
        if contract.similarity.default_profile_id:
            policy_ids.add(contract.similarity.default_profile_id)
    elif action is IntentType.EXPLAIN and contract.explanation.profile_id:
        policy_ids.add(contract.explanation.profile_id)
    return policy_ids


def _execution_steps(
    contract: SolvedQueryContractCandidateV2,
) -> tuple[LogicalPrimitiveStepV2, ...]:
    action = contract.action_id
    bundle = _SQL_EXECUTION_BUNDLES.get(action)
    if not bundle:
        raise ValueError("EXECUTION_PRIMITIVE_BUNDLE_MISMATCH")
    dynamic_steps: list[tuple[str, Capability, str, LogicalExecutionRoute]] = [
        (
            *step,
            LogicalExecutionRoute.SEARCH
            if step[1] is Capability.KEYWORD_SEARCH
            else LogicalExecutionRoute.GRAPH
            if step[1] is Capability.GRAPH_TRAVERSAL
            else LogicalExecutionRoute.SEMANTIC_SQL,
        )
        for step in bundle
    ]
    if action is IntentType.RANK and len(contract.scope.product_family_ids) > 1:
        dynamic_steps[1:1] = [
            (
                "check-comparability",
                Capability.COMPARISON,
                "check_comparability",
                LogicalExecutionRoute.SEMANTIC_SQL,
            ),
            (
                "normalize-values",
                Capability.FINANCIAL_CALCULATION,
                "normalize_values",
                LogicalExecutionRoute.SEMANTIC_SQL,
            ),
        ]
    relation_required = (
        action is IntentType.LOOKUP
        and bool(_RELATION_CONCEPT_IDS & set(contract.projections.field_concept_ids))
    ) or (
        action is IntentType.SCREEN
        and bool(_RELATION_CONCEPT_IDS & _predicate_field_ids(contract.predicate))
    ) or (
        action is IntentType.COMPARE
        and bool(
            _RELATION_CONCEPT_IDS
            & set(contract.comparison.metric_concept_ids)
        )
    ) or (
        action is IntentType.EXPLAIN
        and contract.explanation.topic_concept_id in _RELATION_CONCEPT_IDS
    )
    if relation_required:
        dynamic_steps.append(
            (
                "traverse-relations",
                Capability.GRAPH_TRAVERSAL,
                "traverse_relation",
                LogicalExecutionRoute.GRAPH,
            )
        )
    return tuple(
        LogicalPrimitiveStepV2(
            primitive_id=primitive_id,
            action_id=action,
            capability=capability,
            operation_kind=operation_kind,
            execution_route=execution_route,
        )
        for primitive_id, capability, operation_kind, execution_route in dynamic_steps
    )


def _predicate_field_ids(predicate: Any) -> set[str]:
    if predicate.node_type == "atom":
        return {predicate.field_concept_id}
    if predicate.node_type == "not":
        return _predicate_field_ids(predicate.child)
    return {
        field_id
        for child in predicate.children
        for field_id in _predicate_field_ids(child)
    }


def resolved_contract_id(
    frame_id: str,
    candidate_id: str,
    contract_hash: str,
) -> str:
    return _stable_id(
        "resolved-query-contract",
        (frame_id, candidate_id, contract_hash),
    )


def resolved_query_contract_bundle_id(
    bundle: ResolvedQueryContractBundleV2,
) -> str:
    return f"query-contract-bundle-{canonical_sha256(bundle)}"


def semantic_compilation_id(compilation: SemanticQueryPlanCompilation) -> str:
    return "semantic-compilation-" + canonical_sha256(
        compilation,
        exclude_fields={"compilation_id"},
    )


def _predicate_policy_ids(predicate: Any) -> set[str]:
    if predicate.node_type == "atom":
        return {predicate.null_policy_id}
    if predicate.node_type == "not":
        return _predicate_policy_ids(predicate.child)
    result: set[str] = set()
    for child in predicate.children:
        result.update(_predicate_policy_ids(child))
    return result


def _stable_id(prefix: str, value: object) -> str:
    return f"{prefix}-{canonical_sha256({'value': _canonical_seed(value)})}"


def _canonical_seed(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_canonical_seed(item) for item in value]
    if isinstance(value, list):
        return [_canonical_seed(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_seed(item) for key, item in value.items()}
    return value


def _validate_prior_result_ownership(
    candidates: tuple[QueryContractCandidate, ...],
    ownership: tuple[PriorResultOwnershipV2, ...],
) -> None:
    owners = {item.binding_id: item for item in ownership}
    if len(owners) != len(ownership):
        raise ValueError("DUPLICATE_PRIOR_RESULT_OWNERSHIP")
    required = {
        candidate.contract.scope.prior_result_binding
        for candidate in candidates
        if candidate.contract.scope.prior_result_binding is not None
    }
    if set(owners) != required:
        raise ValueError("PRIOR_RESULT_OWNERSHIP_MISMATCH")
    frame_order = {
        candidate.contract.frame_id: index for index, candidate in enumerate(candidates)
    }
    for candidate in candidates:
        binding_id = candidate.contract.scope.prior_result_binding
        if binding_id is None:
            continue
        owner = owners[binding_id]
        if (
            owner.producer_frame_id not in frame_order
            or frame_order[owner.producer_frame_id] >= frame_order[candidate.contract.frame_id]
        ):
            raise ValueError("PRIOR_RESULT_OWNERSHIP_MISMATCH")
