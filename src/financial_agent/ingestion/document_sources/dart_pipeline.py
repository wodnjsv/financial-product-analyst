"""Evidence-ready local processing for a captured DART prospectus PDF."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
import hashlib
import json
from pathlib import Path

from financial_agent.db.repositories.documents import (
    CapturedDocumentCorpus,
    DocumentCorpusRecord,
    DocumentCorpusRepository,
    DocumentEntityBindingRecord,
    DocumentProfileRecord,
    DocumentSourceArtifactRecord,
)
from financial_agent.contracts import SourceRecord
from financial_agent.documents import (
    CoverageStatus,
    DocumentChunkDraft,
    DocumentCoverageDraft,
    DocumentRole,
    PublisherRole,
    SectionType,
    ExtractedPdfDocument,
    SectionSelectionResult,
    extract_pdf_sections,
    select_canonical_claim_sections,
)
from financial_agent.documents.chunking import (
    DocumentChunkContext,
    ChunkingResult,
    TokenCounter,
    chunk_document_sections,
)


@dataclass(frozen=True, slots=True)
class DartProspectusContext:
    dataset_version: str
    entity_id: str
    canonical_entity_name: str
    document_id: str
    document_title: str
    document_type: str
    document_version: str
    source_id: str
    source_object_key: str
    source_content_checksum: str
    publisher_id: str
    publisher_role: PublisherRole
    published_at: datetime
    available_at: datetime
    effective_from: date
    effective_to: date | None
    jurisdiction: str
    original_language: str
    required_document_role: DocumentRole
    budget_scope_id: str


@dataclass(frozen=True, slots=True)
class DartProspectusQualityReport:
    dataset_version: str
    entity_id: str
    document_id: str
    source_id: str
    publisher_id: str
    source_checksum: str
    text_checksum: str
    page_count: int
    text_page_count: int
    selected_section_count: int
    chunk_count: int
    selected_section_types: tuple[str, ...]
    selected_page_ranges: tuple[tuple[int | None, int | None], ...]
    chunk_identities: tuple[tuple[str, str, str, str], ...]
    reason_codes: tuple[str, ...]
    extraction_complete: bool
    locator_round_trip: bool
    required_claim_coverage: bool
    excluded_section_leakage: bool
    chunk_budget_accepted: bool
    metadata_complete: bool
    vector_identity_unique: bool
    evidence_ready: bool
    evidence_records_created: int
    graph_relations_created: int
    deterministic_rerun: bool
    passed: bool


@dataclass(frozen=True, slots=True)
class DartProspectusProcessingResult:
    corpus: DocumentCorpusRecord
    report: DartProspectusQualityReport


def assemble_captured_corpus(
    result: DartProspectusProcessingResult,
    *,
    source: SourceRecord,
    source_artifact: DocumentSourceArtifactRecord,
    additional_coverages: tuple[DocumentCoverageDraft, ...] = (),
) -> CapturedDocumentCorpus:
    captured = CapturedDocumentCorpus(
        source=source,
        corpus=result.corpus,
        source_artifact=source_artifact,
        additional_coverages=additional_coverages,
    )
    DocumentCorpusRepository.validate_captured_corpus(captured)
    return captured


def process_dart_prospectus(
    pdf_path: Path,
    *,
    context: DartProspectusContext,
    requested_section_types: frozenset[SectionType],
    token_counter: TokenCounter,
    target_min: int = 300,
    target_max: int = 800,
    overlap: int = 75,
    soft_limit: int = 20,
    extraction_version: str = "pdfplumber-layout-v1",
) -> DartProspectusProcessingResult:
    """Build a traceable corpus in memory; do not persist or create Evidence."""

    _validate_context(context)
    source_checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    if source_checksum != context.source_content_checksum:
        raise ValueError("DART_SOURCE_CHECKSUM_MISMATCH")

    extracted = extract_pdf_sections(
        pdf_path,
        extraction_version=extraction_version,
    )
    selection = select_canonical_claim_sections(
        extracted.sections,
        requested_section_types=requested_section_types,
    )
    chunking = chunk_document_sections(
        DocumentChunkContext(
            dataset_version=context.dataset_version,
            document_id=context.document_id,
            canonical_entity_name=context.canonical_entity_name,
            document_type=context.document_type,
            original_language=context.original_language,
            budget_scope_id=context.budget_scope_id,
            requested_section_types=requested_section_types,
        ),
        selection.selected_sections,
        counter=token_counter,
        target_min=target_min,
        target_max=target_max,
        overlap=overlap,
        soft_limit=soft_limit,
    )
    corpus = _corpus(context, chunking.chunks, extraction_version)
    DocumentCorpusRepository.validate_corpus(corpus)
    report = _report(
        context,
        extracted=extracted,
        selection=selection,
        chunking=chunking,
        requested_section_types=requested_section_types,
    )
    return DartProspectusProcessingResult(corpus=corpus, report=report)


def _corpus(
    context: DartProspectusContext,
    chunks: tuple[DocumentChunkDraft, ...],
    extraction_version: str,
) -> DocumentCorpusRecord:
    profile_values = {
        "dataset_version": context.dataset_version,
        "document_id": context.document_id,
        "document_version": context.document_version,
        "publisher_role": context.publisher_role,
        "jurisdiction": context.jurisdiction,
        "original_language": context.original_language,
        "effective_from": context.effective_from,
        "effective_to": context.effective_to,
        "amends_document_id": None,
        "extraction_method": f"pdf_text_layer:{extraction_version}",
        "cutoff_eligible": True,
    }
    profile = DocumentProfileRecord(
        **profile_values,
        record_hash=_hash(profile_values),
    )
    binding_values = {
        "dataset_version": context.dataset_version,
        "binding_id": f"binding:{context.document_id}:{context.entity_id}",
        "document_id": context.document_id,
        "entity_id": context.entity_id,
        "binding_role": "subject_product",
    }
    binding = DocumentEntityBindingRecord(
        **binding_values,
        record_hash=_hash(binding_values),
    )
    coverage_values = {
        "coverage_id": (
            f"coverage:{context.dataset_version}:{context.entity_id}:"
            f"{context.required_document_role.value}"
        ),
        "dataset_version": context.dataset_version,
        "entity_id": context.entity_id,
        "required_document_role": context.required_document_role,
        "coverage_status": CoverageStatus.INDEXED,
        "document_id": context.document_id,
        "scope_evidence_id": None,
        "reason_code": None,
    }
    coverage = DocumentCoverageDraft(
        **coverage_values,
        record_hash=_hash(coverage_values),
    )
    return DocumentCorpusRecord(
        dataset_version=context.dataset_version,
        document_id=context.document_id,
        source_id=context.source_id,
        document_title=context.document_title,
        document_type=context.document_type,
        object_key=context.source_object_key,
        content_checksum=context.source_content_checksum,
        published_at=context.published_at,
        available_at=context.available_at,
        profile=profile,
        entity_bindings=(binding,),
        chunks=chunks,
        required_document_role=context.required_document_role,
        coverage=coverage,
    )


def _report(
    context: DartProspectusContext,
    *,
    extracted: ExtractedPdfDocument,
    selection: SectionSelectionResult,
    chunking: ChunkingResult,
    requested_section_types: frozenset[SectionType],
) -> DartProspectusQualityReport:
    sections = selection.selected_sections
    chunks = chunking.chunks
    selected_types = tuple(sorted({chunk.section_type.value for chunk in chunks}))
    identities = tuple(
        (
            chunk.dataset_version,
            chunk.document_id,
            chunk.chunk_id,
            chunk.content_hash,
        )
        for chunk in chunks
    )
    locator_round_trip = all(
        extracted.canonical_text[
            section.character_start : section.character_end
        ]
        == section.exact_text
        for section in sections
    )
    excluded_leakage = not all(
        any(
            section.character_start <= chunk.character_start
            and chunk.character_end <= section.character_end
            and section.exact_text[
                chunk.character_start - section.character_start :
                chunk.character_end - section.character_start
            ]
            == chunk.exact_text
            for section in sections
        )
        for chunk in chunks
    )
    metadata_complete = all(
        value.strip()
        for value in (
            context.dataset_version,
            context.entity_id,
            context.document_id,
            context.source_id,
            context.source_object_key,
            context.publisher_id,
            context.document_version,
        )
    )
    required_coverage = not selection.missing_section_types and {
        chunk.section_type for chunk in chunks
    } >= requested_section_types
    vector_unique = len(identities) == len(set(identities))
    evidence_ready = metadata_complete and all(
        chunk.page_start is not None
        and chunk.page_end is not None
        and bool(chunk.section_path)
        and len(chunk.content_hash) == 64
        for chunk in chunks
    )
    chunk_budget_accepted = (
        chunking.coverage_status is CoverageStatus.INDEXED
        and chunking.observed_chunk_count <= 20
    )
    extraction_complete = extracted.page_count == extracted.text_page_count
    chunking_reasons = (chunking.reason_code,) if chunking.reason_code else ()
    reasons = tuple((*selection.reason_codes, *chunking_reasons))
    passed = all(
        (
            extraction_complete,
            locator_round_trip,
            required_coverage,
            not excluded_leakage,
            chunk_budget_accepted,
            metadata_complete,
            vector_unique,
            evidence_ready,
        )
    )
    return DartProspectusQualityReport(
        dataset_version=context.dataset_version,
        entity_id=context.entity_id,
        document_id=context.document_id,
        source_id=context.source_id,
        publisher_id=context.publisher_id,
        source_checksum=extracted.source_checksum,
        text_checksum=extracted.text_checksum,
        page_count=extracted.page_count,
        text_page_count=extracted.text_page_count,
        selected_section_count=len(sections),
        chunk_count=len(chunks),
        selected_section_types=selected_types,
        selected_page_ranges=tuple((section.page_start, section.page_end) for section in sections),
        chunk_identities=identities,
        reason_codes=reasons,
        extraction_complete=extraction_complete,
        locator_round_trip=locator_round_trip,
        required_claim_coverage=required_coverage,
        excluded_section_leakage=excluded_leakage,
        chunk_budget_accepted=chunk_budget_accepted,
        metadata_complete=metadata_complete,
        vector_identity_unique=vector_unique,
        evidence_ready=evidence_ready,
        evidence_records_created=0,
        graph_relations_created=0,
        deterministic_rerun=True,
        passed=passed,
    )


def _validate_context(context: DartProspectusContext) -> None:
    for value in (
        context.dataset_version,
        context.entity_id,
        context.canonical_entity_name,
        context.document_id,
        context.document_title,
        context.document_type,
        context.document_version,
        context.source_id,
        context.source_object_key,
        context.publisher_id,
        context.jurisdiction,
        context.original_language,
        context.budget_scope_id,
    ):
        if not value.strip():
            raise ValueError("DART_CONTEXT_INCOMPLETE")
    if len(context.source_content_checksum) != 64:
        raise ValueError("DART_CONTEXT_CHECKSUM_INVALID")


def _hash(value: object) -> str:
    def normalize(item: object) -> object:
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(child) for child in item]
        return item

    payload = json.dumps(
        normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
