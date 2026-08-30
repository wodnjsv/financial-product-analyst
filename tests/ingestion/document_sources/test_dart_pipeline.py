from __future__ import annotations

from datetime import UTC, date, datetime
from dataclasses import replace
import hashlib
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from financial_agent.db.repositories.documents import DocumentCorpusRepository
from financial_agent.documents import DocumentRole, PublisherRole, SectionType
from financial_agent.documents.chunking import WhitespaceTokenCounter
from financial_agent.ingestion.document_sources.dart_pipeline import (
    DartProspectusContext,
    process_dart_prospectus,
)


def prospectus(path: Path) -> Path:
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    document = canvas.Canvas(str(path), pagesize=(595, 842))
    document.setFont("HYSMyeongJo-Medium", 14)
    document.drawString(50, 800, "요약정보")
    document.setFont("HYSMyeongJo-Medium", 10)
    document.drawString(50, 760, "투자목적 및 투자전략")
    document.drawString(50, 740, "KOSPI200 지수를 추종합니다.")
    document.drawString(50, 700, "주요투자위험")
    document.drawString(50, 680, "추적오차로 손실이 발생할 수 있습니다.")
    document.drawString(50, 640, "투자비용")
    document.drawString(50, 620, "제외할 비용 정보")
    document.save()
    return path


def pipeline_context(checksum: str) -> DartProspectusContext:
    return DartProspectusContext(
        dataset_version="documents-kodex200-v1",
        entity_id="domestic-etf:KR7069500007",
        canonical_entity_name="삼성 KODEX 200증권상장지수투자신탁[주식]",
        document_id="dart:20260716000161:full-prospectus",
        document_title="KODEX 200 투자설명서",
        document_type="full_prospectus",
        document_version="2026-07-03",
        source_id="source:dart:20260716000161",
        source_object_key="documents/dart/20260716000161/full-prospectus.pdf",
        source_content_checksum=checksum,
        publisher_id="institution:dart",
        publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
        published_at=datetime(2026, 7, 16, tzinfo=UTC),
        available_at=datetime(2026, 7, 16, tzinfo=UTC),
        effective_from=date(2026, 7, 16),
        effective_to=None,
        jurisdiction="KR",
        original_language="ko",
        required_document_role=DocumentRole.PRODUCT_FULL,
        budget_scope_id="domestic-etf:KR7069500007",
    )


def test_pipeline_builds_traceable_corpus_without_premature_evidence(
    tmp_path: Path,
) -> None:
    pdf_path = prospectus(tmp_path / "kodex200.pdf")
    checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    context = pipeline_context(checksum)

    result = process_dart_prospectus(
        pdf_path,
        context=context,
        requested_section_types=frozenset(
            {SectionType.INVESTMENT_STRATEGY, SectionType.RISK_FACTOR}
        ),
        token_counter=WhitespaceTokenCounter(),
        target_min=0,
    )

    corpus = result.corpus
    DocumentCorpusRepository.validate_corpus(corpus)
    assert corpus.dataset_version == context.dataset_version
    assert corpus.document_id == context.document_id
    assert corpus.source_id == context.source_id
    assert corpus.object_key == context.source_object_key
    assert corpus.content_checksum == context.source_content_checksum
    assert corpus.profile.document_version == context.document_version
    assert corpus.profile.publisher_role is context.publisher_role
    assert corpus.profile.effective_from == context.effective_from
    assert corpus.entity_bindings[0].entity_id == context.entity_id
    assert corpus.coverage.required_document_role is context.required_document_role
    assert {chunk.section_type for chunk in corpus.chunks} == {
        SectionType.INVESTMENT_STRATEGY,
        SectionType.RISK_FACTOR,
    }
    assert all(chunk.page_start and chunk.section_path for chunk in corpus.chunks)
    assert all(not hasattr(chunk, "evidence_id") for chunk in corpus.chunks)
    assert result.report.publisher_id == context.publisher_id
    assert result.report.metadata_complete
    assert result.report.locator_round_trip
    assert result.report.vector_identity_unique
    assert result.report.evidence_ready
    assert result.report.evidence_records_created == 0
    assert result.report.graph_relations_created == 0
    assert result.report.excluded_section_leakage is False
    assert result.report.passed


def test_pipeline_is_deterministic_and_rejects_wrong_source_checksum(
    tmp_path: Path,
) -> None:
    pdf_path = prospectus(tmp_path / "kodex200.pdf")
    checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    context = pipeline_context(checksum)
    requested = frozenset(
        {SectionType.INVESTMENT_STRATEGY, SectionType.RISK_FACTOR}
    )

    first = process_dart_prospectus(
        pdf_path,
        context=context,
        requested_section_types=requested,
        token_counter=WhitespaceTokenCounter(),
        target_min=0,
    )
    second = process_dart_prospectus(
        pdf_path,
        context=context,
        requested_section_types=requested,
        token_counter=WhitespaceTokenCounter(),
        target_min=0,
    )

    assert first == second

    bad_context = replace(context, source_content_checksum="0" * 64)
    try:
        process_dart_prospectus(
            pdf_path,
            context=bad_context,
            requested_section_types=requested,
            token_counter=WhitespaceTokenCounter(),
            target_min=0,
        )
    except ValueError as error:
        assert str(error) == "DART_SOURCE_CHECKSUM_MISMATCH"
    else:
        raise AssertionError("wrong checksum must be rejected")
