from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from financial_agent.intent.query_contracts import (
    PlanReadiness,
    SolvedQueryContractCandidateV2,
)
from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.planning.physical_bindings import (
    PhysicalReadinessFacts,
    PopulationMetricOwnership,
    RepresentativeShareEdge,
    load_physical_binding_registry,
    load_semantic_sql_policy_registry,
)
from financial_agent.planning.readiness import assess_plan_readiness


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATE_ADAPTER = TypeAdapter(SolvedQueryContractCandidateV2)
_SEMANTIC_REGISTRY = load_query_contract_registry(PROJECT_ROOT)


def _validate(payload: dict[str, object]):
    return _CANDIDATE_ADAPTER.validate_json(json.dumps(payload))


def _common(action: str, family: str = "public_fund") -> dict[str, object]:
    return {
        "contract_schema_version": "2.0",
        "contract_variant_id": {
            "screen": "screen.predicate.v2",
            "aggregate": "aggregate.scalar.v2",
            "lookup": "lookup.projection.v2",
            "rank": "rank.ordering.v2",
            "compare": "compare.subjects.v2",
            "calculate": "calculate.recipe.v2",
            "similar": "similar.policy.v2",
            "explain": "explain.topic.v2",
        }[action],
        "frame_id": "frame-1",
        "action_id": action,
        "scope": {"product_family_ids": [family], "entity_refs": [], "prior_result_binding": None},
        "qualifiers": {"period_id": None, "currency_id": None, "unit_id": None, "as_of_date": None},
        "result_shape": {
            "screen": "product_list",
            "aggregate": "single_value",
            "lookup": "product_list",
            "rank": "top_k",
            "compare": "comparison_table",
            "calculate": "single_value",
            "similar": "product_list",
            "explain": "explanation",
        }[action],
        "provenance": [{"semantic_input_id": "input-1", "source_kind": "exact_lock", "source_ref": "span-1"}],
        "registry_pins": {
            "contract_registry_version": _SEMANTIC_REGISTRY.contract_registry_version,
            "contract_registry_hash": _SEMANTIC_REGISTRY.contract_registry_hash,
            "operator_registry_version": _SEMANTIC_REGISTRY.operator_registry_version,
            "operator_registry_hash": _SEMANTIC_REGISTRY.operator_registry_hash,
            "policy_registry_version": _SEMANTIC_REGISTRY.policy_registry_version,
            "policy_registry_hash": _SEMANTIC_REGISTRY.policy_registry_hash,
        },
    }


def _screen(field: str = "fee_rate", family: str = "public_fund"):
    payload = _common("screen", family)
    payload["predicate"] = {
        "node_type": "atom",
        "field_concept_id": field,
        "operator_id": "lte",
        "value": {"kind": "decimal", "decimal": "1", "unit_id": "percent"},
        "values": [],
        "null_policy_id": "exclude_missing.v1",
    }
    return _validate(payload)


def _public_fund_aum_sum():
    payload = _common("aggregate")
    payload["qualifiers"] = {
        "period_id": None,
        "currency_id": None,
        "unit_id": None,
        "as_of_date": "2026-08-24",
    }
    payload["aggregation"] = {
        "function_id": "sum",
        "target_field_concept_id": "aum",
        "count_population_id": None,
        "group_by_field_concept_ids": [],
        "bucket_policy_id": None,
        "population_grain_id": "representative-product.v1",
        "dedup_policy_id": "public-fund-representative-share.v1",
    }
    payload["predicate"] = None
    return _validate(payload)


def _verified_population_facts() -> PhysicalReadinessFacts:
    return PhysicalReadinessFacts(
        known_entity_ids=frozenset({"representative-a", "share-a", "share-b"}),
        verified_relation_ids=frozenset({"relation-a", "relation-b"}),
        verified_observation_ids=frozenset({"observation-a"}),
        verified_evidence_ids=frozenset({
            "evidence-a", "evidence-b", "evidence-observation-a"
        }),
        verified_source_ids=frozenset({
            "source-a", "source-b", "source-observation-a"
        }),
        public_fund_share_class_ids=frozenset({"share-a", "share-b"}),
        representative_share_edges=(
            RepresentativeShareEdge(
                representative_id="representative-a",
                share_class_id="share-a",
                predicate_id="hasShareClass",
                relation_id="relation-a",
                evidence_id="evidence-a",
                source_id="source-a",
            ),
            RepresentativeShareEdge(
                representative_id="representative-a",
                share_class_id="share-b",
                predicate_id="hasShareClass",
                relation_id="relation-b",
                evidence_id="evidence-b",
                source_id="source-b",
            ),
        ),
        ambiguous_share_class_ids=frozenset(),
        population_metric_ownerships=(
            PopulationMetricOwnership(
                representative_id="representative-a",
                metric_id="organizer.prfd01n001.net_assets",
                owner_entity_id="representative-a",
                observation_id="observation-a",
                evidence_id="evidence-observation-a",
                source_id="source-observation-a",
            ),
        ),
    )


def test_public_fund_aum_sum_is_limited_when_real_grain_is_unverified() -> None:
    contract = _public_fund_aum_sum()
    before = contract.model_dump_json()

    result = assess_plan_readiness(
        contract,
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == ("PUBLIC_FUND_GRAIN_UNVERIFIED",)
    assert contract.model_dump_json() == before


def test_synthetic_verified_representative_population_is_executable(
) -> None:
    result = assess_plan_readiness(
        _public_fund_aum_sum(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=_verified_population_facts(),
    )

    assert result.readiness is PlanReadiness.EXECUTABLE
    assert result.reason_codes == ()
    assert result.binding_ids == ("public-fund-aum.v1",)
    assert {
        "representative-product.v1",
        "public-fund-representative-share.v1",
    } <= set(result.policy_ids)


def test_public_fund_source_grain_sum_never_executes() -> None:
    payload = json.loads(_public_fund_aum_sum().model_dump_json())
    payload["aggregation"]["population_grain_id"] = "source-product.v1"
    payload["aggregation"]["dedup_policy_id"] = "no-dedup.v1"

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=_verified_population_facts(),
    )

    assert result.readiness is not PlanReadiness.EXECUTABLE
    assert "PUBLIC_FUND_REPRESENTATIVE_POLICY_REQUIRED" in result.reason_codes


def test_public_fund_aum_rank_never_uses_share_class_rows_as_products() -> None:
    payload = _common("rank", "public_fund")
    payload["qualifiers"]["as_of_date"] = "2026-08-24"
    payload["ordering"] = [{
        "field_concept_id": "aum",
        "direction": "desc",
        "direction_policy_id": None,
        "nulls_policy_id": "exclude_missing.v1",
        "tie_break_policy_id": "stable-product-id.v1",
    }]
    payload["limit"] = 5
    payload["limit_policy_id"] = None
    payload["predicate"] = None

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=_verified_population_facts(),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_GRAIN_UNVERIFIED" in result.reason_codes


def test_representative_proof_is_computed_not_declared() -> None:
    facts = _verified_population_facts().model_copy(
        update={"representative_share_edges": ()}
    )

    result = assess_plan_readiness(
        _public_fund_aum_sum(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=facts,
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_REPRESENTATIVE_COVERAGE_INCOMPLETE" in result.reason_codes


def test_representative_proof_rejects_ambiguity_cycles_and_multiple_aum_owners() -> None:
    base = _verified_population_facts()
    facts = base.model_copy(
        update={
            "known_entity_ids": frozenset(
                {"representative-a", "representative-b", "share-a", "share-b"}
            ),
            "verified_relation_ids": frozenset({
                "relation-a", "relation-b", "relation-c", "relation-cycle"
            }),
            "verified_observation_ids": frozenset({"observation-a", "observation-b"}),
            "verified_evidence_ids": frozenset({
                "evidence-a", "evidence-b", "evidence-c", "evidence-cycle",
                "evidence-observation-a", "evidence-observation-b",
            }),
            "verified_source_ids": frozenset({
                "source-a", "source-b", "source-c", "source-cycle",
                "source-observation-a", "source-observation-b",
            }),
            "representative_share_edges": base.representative_share_edges + (
                RepresentativeShareEdge(
                    representative_id="representative-b",
                    share_class_id="share-a",
                    predicate_id="hasShareClass",
                    relation_id="relation-c",
                    evidence_id="evidence-c",
                    source_id="source-c",
                ),
                RepresentativeShareEdge(
                    representative_id="share-a",
                    share_class_id="representative-a",
                    predicate_id="hasShareClass",
                    relation_id="relation-cycle",
                    evidence_id="evidence-cycle",
                    source_id="source-cycle",
                ),
            ),
            "population_metric_ownerships": base.population_metric_ownerships + (
                PopulationMetricOwnership(
                    representative_id="representative-a",
                    metric_id="organizer.prfd01n001.net_assets",
                    owner_entity_id="representative-a",
                    observation_id="observation-b",
                    evidence_id="evidence-observation-b",
                    source_id="source-observation-b",
                ),
            ),
        }
    )

    result = assess_plan_readiness(
        _public_fund_aum_sum(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=facts,
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert {
        "PUBLIC_FUND_REPRESENTATIVE_AMBIGUOUS",
        "PUBLIC_FUND_REPRESENTATIVE_CYCLE",
        "PUBLIC_FUND_AUM_OWNERSHIP_UNVERIFIED",
    } <= set(result.reason_codes)


def test_public_fund_total_fee_is_semantically_complete_but_physically_limited() -> None:
    result = assess_plan_readiness(
        _screen(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == ("PHYSICAL_DEFINITION_UNVERIFIED",)
    assert "public-fund-fee-rate.v1" in result.binding_ids


def test_unknown_esg_field_is_explorable_not_fabricated() -> None:
    result = assess_plan_readiness(
        _screen("esg_rating", "domestic_etf"),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.EXPLORABLE
    assert result.reason_codes == ("SEMANTIC_CONCEPT_NOT_REGISTERED",)
    assert result.binding_ids == ()


def test_known_field_outside_scope_family_is_blocked() -> None:
    result = assess_plan_readiness(
        _screen("maturity_date", "domestic_etf"),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert result.reason_codes == ("SEMANTIC_FIELD_FAMILY_MISMATCH",)


def test_percent_conversion_comes_from_physical_binding() -> None:
    result = assess_plan_readiness(
        _screen("fee_rate", "domestic_etf"),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.EXECUTABLE
    assert result.unit_conversion_policy_ids == (
        "semantic-percent-to-percentage-point.v1",
    )


def test_fee_rate_rejects_integer_and_non_percent_units() -> None:
    payload = json.loads(_screen("fee_rate", "domestic_etf").model_dump_json())
    payload["predicate"]["value"] = {
        "kind": "integer",
        "integer": 1,
        "unit_id": "won",
    }

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert {
        "PHYSICAL_VALUE_KIND_MISMATCH",
        "SEMANTIC_UNIT_NOT_SUPPORTED",
    } <= set(result.reason_codes)


def test_overseas_aum_rank_without_currency_normalization_is_limited() -> None:
    payload = _common("rank", "overseas_etf")
    payload["qualifiers"]["as_of_date"] = "2026-08-24"
    payload["ordering"] = [{
        "field_concept_id": "aum",
        "direction": "desc",
        "direction_policy_id": None,
        "nulls_policy_id": "exclude_missing.v1",
        "tie_break_policy_id": "stable-product-id.v1",
    }]
    payload["limit"] = 5
    payload["limit_policy_id"] = None
    payload["predicate"] = None

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "CURRENCY_NORMALIZATION_POLICY_REQUIRED" in result.reason_codes


def test_mixed_family_aum_rank_without_normalization_is_limited() -> None:
    payload = _common("rank", "domestic_etf")
    payload["scope"]["product_family_ids"] = ["domestic_etf", "public_fund"]
    payload["qualifiers"]["as_of_date"] = "2026-08-24"
    payload["ordering"] = [{
        "field_concept_id": "aum",
        "direction": "desc",
        "direction_policy_id": None,
        "nulls_policy_id": "exclude_missing.v1",
        "tie_break_policy_id": "stable-product-id.v1",
    }]
    payload["limit"] = 5
    payload["limit_policy_id"] = None
    payload["predicate"] = None

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "CURRENCY_NORMALIZATION_POLICY_REQUIRED" in result.reason_codes


def test_required_as_of_qualifier_is_independently_enforced() -> None:
    payload = _common("lookup", "domestic_etf")
    payload["projections"] = {
        "field_concept_ids": ["aum"],
        "default_profile_id": None,
    }
    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == ("PHYSICAL_REQUIRED_QUALIFIER_MISSING",)


def test_comparison_checks_metrics_and_basis_policy() -> None:
    payload = _common("compare", "domestic_etf")
    payload["comparison"] = {
        "subject_refs": ["entity-a", "entity-b"],
        "group_basis_id": None,
        "metric_concept_ids": ["fee_rate"],
        "projection_profile_id": None,
        "basis_policy_id": "same-definition-period-unit.v1",
        "normalization_policy_id": None,
    }

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=PhysicalReadinessFacts(
            known_entity_ids=frozenset({"entity-a", "entity-b"})
        ),
    )

    assert result.readiness is PlanReadiness.EXECUTABLE
    assert result.binding_ids == ("domestic-etf-fee-rate.v1",)
    assert "same-definition-period-unit.v1" in result.policy_ids


def test_calculation_requires_a_registered_recipe() -> None:
    payload = _common("calculate", "domestic_etf")
    payload["calculation"] = {
        "recipe_id": "unregistered-recipe.v1",
        "operands": [
            {"role_id": "metric", "value_ref": None, "field_concept_id": "fee_rate"}
        ],
    }

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert result.reason_codes == ("RECIPE_NOT_REGISTERED",)


def test_calculation_value_reference_is_independently_verified() -> None:
    payload = _common("calculate", "domestic_etf")
    payload["calculation"] = {
        "recipe_id": "unregistered-recipe.v1",
        "operands": [
            {"role_id": "amount", "value_ref": "unknown-value", "field_concept_id": None}
        ],
    }

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert result.reason_codes == (
        "CALCULATION_VALUE_REF_UNVERIFIED",
        "RECIPE_NOT_REGISTERED",
    )


def test_similarity_checks_dimension_binding_and_similarity_policy() -> None:
    payload = _common("similar", "domestic_etf")
    payload["similarity"] = {
        "anchor_ref": "entity-a",
        "policy_id": "cosine-complete-dimensions.v1",
        "dimension_concept_ids": ["fee_rate"],
        "default_profile_id": None,
        "coverage_threshold": "0.6",
        "limit": 5,
    }

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "SIMILARITY_EXECUTOR_OUT_OF_SCOPE" in result.reason_codes
    assert "ENTITY_IDENTITY_UNVERIFIED" in result.reason_codes
    assert "cosine-complete-dimensions.v1" in result.policy_ids


def test_unknown_count_population_and_comparison_subjects_fail_closed() -> None:
    payload = _common("aggregate", "domestic_etf")
    payload["aggregation"] = {
        "function_id": "count",
        "target_field_concept_id": None,
        "count_population_id": "invented-population.v1",
        "group_by_field_concept_ids": [],
        "bucket_policy_id": None,
        "population_grain_id": "source-product.v1",
        "dedup_policy_id": "no-dedup.v1",
    }
    payload["predicate"] = None
    count_result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )
    assert "COUNT_POPULATION_MISMATCH" in count_result.reason_codes

    compare = _common("compare", "domestic_etf")
    compare["comparison"] = {
        "subject_refs": ["unknown-a", "unknown-b"],
        "group_basis_id": None,
        "metric_concept_ids": ["fee_rate"],
        "projection_profile_id": None,
        "basis_policy_id": "same-definition-period-unit.v1",
        "normalization_policy_id": None,
    }
    compare_result = assess_plan_readiness(
        _validate(compare),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )
    assert compare_result.readiness is PlanReadiness.LIMITED
    assert compare_result.reason_codes == ("ENTITY_IDENTITY_UNVERIFIED",)


def test_scope_entity_and_prior_result_binding_fail_closed() -> None:
    payload = _common("lookup", "domestic_etf")
    payload["scope"]["entity_refs"] = ["unknown-entity"]
    payload["scope"]["prior_result_binding"] = "unknown-result"
    payload["projections"] = {
        "field_concept_ids": ["fee_rate"],
        "default_profile_id": None,
    }

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == (
        "ENTITY_IDENTITY_UNVERIFIED",
        "PRIOR_RESULT_BINDING_UNVERIFIED",
    )


def test_unknown_comparison_group_basis_fails_closed() -> None:
    payload = _common("compare", "domestic_etf")
    payload["comparison"] = {
        "subject_refs": [],
        "group_basis_id": "invented-group-basis",
        "metric_concept_ids": ["fee_rate"],
        "projection_profile_id": None,
        "basis_policy_id": "same-definition-period-unit.v1",
        "normalization_policy_id": None,
    }

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == ("COMPARISON_GROUP_BASIS_UNVERIFIED",)


def test_semantic_registry_pin_mismatch_is_blocked() -> None:
    payload = json.loads(_screen("fee_rate", "domestic_etf").model_dump_json())
    payload["registry_pins"]["operator_registry_hash"] = "f" * 64

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert "SEMANTIC_REGISTRY_PIN_MISMATCH" in result.reason_codes


def test_explanation_topic_without_physical_source_is_explorable() -> None:
    payload = _common("explain", "domestic_etf")
    payload["explanation"] = {"topic_concept_id": "risk_factor", "profile_id": None}

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.EXPLORABLE
    assert result.reason_codes == ("PHYSICAL_BINDING_NOT_REGISTERED",)


def test_explanation_profile_must_be_expanded_before_execution() -> None:
    payload = _common("explain", "domestic_etf")
    payload["explanation"] = {
        "topic_concept_id": None,
        "profile_id": "default-product-projection.v1",
    }

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert result.reason_codes == ("EXPLANATION_PROFILE_NOT_EXPANDED",)


def test_grouping_and_aggregate_operator_are_both_checked() -> None:
    payload = _common("aggregate", "domestic_etf")
    payload["contract_variant_id"] = "aggregate.grouped.v2"
    payload["result_shape"] = "grouped_table"
    payload["qualifiers"] = {
        "period_id": None,
        "currency_id": None,
        "unit_id": None,
        "as_of_date": "2026-08-24",
    }
    payload["aggregation"] = {
        "function_id": "sum",
        "target_field_concept_id": "fee_rate",
        "count_population_id": None,
        "group_by_field_concept_ids": ["product_risk_grade"],
        "bucket_policy_id": None,
        "population_grain_id": "source-product.v1",
        "dedup_policy_id": "no-dedup.v1",
    }
    payload["predicate"] = None

    result = assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == (
        "PHYSICAL_AGGREGATE_UNSUPPORTED",
        "PHYSICAL_BINDING_NOT_REGISTERED",
        "PHYSICAL_QUALIFIER_UNSUPPORTED",
    )


def test_readiness_returns_all_stable_reasons_across_roles() -> None:
    payload = _common("rank", "public_fund")
    payload["ordering"] = [
        {
            "field_concept_id": "fee_rate",
            "direction": "asc",
            "direction_policy_id": None,
            "nulls_policy_id": "exclude_missing.v1",
            "tie_break_policy_id": "missing-tie-policy.v1",
        }
    ]
    payload["limit"] = 5
    payload["limit_policy_id"] = None
    payload["predicate"] = {
        "node_type": "atom",
        "field_concept_id": "esg_rating",
        "operator_id": "lte",
        "value": {"kind": "decimal", "decimal": "1", "unit_id": None},
        "values": [],
        "null_policy_id": "missing-null-policy.v1",
    }
    contract = _validate(payload)

    result = assess_plan_readiness(
        contract,
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert result.reason_codes == tuple(sorted({
        "PHYSICAL_DEFINITION_UNVERIFIED",
        "SEMANTIC_CONCEPT_NOT_REGISTERED",
        "SQL_POLICY_NOT_REGISTERED",
    }))
