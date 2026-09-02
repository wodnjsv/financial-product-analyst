"""Deterministic compiler from LogicalQueryPlanV2 to read-only SQL."""

from __future__ import annotations

from dataclasses import dataclass
import sqlalchemy as sa
from pydantic import ConfigDict, model_validator
from sqlalchemy.dialects import postgresql

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.enums import ProductFamily
from financial_agent.db.schema.catalog import entity, product
from financial_agent.db.schema.evidence import evidence_record
from financial_agent.db.schema.observation import observation_record
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
)
from financial_agent.planning.physical_bindings import (
    EvidenceLocator,
    PhysicalBindingAvailability,
    PhysicalBindingRegistry,
    PhysicalReadinessFacts,
    SemanticQualifierId,
    SemanticSqlPolicyRegistry,
)
from financial_agent.planning.registry import PlanningRegistry

from .contracts import (
    COMPILER_VERSION,
    CompiledSqlRequest,
    PhysicalLoweringKind,
    PhysicalLoweringRecord,
    compiled_sql_request_id,
    physical_lowering_record_id,
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
    plan: LogicalQueryPlanV2
    task: LogicalQueryTaskV2
    bindings: PhysicalBindingRegistry
    policies: SemanticSqlPolicyRegistry
    facts: PhysicalReadinessFacts | None
    params: ParameterBuilder
    records: list[PhysicalLoweringRecord]
    observation_aliases: dict[str, sa.Alias]
    evidence_aliases: dict[str, sa.Alias]


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
            task = next((item for item in plan.tasks if item.task_id == task_id), None)
            if task is None:
                raise SqlCompileRejection("SQL_TASK_NOT_FOUND")
            self._validate_ownership(plan, task)
            context = _Context(
                plan=plan,
                task=task,
                bindings=self._bindings,
                policies=self._policies,
                facts=readiness_facts,
                params=ParameterBuilder(),
                records=[],
                observation_aliases={},
                evidence_aliases={},
            )
            statement, evidence_ids = _compile_statement(context)
            sql = str(
                statement.compile(
                    dialect=postgresql.dialect(paramstyle="named"),
                    compile_kwargs={"render_postcompile": True},
                )
            )
            kwargs = dict(
                logical_plan_id=plan.logical_plan_id,
                task_id=task.task_id,
                statement=sql,
                parameters=tuple(context.params.parameters),
                lowering_records=tuple(context.records),
                applied_policy_ids=task.policy_ids,
                evidence_projection_ids=evidence_ids,
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
                population_manifest_id=(
                    readiness_facts.public_fund_manifest.manifest_id
                    if readiness_facts is not None
                    and readiness_facts.public_fund_manifest is not None
                    and _uses_representative_population(task)
                    else None
                ),
                population_manifest_hash=(
                    readiness_facts.public_fund_manifest_hash
                    if readiness_facts is not None
                    and _uses_representative_population(task)
                    else None
                ),
            )
            draft = CompiledSqlRequest.model_construct(compiled_request_id="pending", **kwargs)
            request = CompiledSqlRequest(
                compiled_request_id=compiled_sql_request_id(draft), **kwargs
            )
            return SqlCompilationOutcome(request=request)
        except SqlCompileRejection as error:
            return SqlCompilationOutcome(
                rejection=SqlCompileRejectionRecord(
                    code=error.code,
                    logical_plan_id=plan.logical_plan_id,
                    task_id=task_id,
                )
            )

    def _validate_ownership(
        self, plan: LogicalQueryPlanV2, task: LogicalQueryTaskV2
    ) -> None:
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
        if any(item.execution_route.value != "semantic_sql" for item in task.execution_steps):
            raise SqlCompileRejection("SQL_EXECUTION_ROUTE_REQUIRED")
        if any(item not in self._bindings.bindings_by_id for item in task.binding_ids):
            raise SqlCompileRejection("PHYSICAL_BINDING_NOT_REGISTERED")
        for binding_id in task.binding_ids:
            binding = self._bindings.bindings_by_id[binding_id]
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
            if not required <= set(task.policy_ids):
                raise SqlCompileRejection("PHYSICAL_POLICY_OWNERSHIP_MISMATCH")
        if any(item not in self._policies.policies_by_id for item in task.policy_ids):
            raise SqlCompileRejection("SQL_POLICY_NOT_REGISTERED")
        if any(not self._policies.policies_by_id[item].verified for item in task.policy_ids):
            raise SqlCompileRejection("SQL_POLICY_UNVERIFIED")


def _compile_statement(context: _Context):
    task = context.task
    if len(task.scope.product_family_ids) != 1:
        raise SqlCompileRejection("SQL_SINGLE_FAMILY_SCOPE_REQUIRED")
    if task.scope.prior_result_binding is not None:
        raise SqlCompileRejection("PRIOR_RESULT_SQL_INPUT_NOT_BOUND")
    family = task.scope.product_family_ids[0]
    base = product.join(
        entity,
        sa.and_(
            product.c.dataset_version == entity.c.dataset_version,
            product.c.entity_id == entity.c.entity_id,
        ),
    )
    dataset = context.params.bind(context.plan.dataset_version, prefix="dataset")
    family_param = context.params.bind(family.value, prefix="family")
    where = [
        product.c.dataset_version == dataset,
        product.c.product_family == family_param,
    ]
    _record(context, "scope.product_family_ids", "catalog-product-family.v1", PhysicalLoweringKind.SCOPE)
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
            where.append(_present(context, alias.c.value_status))
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
                    evidence_alias.c.evidence_id.label(f"evidence_id_{index}"),
                    evidence_alias.c.source_id.label(f"source_id_{index}"),
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
                    evidence_alias.c.evidence_id.label(f"evidence_id_{index}"),
                    evidence_alias.c.source_id.label(f"source_id_{index}"),
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
                    evidence_alias.c.evidence_id.label(f"evidence_id_{index}"),
                    evidence_alias.c.source_id.label(f"source_id_{index}"),
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
                    evidence_alias.c.evidence_id.label(f"evidence_id_{index}"),
                    evidence_alias.c.source_id.label(f"source_id_{index}"),
                )
            )
        statement = sa.select(*selected).select_from(base).where(*where).order_by(product.c.entity_id.asc())
    elif isinstance(operation, LogicalAggregateOperationV2):
        statement = _aggregate(context, base, where, family, operation)
    else:
        raise SqlCompileRejection("SQL_ACTION_NOT_SUPPORTED")

    statement = _apply_qualifiers(context, statement)
    evidence = _evidence_ids(context)
    return statement, evidence


def _field(context: _Context, family: ProductFamily, concept_id: str):
    binding = context.bindings.binding_for(family, concept_id)
    if binding is None or binding.id not in context.task.binding_ids:
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
    evidence_alias = evidence_record.alias(
        f"evidence_{len(context.evidence_aliases)}"
    )
    context.evidence_aliases[binding.id] = evidence_alias
    return base.join(
        evidence_alias,
        sa.and_(
            evidence_alias.c.dataset_version == alias.c.dataset_version,
            evidence_alias.c.subject_id == alias.c.entity_id,
            evidence_alias.c.predicate_id == alias.c.metric_id,
            evidence_alias.c.applicable_date.is_not_distinct_from(
                alias.c.applicable_date
            ),
            evidence_alias.c.evidence_kind
            == context.params.bind("observation", prefix="evidence_kind"),
        ),
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
        representative = representative_product_cte(context.params)
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
        evidence_alias = context.evidence_aliases[binding.id]
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
                sa.func.array_agg(sa.distinct(evidence_alias.c.evidence_id)).label(
                    "evidence_ids"
                ),
                sa.func.array_agg(sa.distinct(evidence_alias.c.source_id)).label(
                    "source_ids"
                ),
            )
        )
        _record(context, "operation.aggregation.target", binding.id, PhysicalLoweringKind.AGGREGATION, binding, (spec.population_grain_id, spec.dedup_policy_id))

    groups = []
    for index, concept in enumerate(spec.group_by_field_concept_ids):
        group_expression, group_binding, group_alias = _field(context, family, concept)
        if group_alias.name not in joined_alias_names:
            base = _join_observation_with_evidence(
                context, base, group_alias, group_binding
            )
            joined_alias_names.add(group_alias.name)
        where.append(_present(context, group_alias.c.value_status))
        selected.insert(index, group_expression.label(f"group_{index}"))
        groups.append(group_expression)
        _record(context, f"operation.aggregation.group_by.{index}", group_binding.id, PhysicalLoweringKind.GROUPING, group_binding)
    statement = sa.select(*selected).select_from(base).where(*where)
    if groups:
        statement = statement.group_by(*groups).order_by(*groups)
    _record(context, "operation.aggregation.population", "catalog-product-family.v1", PhysicalLoweringKind.DEDUPLICATION, policy_ids=(spec.population_grain_id, spec.dedup_policy_id))
    return statement


def _apply_qualifiers(context: _Context, statement):
    qualifiers = context.task.qualifiers
    requested = {
        SemanticQualifierId.PERIOD: qualifiers.period_id,
        SemanticQualifierId.CURRENCY: qualifiers.currency_id,
        SemanticQualifierId.UNIT: qualifiers.unit_id,
        SemanticQualifierId.AS_OF: qualifiers.as_of_date,
    }
    bindings = [context.bindings.bindings_by_id[item] for item in context.task.binding_ids]
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
        binding = context.bindings.bindings_by_id[binding_id]
        if qualifiers.period_id is not None:
            raise SqlCompileRejection("PERIOD_LOWERING_NOT_REGISTERED")
        if qualifiers.currency_id is not None:
            filters.append(alias.c.currency == context.params.bind(qualifiers.currency_id, prefix="currency"))
        if qualifiers.unit_id is not None:
            filters.append(alias.c.unit == context.params.bind(binding.storage_unit_id, prefix="unit"))
        if qualifiers.as_of_date is not None:
            filters.append(alias.c.applicable_date == context.params.bind(qualifiers.as_of_date, prefix="as_of"))
    if filters:
        statement = statement.where(*filters)
    return statement


def _evidence_ids(context):
    allowed = {item.value: item for item in EvidenceLocator}
    requested = set(context.task.evidence_requirements)
    for binding_id in context.task.binding_ids:
        requested.update(item.value for item in context.bindings.bindings_by_id[binding_id].required_evidence_locators)
    if not requested <= set(allowed):
        raise SqlCompileRejection("EVIDENCE_PROJECTION_NOT_REGISTERED")
    for index, evidence_id in enumerate(sorted(requested)):
        _record(context, f"evidence.{index}", f"evidence-{evidence_id}.v1", PhysicalLoweringKind.EVIDENCE)
    return tuple(allowed[item] for item in sorted(requested))


def _record(context, path, binding_id, kind, binding=None, policy_ids=()):
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
