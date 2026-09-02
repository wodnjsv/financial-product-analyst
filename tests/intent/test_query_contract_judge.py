from __future__ import annotations

import json
from pathlib import Path

import pytest

from financial_agent.intent.clova import ModelInvocationResult
from financial_agent.intent.errors import MODEL_TIMEOUT, ModelInvocationError
from financial_agent.intent.query_contract_judge import (
    QueryContractJudge,
    build_query_contract_judge_envelope,
)
from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.intent.query_contract_solver import solve_query_contracts
from financial_agent.intent.query_contracts import ContractReadiness
from financial_agent.intent.view import ResolverViewSemanticCandidate, ResolverViewSemanticCandidateGroup
from tests.planning.fixtures import resolution, view


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _ambiguous_candidates():
    source = resolution()
    frame = source.canonical_frames[0].model_copy(update={"slot_assignments": ()})
    source = source.model_copy(update={"canonical_frames": (frame,)})
    resolver_view = view().model_copy(
        update={
            "semantic_candidates": (
                ResolverViewSemanticCandidateGroup(
                    mention_id="mention-s1-0-3",
                    items=(ResolverViewSemanticCandidate(semantic_id="aum", match_kind="direct_alias", score=1_000_000),),
                ),
                ResolverViewSemanticCandidateGroup(
                    mention_id="mention-s1-4-7",
                    items=(ResolverViewSemanticCandidate(semantic_id="product_risk_grade", match_kind="trigram", score=900_000),),
                ),
            )
        }
    )
    solved = solve_query_contracts(
        resolution=source,
        view=resolver_view,
        exact_locks=(),
        registry=load_query_contract_registry(PROJECT_ROOT),
    )
    return frame, solved.frames[0].complete_candidates


class _Adapter:
    def __init__(self, content: str | None = None, failure: Exception | None = None):
        self.content = content
        self.failure = failure
        self.calls = []

    async def invoke(self, envelope, timeout_seconds: float):
        self.calls.append((envelope, timeout_seconds))
        if self.failure is not None:
            raise self.failure
        return ModelInvocationResult(
            content=self.content or "{}",
            usage={"promptTokens": 1, "completionTokens": 1, "totalTokens": 2},
        )


def test_judge_schema_enum_contains_exactly_offered_complete_candidate_ids() -> None:
    frame, candidates = _ambiguous_candidates()
    envelope = build_query_contract_judge_envelope(
        question="ETF 중 규모가 큰 상품",
        frame=frame,
        candidates=candidates,
    )

    assert envelope.response_schema["properties"]["candidate_id"]["enum"] == [
        item.candidate_id for item in candidates
    ]


def test_judge_prompt_contains_semantics_but_no_physical_or_sql_tokens() -> None:
    frame, candidates = _ambiguous_candidates()
    envelope = build_query_contract_judge_envelope(
        question="ETF 중 규모가 큰 상품",
        frame=frame,
        candidates=candidates,
    )
    payload = json.loads(envelope.user_message)
    serialized = json.dumps(payload, ensure_ascii=False)
    complete_prompt = envelope.system_message + envelope.user_message

    assert payload["question"] == "ETF 중 규모가 큰 상품"
    assert payload["candidates"]
    assert "registry_pins" not in serialized
    assert "physical" not in serialized.lower()
    assert "sql" not in complete_prompt.lower()
    assert "SELECT" not in complete_prompt
    assert "table_name" not in serialized


@pytest.mark.asyncio
async def test_unknown_judge_id_remains_ambiguous_without_repair() -> None:
    frame, candidates = _ambiguous_candidates()
    adapter = _Adapter(content='{"candidate_id":"not-offered"}')
    judge = QueryContractJudge(adapter)

    result = await judge.select_offered_id(
        question="ETF 중 규모가 큰 상품",
        frame=frame,
        candidates=candidates,
        timeout_seconds=2.0,
    )

    assert result.contract_readiness.readiness is ContractReadiness.AMBIGUOUS
    assert result.contract_readiness.reason_codes == ("JUDGE_UNKNOWN_CANDIDATE_ID",)
    assert result.candidate_id is None
    assert len(adapter.calls) == 1


@pytest.mark.asyncio
async def test_timeout_remains_ambiguous_and_makes_no_repair_call() -> None:
    frame, candidates = _ambiguous_candidates()
    adapter = _Adapter(failure=ModelInvocationError(MODEL_TIMEOUT))
    judge = QueryContractJudge(adapter)

    result = await judge.select_offered_id(
        question="ETF 중 규모가 큰 상품",
        frame=frame,
        candidates=candidates,
        timeout_seconds=2.0,
    )

    assert result.contract_readiness.readiness is ContractReadiness.AMBIGUOUS
    assert result.contract_readiness.reason_codes == (MODEL_TIMEOUT,)
    assert len(adapter.calls) == 1


@pytest.mark.asyncio
async def test_exhausted_deadline_stays_ambiguous_without_provider_call() -> None:
    frame, candidates = _ambiguous_candidates()
    adapter = _Adapter()
    judge = QueryContractJudge(adapter)

    result = await judge.select_offered_id(
        question="ETF 중 규모가 큰 상품",
        frame=frame,
        candidates=candidates,
        timeout_seconds=0.0,
    )

    assert result.candidate_id is None
    assert result.contract_readiness.reason_codes == (MODEL_TIMEOUT,)
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_unique_candidate_needs_no_judge_call() -> None:
    frame, candidates = _ambiguous_candidates()
    adapter = _Adapter()
    judge = QueryContractJudge(adapter)

    result = await judge.select_offered_id(
        question="ETF 중 규모가 큰 상품",
        frame=frame,
        candidates=candidates[:1],
        timeout_seconds=2.0,
    )

    assert result.candidate_id == candidates[0].candidate_id
    assert result.contract_readiness.readiness is ContractReadiness.COMPLETE
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_used_repair_allowance_blocks_judge_call() -> None:
    frame, candidates = _ambiguous_candidates()
    adapter = _Adapter()
    judge = QueryContractJudge(adapter)

    result = await judge.select_offered_id(
        question="ETF 중 규모가 큰 상품",
        frame=frame,
        candidates=candidates,
        timeout_seconds=2.0,
        repair_used=True,
    )

    assert result.candidate_id is None
    assert result.contract_readiness.reason_codes == ("EXTRA_MODEL_ALLOWANCE_ALREADY_USED",)
    assert adapter.calls == []
