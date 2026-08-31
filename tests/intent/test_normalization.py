from datetime import datetime, timedelta, timezone

import pytest

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.normalization import (
    RequestNormalizationError,
    normalize_request,
    normalize_segment,
)


def context_factory(
    *, question: str = "질문", segment_count: int = 1
) -> RequestContext:
    created_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
    return RequestContext(
        request_key=build_request_key("q1", question, "dataset-v1", "1.0"),
        run_id="run-1",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q1",
        question=question,
        segments=tuple(
            Segment(segment_id=f"s{index}", ordinal=index - 1, text=f"문장 {index}")
            for index in range(1, segment_count + 1)
        ),
        deadline_at=created_at + timedelta(seconds=10),
    )


def test_nfkc_and_whitespace_mapping_returns_exact_original_slice() -> None:
    segment = normalize_segment("s1", "ＡＵＭ   상위 ５개")

    start, end = segment.find_normalized("AUM 상위 5개")
    original_start, original_end = segment.to_original_span(start, end)

    assert segment.original_text[original_start:original_end] == "ＡＵＭ   상위 ５개"


def test_nfkc_expansion_maps_each_normalized_code_point_to_its_source() -> None:
    segment = normalize_segment("s1", "㍉")

    assert segment.normalized_text == "ミリ"
    assert segment.origin_spans == ((0, 1), (0, 1))
    assert segment.to_original_span(0, 2) == (0, 1)


def test_whitespace_run_maps_to_the_complete_original_run() -> None:
    segment = normalize_segment("s1", "가\t \n나")

    assert segment.normalized_text == "가 나"
    assert segment.origin_spans[1] == (1, 4)
    assert segment.to_original_span(1, 2) == (1, 4)


@pytest.mark.parametrize("start,end", [(0, 0), (-1, 1), (0, 4), (2, 1)])
def test_original_span_rejects_invalid_normalized_boundaries(
    start: int, end: int
) -> None:
    segment = normalize_segment("s1", "가 나")

    with pytest.raises(ValueError, match="normalized span is out of range"):
        segment.to_original_span(start, end)


def test_request_rejects_more_than_4096_code_points() -> None:
    context = context_factory(question="가" * 4097)

    with pytest.raises(RequestNormalizationError, match="REQUEST_CONTRACT_INVALID"):
        normalize_request(context)


def test_request_rejects_more_than_16_segments() -> None:
    with pytest.raises(RequestNormalizationError, match="REQUEST_CONTRACT_INVALID"):
        normalize_request(context_factory(segment_count=17))


def test_request_marks_explicit_korean_reference_surfaces_with_original_spans() -> None:
    context = context_factory(question="그 상품들, 이 상품, 전자와 후자 각각")
    context = context.model_copy(
        update={
            "segments": (Segment(segment_id="s1", ordinal=0, text=context.question),)
        }
    )

    request = normalize_request(context)

    assert [candidate.text for candidate in request.reference_candidates] == [
        "그 상품들",
        "이 상품",
        "전자",
        "후자",
        "각각",
    ]
    assert [candidate.start_char for candidate in request.reference_candidates] == [
        0,
        7,
        13,
        17,
        20,
    ]
    assert [candidate.end_char for candidate in request.reference_candidates] == [5, 11, 15, 19, 22]
