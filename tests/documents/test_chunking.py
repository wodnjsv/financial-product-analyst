from __future__ import annotations

import hashlib

import pytest

from financial_agent.documents import CoverageStatus, SectionType
from financial_agent.documents.chunking import (
    DocumentChunkContext,
    ExtractedSection,
    WhitespaceTokenCounter,
    chunk_document_sections,
    classify_section,
)


def context(document_id: str = "document-a") -> DocumentChunkContext:
    return DocumentChunkContext(
        dataset_version="2026-08-24",
        document_id=document_id,
        canonical_entity_name="Selected ETF",
        document_type="summary_prospectus",
        original_language="en",
    )


def section(
    heading_path: tuple[str, ...],
    exact_text: str = "approved section text",
    *,
    page_start: int | None = 1,
    page_end: int | None = 1,
    character_start: int = 0,
) -> ExtractedSection:
    return ExtractedSection(
        heading_path=heading_path,
        exact_text=exact_text,
        page_start=page_start,
        page_end=page_end,
        character_start=character_start,
        character_end=character_start + len(exact_text),
    )


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        (("투자목적 및 투자전략",), SectionType.INVESTMENT_STRATEGY),
        (("투자위험", "환율변동위험"), SectionType.RISK_FACTOR),
        (("Principal Investment Strategies",), SectionType.INVESTMENT_STRATEGY),
        (("Principal Risks", "Index-Related Risk"), SectionType.RISK_FACTOR),
        (("Index Methodology", "Rebalancing"), SectionType.REBALANCING),
    ],
)
def test_classifies_only_approved_sections(
    heading: tuple[str, ...], expected: SectionType
) -> None:
    assert classify_section(section(heading)) is expected


@pytest.mark.parametrize(
    "heading",
    [
        ("Fees and Expenses",),
        ("Distributions and Redemptions",),
        ("Taxation",),
        ("Accounting Policies",),
        ("Legal Notice",),
        ("Portfolio Holdings",),
        ("Historical Performance",),
        ("Financial Statements",),
        ("Market Commentary",),
    ],
)
def test_rejects_disallowed_operational_or_marketing_sections(
    heading: tuple[str, ...],
) -> None:
    assert classify_section(section(heading)) is None


def test_excludes_performance_and_holdings_tables() -> None:
    result = chunk_document_sections(
        context(),
        (
            section(("Principal Risks",), "risk text", character_start=0),
            section(
                ("Historical Performance",), "performance text", character_start=100
            ),
            section(("Portfolio Holdings",), "holding rows", character_start=200),
        ),
        counter=WhitespaceTokenCounter(),
    )

    assert {chunk.section_type for chunk in result.chunks} == {
        SectionType.RISK_FACTOR
    }
    assert result.coverage_status is CoverageStatus.INDEXED


def test_preserves_exact_text_and_uses_only_embedding_prefixes_for_search() -> None:
    exact_text = "Original risk text.\n\nSecond paragraph."
    result = chunk_document_sections(
        context(),
        (section(("Principal Risks",), exact_text),),
        counter=WhitespaceTokenCounter(),
    )

    chunk = result.chunks[0]
    assert chunk.exact_text == exact_text
    assert chunk.character_start == 0
    assert chunk.character_end == len(exact_text)
    assert chunk.embedding_text == "\n".join(
        ("Selected ETF", "summary_prospectus", "Principal Risks", exact_text)
    )
    assert chunk.content_hash == hashlib.sha256(exact_text.encode()).hexdigest()


def test_overlap_is_limited_to_its_own_section() -> None:
    first = "one two three\n\nfour five six\n\nseven eight nine"
    second = "ten eleven twelve\n\nthirteen fourteen fifteen"
    result = chunk_document_sections(
        context(),
        (
            section(("Principal Risks",), first, character_start=0),
            section(("Investment Objective",), second, character_start=100),
        ),
        counter=WhitespaceTokenCounter(),
        target_min=0,
        target_max=6,
        overlap=3,
    )

    risk_chunks = [
        chunk for chunk in result.chunks if chunk.section_type is SectionType.RISK_FACTOR
    ]
    objective_chunks = [
        chunk
        for chunk in result.chunks
        if chunk.section_type is SectionType.INVESTMENT_OBJECTIVE
    ]
    assert len(risk_chunks) == 2
    assert risk_chunks[1].exact_text.startswith("four five six")
    assert all("nine" not in chunk.exact_text for chunk in objective_chunks)
    assert all(chunk.character_start >= 100 for chunk in objective_chunks)


def test_keeps_an_oversized_risk_bullet_intact() -> None:
    bullet = "- this risk bullet must remain a single evidence span"
    result = chunk_document_sections(
        context(),
        (section(("Principal Risks",), bullet),),
        counter=WhitespaceTokenCounter(),
        target_min=0,
        target_max=4,
    )

    assert tuple(chunk.exact_text for chunk in result.chunks) == (bullet,)


def test_removes_duplicate_paragraphs_without_rewriting_original_evidence() -> None:
    first = section(("Principal Risks",), "duplicate paragraph", character_start=0)
    second = section(
        ("Principal Risks",), "duplicate paragraph", character_start=100
    )
    result = chunk_document_sections(
        context(),
        (first, second),
        counter=WhitespaceTokenCounter(),
        target_min=0,
        target_max=3,
    )

    assert tuple(chunk.exact_text for chunk in result.chunks) == ("duplicate paragraph",)


def test_exposes_section_and_document_budget_review_without_truncation() -> None:
    required_risks = "\n".join(f"- risk-{index}" for index in range(21))

    result = chunk_document_sections(
        context(),
        (section(("Principal Risks",), required_risks),),
        counter=WhitespaceTokenCounter(),
        target_min=0,
        target_max=1,
        overlap=0,
        soft_limit=20,
    )

    assert result.coverage_status is CoverageStatus.REVIEW_REQUIRED_CHUNK_BUDGET
    assert result.reason_code == "soft_chunk_limit_exceeded"
    assert result.observed_chunk_count == 21
    assert result.chunks[-1].exact_text == "- risk-20"


def test_is_deterministic_and_does_not_mix_document_contexts() -> None:
    sections = (
        section(("Investment Objective",), "objective", character_start=100),
        section(("Principal Risks",), "risk", character_start=0),
    )
    reversed_sections = tuple(reversed(sections))

    first = chunk_document_sections(
        context("product-a-document"),
        sections,
        counter=WhitespaceTokenCounter(),
    )
    same = chunk_document_sections(
        context("product-a-document"),
        reversed_sections,
        counter=WhitespaceTokenCounter(),
    )
    other = chunk_document_sections(
        context("product-b-document"),
        sections,
        counter=WhitespaceTokenCounter(),
    )

    assert first.chunks == same.chunks
    assert {chunk.document_id for chunk in first.chunks} == {"product-a-document"}
    assert {chunk.document_id for chunk in other.chunks} == {"product-b-document"}
    assert {chunk.chunk_id for chunk in first.chunks}.isdisjoint(
        {chunk.chunk_id for chunk in other.chunks}
    )
