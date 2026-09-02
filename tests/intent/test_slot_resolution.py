import json
from pathlib import Path
from types import MappingProxyType

import pytest

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.clova import ModelInvocationResult
from financial_agent.intent.slot_resolution import (
    SlotResolutionError,
    resolve_ambiguous_slots,
)
from financial_agent.intent.task_binding import (
    BindingSource,
    TaskReadiness,
    bind_task_slots,
)
from financial_agent.intent.task_contracts import load_task_contract_registry
from financial_agent.intent.types import SlotKind
from financial_agent.intent.view import (
    ResolverViewSemanticCandidate,
    ResolverViewSemanticCandidateGroup,
)
from tests.planning.fixtures import NOW, resolution, view


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _context() -> RequestContext:
    question = "ETF에서 순자산 또는 위험등급 기준 상위 5개"
    return RequestContext(
        request_key=build_request_key("q-slot", question, "dataset-v1", "1.0"),
        run_id="run-slot",
        dataset_version="dataset-v1",
        producer="test",
        created_at=NOW,
        question_id="q-slot",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=NOW.replace(second=55),
    )


def _ambiguous_bound():
    source = resolution()
    axis_frame = source.canonical_frames[0].model_copy(update={"slot_assignments": ()})
    axis = source.model_copy(update={"canonical_frames": (axis_frame,)})
    resolver_view = view().model_copy(
        update={
            "semantic_candidates": (
                ResolverViewSemanticCandidateGroup(
                    mention_id="mention-aum",
                    items=(
                        ResolverViewSemanticCandidate(
                            semantic_id="aum",
                            match_kind="direct_alias",
                            score=1_000_000,
                        ),
                    ),
                ),
                ResolverViewSemanticCandidateGroup(
                    mention_id="mention-risk",
                    items=(
                        ResolverViewSemanticCandidate(
                            semantic_id="product_risk_grade",
                            match_kind="direct_alias",
                            score=1_000_000,
                        ),
                    ),
                ),
            )
        }
    )
    return bind_task_slots(
        axis,
        resolver_view,
        load_task_contract_registry(PROJECT_ROOT),
    )


class FakeAdapter:
    def __init__(self, selected_id: str) -> None:
        self.selected_id = selected_id
        self.calls = 0
        self.envelopes = []

    async def invoke(self, envelope, timeout_seconds: float) -> ModelInvocationResult:
        self.calls += 1
        self.envelopes.append(envelope)
        return ModelInvocationResult(
            content=json.dumps(
                {
                    "proposal_schema_version": "1.0",
                    "selections": [
                        {
                            "frame_id": "frame-1",
                            "slot_kind": "sort_key",
                            "selected_value_ids": [self.selected_id],
                        }
                    ],
                }
            ),
            usage=MappingProxyType(
                {"promptTokens": 5, "completionTokens": 3, "totalTokens": 8}
            ),
        )


@pytest.mark.asyncio
async def test_ambiguous_required_slot_uses_one_bounded_call() -> None:
    adapter = FakeAdapter("aum")

    result, usage = await resolve_ambiguous_slots(
        adapter=adapter,
        context=_context(),
        bound=_ambiguous_bound(),
        timeout_seconds=30.0,
    )

    assert adapter.calls == 1
    assert result.conditional_slot_call_used is True
    assert result.resolution.repair_used is True
    assert result.task_contracts[0].readiness is TaskReadiness.COMPLETE
    binding = next(
        item
        for item in result.task_contracts[0].bindings
        if item.slot_kind is SlotKind.SORT_KEY
    )
    assert binding.value_ids == ("aum",)
    assert binding.source is BindingSource.AMBIGUITY_MODEL
    schema_text = json.dumps(adapter.envelopes[0].response_schema)
    assert "aum" in schema_text
    assert "product_risk_grade" in schema_text
    assert "metric" not in schema_text
    assert usage["totalTokens"] == 8


@pytest.mark.asyncio
async def test_unknown_slot_choice_fails_closed() -> None:
    adapter = FakeAdapter("invented")

    with pytest.raises(SlotResolutionError, match="SLOT_SELECTION_NOT_OFFERED"):
        await resolve_ambiguous_slots(
            adapter=adapter,
            context=_context(),
            bound=_ambiguous_bound(),
            timeout_seconds=30.0,
        )

    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_non_ambiguous_contract_never_enters_slot_resolver() -> None:
    bound = _ambiguous_bound()
    blocked = bound.model_copy(
        update={
            "task_contracts": (
                bound.task_contracts[0].model_copy(
                    update={
                        "readiness": TaskReadiness.BLOCKED,
                        "ambiguous_choices": (),
                    }
                ),
            )
        }
    )
    adapter = FakeAdapter("aum")

    with pytest.raises(SlotResolutionError, match="SLOT_SELECTION_NOT_ELIGIBLE"):
        await resolve_ambiguous_slots(
            adapter=adapter,
            context=_context(),
            bound=blocked,
            timeout_seconds=30.0,
        )

    assert adapter.calls == 0
