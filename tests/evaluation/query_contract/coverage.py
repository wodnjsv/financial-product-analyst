"""Reproducible, evaluation-only semantic contract coverage audit."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CORE_PATH = Path("tests/gold/core_questions.json")
HELDOUT_PATH = Path("tests/evaluation/intent/intent_resolution_heldout_ko_v3.json")
REQUIREMENTS_PATH = Path(
    "tests/evaluation/query_contract/query_contract_requirements.v1.json"
)
V1_CONTRACTS_PATH = Path("config/intent/task-input-contracts.v1.json")
ACTION_IDS = (
    "lookup",
    "screen",
    "rank",
    "compare",
    "aggregate",
    "calculate",
    "similar",
    "explain",
)


@dataclass(frozen=True, slots=True)
class CoverageCount:
    representable: int
    total: int


@dataclass(frozen=True, slots=True)
class V1CoverageReport:
    total_frames: int
    representable_frames: int
    by_action: dict[str, CoverageCount]


@dataclass(frozen=True, slots=True)
class RequirementSnapshot:
    core_question_count: int
    heldout_case_count: int
    heldout_frame_count: int
    core_source_hash: str
    heldout_source_hash: str


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_requirement_snapshot(project_root: Path) -> RequirementSnapshot:
    root = project_root.resolve()
    payload = _load_json(root / REQUIREMENTS_PATH)
    sources = _expect_mapping(payload, "sources")
    core_pin = _expect_mapping(sources, "core")
    heldout_pin = _expect_mapping(sources, "heldout")
    core_hash = _expect_string(core_pin, "sha256")
    heldout_hash = _expect_string(heldout_pin, "sha256")
    if core_hash != file_sha256(root / CORE_PATH):
        raise ValueError("QUERY_CONTRACT_CORE_SOURCE_STALE")
    if heldout_hash != file_sha256(root / HELDOUT_PATH):
        raise ValueError("QUERY_CONTRACT_HELDOUT_SOURCE_STALE")

    core = _expect_cases(_load_json(root / CORE_PATH), "id")
    heldout = _expect_cases(_load_json(root / HELDOUT_PATH), "case_id")
    frames = tuple(_action_frames(heldout))
    counts = _expect_mapping(payload, "counts")
    if (
        _expect_int(counts, "core_questions") != len(core)
        or _expect_int(counts, "heldout_cases") != len(heldout)
        or _expect_int(counts, "heldout_frames") != len(frames)
    ):
        raise ValueError("QUERY_CONTRACT_SOURCE_COUNT_MISMATCH")

    requirements = _expect_list(payload, "requirements")
    keys = {
        (item.get("source"), item.get("case_id"), item.get("frame_ordinal"))
        for item in requirements
        if isinstance(item, dict)
    }
    expected_keys = {
        *(('core', _expect_string(case, 'id'), 0) for case in core),
        *(('heldout', case_id, ordinal) for case_id, ordinal, _ in frames),
    }
    if len(keys) != len(requirements) or keys != expected_keys:
        raise ValueError("QUERY_CONTRACT_REQUIREMENT_SET_MISMATCH")
    return RequirementSnapshot(
        core_question_count=len(core),
        heldout_case_count=len(heldout),
        heldout_frame_count=len(frames),
        core_source_hash=core_hash,
        heldout_source_hash=heldout_hash,
    )


def audit_v1_representability(project_root: Path) -> V1CoverageReport:
    root = project_root.resolve()
    contracts = _expect_list(_load_json(root / V1_CONTRACTS_PATH), "contracts")
    allowed_by_action: dict[str, set[str]] = {}
    required_by_action: dict[str, set[str]] = {}
    for contract in contracts:
        if not isinstance(contract, dict):
            raise ValueError("invalid task contract registry")
        action = _expect_string(contract, "action_id")
        allowed_by_action[action] = set(_expect_list(contract, "required_slot_kinds")) | set(
            _expect_list(contract, "optional_slot_kinds")
        )
        required_by_action[action] = set(_expect_list(contract, "required_slot_kinds"))
    if set(allowed_by_action) != set(ACTION_IDS):
        raise ValueError("invalid task contract registry")

    heldout = _expect_cases(_load_json(root / HELDOUT_PATH), "case_id")
    totals: Counter[str] = Counter()
    represented: Counter[str] = Counter()
    for _, _, frame in _action_frames(heldout):
        action = frame["action_ids"][0]
        slots = {
            _expect_string(slot, "slot_kind")
            for slot in _expect_list(frame, "slots")
            if isinstance(slot, dict)
        }
        totals[action] += 1
        if required_by_action[action] <= slots and slots <= allowed_by_action[action]:
            represented[action] += 1
    by_action = {
        action: CoverageCount(represented[action], totals[action]) for action in ACTION_IDS
    }
    return V1CoverageReport(
        total_frames=sum(totals.values()),
        representable_frames=sum(represented.values()),
        by_action=by_action,
    )


def _action_frames(cases: list[dict[str, Any]]) -> list[tuple[str, int, dict[str, Any]]]:
    frames: list[tuple[str, int, dict[str, Any]]] = []
    for case in cases:
        case_id = _expect_string(case, "case_id")
        for frame in _expect_list(case, "expected_frames"):
            if not isinstance(frame, dict):
                raise ValueError("invalid held-out frame")
            action_ids = _expect_list(frame, "action_ids")
            if len(action_ids) != 1 or action_ids[0] not in ACTION_IDS:
                continue
            frames.append((case_id, _expect_int(frame, "ordinal"), frame))
    return frames


def _load_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"duplicate JSON key: {key}")
            payload[key] = value
        return payload

    result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(result, dict):
        raise ValueError("JSON root must be an object")
    return result


def _expect_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {key}")
    return value


def _expect_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"expected list: {key}")
    return value


def _expect_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"expected non-empty string: {key}")
    return value


def _expect_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"expected integer: {key}")
    return value


def _expect_cases(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    cases = _expect_list(payload, "cases")
    if any(not isinstance(case, dict) or not _expect_string(case, key) for case in cases):
        raise ValueError("invalid case fixture")
    return cases
