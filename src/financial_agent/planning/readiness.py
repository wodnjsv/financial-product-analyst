"""Independent physical executability assessment for solved semantic contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pydantic import ConfigDict, Field, ValidationError, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.query_contracts import (
    is_population_count,
    PlanReadiness,
    PredicateAllOfV2,
    PredicateAnyOfV2,
    PredicateAtomV2,
    PredicateNodeV2,
    PredicateNotV2,
    SolvedQueryContractCandidateV2,
    SemanticValueKind,
)
from financial_agent.intent.view import ActiveDatasetPin

from .physical_bindings import (
    EXPECTED_POLICY_REGISTRY_HASH,
    POLICY_REGISTRY_VERSION,
    PhysicalBindingAvailability,
    PhysicalBindingDefinition,
    PhysicalBindingRegistry,
    PhysicalReadinessFacts,
    PopulationMetricOwnership,
    SemanticQualifierId,
    SemanticSqlPolicyKind,
    SemanticSqlPolicyRegistry,
    TRUSTED_PUBLIC_FUND_MANIFEST_PINS,
)


_KNOWN_CURRENCY_QUALIFIER_IDS = frozenset({"KRW", "USD"})
_KNOWN_UNIT_QUALIFIER_IDS = frozenset({"percent", "KRW", "USD"})
_PERIOD_QUALIFIER_PATTERN = re.compile(r"^P[1-9][0-9]*(?:Y|M)$")
_MAX_PRIOR_RESULT_DEPTH = 16


class PlanReadinessResult(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    frame_id: Identifier
    contract_hash: Sha256Hex
    dataset_version: Identifier
    dataset_pin: Sha256Hex
    binding_registry_version: Identifier
    binding_registry_hash: Sha256Hex
    policy_registry_version: Identifier
    policy_registry_hash: Sha256Hex
    readiness: PlanReadiness
    reason_codes: tuple[Identifier, ...]
    binding_ids: tuple[Identifier, ...]
    policy_ids: tuple[Identifier, ...]
    unit_conversion_policy_ids: tuple[Identifier, ...]


class PriorResultReadinessSource(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    binding_name: Identifier
    producer_contract: SolvedQueryContractCandidateV2
    producer_assessment: PlanReadinessResult
    consumer_frame_id: Identifier
    consumer_contract_hash: Sha256Hex
    product_family_ids: tuple[ProductFamily, ...] = Field(min_length=1)
    producer_prior_result_context: PriorResultReadinessContext | None = None

    @model_validator(mode="after")
    def validate_source(self):
        if self.producer_contract.frame_id == self.consumer_frame_id:
            raise ValueError("PRIOR_RESULT_READINESS_SELF_REFERENCE")
        if len(self.product_family_ids) != len(set(self.product_family_ids)):
            raise ValueError("PRIOR_RESULT_READINESS_FAMILY_DUPLICATE")
        if (
            self.producer_assessment.frame_id != self.producer_contract.frame_id
            or self.producer_assessment.contract_hash
            != canonical_sha256(self.producer_contract)
            or (
                self.producer_contract.scope.product_family_ids
                and self.product_family_ids
                != self.producer_contract.scope.product_family_ids
            )
        ):
            raise ValueError("PRIOR_RESULT_READINESS_PRODUCER_MISMATCH")
        return self


class PriorResultReadinessContext(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dataset_version: Identifier
    dataset_pin: Sha256Hex
    binding_registry_version: Identifier
    binding_registry_hash: Sha256Hex
    policy_registry_version: Identifier
    policy_registry_hash: Sha256Hex
    sources: tuple[PriorResultReadinessSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_context(self):
        names = tuple(item.binding_name for item in self.sources)
        if len(names) != len(set(names)):
            raise ValueError("PRIOR_RESULT_READINESS_SOURCE_DUPLICATE")
        return self


@dataclass(slots=True)
class _Assessment:
    reasons: set[str] = field(default_factory=set)
    binding_ids: set[str] = field(default_factory=set)
    policy_ids: set[str] = field(default_factory=set)
    unit_conversion_policy_ids: set[str] = field(default_factory=set)
    reason_levels: dict[str, PlanReadiness] = field(default_factory=dict)

    def add(self, reason: str, level: PlanReadiness) -> None:
        self.reasons.add(reason)
        current = self.reason_levels.get(reason)
        if current is None or _severity(level) > _severity(current):
            self.reason_levels[reason] = level


def assess_plan_readiness(
    contract: SolvedQueryContractCandidateV2,
    bindings: PhysicalBindingRegistry,
    policies: SemanticSqlPolicyRegistry,
    *,
    active_dataset_pin: ActiveDatasetPin,
    facts: PhysicalReadinessFacts | None = None,
    prior_result_context: PriorResultReadinessContext | None = None,
    _prior_result_depth: int = 0,
    _prior_result_ancestors: frozenset[tuple[str, str]] = frozenset(),
) -> PlanReadinessResult:
    """Assess all semantic roles without changing the solved contract."""

    state = _Assessment()
    if (
        facts is not None
        and facts.public_fund_manifest is not None
        and facts.public_fund_manifest.dataset_pin != active_dataset_pin.manifest_hash
    ):
        state.add("DATASET_PROVENANCE_MISMATCH", PlanReadiness.BLOCKED)
    if contract.registry_pins != bindings.semantic_registry_pins:
        state.add("SEMANTIC_REGISTRY_PIN_MISMATCH", PlanReadiness.BLOCKED)
    if (
        bindings.physical_policy_registry_version != policies.registry_version
        or bindings.physical_policy_registry_hash != policies.registry_hash
    ):
        state.add("PHYSICAL_POLICY_REGISTRY_PIN_MISMATCH", PlanReadiness.BLOCKED)
    families = tuple(contract.scope.product_family_ids)
    if contract.scope.prior_result_binding:
        context_source = _prior_result_source(
            contract,
            prior_result_context,
            bindings,
            policies,
            active_dataset_pin,
            facts,
            state,
            depth=_prior_result_depth,
            ancestors=_prior_result_ancestors,
        )
        if context_source is not None:
            if families and families != context_source.product_family_ids:
                state.add(
                    "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
                    PlanReadiness.BLOCKED,
                )
            else:
                families = context_source.product_family_ids
    if not families:
        state.add("PHYSICAL_SCOPE_FAMILY_REQUIRED", PlanReadiness.BLOCKED)
    known_entity_ids = facts.known_entity_ids if facts is not None else frozenset()
    if set(contract.scope.entity_refs) - known_entity_ids:
        state.add("ENTITY_IDENTITY_UNVERIFIED", PlanReadiness.LIMITED)
    field_roles: list[tuple[str, str, object | None]] = []
    policy_roles: list[tuple[str, SemanticSqlPolicyKind, str]] = []
    if contract.action_id is IntentType.LOOKUP:
        if contract.projections.default_profile_id:
            policy_roles.append((contract.projections.default_profile_id, SemanticSqlPolicyKind.DEFAULT, "SQL_POLICY_NOT_REGISTERED"))
            state.add("PROJECTION_PROFILE_NOT_EXPANDED", PlanReadiness.BLOCKED)
        field_roles.extend((item, "projection", None) for item in contract.projections.field_concept_ids)
    elif contract.action_id is IntentType.SCREEN:
        _collect_predicate(contract.predicate, field_roles, policy_roles)
    elif contract.action_id is IntentType.RANK:
        for ordering in contract.ordering:
            field_roles.append((ordering.field_concept_id, "ordering", ordering))
            if ordering.direction_policy_id:
                policy_roles.append((ordering.direction_policy_id, SemanticSqlPolicyKind.DEFAULT, "SQL_POLICY_NOT_REGISTERED"))
            policy_roles.append((ordering.nulls_policy_id, SemanticSqlPolicyKind.MISSINGNESS, "SQL_POLICY_NOT_REGISTERED"))
            policy_roles.append((ordering.tie_break_policy_id, SemanticSqlPolicyKind.STABLE_TIE, "SQL_POLICY_NOT_REGISTERED"))
        if contract.limit_policy_id:
            policy_roles.append((contract.limit_policy_id, SemanticSqlPolicyKind.DEFAULT, "SQL_POLICY_NOT_REGISTERED"))
        if contract.predicate is not None:
            _collect_predicate(contract.predicate, field_roles, policy_roles)
    elif contract.action_id is IntentType.COMPARE:
        if contract.comparison.subject_refs:
            unknown_subjects = set(contract.comparison.subject_refs) - (
                facts.known_entity_ids if facts is not None else frozenset()
            )
            if unknown_subjects:
                state.add("ENTITY_IDENTITY_UNVERIFIED", PlanReadiness.LIMITED)
        if contract.comparison.group_basis_id and (
            facts is None
            or contract.comparison.group_basis_id not in facts.known_group_basis_ids
        ):
            state.add("COMPARISON_GROUP_BASIS_UNVERIFIED", PlanReadiness.LIMITED)
        field_roles.extend(
            (item, "comparison", None) for item in contract.comparison.metric_concept_ids
        )
        if contract.comparison.projection_profile_id:
            policy_roles.append((contract.comparison.projection_profile_id, SemanticSqlPolicyKind.DEFAULT, "SQL_POLICY_NOT_REGISTERED"))
            state.add("PROJECTION_PROFILE_NOT_EXPANDED", PlanReadiness.BLOCKED)
        policy_roles.append((contract.comparison.basis_policy_id, SemanticSqlPolicyKind.COMPARISON, "SQL_POLICY_NOT_REGISTERED"))
        if contract.comparison.normalization_policy_id:
            policy_roles.append((contract.comparison.normalization_policy_id, SemanticSqlPolicyKind.NORMALIZATION, "SQL_POLICY_NOT_REGISTERED"))
    elif contract.action_id is IntentType.AGGREGATE:
        aggregation = contract.aggregation
        if aggregation.target_field_concept_id:
            field_roles.append((aggregation.target_field_concept_id, "aggregation", aggregation))
        field_roles.extend(
            (item, "grouping", aggregation)
            for item in aggregation.group_by_field_concept_ids
        )
        policy_roles.extend((
            (aggregation.population_grain_id, SemanticSqlPolicyKind.POPULATION_GRAIN, "SQL_POLICY_NOT_REGISTERED"),
            (aggregation.dedup_policy_id, SemanticSqlPolicyKind.DEDUPLICATION, "SQL_POLICY_NOT_REGISTERED"),
        ))
        if is_population_count(aggregation.function_id):
            if aggregation.count_population_id != aggregation.population_grain_id:
                state.add("COUNT_POPULATION_MISMATCH", PlanReadiness.BLOCKED)
            policy_roles.append((
                aggregation.count_population_id,
                SemanticSqlPolicyKind.POPULATION_GRAIN,
                "COUNT_POPULATION_NOT_REGISTERED",
            ))
        if aggregation.bucket_policy_id:
            policy_roles.append((aggregation.bucket_policy_id.value, SemanticSqlPolicyKind.BUCKETING, "SQL_POLICY_NOT_REGISTERED"))
        if contract.predicate is not None:
            _collect_predicate(contract.predicate, field_roles, policy_roles)
    elif contract.action_id is IntentType.CALCULATE:
        policy_roles.append((contract.calculation.recipe_id, SemanticSqlPolicyKind.RECIPE, "RECIPE_NOT_REGISTERED"))
        field_roles.extend(
            (item.field_concept_id, "calculation_operand", None)
            for item in contract.calculation.operands
            if item.field_concept_id is not None
        )
        if any(
            item.value_ref is not None
            and (
                facts is None or item.value_ref not in facts.known_value_ref_ids
            )
            for item in contract.calculation.operands
        ):
            state.add("CALCULATION_VALUE_REF_UNVERIFIED", PlanReadiness.LIMITED)
    elif contract.action_id is IntentType.SIMILAR:
        policy_roles.append((contract.similarity.policy_id, SemanticSqlPolicyKind.SIMILARITY, "SQL_POLICY_NOT_REGISTERED"))
        policy_roles.append(("minimum-dimension-coverage.v1", SemanticSqlPolicyKind.COVERAGE, "SQL_POLICY_NOT_REGISTERED"))
        if facts is None or contract.similarity.anchor_ref not in facts.known_entity_ids:
            state.add("ENTITY_IDENTITY_UNVERIFIED", PlanReadiness.LIMITED)
        field_roles.extend(
            (item, "similarity_dimension", None)
            for item in contract.similarity.dimension_concept_ids
        )
        if contract.similarity.default_profile_id:
            policy_roles.append((contract.similarity.default_profile_id, SemanticSqlPolicyKind.DEFAULT, "SQL_POLICY_NOT_REGISTERED"))
            state.add("SIMILARITY_PROFILE_NOT_EXPANDED", PlanReadiness.BLOCKED)
    elif contract.action_id is IntentType.EXPLAIN:
        if contract.explanation.profile_id:
            policy_roles.append((contract.explanation.profile_id, SemanticSqlPolicyKind.DEFAULT, "SQL_POLICY_NOT_REGISTERED"))
            state.add("EXPLANATION_PROFILE_NOT_EXPANDED", PlanReadiness.BLOCKED)
        if contract.explanation.topic_concept_id:
            field_roles.append((contract.explanation.topic_concept_id, "explanation_topic", None))

    resolved_bindings: list[PhysicalBindingDefinition] = []
    for field_id, role, role_value in field_roles:
        resolved_bindings.extend(
            _assess_field(field_id, role, role_value, families, bindings, state)
        )
    for binding in resolved_bindings:
        for policy_id in (
            binding.unit_conversion_policy_id,
            binding.missingness_policy_id,
        ):
            if policy_id is not None:
                expected_kind = (
                    SemanticSqlPolicyKind.UNIT_CONVERSION
                    if policy_id == binding.unit_conversion_policy_id
                    else SemanticSqlPolicyKind.MISSINGNESS
                )
                policy_roles.append((policy_id, expected_kind, "SQL_POLICY_NOT_REGISTERED"))
    for policy_id, expected_kind, missing_reason in policy_roles:
        _assess_policy(policy_id, expected_kind, missing_reason, families, policies, state)
    _assess_qualifiers(contract, resolved_bindings, state)
    if contract.action_id is IntentType.AGGREGATE:
        _assess_aggregate_grain(
            contract.aggregation,
            families,
            resolved_bindings,
            bindings,
            policies,
            facts,
            state,
        )
    _assess_currency_normalization(contract, resolved_bindings, state)
    if contract.action_id is IntentType.RANK and any(
        item.product_family_id is ProductFamily.PUBLIC_FUND
        and item.semantic_concept_id == "aum"
        for item in resolved_bindings
    ):
        state.add("PUBLIC_FUND_GRAIN_UNVERIFIED", PlanReadiness.LIMITED)

    if not state.reasons:
        readiness = PlanReadiness.EXECUTABLE
    else:
        readiness = max(state.reason_levels.values(), key=_severity)
    return PlanReadinessResult(
        frame_id=contract.frame_id,
        contract_hash=canonical_sha256(contract),
        dataset_version=active_dataset_pin.dataset_version,
        dataset_pin=active_dataset_pin.manifest_hash,
        binding_registry_version=bindings.registry_version,
        binding_registry_hash=bindings.registry_hash,
        policy_registry_version=policies.registry_version,
        policy_registry_hash=policies.registry_hash,
        readiness=readiness,
        reason_codes=tuple(sorted(state.reasons)),
        binding_ids=tuple(sorted(state.binding_ids)),
        policy_ids=tuple(sorted(state.policy_ids)),
        unit_conversion_policy_ids=tuple(sorted(state.unit_conversion_policy_ids)),
    )


def _prior_result_source(
    contract: SolvedQueryContractCandidateV2,
    context: PriorResultReadinessContext | None,
    bindings: PhysicalBindingRegistry,
    policies: SemanticSqlPolicyRegistry,
    active_dataset_pin: ActiveDatasetPin,
    facts: PhysicalReadinessFacts | None,
    state: _Assessment,
    *,
    depth: int,
    ancestors: frozenset[tuple[str, str]],
) -> PriorResultReadinessSource | None:
    if context is None:
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_REQUIRED",
            PlanReadiness.BLOCKED,
        )
        return None
    try:
        context = PriorResultReadinessContext.model_validate(
            context.model_dump(mode="python", warnings=False)
        )
    except (AttributeError, ValidationError, ValueError, RecursionError):
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
            PlanReadiness.BLOCKED,
        )
        return None
    expected_binding = contract.scope.prior_result_binding
    if (
        expected_binding is None
        or len(context.sources) != 1
        or context.sources[0].binding_name != expected_binding
    ):
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
            PlanReadiness.BLOCKED,
        )
        return None
    if depth >= _MAX_PRIOR_RESULT_DEPTH:
        state.add(
            "PRIOR_RESULT_READINESS_DEPTH_EXCEEDED",
            PlanReadiness.BLOCKED,
        )
        return None
    if (
        context.dataset_version != active_dataset_pin.dataset_version
        or context.dataset_pin != active_dataset_pin.manifest_hash
        or context.binding_registry_version != bindings.registry_version
        or context.binding_registry_hash != bindings.registry_hash
        or context.policy_registry_version != policies.registry_version
        or context.policy_registry_hash != policies.registry_hash
    ):
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
            PlanReadiness.BLOCKED,
        )
        return None
    source = context.sources[0]
    if (
        source.consumer_frame_id != contract.frame_id
        or source.consumer_contract_hash != canonical_sha256(contract)
    ):
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
            PlanReadiness.BLOCKED,
        )
        return None
    producer_plan = source.producer_assessment
    producer_key = (
        source.producer_contract.frame_id,
        canonical_sha256(source.producer_contract),
    )
    current_key = (contract.frame_id, canonical_sha256(contract))
    if (
        producer_key == current_key
        or producer_key in ancestors
        or any(
            ancestor_frame_id == producer_key[0]
            for ancestor_frame_id, _ in ancestors
        )
    ):
        state.add("PRIOR_RESULT_READINESS_CYCLE", PlanReadiness.BLOCKED)
        return None
    producer_has_prior = (
        source.producer_contract.scope.prior_result_binding is not None
    )
    if producer_has_prior != (
        source.producer_prior_result_context is not None
    ):
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
            PlanReadiness.BLOCKED,
        )
        return None
    if (
        producer_plan.dataset_version != context.dataset_version
        or producer_plan.dataset_pin != context.dataset_pin
        or producer_plan.binding_registry_version != context.binding_registry_version
        or producer_plan.binding_registry_hash != context.binding_registry_hash
        or producer_plan.policy_registry_version != context.policy_registry_version
        or producer_plan.policy_registry_hash != context.policy_registry_hash
        or producer_plan.contract_hash != canonical_sha256(source.producer_contract)
        or (
            source.producer_contract.scope.product_family_ids
            and source.product_family_ids
            != source.producer_contract.scope.product_family_ids
        )
    ):
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
            PlanReadiness.BLOCKED,
        )
        return None
    expected_producer_plan = assess_plan_readiness(
        source.producer_contract,
        bindings,
        policies,
        active_dataset_pin=active_dataset_pin,
        facts=facts,
        prior_result_context=source.producer_prior_result_context,
        _prior_result_depth=depth + 1,
        _prior_result_ancestors=ancestors | frozenset((current_key,)),
    )
    if "PRIOR_RESULT_READINESS_CYCLE" in expected_producer_plan.reason_codes:
        state.add("PRIOR_RESULT_READINESS_CYCLE", PlanReadiness.BLOCKED)
        return None
    if (
        "PRIOR_RESULT_READINESS_DEPTH_EXCEEDED"
        in expected_producer_plan.reason_codes
    ):
        state.add(
            "PRIOR_RESULT_READINESS_DEPTH_EXCEEDED",
            PlanReadiness.BLOCKED,
        )
        return None
    if producer_plan != expected_producer_plan:
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
            PlanReadiness.BLOCKED,
        )
        return None
    if producer_plan.readiness is not PlanReadiness.EXECUTABLE:
        state.add("PRIOR_RESULT_UPSTREAM_NOT_EXECUTABLE", PlanReadiness.BLOCKED)
        return None
    expected_families = source.producer_contract.scope.product_family_ids
    if not expected_families and source.producer_prior_result_context is not None:
        expected_families = (
            source.producer_prior_result_context.sources[0].product_family_ids
        )
    if source.product_family_ids != expected_families:
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
            PlanReadiness.BLOCKED,
        )
        return None
    physical = tuple(
        bindings.bindings_by_id.get(binding_id)
        for binding_id in producer_plan.binding_ids
    )
    if any(item is None for item in physical) or any(
        item.product_family_id not in source.product_family_ids
        for item in physical
        if item is not None
    ):
        state.add(
            "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH",
            PlanReadiness.BLOCKED,
        )
        return None
    return source


def _collect_predicate(
    predicate: PredicateNodeV2,
    fields: list[tuple[str, str, object | None]],
    policies: list[tuple[str, SemanticSqlPolicyKind, str]],
) -> None:
    if isinstance(predicate, PredicateAtomV2):
        fields.append((predicate.field_concept_id, "predicate", predicate))
        policies.append((predicate.null_policy_id, SemanticSqlPolicyKind.MISSINGNESS, "SQL_POLICY_NOT_REGISTERED"))
        return
    if isinstance(predicate, PredicateNotV2):
        _collect_predicate(predicate.child, fields, policies)
        return
    if isinstance(predicate, (PredicateAllOfV2, PredicateAnyOfV2)):
        for child in predicate.children:
            _collect_predicate(child, fields, policies)


def _assess_field(
    field_id: str,
    role: str,
    role_value: object | None,
    families: tuple[ProductFamily, ...],
    bindings: PhysicalBindingRegistry,
    state: _Assessment,
) -> list[PhysicalBindingDefinition]:
    matched: list[PhysicalBindingDefinition] = []
    concept_known = field_id in bindings.catalog_concept_ids
    for family in families:
        if concept_known and family.value not in bindings.catalog_families_by_concept[field_id]:
            state.add("SEMANTIC_FIELD_FAMILY_MISMATCH", PlanReadiness.BLOCKED)
            continue
        binding = bindings.binding_for(family, field_id)
        if binding is None:
            state.add(
                "SEMANTIC_CONCEPT_NOT_REGISTERED"
                if not concept_known
                else "PHYSICAL_BINDING_NOT_REGISTERED",
                PlanReadiness.EXPLORABLE,
            )
            continue
        state.binding_ids.add(binding.id)
        if binding.availability is PhysicalBindingAvailability.UNAVAILABLE:
            state.add(binding.unavailable_reason_code or "PHYSICAL_BINDING_UNAVAILABLE", PlanReadiness.LIMITED)
            continue
        matched.append(binding)
        if binding.unit_conversion_policy_id:
            state.unit_conversion_policy_ids.add(binding.unit_conversion_policy_id)
        if role == "predicate" and role_value is not None:
            if role_value.operator_id not in binding.supported_operator_ids:
                state.add("PHYSICAL_OPERATOR_UNSUPPORTED", PlanReadiness.LIMITED)
            literal_values = (
                (role_value.value,)
                if role_value.value is not None
                else role_value.values
            )
            for literal in literal_values:
                if literal.kind is not binding.semantic_value_kind:
                    state.add("PHYSICAL_VALUE_KIND_MISMATCH", PlanReadiness.BLOCKED)
                if (
                    literal.unit_id is not None
                    and literal.unit_id not in binding.accepted_semantic_unit_ids
                ):
                    state.add("SEMANTIC_UNIT_NOT_SUPPORTED", PlanReadiness.BLOCKED)
        if role == "aggregation" and role_value is not None:
            if role_value.function_id not in binding.supported_aggregate_ids:
                state.add("PHYSICAL_AGGREGATE_UNSUPPORTED", PlanReadiness.LIMITED)
    return matched


def _assess_policy(
    policy_id: str,
    expected_kind: SemanticSqlPolicyKind,
    missing_reason: str,
    families: tuple[ProductFamily, ...],
    policies: SemanticSqlPolicyRegistry,
    state: _Assessment,
) -> None:
    policy = policies.policies_by_id.get(policy_id)
    if policy is None:
        state.add(missing_reason, PlanReadiness.BLOCKED)
        return
    state.policy_ids.add(policy.id)
    if policy.kind is not expected_kind:
        state.add("SQL_POLICY_KIND_MISMATCH", PlanReadiness.BLOCKED)
    if policy.applicable_product_family_ids and not set(families) <= set(
        policy.applicable_product_family_ids
    ):
        state.add("SQL_POLICY_FAMILY_MISMATCH", PlanReadiness.BLOCKED)
    if not policy.verified:
        state.add(policy.unavailable_reason_code or "SQL_POLICY_UNVERIFIED", PlanReadiness.LIMITED)


def _assess_qualifiers(contract, bindings, state: _Assessment) -> None:
    qualifiers = contract.qualifiers
    requested = set()
    if qualifiers.period_id is not None:
        requested.add(SemanticQualifierId.PERIOD)
        if _PERIOD_QUALIFIER_PATTERN.fullmatch(qualifiers.period_id) is None:
            state.add("PERIOD_QUALIFIER_NOT_REGISTERED", PlanReadiness.BLOCKED)
    if qualifiers.currency_id is not None:
        requested.add(SemanticQualifierId.CURRENCY)
        if qualifiers.currency_id not in _KNOWN_CURRENCY_QUALIFIER_IDS:
            state.add("CURRENCY_QUALIFIER_NOT_REGISTERED", PlanReadiness.BLOCKED)
    if qualifiers.unit_id is not None:
        requested.add(SemanticQualifierId.UNIT)
        if qualifiers.unit_id not in _KNOWN_UNIT_QUALIFIER_IDS:
            state.add("UNIT_QUALIFIER_NOT_REGISTERED", PlanReadiness.BLOCKED)
    if qualifiers.as_of_date is not None:
        requested.add(SemanticQualifierId.AS_OF)
    if (
        contract.action_id is IntentType.AGGREGATE
        and is_population_count(contract.aggregation.function_id)
        and requested & {SemanticQualifierId.CURRENCY, SemanticQualifierId.UNIT}
    ):
        state.add("QUALIFIER_ACTION_UNSUPPORTED", PlanReadiness.BLOCKED)
    for binding in bindings:
        if not set(binding.required_qualifier_ids) <= requested:
            state.add("PHYSICAL_REQUIRED_QUALIFIER_MISSING", PlanReadiness.LIMITED)
        if not requested <= set(binding.supported_qualifier_ids):
            state.add("PHYSICAL_QUALIFIER_UNSUPPORTED", PlanReadiness.LIMITED)
        if qualifiers.unit_id is not None and (
            not binding.accepted_semantic_unit_ids
            or qualifiers.unit_id not in binding.accepted_semantic_unit_ids
        ):
            state.add("SEMANTIC_UNIT_NOT_SUPPORTED", PlanReadiness.BLOCKED)


def _assess_aggregate_grain(
    aggregation,
    families,
    bindings,
    binding_registry: PhysicalBindingRegistry,
    policies,
    facts: PhysicalReadinessFacts | None,
    state: _Assessment,
) -> None:
    grain_id = aggregation.population_grain_id
    dedup_id = aggregation.dedup_policy_id
    for binding in bindings:
        if binding.product_family_id is ProductFamily.PUBLIC_FUND:
            if (
                grain_id != "representative-product.v1"
                or dedup_id != "public-fund-representative-share.v1"
            ):
                state.add(
                    "PUBLIC_FUND_REPRESENTATIVE_POLICY_REQUIRED",
                    PlanReadiness.LIMITED,
                )
                continue
            proof_reasons = _public_fund_population_proof(binding, facts)
            for reason in proof_reasons:
                state.add(reason, PlanReadiness.LIMITED)
            continue
        if grain_id not in binding.verified_population_grain_ids:
            state.add(
                "PUBLIC_FUND_GRAIN_UNVERIFIED"
                if binding.product_family_id is ProductFamily.PUBLIC_FUND
                else "POPULATION_GRAIN_UNVERIFIED",
                PlanReadiness.LIMITED,
            )
    if (
        is_population_count(aggregation.function_id)
        and ProductFamily.PUBLIC_FUND in families
    ):
        if (
            grain_id != "representative-product.v1"
            or aggregation.count_population_id != "representative-product.v1"
            or dedup_id != "public-fund-representative-share.v1"
        ):
            state.add(
                "PUBLIC_FUND_REPRESENTATIVE_POLICY_REQUIRED",
                PlanReadiness.LIMITED,
            )
        else:
            public_aum = binding_registry.binding_for(ProductFamily.PUBLIC_FUND, "aum")
            if public_aum is None:
                state.add("PUBLIC_FUND_GRAIN_UNVERIFIED", PlanReadiness.LIMITED)
            else:
                for reason in _public_fund_population_proof(public_aum, facts):
                    state.add(reason, PlanReadiness.LIMITED)
    grain = policies.policies_by_id.get(grain_id)
    dedup = policies.policies_by_id.get(dedup_id)
    if grain is not None and dedup is not None:
        if dedup.population_grain_id and dedup.population_grain_id != grain.id:
            state.add("DEDUP_GRAIN_POLICY_MISMATCH", PlanReadiness.BLOCKED)


def _public_fund_population_proof(
    binding: PhysicalBindingDefinition,
    facts: PhysicalReadinessFacts | None,
) -> set[str]:
    if facts is None:
        return {"PUBLIC_FUND_GRAIN_UNVERIFIED"}
    manifest = facts.public_fund_manifest
    declared_manifest_hash = facts.public_fund_manifest_hash
    if manifest is None or declared_manifest_hash is None:
        return {"PUBLIC_FUND_GRAIN_UNVERIFIED"}
    reasons: set[str] = set()
    computed_manifest_hash = canonical_sha256(manifest)
    trusted_pin = TRUSTED_PUBLIC_FUND_MANIFEST_PINS.get(manifest.manifest_id)
    if (
        declared_manifest_hash != computed_manifest_hash
        or trusted_pin != (manifest.dataset_pin, computed_manifest_hash)
    ):
        reasons.add("PUBLIC_FUND_MANIFEST_UNTRUSTED")
    if (
        manifest.physical_policy_registry_version != POLICY_REGISTRY_VERSION
        or manifest.physical_policy_registry_hash != EXPECTED_POLICY_REGISTRY_HASH
        or manifest.population_grain_policy_id != "representative-product.v1"
        or manifest.dedup_policy_id != "public-fund-representative-share.v1"
    ):
        reasons.add("PUBLIC_FUND_MANIFEST_POLICY_MISMATCH")
    shares = set(manifest.authoritative_share_class_ids)
    edges = manifest.representative_share_edges
    if not shares:
        reasons.add("PUBLIC_FUND_REPRESENTATIVE_FACTS_MISSING")
    sources = {item.source_id: item for item in manifest.source_records}
    evidence = {item.evidence_id: item for item in manifest.evidence_records}
    if any(item.dataset_pin != manifest.dataset_pin for item in sources.values()):
        reasons.add("PUBLIC_FUND_DATASET_PIN_MISMATCH")
    for item in evidence.values():
        source = sources.get(item.source_id)
        if (
            item.dataset_pin != manifest.dataset_pin
            or source is None
            or source.dataset_pin != manifest.dataset_pin
        ):
            reasons.add("PUBLIC_FUND_EVIDENCE_PATH_UNVERIFIED")
    incoming: dict[str, set[str]] = {share_id: set() for share_id in shares}
    graph: dict[str, set[str]] = {}
    for edge in edges:
        if edge.predicate_id != "hasShareClass":
            reasons.add("PUBLIC_FUND_REPRESENTATIVE_RELATION_UNVERIFIED")
        if edge.dataset_pin != manifest.dataset_pin:
            reasons.add("PUBLIC_FUND_DATASET_PIN_MISMATCH")
        evidence_record = evidence.get(edge.evidence_id)
        source_record = sources.get(edge.source_id)
        if (
            edge.dataset_pin != manifest.dataset_pin
            or evidence_record is None
            or source_record is None
            or evidence_record.source_id != edge.source_id
            or evidence_record.dataset_pin != manifest.dataset_pin
            or source_record.dataset_pin != manifest.dataset_pin
        ):
            reasons.add("PUBLIC_FUND_EVIDENCE_PATH_UNVERIFIED")
        incoming.setdefault(edge.share_class_id, set()).add(edge.representative_id)
        graph.setdefault(edge.representative_id, set()).add(edge.share_class_id)
    if set(incoming) != shares or any(len(items) != 1 for items in incoming.values()):
        reasons.add("PUBLIC_FUND_REPRESENTATIVE_COVERAGE_INCOMPLETE")
    if any(len(items) > 1 for items in incoming.values()):
        reasons.add("PUBLIC_FUND_REPRESENTATIVE_AMBIGUOUS")
    if _has_cycle(graph):
        reasons.add("PUBLIC_FUND_REPRESENTATIVE_CYCLE")
    representatives = {edge.representative_id for edge in edges}
    ownerships = [
        item for item in manifest.population_metric_ownerships
        if item.metric_id in binding.approved_metric_ids
    ]
    by_representative: dict[str, list[PopulationMetricOwnership]] = {
        item: [] for item in representatives
    }
    for ownership in ownerships:
        by_representative.setdefault(ownership.representative_id, []).append(ownership)
        if ownership.dataset_pin != manifest.dataset_pin:
            reasons.add("PUBLIC_FUND_DATASET_PIN_MISMATCH")
        evidence_record = evidence.get(ownership.evidence_id)
        source_record = sources.get(ownership.source_id)
        if (
            ownership.dataset_pin != manifest.dataset_pin
            or evidence_record is None
            or source_record is None
            or evidence_record.source_id != ownership.source_id
            or evidence_record.dataset_pin != manifest.dataset_pin
            or source_record.dataset_pin != manifest.dataset_pin
        ):
            reasons.add("PUBLIC_FUND_EVIDENCE_PATH_UNVERIFIED")
    if set(by_representative) != representatives:
        reasons.add("PUBLIC_FUND_AUM_OWNERSHIP_UNVERIFIED")
    if len({item.observation_id for item in ownerships}) != len(ownerships):
        reasons.add("PUBLIC_FUND_AUM_OWNERSHIP_UNVERIFIED")
    for representative_id in representatives:
        owned = by_representative.get(representative_id, [])
        if len(owned) != 1 or owned[0].owner_entity_id != representative_id:
            reasons.add("PUBLIC_FUND_AUM_OWNERSHIP_UNVERIFIED")
    if not representatives:
        reasons.add("PUBLIC_FUND_AUM_OWNERSHIP_UNVERIFIED")
    return reasons


def _has_cycle(graph: dict[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for child in graph.get(node, set()):
            if visit(child):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _assess_currency_normalization(contract, bindings, state: _Assessment) -> None:
    if contract.action_id not in {
        IntentType.RANK,
        IntentType.AGGREGATE,
        IntentType.COMPARE,
    }:
        return
    aum_bindings = [
        binding for binding in bindings if binding.semantic_concept_id == "aum"
    ]
    cross_family = len(set(contract.scope.product_family_ids)) > 1
    if (
        cross_family
        or any(binding.currency_normalization_required for binding in aum_bindings)
        or len({binding.product_family_id for binding in aum_bindings}) > 1
    ):
        state.add("CURRENCY_NORMALIZATION_POLICY_REQUIRED", PlanReadiness.LIMITED)


def _severity(readiness: PlanReadiness) -> int:
    return {
        PlanReadiness.EXECUTABLE: 0,
        PlanReadiness.EXPLORABLE: 1,
        PlanReadiness.LIMITED: 2,
        PlanReadiness.BLOCKED: 3,
    }[readiness]
