from __future__ import annotations

from pathlib import Path

import json

import pytest

from tests.evaluation.query_contract.coverage import (
    CORE_PATH,
    HELDOUT_PATH,
    CoverageCount,
    audit_v1_representability,
    file_sha256,
    load_requirement_snapshot,
)
from scripts.generate_query_contract_requirements import build_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_requirement_snapshot_is_pinned_to_current_sources() -> None:
    snapshot = load_requirement_snapshot(PROJECT_ROOT)

    assert snapshot.core_question_count == 52
    assert snapshot.heldout_case_count == 160
    assert snapshot.heldout_frame_count == 209
    assert snapshot.core_source_hash == file_sha256(PROJECT_ROOT / CORE_PATH)
    assert snapshot.heldout_source_hash == file_sha256(PROJECT_ROOT / HELDOUT_PATH)


def test_v1_representability_baseline_is_frozen_before_contract_replacement() -> None:
    report = audit_v1_representability(PROJECT_ROOT)

    assert report.total_frames == 209
    assert report.representable_frames == 94
    assert report.by_action["lookup"] == CoverageCount(5, 58)
    assert report.by_action["screen"] == CoverageCount(0, 23)
    assert report.by_action["rank"] == CoverageCount(43, 66)
    assert report.by_action["compare"] == CoverageCount(17, 30)
    assert report.by_action["aggregate"] == CoverageCount(8, 11)
    assert report.by_action["calculate"] == CoverageCount(5, 5)
    assert report.by_action["similar"] == CoverageCount(10, 10)
    assert report.by_action["explain"] == CoverageCount(6, 6)


def test_snapshot_captures_fee_semantic_adjudications() -> None:
    payload = json.loads(
        (PROJECT_ROOT / "tests/evaluation/query_contract/query_contract_requirements.v1.json").read_text(
            encoding="utf-8"
        )
    )
    requirements = {
        (item["source"], item["case_id"], item["frame_ordinal"]): item
        for item in payload["requirements"]
    }

    qualitative = requirements[("heldout", "HKO-PAR-011", 0)]
    assert qualitative["action_id"] == "rank"
    assert qualitative["semantic_overrides"]["ordering"] == {
        "field": "fee_rate",
        "direction": "asc",
        "limit_policy": "default-limit-5.v1",
    }
    threshold = requirements[("core", "FLT-OETF-001", 0)]
    assert threshold["action_id"] == "screen"
    assert threshold["semantic_overrides"]["predicate"] == {
        "field": "fee_rate",
        "operator": "lte",
        "value": {"kind": "decimal", "decimal": "0.5", "unit": "percent"},
    }


def test_partial_heldout_frames_have_explicit_unsupported_reasons() -> None:
    snapshot = json.loads(
        (PROJECT_ROOT / "tests/evaluation/query_contract/query_contract_requirements.v1.json").read_text(
            encoding="utf-8"
        )
    )
    requirements = {
        (item["source"], item["case_id"], item["frame_ordinal"]): item
        for item in snapshot["requirements"]
    }
    heldout = json.loads((PROJECT_ROOT / HELDOUT_PATH).read_text(encoding="utf-8"))

    partial_frames = [
        (case["case_id"], frame["ordinal"], frame["semantic_coverage"]["reason"])
        for case in heldout["cases"]
        for frame in case["expected_frames"]
        if frame["semantic_coverage"]["state"] == "partial"
    ]
    assert partial_frames
    for case_id, ordinal, reason in partial_frames:
        requirement = requirements[("heldout", case_id, ordinal)]
        assert requirement == {
            "source": "heldout",
            "case_id": case_id,
            "frame_ordinal": ordinal,
            "support_status": "unsupported",
            "reason_code": reason.upper(),
        }


def test_snapshot_preserves_every_composite_core_semantic_stage() -> None:
    snapshot = json.loads(
        (PROJECT_ROOT / "tests/evaluation/query_contract/query_contract_requirements.v1.json").read_text(
            encoding="utf-8"
        )
    )
    requirements = {
        item["case_id"]: item
        for item in snapshot["requirements"]
        if item["source"] == "core"
    }

    expected_stages = {
        "CMP-AUM-001": ["compare", "rank"],
        "CALC-DETF-001": ["calculate", "compare"],
        "MIS-BOND-001": ["lookup", "similar"],
        "REL-CORP-001": ["screen", "rank", "explain"],
    }
    for case_id, action_ids in expected_stages.items():
        assert [stage["action_id"] for stage in requirements[case_id]["semantic_stages"]] == action_ids


@pytest.mark.parametrize(
    ("adjudications", "heldout", "match"),
    [
        (
            [],
            {
                "cases": [
                    {
                        "case_id": "HKO-001",
                        "expected_frames": [
                            {"ordinal": 0, "action_ids": ["rank"], "slots": []},
                            {"ordinal": 0, "action_ids": ["rank"], "slots": []},
                        ],
                    }
                ]
            },
            "duplicate query contract frame key",
        ),
        (
            [
                {
                    "source": "heldout",
                    "case_id": "HKO-001",
                    "frame_ordinal": 0,
                    "original_action_id": "unknown",
                    "adjudicated_action_id": "rank",
                    "support_status": "supported",
                    "reason_code": "REVIEWED",
                    "semantic_overrides": {},
                }
            ],
            None,
            "unknown query contract action ID",
        ),
        (
            [
                {
                    "source": "heldout",
                    "case_id": "HKO-001",
                    "frame_ordinal": 0,
                    "original_action_id": "rank",
                    "adjudicated_action_id": "rank",
                    "support_status": "unsupported",
                    "reason_code": "",
                    "semantic_overrides": {},
                }
            ],
            None,
            "expected non-empty string: reason_code",
        ),
        (
            [
                {
                    "source": "heldout",
                    "case_id": "HKO-MISSING",
                    "frame_ordinal": 0,
                    "original_action_id": "rank",
                    "adjudicated_action_id": "rank",
                    "support_status": "supported",
                    "reason_code": "REVIEWED",
                    "semantic_overrides": {},
                }
            ],
            None,
            "invalid query contract adjudication key",
        ),
        (
            [],
            {
                "cases": [
                    {
                        "case_id": "HKO-001",
                        "expected_frames": [
                            {"ordinal": 0, "action_ids": ["unknown"], "slots": []}
                        ],
                    }
                ]
            },
            "unknown held-out action ID",
        ),
        (
            [],
            {
                "cases": [
                    {
                        "case_id": "HKO-001",
                        "expected_frames": [
                            {
                                "ordinal": 0,
                                "action_ids": ["rank", "compare"],
                                "slots": [],
                            }
                        ],
                    }
                ]
            },
            "expected exactly one held-out action ID",
        ),
    ],
)
def test_generator_rejects_invalid_adjudication_or_frame_keys(
    tmp_path: Path,
    adjudications: list[dict[str, object]],
    heldout: dict[str, object] | None,
    match: str,
) -> None:
    core_path = tmp_path / "tests/gold/core_questions.json"
    heldout_path = tmp_path / "tests/evaluation/intent/intent_resolution_heldout_ko_v3.json"
    adjudications_path = (
        tmp_path / "tests/evaluation/query_contract/query_contract_adjudications.v1.json"
    )
    core_path.parent.mkdir(parents=True)
    heldout_path.parent.mkdir(parents=True)
    adjudications_path.parent.mkdir(parents=True)
    core_path.write_text(json.dumps({"cases": []}), encoding="utf-8")
    heldout_path.write_text(
        json.dumps(
            heldout
            or {
                "cases": [
                    {
                        "case_id": "HKO-001",
                        "expected_frames": [
                            {"ordinal": 0, "action_ids": ["rank"], "slots": []}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    adjudications_path.write_text(
        json.dumps({"adjudications": adjudications}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match=match):
        build_snapshot(tmp_path)


@pytest.mark.parametrize(
    ("core", "heldout", "adjudication", "match"),
    [
        (
            {"cases": []},
            {
                "cases": [
                    {
                        "case_id": "HKO-001",
                        "expected_frames": [
                            {
                                "ordinal": 0,
                                "action_ids": ["rank"],
                                "slots": [],
                                "semantic_coverage": {"state": "covered", "reason": "none"},
                            }
                        ],
                    }
                ]
            },
            {
                "source": "heldout",
                "case_id": "HKO-001",
                "frame_ordinal": 0,
                "original_action_id": "screen",
                "adjudicated_action_id": "rank",
                "support_status": "supported",
                "reason_code": "REVIEWED",
                "semantic_overrides": {
                    "ordering": {
                        "field": "fee_rate",
                        "direction": "asc",
                        "limit_policy": "default-limit-5.v1",
                    }
                },
            },
            "adjudication original action mismatch",
        ),
        (
            {"cases": []},
            {
                "cases": [
                    {
                        "case_id": "HKO-001",
                        "expected_frames": [
                            {
                                "ordinal": 0,
                                "action_ids": ["rank"],
                                "slots": [],
                                "semantic_coverage": {"state": "covered", "reason": "none"},
                            }
                        ],
                    }
                ]
            },
            {
                "source": "heldout",
                "case_id": "HKO-001",
                "frame_ordinal": 0,
                "original_action_id": "rank",
                "adjudicated_action_id": "rank",
                "support_status": "supported",
                "reason_code": "REVIEWED",
                "semantic_overrides": {"predicate": {"field": "fee_rate"}},
            },
            "invalid rank semantic overrides",
        ),
        (
            {
                "cases": [
                    {"id": "CORE-001", "intent": "lookup", "support_level": "supported"}
                ]
            },
            {"cases": []},
            {
                "source": "core",
                "case_id": "CORE-001",
                "frame_ordinal": 0,
                "original_action_id": "rank",
                "adjudicated_action_id": "rank",
                "support_status": "supported",
                "reason_code": "REVIEWED",
                "semantic_overrides": {
                    "ordering": {
                        "field": "fee_rate",
                        "direction": "asc",
                        "limit_policy": "default-limit-5.v1",
                    }
                },
            },
            "adjudication original action mismatch",
        ),
    ],
)
def test_generator_rejects_stale_adjudication_semantics(
    tmp_path: Path,
    core: dict[str, object],
    heldout: dict[str, object],
    adjudication: dict[str, object],
    match: str,
) -> None:
    core_path = tmp_path / "tests/gold/core_questions.json"
    heldout_path = tmp_path / "tests/evaluation/intent/intent_resolution_heldout_ko_v3.json"
    adjudications_path = (
        tmp_path / "tests/evaluation/query_contract/query_contract_adjudications.v1.json"
    )
    core_path.parent.mkdir(parents=True)
    heldout_path.parent.mkdir(parents=True)
    adjudications_path.parent.mkdir(parents=True)
    core_path.write_text(json.dumps(core), encoding="utf-8")
    heldout_path.write_text(json.dumps(heldout), encoding="utf-8")
    adjudications_path.write_text(
        json.dumps({"adjudications": [adjudication]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match=match):
        build_snapshot(tmp_path)
