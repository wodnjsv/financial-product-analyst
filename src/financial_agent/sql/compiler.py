"""Deterministic compiler from LogicalQueryPlanV2 to read-only SQL."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
import sqlalchemy as sa
from pydantic import ConfigDict, TypeAdapter, ValidationError, model_validator
from sqlalchemy.dialects import postgresql

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.enums import Capability, Cardinality, ProductFamily, ToolStatus
from financial_agent.contracts.execution import BindingValue, ToolResult
from financial_agent.contracts.values import decode_contract_value
from financial_agent.db.schema.catalog import entity, product
from financial_agent.contracts.canonical import canonical_json_bytes, canonical_sha256
from financial_agent.db.schema.evidence import (
    evidence_observation_origin,
    evidence_relation_origin,
    evidence_record,
    source_record,
)
from financial_agent.db.schema.observation import observation_record
from financial_agent.db.schema.relation import relation_record
from financial_agent.intent.view import ActiveDatasetPin
from financial_agent.intent.query_contracts import AggregationFunction, OrderingDirection
from financial_agent.planning.logical_query import (
    LogicalAggregateOperationV2,
    LogicalCompareOperationV2,
    LogicalLookupOperationV2,
    LogicalQueryPlanV2,
    LogicalQueryTaskV2,
    LogicalRankOperationV2,
    LogicalScreenOperationV2,
    logical_task_semantic_hash,
)
from financial_agent.planning.physical_bindings import (
    EvidenceLocator,
    PhysicalBindingAvailability,
    PhysicalBindingRegistry,
    PhysicalReadinessFacts,
    SemanticQualifierId,
    SemanticSqlPolicyRegistry,
    PhysicalBindingDefinition,
    population_metric_ownership_lineage_ref,
    representative_share_edge_lineage_ref,
)
from financial_agent.planning.registry import PlanningRegistry

from .contracts import (
    COMPILER_VERSION,
    CompiledSqlRequest,
    PhysicalSqlRenderManifest,
    PhysicalLoweringKind,
    PhysicalLoweringRecord,
    DeferredSqlParameter,
    SqlParameter,
    compiled_sql_request_id,
    identifier_occurrences,
    physical_sql_render_manifest_id,
    placeholder_occurrences,
    physical_lowering_record_id,
    sql_render_template_id,
    statement_sha256,
    validate_compiled_request_ownership,
)
from .lowering import (
    ParameterBuilder,
    SqlCompileRejection,
    lower_predicate,
    physical_value_column,
    representative_product_cte,
    verified_public_fund_proof,
)


class SqlCompileRejectionRecord(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    code: Identifier
    logical_plan_id: Identifier
    task_id: Identifier


class SqlCompilationOutcome(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    request: CompiledSqlRequest | None = None
    rejection: SqlCompileRejectionRecord | None = None

    @model_validator(mode="after")
    def exactly_one_result(self):
        if bool(self.request) == bool(self.rejection):
            raise ValueError("SQL_COMPILATION_OUTCOME_REQUIRED")
        return self


@dataclass(slots=True)
class _Context:
    plan: object
    task: LogicalQueryTaskV2
    bindings: object
    policies: object
    facts: PhysicalReadinessFacts | None
    params: ParameterBuilder
    records: list[PhysicalLoweringRecord]
    observation_aliases: dict[str, sa.Alias]
    evidence_aliases: dict[str, sa.Alias]
    count_lineage_metric_definition_refs: tuple[str, ...]
    prior_result_entity_ids: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class _BoundMetricSet:
    definitions: tuple[PhysicalBindingDefinition, ...]

    @property
    def id(self) -> str:
        return self.definitions[0].id

    @property
    def approved_metric_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                metric
                for definition in self.definitions
                for metric in definition.approved_metric_ids
            )
        )

    @property
    def approved_metric_definition_refs(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                reference
                for definition in self.definitions
                for reference in definition.approved_metric_definition_refs
            )
        )

    def __getattr__(self, name: str):
        return getattr(self.definitions[0], name)


@dataclass(frozen=True, slots=True)
class RenderedPhysicalSql:
    statement: str
    parameters: tuple[SqlParameter | DeferredSqlParameter, ...]
    lowering_records: tuple[PhysicalLoweringRecord, ...]
    evidence_projection_ids: tuple[EvidenceLocator, ...]
    population_manifest_id: str | None
    population_manifest_hash: str | None
    count_lineage_metric_definition_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RenderPlan:
    dataset_version: str
    dataset_pin: str


@dataclass(frozen=True, slots=True)
class _ManifestBindings:
    bindings_by_id: MappingProxyType
    bindings_by_family_concept: MappingProxyType
    binding_sets_by_concept: MappingProxyType
    binding_sets_by_key: MappingProxyType

    def binding_for(
        self, family_id: str | ProductFamily | None, concept_id: str
    ) -> _BoundMetricSet | None:
        if family_id is None:
            return self.binding_sets_by_concept.get(concept_id)
        family = family_id.value if isinstance(family_id, ProductFamily) else family_id
        definition = self.bindings_by_family_concept.get((family, concept_id))
        return _BoundMetricSet((definition,)) if definition is not None else None


@dataclass(frozen=True, slots=True)
class _ManifestPolicies:
    registry_version: str
    registry_hash: str


class SemanticSqlCompiler:
    def __init__(
        self,
        bindings: PhysicalBindingRegistry,
        policies: SemanticSqlPolicyRegistry,
        planning: PlanningRegistry,
        active_dataset_pin: ActiveDatasetPin,
    ) -> None:
        self._bindings = bindings
        self._policies = policies
        self._planning = planning
        self._active_dataset_pin = active_dataset_pin

    def compile_task(
        self,
        plan: LogicalQueryPlanV2,
        task_id: str,
        *,
        readiness_facts: PhysicalReadinessFacts | None = None,
    ) -> SqlCompilationOutcome:
        try:
            self._validate_registry_pins(plan)
            try:
                plan = LogicalQueryPlanV2.model_validate_json(canonical_json_bytes(plan))
            except ValidationError as error:
                raise SqlCompileRejection("LOGICAL_PLAN_REVALIDATION_FAILED") from error
            task = next((item for item in plan.tasks if item.task_id == task_id), None)
            if task is None:
                raise SqlCompileRejection("SQL_TASK_NOT_FOUND")
            binding_definitions = _effective_binding_definitions(
                plan, task, self._bindings
            )
            applied_policy_ids = _effective_policy_ids(task, binding_definitions)
            self._validate_ownership(
                plan,
                task,
                binding_definitions=binding_definitions,
                applied_policy_ids=applied_policy_ids,
            )
            manifest_bindings = _manifest_bindings(binding_definitions)
            context = _Context(
                plan=plan,
                task=task,
                bindings=manifest_bindings,
                policies=self._policies,
                facts=readiness_facts,
                params=ParameterBuilder(),
                records=[],
                observation_aliases={},
                evidence_aliases={},
                count_lineage_metric_definition_refs=_count_lineage_metric_definition_refs(
                    task, self._bindings, readiness_facts
                ),
                prior_result_entity_ids=None,
            )
            rendered = _render_context(context)
            manifest_facts = (
                readiness_facts if _uses_representative_population(task) else None
            )
            manifest_kwargs = dict(
                template_id=sql_render_template_id(task),
                logical_plan_id=plan.logical_plan_id,
                logical_task=task,
                logical_task_semantic_hash=logical_task_semantic_hash(task),
                dataset_version=plan.dataset_version,
                dataset_pin=plan.dataset_pin,
                binding_definitions=binding_definitions,
                readiness_facts=manifest_facts,
                binding_registry_version=plan.binding_registry_version,
                binding_registry_hash=plan.binding_registry_hash,
                policy_registry_version=plan.physical_policy_registry_version,
                policy_registry_hash=plan.physical_policy_registry_hash,
                contract_registry_version=plan.contract_registry_version,
                contract_registry_hash=plan.contract_registry_hash,
                operator_registry_version=plan.operator_registry_version,
                operator_registry_hash=plan.operator_registry_hash,
                semantic_policy_registry_version=plan.semantic_policy_registry_version,
                semantic_policy_registry_hash=plan.semantic_policy_registry_hash,
                planning_registry_version=plan.planning_registry_version,
                planning_registry_hash=plan.planning_registry_hash,
                statement_sha256=statement_sha256(rendered.statement),
                ordered_placeholder_names=placeholder_occurrences(rendered.statement),
                identifier_occurrences=identifier_occurrences(rendered.statement),
                lowering_record_ids=tuple(
                    item.lowering_id for item in rendered.lowering_records
                ),
                evidence_projection_ids=rendered.evidence_projection_ids,
                count_lineage_metric_definition_refs=(
                    rendered.count_lineage_metric_definition_refs
                ),
                prior_result_entity_ids=None,
            )
            manifest_draft = PhysicalSqlRenderManifest.model_construct(
                manifest_id="pending", **manifest_kwargs
            )
            manifest = PhysicalSqlRenderManifest(
                manifest_id=physical_sql_render_manifest_id(manifest_draft),
                **manifest_kwargs,
            )
            kwargs = dict(
                logical_plan_id=plan.logical_plan_id,
                task_id=task.task_id,
                logical_task_semantic_hash=logical_task_semantic_hash(task),
                render_manifest=manifest,
                execution_ownership_required=True,
                statement=rendered.statement,
                parameters=rendered.parameters,
                lowering_records=rendered.lowering_records,
                applied_policy_ids=applied_policy_ids,
                evidence_projection_ids=rendered.evidence_projection_ids,
                compiler_version=COMPILER_VERSION,
                binding_registry_version=plan.binding_registry_version,
                binding_registry_hash=plan.binding_registry_hash,
                policy_registry_version=plan.physical_policy_registry_version,
                policy_registry_hash=plan.physical_policy_registry_hash,
                contract_registry_version=plan.contract_registry_version,
                contract_registry_hash=plan.contract_registry_hash,
                operator_registry_version=plan.operator_registry_version,
                operator_registry_hash=plan.operator_registry_hash,
                semantic_policy_registry_version=plan.semantic_policy_registry_version,
                semantic_policy_registry_hash=plan.semantic_policy_registry_hash,
                planning_registry_version=plan.planning_registry_version,
                planning_registry_hash=plan.planning_registry_hash,
                dataset_version=plan.dataset_version,
                dataset_pin=plan.dataset_pin,
                population_manifest_id=rendered.population_manifest_id,
                population_manifest_hash=rendered.population_manifest_hash,
            )
            draft = CompiledSqlRequest.model_construct(compiled_request_id="pending", **kwargs)
            request = CompiledSqlRequest(
                compiled_request_id=compiled_sql_request_id(draft), **kwargs
            )
            return SqlCompilationOutcome(request=request)
        except ValidationError:
            return SqlCompilationOutcome(
                rejection=SqlCompileRejectionRecord(
                    code="COMPILED_SQL_VALIDATION_FAILED",
                    logical_plan_id=plan.logical_plan_id,
                    task_id=task_id,
                )
            )
        except SqlCompileRejection as error:
            return SqlCompilationOutcome(
                rejection=SqlCompileRejectionRecord(
                    code=error.code,
                    logical_plan_id=plan.logical_plan_id,
                    task_id=task_id,
                )
            )

    def validate_request_for_execution(
        self,
        request: CompiledSqlRequest,
        logical_plan: LogicalQueryPlanV2,
        *,
        readiness_facts: PhysicalReadinessFacts | None = None,
    ) -> None:
        """Recompile against active registries before Task 9 may execute SQL."""

        validate_compiled_request_ownership(request, logical_plan)
        outcome = self.compile_task(
            logical_plan,
            request.task_id,
            readiness_facts=readiness_facts,
        )
        if outcome.request is None:
            code = outcome.rejection.code if outcome.rejection is not None else "UNKNOWN"
            raise ValueError(f"COMPILED_SQL_ACTIVE_RECOMPILATION_REJECTED:{code}")
        expected = outcome.request
        entity_ids = request.render_manifest.prior_result_entity_ids
        if entity_ids is not None:
            expected = _bind_compiled_request(expected, entity_ids)
        if canonical_json_bytes(expected) != canonical_json_bytes(request):
            raise ValueError("COMPILED_SQL_ACTIVE_RECOMPILATION_MISMATCH")

    def _validate_ownership(
        self,
        plan: LogicalQueryPlanV2,
        task: LogicalQueryTaskV2,
        *,
        binding_definitions: tuple[PhysicalBindingDefinition, ...],
        applied_policy_ids: tuple[str, ...],
    ) -> None:
        self._validate_registry_pins(plan)
        if any(item.execution_route.value != "semantic_sql" for item in task.execution_steps):
            raise SqlCompileRejection("SQL_EXECUTION_ROUTE_REQUIRED")
        if any(item not in self._bindings.bindings_by_id for item in task.binding_ids):
            raise SqlCompileRejection("PHYSICAL_BINDING_NOT_REGISTERED")
        for binding in binding_definitions:
            if binding.availability is not PhysicalBindingAvailability.VERIFIED:
                raise SqlCompileRejection("PHYSICAL_BINDING_UNAVAILABLE")
            required = {
                item
                for item in (
                    binding.unit_conversion_policy_id,
                    binding.missingness_policy_id,
                )
                if item is not None
            }
            if not required <= set(applied_policy_ids):
                raise SqlCompileRejection("PHYSICAL_POLICY_OWNERSHIP_MISMATCH")
        if any(item not in self._policies.policies_by_id for item in applied_policy_ids):
            raise SqlCompileRejection("SQL_POLICY_NOT_REGISTERED")
        if any(not self._policies.policies_by_id[item].verified for item in applied_policy_ids):
            raise SqlCompileRejection("SQL_POLICY_UNVERIFIED")

    def _validate_registry_pins(self, plan: LogicalQueryPlanV2) -> None:
        if (
            plan.binding_registry_version != self._bindings.registry_version
            or plan.binding_registry_hash != self._bindings.registry_hash
        ):
            raise SqlCompileRejection("BINDING_REGISTRY_PIN_MISMATCH")
        if (
            plan.physical_policy_registry_version != self._policies.registry_version
            or plan.physical_policy_registry_hash != self._policies.registry_hash
        ):
            raise SqlCompileRejection("PHYSICAL_POLICY_REGISTRY_PIN_MISMATCH")
        pins = self._bindings.semantic_registry_pins
        if (
            plan.contract_registry_version != pins.contract_registry_version
            or plan.contract_registry_hash != pins.contract_registry_hash
            or plan.operator_registry_version != pins.operator_registry_version
            or plan.operator_registry_hash != pins.operator_registry_hash
            or plan.semantic_policy_registry_version != pins.policy_registry_version
            or plan.semantic_policy_registry_hash != pins.policy_registry_hash
        ):
            raise SqlCompileRejection("SEMANTIC_REGISTRY_PIN_MISMATCH")
        if (
            plan.planning_registry_version != self._planning.registry_version
            or plan.planning_registry_hash != self._planning.registry_hash
        ):
            raise SqlCompileRejection("PLANNING_REGISTRY_PIN_MISMATCH")
        if (
            plan.dataset_version != self._active_dataset_pin.dataset_version
            or plan.dataset_pin != self._active_dataset_pin.manifest_hash
        ):
            raise SqlCompileRejection("DATASET_PROVENANCE_MISMATCH")


class SemanticSqlRuntimeBinder:
    """Resolve compiler-declared prior-result slots without altering SQL text."""

    def __init__(self, compiler: SemanticSqlCompiler) -> None:
        self._compiler = compiler

    def bind(
        self,
        request: CompiledSqlRequest,
        logical_plan: LogicalQueryPlanV2,
        binding_values: tuple[BindingValue, ...],
        *,
        dependency_results: tuple[ToolResult, ...],
    ) -> CompiledSqlRequest:
        validate_compiled_request_ownership(request, logical_plan)
        self._compiler.validate_request_for_execution(
            request,
            logical_plan,
            readiness_facts=request.render_manifest.readiness_facts,
        )
        task = next(
            item for item in logical_plan.tasks if item.task_id == request.task_id
        )
        if task.scope.prior_result_binding is None:
            if binding_values:
                raise ValueError("PRIOR_RESULT_BINDING_UNDECLARED")
            return request
        if request.render_manifest.prior_result_entity_ids is not None:
            raise ValueError("PRIOR_RESULT_REQUEST_ALREADY_BOUND")
        if len(task.prior_result_inputs) != 1 or len(binding_values) != 1:
            raise ValueError("PRIOR_RESULT_BINDING_INVALID")
        declaration = task.prior_result_inputs[0]
        binding = binding_values[0]
        if (
            binding.binding_name != declaration.binding_id
            or binding.value_type
            != f"semantic-result:{declaration.cardinality.value}"
        ):
            raise ValueError("PRIOR_RESULT_BINDING_INVALID")
        producer_task_id = f"semantic-execution:{declaration.producer_task_id}"
        producer_task = next(
            item
            for item in logical_plan.tasks
            if item.task_id == declaration.producer_task_id
        )
        producer_capability = (
            Capability.RDB_LOOKUP
            if all(
                step.execution_route.value == "semantic_sql"
                for step in producer_task.execution_steps
            )
            else producer_task.execution_steps[-1].capability
        )
        expected_result_type = self._compiler._planning.primitives_by_id[
            producer_task.execution_steps[-1].primitive_id
        ].result_type
        if len(dependency_results) != 1:
            raise ValueError("PRIOR_RESULT_DEPENDENCY_INVALID")
        dependency = dependency_results[0]
        if (
            dependency.task_id != producer_task_id
            or dependency.producer != f"executor:{producer_capability.value}"
            or dependency.result_type is not expected_result_type
            or dependency.status is not ToolStatus.SUCCESS
            or dependency.request_key != logical_plan.request_key
            or dependency.run_id != logical_plan.run_id
            or dependency.dataset_version != logical_plan.dataset_version
            or dependency.cutoff_date != logical_plan.cutoff_date
            or dependency.created_at != logical_plan.created_at
            or dependency.result_hash
            != canonical_sha256(dependency, exclude_fields=("result_hash",))
        ):
            raise ValueError("PRIOR_RESULT_DEPENDENCY_INVALID")
        origins = tuple(
            value
            for result in dependency_results
            if result.task_id == producer_task_id
            for value in result.binding_values
            if value.binding_name == declaration.binding_id
        )
        if origins != (binding,):
            raise ValueError("PRIOR_RESULT_BINDING_ORIGIN_MISMATCH")
        entity_ids = _canonical_prior_result_ids(binding, declaration.cardinality)
        bound = _bind_compiled_request(request, entity_ids)
        self._compiler.validate_request_for_execution(
            bound,
            logical_plan,
            readiness_facts=bound.render_manifest.readiness_facts,
        )
        return bound


_IDENTIFIER_ADAPTER = TypeAdapter(Identifier)


def _canonical_prior_result_ids(
    binding: BindingValue,
    cardinality: Cardinality,
) -> tuple[str, ...]:
    decoded = decode_contract_value(binding.value)
    if cardinality is Cardinality.MANY:
        if not isinstance(decoded, tuple) or not decoded:
            raise ValueError("PRIOR_RESULT_BINDING_INVALID")
        candidates = decoded
    else:
        if not isinstance(decoded, str):
            raise ValueError("PRIOR_RESULT_BINDING_INVALID")
        candidates = (decoded,)
    try:
        for candidate in candidates:
            if not isinstance(candidate, str):
                raise ValueError
            _IDENTIFIER_ADAPTER.validate_python(candidate)
    except ValueError as error:
        raise ValueError("PRIOR_RESULT_BINDING_INVALID") from error
    return tuple(sorted(set(candidates)))


def _bind_compiled_request(
    request: CompiledSqlRequest,
    entity_ids: tuple[str, ...],
) -> CompiledSqlRequest:
    manifest_draft = request.render_manifest.model_copy(
        update={
            "manifest_id": "pending",
            "prior_result_entity_ids": entity_ids,
        }
    )
    manifest = PhysicalSqlRenderManifest.model_validate(
        manifest_draft.model_copy(
            update={
                "manifest_id": physical_sql_render_manifest_id(manifest_draft)
            }
        ).model_dump()
    )
    rendered = render_physical_sql_manifest(manifest)
    draft = request.model_copy(
        update={
            "compiled_request_id": "pending",
            "render_manifest": manifest,
            "statement": rendered.statement,
            "parameters": rendered.parameters,
            "lowering_records": rendered.lowering_records,
            "evidence_projection_ids": rendered.evidence_projection_ids,
        }
    )
    return CompiledSqlRequest.model_validate(
        draft.model_copy(
            update={"compiled_request_id": compiled_sql_request_id(draft)}
        ).model_dump()
    )


def _manifest_bindings(
    definitions: tuple[PhysicalBindingDefinition, ...],
) -> _ManifestBindings:
    by_id = MappingProxyType({item.id: item for item in definitions})
    by_pair = MappingProxyType(
        {
            (item.product_family_id.value, item.semantic_concept_id): item
            for item in definitions
        }
    )
    grouped: dict[str, list[PhysicalBindingDefinition]] = {}
    for definition in definitions:
        grouped.setdefault(definition.semantic_concept_id, []).append(definition)
    by_concept = MappingProxyType(
        {
            concept: _compatible_metric_set(tuple(items))
            for concept, items in grouped.items()
        }
    )
    by_key = MappingProxyType({item.id: item for item in by_concept.values()})
    return _ManifestBindings(by_id, by_pair, by_concept, by_key)


def _compatible_metric_set(
    definitions: tuple[PhysicalBindingDefinition, ...],
) -> _BoundMetricSet:
    ordered = tuple(sorted(definitions, key=lambda item: item.id))
    if not ordered:
        raise SqlCompileRejection("PHYSICAL_BINDING_NOT_REGISTERED")
    comparable_fields = (
        "semantic_concept_id",
        "source_kind",
        "availability",
        "value_column",
        "semantic_value_kind",
        "storage_unit_id",
        "unit_conversion_policy_id",
        "period_behavior",
        "date_behavior",
        "missingness_policy_id",
        "supported_operator_ids",
        "supported_aggregate_ids",
        "supported_qualifier_ids",
        "required_qualifier_ids",
        "accepted_semantic_unit_ids",
        "currency_normalization_required",
        "verified_population_grain_ids",
        "required_evidence_locators",
    )
    baseline = ordered[0]
    if any(
        getattr(candidate, field) != getattr(baseline, field)
        for candidate in ordered[1:]
        for field in comparable_fields
    ):
        raise SqlCompileRejection("PRIOR_RESULT_BINDINGS_INCOMPATIBLE")
    return _BoundMetricSet(ordered)


def _prior_scope_families(
    plan: LogicalQueryPlanV2,
    task: LogicalQueryTaskV2,
    *,
    seen: frozenset[str] = frozenset(),
) -> tuple[ProductFamily, ...]:
    if task.task_id in seen:
        raise SqlCompileRejection("PRIOR_RESULT_DEPENDENCY_INVALID")
    if task.scope.product_family_ids:
        return task.scope.product_family_ids
    if len(task.prior_result_inputs) != 1:
        raise SqlCompileRejection("SQL_SINGLE_FAMILY_SCOPE_REQUIRED")
    producer_id = task.prior_result_inputs[0].producer_task_id
    producer = next((item for item in plan.tasks if item.task_id == producer_id), None)
    if producer is None:
        raise SqlCompileRejection("PRIOR_RESULT_DEPENDENCY_INVALID")
    return _prior_scope_families(
        plan, producer, seen=seen | frozenset((task.task_id,))
    )


def _task_concepts(task: LogicalQueryTaskV2) -> tuple[str, ...]:
    operation = task.operation
    if isinstance(operation, LogicalLookupOperationV2):
        return operation.projections.field_concept_ids
    if isinstance(operation, LogicalScreenOperationV2):
        return _predicate_concepts(operation.predicate)
    if isinstance(operation, LogicalRankOperationV2):
        concepts = tuple(item.field_concept_id for item in operation.ordering)
        if operation.predicate is not None:
            concepts += _predicate_concepts(operation.predicate)
        return tuple(dict.fromkeys(concepts))
    if isinstance(operation, LogicalCompareOperationV2):
        return operation.comparison.metric_concept_ids
    if isinstance(operation, LogicalAggregateOperationV2):
        concepts = tuple(
            item
            for item in (operation.aggregation.target_field_concept_id,)
            if item is not None
        ) + operation.aggregation.group_by_field_concept_ids
        if operation.predicate is not None:
            concepts += _predicate_concepts(operation.predicate)
        return tuple(dict.fromkeys(concepts))
    raise SqlCompileRejection("SQL_ACTION_NOT_SUPPORTED")


def _effective_binding_definitions(
    plan: LogicalQueryPlanV2,
    task: LogicalQueryTaskV2,
    registry: PhysicalBindingRegistry,
) -> tuple[PhysicalBindingDefinition, ...]:
    if task.scope.product_family_ids:
        if any(item not in registry.bindings_by_id for item in task.binding_ids):
            raise SqlCompileRejection("PHYSICAL_BINDING_NOT_REGISTERED")
        return tuple(registry.bindings_by_id[item] for item in task.binding_ids)
    if task.scope.prior_result_binding is None:
        raise SqlCompileRejection("SQL_SINGLE_FAMILY_SCOPE_REQUIRED")
    if task.binding_ids:
        raise SqlCompileRejection("LOGICAL_BINDING_OWNERSHIP_MISMATCH")
    families = _prior_scope_families(plan, task)
    definitions = []
    for concept in _task_concepts(task):
        concept_definitions = tuple(
            registry.binding_for(family, concept) for family in families
        )
        if any(item is None for item in concept_definitions):
            raise SqlCompileRejection("PHYSICAL_BINDING_NOT_REGISTERED")
        verified = tuple(item for item in concept_definitions if item is not None)
        _compatible_metric_set(verified)
        definitions.extend(verified)
    return tuple(
        sorted(
            {item.id: item for item in definitions}.values(),
            key=lambda item: item.id,
        )
    )


def _effective_policy_ids(
    task: LogicalQueryTaskV2,
    definitions: tuple[PhysicalBindingDefinition, ...],
) -> tuple[str, ...]:
    required = tuple(
        item
        for definition in definitions
        for item in (
            definition.unit_conversion_policy_id,
            definition.missingness_policy_id,
        )
        if item is not None
    )
    return tuple(dict.fromkeys((*task.policy_ids, *required)))


def render_physical_sql_manifest(
    manifest: PhysicalSqlRenderManifest,
) -> RenderedPhysicalSql:
    """Rebuild exact SQL from closed task/binding IR, never from stored SQL text."""

    definitions = tuple(manifest.binding_definitions)
    context = _Context(
        plan=_RenderPlan(
            dataset_version=manifest.dataset_version,
            dataset_pin=manifest.dataset_pin,
        ),
        task=manifest.logical_task,
        bindings=_manifest_bindings(definitions),
        policies=_ManifestPolicies(
            registry_version=manifest.policy_registry_version,
            registry_hash=manifest.policy_registry_hash,
        ),
        facts=manifest.readiness_facts,
        params=ParameterBuilder(),
        records=[],
        observation_aliases={},
        evidence_aliases={},
        count_lineage_metric_definition_refs=(
            manifest.count_lineage_metric_definition_refs
        ),
        prior_result_entity_ids=manifest.prior_result_entity_ids,
    )
    try:
        return _render_context(context)
    except SqlCompileRejection as error:
        raise ValueError(f"SQL_MANIFEST_RENDER_REJECTED:{error.code}") from error


def _render_context(context: _Context) -> RenderedPhysicalSql:
    statement, evidence_ids = _compile_statement(context)
    consumed_binding_ids = {
        definition.id
        for key in context.observation_aliases
        for definition in context.bindings.binding_sets_by_key[key].definitions
    }
    if consumed_binding_ids != set(context.bindings.bindings_by_id):
        if (
            isinstance(context.task.operation, LogicalAggregateOperationV2)
            and context.task.operation.aggregation.function_id
            is AggregationFunction.COUNT
            and any(
                value is not None
                for value in (
                    context.task.qualifiers.period_id,
                    context.task.qualifiers.currency_id,
                    context.task.qualifiers.unit_id,
                    context.task.qualifiers.as_of_date,
                )
            )
        ):
            raise SqlCompileRejection("COUNT_QUALIFIER_BINDING_REQUIRED")
        raise SqlCompileRejection("UNUSED_LOGICAL_BINDING")
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(paramstyle="named"),
            compile_kwargs={"render_postcompile": True},
        )
    )
    facts = context.facts
    representative = _uses_representative_population(context.task)
    return RenderedPhysicalSql(
        statement=sql,
        parameters=tuple(context.params.parameters),
        lowering_records=tuple(context.records),
        evidence_projection_ids=evidence_ids,
        population_manifest_id=(
            facts.public_fund_manifest.manifest_id
            if representative
            and facts is not None
            and facts.public_fund_manifest is not None
            else None
        ),
        population_manifest_hash=(
            facts.public_fund_manifest_hash
            if representative and facts is not None
            else None
        ),
        count_lineage_metric_definition_refs=(
            context.count_lineage_metric_definition_refs
        ),
    )


def _compile_statement(context: _Context):
    task = context.task
    if len(task.scope.product_family_ids) > 1:
        raise SqlCompileRejection("SQL_SINGLE_FAMILY_SCOPE_REQUIRED")
    family = (
        task.scope.product_family_ids[0]
        if task.scope.product_family_ids
        else None
    )
    if family is None and task.scope.prior_result_binding is None:
        raise SqlCompileRejection("SQL_SINGLE_FAMILY_SCOPE_REQUIRED")
    base = product.join(
        entity,
        sa.and_(
            product.c.dataset_version == entity.c.dataset_version,
            product.c.entity_id == entity.c.entity_id,
        ),
    )
    dataset = context.params.bind(context.plan.dataset_version, prefix="dataset")
    where = [product.c.dataset_version == dataset]
    if family is not None:
        family_param = context.params.bind(family.value, prefix="family")
        where.append(product.c.product_family == family_param)
        _record(
            context,
            "scope.product_family_ids",
            "catalog-product-family.v1",
            PhysicalLoweringKind.SCOPE,
        )
    if task.scope.prior_result_binding is not None:
        prior_result = context.params.bind_prior_result(
            task.scope.prior_result_binding,
            context.prior_result_entity_ids,
        )
        where.append(product.c.entity_id == sa.any_(prior_result))
    if task.scope.entity_refs:
        where.append(
            product.c.entity_id.in_(
                tuple(
                    context.params.bind(entity_ref, prefix="entity")
                    for entity_ref in task.scope.entity_refs
                )
            )
        )

    operation = task.operation
    if isinstance(operation, LogicalLookupOperationV2):
        if operation.projections.default_profile_id is not None:
            raise SqlCompileRejection("PROJECTION_PROFILE_NOT_EXPANDED")
        fields = operation.projections.field_concept_ids
        selected = [product.c.entity_id.label("product_id"), entity.c.canonical_name.label("product_name")]
        for index, concept_id in enumerate(fields):
            expression, binding, alias = _field(context, family, concept_id)
            base = _join_observation_with_evidence(context, base, alias, binding)
            evidence_alias = context.evidence_aliases[binding.id]
            selected.extend(
                (
                    expression.label(f"field_{index}"),
                    alias.c.value_status.label(f"value_status_{index}"),
                    alias.c.reason_code.label(f"reason_code_{index}"),
                    alias.c.observation_id.label(f"observation_id_{index}"),
                    alias.c.metric_id.label(f"metric_id_{index}"),
                    alias.c.metric_definition_version.label(
                        f"metric_definition_version_{index}"
                    ),
                    alias.c.unit.label(f"unit_{index}"),
                    alias.c.currency.label(f"currency_{index}"),
                    alias.c.applicable_date.label(f"applicable_date_{index}"),
                    evidence_alias.c.evidence_ids.label(f"evidence_id_{index}"),
                    evidence_alias.c.source_ids.label(f"source_id_{index}"),
                )
            )
            _record(context, f"operation.projections.{index}", binding.id, PhysicalLoweringKind.PROJECTION, binding)
        statement = sa.select(*selected).select_from(base).where(*where)
    elif isinstance(operation, LogicalScreenOperationV2):
        concepts = _predicate_concepts(operation.predicate)
        base, expressions = _join_fields(context, base, family, concepts)
        where.append(
            lower_predicate(
                operation.predicate,
                expression_for=lambda concept: expressions[concept][:3],
                parameters=context.params,
            )
        )
        for index, concept in enumerate(concepts):
            binding = expressions[concept][1]
            _record(context, f"operation.predicate.{index}", binding.id, PhysicalLoweringKind.PREDICATE, binding, (binding.missingness_policy_id,))
        selected = [product.c.entity_id.label("product_id"), entity.c.canonical_name.label("product_name")]
        for index, concept in enumerate(concepts):
            expression, binding, _, alias = expressions[concept]
            evidence_alias = context.evidence_aliases[binding.id]
            selected.extend(
                (
                    expression.label(f"field_{index}"),
                    alias.c.observation_id.label(f"observation_id_{index}"),
                    alias.c.metric_id.label(f"metric_id_{index}"),
                    alias.c.metric_definition_version.label(
                        f"metric_definition_version_{index}"
                    ),
                    alias.c.unit.label(f"unit_{index}"),
                    alias.c.currency.label(f"currency_{index}"),
                    alias.c.applicable_date.label(f"applicable_date_{index}"),
                    evidence_alias.c.evidence_ids.label(f"evidence_id_{index}"),
                    evidence_alias.c.source_ids.label(f"source_id_{index}"),
                )
            )
        statement = sa.select(*selected).select_from(base).where(*where)
    elif isinstance(operation, LogicalRankOperationV2):
        concepts = tuple(dict.fromkeys(item.field_concept_id for item in operation.ordering))
        if operation.predicate is not None:
            concepts += tuple(item for item in _predicate_concepts(operation.predicate) if item not in concepts)
        base, expressions = _join_fields(context, base, family, concepts)
        if operation.predicate is not None:
            if any(
                _predicate_has_missing_test(operation.predicate, item)
                for item in (ordering.field_concept_id for ordering in operation.ordering)
            ):
                raise SqlCompileRejection("ORDERING_MISSINGNESS_CONFLICT")
            where.append(lower_predicate(operation.predicate, expression_for=lambda concept: expressions[concept][:3], parameters=context.params))
        ordering = []
        for index, item in enumerate(operation.ordering):
            expression, binding, _, alias = expressions[item.field_concept_id]
            where.append(_present(context, alias.c.value_status))
            direction = item.direction
            if direction is None:
                if item.direction_policy_id != "default-direction-descending.v1":
                    raise SqlCompileRejection("ORDER_DIRECTION_POLICY_UNSUPPORTED")
                direction = OrderingDirection.DESC
            ordering.append(expression.asc() if direction is OrderingDirection.ASC else expression.desc())
            _record(context, f"operation.ordering.{index}", binding.id, PhysicalLoweringKind.ORDERING, binding, (item.nulls_policy_id, item.tie_break_policy_id))
        ordering.append(product.c.entity_id.asc())
        limit = operation.limit
        if limit is None:
            if operation.limit_policy_id != "default-limit-5.v1":
                raise SqlCompileRejection("RESULT_LIMIT_POLICY_UNSUPPORTED")
            limit = 5
        selected = [product.c.entity_id.label("product_id"), entity.c.canonical_name.label("product_name")]
        for index, concept in enumerate(concepts):
            expression, binding, _, alias = expressions[concept]
            evidence_alias = context.evidence_aliases[binding.id]
            selected.extend(
                (
                    expression.label(f"field_{index}"),
                    alias.c.observation_id.label(f"observation_id_{index}"),
                    alias.c.metric_id.label(f"metric_id_{index}"),
                    alias.c.metric_definition_version.label(
                        f"metric_definition_version_{index}"
                    ),
                    alias.c.unit.label(f"unit_{index}"),
                    alias.c.currency.label(f"currency_{index}"),
                    alias.c.applicable_date.label(f"applicable_date_{index}"),
                    evidence_alias.c.evidence_ids.label(f"evidence_id_{index}"),
                    evidence_alias.c.source_ids.label(f"source_id_{index}"),
                )
            )
        statement = sa.select(*selected).select_from(base).where(*where).order_by(*ordering).limit(context.params.bind(limit, prefix="limit"))
    elif isinstance(operation, LogicalCompareOperationV2):
        comparison = operation.comparison
        if not comparison.subject_refs:
            raise SqlCompileRejection("COMPARISON_SUBJECTS_REQUIRED")
        if comparison.normalization_policy_id:
            raise SqlCompileRejection("CROSS_CURRENCY_NORMALIZATION_UNVERIFIED")
        concepts = comparison.metric_concept_ids
        base, expressions = _join_fields(context, base, family, concepts)
        where.append(product.c.entity_id.in_(tuple(context.params.bind(item, prefix="subject") for item in comparison.subject_refs)))
        selected = [product.c.entity_id.label("product_id"), entity.c.canonical_name.label("product_name")]
        for index, item in enumerate(concepts):
            expression, binding, _, alias = expressions[item]
            evidence_alias = context.evidence_aliases[binding.id]
            where.append(_present(context, alias.c.value_status))
            selected.extend(
                (
                    expression.label(f"field_{index}"),
                    alias.c.observation_id.label(f"observation_id_{index}"),
                    alias.c.metric_id.label(f"metric_id_{index}"),
                    alias.c.metric_definition_version.label(
                        f"metric_definition_version_{index}"
                    ),
                    alias.c.unit.label(f"unit_{index}"),
                    alias.c.currency.label(f"currency_{index}"),
                    alias.c.applicable_date.label(f"applicable_date_{index}"),
                    evidence_alias.c.evidence_ids.label(f"evidence_id_{index}"),
                    evidence_alias.c.source_ids.label(f"source_id_{index}"),
                )
            )
        statement = sa.select(*selected).select_from(base).where(*where).order_by(product.c.entity_id.asc())
    elif isinstance(operation, LogicalAggregateOperationV2):
        statement = _aggregate(context, base, where, family, operation)
    else:
        raise SqlCompileRejection("SQL_ACTION_NOT_SUPPORTED")

    if not isinstance(operation, LogicalAggregateOperationV2):
        statement = _apply_qualifiers(context, statement)
    evidence = _evidence_ids(context)
    return statement, evidence


def _field(context: _Context, family: ProductFamily | None, concept_id: str):
    binding = context.bindings.binding_for(family, concept_id)
    if binding is None:
        raise SqlCompileRejection("LOGICAL_BINDING_OWNERSHIP_MISMATCH")
    if binding.availability is not PhysicalBindingAvailability.VERIFIED:
        raise SqlCompileRejection("PHYSICAL_BINDING_UNAVAILABLE")
    alias = context.observation_aliases.get(binding.id)
    if alias is None:
        alias = observation_record.alias(f"observation_{len(context.observation_aliases)}")
        context.observation_aliases[binding.id] = alias
    original = physical_value_column(binding)
    expression = alias.c[original.name]
    return expression, binding, alias


def _join_fields(context, base, family, concepts):
    expressions = {}
    for concept in concepts:
        expression, binding, alias = _field(context, family, concept)
        if alias not in {item[3] for item in expressions.values()}:
            base = _join_observation_with_evidence(context, base, alias, binding)
        expressions[concept] = (expression, binding, alias.c.value_status, alias)
    return base, expressions


def _observation_join(context, alias, binding):
    metric_conditions = tuple(
        alias.c.metric_id == context.params.bind(metric, prefix="metric")
        for metric in binding.approved_metric_ids
    )
    return sa.and_(
        alias.c.dataset_version == product.c.dataset_version,
        alias.c.entity_id == product.c.entity_id,
        sa.or_(*metric_conditions),
    )


def _join_observation_with_evidence(context, base, alias, binding):
    base = base.join(alias, _observation_join(context, alias, binding))
    return _join_evidence(context, base, alias, binding)


def _join_evidence(context, base, alias, binding):
    index = len(context.evidence_aliases)
    origin_alias = evidence_observation_origin.alias(f"evidence_origin_{index}")
    record_alias = evidence_record.alias(f"evidence_{index}")
    source_alias = source_record.alias(f"evidence_source_{index}")
    lineage_filters = [
        record_alias.c.evidence_kind
        == context.params.bind("observation", prefix="evidence_kind")
    ]
    ownerships = _manifest_metric_ownerships(context, binding)
    if ownerships:
        lineage_filters.append(
            sa.or_(
                *(
                    sa.and_(
                        origin_alias.c.observation_id
                        == context.params.bind(item.observation_id, prefix="owned_observation_id"),
                        origin_alias.c.evidence_id
                        == context.params.bind(item.evidence_id, prefix="owned_evidence_id"),
                        record_alias.c.source_id
                        == context.params.bind(item.source_id, prefix="owned_source_id"),
                    )
                    for item in ownerships
                )
            )
        )
    evidence_alias = (
        sa.select(
            origin_alias.c.dataset_version,
            origin_alias.c.observation_id,
            sa.func.array_agg(sa.distinct(record_alias.c.evidence_id)).label("evidence_ids"),
            sa.func.array_agg(sa.distinct(source_alias.c.source_id)).label("source_ids"),
        )
        .select_from(
            origin_alias.join(
                record_alias,
                sa.and_(
                    record_alias.c.dataset_version == origin_alias.c.dataset_version,
                    record_alias.c.evidence_id == origin_alias.c.evidence_id,
                ),
            ).join(
                source_alias,
                sa.and_(
                    source_alias.c.dataset_version == record_alias.c.dataset_version,
                    source_alias.c.source_id == record_alias.c.source_id,
                ),
            )
        )
        .where(*lineage_filters)
        .group_by(origin_alias.c.dataset_version, origin_alias.c.observation_id)
        .subquery(f"evidence_lineage_{index}")
    )
    context.evidence_aliases[binding.id] = evidence_alias
    return base.join(
        evidence_alias,
        sa.and_(
            evidence_alias.c.dataset_version == alias.c.dataset_version,
            evidence_alias.c.observation_id == alias.c.observation_id,
        ),
    )


def _manifest_metric_ownerships(context: _Context, binding):
    if context.facts is None or context.facts.public_fund_manifest is None:
        return ()
    approved = set(binding.approved_metric_ids)
    return tuple(
        item
        for item in context.facts.public_fund_manifest.population_metric_ownerships
        if item.metric_id in approved
    )


def _aggregate(context, base, where, family, operation):
    spec = operation.aggregation
    joined_alias_names: set[str] = set()
    is_public_representative = family is ProductFamily.PUBLIC_FUND and spec.population_grain_id == "representative-product.v1"
    if family is ProductFamily.PUBLIC_FUND and not is_public_representative:
        raise SqlCompileRejection("PUBLIC_FUND_REPRESENTATIVE_POLICY_REQUIRED")
    if is_public_representative:
        if spec.dedup_policy_id != "public-fund-representative-share.v1":
            raise SqlCompileRejection("PUBLIC_FUND_REPRESENTATIVE_POLICY_REQUIRED")
        metric_ids = ()
        if spec.target_field_concept_id:
            binding = context.bindings.binding_for(family, spec.target_field_concept_id)
            metric_ids = binding.approved_metric_ids if binding is not None else ()
        if not verified_public_fund_proof(context.facts, dataset_pin=context.plan.dataset_pin, policies=context.policies, metric_ids=metric_ids):
            raise SqlCompileRejection("PUBLIC_FUND_VERIFIED_PROOF_REQUIRED")
        assert context.facts is not None
        representative = representative_product_cte(
            context.params,
            context.facts,
            dataset_version=context.plan.dataset_version,
        )
        base = representative.join(
            product,
            sa.and_(
                representative.c.dataset_version == product.c.dataset_version,
                representative.c.entity_id == product.c.entity_id,
            ),
        ).join(
            entity,
            sa.and_(
                representative.c.dataset_version == entity.c.dataset_version,
                representative.c.entity_id == entity.c.entity_id,
            ),
        )

    if spec.function_id is AggregationFunction.COUNT:
        id_expression = representative.c.entity_id if is_public_representative else product.c.entity_id
        aggregate_expression = sa.func.count(sa.distinct(id_expression))
        selected = [
            aggregate_expression.label("aggregate_value"),
            sa.func.array_agg(sa.distinct(id_expression)).label("product_ids"),
        ]
    else:
        if spec.target_field_concept_id is None:
            raise SqlCompileRejection("AGGREGATION_TARGET_REQUIRED")
        expression, binding, alias = _field(context, family, spec.target_field_concept_id)
        join_target = representative if is_public_representative else product
        join_condition = sa.and_(
            alias.c.dataset_version == join_target.c.dataset_version,
            alias.c.entity_id == join_target.c.entity_id,
            sa.or_(*(alias.c.metric_id == context.params.bind(metric, prefix="metric") for metric in binding.approved_metric_ids)),
        )
        ownerships = _manifest_metric_ownerships(context, binding)
        if (
            is_public_representative
            and spec.function_id is AggregationFunction.COUNT
        ):
            if not ownerships:
                raise SqlCompileRejection("PUBLIC_FUND_VERIFIED_PROOF_REQUIRED")
            join_condition = sa.and_(
                join_condition,
                sa.or_(
                    *(
                        sa.and_(
                            alias.c.entity_id
                            == context.params.bind(item.owner_entity_id, prefix="owned_entity_id"),
                            alias.c.metric_id
                            == context.params.bind(item.metric_id, prefix="owned_metric_id"),
                            alias.c.observation_id
                            == context.params.bind(item.observation_id, prefix="owned_observation_id"),
                        )
                        for item in ownerships
                    )
                ),
            )
        base = base.join(alias, join_condition)
        base = _join_evidence(context, base, alias, binding)
        joined_alias_names.add(alias.name)
        where.append(_present(context, alias.c.value_status))
        if spec.function_id not in binding.supported_aggregate_ids:
            raise SqlCompileRejection("PHYSICAL_AGGREGATE_UNSUPPORTED")
        aggregate_expression = {
            AggregationFunction.SUM: sa.func.sum(expression),
            AggregationFunction.COUNT_DISTINCT: sa.func.count(sa.distinct(expression)),
            AggregationFunction.AVG: sa.func.avg(expression),
            AggregationFunction.MIN: sa.func.min(expression),
            AggregationFunction.MAX: sa.func.max(expression),
        }.get(spec.function_id)
        if aggregate_expression is None and spec.function_id is not AggregationFunction.DISTRIBUTION:
            raise SqlCompileRejection("PHYSICAL_AGGREGATE_UNSUPPORTED")
        selected = [aggregate_expression.label("aggregate_value")] if aggregate_expression is not None else []
        selected.extend(
            (
                sa.func.array_agg(sa.distinct(alias.c.observation_id)).label(
                    "observation_ids"
                ),
                sa.func.array_agg(sa.distinct(alias.c.metric_id)).label(
                    "metric_ids"
                ),
                sa.func.array_agg(
                    sa.distinct(alias.c.metric_definition_version)
                ).label("metric_definition_versions"),
                sa.func.array_agg(sa.distinct(alias.c.unit)).label("units"),
                sa.func.array_agg(sa.distinct(alias.c.currency)).label(
                    "currencies"
                ),
                sa.func.array_agg(sa.distinct(alias.c.applicable_date)).label(
                    "applicable_dates"
                ),
            )
        )
        _record(context, "operation.aggregation.target", binding.id, PhysicalLoweringKind.AGGREGATION, binding, (spec.population_grain_id, spec.dedup_policy_id))

    groups = []
    group_observation_aliases = []
    for index, concept in enumerate(spec.group_by_field_concept_ids):
        group_expression, group_binding, group_alias = _field(context, family, concept)
        if group_alias.name not in joined_alias_names:
            base = _join_observation_with_evidence(
                context, base, group_alias, group_binding
            )
            joined_alias_names.add(group_alias.name)
        if is_public_representative:
            group_ownerships = _manifest_metric_ownerships(context, group_binding)
            if not group_ownerships:
                raise SqlCompileRejection("PUBLIC_FUND_VERIFIED_PROOF_REQUIRED")
            where.append(
                sa.or_(
                    *(
                        sa.and_(
                            group_alias.c.entity_id
                            == context.params.bind(
                                item.owner_entity_id,
                                prefix="group_owned_entity_id",
                            ),
                            group_alias.c.metric_id
                            == context.params.bind(
                                item.metric_id, prefix="group_owned_metric_id"
                            ),
                            group_alias.c.metric_definition_version
                            == context.params.bind(
                                item.metric_definition_version,
                                prefix="group_owned_metric_definition_version",
                            ),
                            group_alias.c.observation_id
                            == context.params.bind(
                                item.observation_id,
                                prefix="group_owned_observation_id",
                            ),
                        )
                        for item in group_ownerships
                    )
                )
            )
        where.append(_present(context, group_alias.c.value_status))
        selected.insert(index, group_expression.label(f"group_{index}"))
        groups.append(group_expression)
        group_observation_aliases.append(group_alias)
        _record(context, f"operation.aggregation.group_by.{index}", group_binding.id, PhysicalLoweringKind.GROUPING, group_binding)

    if operation.predicate is not None:
        predicate_concepts = _predicate_concepts(operation.predicate)
        expressions = {}
        for concept in predicate_concepts:
            expression, binding, alias = _field(context, family, concept)
            if alias.name not in joined_alias_names:
                base = _join_observation_with_evidence(context, base, alias, binding)
                joined_alias_names.add(alias.name)
            expressions[concept] = (expression, binding, alias.c.value_status)
        where.append(
            lower_predicate(
                operation.predicate,
                expression_for=lambda concept: expressions[concept],
                parameters=context.params,
            )
        )
        for index, concept in enumerate(predicate_concepts):
            binding = expressions[concept][1]
            _record(
                context,
                f"operation.predicate.{index}",
                binding.id,
                PhysicalLoweringKind.PREDICATE,
                binding,
                (binding.missingness_policy_id,),
            )
    where.extend(_qualifier_filters(context))
    statement = sa.select(*selected).select_from(base).where(*where)
    if groups:
        statement = statement.group_by(*groups)
    if spec.function_id is AggregationFunction.COUNT and (
        not groups or is_public_representative
    ):
        statement = _attach_count_population_lineage(
            context,
            statement,
            base,
            where,
            groups=tuple(groups),
        )
    else:
        statement = _attach_flat_aggregate_evidence(
            context,
            statement,
            base=base,
            where=where,
            groups=groups,
            evidence_aliases=tuple(context.evidence_aliases.values()),
            observation_aliases=(
                tuple(group_observation_aliases)
                if spec.function_id is AggregationFunction.COUNT
                else ()
            ),
        )
    _record(context, "operation.aggregation.population", "catalog-product-family.v1", PhysicalLoweringKind.DEDUPLICATION, policy_ids=(spec.population_grain_id, spec.dedup_policy_id))
    return statement


def _attach_count_population_lineage(
    context,
    numeric_statement,
    base,
    where,
    *,
    groups=(),
):
    """Attach whole-population lineage without joining it into COUNT itself."""

    numeric = numeric_statement.subquery("count_values")
    observation_alias = observation_record.alias("count_observation")
    origin_alias = evidence_observation_origin.alias("count_evidence_origin")
    evidence_alias = evidence_record.alias("count_evidence")
    source_alias = source_record.alias("count_source")
    requested = set(_requested_evidence_ids(context))
    if not requested & {
        EvidenceLocator.METRIC_DEFINITION,
        EvidenceLocator.OBSERVATION_RECORD,
        EvidenceLocator.RELATION_RECORD,
        EvidenceLocator.EVIDENCE_RECORD,
        EvidenceLocator.SOURCE_RECORD,
    }:
        return numeric_statement
    lineage_filters = [
        evidence_alias.c.evidence_kind
        == context.params.bind("observation", prefix="count_evidence_kind")
    ]
    operation = context.task.operation
    ownerships = ()
    ownership_conditions = ()
    if (
        isinstance(operation, LogicalAggregateOperationV2)
        and operation.aggregation.population_grain_id
        == "representative-product.v1"
        and context.facts is not None
        and context.facts.public_fund_manifest is not None
    ):
        ownerships = context.facts.public_fund_manifest.population_metric_ownerships
    if ownerships:
        ownership_conditions = tuple(
            sa.and_(
                observation_alias.c.entity_id
                == context.params.bind(
                    item.owner_entity_id, prefix="count_owned_entity_id"
                ),
                observation_alias.c.metric_id
                == context.params.bind(
                    item.metric_id, prefix="count_owned_metric_id"
                ),
                observation_alias.c.metric_definition_version
                == context.params.bind(
                    item.metric_definition_version,
                    prefix="count_owned_metric_definition_version",
                ),
                observation_alias.c.observation_id
                == context.params.bind(
                    item.observation_id, prefix="count_owned_observation_id"
                ),
                origin_alias.c.evidence_id
                == context.params.bind(
                    item.evidence_id, prefix="count_owned_evidence_id"
                ),
                evidence_alias.c.source_id
                == context.params.bind(
                    item.source_id, prefix="count_owned_source_id"
                ),
                source_alias.c.source_id
                == context.params.bind(
                    item.source_id, prefix="count_owned_source_record_id"
                ),
            )
            for item in ownerships
        )
        lineage_filters.append(sa.or_(*ownership_conditions))
        approved_refs = tuple(
            dict.fromkeys(
                f"{item.metric_id}:{item.metric_definition_version}"
                for item in ownerships
            )
        )
    else:
        approved_refs = context.count_lineage_metric_definition_refs
    if not approved_refs:
        raise SqlCompileRejection("COUNT_LINEAGE_METRIC_OWNERSHIP_REQUIRED")
    lineage_filters.append(
        sa.or_(
            *(
                sa.and_(
                    observation_alias.c.metric_id
                    == context.params.bind(
                        reference.rpartition(":")[0], prefix="count_metric"
                    ),
                    observation_alias.c.metric_definition_version
                    == context.params.bind(
                        reference.rpartition(":")[2],
                        prefix="count_metric_definition_version",
                    ),
                )
                for reference in approved_refs
            )
        )
    )
    lineage_base = (
        base.join(
            observation_alias,
            sa.and_(
                observation_alias.c.dataset_version == product.c.dataset_version,
                observation_alias.c.entity_id == product.c.entity_id,
            ),
        )
        .join(
            origin_alias,
            sa.and_(
                origin_alias.c.dataset_version == observation_alias.c.dataset_version,
                origin_alias.c.observation_id == observation_alias.c.observation_id,
            ),
        )
        .join(
            evidence_alias,
            sa.and_(
                evidence_alias.c.dataset_version == origin_alias.c.dataset_version,
                evidence_alias.c.evidence_id == origin_alias.c.evidence_id,
            ),
        )
        .join(
            source_alias,
            sa.and_(
                source_alias.c.dataset_version == evidence_alias.c.dataset_version,
                source_alias.c.source_id == evidence_alias.c.source_id,
            ),
        )
    )
    relation_lineage = None
    relation_conditions = ()
    representative_edges = (
        context.facts.public_fund_manifest.representative_share_edges
        if ownerships
        and context.facts is not None
        and context.facts.public_fund_manifest is not None
        else ()
    )
    if representative_edges:
        relation_alias = relation_record.alias("count_relation")
        relation_origin_alias = evidence_relation_origin.alias(
            "count_relation_evidence_origin"
        )
        relation_evidence_alias = evidence_record.alias("count_relation_evidence")
        relation_source_alias = source_record.alias("count_relation_source")
        relation_lineage = (
            relation_alias,
            relation_evidence_alias,
            relation_source_alias,
        )
        lineage_base = (
            lineage_base.join(
                relation_alias,
                sa.and_(
                    relation_alias.c.dataset_version == product.c.dataset_version,
                    relation_alias.c.subject_id == product.c.entity_id,
                ),
            )
            .join(
                relation_origin_alias,
                sa.and_(
                    relation_origin_alias.c.dataset_version
                    == relation_alias.c.dataset_version,
                    relation_origin_alias.c.relation_id
                    == relation_alias.c.relation_id,
                ),
            )
            .join(
                relation_evidence_alias,
                sa.and_(
                    relation_evidence_alias.c.dataset_version
                    == relation_origin_alias.c.dataset_version,
                    relation_evidence_alias.c.evidence_id
                    == relation_origin_alias.c.evidence_id,
                ),
            )
            .join(
                relation_source_alias,
                sa.and_(
                    relation_source_alias.c.dataset_version
                    == relation_evidence_alias.c.dataset_version,
                    relation_source_alias.c.source_id
                    == relation_evidence_alias.c.source_id,
                ),
            )
        )
        relation_conditions = tuple(
            sa.and_(
                relation_alias.c.relation_id
                == context.params.bind(
                    edge.relation_id,
                    prefix="count_owned_relation_id",
                ),
                relation_alias.c.subject_id
                == context.params.bind(
                    edge.representative_id,
                    prefix="count_owned_representative_id",
                ),
                relation_alias.c.object_id
                == context.params.bind(
                    edge.share_class_id,
                    prefix="count_owned_share_class_id",
                ),
                relation_alias.c.predicate_id
                == context.params.bind(
                    edge.predicate_id,
                    prefix="count_owned_relation_predicate",
                ),
                relation_origin_alias.c.evidence_id
                == context.params.bind(
                    edge.evidence_id,
                    prefix="count_owned_relation_evidence_id",
                ),
                relation_evidence_alias.c.source_id
                == context.params.bind(
                    edge.source_id,
                    prefix="count_owned_relation_source_id",
                ),
                relation_source_alias.c.source_id
                == context.params.bind(
                    edge.source_id,
                    prefix="count_owned_relation_source_record_id",
                ),
            )
            for edge in representative_edges
        )
        lineage_filters.append(sa.or_(*relation_conditions))
    lineage_columns = [
        expression.label(f"group_{index}")
        for index, expression in enumerate(groups)
    ]
    if EvidenceLocator.METRIC_DEFINITION in requested:
        separator = context.params.bind(":", prefix="metric_definition_separator")
        lineage_columns.append(
            sa.func.array_agg(
                sa.distinct(
                    sa.func.concat(
                        observation_alias.c.metric_id,
                        separator,
                        observation_alias.c.metric_definition_version,
                    )
                )
            ).label("metric_definition_refs")
        )
    if EvidenceLocator.OBSERVATION_RECORD in requested:
        lineage_columns.append(
            sa.func.array_agg(sa.distinct(observation_alias.c.observation_id)).label(
                "observation_ids"
            )
        )
    if ownership_conditions:
        observation_lineage_ref = sa.case(
            *(
                (
                    condition,
                    context.params.bind(
                        population_metric_ownership_lineage_ref(item),
                        prefix="observation_lineage_ref",
                    ),
                )
                for item, condition in zip(ownerships, ownership_conditions, strict=True)
            ),
            else_=None,
        )
        lineage_columns.append(
            sa.func.array_agg(sa.distinct(observation_lineage_ref)).label(
                "observation_lineage_refs"
            )
        )
    if EvidenceLocator.RELATION_RECORD in requested:
        if relation_lineage is None:
            raise SqlCompileRejection("COUNT_RELATION_LINEAGE_NOT_OWNED")
        lineage_columns.append(
            sa.func.array_agg(sa.distinct(relation_lineage[0].c.relation_id)).label(
                "relation_ids"
            )
        )
    if relation_conditions:
        relation_lineage_ref = sa.case(
            *(
                (
                    condition,
                    context.params.bind(
                        representative_share_edge_lineage_ref(edge),
                        prefix="relation_lineage_ref",
                    ),
                )
                for edge, condition in zip(
                    representative_edges, relation_conditions, strict=True
                )
            ),
            else_=None,
        )
        lineage_columns.append(
            sa.func.array_agg(sa.distinct(relation_lineage_ref)).label(
                "relation_lineage_refs"
            )
        )
    if EvidenceLocator.EVIDENCE_RECORD in requested:
        observation_evidence = sa.func.array_agg(
            sa.distinct(evidence_alias.c.evidence_id)
        )
        evidence_values = (
            sa.func.array_cat(
                observation_evidence,
                sa.func.array_agg(sa.distinct(relation_lineage[1].c.evidence_id)),
            )
            if relation_lineage is not None
            else observation_evidence
        )
        lineage_columns.append(evidence_values.label("evidence_ids"))
    if EvidenceLocator.SOURCE_RECORD in requested:
        observation_sources = sa.func.array_agg(sa.distinct(source_alias.c.source_id))
        source_values = (
            sa.func.array_cat(
                observation_sources,
                sa.func.array_agg(sa.distinct(relation_lineage[2].c.source_id)),
            )
            if relation_lineage is not None
            else observation_sources
        )
        lineage_columns.append(source_values.label("source_ids"))
    lineage_statement = (
        sa.select(*lineage_columns)
        .select_from(lineage_base)
        .where(*where, *lineage_filters)
    )
    if groups:
        lineage_statement = lineage_statement.group_by(*groups)
    lineage = lineage_statement.subquery("count_population_lineage")
    join_condition = sa.true()
    if groups:
        join_condition = sa.and_(
            *(
                numeric.c[f"group_{index}"] == lineage.c[f"group_{index}"]
                for index in range(len(groups))
            )
        )
    lineage_outputs = tuple(
        column
        for column in lineage.c
        if not column.key.startswith("group_")
    )
    statement = sa.select(*numeric.c, *lineage_outputs).select_from(
        numeric.join(lineage, join_condition)
    )
    if groups:
        statement = statement.order_by(
            *(numeric.c[f"group_{index}"] for index in range(len(groups)))
        )
    return statement


def _count_lineage_metric_definition_refs(task, bindings, facts) -> tuple[str, ...]:
    operation = task.operation
    if (
        not isinstance(operation, LogicalAggregateOperationV2)
        or operation.aggregation.function_id is not AggregationFunction.COUNT
    ):
        return ()
    if (
        operation.aggregation.population_grain_id == "representative-product.v1"
        and facts is not None
        and facts.public_fund_manifest is not None
    ):
        return tuple(
            dict.fromkeys(
                f"{item.metric_id}:{item.metric_definition_version}"
                for item in facts.public_fund_manifest.population_metric_ownerships
            )
        )
    family = task.scope.product_family_ids[0]
    binding_ids = task.binding_ids or tuple(
        item.id
        for item in bindings.bindings_by_id.values()
        if item.product_family_id is family
        and item.availability is PhysicalBindingAvailability.VERIFIED
    )
    return tuple(
        dict.fromkeys(
            reference
            for binding_id in binding_ids
            for reference in bindings.bindings_by_id[
                binding_id
            ].approved_metric_definition_refs
        )
    )


def _attach_flat_aggregate_evidence(
    context,
    numeric_statement,
    *,
    base,
    where,
    groups,
    evidence_aliases,
    observation_aliases=(),
):
    """Aggregate lineage on a separate branch so it cannot multiply values."""

    numeric = numeric_statement.subquery("aggregate_values")
    if not evidence_aliases:
        statement = sa.select(*numeric.c).select_from(numeric)
        if groups:
            statement = statement.order_by(
                *(numeric.c[f"group_{index}"] for index in range(len(groups)))
            )
        return statement

    evidence_base = base
    combined_evidence = evidence_aliases[0].c.evidence_ids
    combined_sources = evidence_aliases[0].c.source_ids
    for evidence_alias in evidence_aliases[1:]:
        combined_evidence = combined_evidence.op("||")(
            evidence_alias.c.evidence_ids
        )
        combined_sources = combined_sources.op("||")(evidence_alias.c.source_ids)
    evidence_item = (
        sa.func.unnest(combined_evidence)
        .table_valued("evidence_id")
        .lateral("aggregate_evidence_item")
    )
    source_item = (
        sa.func.unnest(combined_sources)
        .table_valued("source_id")
        .lateral("aggregate_source_item")
    )
    evidence_base = evidence_base.join(evidence_item, sa.true()).join(
        source_item, sa.true()
    )

    observation_item = None
    metric_definition_item = None
    if observation_aliases:
        combined_observations = sa.dialects.postgresql.array(
            tuple(alias.c.observation_id for alias in observation_aliases)
        )
        observation_item = (
            sa.func.unnest(combined_observations)
            .table_valued("observation_id")
            .lateral("aggregate_observation_item")
        )
        evidence_base = evidence_base.join(observation_item, sa.true())
        if EvidenceLocator.METRIC_DEFINITION in set(
            _requested_evidence_ids(context)
        ):
            separator = context.params.bind(
                ":", prefix="metric_definition_separator"
            )
            combined_metric_definitions = sa.dialects.postgresql.array(
                tuple(
                    sa.func.concat(
                        alias.c.metric_id,
                        separator,
                        alias.c.metric_definition_version,
                    )
                    for alias in observation_aliases
                )
            )
            metric_definition_item = (
                sa.func.unnest(combined_metric_definitions)
                .table_valued("metric_definition_ref")
                .lateral("aggregate_metric_definition_item")
            )
            evidence_base = evidence_base.join(metric_definition_item, sa.true())

    evidence_columns = [
        expression.label(f"group_{index}")
        for index, expression in enumerate(groups)
    ]
    evidence_columns.extend(
        (
            sa.func.array_agg(sa.distinct(evidence_item.c.evidence_id)).label(
                "evidence_ids"
            ),
            sa.func.array_agg(sa.distinct(source_item.c.source_id)).label(
                "source_ids"
            ),
        )
    )
    if observation_item is not None:
        evidence_columns.append(
            sa.func.array_agg(
                sa.distinct(observation_item.c.observation_id)
            ).label("observation_ids")
        )
    if metric_definition_item is not None:
        evidence_columns.append(
            sa.func.array_agg(
                sa.distinct(metric_definition_item.c.metric_definition_ref)
            ).label("metric_definition_refs")
        )
    evidence_statement = (
        sa.select(*evidence_columns).select_from(evidence_base).where(*where)
    )
    if groups:
        evidence_statement = evidence_statement.group_by(*groups)
    evidence = evidence_statement.subquery("aggregate_evidence")

    join_condition = sa.true()
    if groups:
        join_condition = sa.and_(
            *(
                numeric.c[f"group_{index}"] == evidence.c[f"group_{index}"]
                for index in range(len(groups))
            )
        )
    statement = sa.select(
        *numeric.c,
        *(
            (evidence.c.observation_ids,)
            if "observation_ids" in evidence.c
            else ()
        ),
        *(
            (evidence.c.metric_definition_refs,)
            if "metric_definition_refs" in evidence.c
            else ()
        ),
        evidence.c.evidence_ids,
        evidence.c.source_ids,
    ).select_from(numeric.join(evidence, join_condition))
    if groups:
        statement = statement.order_by(
            *(numeric.c[f"group_{index}"] for index in range(len(groups)))
        )
    return statement


def _apply_qualifiers(context: _Context, statement):
    filters = _qualifier_filters(context)
    return statement.where(*filters) if filters else statement


def _qualifier_filters(context: _Context):
    qualifiers = context.task.qualifiers
    requested = {
        SemanticQualifierId.PERIOD: qualifiers.period_id,
        SemanticQualifierId.CURRENCY: qualifiers.currency_id,
        SemanticQualifierId.UNIT: qualifiers.unit_id,
        SemanticQualifierId.AS_OF: qualifiers.as_of_date,
    }
    consumed_binding_ids = tuple(context.observation_aliases)
    bindings = [
        context.bindings.binding_sets_by_key[item]
        for item in consumed_binding_ids
    ]
    if any(value is not None for value in requested.values()) and not bindings:
        if (
            isinstance(context.task.operation, LogicalAggregateOperationV2)
            and context.task.operation.aggregation.function_id is AggregationFunction.COUNT
        ):
            raise SqlCompileRejection("COUNT_QUALIFIER_BINDING_REQUIRED")
        raise SqlCompileRejection("QUALIFIER_BINDING_REQUIRED")
    for binding in bindings:
        supplied = {key for key, value in requested.items() if value is not None}
        if not set(binding.required_qualifier_ids) <= supplied:
            raise SqlCompileRejection("PHYSICAL_REQUIRED_QUALIFIER_MISSING")
        if not supplied <= set(binding.supported_qualifier_ids):
            raise SqlCompileRejection("PHYSICAL_QUALIFIER_UNSUPPORTED")
        if binding.currency_normalization_required and qualifiers.currency_id is not None:
            raise SqlCompileRejection("CROSS_CURRENCY_NORMALIZATION_UNVERIFIED")
        for qualifier_id in sorted(supplied, key=lambda item: item.value):
            policies = (
                (binding.unit_conversion_policy_id,)
                if qualifier_id is SemanticQualifierId.UNIT
                and binding.unit_conversion_policy_id is not None
                else ()
            )
            _record(
                context,
                f"qualifiers.{qualifier_id.value}",
                binding.id,
                PhysicalLoweringKind.QUALIFIER,
                binding,
                policies,
            )
    filters = []
    for binding_id, alias in context.observation_aliases.items():
        binding = context.bindings.binding_sets_by_key[binding_id]
        if qualifiers.period_id is not None:
            raise SqlCompileRejection("PERIOD_LOWERING_NOT_REGISTERED")
        if qualifiers.currency_id is not None:
            filters.append(alias.c.currency == context.params.bind(qualifiers.currency_id, prefix="currency"))
        if qualifiers.unit_id is not None:
            filters.append(alias.c.unit == context.params.bind(binding.storage_unit_id, prefix="unit"))
        if qualifiers.as_of_date is not None:
            filters.append(alias.c.applicable_date == context.params.bind(qualifiers.as_of_date, prefix="as_of"))
    return filters


def _evidence_ids(context):
    requested = _requested_evidence_ids(context)
    for index, evidence_id in enumerate(requested):
        _record(context, f"evidence.{index}", f"evidence-{evidence_id.value}.v1", PhysicalLoweringKind.EVIDENCE)
    return requested


def _requested_evidence_ids(context):
    allowed = {item.value: item for item in EvidenceLocator}
    requested = set(context.task.evidence_requirements)
    for binding_id in context.bindings.bindings_by_id:
        requested.update(item.value for item in context.bindings.bindings_by_id[binding_id].required_evidence_locators)
    if not requested <= set(allowed):
        raise SqlCompileRejection("EVIDENCE_PROJECTION_NOT_REGISTERED")
    return tuple(allowed[item] for item in sorted(requested))


def _record(context, path, binding_id, kind, binding=None, policy_ids=()):
    if isinstance(binding, _BoundMetricSet) and len(binding.definitions) > 1:
        for definition in binding.definitions:
            _record(
                context,
                path,
                definition.id,
                kind,
                definition,
                policy_ids,
            )
        return
    policies = tuple(
        dict.fromkeys(
            item
            for item in (
                *policy_ids,
                *(
                    (binding.unit_conversion_policy_id, binding.missingness_policy_id)
                    if binding is not None
                    else ()
                ),
            )
            if item is not None
        )
    )
    draft = PhysicalLoweringRecord.model_construct(
        lowering_id="pending",
        semantic_path=path,
        binding_id=binding_id,
        lowering_kind=kind,
        value_column=binding.value_column if binding is not None else None,
        policy_ids=policies,
    )
    context.records.append(
        PhysicalLoweringRecord(
            lowering_id=physical_lowering_record_id(draft),
            semantic_path=path,
            binding_id=binding_id,
            lowering_kind=kind,
            value_column=binding.value_column if binding is not None else None,
            policy_ids=policies,
        )
    )


def _predicate_concepts(predicate):
    if predicate.node_type == "atom":
        return (predicate.field_concept_id,)
    if predicate.node_type == "not":
        return _predicate_concepts(predicate.child)
    return tuple(dict.fromkeys(item for child in predicate.children for item in _predicate_concepts(child)))


def _predicate_has_missing_test(predicate, concept_id: str) -> bool:
    if predicate.node_type == "atom":
        return (
            predicate.field_concept_id == concept_id
            and predicate.operator_id.value == "is_missing"
        )
    if predicate.node_type == "not":
        return _predicate_has_missing_test(predicate.child, concept_id)
    return any(
        _predicate_has_missing_test(child, concept_id)
        for child in predicate.children
    )


def _present(context: _Context, status_column):
    return status_column.in_(
        (
            context.params.bind("present", prefix="status"),
            context.params.bind("zero", prefix="status"),
        )
    )


def _uses_representative_population(task: LogicalQueryTaskV2) -> bool:
    return (
        isinstance(task.operation, LogicalAggregateOperationV2)
        and task.operation.aggregation.population_grain_id
        == "representative-product.v1"
    )
