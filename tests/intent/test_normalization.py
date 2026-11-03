from datetime import datetime, timedelta, timezone

import pytest

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import NamedEntityMention, RequestContext, Segment
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
    ]
    assert [candidate.start_char for candidate in request.reference_candidates] == [
        0,
        7,
        13,
        17,
    ]
    assert [candidate.end_char for candidate in request.reference_candidates] == [5, 11, 15, 19]


def test_request_marks_context_reference_stems_longest_first_without_overlap() -> None:
    text = "그 운용사는? 각 상품의 수익률은? 그 결과의 근거는? 나머지 상품은? 이거는?"
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    request = normalize_request(context)

    assert [candidate.text for candidate in request.reference_candidates] == [
        "그 운용사",
        "각 상품",
        "그 결과",
        "나머지 상품",
        "이거",
    ]
    assert [text[candidate.start_char:candidate.end_char] for candidate in request.reference_candidates] == [
        "그 운용사",
        "각 상품",
        "그 결과",
        "나머지 상품",
        "이거",
    ]


def test_company_name_does_not_create_a_context_reference() -> None:
    text = "삼성전자와 SK하이닉스 중 전자와 후자를 비교해줘"
    context = context_factory(question=text).model_copy(
        update={
            "segments": (Segment(segment_id="s1", ordinal=0, text=text),),
            "named_entities": (
                NamedEntityMention(
                    mention_id="entity-1",
                    segment_id="s1",
                    text="삼성전자",
                    expected_entity_types=("Security",),
                ),
            ),
        }
    )

    request = normalize_request(context)

    assert [candidate.text for candidate in request.reference_candidates] == ["전자", "후자"]
    assert all(candidate.start_char > len("삼성전자") for candidate in request.reference_candidates)


@pytest.mark.parametrize(
    "reference",
    [
        "이 국내 ETF", "이 해외 ETF", "이 ETF", "이 채권", "이 공모펀드",
        "그 ETF", "해당 채권", "이 채권들", "그 공모 펀드들",
    ],
)
def test_typed_product_references_retain_exact_source_spans(reference: str) -> None:
    text = f"조회: {reference}의 위험등급을 알려줘."
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    candidates = normalize_request(context).reference_candidates

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.text == reference
    assert candidate.reference_id == f"ref-s1-4-{4 + len(reference)}"
    assert text[candidate.start_char:candidate.end_char] == reference


def test_typed_reference_normalization_preserves_whitespace_and_unicode_source() -> None:
    text = "이\t 국내   ＥＴＦ의 위험등급을 알려줘."
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    candidates = normalize_request(context).reference_candidates

    assert len(candidates) == 1
    assert candidates[0].text == "이\t 국내   ＥＴＦ"
    assert (candidates[0].start_char, candidates[0].end_char) == (0, 11)


@pytest.mark.parametrize("reference,particle,continuation", [
    ("이 상품", "에", "대해 설명해줘."), ("이 국내 ETF", "로", "비교해줘."),
    ("이 상품", "으로", "비교해줘."), ("이 ETF", "보다", "보수가 낮은 국내 ETF를 찾아줘."),
])
def test_product_reference_particles_preserve_only_the_original_reference_stem(reference: str, particle: str, continuation: str) -> None:
    text = f"조회: {reference}{particle} {continuation}"
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    candidates = normalize_request(context).reference_candidates

    assert [(candidate.text, candidate.start_char, candidate.end_char) for candidate in candidates] == [
        (reference, 4, 4 + len(reference)),
    ]
    assert candidates[0].reference_id == f"ref-s1-4-{4 + len(reference)}"
    assert text[candidates[0].start_char:candidates[0].end_char] == reference


@pytest.mark.parametrize("text", [
    "이 상품에너지 구조를 알려줘.", "이 ETF로드 상품을 알려줘.",
    "이 상품으로봇 구조를 알려줘.", "이 상품보다리 구조를 알려줘.",
])
def test_reference_particle_prefixes_inside_longer_words_are_not_candidates(text: str) -> None:
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    assert normalize_request(context).reference_candidates == ()


@pytest.mark.parametrize(
    "text", ["카카오페이 ETF를 조회해줘.", "이 ETF랩 상품을 조회해줘.", "전자금융 상품을 찾아줘."]
)
def test_reference_substrings_inside_words_are_not_candidates(text: str) -> None:
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    assert normalize_request(context).reference_candidates == ()


def test_typed_reference_is_masked_inside_a_source_grounded_product_name() -> None:
    text = "이 ETF 상품과 이 ETF를 비교해줘."
    context = context_factory(question=text).model_copy(
        update={
            "segments": (Segment(segment_id="s1", ordinal=0, text=text),),
            "named_entities": (
                NamedEntityMention(
                    mention_id="entity-1", segment_id="s1", text="이 ETF 상품",
                    expected_entity_types=("DomesticETF",), start_char=0, end_char=8,
                ),
            ),
        }
    )

    candidates = normalize_request(context).reference_candidates

    assert len(candidates) == 1
    assert (candidates[0].text, candidates[0].start_char, candidates[0].end_char) == (
        "이 ETF", 10, 15,
    )


def test_casual_demonstrative_reference_keeps_the_source_stem() -> None:
    text = "그거랑 비슷한 상품을 찾아줘."
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    candidates = normalize_request(context).reference_candidates

    assert [(candidate.text, candidate.start_char, candidate.end_char) for candidate in candidates] == [
        ("그거", 0, 2)
    ]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("국내 ETF와 해외 ETF를 각각 AUM 순으로 세 개씩 보여줘", []),
        ("가상 국내 ETF를 AUM 상위 5개까지 보여줘. 그 상품들 각각 위험등급을 붙여줘.", ["그 상품들"]),
        ("각각 수수료도 알려줘.", ["각각"]),
        ("이 데이터의 공모펀드 수를 원본 행, 고유 판매클래스, 대표펀드군 기준으로 각각 알려줘.", []),
        ("국내 ETF와 해외 ETF를 보여줘. 각각 수수료도 알려줘.", ["각각"]),
        ("상품번호, 만기일을 각각 알려줘.", []),
        ("분석결과 ETF를 각각 보여줘.", ["각각"]),
    ],
)
def test_distributive_each_does_not_create_a_second_or_unbound_reference(
    text: str, expected: list[str]
) -> None:
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    candidates = normalize_request(context).reference_candidates

    assert [candidate.text for candidate in candidates] == expected
    assert all(text[candidate.start_char:candidate.end_char] == candidate.text for candidate in candidates)


@pytest.mark.parametrize("text,expected", [
    ("가상 국내 ETF를 AUM 상위 5개까지 보여줘. 해당 상품들에서 연간 성과 1위를 알려줘.", "해당 상품들"),
    ("가상 국내 ETF를 AUM 상위 5개까지 보여줘. 그 목록 중 최근 일 년 수익률이 제일 큰 상품은?", "그 목록"),
    ("가상 국내 ETF를 AUM 상위 5개까지 보여줘. 그 목록의 마지막 상품은 위험등급이 뭐야?", "그 목록"),
    ("가상 국내 ETF를 AUM 상위 5개까지 보여줘. 그중 첫 상품만 1년 수익률을 보여줘.", "그중"),
    ("가상 국내 ETF를 AUM 상위 5개까지 보여줘. 그중 하나씩 운용사를 연결해줘.", "그중"),
    ("가상운용사의 국내 ETF 중 AUM 1위를 알려줘. 해당 운용사의 해외 상품 중 1년 수익률 상위를 알려줘.", "해당 운용사"),
    ("가상운용사의 국내 ETF 중 AUM 1위를 알려줘. 그 운용사의 다른 공모펀드도 AUM 순으로.", "그 운용사"),
    ("가상운용사의 국내 ETF 중 AUM 1위를 알려줘. 해당 회사가 운용하는 해외 ETF를 세 개만 골라줘.", "해당 회사"),
    ("가상운용사의 국내 ETF 중 AUM 1위를 알려줘. 해당 운용기관의 해외 ETF 운용 목록을 알려줘.", "해당 운용기관"),
    ("가상운용사의 국내 ETF 중 AUM 1위를 알려줘. 그 회사가 맡은 공모펀드 중 보수가 낮은 상품은?", "그 회사"),
    ("위 목록 중 AUM 1위는?", "위 목록"),
    ("해외ETF 지역 조회하고 그 지역별 연간 수익률 비교", "그 지역"),
])
def test_authored_followup_reference_surfaces_are_source_offered(text: str, expected: str) -> None:
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    candidates = normalize_request(context).reference_candidates

    assert [candidate.text for candidate in candidates] == [expected]
    candidate = candidates[0]
    assert text[candidate.start_char:candidate.end_char] == expected
    assert candidate.reference_id == f"ref-s1-{candidate.start_char}-{candidate.end_char}"


@pytest.mark.parametrize("text", ["그중국 상품을 찾아줘.", "해당 회사명을 알려줘."])
def test_observed_reference_surfaces_do_not_match_longer_words(text: str) -> None:
    context = context_factory(question=text).model_copy(
        update={"segments": (Segment(segment_id="s1", ordinal=0, text=text),)}
    )

    assert normalize_request(context).reference_candidates == ()
