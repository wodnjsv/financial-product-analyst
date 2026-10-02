"""Explicit listing scope must survive model mistakes in personal V3 routing."""

import json

import pytest

from financial_agent.intent.axis_locks import build_exact_semantic_locks
from financial_agent.intent.candidates import generate_semantic_candidates
from financial_agent.intent.catalog import load_hybrid_catalog
from financial_agent.intent.errors import ResolverContractError
from financial_agent.intent.normalization import normalize_request
from tests.intent.test_query_contract_service import (
    PROJECT_ROOT,
    _Adapter,
    _context,
    _hybrid_service,
)


def _family_locks(question: str):
    catalog = load_hybrid_catalog(PROJECT_ROOT)
    normalized = normalize_request(_context(question))
    candidates = generate_semantic_candidates(normalized, catalog)
    return tuple(
        item
        for item in build_exact_semantic_locks(
            normalized, catalog, semantic_candidates=candidates
        )
        if item.role == "product_family"
    )


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("국내 ETF 중 1년 수익률 높은 5개", {"domestic_etf"}),
        ("국내ETF 중 1년 수익률 높은 5개", {"domestic_etf"}),
        ("국내 상장 ETF 중 1년 수익률 높은 5개", {"domestic_etf"}),
        ("해외 ETF 중 1년 수익률 높은 5개", {"overseas_etf"}),
        ("미국 ETF 중 1년 수익률 높은 5개", {"overseas_etf"}),
        ("국내 ETF와 해외 ETF를 비교해줘", {"domestic_etf", "overseas_etf"}),
    ],
)
def test_explicit_family_axis_surfaces_become_source_owned_locks(question, expected):
    locks = _family_locks(question)

    assert {item.canonical_id for item in locks} == expected
    assert all(item.source == "direct_alias" and item.evidence_span_ids for item in locks)


@pytest.mark.parametrize(
    "question", ["ETF 순위", "펀드 순위", "미국에 투자하는 ETF 순위"]
)
def test_generic_type_or_investment_geography_does_not_lock_listing_family(question):
    assert _family_locks(question) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "wrong_family"),
    [
        ("국내 ETF 중 1년 수익률 높은 5개", "overseas_etf"),
        ("해외 ETF 중 1년 수익률 높은 5개", "domestic_etf"),
        ("미국 ETF 중 1년 수익률 높은 5개", "domestic_etf"),
        ("국내 ETF와 해외 ETF의 1년 수익률 높은 5개", "domestic_etf"),
        ("국내 ETF와 해외 ETF의 1년 수익률 높은 5개", "overseas_etf"),
    ],
)
async def test_wrong_model_family_cannot_override_explicit_listing_scope(
    question, wrong_family
):
    service = _hybrid_service(_Adapter([]))
    prepared = await service.prepare_hybrid(_context(question))
    mention = next(
        item for item in prepared.view.mention_spans.items if item.text == "1년 수익률"
    )
    payload = {
        "proposal_schema_version": "3.0",
        "frames": [
            {
                "segment_ids": ["s1"],
                "action_choice": {
                    "state": "selected",
                    "selected_ids": ["rank"],
                    "evidence_ids": [],
                    "reason_code": "explicit",
                },
                "product_family_choice": {
                    "state": "selected",
                    "selected_ids": [wrong_family],
                    "evidence_ids": [],
                    "reason_code": "explicit",
                },
                "entity_type_ids": ["FinancialProduct"],
                "semantic_links": [
                    {
                        "mention_id": mention.mention_id,
                        "state": "selected",
                        "semantic_ids": ["trailing_1y_historical_cumulative_return"],
                        "reason_code": "explicit",
                    }
                ],
                "unmapped_mention_ids": [],
                "semantic_coverage": {"state": "covered", "reason": "none"},
                "entity_hints": [],
                "produced_result_hints": ["candidates"],
            }
        ],
        "references": [],
        "context_links": [],
        "slot_mutations": [],
        "semantic_flag_hints": [],
        "frame_limit_exceeded": False,
    }

    with pytest.raises(ResolverContractError, match="MODEL_EXACT_LOCK_CONFLICT"):
        service.validate_hybrid_response(prepared, json.dumps(payload))
