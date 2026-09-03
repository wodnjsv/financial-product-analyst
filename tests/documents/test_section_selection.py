from __future__ import annotations

from financial_agent.documents.chunking import (
    DocumentChunkContext,
    ExtractedSection,
    WhitespaceTokenCounter,
    chunk_document_sections,
)
from financial_agent.documents.models import CoverageStatus, SectionType
from financial_agent.documents.section_selection import (
    select_canonical_claim_sections,
)


def extracted(
    heading_path: tuple[str, ...],
    text: str,
    *,
    start: int,
    page: int = 1,
) -> ExtractedSection:
    return ExtractedSection(
        heading_path=heading_path,
        exact_text=text,
        page_start=page,
        page_end=page,
        character_start=start,
        character_end=start + len(text),
    )


REQUESTED = frozenset(
    {SectionType.INVESTMENT_STRATEGY, SectionType.RISK_FACTOR}
)


def test_concise_sections_win_and_full_text_only_fills_missing_claims() -> None:
    sections = (
        extracted(
            ("요약정보", "투자목적 및 투자전략"),
            "summary strategy",
            start=10,
        ),
        extracted(
            ("제2부", "집합투자기구의 투자전략"),
            "full strategy",
            start=100,
        ),
        extracted(
            ("제2부", "집합투자기구의 투자위험"),
            "full risk",
            start=200,
        ),
    )

    result = select_canonical_claim_sections(
        sections,
        requested_section_types=REQUESTED,
    )

    assert [item.exact_text for item in result.selected_sections] == [
        "summary strategy",
        "full risk",
    ]
    assert result.missing_section_types == frozenset()
    assert result.reason_codes == ()


def test_all_concise_sections_for_one_claim_are_preserved_in_source_order() -> None:
    sections = (
        extracted(("요약정보", "주요투자 위험"), "risk two", start=30),
        extracted(("요약정보", "주요투자 위험"), "risk one", start=20),
        extracted(("제2부", "집합투자기구의 투자위험"), "full risk", start=90),
    )

    result = select_canonical_claim_sections(
        sections,
        requested_section_types=frozenset({SectionType.RISK_FACTOR}),
    )

    assert [item.exact_text for item in result.selected_sections] == [
        "risk one",
        "risk two",
    ]


def test_duplicate_exact_text_is_selected_once() -> None:
    sections = (
        extracted(("요약정보", "주요투자 위험"), "same risk", start=10),
        extracted(("요약정보", "주요투자 위험"), "same risk", start=20),
    )

    result = select_canonical_claim_sections(
        sections,
        requested_section_types=frozenset({SectionType.RISK_FACTOR}),
    )

    assert [item.exact_text for item in result.selected_sections] == ["same risk"]


def test_selection_is_deterministic_when_input_order_changes() -> None:
    sections = (
        extracted(("요약정보", "주요투자 위험"), "risk", start=20),
        extracted(("요약정보", "투자목적 및 투자전략"), "strategy", start=10),
    )

    first = select_canonical_claim_sections(
        sections,
        requested_section_types=REQUESTED,
    )
    reversed_result = select_canonical_claim_sections(
        tuple(reversed(sections)),
        requested_section_types=REQUESTED,
    )

    assert first == reversed_result


def test_unrelated_and_excluded_sections_do_not_fill_requested_claims() -> None:
    sections = (
        extracted(("요약정보", "투자목적"), "objective only", start=10),
        extracted(("요약정보", "투자비용"), "fees", start=20),
        extracted(("부록", "주요 투자위험"), "appendix risk", start=30),
    )

    result = select_canonical_claim_sections(
        sections,
        requested_section_types=REQUESTED,
    )

    assert result.selected_sections == ()
    assert result.missing_section_types == REQUESTED
    assert result.reason_codes == (
        "missing_section:investment_strategy",
        "missing_section:risk_factor",
    )


def test_selected_sections_feed_existing_chunker_with_complete_locators() -> None:
    strategy = "KOSPI200 지수를 추종합니다."
    risk = "추적오차로 손실이 발생할 수 있습니다."
    selection = select_canonical_claim_sections(
        (
            extracted(
                ("요약정보", "투자목적 및 투자전략"), strategy, start=100, page=8
            ),
            extracted(("요약정보", "주요투자 위험"), risk, start=200, page=9),
            extracted(("요약정보", "투자비용"), "excluded fee", start=300),
        ),
        requested_section_types=REQUESTED,
    )
    context = DocumentChunkContext(
        dataset_version="documents-kodex200-v1",
        document_id="dart:20260716000161:full-prospectus",
        canonical_entity_name="KODEX 200",
        document_type="full_prospectus",
        original_language="ko",
        budget_scope_id="domestic-etf:KR7069500007",
        requested_section_types=REQUESTED,
    )

    result = chunk_document_sections(
        context,
        selection.selected_sections,
        counter=WhitespaceTokenCounter(),
        target_min=0,
        target_max=800,
    )

    assert result.coverage_status is CoverageStatus.INDEXED
    assert len(result.chunks) == 2
    for chunk in result.chunks:
        assert chunk.dataset_version == context.dataset_version
        assert chunk.document_id == context.document_id
        assert chunk.page_start is not None
        assert chunk.page_end is not None
        assert chunk.section_path
        assert chunk.character_end > chunk.character_start
        assert chunk.exact_text in {strategy, risk}
        assert len(chunk.content_hash) == 64
    assert all("excluded fee" not in chunk.exact_text for chunk in result.chunks)
