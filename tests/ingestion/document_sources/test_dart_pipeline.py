from __future__ import annotations

from datetime import UTC, date, datetime
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from financial_agent.contracts import SourceRecord
from financial_agent.db.repositories import documents as document_repository
from financial_agent.db.repositories.documents import (
    DocumentCorpusRepository,
    DocumentSourceArtifactRecord,
)
from financial_agent.documents import DocumentRole, PublisherRole, SectionType
from financial_agent.documents.chunking import WhitespaceTokenCounter
from financial_agent.ingestion.document_sources.dart_pipeline import (
    DartProspectusContext,
    DartProspectusProcessingError,
    assemble_captured_corpus,
    process_dart_prospectus,
)
from tests.fixtures.synthetic_pdf import write_synthetic_prospectus


def prospectus(path: Path) -> Path:
    return write_synthetic_prospectus(path)


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
    assert result.report.observed_selected_token_count > 0
    assert result.report.counter_identity == "WhitespaceTokenCounter"
    assert result.report.passed


def test_pipeline_accepts_claim_chunks_over_the_retired_count_limit(
    tmp_path: Path,
) -> None:
    pdf_path = prospectus(tmp_path / "kodex200.pdf")
    checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    result = process_dart_prospectus(
        pdf_path,
        context=pipeline_context(checksum),
        requested_section_types=frozenset(
            {SectionType.INVESTMENT_STRATEGY, SectionType.RISK_FACTOR}
        ),
        token_counter=WhitespaceTokenCounter(),
        target_min=0,
        soft_limit=1,
    )

    assert len(result.corpus.chunks) > 1
    assert result.report.chunk_budget_accepted
    assert result.report.passed


def test_pipeline_reports_missing_requested_chunks_with_specific_reason(
    tmp_path: Path,
) -> None:
    pdf_path = prospectus(tmp_path / "kodex200.pdf")
    checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    with pytest.raises(DartProspectusProcessingError) as raised:
        process_dart_prospectus(
            pdf_path,
            context=pipeline_context(checksum),
            requested_section_types=frozenset({SectionType.INDEX_METHODOLOGY}),
            token_counter=WhitespaceTokenCounter(),
            target_min=0,
        )

    assert raised.value.code == "approved_section_not_found"


def test_pipeline_accepts_partial_claim_coverage_when_chunks_exist(
    tmp_path: Path,
) -> None:
    pdf_path = prospectus(tmp_path / "kodex200.pdf")
    checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    result = process_dart_prospectus(
        pdf_path,
        context=pipeline_context(checksum),
        requested_section_types=frozenset(
            {SectionType.INVESTMENT_STRATEGY, SectionType.INDEX_METHODOLOGY}
        ),
        token_counter=WhitespaceTokenCounter(),
        target_min=0,
    )

    assert result.corpus.chunks
    assert not result.report.required_claim_coverage
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


def test_pipeline_assembles_source_file_provenance_with_the_corpus(
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
    source = SourceRecord(
        source_id=context.source_id,
        publisher=context.publisher_id,
        publisher_type="regulator",
        source_title=context.document_title,
        source_type="filing",
        authority_tier="official_primary",
        source_locator_root=(
            "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260716000161"
        ),
        content_checksum=checksum,
        license_or_usage_note="metadata retained after local PDF deletion",
        eligible_for_claim=True,
    )
    artifact = DocumentSourceArtifactRecord(
        dataset_version=context.dataset_version,
        source_artifact_id="artifact:dart:20260716000161",
        source_id=context.source_id,
        document_id=context.document_id,
        receipt_id="20260716000161",
        original_filename="KODEX 200 투자설명서.pdf",
        filing_locator=source.source_locator_root,
        attachment_locator=(
            "https://dart.fss.or.kr/pdf/download/file.do?"
            "rcp_no=20260716000161&dcm_no=1&fl_nm=1"
        ),
        media_type="application/pdf",
        byte_count=pdf_path.stat().st_size,
        source_checksum=result.report.source_checksum,
        text_checksum=result.report.text_checksum,
        page_count=result.report.page_count,
        extraction_version="pdfplumber-layout-v1",
        retention_disposition="pending_delete",
        downloaded_at=datetime(2026, 8, 31, tzinfo=UTC),
        persisted_at=datetime(2026, 8, 31, 0, 1, tzinfo=UTC),
        verified_at=None,
        discarded_at=None,
        record_hash="0" * 64,
    )
    artifact = replace(
        artifact,
        record_hash=document_repository._source_artifact_record_hash(artifact),
    )

    captured = assemble_captured_corpus(
        result,
        source=source,
        source_artifact=artifact,
    )

    assert captured.corpus == result.corpus
    assert captured.source == source
    assert captured.source_artifact == artifact
    assert captured.additional_coverages == ()
