from datetime import datetime, timedelta, timezone

import pytest

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.candidates import Mention
from financial_agent.intent.literals import LiteralCandidate, extract_literals
from financial_agent.intent.mention_spans import (
    MentionSpanLimitError,
    generate_mention_spans,
)
from financial_agent.intent.normalization import normalize_request


def request_context(question: str, *, segments: tuple[str, ...] | None = None) -> RequestContext:
    created_at = datetime(2026, 9, 3, tzinfo=timezone.utc)
    segment_texts = segments or (question,)
    return RequestContext(
        request_key=build_request_key("q-mentions", question, "dataset-v1", "1.0"),
        run_id="run-mentions",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q-mentions",
        question=question,
        segments=tuple(
            Segment(segment_id=f"s{index}", ordinal=index - 1, text=text)
            for index, text in enumerate(segment_texts, start=1)
        ),
        deadline_at=created_at + timedelta(seconds=10),
    )


def _mention(
    *, mention_id: str, segment_id: str, text: str, start: int, end: int
) -> Mention:
    return Mention(
        mention_id=mention_id,
        segment_id=segment_id,
        text=text,
        normalized_text=text,
        start_char=start,
        end_char=end,
    )


def test_phrase_spans_preserve_unseen_fee_paraphrase() -> None:
    normalized = normalize_request(request_context("비용 부담이 작은 ETF를 알려줘"))

    spans = generate_mention_spans(normalized, (), (), (), ())

    assert any(item.text == "비용 부담" for item in spans.items)
    assert all(
        normalized.context.segments[0].text[item.start_char : item.end_char]
        == item.text
        for item in spans.items
    )


def test_required_spans_are_never_silently_truncated() -> None:
    text = " ".join(f"항목{index}" for index in range(97))
    normalized = normalize_request(request_context(text))
    exact_mentions = tuple(
        _mention(
            mention_id=f"exact-{index}",
            segment_id="s1",
            text=f"항목{index}",
            start=text.index(f"항목{index}"),
            end=text.index(f"항목{index}") + len(f"항목{index}"),
        )
        for index in range(97)
    )

    with pytest.raises(MentionSpanLimitError, match="MENTION_SPAN_LIMIT_EXCEEDED"):
        generate_mention_spans(normalized, exact_mentions, (), (), ())


def test_merges_required_sources_by_original_range_without_losing_kinds() -> None:
    normalized = normalize_request(request_context("KODEX 200의 수수료율은 1% 이하야"))
    literal = next(item for item in extract_literals(normalized) if item.original_text == "1%")
    exact = _mention(
        mention_id="exact-fee",
        segment_id="s1",
        text="수수료율",
        start=11,
        end=15,
    )
    entity = _mention(
        mention_id="entity-kodex",
        segment_id="s1",
        text="KODEX 200",
        start=0,
        end=9,
    )
    reference = normalized.reference_candidates

    spans = generate_mention_spans(normalized, (exact,), (literal,), (entity,), reference)

    fee = next(item for item in spans.items if item.text == "수수료율")
    one_percent = next(item for item in spans.items if item.text == "1%")
    kodex = next(item for item in spans.items if item.text == "KODEX 200")
    assert fee.source_kinds == ("exact_anchor", "phrase")
    assert one_percent.source_kinds == ("literal_context",)
    assert kodex.source_kinds == ("entity", "phrase")


def test_source_ranged_duplicate_entity_mentions_keep_their_supplied_ranges() -> None:
    normalized = normalize_request(request_context("KODEX, KODEX"))
    first = _mention(
        mention_id="entity-kodex-first",
        segment_id="s1",
        text="KODEX",
        start=0,
        end=5,
    )
    second = _mention(
        mention_id="entity-kodex-second",
        segment_id="s1",
        text="KODEX",
        start=7,
        end=12,
    )

    spans = generate_mention_spans(normalized, (), (), (first, second), ())

    entities = [item for item in spans.items if item.source_kinds == ("entity", "phrase")]
    assert [(item.mention_id, item.start_char, item.end_char) for item in entities] == [
        ("mention-s1-0-5", 0, 5),
        ("mention-s1-7-12", 7, 12),
    ]


def test_phrase_windows_preserve_korean_particles_and_whitespace_boundaries() -> None:
    normalized = normalize_request(request_context("수수료율은 낮고 신용 등급이 높은 ETF"))

    spans = generate_mention_spans(normalized, (), (), (), ())

    assert {"수수료율은", "신용 등급", "신용 등급이 높은 ETF"} <= {
        item.text for item in spans.items
    }
    assert all(
        normalized.context.segments[0].text[item.start_char : item.end_char]
        == item.text
        for item in spans.items
    )


def test_phrase_windows_split_at_comma_and_preserve_unicode_source_offsets() -> None:
    text = "ＡＵＭ이 큰 ETF, 만기까지 며칠 남았는지 알려줘"
    normalized = normalize_request(request_context(text))

    spans = generate_mention_spans(normalized, (), (), (), ())

    assert "ＡＵＭ이 큰 ETF" in {item.text for item in spans.items}
    assert "만기까지 며칠 남았는지" in {item.text for item in spans.items}
    assert not any(
        "ETF, 만기" in item.text and item.text != text for item in spans.items
    )
    assert all(text[item.start_char : item.end_char] == item.text for item in spans.items)


def test_full_segments_and_references_are_ordered_across_prior_result_frames() -> None:
    first = "수수료율이 낮은 ETF를 보여줘"
    second = "그 결과 중 신용 등급이 높은 상품만 알려줘"
    normalized = normalize_request(request_context(f"{first} {second}", segments=(first, second)))

    spans = generate_mention_spans(
        normalized, (), (), (), normalized.reference_candidates
    )

    assert {
        (item.segment_id, item.text)
        for item in spans.items
        if item.source_kinds == ("phrase",)
    } >= {("s1", first), ("s2", second)}
    reference = next(item for item in spans.items if item.text == "그 결과")
    assert reference.source_kinds == ("reference", "phrase")
    assert [(item.segment_id, item.start_char, item.end_char) for item in spans.items] == sorted(
        (item.segment_id, item.start_char, item.end_char) for item in spans.items
    )


def test_outputs_are_byte_reproducible_and_literal_normalization_follows_source_mapping() -> None:
    normalized = normalize_request(request_context("ＡＵＭ   상위 ５개"))
    literal = LiteralCandidate(
        literal_id="lit-s1-9-11-result_limit",
        segment_id="s1",
        kind="result_limit",
        original_text="５개",
        start_char=9,
        end_char=11,
        canonical_value="5",
    )

    first = generate_mention_spans(normalized, (), (literal,), (), ())
    second = generate_mention_spans(normalized, (), (literal,), (), ())

    literal_span = next(item for item in first.items if item.text == "５개")
    assert first.model_dump_json() == second.model_dump_json()
    assert literal_span.normalized_text == "5개"
    assert normalized.context.segments[0].text[
        literal_span.start_char : literal_span.end_char
    ] == literal_span.text
