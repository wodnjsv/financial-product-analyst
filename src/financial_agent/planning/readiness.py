"""Independent physical executability assessment for solved semantic contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pydantic import ConfigDict

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.query_contracts import (
    AggregationFunction,
    PlanReadiness,
    PredicateAllOfV2,
    PredicateAnyOfV2,
    PredicateAtomV2,
    PredicateNodeV2,
    PredicateNotV2,
    SolvedQueryContractCandidateV2,
    SemanticValueKind,
)

from .physical_bindings import (
    PhysicalBindingAvailability,
    PhysicalBindingDefinition,
    PhysicalBindingRegistry,
    PhysicalReadinessFacts,
    PopulationMetricOwnership,
    SemanticQualifierId,
    SemanticSqlPolicyKind,
    SemanticSqlPolicyRegistry,
)


class PlanReadinessResult(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    frame_id: Identifier
    contract_hash: Sha256Hex
    binding_registry_version: Identifier
    binding_registry_hash: Sha256Hex
    policy_registry_version: Identifier
    policy_registry_hash: Sha256Hex
    readiness: PlanReadiness
    reason_codes: tuple[Identifier, ...]
    binding_ids: tuple[Identifier, ...]
    policy_ids: tuple[Identifier, ...]
    unit_conversion_policy_ids: tuple[Identifier, ...]


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
    facts: PhysicalReadinessFacts | None = None,
) -> PlanReadinessResult:
    """Assess all semantic roles without changing the solved contract."""

    state = _Assessment()
    if contract.registry_pins != bindings.semantic_registry_pins:
        state.add("SEMANTIC_REGISTRY_PIN_MISMATCH", PlanReadiness.BLOCKED)
    if (
        bindings.physical_policy_registry_version != policies.registry_version
        or bindings.physical_policy_registry_hash != policies.registry_hash
    ):
        state.add("PHYSICAL_POLICY_REGISTRY_PIN_MISMATCH", PlanReadiness.BLOCKED)
    families = tuple(contract.scope.product_family_ids)
    if not families:
        state.add("PHYSICAL_SCOPE_FAMILY_REQUIRED", PlanReadiness.BLOCKED)
    known_entity_ids = facts.known_entity_ids if facts is not None else frozenset()
    if set(contract.scope.entity_refs) - known_entity_ids:
        state.add("ENTITY_IDENTITY_UNVERIFIED", PlanReadiness.LIMITED)
    if contract.scope.prior_result_binding and (
        facts is None
        or contract.scope.prior_result_binding
        not in facts.known_prior_result_binding_ids
    ):
        state.add("PRIOR_RESULT_BINDING_UNVERIFIED", PlanReadiness.LIMITED)

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
        if aggregation.function_id is AggregationFunction.COUNT:
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
    _assess_qualifiers(contract.qualifiers, resolved_bindings, state)
    if contract.action_id is IntentType.AGGREGATE:
        _assess_aggregate_grain(
            contract.aggregation, resolved_bindings, policies, facts, state
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


def _assess_qualifiers(qualifiers, bindings, state: _Assessment) -> None:
    requested = set()
    if qualifiers.period_id is not None:
        requested.add(SemanticQualifierId.PERIOD)
    if qualifiers.currency_id is not None:
        requested.add(SemanticQualifierId.CURRENCY)
    if qualifiers.unit_id is not None:
        requested.add(SemanticQualifierId.UNIT)
    if qualifiers.as_of_date is not None:
        requested.add(SemanticQualifierId.AS_OF)
    for binding in bindings:
        if not set(binding.required_qualifier_ids) <= requested:
            state.add("PHYSICAL_REQUIRED_QUALIFIER_MISSING", PlanReadiness.LIMITED)
        if not requested <= set(binding.supported_qualifier_ids):
            state.add("PHYSICAL_QUALIFIER_UNSUPPORTED", PlanReadiness.LIMITED)


def _assess_aggregate_grain(
    aggregation, bindings, policies, facts: PhysicalReadinessFacts | None,
    state: _Assessment
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
    reasons: set[str] = set()
    shares = set(facts.public_fund_share_class_ids)
    edges = facts.representative_share_edges
    if not shares:
        reasons.add("PUBLIC_FUND_REPRESENTATIVE_FACTS_MISSING")
    incoming: dict[str, set[str]] = {share_id: set() for share_id in shares}
    graph: dict[str, set[str]] = {}
    for edge in edges:
        if edge.predicate_id != "hasShareClass":
            reasons.add("PUBLIC_FUND_REPRESENTATIVE_RELATION_UNVERIFIED")
        if (
            edge.relation_id not in facts.verified_relation_ids
            or edge.evidence_id not in facts.verified_evidence_ids
            or edge.source_id not in facts.verified_source_ids
        ):
            reasons.add("PUBLIC_FUND_EVIDENCE_PATH_UNVERIFIED")
        incoming.setdefault(edge.share_class_id, set()).add(edge.representative_id)
        graph.setdefault(edge.representative_id, set()).add(edge.share_class_id)
    if set(incoming) != shares or any(len(items) != 1 for items in incoming.values()):
        reasons.add("PUBLIC_FUND_REPRESENTATIVE_COVERAGE_INCOMPLETE")
    if facts.ambiguous_share_class_ids or any(len(items) > 1 for items in incoming.values()):
        reasons.add("PUBLIC_FUND_REPRESENTATIVE_AMBIGUOUS")
    if _has_cycle(graph):
        reasons.add("PUBLIC_FUND_REPRESENTATIVE_CYCLE")
    representatives = {edge.representative_id for edge in edges}
    if not (shares | representatives) <= set(facts.known_entity_ids):
        reasons.add("PUBLIC_FUND_REPRESENTATIVE_FACTS_MISSING")
    ownerships = [
        item for item in facts.population_metric_ownerships
        if item.metric_id in binding.approved_metric_ids
    ]
    by_representative: dict[str, list[PopulationMetricOwnership]] = {
        item: [] for item in representatives
    }
    for ownership in ownerships:
        by_representative.setdefault(ownership.representative_id, []).append(ownership)
        if (
            ownership.observation_id not in facts.verified_observation_ids
            or ownership.evidence_id not in facts.verified_evidence_ids
            or ownership.source_id not in facts.verified_source_ids
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
    if contract.action_id not in {IntentType.RANK, IntentType.AGGREGATE}:
        return
    aum_bindings = [
        binding for binding in bindings if binding.semantic_concept_id == "aum"
    ]
    if any(binding.currency_normalization_required for binding in aum_bindings) or len(
        {binding.product_family_id for binding in aum_bindings}
    ) > 1:
        state.add("CURRENCY_NORMALIZATION_POLICY_REQUIRED", PlanReadiness.LIMITED)


def _severity(readiness: PlanReadiness) -> int:
    return {
        PlanReadiness.EXECUTABLE: 0,
        PlanReadiness.EXPLORABLE: 1,
        PlanReadiness.LIMITED: 2,
        PlanReadiness.BLOCKED: 3,
    }[readiness]
