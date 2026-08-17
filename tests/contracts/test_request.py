import pytest
from pydantic import ValidationError

from financial_agent.contracts.request import RequestContext


def test_request_context_owns_all_segments_and_surface_mentions(load_fixture) -> None:
    context = RequestContext.model_validate(load_fixture("request_context.json"))
    assert [segment.segment_id for segment in context.segments] == ["s1", "s2"]
    assert context.reference_mentions[0].text == "이 상품들"


def test_request_context_rejects_unknown_segment_reference(load_fixture) -> None:
    payload = load_fixture("request_context.json")
    payload["reference_mentions"][0]["segment_id"] = "missing"
    with pytest.raises(ValidationError):
        RequestContext.model_validate(payload)


def test_request_context_deadline_is_at_most_55_seconds(load_fixture) -> None:
    payload = load_fixture("request_context.json")
    payload["deadline_at"] = "2026-08-17T00:00:56Z"
    with pytest.raises(ValidationError):
        RequestContext.model_validate(payload)
