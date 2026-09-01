import json
from pathlib import Path

import pytest

from financial_agent.planning.registry import load_planning_registry


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_registry_is_deterministic_and_references_registered_primitives() -> None:
    """Catches registry order affecting hashes or archetypes naming missing work."""
    first = load_planning_registry(PROJECT_ROOT)
    second = load_planning_registry(PROJECT_ROOT)

    assert first.registry_hash == second.registry_hash
    assert first.registry_version == "query-plan-registry.v1"
    assert "rank-products" in first.primitives_by_id
    assert "rank.single-family.v1" in first.archetypes_by_id


def test_registry_rejects_unknown_primitive_reference(tmp_path: Path) -> None:
    """Catches a Fast archetype that cannot be expanded into registered work."""
    payload = json.loads(
        (PROJECT_ROOT / "config/planning/query-plan-registry.v1.json").read_text()
    )
    payload["archetypes"][0]["primitive_ids"] = ["missing-primitive"]
    config_dir = tmp_path / "config" / "planning"
    config_dir.mkdir(parents=True)
    (config_dir / "query-plan-registry.v1.json").write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="unknown primitive"):
        load_planning_registry(tmp_path)


def test_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    """Catches ambiguous registry lookup silently overwriting an operation."""
    payload = json.loads(
        (PROJECT_ROOT / "config/planning/query-plan-registry.v1.json").read_text()
    )
    payload["primitives"].append(payload["primitives"][0])
    config_dir = tmp_path / "config" / "planning"
    config_dir.mkdir(parents=True)
    (config_dir / "query-plan-registry.v1.json").write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="duplicate primitive"):
        load_planning_registry(tmp_path)


def test_registry_rejects_invalid_result_type_and_incompatible_archetype(
    tmp_path: Path,
) -> None:
    payload = json.loads(
        (PROJECT_ROOT / "config/planning/query-plan-registry.v1.json").read_text()
    )
    payload["primitives"][0]["result_type"] = "invented-result"
    config_dir = tmp_path / "config" / "planning"
    config_dir.mkdir(parents=True)
    path = config_dir / "query-plan-registry.v1.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid planning registry"):
        load_planning_registry(tmp_path)

    payload = json.loads(
        (PROJECT_ROOT / "config/planning/query-plan-registry.v1.json").read_text()
    )
    payload["archetypes"][0]["primitive_ids"] = ["compare-products"]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="action is incompatible"):
        load_planning_registry(tmp_path)
