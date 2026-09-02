from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from financial_agent.intent.query_contracts import (
    PlanReadiness,
    SolvedQueryContractCandidateV2,
)
from financial_agent.planning.physical_bindings import (
    load_physical_binding_registry,
    load_semantic_sql_policy_registry,
)
from financial_agent.planning.readiness import assess_plan_readiness


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATE_ADAPTER = TypeAdapter(SolvedQueryContractCandidateV2)


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
            "contract_registry_version": "query-contract-registry.v2",
            "contract_registry_hash": "a" * 64,
            "operator_registry_version": "query-operator-registry.v1",
            "operator_registry_hash": "b" * 64,
            "policy_registry_version": "query-policy-registry.v1",
            "policy_registry_hash": "c" * 64,
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


def _verified_synthetic_registries(tmp_path: Path):
    bindings_payload = json.loads(
        (PROJECT_ROOT / "config/planning/semantic-sql-bindings.v1.json").read_text()
    )
    for binding in bindings_payload["bindings"]:
        if binding["product_family_id"] == "public_fund" and binding["semantic_concept_id"] == "aum":
            binding["verified_population_grain_ids"] = [
                "source-product.v1",
                "representative-product.v1",
            ]
    binding_path = tmp_path / "bindings.json"
    binding_path.write_text(json.dumps(bindings_payload), encoding="utf-8")

    policies_payload = json.loads(
        (PROJECT_ROOT / "config/planning/semantic-sql-policies.v1.json").read_text()
    )
    for policy in policies_payload["policies"]:
        if policy["id"] in {
            "representative-product.v1",
            "public-fund-representative-share.v1",
        }:
            policy["verified"] = True
            policy["unavailable_reason_code"] = None
    policy_path = tmp_path / "policies.json"
    policy_path.write_text(json.dumps(policies_payload), encoding="utf-8")
    return (
        load_physical_binding_registry(PROJECT_ROOT, registry_path=binding_path),
        load_semantic_sql_policy_registry(PROJECT_ROOT, registry_path=policy_path),
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
    tmp_path: Path,
) -> None:
    bindings, policies = _verified_synthetic_registries(tmp_path)

    result = assess_plan_readiness(_public_fund_aum_sum(), bindings, policies)

    assert result.readiness is PlanReadiness.EXECUTABLE
    assert result.reason_codes == ()
    assert result.binding_ids == ("public-fund-aum.v1",)
    assert {
        "representative-product.v1",
        "public-fund-representative-share.v1",
    } <= set(result.policy_ids)


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

    assert result.readiness is PlanReadiness.EXECUTABLE
    assert "cosine-complete-dimensions.v1" in result.policy_ids


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
