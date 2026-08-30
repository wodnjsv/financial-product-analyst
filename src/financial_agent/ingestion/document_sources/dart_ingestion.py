"""Transactional DART corpus ingestion and exact-file cleanup."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Callable

from financial_agent.contracts import SourceRecord
from financial_agent.db.repositories.documents import (
    CapturedDocumentCorpus,
    DocumentCorpusNotFound,
    DocumentCorpusRepository,
    DocumentEntityBindingRecord,
    DocumentSourceArtifactRecord,
    captured_corpus_hash,
    source_artifact_record_hash,
)
from financial_agent.documents import (
    CoverageStatus,
    DocumentCoverageDraft,
    DocumentSourceCandidate,
    SectionType,
)
from financial_agent.documents.chunking import TokenCounter

from .base import NoRedirectHttpOpener
from .dart_capture import capture_dart_full_prospectus
from .dart_pipeline import (
    DartProspectusContext,
    DartProspectusProcessingResult,
    assemble_captured_corpus,
    process_dart_prospectus,
)
from .dart_targets import OrganizerDartTarget


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CUTOFF = date(2026, 8, 24)
_QUARANTINE_FILE_LIMIT = 5
_QUARANTINE_BYTE_LIMIT = 100 * 1024 * 1024


class DartCorpusIngestionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DartCorpusIngestionRequest:
    run_root: Path
    target: OrganizerDartTarget
    candidate: DocumentSourceCandidate
    context: DartProspectusContext
    requested_section_types: frozenset[SectionType]
    token_counter: TokenCounter
    maximum_bytes: int
    target_min: int = 300
    target_max: int = 800
    overlap: int = 75
    soft_limit: int = 20
    extraction_version: str = "pdfplumber-layout-v1"


@dataclass(frozen=True, slots=True)
class DartCorpusIngestionResult:
    dataset_version: str
    document_id: str
    pdf_path: Path
    retention_disposition: str
    readback_verified: bool
    deleted_bytes: int
    processing: DartProspectusProcessingResult | None


def _after_stage(stage: str) -> None:
    """Test seam for simulating process interruption at durable boundaries."""

    del stage


async def ingest_one_dart_document(
    repository: DocumentCorpusRepository,
    opener: NoRedirectHttpOpener,
    *,
    request: DartCorpusIngestionRequest,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DartCorpusIngestionResult:
    """Persist one organizer-bound DART document, verify it, then discard it."""

    _validate_request(request)
    receipt = request.candidate.accession_or_receipt_id
    assert receipt is not None
    document_root = request.run_root / f"dart-{receipt}"
    pdf_path = document_root / "source.pdf"

    existing = await _find_existing(repository, request)
    if existing is not None:
        _validate_existing_identity(existing, request)
        state = existing.source_artifact.retention_disposition
        if state == "metadata_only_deleted":
            _remove_empty_directory(document_root)
            return _result(request, pdf_path, state, True, 0, None)
        if state == "delete_authorized":
            deleted_bytes = 0
            if pdf_path.exists():
                deleted_bytes = safe_discard_verified_pdf(
                    run_root=request.run_root,
                    pdf_path=pdf_path,
                    expected_checksum=existing.source_artifact.source_checksum,
                    transaction_committed=True,
                    readback_verified=True,
                    retention_disposition=state,
                )
            _after_stage("pdf_deleted")
            completed = await repository.transition_source_retention(
                request.context.dataset_version,
                request.context.document_id,
                "metadata_only_deleted",
                occurred_at=now(),
            )
            _remove_empty_directory(document_root)
            return _result(
                request,
                pdf_path,
                completed.retention_disposition,
                True,
                deleted_bytes,
                None,
            )
        if state != "pending_delete" or not pdf_path.is_file():
            raise DartCorpusIngestionError("dart_ingestion_resume_source_missing")
    else:
        if pdf_path.exists():
            raise DartCorpusIngestionError("dart_ingestion_untracked_pdf")
        _reserve_quarantine_capacity(request)
        document_root.mkdir(parents=True, exist_ok=False)

    captured_at = now()
    if existing is None:
        captured_file = capture_dart_full_prospectus(
            opener,
            candidate=request.candidate,
            canonical_name=request.target.canonical_name,
            destination=pdf_path,
            maximum_bytes=request.maximum_bytes,
        )
        context = replace(
            request.context,
            source_object_key=captured_file.object_key,
            source_content_checksum=captured_file.sha256,
        )
    else:
        captured_file = None
        context = replace(
            request.context,
            source_object_key=existing.corpus.object_key,
            source_content_checksum=existing.source_artifact.source_checksum,
        )

    processing = process_dart_prospectus(
        pdf_path,
        context=context,
        requested_section_types=request.requested_section_types,
        token_counter=request.token_counter,
        target_min=request.target_min,
        target_max=request.target_max,
        overlap=request.overlap,
        soft_limit=request.soft_limit,
        extraction_version=request.extraction_version,
    )
    processing, additional_coverages = _bind_target_members(
        processing, request.target
    )
    if existing is None:
        assert captured_file is not None
        source = _source_record(request, context.source_content_checksum)
        artifact = _source_artifact(
            request,
            processing,
            original_filename=captured_file.object_name,
            attachment_locator=captured_file.attachment_locator,
            byte_count=captured_file.size_bytes,
            captured_at=captured_at,
            persisted_at=now(),
        )
    else:
        source = existing.source
        artifact = existing.source_artifact
    expected = assemble_captured_corpus(
        processing,
        source=source,
        source_artifact=artifact,
        additional_coverages=additional_coverages,
    )
    await repository.append_captured_corpus(expected)
    _after_stage("committed")
    readback = await repository.get_captured_corpus(
        context.dataset_version, context.document_id
    )
    if captured_corpus_hash(readback) != captured_corpus_hash(expected):
        raise DartCorpusIngestionError("dart_corpus_readback_mismatch")
    _after_stage("read_back")
    authorized = await repository.transition_source_retention(
        context.dataset_version,
        context.document_id,
        "delete_authorized",
        occurred_at=now(),
    )
    _after_stage("delete_authorized")
    deleted_bytes = safe_discard_verified_pdf(
        run_root=request.run_root,
        pdf_path=pdf_path,
        expected_checksum=authorized.source_checksum,
        transaction_committed=True,
        readback_verified=True,
        retention_disposition=authorized.retention_disposition,
    )
    _after_stage("pdf_deleted")
    completed = await repository.transition_source_retention(
        context.dataset_version,
        context.document_id,
        "metadata_only_deleted",
        occurred_at=now(),
    )
    _remove_empty_directory(document_root)
    return _result(
        request,
        pdf_path,
        completed.retention_disposition,
        True,
        deleted_bytes,
        processing,
    )


async def _find_existing(
    repository: DocumentCorpusRepository,
    request: DartCorpusIngestionRequest,
) -> CapturedDocumentCorpus | None:
    try:
        return await repository.get_captured_corpus(
            request.context.dataset_version, request.context.document_id
        )
    except DocumentCorpusNotFound:
        return None


def _validate_existing_identity(
    existing: CapturedDocumentCorpus,
    request: DartCorpusIngestionRequest,
) -> None:
    receipt = request.candidate.accession_or_receipt_id
    bindings = {
        binding.entity_id for binding in existing.corpus.entity_bindings
    }
    coverages = {
        existing.corpus.coverage.entity_id,
        *(item.entity_id for item in existing.additional_coverages),
    }
    if (
        existing.source_artifact.receipt_id != receipt
        or existing.source.source_id != request.context.source_id
        or existing.corpus.source_id != request.context.source_id
        or existing.corpus.object_key != request.context.source_object_key
        or existing.corpus.document_title != request.context.document_title
        or existing.corpus.profile.document_version
        != request.context.document_version
        or bindings != set(request.target.member_entity_ids)
        or coverages != bindings
    ):
        raise DartCorpusIngestionError(
            "dart_ingestion_existing_identity_mismatch"
        )


def _validate_request(request: DartCorpusIngestionRequest) -> None:
    candidate = request.candidate
    target = request.target
    context = request.context
    receipt = candidate.accession_or_receipt_id
    if (
        candidate.target_entity_id != target.representative_entity_id
        or context.entity_id != target.representative_entity_id
        or context.canonical_entity_name != target.canonical_name
        or context.entity_id not in target.member_entity_ids
    ):
        raise DartCorpusIngestionError("dart_target_not_in_organizer_inventory")
    if (
        candidate.source_code != "DART"
        or candidate.document_type != "full_prospectus"
        or candidate.authority_tier.value != "tier_1_regulatory"
        or receipt is None
        or context.document_id != f"dart:{receipt}:full-prospectus"
        or context.source_id != f"source:dart:{receipt}"
        or context.source_object_key
        != f"documents/dart/{receipt}/full-prospectus.pdf"
        or candidate.published_at is None
        or candidate.available_at is None
        or candidate.effective_from is None
        or candidate.published_at.date() > _CUTOFF
        or candidate.available_at.date() > _CUTOFF
        or candidate.effective_from > _CUTOFF
    ):
        raise DartCorpusIngestionError("dart_candidate_not_cutoff_eligible")
    if not request.run_root.is_absolute() or request.run_root.is_symlink():
        raise DartCorpusIngestionError("dart_run_root_invalid")
    if (
        isinstance(request.maximum_bytes, bool)
        or request.maximum_bytes <= 0
        or request.maximum_bytes > _QUARANTINE_BYTE_LIMIT
    ):
        raise DartCorpusIngestionError("dart_maximum_bytes_invalid")


def _source_record(
    request: DartCorpusIngestionRequest, checksum: str
) -> SourceRecord:
    context = request.context
    return SourceRecord(
        source_id=context.source_id,
        publisher=context.publisher_id,
        publisher_type="regulator",
        source_title=context.document_title,
        source_type="filing",
        authority_tier="official_primary",
        source_locator_root=request.candidate.source_locator,
        content_checksum=checksum,
        license_or_usage_note="metadata retained after local PDF deletion",
        eligible_for_claim=True,
    )


def _source_artifact(
    request: DartCorpusIngestionRequest,
    processing: DartProspectusProcessingResult,
    *,
    original_filename: str,
    attachment_locator: str,
    byte_count: int,
    captured_at: datetime,
    persisted_at: datetime,
) -> DocumentSourceArtifactRecord:
    receipt = request.candidate.accession_or_receipt_id
    assert receipt is not None
    artifact = DocumentSourceArtifactRecord(
        dataset_version=request.context.dataset_version,
        source_artifact_id=f"artifact:dart:{receipt}",
        source_id=request.context.source_id,
        document_id=request.context.document_id,
        receipt_id=receipt,
        original_filename=original_filename,
        filing_locator=request.candidate.source_locator,
        attachment_locator=attachment_locator,
        media_type="application/pdf",
        byte_count=byte_count,
        source_checksum=processing.report.source_checksum,
        text_checksum=processing.report.text_checksum,
        page_count=processing.report.page_count,
        extraction_version=request.extraction_version,
        retention_disposition="pending_delete",
        downloaded_at=captured_at,
        persisted_at=persisted_at,
        verified_at=None,
        discarded_at=None,
        record_hash="0" * 64,
    )
    return replace(artifact, record_hash=source_artifact_record_hash(artifact))


def _bind_target_members(
    processing: DartProspectusProcessingResult,
    target: OrganizerDartTarget,
) -> tuple[DartProspectusProcessingResult, tuple[DocumentCoverageDraft, ...]]:
    corpus = processing.corpus
    member_ids = tuple(sorted(target.member_entity_ids))
    bindings = tuple(
        DocumentEntityBindingRecord(
            dataset_version=corpus.dataset_version,
            binding_id=f"binding:{corpus.document_id}:{entity_id}",
            document_id=corpus.document_id,
            entity_id=entity_id,
            binding_role="subject_product",
            record_hash=_metadata_hash(
                {
                    "dataset_version": corpus.dataset_version,
                    "binding_id": f"binding:{corpus.document_id}:{entity_id}",
                    "document_id": corpus.document_id,
                    "entity_id": entity_id,
                    "binding_role": "subject_product",
                }
            ),
        )
        for entity_id in member_ids
    )
    coverages = tuple(
        _coverage(corpus, entity_id) for entity_id in member_ids
    )
    updated_corpus = replace(
        corpus,
        entity_bindings=bindings,
        coverage=coverages[0],
    )
    return replace(processing, corpus=updated_corpus), coverages[1:]


def _coverage(corpus, entity_id: str) -> DocumentCoverageDraft:
    values = {
        "coverage_id": (
            f"coverage:{corpus.dataset_version}:{entity_id}:"
            f"{corpus.required_document_role.value}"
        ),
        "dataset_version": corpus.dataset_version,
        "entity_id": entity_id,
        "required_document_role": corpus.required_document_role,
        "coverage_status": CoverageStatus.INDEXED,
        "document_id": corpus.document_id,
        "scope_evidence_id": None,
        "reason_code": None,
    }
    return DocumentCoverageDraft(**values, record_hash=_metadata_hash(values))


def _metadata_hash(value: object) -> str:
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

    return hashlib.sha256(
        json.dumps(
            normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _reserve_quarantine_capacity(request: DartCorpusIngestionRequest) -> None:
    root = request.run_root
    if not root.exists():
        return
    count = 0
    byte_count = 0
    for path in root.rglob("*.pdf"):
        if path.is_symlink() or not path.is_file():
            raise DartCorpusIngestionError("dart_quarantine_path_invalid")
        count += 1
        byte_count += path.stat().st_size
    if (
        count >= _QUARANTINE_FILE_LIMIT
        or byte_count + request.maximum_bytes > _QUARANTINE_BYTE_LIMIT
    ):
        raise DartCorpusIngestionError("dart_quarantine_limit_reached")


def _remove_empty_directory(path: Path) -> None:
    try:
        path.rmdir()
    except (FileNotFoundError, OSError):
        pass


def _result(
    request: DartCorpusIngestionRequest,
    pdf_path: Path,
    retention_disposition: str,
    readback_verified: bool,
    deleted_bytes: int,
    processing: DartProspectusProcessingResult | None,
) -> DartCorpusIngestionResult:
    return DartCorpusIngestionResult(
        dataset_version=request.context.dataset_version,
        document_id=request.context.document_id,
        pdf_path=pdf_path,
        retention_disposition=retention_disposition,
        readback_verified=readback_verified,
        deleted_bytes=deleted_bytes,
        processing=processing,
    )


def safe_discard_verified_pdf(
    *,
    run_root: Path,
    pdf_path: Path,
    expected_checksum: str,
    transaction_committed: bool,
    readback_verified: bool,
    retention_disposition: str,
) -> int:
    if (
        not transaction_committed
        or not readback_verified
        or retention_disposition != "delete_authorized"
    ):
        raise DartCorpusIngestionError("dart_pdf_cleanup_not_authorized")
    if _SHA256.fullmatch(expected_checksum) is None:
        raise DartCorpusIngestionError("dart_pdf_cleanup_checksum_mismatch")
    if (
        not run_root.is_absolute()
        or not pdf_path.is_absolute()
        or run_root.is_symlink()
        or pdf_path.is_symlink()
        or not run_root.is_dir()
        or not pdf_path.is_file()
    ):
        raise DartCorpusIngestionError("dart_pdf_cleanup_path_invalid")
    try:
        root = run_root.resolve(strict=True)
        target = pdf_path.resolve(strict=True)
        target.relative_to(root)
    except (OSError, ValueError):
        raise DartCorpusIngestionError("dart_pdf_cleanup_path_invalid") from None
    if target == root:
        raise DartCorpusIngestionError("dart_pdf_cleanup_path_invalid")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags)
    except OSError:
        raise DartCorpusIngestionError("dart_pdf_cleanup_path_invalid") from None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise DartCorpusIngestionError("dart_pdf_cleanup_path_invalid")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        if digest.hexdigest() != expected_checksum:
            raise DartCorpusIngestionError("dart_pdf_cleanup_checksum_mismatch")
        current = os.stat(target, follow_symlinks=False)
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_dev != opened.st_dev
            or current.st_ino != opened.st_ino
        ):
            raise DartCorpusIngestionError("dart_pdf_cleanup_path_invalid")
        os.unlink(target)
        return opened.st_size
    except DartCorpusIngestionError:
        raise
    except OSError:
        raise DartCorpusIngestionError("dart_pdf_cleanup_failed") from None
    finally:
        os.close(descriptor)
