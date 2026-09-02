"""Generate the evaluation-only semantic query-contract requirement snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tests.evaluation.query_contract.coverage import (  # noqa: E402
    ACTION_IDS,
    CORE_PATH,
    HELDOUT_PATH,
    REQUIREMENTS_PATH,
    _action_frames,
    _expect_cases,
    _expect_int,
    _expect_list,
    _expect_mapping,
    _expect_string,
    _load_json,
    file_sha256,
)


ADJUDICATIONS_PATH = Path(
    "tests/evaluation/query_contract/query_contract_adjudications.v1.json"
)

COMPONENTS = {
    "lookup": ["scope", "projection"],
    "screen": ["scope", "predicate.field", "predicate.operator", "predicate.value"],
    "rank": ["scope", "ordering.field", "ordering.direction", "limit"],
    "compare": ["scope", "comparison.subjects", "comparison.metrics", "comparison.basis"],
    "aggregate": [
        "scope",
        "aggregation.function",
        "aggregation.target",
        "aggregation.population_grain",
        "aggregation.dedup_policy",
    ],
    "calculate": ["scope", "calculation.recipe", "calculation.operands"],
    "similar": ["similarity.anchor", "similarity.policy", "similarity.dimensions", "limit"],
    "explain": ["scope", "explanation.topic_or_profile"],
}

CORE_ACTIONS = {
    "lookup": "lookup",
    "filter": "screen",
    "rank": "rank",
    "calculate": "calculate",
    "aggregate": "aggregate",
    "compare": "compare",
    "compare_and_rank": "rank",
    "relationship_filter_and_rank": "rank",
    "relationship_lookup_and_rank": "rank",
    "relationship_similarity": "similar",
    "relationship_aggregate_filter_and_rank": "aggregate",
    "dependent_multi_step": "rank",
    "family_specific_similarity": "similar",
    "relationship_lookup_and_compare": "compare",
    "relationship_rank_and_expand": "rank",
    "compare_then_followup": "compare",
    "cross_family_dependent_lookup": "rank",
    "lookup_and_similarity": "lookup",
    "similarity_search": "similar",
    "forecast_and_recommend": "rank",
    "personalized_recommendation": "rank",
    "real_time_lookup": "lookup",
    "order_execution": "lookup",
    "document_grounded_product_explanation": "explain",
    "multi_hop_holding_filter": "screen",
    "temporal_relationship_search": "lookup",
    "relationship_filter_rank_then_document_explanation": "rank",
    "invalid_ontology_value_lookup": "lookup",
    "unsupported_entity_relationship_search": "lookup",
    "absent_exact_product_lookup": "lookup",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = _canonical_json(build_snapshot(PROJECT_ROOT))
    target = PROJECT_ROOT / REQUIREMENTS_PATH
    if args.check:
        if not target.exists() or target.read_bytes() != content:
            print("query contract requirement snapshot is stale", file=sys.stderr)
            return 1
        return 0
    target.write_bytes(content)
    return 0


def build_snapshot(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    core = _expect_cases(_load_json(root / CORE_PATH), "id")
    heldout = _expect_cases(_load_json(root / HELDOUT_PATH), "case_id")
    frames = _action_frames(heldout)
    frame_keys = [(case_id, ordinal) for case_id, ordinal, _ in frames]
    if len(frame_keys) != len(set(frame_keys)):
        raise ValueError("duplicate query contract frame key")
    adjudications = _load_adjudications(root, core, frames)
    requirements = [
        _core_requirement(case, adjudications.get(("core", case["id"], 0)))
        for case in core
    ]
    requirements.extend(
        _heldout_requirement(case_id, ordinal, frame, adjudications.get(("heldout", case_id, ordinal)))
        for case_id, ordinal, frame in frames
    )
    return {
        "schema_version": "query-contract-requirements.v1",
        "sources": {
            "core": {"path": str(CORE_PATH), "sha256": file_sha256(root / CORE_PATH)},
            "heldout": {"path": str(HELDOUT_PATH), "sha256": file_sha256(root / HELDOUT_PATH)},
        },
        "counts": {
            "core_questions": len(core),
            "heldout_cases": len(heldout),
            "heldout_frames": len(frames),
        },
        "requirements": requirements,
    }


def _load_adjudications(
    root: Path,
    core: list[dict[str, Any]],
    frames: list[tuple[str, int, dict[str, Any]]],
) -> dict[tuple[str, str, int], dict[str, Any]]:
    payload = _load_json(root / ADJUDICATIONS_PATH)
    entries = _expect_list(payload, "adjudications")
    real_keys = {
        *(('core', _expect_string(case, 'id'), 0) for case in core),
        *(('heldout', case_id, ordinal) for case_id, ordinal, _ in frames),
    }
    result: dict[tuple[str, str, int], dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid query contract adjudication")
        source = _expect_string(entry, "source")
        key = (source, _expect_string(entry, "case_id"), _expect_int(entry, "frame_ordinal"))
        original = _expect_string(entry, "original_action_id")
        adjudicated = _expect_string(entry, "adjudicated_action_id")
        status = _expect_string(entry, "support_status")
        reason = _expect_string(entry, "reason_code")
        if key not in real_keys or key in result:
            raise ValueError("invalid query contract adjudication key")
        if original not in ACTION_IDS or adjudicated not in ACTION_IDS:
            raise ValueError("unknown query contract action ID")
        if status not in {"supported", "unsupported"}:
            raise ValueError("invalid query contract support status")
        if status == "unsupported" and not reason:
            raise ValueError("missing unsupported reason")
        overrides = _expect_mapping(entry, "semantic_overrides")
        result[key] = {
            "action_id": adjudicated,
            "support_status": status,
            "reason_code": reason,
            "semantic_overrides": overrides,
        }
    return result


def _core_requirement(case: dict[str, Any], adjudication: dict[str, Any] | None) -> dict[str, Any]:
    case_id = _expect_string(case, "id")
    action = CORE_ACTIONS.get(_expect_string(case, "intent"))
    if action is None:
        raise ValueError(f"unmapped core intent: {case['intent']}")
    requirement = {"source": "core", "case_id": case_id, "frame_ordinal": 0}
    if adjudication is not None:
        return requirement | _adjudicated_body(adjudication)
    if _expect_string(case, "support_level") == "unsupported":
        raise ValueError(f"unsupported core case requires adjudication: {case_id}")
    return requirement | _supported_body(action, {})


def _heldout_requirement(
    case_id: str,
    ordinal: int,
    frame: dict[str, Any],
    adjudication: dict[str, Any] | None,
) -> dict[str, Any]:
    requirement = {"source": "heldout", "case_id": case_id, "frame_ordinal": ordinal}
    coverage = _expect_mapping(frame, "semantic_coverage")
    coverage_state = _expect_string(coverage, "state")
    if coverage_state != "covered":
        if adjudication is None or adjudication["support_status"] != "unsupported":
            raise ValueError(f"unsupported held-out frame requires adjudication: {case_id}:{ordinal}")
        if adjudication["reason_code"] != _expect_string(coverage, "reason").upper():
            raise ValueError(f"held-out unsupported reason mismatch: {case_id}:{ordinal}")
    if adjudication is not None:
        return requirement | _adjudicated_body(adjudication)
    action = _expect_list(frame, "action_ids")[0]
    values = {
        _expect_string(slot, "slot_kind"): _expect_list(slot, "value_ids")
        for slot in _expect_list(frame, "slots")
        if isinstance(slot, dict)
    }
    return requirement | _supported_body(action, {"source_slot_values": values})


def _adjudicated_body(adjudication: dict[str, Any]) -> dict[str, Any]:
    if adjudication["support_status"] == "unsupported":
        return {"support_status": "unsupported", "reason_code": adjudication["reason_code"]}
    return _supported_body(
        adjudication["action_id"], {"semantic_overrides": adjudication["semantic_overrides"]}
    )


def _supported_body(action: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "support_status": "supported",
        "action_id": action,
        "required_components": COMPONENTS[action],
        **details,
    }


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
