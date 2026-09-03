from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import ProductFamily
from financial_agent.intent.query_contracts import (
    PlanReadiness,
    SolvedQueryContractCandidateV2,
)
from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.intent.view import ActiveDatasetPin
from financial_agent.planning.physical_bindings import (
    DatasetEvidenceRecord,
    DatasetSourceRecord,
    PhysicalReadinessFacts,
    PopulationMetricOwnership,
    PublicFundDatasetManifest,
    RepresentativeShareEdge,
    load_physical_binding_registry,
    load_semantic_sql_policy_registry,
)
from financial_agent.planning.readiness import (
    PlanReadinessResult,
    PriorResultReadinessContext,
    PriorResultReadinessSource,
    assess_plan_readiness,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATE_ADAPTER = TypeAdapter(SolvedQueryContractCandidateV2)
_SEMANTIC_REGISTRY = load_query_contract_registry(PROJECT_ROOT)
_DATASET_PIN = "43138033043db74566a74023c18b83e01b9637c1041ae737758aef55aaa9b36f"
_ACTIVE_DATASET_PIN = ActiveDatasetPin(
    dataset_version="synthetic-dataset-v1",
    manifest_hash=_DATASET_PIN,
)


def _assess_plan_readiness(
    contract,
    bindings,
    policies,
    *,
    facts=None,
    active_dataset_pin=_ACTIVE_DATASET_PIN,
):
    return assess_plan_readiness(
        contract,
        bindings,
        policies,
        facts=facts,
        active_dataset_pin=active_dataset_pin,
    )


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
    if field == "fee_rate":
        payload["qualifiers"]["unit_id"] = "percent"
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


def _public_fund_representative_count():
    payload = _common("aggregate")
    payload["aggregation"] = {
        "function_id": "count",
        "target_field_concept_id": None,
        "count_population_id": "representative-product.v1",
        "group_by_field_concept_ids": [],
        "bucket_policy_id": None,
        "population_grain_id": "representative-product.v1",
        "dedup_policy_id": "public-fund-representative-share.v1",
    }
    payload["predicate"] = None
    return _validate(payload)


def _verified_population_manifest() -> PublicFundDatasetManifest:
    return PublicFundDatasetManifest(
        manifest_id="synthetic-public-fund-complete.v1",
        dataset_pin=_DATASET_PIN,
        physical_policy_registry_version="semantic-sql-policies.v1",
        physical_policy_registry_hash="cf4f5065eb4fdae76902a1c0bd817700129ad077fe56795c05ab95d76937abf4",
        population_grain_policy_id="representative-product.v1",
        dedup_policy_id="public-fund-representative-share.v1",
        authoritative_share_class_ids=("share-a", "share-b"),
        source_records=tuple(
            DatasetSourceRecord(dataset_pin=_DATASET_PIN, source_id=source_id)
            for source_id in ("source-a", "source-b", "source-observation-a")
        ),
        evidence_records=(
            DatasetEvidenceRecord(
                dataset_pin=_DATASET_PIN,
                evidence_id="evidence-a",
                source_id="source-a",
            ),
            DatasetEvidenceRecord(
                dataset_pin=_DATASET_PIN,
                evidence_id="evidence-b",
                source_id="source-b",
            ),
            DatasetEvidenceRecord(
                dataset_pin=_DATASET_PIN,
                evidence_id="evidence-observation-a",
                source_id="source-observation-a",
            ),
        ),
        representative_share_edges=(
            RepresentativeShareEdge(
                dataset_pin=_DATASET_PIN,
                representative_id="representative-a",
                share_class_id="share-a",
                predicate_id="hasShareClass",
                relation_id="relation-a",
                evidence_id="evidence-a",
                source_id="source-a",
            ),
            RepresentativeShareEdge(
                dataset_pin=_DATASET_PIN,
                representative_id="representative-a",
                share_class_id="share-b",
                predicate_id="hasShareClass",
                relation_id="relation-b",
                evidence_id="evidence-b",
                source_id="source-b",
            ),
        ),
        population_metric_ownerships=(
            PopulationMetricOwnership(
                dataset_pin=_DATASET_PIN,
                representative_id="representative-a",
                metric_id="organizer.prfd01n001.net_assets",
                metric_definition_version="2",
                owner_entity_id="representative-a",
                observation_id="observation-a",
                evidence_id="evidence-observation-a",
                source_id="source-observation-a",
            ),
        ),
    )


def _verified_population_facts() -> PhysicalReadinessFacts:
    manifest = _verified_population_manifest()
    return PhysicalReadinessFacts(
        known_entity_ids=frozenset({"representative-a", "share-a", "share-b"}),
        public_fund_manifest=manifest,
        public_fund_manifest_hash=canonical_sha256(manifest),
    )


def test_plan_readiness_is_bound_to_the_active_dataset_provenance() -> None:
    result = _assess_plan_readiness(
        _screen(field="aum", family="domestic_etf"),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        active_dataset_pin=_ACTIVE_DATASET_PIN,
    )

    assert result.dataset_version == _ACTIVE_DATASET_PIN.dataset_version
    assert result.dataset_pin == _ACTIVE_DATASET_PIN.manifest_hash


def test_public_fund_proof_cannot_be_relabelled_to_another_active_dataset() -> None:
    other_dataset = ActiveDatasetPin(
        dataset_version="synthetic-dataset-v2",
        manifest_hash="f" * 64,
    )

    result = _assess_plan_readiness(
        _public_fund_aum_sum(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=_verified_population_facts(),
        active_dataset_pin=other_dataset,
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert "DATASET_PROVENANCE_MISMATCH" in result.reason_codes


def test_public_fund_aum_sum_is_limited_when_real_grain_is_unverified() -> None:
    contract = _public_fund_aum_sum()
    before = contract.model_dump_json()

    result = _assess_plan_readiness(
        contract,
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == ("PUBLIC_FUND_GRAIN_UNVERIFIED",)
    assert contract.model_dump_json() == before


def test_synthetic_verified_representative_population_is_executable(
) -> None:
    result = _assess_plan_readiness(
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

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=_verified_population_facts(),
    )

    assert result.readiness is not PlanReadiness.EXECUTABLE
    assert "PUBLIC_FUND_REPRESENTATIVE_POLICY_REQUIRED" in result.reason_codes


def test_public_fund_representative_count_requires_population_proof() -> None:
    result = _assess_plan_readiness(
        _public_fund_representative_count(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_GRAIN_UNVERIFIED" in result.reason_codes


def test_public_fund_representative_count_uses_complete_manifest_proof() -> None:
    result = _assess_plan_readiness(
        _public_fund_representative_count(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=_verified_population_facts(),
    )

    assert result.readiness is PlanReadiness.EXECUTABLE
    assert result.reason_codes == ()


def test_public_fund_representative_count_rejects_manifest_subset() -> None:
    base = _verified_population_facts()
    manifest = base.public_fund_manifest.model_copy(
        update={
            "authoritative_share_class_ids": ("share-a",),
            "representative_share_edges": (
                base.public_fund_manifest.representative_share_edges[0],
            ),
        }
    )
    facts = base.model_copy(update={"public_fund_manifest": manifest})

    result = _assess_plan_readiness(
        _public_fund_representative_count(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=facts,
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_MANIFEST_UNTRUSTED" in result.reason_codes


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

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=_verified_population_facts(),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_GRAIN_UNVERIFIED" in result.reason_codes


def test_representative_proof_is_computed_not_declared() -> None:
    base = _verified_population_facts()
    manifest = base.public_fund_manifest.model_copy(
        update={"representative_share_edges": ()}
    )
    facts = base.model_copy(
        update={"public_fund_manifest": manifest}
    )

    result = _assess_plan_readiness(
        _public_fund_aum_sum(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=facts,
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_REPRESENTATIVE_COVERAGE_INCOMPLETE" in result.reason_codes


def test_self_consistent_manifest_subset_cannot_claim_complete_population() -> None:
    base = _verified_population_facts()
    manifest = base.public_fund_manifest.model_copy(
        update={
            "authoritative_share_class_ids": ("share-a",),
            "representative_share_edges": (
                base.public_fund_manifest.representative_share_edges[0],
            ),
        }
    )
    facts = base.model_copy(update={"public_fund_manifest": manifest})

    result = _assess_plan_readiness(
        _public_fund_aum_sum(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=facts,
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_MANIFEST_UNTRUSTED" in result.reason_codes


def test_manifest_requires_same_dataset_pin_and_linked_evidence_source() -> None:
    base = _verified_population_facts()
    edge = base.public_fund_manifest.representative_share_edges[0].model_copy(
        update={"dataset_pin": "f" * 64, "evidence_id": "missing-evidence"}
    )
    manifest = base.public_fund_manifest.model_copy(
        update={
            "representative_share_edges": (
                edge,
                base.public_fund_manifest.representative_share_edges[1],
            )
        }
    )
    facts = base.model_copy(update={"public_fund_manifest": manifest})

    result = _assess_plan_readiness(
        _public_fund_aum_sum(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=facts,
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert {
        "PUBLIC_FUND_MANIFEST_UNTRUSTED",
        "PUBLIC_FUND_DATASET_PIN_MISMATCH",
        "PUBLIC_FUND_EVIDENCE_PATH_UNVERIFIED",
    } <= set(result.reason_codes)


def test_manifest_is_bound_to_exact_representative_policy_registry() -> None:
    base = _verified_population_facts()
    manifest = base.public_fund_manifest.model_copy(
        update={"dedup_policy_id": "no-dedup.v1"}
    )
    facts = base.model_copy(update={"public_fund_manifest": manifest})

    result = _assess_plan_readiness(
        _public_fund_aum_sum(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=facts,
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert {
        "PUBLIC_FUND_MANIFEST_UNTRUSTED",
        "PUBLIC_FUND_MANIFEST_POLICY_MISMATCH",
    } <= set(result.reason_codes)


def test_representative_proof_rejects_ambiguity_cycles_and_multiple_aum_owners() -> None:
    base = _verified_population_facts()
    manifest = base.public_fund_manifest
    extra_sources = tuple(
        DatasetSourceRecord(dataset_pin=_DATASET_PIN, source_id=source_id)
        for source_id in (
            "source-c", "source-cycle", "source-observation-b"
        )
    )
    extra_evidence = (
        DatasetEvidenceRecord(
            dataset_pin=_DATASET_PIN,
            evidence_id="evidence-c",
            source_id="source-c",
        ),
        DatasetEvidenceRecord(
            dataset_pin=_DATASET_PIN,
            evidence_id="evidence-cycle",
            source_id="source-cycle",
        ),
        DatasetEvidenceRecord(
            dataset_pin=_DATASET_PIN,
            evidence_id="evidence-observation-b",
            source_id="source-observation-b",
        ),
    )
    changed_manifest = manifest.model_copy(
        update={
            "source_records": manifest.source_records + extra_sources,
            "evidence_records": manifest.evidence_records + extra_evidence,
            "representative_share_edges": manifest.representative_share_edges + (
                RepresentativeShareEdge(
                    dataset_pin=_DATASET_PIN,
                    representative_id="representative-b",
                    share_class_id="share-a",
                    predicate_id="hasShareClass",
                    relation_id="relation-c",
                    evidence_id="evidence-c",
                    source_id="source-c",
                ),
                RepresentativeShareEdge(
                    dataset_pin=_DATASET_PIN,
                    representative_id="share-a",
                    share_class_id="representative-a",
                    predicate_id="hasShareClass",
                    relation_id="relation-cycle",
                    evidence_id="evidence-cycle",
                    source_id="source-cycle",
                ),
            ),
            "population_metric_ownerships": manifest.population_metric_ownerships + (
                PopulationMetricOwnership(
                    dataset_pin=_DATASET_PIN,
                    representative_id="representative-a",
                    metric_id="organizer.prfd01n001.net_assets",
                    metric_definition_version="2",
                    owner_entity_id="representative-a",
                    observation_id="observation-b",
                    evidence_id="evidence-observation-b",
                    source_id="source-observation-b",
                ),
            ),
        }
    )
    facts = base.model_copy(
        update={
            "known_entity_ids": frozenset(
                {"representative-a", "representative-b", "share-a", "share-b"}
            ),
            "public_fund_manifest": changed_manifest,
        }
    )

    result = _assess_plan_readiness(
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
    result = _assess_plan_readiness(
        _screen(),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == ("PHYSICAL_DEFINITION_UNVERIFIED",)
    assert "public-fund-fee-rate.v1" in result.binding_ids


def test_unknown_esg_field_is_explorable_not_fabricated() -> None:
    result = _assess_plan_readiness(
        _screen("esg_rating", "domestic_etf"),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.EXPLORABLE
    assert result.reason_codes == ("SEMANTIC_CONCEPT_NOT_REGISTERED",)
    assert result.binding_ids == ()


def test_known_field_outside_scope_family_is_blocked() -> None:
    result = _assess_plan_readiness(
        _screen("maturity_date", "domestic_etf"),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert result.reason_codes == ("SEMANTIC_FIELD_FAMILY_MISMATCH",)


def test_percent_conversion_comes_from_physical_binding() -> None:
    result = _assess_plan_readiness(
        _screen("fee_rate", "domestic_etf"),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.EXECUTABLE
    assert result.unit_conversion_policy_ids == (
        "semantic-percent-to-percentage-point.v1",
    )


def test_fee_rate_requires_explicit_percentage_qualifier() -> None:
    payload = json.loads(_screen("fee_rate", "domestic_etf").model_dump_json())
    payload["qualifiers"]["unit_id"] = None

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "PHYSICAL_REQUIRED_QUALIFIER_MISSING" in result.reason_codes


def test_invented_aum_currency_and_unit_qualifiers_fail_closed() -> None:
    payload = _common("lookup", "domestic_etf")
    payload["qualifiers"] = {
        "period_id": None,
        "currency_id": "INVENTED",
        "unit_id": "invented-unit",
        "as_of_date": "2026-08-24",
    }
    payload["projections"] = {
        "field_concept_ids": ["aum"],
        "default_profile_id": None,
    }

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert {
        "CURRENCY_QUALIFIER_NOT_REGISTERED",
        "UNIT_QUALIFIER_NOT_REGISTERED",
    } <= set(result.reason_codes)


def test_count_without_field_binding_still_validates_qualifier_registry() -> None:
    payload = json.loads(_public_fund_representative_count().model_dump_json())
    payload["qualifiers"]["currency_id"] = "INVENTED"
    payload["qualifiers"]["unit_id"] = "invented-unit"

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=_verified_population_facts(),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert {
        "CURRENCY_QUALIFIER_NOT_REGISTERED",
        "UNIT_QUALIFIER_NOT_REGISTERED",
        "QUALIFIER_ACTION_UNSUPPORTED",
    } <= set(result.reason_codes)


def test_fee_rate_rejects_integer_and_non_percent_units() -> None:
    payload = json.loads(_screen("fee_rate", "domestic_etf").model_dump_json())
    payload["predicate"]["value"] = {
        "kind": "integer",
        "integer": 1,
        "unit_id": "won",
    }

    result = _assess_plan_readiness(
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

    result = _assess_plan_readiness(
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

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "CURRENCY_NORMALIZATION_POLICY_REQUIRED" in result.reason_codes


def test_domestic_overseas_aum_compare_requires_normalization() -> None:
    payload = _common("compare", "domestic_etf")
    payload["scope"]["product_family_ids"] = ["domestic_etf", "overseas_etf"]
    payload["qualifiers"]["as_of_date"] = "2026-08-24"
    payload["comparison"] = {
        "subject_refs": ["entity-a", "entity-b"],
        "group_basis_id": None,
        "metric_concept_ids": ["aum"],
        "projection_profile_id": None,
        "basis_policy_id": "same-definition-period-unit.v1",
        "normalization_policy_id": None,
    }

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
        facts=PhysicalReadinessFacts(
            known_entity_ids=frozenset({"entity-a", "entity-b"})
        ),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert "CURRENCY_NORMALIZATION_POLICY_REQUIRED" in result.reason_codes


def test_required_as_of_qualifier_is_independently_enforced() -> None:
    payload = _common("lookup", "domestic_etf")
    payload["projections"] = {
        "field_concept_ids": ["aum"],
        "default_profile_id": None,
    }
    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == ("PHYSICAL_REQUIRED_QUALIFIER_MISSING",)


def test_comparison_checks_metrics_and_basis_policy() -> None:
    payload = _common("compare", "domestic_etf")
    payload["qualifiers"]["unit_id"] = "percent"
    payload["comparison"] = {
        "subject_refs": ["entity-a", "entity-b"],
        "group_basis_id": None,
        "metric_concept_ids": ["fee_rate"],
        "projection_profile_id": None,
        "basis_policy_id": "same-definition-period-unit.v1",
        "normalization_policy_id": None,
    }

    result = _assess_plan_readiness(
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
    payload["qualifiers"]["unit_id"] = "percent"
    payload["calculation"] = {
        "recipe_id": "unregistered-recipe.v1",
        "operands": [
            {"role_id": "metric", "value_ref": None, "field_concept_id": "fee_rate"}
        ],
    }

    result = _assess_plan_readiness(
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

    result = _assess_plan_readiness(
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

    result = _assess_plan_readiness(
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
    count_result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )
    assert "COUNT_POPULATION_MISMATCH" in count_result.reason_codes

    compare = _common("compare", "domestic_etf")
    compare["qualifiers"]["unit_id"] = "percent"
    compare["comparison"] = {
        "subject_refs": ["unknown-a", "unknown-b"],
        "group_basis_id": None,
        "metric_concept_ids": ["fee_rate"],
        "projection_profile_id": None,
        "basis_policy_id": "same-definition-period-unit.v1",
        "normalization_policy_id": None,
    }
    compare_result = _assess_plan_readiness(
        _validate(compare),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )
    assert compare_result.readiness is PlanReadiness.LIMITED
    assert compare_result.reason_codes == ("ENTITY_IDENTITY_UNVERIFIED",)


def test_scope_entity_and_prior_result_binding_fail_closed() -> None:
    payload = _common("lookup", "domestic_etf")
    payload["qualifiers"]["unit_id"] = "percent"
    payload["scope"]["entity_refs"] = ["unknown-entity"]
    payload["scope"]["prior_result_binding"] = "unknown-result"
    payload["projections"] = {
        "field_concept_ids": ["fee_rate"],
        "default_profile_id": None,
    }

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert result.reason_codes == (
        "ENTITY_IDENTITY_UNVERIFIED",
        "PRIOR_RESULT_READINESS_CONTEXT_REQUIRED",
    )


def _rank_contract(
    *, family: str | None, prior: str | None = None, frame_id: str = "frame-1"
):
    payload = _common("rank", family or "domestic_etf")
    payload["frame_id"] = frame_id
    payload["scope"] = {
        "product_family_ids": [family] if family else [],
        "entity_refs": [],
        "prior_result_binding": prior,
    }
    payload["qualifiers"] = {
        "period_id": None,
        "currency_id": None,
        "unit_id": None,
        "as_of_date": "2026-08-24",
    }
    payload["ordering"] = [{
        "field_concept_id": "aum",
        "direction": "desc",
        "direction_policy_id": None,
        "nulls_policy_id": "exclude_missing.v1",
        "tie_break_policy_id": "stable-product-id.v1",
    }]
    payload["limit"] = 5 if prior is None else 1
    payload["limit_policy_id"] = None
    payload["predicate"] = None
    return _validate(payload)


def _prior_context(
    producer,
    consumer,
    assessment,
    *,
    binding_name="result-set-1",
    product_family_ids=None,
    producer_prior_result_context=None,
):
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    return PriorResultReadinessContext(
        dataset_version=_ACTIVE_DATASET_PIN.dataset_version,
        dataset_pin=_ACTIVE_DATASET_PIN.manifest_hash,
        binding_registry_version=bindings.registry_version,
        binding_registry_hash=bindings.registry_hash,
        policy_registry_version=policies.registry_version,
        policy_registry_hash=policies.registry_hash,
        sources=(
            PriorResultReadinessSource(
                binding_name=binding_name,
                producer_contract=producer,
                producer_assessment=assessment,
                consumer_frame_id=consumer.frame_id,
                consumer_contract_hash=canonical_sha256(consumer),
                product_family_ids=(
                    producer.scope.product_family_ids
                    if product_family_ids is None
                    else product_family_ids
                ),
                **(
                    {
                        "producer_prior_result_context": (
                            producer_prior_result_context
                        )
                    }
                    if producer_prior_result_context is not None
                    else {}
                ),
            ),
        ),
    )


def test_prior_result_readiness_recomputes_every_three_frame_predecessor() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    first = _rank_contract(family="domestic_etf", frame_id="frame-1")
    first_plan = _assess_plan_readiness(first, bindings, policies)
    second = _rank_contract(
        family=None, prior="result-set-1", frame_id="frame-2"
    )
    first_context = _prior_context(first, second, first_plan)
    second_plan = assess_plan_readiness(
        second,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=first_context,
    )
    third = _rank_contract(
        family=None, prior="result-set-2", frame_id="frame-3"
    )
    second_context = _prior_context(
        second,
        third,
        second_plan,
        binding_name="result-set-2",
        product_family_ids=(ProductFamily.DOMESTIC_ETF,),
        producer_prior_result_context=first_context,
    )

    result = assess_plan_readiness(
        third,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=second_context,
    )

    assert result.readiness is PlanReadiness.EXECUTABLE
    assert result.binding_ids == ("domestic-etf-aum.v1",)


def test_prior_result_readiness_rejects_extra_and_missing_context_sources() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    producer = _rank_contract(family="domestic_etf", frame_id="frame-1")
    producer_plan = _assess_plan_readiness(producer, bindings, policies)
    consumer = _rank_contract(
        family=None, prior="result-set-1", frame_id="frame-2"
    )
    valid = _prior_context(producer, consumer, producer_plan)
    foreign_source = valid.sources[0].model_copy(
        update={"binding_name": "foreign-result"}
    )

    extra = assess_plan_readiness(
        consumer,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=valid.model_copy(
            update={"sources": (*valid.sources, foreign_source)}
        ),
    )
    missing = assess_plan_readiness(
        consumer,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=valid.model_copy(
            update={"sources": (foreign_source,)}
        ),
    )

    assert extra.readiness is PlanReadiness.BLOCKED
    assert "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH" in extra.reason_codes
    assert missing.readiness is PlanReadiness.BLOCKED
    assert "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH" in missing.reason_codes


def test_prior_result_readiness_rejects_forged_intermediate_assessment() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    facts = _verified_population_facts()
    first_payload = _common("lookup", "public_fund")
    first_payload["qualifiers"]["as_of_date"] = "2026-08-24"
    first_payload["projections"] = {
        "field_concept_ids": ["aum"],
        "default_profile_id": None,
    }
    first = _validate(first_payload)
    first_plan = _assess_plan_readiness(first, bindings, policies, facts=facts)
    second = _rank_contract(
        family=None, prior="result-set-1", frame_id="frame-2"
    )
    first_context = _prior_context(first, second, first_plan)
    limited = assess_plan_readiness(
        second,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        facts=facts,
        prior_result_context=first_context,
    )
    assert limited.readiness is PlanReadiness.LIMITED
    forged = limited.model_copy(
        update={"readiness": PlanReadiness.EXECUTABLE, "reason_codes": ()}
    )
    third = _rank_contract(
        family=None, prior="result-set-2", frame_id="frame-3"
    )
    forged_context = _prior_context(
        second,
        third,
        forged,
        binding_name="result-set-2",
        product_family_ids=(ProductFamily.PUBLIC_FUND,),
        producer_prior_result_context=first_context,
    )

    result = assess_plan_readiness(
        third,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        facts=facts,
        prior_result_context=forged_context,
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH" in result.reason_codes


def test_prior_result_readiness_rejects_dependency_cycle() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    second = _rank_contract(
        family=None, prior="result-set-1", frame_id="frame-2"
    )
    third = _rank_contract(
        family=None, prior="result-set-2", frame_id="frame-3"
    )
    forged_second_plan = PlanReadinessResult(
        frame_id=second.frame_id,
        contract_hash=canonical_sha256(second),
        dataset_version=_ACTIVE_DATASET_PIN.dataset_version,
        dataset_pin=_ACTIVE_DATASET_PIN.manifest_hash,
        binding_registry_version=bindings.registry_version,
        binding_registry_hash=bindings.registry_hash,
        policy_registry_version=policies.registry_version,
        policy_registry_hash=policies.registry_hash,
        readiness=PlanReadiness.EXECUTABLE,
        reason_codes=(),
        binding_ids=("domestic-etf-aum.v1",),
        policy_ids=(
            "exclude_missing.v1",
            "stable-product-id.v1",
        ),
        unit_conversion_policy_ids=("identity-unit.v1",),
    )
    forged_third_plan = forged_second_plan.model_copy(
        update={
            "frame_id": third.frame_id,
            "contract_hash": canonical_sha256(third),
        }
    )
    cycle_back = _prior_context(
        third,
        second,
        forged_third_plan,
        binding_name="result-set-1",
        product_family_ids=(ProductFamily.DOMESTIC_ETF,),
    )
    outer = _prior_context(
        second,
        third,
        forged_second_plan,
        binding_name="result-set-2",
        product_family_ids=(ProductFamily.DOMESTIC_ETF,),
        producer_prior_result_context=cycle_back,
    )

    result = assess_plan_readiness(
        third,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=outer,
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert "PRIOR_RESULT_READINESS_CYCLE" in result.reason_codes


def test_prior_result_readiness_bounds_dependency_depth() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    producer = _rank_contract(family="domestic_etf", frame_id="frame-1")
    producer_plan = _assess_plan_readiness(producer, bindings, policies)
    producer_context = None

    for frame_number in range(2, 19):
        binding_name = f"result-set-{frame_number - 1}"
        consumer = _rank_contract(
            family=None,
            prior=binding_name,
            frame_id=f"frame-{frame_number}",
        )
        consumer_context = _prior_context(
            producer,
            consumer,
            producer_plan,
            binding_name=binding_name,
            product_family_ids=(ProductFamily.DOMESTIC_ETF,),
            producer_prior_result_context=producer_context,
        )
        producer_plan = assess_plan_readiness(
            consumer,
            bindings,
            policies,
            active_dataset_pin=_ACTIVE_DATASET_PIN,
            prior_result_context=consumer_context,
        )
        producer = consumer
        producer_context = consumer_context

    assert producer_plan.readiness is PlanReadiness.BLOCKED
    assert (
        "PRIOR_RESULT_READINESS_DEPTH_EXCEEDED"
        in producer_plan.reason_codes
    )


def test_familyless_prior_scope_uses_authoritative_upstream_readiness_context() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    producer = _rank_contract(family="domestic_etf")
    producer_assessment = _assess_plan_readiness(producer, bindings, policies)
    consumer = _rank_contract(
        family=None, prior="result-set-1", frame_id="frame-2"
    )

    result = assess_plan_readiness(
        consumer,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=_prior_context(producer, consumer, producer_assessment),
    )

    assert producer_assessment.readiness is PlanReadiness.EXECUTABLE
    assert result.readiness is PlanReadiness.EXECUTABLE
    assert result.binding_ids == ("domestic-etf-aum.v1",)


def test_familyless_prior_scope_without_or_with_foreign_context_is_blocked() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    consumer = _rank_contract(
        family=None, prior="result-set-1", frame_id="frame-2"
    )

    missing = assess_plan_readiness(
        consumer,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
    )
    producer = _rank_contract(family="domestic_etf")
    producer_assessment = _assess_plan_readiness(producer, bindings, policies)
    foreign = _prior_context(producer, consumer, producer_assessment).model_copy(
        update={"dataset_pin": "f" * 64}
    )
    mismatched = assess_plan_readiness(
        consumer,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=foreign,
    )
    valid_context = _prior_context(producer, consumer, producer_assessment)
    forged_source = valid_context.sources[0].model_copy(
        update={"product_family_ids": (ProductFamily.PUBLIC_FUND,)}
    )
    forged = assess_plan_readiness(
        consumer,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=valid_context.model_copy(
            update={"sources": (forged_source,)}
        ),
    )

    assert missing.readiness is PlanReadiness.BLOCKED
    assert "PRIOR_RESULT_READINESS_CONTEXT_REQUIRED" in missing.reason_codes
    assert mismatched.readiness is PlanReadiness.BLOCKED
    assert "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH" in mismatched.reason_codes
    assert forged.readiness is PlanReadiness.BLOCKED
    assert "PRIOR_RESULT_READINESS_CONTEXT_MISMATCH" in forged.reason_codes


def _public_fund_prior_aggregate(*, representative: bool):
    payload = _common("aggregate", "domestic_etf")
    payload["frame_id"] = "frame-2"
    payload["scope"] = {
        "product_family_ids": [],
        "entity_refs": [],
        "prior_result_binding": "result-set-1",
    }
    payload["qualifiers"]["as_of_date"] = "2026-08-24"
    payload["aggregation"] = {
        "function_id": "sum",
        "target_field_concept_id": "aum",
        "count_population_id": None,
        "group_by_field_concept_ids": [],
        "bucket_policy_id": None,
        "population_grain_id": (
            "representative-product.v1" if representative else "source-product.v1"
        ),
        "dedup_policy_id": (
            "public-fund-representative-share.v1"
            if representative
            else "no-dedup.v1"
        ),
    }
    payload["predicate"] = None
    return _validate(payload)


def test_public_fund_prior_aggregate_requires_representative_policy_and_proof() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    producer_payload = _common("lookup", "public_fund")
    producer_payload["qualifiers"]["as_of_date"] = "2026-08-24"
    producer_payload["projections"] = {
        "field_concept_ids": ["aum"],
        "default_profile_id": None,
    }
    producer = _validate(producer_payload)
    producer_assessment = _assess_plan_readiness(producer, bindings, policies)
    unsafe = _public_fund_prior_aggregate(representative=False)
    safe = _public_fund_prior_aggregate(representative=True)

    unsafe_result = assess_plan_readiness(
        unsafe,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=_prior_context(producer, unsafe, producer_assessment),
    )
    unproved = assess_plan_readiness(
        safe,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=_prior_context(producer, safe, producer_assessment),
    )
    proved = assess_plan_readiness(
        safe,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=_prior_context(producer, safe, producer_assessment),
        facts=_verified_population_facts(),
    )

    assert unsafe_result.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_REPRESENTATIVE_POLICY_REQUIRED" in unsafe_result.reason_codes
    assert unproved.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_GRAIN_UNVERIFIED" in unproved.reason_codes
    assert proved.readiness is PlanReadiness.EXECUTABLE


def test_public_fund_prior_rank_inherits_upstream_family_policy() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)
    producer_payload = _common("lookup", "public_fund")
    producer_payload["qualifiers"]["as_of_date"] = "2026-08-24"
    producer_payload["projections"] = {
        "field_concept_ids": ["aum"],
        "default_profile_id": None,
    }
    producer = _validate(producer_payload)
    producer_assessment = _assess_plan_readiness(producer, bindings, policies)
    consumer = _rank_contract(
        family=None,
        prior="result-set-1",
        frame_id="frame-2",
    )

    result = assess_plan_readiness(
        consumer,
        bindings,
        policies,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_context=_prior_context(producer, consumer, producer_assessment),
        facts=_verified_population_facts(),
    )

    assert producer_assessment.readiness is PlanReadiness.EXECUTABLE
    assert result.readiness is PlanReadiness.LIMITED
    assert "PUBLIC_FUND_GRAIN_UNVERIFIED" in result.reason_codes


def test_unknown_comparison_group_basis_fails_closed() -> None:
    payload = _common("compare", "domestic_etf")
    payload["qualifiers"]["unit_id"] = "percent"
    payload["comparison"] = {
        "subject_refs": [],
        "group_basis_id": "invented-group-basis",
        "metric_concept_ids": ["fee_rate"],
        "projection_profile_id": None,
        "basis_policy_id": "same-definition-period-unit.v1",
        "normalization_policy_id": None,
    }

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.LIMITED
    assert result.reason_codes == ("COMPARISON_GROUP_BASIS_UNVERIFIED",)


def test_semantic_registry_pin_mismatch_is_blocked() -> None:
    payload = json.loads(_screen("fee_rate", "domestic_etf").model_dump_json())
    payload["registry_pins"]["operator_registry_hash"] = "f" * 64

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.BLOCKED
    assert "SEMANTIC_REGISTRY_PIN_MISMATCH" in result.reason_codes


def test_explanation_topic_without_physical_source_is_explorable() -> None:
    payload = _common("explain", "domestic_etf")
    payload["explanation"] = {"topic_concept_id": "risk_factor", "profile_id": None}

    result = _assess_plan_readiness(
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

    result = _assess_plan_readiness(
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
        "unit_id": "percent",
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

    result = _assess_plan_readiness(
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


def test_grouped_distinct_population_count_preserves_grain_readiness() -> None:
    payload = _common("aggregate", "domestic_etf")
    payload["contract_variant_id"] = "aggregate.grouped.v2"
    payload["result_shape"] = "grouped_table"
    payload["aggregation"] = {
        "function_id": "count_distinct",
        "target_field_concept_id": None,
        "count_population_id": "source-product.v1",
        "group_by_field_concept_ids": ["product_risk_grade"],
        "bucket_policy_id": None,
        "population_grain_id": "source-product.v1",
        "dedup_policy_id": "no-dedup.v1",
    }
    payload["predicate"] = None

    result = _assess_plan_readiness(
        _validate(payload),
        load_physical_binding_registry(PROJECT_ROOT),
        load_semantic_sql_policy_registry(PROJECT_ROOT),
    )

    assert result.readiness is PlanReadiness.EXPLORABLE
    assert "COUNT_POPULATION_MISMATCH" not in result.reason_codes
    assert result.reason_codes == ("PHYSICAL_BINDING_NOT_REGISTERED",)


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

    result = _assess_plan_readiness(
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
