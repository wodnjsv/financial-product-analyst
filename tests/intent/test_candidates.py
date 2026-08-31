from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from financial_agent.contracts import canonical_json_bytes
from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.candidates import generate_semantic_candidates
from financial_agent.intent.catalog import SemanticCatalogSnapshot, load_catalog
from financial_agent.intent.normalization import normalize_request


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def snapshot():
    return load_catalog(PROJECT_ROOT)


@pytest.fixture
def normalized() -> object:
    question = "위험등급과 AUM, 수익률을 비교해줘"
    created_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("q1", question, "dataset-v1", "1.0"),
        run_id="run-1",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q1",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=10),
    )
    return normalize_request(context)


def _items_for(result: object, text: str):
    for group in result.by_mention:
        if group.mention.text == text:
            return group.items
    raise AssertionError(f"candidate mention missing: {text}")


def test_semantic_candidates_are_stable_and_bounded(snapshot, normalized) -> None:
    """Catches nondeterministic ordering or candidate-limit regressions."""
    first = generate_semantic_candidates(normalized, snapshot)
    second = generate_semantic_candidates(normalized, snapshot)

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert all(len(group.items) <= 5 for group in first.by_mention)
    assert first.total_count <= 80


def test_risk_grade_keeps_both_semantic_candidates(snapshot) -> None:
    """Catches collapsing the registered credit/product-risk ambiguity."""
    question = "위험등급"
    created_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("q2", question, "dataset-v1", "1.0"),
        run_id="run-2",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q2",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=10),
    )

    result = generate_semantic_candidates(normalize_request(context), snapshot)

    assert [item.semantic_id for item in _items_for(result, "위험등급")] == [
        "credit_grade",
        "product_risk_grade",
    ]


def test_semantic_candidate_limits_keep_exact_candidates_first() -> None:
    """Catches a global limit dropping exact candidates or six-way mention groups."""
    aliases = {"collision": tuple(f"metric-{index}" for index in range(6))}
    aliases.update(
        {f"item{index:03d}": (f"item-metric-{index}",) for index in range(81)}
    )
    snapshot = SemanticCatalogSnapshot(
        catalog_version="test-v1",
        catalog_hash="a" * 64,
        overlay_version="test-v1",
        overlay_hash="b" * 64,
        product_family_ids=(),
        action_ids=(),
        entity_type_ids=(),
        concepts_by_id={},
        alias_candidates=aliases,
        alias_kinds={alias: "direct" for alias in aliases},
        ontology_hashes={},
    )
    question = " ".join(("collision", *aliases.keys()))
    created_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("q3", question, "dataset-v1", "1.0"),
        run_id="run-3",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q3",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=10),
    )

    result = generate_semantic_candidates(normalize_request(context), snapshot)

    assert len(_items_for(result, "collision")) == 5
    assert result.total_count == 80
    assert all(
        item.match_kind != "trigram"
        for group in result.by_mention
        for item in group.items
    )
