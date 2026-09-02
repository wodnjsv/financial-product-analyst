from datetime import datetime, timedelta, timezone

import pytest

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.operators import extract_operator_candidates


def _normalized_request(text: str):
    created_at = datetime(2026, 9, 2, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("operators", text, "dataset-v1", "1.0"),
        run_id="run-operators",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="operators",
        question=text,
        segments=(Segment(segment_id="s1", ordinal=0, text=text),),
        deadline_at=created_at + timedelta(seconds=10),
    )
    return normalize_request(context)


@pytest.mark.parametrize(
    ("text", "operator_id"),
    [
        ("1% 이하", "lte"),
        ("1% 미만", "lt"),
        ("1% 이상", "gte"),
        ("1% 초과", "gt"),
        ("1% 이하가 아닌", "gt"),
    ],
)
def test_comparison_cues_emit_semantic_operator_ids_only(
    text: str, operator_id: str
) -> None:
    """Catches SQL syntax or the wrong comparison polarity leaking from Korean cues."""
    request = _normalized_request(text)

    operators = extract_operator_candidates(request, extract_literals(request))

    assert [(item.operator_id.value, item.arity.value) for item in operators] == [
        (operator_id, "one")
    ]
    assert operators[0].compatible_value_candidate_ids[0].endswith("percentage")
    assert not any("<" in field or ">" in field for field in operators[0].model_dump_json())


@pytest.mark.parametrize(
    ("text", "operator_id", "value_count"),
    [
        ("1% 제외", "neq", 1),
        ("1%, 2% 제외", "not_in", 2),
        ("1%에서 3% 사이", "between", 2),
    ],
)
def test_exclusion_and_range_cues_use_semantic_arity(
    text: str, operator_id: str, value_count: int
) -> None:
    """Catches collapsing membership and range clauses into a scalar comparison."""
    request = _normalized_request(text)

    operators = extract_operator_candidates(request, extract_literals(request))

    assert [(item.operator_id.value, item.arity.value) for item in operators] == [
        (operator_id, "one_or_more" if operator_id == "not_in" else "two" if operator_id == "between" else "one")
    ]
    assert len(operators[0].compatible_value_candidate_ids) == value_count


def test_each_operator_binds_only_literals_in_its_own_clause() -> None:
    """Catches one percentage literal being attached to unrelated predicates."""
    request = _normalized_request("총보수 1% 이하, 수익률 3% 이상")

    operators = extract_operator_candidates(request, extract_literals(request))

    assert [item.operator_id.value for item in operators] == ["lte", "gte"]
    assert [item.compatible_value_candidate_ids for item in operators] == [
        ("lit-s1-4-6-percentage",),
        ("lit-s1-15-17-percentage",),
    ]
