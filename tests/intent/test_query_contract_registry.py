from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from financial_agent.contracts.enums import IntentType
from financial_agent.intent.query_contract_registry import (
    CONTRACT_VARIANT_ORDER,
    OPERATOR_ORDER,
    assess_requirement_representability,
    find_representing_variant,
    load_query_contract_registry,
)
from financial_agent.intent.task_contracts import load_task_contract_registry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATHS = (
    Path("config/intent/query-contract-registry.v2.json"),
    Path("config/intent/query-operator-registry.v1.json"),
    Path("config/intent/query-policy-registry.v1.json"),
)


def test_closed_registries_have_canonical_order_and_deterministic_hash_pins() -> None:
    first = load_query_contract_registry(PROJECT_ROOT)
    second = load_query_contract_registry(PROJECT_ROOT)

    assert tuple(first.variants_by_id) == CONTRACT_VARIANT_ORDER
    assert tuple(first.operators_by_id) == OPERATOR_ORDER
    assert tuple(first.policies_by_id) == tuple(sorted(first.policies_by_id))
    assert first.contract_registry_hash == second.contract_registry_hash
    assert first.operator_registry_hash == second.operator_registry_hash
    assert first.policy_registry_hash == second.policy_registry_hash
    assert first.pinned_operator_registry_hash == first.operator_registry_hash
    assert first.pinned_policy_registry_hash == first.policy_registry_hash
    assert all(len(value) == 64 for value in (
        first.contract_registry_hash,
        first.operator_registry_hash,
        first.policy_registry_hash,
    ))


def test_registry_has_exact_variants_operators_and_actions() -> None:
    registry = load_query_contract_registry(PROJECT_ROOT)

    assert CONTRACT_VARIANT_ORDER == (
        "lookup.projection.v2",
        "screen.predicate.v2",
        "rank.ordering.v2",
        "compare.subjects.v2",
        "aggregate.scalar.v2",
        "aggregate.grouped.v2",
        "aggregate.distribution.v2",
        "calculate.recipe.v2",
        "similar.policy.v2",
        "explain.topic.v2",
    )
    assert OPERATOR_ORDER == (
        "eq", "neq", "lt", "lte", "gt", "gte", "between", "in", "not_in",
        "contains", "is_missing", "is_present",
    )
    assert {variant.action_id for variant in registry.variants_by_id.values()} == set(IntentType)


def _copy_registries(tmp_path: Path) -> Path:
    for relative in REGISTRY_PATHS:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((PROJECT_ROOT / relative).read_bytes())
    return tmp_path


def _mutate(tmp_path: Path, relative: Path, mutate) -> Path:
    root = _copy_registries(tmp_path)
    path = root / relative
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return root


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _repin(root: Path) -> None:
    contracts_path = root / REGISTRY_PATHS[0]
    contracts = json.loads(contracts_path.read_text(encoding="utf-8"))
    for relative, hash_key, version_key in (
        (REGISTRY_PATHS[1], "operator_registry_hash", "operator_registry_version"),
        (REGISTRY_PATHS[2], "policy_registry_hash", "policy_registry_version"),
    ):
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
        contracts[hash_key] = _canonical_hash(payload)
        contracts[version_key] = payload["registry_version"]
    contracts_path.write_text(
        json.dumps(contracts, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _mutate_and_repin(tmp_path: Path, relative: Path, mutate) -> Path:
    root = _mutate(tmp_path, relative, mutate)
    _repin(root)
    return root


@pytest.mark.parametrize(
    ("relative", "mutate"),
    [
        (
            REGISTRY_PATHS[0],
            lambda payload: payload["variants"].append(payload["variants"][0]),
        ),
        (
            REGISTRY_PATHS[1],
            lambda payload: payload["operators"].append(payload["operators"][0]),
        ),
        (
            REGISTRY_PATHS[2],
            lambda payload: payload["policies"].append(payload["policies"][0]),
        ),
    ],
)
def test_registry_rejects_duplicate_ids(tmp_path: Path, relative: Path, mutate) -> None:
    with pytest.raises(ValueError, match="invalid query contract registry"):
        load_query_contract_registry(_mutate(tmp_path, relative, mutate))


def test_registry_rejects_unknown_cross_references(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["variants"][1]["policy_ids"].append("invented.v1")

    with pytest.raises(ValueError, match="unknown policy reference"):
        load_query_contract_registry(_mutate(tmp_path, REGISTRY_PATHS[0], mutate))


@pytest.mark.parametrize(
    ("relative", "mutate"),
    [
        (
            REGISTRY_PATHS[0],
            lambda payload: payload.update(
                registry_version="query-contract-registry.v999"
            ),
        ),
        (
            REGISTRY_PATHS[1],
            lambda payload: payload.update(
                registry_version="query-operator-registry.v999"
            ),
        ),
        (
            REGISTRY_PATHS[2],
            lambda payload: payload.update(
                registry_version="query-policy-registry.v999"
            ),
        ),
    ],
)
def test_registry_rejects_redefined_versions_even_when_repinned(
    tmp_path: Path, relative: Path, mutate
) -> None:
    with pytest.raises(ValueError, match="unsupported query registry version"):
        load_query_contract_registry(
            _mutate_and_repin(tmp_path, relative, mutate)
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["operators"][3].update(arity="zero"),
        lambda payload: payload["operators"][3]["allowed_value_kinds"].append(
            "decimal"
        ),
        lambda payload: payload["operators"][3]["allowed_value_kinds"].reverse(),
    ],
)
def test_registry_rejects_redefined_operator_matrix_when_repinned(
    tmp_path: Path, mutate
) -> None:
    with pytest.raises(ValueError, match="operator registry definition mismatch"):
        load_query_contract_registry(
            _mutate_and_repin(tmp_path, REGISTRY_PATHS[1], mutate)
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["policies"][0].update(kind="coverage"),
        lambda payload: payload["policies"].append(
            {"id": "zzz-invented.v1", "kind": "default"}
        ),
    ],
)
def test_registry_rejects_redefined_policy_set_when_repinned(
    tmp_path: Path, mutate
) -> None:
    with pytest.raises(ValueError, match="policy registry definition mismatch"):
        load_query_contract_registry(
            _mutate_and_repin(tmp_path, REGISTRY_PATHS[2], mutate)
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["variants"][0]["required_components"].append(
            "invented.component"
        ),
        lambda payload: payload["variants"][0].update(action_id="screen"),
    ],
)
def test_registry_rejects_redefined_variant_schema(
    tmp_path: Path, mutate
) -> None:
    with pytest.raises(ValueError, match="contract variant definition mismatch"):
        load_query_contract_registry(
            _mutate(tmp_path, REGISTRY_PATHS[0], mutate)
        )


@pytest.mark.parametrize(
    "relative,key",
    [
        (REGISTRY_PATHS[0], "variants"),
        (REGISTRY_PATHS[1], "operators"),
        (REGISTRY_PATHS[2], "policies"),
    ],
)
def test_registry_rejects_noncanonical_order(tmp_path: Path, relative: Path, key: str) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload[key][0], payload[key][1] = payload[key][1], payload[key][0]

    with pytest.raises(ValueError, match="non-canonical registry order"):
        load_query_contract_registry(_mutate(tmp_path, relative, mutate))


def test_every_supported_requirement_vector_is_v2_representable() -> None:
    registry = load_query_contract_registry(PROJECT_ROOT)
    snapshot = json.loads(
        (
            PROJECT_ROOT
            / "tests/evaluation/query_contract/query_contract_requirements.v1.json"
        ).read_text(encoding="utf-8")
    )
    supported: list[tuple[str, tuple[str, ...]]] = []
    for requirement in snapshot["requirements"]:
        if requirement["support_status"] == "unsupported":
            continue
        if "action_id" in requirement:
            supported.append((requirement["action_id"], tuple(requirement["required_components"])))
        supported.extend(
            (stage["action_id"], tuple(stage["required_components"]))
            for stage in requirement.get("semantic_stages", [])
        )

    assert supported
    assert all(
        find_representing_variant(registry, action, components) is not None
        for action, components in supported
    )


def test_every_unsupported_requirement_retains_its_adjudicated_reason() -> None:
    registry = load_query_contract_registry(PROJECT_ROOT)
    requirements = json.loads(
        (
            PROJECT_ROOT
            / "tests/evaluation/query_contract/query_contract_requirements.v1.json"
        ).read_text(encoding="utf-8")
    )["requirements"]
    adjudications = json.loads(
        (
            PROJECT_ROOT
            / "tests/evaluation/query_contract/query_contract_adjudications.v1.json"
        ).read_text(encoding="utf-8")
    )["adjudications"]
    adjudication_by_key = {
        (item["source"], item["case_id"], item["frame_ordinal"]): item
        for item in adjudications
    }
    unsupported = [
        requirement
        for requirement in requirements
        if requirement["support_status"] == "unsupported"
    ]

    assert unsupported
    for requirement in unsupported:
        key = (
            requirement["source"],
            requirement["case_id"],
            requirement["frame_ordinal"],
        )
        adjudication = adjudication_by_key[key]
        assessment = assess_requirement_representability(
            registry,
            action_id=adjudication["adjudicated_action_id"],
            components=tuple(requirement.get("required_components", ())),
            nonrepresentable_reason=requirement["reason_code"],
        )

        assert adjudication["support_status"] == "unsupported"
        assert requirement["reason_code"] == adjudication["reason_code"]
        assert assessment.variant_id is None
        assert assessment.reason_code == adjudication["reason_code"]
        assert assessment.structural_variant_id is not None


def test_registry_declares_the_action_specific_completeness_table() -> None:
    registry = load_query_contract_registry(PROJECT_ROOT)

    assert registry.variants_by_id["screen.predicate.v2"].required_components == (
        "scope", "predicate.field", "predicate.operator", "predicate.value",
    )
    assert registry.variants_by_id["aggregate.scalar.v2"].required_components == (
        "scope", "aggregation.function", "aggregation.target",
        "aggregation.population_grain", "aggregation.dedup_policy",
    )
    assert registry.variants_by_id["similar.policy.v2"].required_components == (
        "scope", "similarity.anchor", "similarity.policy", "similarity.dimensions",
        "similarity.coverage_threshold", "limit",
    )


def test_v1_registry_bytes_hash_and_contract_hash_do_not_drift() -> None:
    v1_path = PROJECT_ROOT / "config/intent/task-input-contracts.v1.json"

    assert hashlib.sha256(v1_path.read_bytes()).hexdigest() == (
        "da5ec31d2f1a59d0ce343e51acb214deb8cd536b6aceeeacbd021d9dcf9f95fe"
    )
    assert load_task_contract_registry(PROJECT_ROOT).registry_hash == (
        "ad3f7629ace7278fa55651ab2fa2d53e2ba8b5ea7c00f917de4549186c3de99b"
    )
