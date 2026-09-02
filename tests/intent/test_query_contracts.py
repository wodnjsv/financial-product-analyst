from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from financial_agent.contracts.canonical import canonical_json_bytes
from financial_agent.contracts.enums import IntentType
from financial_agent.intent.query_contracts import (
    AxisReadiness,
    LookupQueryContractV2,
    ResolvedQueryContractBundleV2,
    ResolvedQueryContractV2,
    ScreenQueryContractV2,
    SolvedQueryContractCandidateV2,
    TypedSemanticValue,
)


RESOLVED_ADAPTER = TypeAdapter(ResolvedQueryContractV2)
CANDIDATE_ADAPTER = TypeAdapter(SolvedQueryContractCandidateV2)


def _base(action_id: str, result_shape: str) -> dict[str, Any]:
    return {
        "contract_schema_version": "2.0",
        "contract_variant_id": {
            "lookup": "lookup.projection.v2",
            "screen": "screen.predicate.v2",
            "rank": "rank.ordering.v2",
            "compare": "compare.subjects.v2",
            "aggregate": "aggregate.scalar.v2",
            "calculate": "calculate.recipe.v2",
            "similar": "similar.policy.v2",
            "explain": "explain.topic.v2",
        }[action_id],
        "frame_id": f"frame-{action_id}",
        "action_id": action_id,
        "scope": {
            "product_family_ids": ["public_fund"],
            "entity_refs": [],
            "prior_result_binding": None,
        },
        "qualifiers": {},
        "result_shape": result_shape,
        "provenance": [
            {
                "semantic_input_id": "scope",
                "source_kind": "exact_lock",
                "source_ref": "question-span-1",
            }
        ],
        "registry_pins": {
            "contract_registry_version": "query-contract-registry.v2",
            "contract_registry_hash": "a" * 64,
            "operator_registry_version": "query-operator-registry.v1",
            "operator_registry_hash": "b" * 64,
            "policy_registry_version": "query-policy-registry.v1",
            "policy_registry_hash": "c" * 64,
        },
        "axis_readiness": {"readiness": "complete", "reason_codes": []},
        "contract_readiness": {"readiness": "complete", "reason_codes": []},
        "plan_readiness": {"readiness": "executable", "reason_codes": []},
    }


def _payload(action_id: str) -> dict[str, Any]:
    if action_id == "lookup":
        return {
            **_base(action_id, "product_list"),
            "projections": {
                "field_concept_ids": ["official_product_name", "fee_rate"],
                "default_profile_id": None,
            },
        }
    if action_id == "screen":
        return {
            **_base(action_id, "product_list"),
            "predicate": {
                "node_type": "atom",
                "field_concept_id": "fee_rate",
                "operator_id": "lte",
                "value": {"kind": "decimal", "decimal": "1", "unit_id": "percent"},
                "values": [],
                "null_policy_id": "exclude_missing.v1",
            },
        }
    if action_id == "rank":
        return {
            **_base(action_id, "top_k"),
            "ordering": [
                {
                    "field_concept_id": "aum",
                    "direction": "desc",
                    "direction_policy_id": None,
                    "nulls_policy_id": "exclude_missing.v1",
                    "tie_break_policy_id": "stable-product-id.v1",
                }
            ],
            "limit": 5,
            "limit_policy_id": None,
            "predicate": None,
        }
    if action_id == "compare":
        return {
            **_base(action_id, "comparison_table"),
            "comparison": {
                "subject_refs": ["product-a", "product-b"],
                "group_basis_id": None,
                "metric_concept_ids": ["fee_rate"],
                "projection_profile_id": None,
                "basis_policy_id": "same-definition-period-unit.v1",
                "normalization_policy_id": None,
            },
        }
    if action_id == "aggregate":
        return {
            **_base(action_id, "single_value"),
            "aggregation": {
                "function_id": "sum",
                "target_field_concept_id": "aum",
                "count_population_id": None,
                "group_by_field_concept_ids": [],
                "bucket_policy_id": None,
                "population_grain_id": "representative-product.v1",
                "dedup_policy_id": "public-fund-representative-share.v1",
            },
            "predicate": None,
        }
    if action_id == "calculate":
        return {
            **_base(action_id, "single_value"),
            "calculation": {
                "recipe_id": "simple-interest.v1",
                "operands": [
                    {
                        "role_id": "principal",
                        "value_ref": "literal-principal",
                        "field_concept_id": None,
                    }
                ],
            },
        }
    if action_id == "similar":
        return {
            **_base(action_id, "product_list"),
            "similarity": {
                "anchor_ref": "product-a",
                "policy_id": "cosine-complete-dimensions.v1",
                "dimension_concept_ids": ["fee_rate", "aum"],
                "default_profile_id": None,
                "coverage_threshold": "0.8",
                "limit": 5,
            },
        }
    if action_id == "explain":
        return {
            **_base(action_id, "explanation"),
            "explanation": {
                "topic_concept_id": "risk_factor",
                "profile_id": None,
            },
        }
    raise AssertionError(action_id)


def _validate(payload: dict[str, Any]):
    return RESOLVED_ADAPTER.validate_json(json.dumps(payload))


@pytest.mark.parametrize("action_id", [item.value for item in IntentType])
def test_every_action_has_one_strict_resolved_variant(action_id: str) -> None:
    contract = _validate(_payload(action_id))

    assert contract.action_id.value == action_id
    assert contract.contract_schema_version == "2.0"


@pytest.mark.parametrize(
    ("action_id", "missing_path"),
    [
        ("lookup", ("scope",)),
        ("lookup", ("projections",)),
        ("screen", ("scope",)),
        ("screen", ("predicate", "field_concept_id")),
        ("screen", ("predicate", "operator_id")),
        ("screen", ("predicate", "value")),
        ("rank", ("scope",)),
        ("rank", ("ordering", 0, "field_concept_id")),
        ("rank", ("ordering", 0, "direction")),
        ("rank", ("limit",)),
        ("compare", ("scope",)),
        ("compare", ("comparison", "subject_refs")),
        ("compare", ("comparison", "metric_concept_ids")),
        ("compare", ("comparison", "basis_policy_id")),
        ("aggregate", ("scope",)),
        ("aggregate", ("aggregation", "function_id")),
        ("aggregate", ("aggregation", "target_field_concept_id")),
        ("aggregate", ("aggregation", "population_grain_id")),
        ("aggregate", ("aggregation", "dedup_policy_id")),
        ("calculate", ("scope",)),
        ("calculate", ("calculation", "recipe_id")),
        ("calculate", ("calculation", "operands")),
        ("similar", ("scope",)),
        ("similar", ("similarity", "anchor_ref")),
        ("similar", ("similarity", "policy_id")),
        ("similar", ("similarity", "dimension_concept_ids")),
        ("similar", ("similarity", "coverage_threshold")),
        ("similar", ("similarity", "limit")),
        ("explain", ("scope",)),
        ("explain", ("explanation", "topic_concept_id")),
    ],
)
def test_action_variants_reject_each_missing_completeness_component(
    action_id: str, missing_path: tuple[str | int, ...]
) -> None:
    payload = deepcopy(_payload(action_id))
    target: Any = payload
    for part in missing_path[:-1]:
        target = target[part]
    del target[missing_path[-1]]

    with pytest.raises(ValidationError):
        _validate(payload)


def test_resolved_contract_rejects_extra_fields_and_is_frozen() -> None:
    payload = _payload("lookup")
    payload["invented"] = True
    with pytest.raises(ValidationError):
        _validate(payload)

    contract = _validate(_payload("lookup"))
    with pytest.raises(ValidationError):
        contract.frame_id = "changed"


def test_unassessed_candidate_cannot_masquerade_as_resolved() -> None:
    payload = _payload("screen")
    for key in ("axis_readiness", "contract_readiness", "plan_readiness"):
        payload.pop(key)

    candidate = CANDIDATE_ADAPTER.validate_json(json.dumps(payload))
    assert not hasattr(candidate, "axis_readiness")
    with pytest.raises(ValidationError):
        RESOLVED_ADAPTER.validate_json(json.dumps(payload))

    payload["axis_readiness"] = {"readiness": "complete", "reason_codes": []}
    with pytest.raises(ValidationError):
        CANDIDATE_ADAPTER.validate_json(json.dumps(payload))


def test_scope_projection_and_provenance_ids_are_unique() -> None:
    mutations = []
    scope = _payload("lookup")
    scope["scope"]["product_family_ids"] = ["public_fund", "public_fund"]
    mutations.append(scope)
    projection = _payload("lookup")
    projection["projections"]["field_concept_ids"] = ["fee_rate", "fee_rate"]
    mutations.append(projection)
    provenance = _payload("lookup")
    provenance["provenance"] *= 2
    mutations.append(provenance)

    for payload in mutations:
        with pytest.raises(ValidationError):
            _validate(payload)


def test_predicate_depth_is_at_most_three() -> None:
    atom = _payload("screen")["predicate"]
    valid = _payload("screen")
    valid["predicate"] = {
        "node_type": "all_of",
        "children": [{"node_type": "not", "child": atom}],
    }
    _validate(valid)

    invalid = _payload("screen")
    invalid["predicate"] = {
        "node_type": "all_of",
        "children": [
            {
                "node_type": "any_of",
                "children": [{"node_type": "not", "child": atom}],
            }
        ],
    }
    with pytest.raises(ValidationError, match="PREDICATE_DEPTH_EXCEEDED"):
        _validate(invalid)


def test_predicate_atom_count_is_at_most_eight() -> None:
    atom = _payload("screen")["predicate"]
    payload = _payload("screen")
    payload["predicate"] = {"node_type": "all_of", "children": [atom] * 9}

    with pytest.raises(ValidationError, match="PREDICATE_ATOM_LIMIT_EXCEEDED"):
        _validate(payload)


def test_bounded_projection_order_limit_and_frame_count() -> None:
    too_many_projections = _payload("lookup")
    too_many_projections["projections"]["field_concept_ids"] = [f"field-{i}" for i in range(9)]
    too_many_order_terms = _payload("rank")
    too_many_order_terms["ordering"] *= 5
    bad_limit = _payload("rank")
    bad_limit["limit"] = 101
    for payload in (too_many_projections, too_many_order_terms, bad_limit):
        with pytest.raises(ValidationError):
            _validate(payload)

    contract = _validate(_payload("lookup"))
    ResolvedQueryContractBundleV2(
        contracts=tuple(
            contract.model_copy(update={"frame_id": f"f-{i}"}) for i in range(16)
        )
    )
    with pytest.raises(ValidationError):
        ResolvedQueryContractBundleV2(
            contracts=tuple(
                contract.model_copy(update={"frame_id": f"f-{i}"})
                for i in range(17)
            )
        )


def test_predicate_operators_enforce_value_arity() -> None:
    missing = _payload("screen")
    missing["predicate"]["value"] = None
    zero_arity = _payload("screen")
    zero_arity["predicate"].update(operator_id="is_missing", value=None)
    between = _payload("screen")
    between["predicate"].update(
        operator_id="between",
        value=None,
        values=[
            {"kind": "decimal", "decimal": "0", "unit_id": "percent"},
            {"kind": "decimal", "decimal": "1", "unit_id": "percent"},
        ],
    )

    with pytest.raises(ValidationError):
        _validate(missing)
    _validate(zero_arity)
    _validate(between)


def test_predicate_operators_reject_incompatible_or_mixed_value_kinds() -> None:
    ordered_text = _payload("screen")
    ordered_text["predicate"].update(
        operator_id="lte",
        value={"kind": "string", "string": "one"},
    )
    mixed_between = _payload("screen")
    mixed_between["predicate"].update(
        operator_id="between",
        value=None,
        values=[
            {"kind": "decimal", "decimal": "0", "unit_id": "percent"},
            {"kind": "integer", "integer": 1, "unit_id": "percent"},
        ],
    )

    for payload in (ordered_text, mixed_between):
        with pytest.raises(ValidationError):
            _validate(payload)


def test_rank_accepts_only_named_direction_and_limit_defaults() -> None:
    payload = _payload("rank")
    payload["ordering"][0].update(
        direction=None,
        direction_policy_id="default-direction-descending.v1",
    )
    payload.update(limit=None, limit_policy_id="default-limit-5.v1")

    _validate(payload)

    payload["ordering"][0]["direction_policy_id"] = None
    with pytest.raises(ValidationError):
        _validate(payload)


def test_canonical_serialization_retains_percent_semantics() -> None:
    first = _validate(_payload("screen"))
    reordered = dict(reversed(list(_payload("screen").items())))
    second = _validate(reordered)

    assert isinstance(first, ScreenQueryContractV2)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    predicate = json.loads(canonical_json_bytes(first))["predicate"]
    assert predicate["value"] == {
        "boolean": None,
        "date": None,
        "datetime": None,
        "decimal": "1",
        "identifier": None,
        "integer": None,
        "kind": "decimal",
        "string": None,
        "unit_id": "percent",
    }


def test_percent_value_constructor_preserves_the_semantic_unit() -> None:
    value = TypedSemanticValue(kind="decimal", decimal="1", unit_id="percent")

    assert value.model_dump(mode="json")["decimal"] == "1"
    assert value.unit_id == "percent"


def test_readiness_values_are_closed() -> None:
    contract = _validate(_payload("lookup"))
    assert isinstance(contract, LookupQueryContractV2)
    assert contract.axis_readiness.readiness is AxisReadiness.COMPLETE

    payload = _payload("lookup")
    payload["axis_readiness"]["readiness"] = "invented"
    with pytest.raises(ValidationError):
        _validate(payload)


def _aggregate_payload(
    variant_id: str,
    result_shape: str,
    *,
    group_by: list[str] | None = None,
    bucket_policy_id: str | None = None,
) -> dict[str, Any]:
    payload = _payload("aggregate")
    payload["contract_variant_id"] = variant_id
    payload["result_shape"] = result_shape
    payload["aggregation"].update(
        function_id="distribution" if result_shape == "distribution" else "sum",
        group_by_field_concept_ids=group_by or [],
        bucket_policy_id=bucket_policy_id,
    )
    return payload


def test_distribution_rejects_unregistered_bucket_policy() -> None:
    payload = _aggregate_payload(
        "aggregate.distribution.v2",
        "distribution",
        bucket_policy_id="invented.v1",
    )

    with pytest.raises(ValidationError):
        _validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        _aggregate_payload(
            "aggregate.scalar.v2",
            "single_value",
            group_by=["currency"],
        ),
        _aggregate_payload(
            "aggregate.scalar.v2",
            "single_value",
            bucket_policy_id="equal-width-10.v1",
        ),
        _aggregate_payload(
            "aggregate.grouped.v2",
            "grouped_table",
            group_by=["currency"],
            bucket_policy_id="equal-width-10.v1",
        ),
        _aggregate_payload(
            "aggregate.distribution.v2",
            "distribution",
            group_by=["currency"],
            bucket_policy_id="equal-width-10.v1",
        ),
    ],
)
def test_aggregate_variants_reject_contradictory_fields(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _validate(payload)


def test_distribution_requires_exactly_grouping_or_registered_bucket_policy() -> None:
    grouped = _aggregate_payload(
        "aggregate.distribution.v2",
        "distribution",
        group_by=["currency"],
    )
    bucketed = _aggregate_payload(
        "aggregate.distribution.v2",
        "distribution",
        bucket_policy_id="equal-width-10.v1",
    )

    _validate(grouped)
    _validate(bucketed)
