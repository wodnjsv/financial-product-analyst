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


@pytest.mark.parametrize(
    "text",
    [
        "총보수 1% 이하, 수익률 이상",
        "총보수 1% 이하 그리고 수익률 이상",
        "총보수 1% 이하 수익률 이상",
    ],
)
def test_comparison_without_a_local_literal_does_not_reuse_a_previous_clause(
    text: str,
) -> None:
    """Catches a later predicate borrowing a percentage from an earlier clause."""
    request = _normalized_request(text)

    operators = extract_operator_candidates(request, extract_literals(request))

    assert [(item.operator_id.value, item.compatible_value_candidate_ids) for item in operators] == [
        ("lte", ("lit-s1-4-6-percentage",))
    ]


def test_each_exclusion_clause_uses_its_own_cardinality() -> None:
    """Catches a later exclusion extending the preceding exclusion value set."""
    request = _normalized_request("1% 제외, 2% 제외")

    operators = extract_operator_candidates(request, extract_literals(request))

    assert [(item.operator_id.value, item.compatible_value_candidate_ids) for item in operators] == [
        ("neq", ("lit-s1-0-2-percentage",)),
        ("neq", ("lit-s1-7-9-percentage",)),
    ]


def test_from_until_range_binds_literals_on_both_sides_of_the_range_cue() -> None:
    """Catches a range parser that only searches before `부터` for both values."""
    request = _normalized_request("1%부터 3%까지")

    operators = extract_operator_candidates(request, extract_literals(request))

    assert [(item.operator_id.value, item.compatible_value_candidate_ids) for item in operators] == [
        ("between", ("lit-s1-0-2-percentage", "lit-s1-5-7-percentage"))
    ]


def test_ordered_operators_reject_an_incompatible_sort_direction_literal() -> None:
    """Catches ordered operators accepting a string candidate outside the closed registry."""
    request = _normalized_request("낮은 이하")

    assert extract_operator_candidates(request, extract_literals(request)) == ()
