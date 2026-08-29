from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from financial_agent.documents import CoverageStatus, SectionType
from financial_agent.documents.chunking import (
    DocumentChunkContext,
    ExtractedSection,
    WhitespaceTokenCounter,
    aggregate_chunking_results,
    chunk_document_sections,
    classify_section,
)


def context(
    document_id: str = "document-a",
    *,
    dataset_version: str = "2026-08-24",
    budget_scope_id: str = "product-a",
    requested_section_types: frozenset[SectionType] = frozenset(),
) -> DocumentChunkContext:
    return DocumentChunkContext(
        dataset_version=dataset_version,
        document_id=document_id,
        canonical_entity_name="Selected ETF",
        document_type="summary_prospectus",
        original_language="en",
        budget_scope_id=budget_scope_id,
        requested_section_types=requested_section_types,
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
    assert result.coverage_status is CoverageStatus.REVIEW_REQUIRED_CHUNK_BUDGET
    assert result.reason_code == "indivisible_unit_over_target_max"


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
        target_max=2,
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


def words(count: int, prefix: str) -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def test_splits_ordinary_long_prose_within_target_max() -> None:
    prose = "one two three four five. six seven eight nine ten."
    result = chunk_document_sections(
        context(),
        (section(("Principal Risks",), prose),),
        counter=WhitespaceTokenCounter(),
        target_min=0,
        target_max=5,
        overlap=0,
    )

    assert result.coverage_status is CoverageStatus.INDEXED
    assert tuple(WhitespaceTokenCounter().count(chunk.exact_text) for chunk in result.chunks) == (5, 5)
    assert "".join(chunk.exact_text for chunk in result.chunks) == prose


def test_retains_an_unbroken_over_budget_unit_only_with_review_status() -> None:
    class CharacterCounter:
        def count(self, text: str) -> int:
            return len(text)

    text = "unbroken"
    result = chunk_document_sections(
        context(),
        (section(("Principal Risks",), text),),
        counter=CharacterCounter(),
        target_min=0,
        target_max=4,
        overlap=0,
    )

    assert tuple(chunk.exact_text for chunk in result.chunks) == (text,)
    assert result.coverage_status is CoverageStatus.REVIEW_REQUIRED_CHUNK_BUDGET
    assert result.reason_code == "indivisible_unit_over_target_max"


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        (("Principal   Risks",), SectionType.RISK_FACTOR),
        (("Principal\nRisks",), SectionType.RISK_FACTOR),
        (("투자 위험",), SectionType.RISK_FACTOR),
        (("투자 목적\n및 투자 전략",), SectionType.INVESTMENT_STRATEGY),
        (("통화 헤지",), SectionType.CURRENCY_HEDGE),
        (("파생 상품 및 레버리지",), SectionType.DERIVATIVES_LEVERAGE),
    ],
)
def test_normalizes_explicit_heading_aliases(
    heading: tuple[str, ...], expected: SectionType
) -> None:
    assert classify_section(
        section(heading), requested_section_types=frozenset({expected})
    ) is expected


@pytest.mark.parametrize(
    "heading",
    [
        ("Research Methodology",),
        ("Appendix: Principal Risks",),
        ("부록: 투자위험",),
    ],
)
def test_registry_rejects_false_positive_and_appendix_headings(
    heading: tuple[str, ...],
) -> None:
    assert classify_section(section(heading)) is None


def test_admits_conditional_sections_only_for_an_explicit_claim_context() -> None:
    hedge = section(("Currency Hedge",), "hedge policy")

    default_result = chunk_document_sections(
        context(), (hedge,), counter=WhitespaceTokenCounter()
    )
    requested_result = chunk_document_sections(
        context(requested_section_types=frozenset({SectionType.CURRENCY_HEDGE})),
        (hedge,),
        counter=WhitespaceTokenCounter(),
    )

    assert classify_section(hedge) is None
    assert default_result.coverage_status is CoverageStatus.SECTION_MISSING
    assert requested_result.chunks[0].section_type is SectionType.CURRENCY_HEDGE


def test_aggregates_budget_across_documents_in_one_explicit_scope() -> None:
    risks = "\n".join(f"- risk-{index}" for index in range(11))
    first = chunk_document_sections(
        context("document-a", budget_scope_id="product-a"),
        (section(("Principal Risks",), risks),),
        counter=WhitespaceTokenCounter(),
        target_min=0,
        target_max=2,
        overlap=0,
    )
    second = chunk_document_sections(
        context("document-b", budget_scope_id="product-a"),
        (section(("Principal Risks",), risks.replace("risk-", "other-")),),
        counter=WhitespaceTokenCounter(),
        target_min=0,
        target_max=2,
        overlap=0,
    )

    aggregate = aggregate_chunking_results((second, first), soft_limit=20)

    assert first.coverage_status is CoverageStatus.INDEXED
    assert second.coverage_status is CoverageStatus.INDEXED
    assert aggregate.budget_scope_id == "product-a"
    assert aggregate.observed_chunk_count == 22
    assert aggregate.over_budget is True
    assert tuple(result.document_id for result in aggregate.member_results) == (
        "document-a",
        "document-b",
    )


def test_refuses_to_aggregate_different_budget_scopes() -> None:
    first = chunk_document_sections(
        context("document-a", budget_scope_id="product-a"),
        (section(("Principal Risks",), "risk-a"),),
        counter=WhitespaceTokenCounter(),
    )
    second = chunk_document_sections(
        context("document-b", budget_scope_id="product-b"),
        (section(("Principal Risks",), "risk-b"),),
        counter=WhitespaceTokenCounter(),
    )

    with pytest.raises(ValueError, match="one budget scope"):
        aggregate_chunking_results((first, second), soft_limit=20)


@pytest.mark.parametrize(
    "invalid_section",
    [
        ExtractedSection(("Principal Risks",), "risk", -1, 1, 0, 4),
        ExtractedSection(("Principal Risks",), "risk", 0, 0, 0, 4),
        ExtractedSection(("Principal Risks",), "risk", 2, 1, 0, 4),
        ExtractedSection(("Principal Risks",), "risk", 1, None, 0, 4),
        ExtractedSection(("Principal Risks",), "risk", 1, 1, -1, 3),
        ExtractedSection(("Principal Risks",), "risk", 1, 1, 0, 3),
    ],
)
def test_rejects_invalid_authoritative_source_ranges(
    invalid_section: ExtractedSection,
) -> None:
    with pytest.raises(ValueError, match="section"):
        chunk_document_sections(
            context(), (invalid_section,), counter=WhitespaceTokenCounter()
        )


def test_record_hash_changes_when_an_authoritative_page_locator_changes() -> None:
    first = chunk_document_sections(
        context(),
        (section(("Principal Risks",), "risk", page_start=1, page_end=1),),
        counter=WhitespaceTokenCounter(),
    )
    second = chunk_document_sections(
        context(),
        (section(("Principal Risks",), "risk", page_start=2, page_end=2),),
        counter=WhitespaceTokenCounter(),
    )

    assert first.chunks[0].record_hash != second.chunks[0].record_hash


def test_uses_target_min_to_rebalance_a_short_terminal_group() -> None:
    paragraphs = "\n\n".join((words(500, "a"), words(250, "b"), words(250, "c")))
    result = chunk_document_sections(
        context(),
        (section(("Principal Risks",), paragraphs),),
        counter=WhitespaceTokenCounter(),
        target_min=300,
        target_max=800,
        overlap=0,
    )

    assert tuple(WhitespaceTokenCounter().count(chunk.exact_text) for chunk in result.chunks) == (500, 500)


def test_never_exceeds_overlap_token_budget() -> None:
    paragraphs = "\n\n".join((words(500, "a"), words(200, "b"), words(200, "c")))
    result = chunk_document_sections(
        context(),
        (section(("Principal Risks",), paragraphs),),
        counter=WhitespaceTokenCounter(),
        target_min=0,
        target_max=800,
        overlap=75,
    )

    assert len(result.chunks) == 2
    assert result.chunks[1].exact_text.lstrip().startswith("c0")


def test_uses_exact_heading_path_as_a_permutation_independent_tie_break() -> None:
    upper = section(("Principal Risks",), "same risk")
    lower = section(("principal risks",), "same risk")

    first = chunk_document_sections(
        context(), (lower, upper), counter=WhitespaceTokenCounter()
    )
    second = chunk_document_sections(
        context(), (upper, lower), counter=WhitespaceTokenCounter()
    )

    assert first.chunks == second.chunks
    assert first.chunks[0].section_path == "Principal Risks"


def test_marks_a_late_indivisible_token_over_budget_for_review() -> None:
    class CharacterCounter:
        def count(self, text: str) -> int:
            return len(text)

    result = chunk_document_sections(
        context(),
        (section(("Principal Risks",), "aa LONGGGGG bb"),),
        counter=CharacterCounter(),
        target_min=0,
        target_max=4,
        overlap=0,
    )

    assert result.coverage_status is CoverageStatus.REVIEW_REQUIRED_CHUNK_BUDGET
    assert result.reason_code == "indivisible_unit_over_target_max"


@pytest.mark.parametrize(
    "counter",
    [
        WhitespaceTokenCounter(),
        type("CharacterCounter", (), {"count": lambda self, text: len(text)})(),
        type("DoubleCounter", (), {"count": lambda self, text: len(text.split()) * 2})(),
    ],
)
def test_indexed_chunks_never_exceed_the_injected_maximum(counter: object) -> None:
    result = chunk_document_sections(
        context(),
        (section(("Principal Risks",), "one two three. four five six."),),
        counter=counter,  # type: ignore[arg-type]
        target_min=0,
        target_max=8,
        overlap=0,
    )

    if result.coverage_status is CoverageStatus.INDEXED:
        assert all(counter.count(chunk.exact_text) <= 8 for chunk in result.chunks)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("heading", "requested", "expected"),
    [
        (
            ("Principal Risks", "Currency Hedge"),
            frozenset({SectionType.CURRENCY_HEDGE}),
            SectionType.CURRENCY_HEDGE,
        ),
        (
            ("Investment Strategy", "Governance"),
            frozenset({SectionType.GOVERNANCE}),
            SectionType.GOVERNANCE,
        ),
        (
            ("Index Methodology", "Selection Rules"),
            frozenset(),
            SectionType.SELECTION_RULES,
        ),
        (
            ("Official Update", "Change History"),
            frozenset(),
            SectionType.CHANGE_HISTORY,
        ),
    ],
)
def test_classifies_deepest_approved_heading_before_parent_fallback(
    heading: tuple[str, ...],
    requested: frozenset[SectionType],
    expected: SectionType,
) -> None:
    assert classify_section(
        section(heading), requested_section_types=requested
    ) is expected


@pytest.mark.parametrize(
    "heading",
    [
        ("General Legal Notice", "Fund Structure"),
        ("일반 법적 고지", "펀드 구조"),
        ("Appendix-I", "Principal Risks"),
        ("Appendix 1", "Principal Risks"),
        ("부록-1", "투자위험"),
        ("부록 IV", "투자위험"),
    ],
)
def test_exclusion_in_any_heading_ancestor_rejects_the_whole_path(
    heading: tuple[str, ...],
) -> None:
    assert classify_section(section(heading)) is None


def test_scope_budget_rejects_mixed_dataset_versions_and_duplicate_documents() -> None:
    first = chunk_document_sections(
        context("document-a", dataset_version="v1"),
        (section(("Principal Risks",), "risk-a"),),
        counter=WhitespaceTokenCounter(),
    )
    different_version = chunk_document_sections(
        context("document-b", dataset_version="v2"),
        (section(("Principal Risks",), "risk-b"),),
        counter=WhitespaceTokenCounter(),
    )

    with pytest.raises(ValueError, match="one dataset version"):
        aggregate_chunking_results((first, different_version), soft_limit=20)
    with pytest.raises(ValueError, match="duplicate document"):
        aggregate_chunking_results((first, first), soft_limit=20)


def test_scope_budget_rejects_duplicate_chunk_identities() -> None:
    result = chunk_document_sections(
        context("document-a"),
        (section(("Principal Risks",), "risk-a"),),
        counter=WhitespaceTokenCounter(),
    )
    duplicate_chunks = replace(
        result,
        chunks=(result.chunks[0], result.chunks[0]),
        observed_chunk_count=2,
    )

    with pytest.raises(ValueError, match="duplicate chunk"):
        aggregate_chunking_results((duplicate_chunks,), soft_limit=20)


def test_scope_budget_preserves_negative_member_statuses_without_coverage_result() -> None:
    indexed = chunk_document_sections(
        context("document-a"),
        (section(("Principal Risks",), "risk-a"),),
        counter=WhitespaceTokenCounter(),
    )
    missing = chunk_document_sections(
        context("document-b"),
        (section(("Fees and Expenses",), "fee"),),
        counter=WhitespaceTokenCounter(),
    )

    scope_budget = aggregate_chunking_results((indexed, missing), soft_limit=20)

    assert not hasattr(scope_budget, "coverage_status")
    assert {result.coverage_status for result in scope_budget.member_results} == {
        CoverageStatus.INDEXED,
        CoverageStatus.SECTION_MISSING,
    }
