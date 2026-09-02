from datetime import datetime, timedelta, timezone

import pytest

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.normalization import normalize_request


def normalized_request(text: str):
    created_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("q1", text, "dataset-v1", "1.0"),
        run_id="run-1",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q1",
        question=text,
        segments=(Segment(segment_id="s1", ordinal=0, text=text),),
        deadline_at=created_at + timedelta(seconds=10),
    )
    return normalize_request(context)


def test_extracts_supported_literal_forms_in_source_order_without_overlap() -> None:
    request = normalized_request(
        "상위 5개, 1위, 30%, 3.5%, 330만원, 3,300,000원, KRW, 원화, USD, 달러, "
        "2026-08-24, 2026년 8월 24일, 1년, 6개월, 오름차순, 내림차순, 높은, 낮은"
    )

    literals = extract_literals(request)

    assert [
        (literal.kind, literal.canonical_value, literal.currency)
        for literal in literals
    ] == [
        ("result_limit", "5", None),
        ("rank_position", "1", None),
        ("percentage", "30", None),
        ("percentage", "3.5", None),
        ("money", "3300000", "KRW"),
        ("money", "3300000", "KRW"),
        ("currency", "KRW", "KRW"),
        ("currency", "KRW", "KRW"),
        ("currency", "USD", "USD"),
        ("currency", "USD", "USD"),
        ("date", "2026-08-24", None),
        ("date", "2026-08-24", None),
        ("period", "P1Y", None),
        ("period", "P6M", None),
        ("sort_direction", "asc", None),
        ("sort_direction", "desc", None),
        ("sort_direction", "desc", None),
        ("sort_direction", "asc", None),
    ]
    assert all(
        left.end_char <= right.start_char for left, right in zip(literals, literals[1:])
    )


def test_literal_id_and_original_evidence_span_do_not_use_normalized_offsets() -> None:
    request = normalized_request("ＡＵＭ   상위 ５개를 보여줘")

    literal = extract_literals(request)[0]

    assert literal.literal_id == "lit-s1-9-11-result_limit"
    assert literal.original_text == "５개"
    assert (literal.start_char, literal.end_char) == (9, 11)
    assert literal.canonical_value == "5"


def test_money_uses_decimal_strings_and_applies_manwon_multiplier() -> None:
    literals = extract_literals(normalized_request("0.1만원과 3,300,000원"))

    assert [(literal.canonical_value, literal.currency) for literal in literals] == [
        ("1000", "KRW"),
        ("3300000", "KRW"),
    ]


def test_period_does_not_choose_a_semantic_return_concept_or_emit_its_number() -> None:
    literals = extract_literals(normalized_request("1년 수익률"))

    assert [(literal.kind, literal.canonical_value) for literal in literals] == [
        ("period", "P1Y")
    ]


def test_plain_number_is_extracted_when_no_typed_form_claims_its_span() -> None:
    literals = extract_literals(normalized_request("5를 보여줘"))

    assert [(literal.kind, literal.canonical_value) for literal in literals] == [
        ("number", "5")
    ]


@pytest.mark.parametrize(
    ("text", "original_text", "canonical_value"),
    [
        ("다섯 종목만 보여줘", "다섯 종목", "5"),
        ("다섯개 보여줘", "다섯개", "5"),
        ("세 개씩 보여줘", "세 개", "3"),
        ("세 상품을 보여줘", "세 상품", "3"),
        ("세 자리까지 순위 내줘", "세 자리", "3"),
    ],
)
def test_extracts_native_korean_result_limits(
    text: str,
    original_text: str,
    canonical_value: str,
) -> None:
    literals = extract_literals(normalized_request(text))

    assert [
        (literal.kind, literal.original_text, literal.canonical_value)
        for literal in literals
    ] == [("result_limit", original_text, canonical_value)]


def test_does_not_treat_a_product_family_count_as_a_result_limit() -> None:
    literals = extract_literals(normalized_request("두 상품군을 비교해줘"))

    assert literals == ()
