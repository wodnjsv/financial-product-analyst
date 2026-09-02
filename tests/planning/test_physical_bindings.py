from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from financial_agent.planning.physical_bindings import (
    ObservationValueColumn,
    PhysicalBindingAvailability,
    PhysicalReadinessFacts,
    load_physical_binding_registry,
    load_semantic_sql_policy_registry,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _write_registry(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_policy_registry(tmp_path: Path, policies: list[dict[str, object]]) -> Path:
    path = tmp_path / "policies.json"
    path.write_text(
        json.dumps(
            {"registry_version": "semantic-sql-policies.v1", "policies": policies}
        ),
        encoding="utf-8",
    )
    return path


def _valid_binding(**updates: object) -> dict[str, object]:
    binding: dict[str, object] = {
        "id": "domestic-etf-aum.v1",
        "semantic_concept_id": "aum",
        "product_family_id": "domestic_etf",
        "source_kind": "observation",
        "availability": "verified",
        "approved_metric_ids": ["organizer.pref01n001.aum"],
        "value_column": "decimal_value",
        "semantic_value_kind": "decimal",
        "storage_unit_id": "source_defined_amount",
        "unit_conversion_policy_id": "identity-unit.v1",
        "period_behavior": "point_in_time",
        "date_behavior": "applicable_date",
        "missingness_policy_id": "exclude_missing.v1",
        "supported_operator_ids": ["eq", "neq", "lt", "lte", "gt", "gte", "between", "in", "not_in", "is_missing", "is_present"],
        "supported_aggregate_ids": ["sum", "avg", "min", "max"],
        "supported_qualifier_ids": ["as_of", "currency", "unit"],
        "required_qualifier_ids": ["as_of"],
        "accepted_semantic_unit_ids": [],
        "currency_normalization_required": False,
        "verified_population_grain_ids": ["source-product.v1"],
        "required_evidence_locators": ["metric_definition", "observation_record", "evidence_record", "source_record"],
        "unavailable_reason_code": None,
    }
    binding.update(updates)
    return binding


def _payload(*bindings: dict[str, object]) -> dict[str, object]:
    payload = json.loads(
        (PROJECT_ROOT / "config/planning/semantic-sql-bindings.v1.json").read_text()
    )
    payload["bindings"] = list(bindings)
    return payload


def test_loader_returns_closed_immutable_verified_repository_bindings() -> None:
    registry = load_physical_binding_registry(PROJECT_ROOT)

    domestic_aum = registry.binding_for("domestic_etf", "aum")
    overseas_fee = registry.binding_for("overseas_etf", "fee_rate")
    public_fee = registry.binding_for("public_fund", "fee_rate")

    assert domestic_aum is not None
    assert domestic_aum.approved_metric_ids == ("organizer.pref01n001.aum",)
    assert domestic_aum.value_column is ObservationValueColumn.DECIMAL
    assert domestic_aum.required_qualifier_ids[0].value == "as_of"
    assert overseas_fee is not None
    assert overseas_fee.approved_metric_ids == ("organizer.pref02n001.total_fee_rate",)
    assert public_fee is not None
    assert public_fee.availability is PhysicalBindingAvailability.UNAVAILABLE
    assert public_fee.unavailable_reason_code == "PHYSICAL_DEFINITION_UNVERIFIED"
    assert public_fee.approved_metric_ids == ()
    assert public_fee.value_column is None
    with pytest.raises(TypeError):
        registry.bindings_by_id["new"] = domestic_aum  # type: ignore[index]
    with pytest.raises(ValidationError):
        domestic_aum.storage_unit_id = "won"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("update", "reason"),
    [
        ({"semantic_concept_id": "esg_rating"}, "unknown semantic concept"),
        ({"product_family_id": "crypto"}, "invalid physical binding registry"),
        ({"value_column": "numeric_value"}, "invalid physical binding registry"),
        ({"semantic_value_kind": "string"}, "binding value kind mismatch"),
        ({"supported_operator_ids": ["contains"]}, "operator/value kind mismatch"),
        ({"required_evidence_locators": []}, "missing evidence requirements"),
        ({"required_evidence_locators": ["observation_record"]}, "missing evidence requirements"),
    ],
)
def test_loader_rejects_unknown_or_incompatible_binding_fields(
    tmp_path: Path, update: dict[str, object], reason: str
) -> None:
    path = _write_registry(tmp_path, _payload(_valid_binding(**update)))

    with pytest.raises(ValueError, match=reason):
        load_physical_binding_registry(PROJECT_ROOT, registry_path=path)


def test_loader_rejects_duplicate_family_concept_pair(tmp_path: Path) -> None:
    duplicate = _valid_binding(id="another-binding.v1")
    path = _write_registry(tmp_path, _payload(_valid_binding(), duplicate))

    with pytest.raises(ValueError, match="duplicate family/concept binding"):
        load_physical_binding_registry(PROJECT_ROOT, registry_path=path)


def test_loader_rejects_binding_policy_kind_mismatch(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        _payload(_valid_binding(unit_conversion_policy_id="stable-product-id.v1")),
    )

    with pytest.raises(ValueError, match="binding unit policy kind mismatch"):
        load_physical_binding_registry(PROJECT_ROOT, registry_path=path)


@pytest.mark.parametrize(
    "update",
    [
        {"approved_metric_ids": ["organizer.pref02n001.aum"]},
        {"storage_unit_id": "invented_amount"},
    ],
)
def test_loader_rejects_binding_definition_not_in_code_allowlist(
    tmp_path: Path, update: dict[str, object]
) -> None:
    payload = json.loads(
        (PROJECT_ROOT / "config/planning/semantic-sql-bindings.v1.json").read_text()
    )
    payload["bindings"][0].update(update)
    path = _write_registry(tmp_path, payload)

    with pytest.raises(ValueError, match="physical binding definition mismatch"):
        load_physical_binding_registry(PROJECT_ROOT, registry_path=path)


@pytest.mark.parametrize(
    ("pin_path", "reason"),
    [
        (("semantic_registry_pins", "operator_registry_hash"), "semantic registry pin mismatch"),
        (("physical_policy_registry_hash",), "physical policy registry pin mismatch"),
    ],
)
def test_binding_loader_rejects_registry_pin_mismatch(
    tmp_path: Path, pin_path: tuple[str, ...], reason: str
) -> None:
    payload = json.loads(
        (PROJECT_ROOT / "config/planning/semantic-sql-bindings.v1.json").read_text()
    )
    target = payload
    for part in pin_path[:-1]:
        target = target[part]
    target[pin_path[-1]] = "f" * 64
    path = _write_registry(tmp_path, payload)

    with pytest.raises(ValueError, match=reason):
        load_physical_binding_registry(PROJECT_ROOT, registry_path=path)


def test_unavailable_binding_cannot_smuggle_metric_or_derived_definition(
    tmp_path: Path,
) -> None:
    path = _write_registry(
        tmp_path,
        _payload(
            _valid_binding(
                id="public-fund-fee-rate.v1",
                product_family_id="public_fund",
                semantic_concept_id="fee_rate",
                availability="unavailable",
                approved_metric_ids=[
                    "organizer.prfd01n001.manager_fee_rate",
                    "organizer.prfd01n001.sales_fee_rate",
                ],
                unavailable_reason_code="PHYSICAL_DEFINITION_UNVERIFIED",
            )
        ),
    )

    with pytest.raises(ValueError, match="unavailable binding must not expose physical fields"):
        load_physical_binding_registry(PROJECT_ROOT, registry_path=path)


def test_policy_registry_validates_representative_relation_and_is_immutable() -> None:
    registry = load_semantic_sql_policy_registry(PROJECT_ROOT)
    policy = registry.policies_by_id["public-fund-representative-share.v1"]

    assert policy.relation_predicate_id == "hasShareClass"
    assert policy.relation_direction == "subject_to_object"
    assert policy.population_grain_id == "representative-product.v1"
    assert policy.verified is True
    assert policy.unavailable_reason_code is None
    with pytest.raises(TypeError):
        registry.policies_by_id["new"] = policy  # type: ignore[index]


def test_registry_direct_construction_cannot_bypass_validated_loader() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)

    with pytest.raises(ValueError, match="registry definition mismatch"):
        replace(bindings, registry_version="invented-bindings.v1")
    with pytest.raises(ValueError, match="registry definition mismatch"):
        replace(policies, registry_version="invented-policies.v1")


def test_registry_replace_cannot_clone_token_and_alter_validated_content() -> None:
    bindings = load_physical_binding_registry(PROJECT_ROOT)
    policies = load_semantic_sql_policy_registry(PROJECT_ROOT)

    with pytest.raises(ValueError, match="registry hash mismatch"):
        replace(bindings, registry_hash="f" * 64)
    with pytest.raises(ValueError, match="registry definition mismatch"):
        replace(bindings, bindings_by_id={})
    with pytest.raises(ValueError, match="registry definition mismatch"):
        replace(bindings, bindings_by_family_concept={})
    with pytest.raises(ValueError, match="registry definition mismatch"):
        replace(bindings, catalog_families_by_concept={})
    with pytest.raises(ValueError, match="registry definition mismatch"):
        replace(
            bindings,
            semantic_registry_pins=bindings.semantic_registry_pins.model_copy(
                update={"operator_registry_hash": "f" * 64}
            ),
        )
    with pytest.raises(ValueError, match="registry definition mismatch"):
        replace(bindings, physical_policy_registry_hash="f" * 64)
    with pytest.raises(ValueError, match="registry hash mismatch"):
        replace(policies, registry_hash="f" * 64)
    with pytest.raises(ValueError, match="registry definition mismatch"):
        replace(policies, policies_by_id={})
    altered_policies = dict(policies.policies_by_id)
    altered_policies["identity-unit.v1"] = altered_policies[
        "identity-unit.v1"
    ].model_copy(update={"verified": False, "unavailable_reason_code": "INVENTED"})
    with pytest.raises(ValueError, match="registry definition mismatch"):
        replace(policies, policies_by_id=altered_policies)


def test_registry_replace_deep_freezes_mutable_input_collections() -> None:
    registry = load_physical_binding_registry(PROJECT_ROOT)
    mutable_concepts = set(registry.catalog_concept_ids)
    mutable_families = {
        concept_id: set(families)
        for concept_id, families in registry.catalog_families_by_concept.items()
    }

    cloned = replace(
        registry,
        catalog_concept_ids=mutable_concepts,  # type: ignore[arg-type]
        catalog_families_by_concept=mutable_families,  # type: ignore[arg-type]
    )
    mutable_concepts.clear()
    mutable_families["aum"].clear()

    assert cloned.catalog_concept_ids == registry.catalog_concept_ids
    assert cloned.catalog_families_by_concept["aum"] == registry.catalog_families_by_concept["aum"]
    assert isinstance(cloned.catalog_families_by_concept["aum"], frozenset)


def test_readiness_facts_reject_caller_asserted_verified_id_sets() -> None:
    with pytest.raises(ValidationError):
        PhysicalReadinessFacts.model_validate(
            {"verified_relation_ids": ["caller-asserted-relation"]}
        )


def test_policy_loader_rejects_duplicate_and_unknown_relation(tmp_path: Path) -> None:
    base = {
        "id": "test-policy.v1",
        "kind": "deduplication",
        "applicable_product_family_ids": ["public_fund"],
        "verified": True,
        "relation_predicate_id": "unknownRelation",
        "relation_direction": "subject_to_object",
        "population_grain_id": "representative-product.v1",
        "required_evidence_locators": [
            "relation_record",
            "evidence_record",
            "source_record",
        ],
        "unavailable_reason_code": None,
    }
    unknown_path = _write_policy_registry(tmp_path, [base])
    with pytest.raises(ValueError, match="unknown policy relation concept"):
        load_semantic_sql_policy_registry(PROJECT_ROOT, registry_path=unknown_path)

    duplicate = dict(base, relation_predicate_id="hasShareClass")
    duplicate_path = _write_policy_registry(tmp_path, [duplicate, duplicate])
    with pytest.raises(ValueError, match="duplicate semantic SQL policy"):
        load_semantic_sql_policy_registry(PROJECT_ROOT, registry_path=duplicate_path)


def test_policy_loader_rejects_invented_verified_policy(tmp_path: Path) -> None:
    payload = json.loads(
        (PROJECT_ROOT / "config/planning/semantic-sql-policies.v1.json").read_text()
    )
    payload["policies"].append(
        {
            "id": "invented-policy.v1",
            "kind": "normalization",
            "applicable_product_family_ids": [],
            "verified": True,
            "relation_predicate_id": None,
            "relation_direction": None,
            "population_grain_id": None,
            "unavailable_reason_code": None,
        }
    )
    path = _write_policy_registry(tmp_path, payload["policies"])

    with pytest.raises(ValueError, match="semantic SQL policy definition mismatch"):
        load_semantic_sql_policy_registry(PROJECT_ROOT, registry_path=path)
