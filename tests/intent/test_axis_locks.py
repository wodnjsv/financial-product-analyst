from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.axis_locks import (
    ExactSemanticLock,
    build_exact_semantic_locks,
    validate_exact_semantic_locks,
)
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.normalization import normalize_request


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _normalized_request(text: str):
    created_at = datetime(2026, 9, 2, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("locks", text, "dataset-v1", "1.0"),
        run_id="run-locks",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="locks",
        question=text,
        segments=(Segment(segment_id="s1", ordinal=0, text=text),),
        deadline_at=created_at + timedelta(seconds=10),
    )
    return normalize_request(context)


@pytest.mark.parametrize("surface", ["공모펀드", "공모 펀드", "공모\u3000펀드"])
def test_exact_public_fund_lock_preserves_original_evidence_for_spacing_variants(
    surface: str,
) -> None:
    """Catches a normalized family match losing its original Korean evidence span."""
    request = _normalized_request(f"{surface} 중 총보수가 1% 이하인 상품")

    locks = build_exact_semantic_locks(request, load_catalog(PROJECT_ROOT))

    family_lock = next(lock for lock in locks if lock.role == "product_family")
    assert family_lock.canonical_id == "public_fund"
    assert family_lock.source == "direct_alias"
    assert family_lock.evidence_span_ids == ("mention-s1-0-" + str(len(surface)),)


def test_exact_field_and_literal_locks_survive_an_hcx_omission() -> None:
    """Catches making exact evidence contingent on a later model selection."""
    request = _normalized_request("공모펀드 중 총보수가 1% 이하인 상품")

    locks = build_exact_semantic_locks(request, load_catalog(PROJECT_ROOT))

    assert {(lock.role, lock.canonical_id) for lock in locks} >= {
        ("product_family", "public_fund"),
        ("field", "fee_rate"),
        ("operator", "lte"),
    }
    assert any(
        lock.role == "literal" and lock.canonical_id.endswith("percentage")
        for lock in locks
    )


@pytest.mark.parametrize("surface", ["순자산", "AUM", "ＡＵＭ"])
def test_unique_direct_field_aliases_become_locks(surface: str) -> None:
    """Catches direct AUM aliases being demoted to model-only candidates."""
    locks = build_exact_semantic_locks(
        _normalized_request(f"{surface} 1% 이상"), load_catalog(PROJECT_ROOT)
    )

    assert ("field", "aum") in {(lock.role, lock.canonical_id) for lock in locks}


def test_group_and_ambiguous_aliases_never_become_locks() -> None:
    """Catches fuzzy or ambiguous language bypassing the deterministic boundary."""
    locks = build_exact_semantic_locks(
        _normalized_request("ETF와 위험등급을 알려줘"), load_catalog(PROJECT_ROOT)
    )

    assert not any(lock.role in {"product_family", "field"} for lock in locks)


@pytest.mark.parametrize("surface", ["보수", "규모", "좋은", "낮은"])
def test_broad_korean_terms_remain_unlocked_candidates(surface: str) -> None:
    """Catches broad adjectives expanding the reviewed direct-alias vocabulary."""
    locks = build_exact_semantic_locks(
        _normalized_request(f"공모펀드 중 {surface} 상품"), load_catalog(PROJECT_ROOT)
    )

    assert not any(lock.role == "field" for lock in locks)


@pytest.mark.parametrize("role", ["product_family", "field", "operator", "literal"])
def test_conflicting_exact_spans_fail_closed(role: str) -> None:
    """Catches contradictory exact evidence being silently ordered or dropped."""
    locks = (
        ExactSemanticLock(
            lock_id=f"lock-{role}-one",
            role=role,
            canonical_id="one",
            evidence_span_ids=("span-1",),
            source="canonical",
        ),
        ExactSemanticLock(
            lock_id=f"lock-{role}-two",
            role=role,
            canonical_id="two",
            evidence_span_ids=("span-1",),
            source="canonical",
        ),
    )

    with pytest.raises(ValueError, match="EXACT_LOCK_CONFLICT"):
        validate_exact_semantic_locks(locks)
