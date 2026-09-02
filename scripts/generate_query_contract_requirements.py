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

CORE_STAGE_ACTIONS = {
    "lookup": ("lookup",),
    "filter": ("screen",),
    "rank": ("rank",),
    "calculate": ("calculate",),
    "aggregate": ("aggregate",),
    "compare": ("compare",),
    "compare_and_rank": ("compare", "rank"),
    "relationship_filter_and_rank": ("screen", "rank"),
    "relationship_lookup_and_rank": ("lookup", "rank"),
    "relationship_similarity": ("similar", "explain"),
    "relationship_aggregate_filter_and_rank": ("screen", "aggregate", "rank"),
    "family_specific_similarity": ("similar", "explain"),
    "relationship_lookup_and_compare": ("lookup", "compare"),
    "relationship_rank_and_expand": ("rank", "lookup"),
    "compare_then_followup": ("compare", "lookup"),
    "cross_family_dependent_lookup": ("rank", "rank"),
    "lookup_and_similarity": ("lookup", "similar"),
    "similarity_search": ("similar",),
    "forecast_and_recommend": ("rank",),
    "personalized_recommendation": ("rank",),
    "real_time_lookup": ("lookup",),
    "order_execution": ("lookup",),
    "document_grounded_product_explanation": ("explain",),
    "multi_hop_holding_filter": ("screen",),
    "temporal_relationship_search": ("lookup",),
    "relationship_filter_rank_then_document_explanation": ("screen", "rank", "explain"),
    "invalid_ontology_value_lookup": ("lookup",),
    "unsupported_entity_relationship_search": ("lookup",),
    "absent_exact_product_lookup": ("lookup",),
}

CORE_CASE_STAGE_ACTIONS = {
    "CALC-DETF-001": ("calculate", "compare"),
    "REL-MGR-001": ("rank", "similar"),
    "CTX-DETF-001": ("rank", "lookup"),
    "CTX-DETF-002": ("rank", "screen"),
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
    source_actions = {
        *(('core', _expect_string(case, 'id'), 0, _core_stage_actions(case)[0]) for case in core),
        *(('heldout', case_id, ordinal, _expect_list(frame, 'action_ids')[0]) for case_id, ordinal, frame in frames),
    }
    adjudications = _load_adjudications(root, source_actions)
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
    source_actions: set[tuple[str, str, int, str]],
) -> dict[tuple[str, str, int], dict[str, Any]]:
    payload = _load_json(root / ADJUDICATIONS_PATH)
    entries = _expect_list(payload, "adjudications")
    actions_by_key = {
        (source, case_id, ordinal): action
        for source, case_id, ordinal, action in source_actions
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
        if key not in actions_by_key or key in result:
            raise ValueError("invalid query contract adjudication key")
        if original not in ACTION_IDS or adjudicated not in ACTION_IDS:
            raise ValueError("unknown query contract action ID")
        if original != actions_by_key[key]:
            raise ValueError("adjudication original action mismatch")
        if status not in {"supported", "unsupported"}:
            raise ValueError("invalid query contract support status")
        if status == "unsupported" and not reason:
            raise ValueError("missing unsupported reason")
        overrides = _expect_mapping(entry, "semantic_overrides")
        _validate_semantic_overrides(adjudicated, status, overrides)
        result[key] = {
            "action_id": adjudicated,
            "support_status": status,
            "reason_code": reason,
            "semantic_overrides": overrides,
        }
    return result


def _core_requirement(case: dict[str, Any], adjudication: dict[str, Any] | None) -> dict[str, Any]:
    case_id = _expect_string(case, "id")
    actions = _core_stage_actions(case)
    requirement = {"source": "core", "case_id": case_id, "frame_ordinal": 0}
    if adjudication is not None:
        return requirement | _adjudicated_body(adjudication)
    if _expect_string(case, "support_level") == "unsupported":
        raise ValueError(f"unsupported core case requires adjudication: {case_id}")
    if len(actions) == 1:
        return requirement | _supported_body(actions[0], {})
    return requirement | {
        "support_status": "supported",
        "semantic_stages": [_supported_body(action, {}) for action in actions],
    }


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


def _core_stage_actions(case: dict[str, Any]) -> tuple[str, ...]:
    case_id = _expect_string(case, "id")
    if case_id in CORE_CASE_STAGE_ACTIONS:
        return CORE_CASE_STAGE_ACTIONS[case_id]
    intent = _expect_string(case, "intent")
    actions = CORE_STAGE_ACTIONS.get(intent)
    if actions is None:
        raise ValueError(f"unmapped core intent: {intent}")
    return actions


def _validate_semantic_overrides(
    action: str, support_status: str, overrides: dict[str, Any]
) -> None:
    if support_status == "unsupported":
        if overrides:
            raise ValueError("unsupported adjudication cannot contain semantic overrides")
        return
    if action == "rank":
        ordering = overrides.get("ordering")
        if set(overrides) != {"ordering"} or not isinstance(ordering, dict):
            raise ValueError("invalid rank semantic overrides")
        if set(ordering) != {"field", "direction", "limit_policy"}:
            raise ValueError("invalid rank semantic overrides")
        if (
            not isinstance(ordering["field"], str)
            or not ordering["field"]
            or ordering["direction"] not in {"asc", "desc"}
            or not isinstance(ordering["limit_policy"], str)
            or not ordering["limit_policy"]
        ):
            raise ValueError("invalid rank semantic overrides")
        return
    if action == "screen":
        predicate = overrides.get("predicate")
        if set(overrides) != {"predicate"} or not isinstance(predicate, dict):
            raise ValueError("invalid screen semantic overrides")
        value = predicate.get("value")
        if (
            set(predicate) != {"field", "operator", "value"}
            or not isinstance(predicate["field"], str)
            or not predicate["field"]
            or predicate["operator"] not in {"eq", "neq", "lt", "lte", "gt", "gte"}
            or not isinstance(value, dict)
            or set(value) != {"kind", "decimal", "unit"}
            or value.get("kind") != "decimal"
            or not isinstance(value.get("decimal"), str)
            or not value["decimal"]
            or not isinstance(value.get("unit"), str)
            or not value["unit"]
        ):
            raise ValueError("invalid screen semantic overrides")
        return
    raise ValueError(f"invalid {action} semantic overrides")


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
