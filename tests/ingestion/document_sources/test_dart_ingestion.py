from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from financial_agent.db.repositories.documents import (
    CapturedDocumentCorpus,
    DocumentCorpusNotFound,
    captured_corpus_hash,
    source_artifact_record_hash,
)
from financial_agent.documents import (
    DocumentRole,
    DocumentSourceCandidate,
    PdfExtractionError,
    PublisherRole,
    SectionType,
    SourceAuthorityTier,
)
from financial_agent.documents.chunking import WhitespaceTokenCounter
from financial_agent.ingestion.document_sources.dart_capture import (
    DartCapturedProspectus,
)
from financial_agent.ingestion.document_sources.dart_ingestion import (
    DartCorpusIngestionError,
    DartCorpusIngestionRequest,
    ingest_one_dart_document,
    safe_discard_verified_pdf,
)
from financial_agent.ingestion.document_sources.dart_pipeline import (
    DartProspectusContext,
)
from financial_agent.ingestion.document_sources.dart_targets import (
    OrganizerDartTarget,
)
from financial_agent.ingestion.official import OfficialObjectManifest
from financial_agent.ingestion.sources import SourceVerificationError
from tests.fixtures.synthetic_pdf import write_synthetic_prospectus


PDF_BYTES = b"%PDF-1.4\nverified synthetic document\n%%EOF\n"
RECEIPT = "20260716000161"
ENTITY_ID = "domestic-etf:KR7069500007"


def _pdf(path: Path) -> tuple[Path, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PDF_BYTES)
    return path, hashlib.sha256(PDF_BYTES).hexdigest()


class _MemoryRepository:
    def __init__(self) -> None:
        self.captured: CapturedDocumentCorpus | None = None

    async def append_captured_corpus(self, captured: CapturedDocumentCorpus) -> None:
        if self.captured is None:
            self.captured = captured
        elif captured_corpus_hash(self.captured) != captured_corpus_hash(captured):
            raise AssertionError("non-idempotent captured corpus")

    async def get_captured_corpus(
        self, dataset_version: str, document_id: str
    ) -> CapturedDocumentCorpus:
        if (
            self.captured is None
            or self.captured.corpus.dataset_version != dataset_version
            or self.captured.corpus.document_id != document_id
        ):
            raise DocumentCorpusNotFound()
        return self.captured

    async def transition_source_retention(
        self,
        dataset_version: str,
        document_id: str,
        target: str,
        *,
        occurred_at: datetime,
    ):
        captured = await self.get_captured_corpus(dataset_version, document_id)
        artifact = captured.source_artifact
        updated = replace(
            artifact,
            retention_disposition=target,
            verified_at=(occurred_at if target == "delete_authorized" else artifact.verified_at),
            discarded_at=(
                occurred_at if target == "metadata_only_deleted" else None
            ),
            record_hash="0" * 64,
        )
        updated = replace(updated, record_hash=source_artifact_record_hash(updated))
        self.captured = replace(captured, source_artifact=updated)
        return updated


def _request(tmp_path: Path) -> DartCorpusIngestionRequest:
    published = datetime(2026, 7, 16, tzinfo=UTC)
    candidate = DocumentSourceCandidate(
        document_id=f"dart-rcept:{RECEIPT}",
        source_code="DART",
        authority_tier=SourceAuthorityTier.TIER_1_REGULATORY,
        publisher_code="FSS_DART",
        publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
        document_type="full_prospectus",
        document_version="2026-07-03",
        source_locator=(
            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={RECEIPT}"
        ),
        discovery_locator=(
            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={RECEIPT}"
        ),
        jurisdiction="KR",
        original_language="ko",
        published_at=published,
        available_at=published,
        effective_from=date(2026, 7, 16),
        effective_to=None,
        media_type="application/pdf",
        accession_or_receipt_id=RECEIPT,
        target_entity_id=ENTITY_ID,
    )
    target = OrganizerDartTarget(
        target_key=f"domestic_etf:{ENTITY_ID}",
        product_family="domestic_etf",
        representative_entity_id=ENTITY_ID,
        canonical_name="삼성 KODEX 200증권상장지수투자신탁[주식]",
        member_entity_ids=(ENTITY_ID,),
        identifiers=((ENTITY_ID, "KRX_SHORT_CODE", "069500"),),
        manager_bindings=(("institution:samsung-am", "삼성자산운용"),),
    )
    context = DartProspectusContext(
        dataset_version="documents-kodex200-v1",
        entity_id=ENTITY_ID,
        canonical_entity_name=target.canonical_name,
        document_id=f"dart:{RECEIPT}:full-prospectus",
        document_title="KODEX 200 투자설명서",
        document_type="full_prospectus",
        document_version="2026-07-03",
        source_id=f"source:dart:{RECEIPT}",
        source_object_key=f"documents/dart/{RECEIPT}/full-prospectus.pdf",
        source_content_checksum="0" * 64,
        publisher_id="institution:dart",
        publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
        published_at=published,
        available_at=published,
        effective_from=date(2026, 7, 16),
        effective_to=None,
        jurisdiction="KR",
        original_language="ko",
        required_document_role=DocumentRole.PRODUCT_FULL,
        budget_scope_id=ENTITY_ID,
    )
    return DartCorpusIngestionRequest(
        run_root=(tmp_path / "run").resolve(),
        target=target,
        candidate=candidate,
        context=context,
        requested_section_types=frozenset(
            {SectionType.INVESTMENT_STRATEGY, SectionType.RISK_FACTOR}
        ),
        token_counter=WhitespaceTokenCounter(),
        maximum_bytes=1024 * 1024,
        target_min=0,
    )


def _install_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    def capture(_opener, *, candidate, canonical_name, destination, maximum_bytes):
        del canonical_name, maximum_bytes
        write_synthetic_prospectus(destination)
        payload = destination.read_bytes()
        manifest = OfficialObjectManifest(
            object_name="KODEX 200 투자설명서.pdf",
            object_key=(
                f"documents/dart/{candidate.accession_or_receipt_id}/"
                "full-prospectus.pdf"
            ),
            media_type="application/pdf",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        return DartCapturedProspectus(
            manifest=manifest,
            attachment_locator=(
                "https://dart.fss.or.kr/pdf/download/file.do?"
                f"rcp_no={candidate.accession_or_receipt_id}&dcm_no=1&fl_nm=1"
            ),
        )

    monkeypatch.setattr(
        "financial_agent.ingestion.document_sources.dart_ingestion."
        "capture_dart_full_prospectus",
        capture,
    )


def test_safe_discard_deletes_only_verified_authorized_pdf(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    pdf_path, checksum = _pdf(run_root / "document-one" / "source.pdf")

    deleted_bytes = safe_discard_verified_pdf(
        run_root=run_root,
        pdf_path=pdf_path,
        expected_checksum=checksum,
        transaction_committed=True,
        readback_verified=True,
        retention_disposition="delete_authorized",
    )

    assert deleted_bytes == len(PDF_BYTES)
    assert not pdf_path.exists()
    assert pdf_path.parent.exists()


@pytest.mark.parametrize(
    ("transaction_committed", "readback_verified", "retention_disposition"),
    (
        (False, True, "delete_authorized"),
        (True, False, "delete_authorized"),
        (True, True, "pending_delete"),
        (True, True, "metadata_only_deleted"),
    ),
)
def test_safe_discard_denies_uncommitted_unverified_or_unauthorized_cleanup(
    tmp_path: Path,
    transaction_committed: bool,
    readback_verified: bool,
    retention_disposition: str,
) -> None:
    run_root = tmp_path / "run"
    pdf_path, checksum = _pdf(run_root / "document-one" / "source.pdf")

    with pytest.raises(DartCorpusIngestionError) as raised:
        safe_discard_verified_pdf(
            run_root=run_root,
            pdf_path=pdf_path,
            expected_checksum=checksum,
            transaction_committed=transaction_committed,
            readback_verified=readback_verified,
            retention_disposition=retention_disposition,
        )

    assert raised.value.code == "dart_pdf_cleanup_not_authorized"
    assert pdf_path.read_bytes() == PDF_BYTES


def test_safe_discard_denies_outside_symlink_directory_and_checksum_change(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    inside, checksum = _pdf(run_root / "document-one" / "source.pdf")
    outside, _ = _pdf(tmp_path / "outside.pdf")
    symlink = run_root / "linked.pdf"
    symlink.symlink_to(outside)
    directory = run_root / "directory.pdf"
    directory.mkdir(parents=True)

    cases = (
        (outside, checksum, "dart_pdf_cleanup_path_invalid"),
        (symlink, checksum, "dart_pdf_cleanup_path_invalid"),
        (directory, checksum, "dart_pdf_cleanup_path_invalid"),
        (inside, "0" * 64, "dart_pdf_cleanup_checksum_mismatch"),
    )
    for path, expected_checksum, reason_code in cases:
        with pytest.raises(DartCorpusIngestionError) as raised:
            safe_discard_verified_pdf(
                run_root=run_root,
                pdf_path=path,
                expected_checksum=expected_checksum,
                transaction_committed=True,
                readback_verified=True,
                retention_disposition="delete_authorized",
            )
        assert raised.value.code == reason_code

    assert outside.read_bytes() == PDF_BYTES
    assert inside.read_bytes() == PDF_BYTES
    assert symlink.is_symlink()
    assert directory.is_dir()


@pytest.mark.asyncio
async def test_ingestion_rejects_candidate_outside_its_organizer_target_before_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    request = replace(
        request,
        candidate=replace(request.candidate, target_entity_id="dart-only:product"),
    )

    def unexpected_capture(*args, **kwargs):
        raise AssertionError("out-of-universe candidate reached PDF capture")

    monkeypatch.setattr(
        "financial_agent.ingestion.document_sources.dart_ingestion."
        "capture_dart_full_prospectus",
        unexpected_capture,
    )

    with pytest.raises(DartCorpusIngestionError) as raised:
        await ingest_one_dart_document(
            _MemoryRepository(), object(), request=request
        )

    assert raised.value.code == "dart_target_not_in_organizer_inventory"
    assert not request.run_root.exists()


@pytest.mark.asyncio
async def test_ingestion_rejects_post_cutoff_filing_before_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    request = replace(
        request,
        candidate=replace(
            request.candidate,
            published_at=datetime(2026, 8, 25, tzinfo=UTC),
        ),
    )

    def unexpected_capture(*args, **kwargs):
        raise AssertionError("post-cutoff candidate reached PDF capture")

    monkeypatch.setattr(
        "financial_agent.ingestion.document_sources.dart_ingestion."
        "capture_dart_full_prospectus",
        unexpected_capture,
    )
    with pytest.raises(DartCorpusIngestionError) as raised:
        await ingest_one_dart_document(
            _MemoryRepository(), object(), request=request
        )

    assert raised.value.code == "dart_candidate_not_cutoff_eligible"
    assert not request.run_root.exists()


@pytest.mark.asyncio
async def test_ingestion_stops_before_a_sixth_quarantined_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    for index in range(5):
        _pdf(request.run_root / f"quarantine-{index}" / "source.pdf")

    def unexpected_capture(*args, **kwargs):
        raise AssertionError("quarantine limit did not stop capture")

    monkeypatch.setattr(
        "financial_agent.ingestion.document_sources.dart_ingestion."
        "capture_dart_full_prospectus",
        unexpected_capture,
    )
    with pytest.raises(DartCorpusIngestionError) as raised:
        await ingest_one_dart_document(
            _MemoryRepository(), object(), request=request
        )

    assert raised.value.code == "dart_quarantine_limit_reached"
    assert len(tuple(request.run_root.rglob("*.pdf"))) == 5


@pytest.mark.asyncio
async def test_ingestion_reuses_only_an_empty_receipt_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_capture(monkeypatch)
    request = _request(tmp_path)
    receipt_root = request.run_root / f"dart-{RECEIPT}"
    receipt_root.mkdir(parents=True)

    result = await ingest_one_dart_document(
        _MemoryRepository(),
        object(),
        request=request,
        now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
    )

    assert result.retention_disposition == "metadata_only_deleted"
    assert not receipt_root.exists()


@pytest.mark.asyncio
async def test_ingestion_removes_empty_directory_after_capture_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    receipt_root = request.run_root / f"dart-{RECEIPT}"

    def failed_capture(*args, **kwargs):
        del args, kwargs
        raise SourceVerificationError("TEST_CAPTURE_FAILED", "synthetic")

    monkeypatch.setattr(
        "financial_agent.ingestion.document_sources.dart_ingestion."
        "capture_dart_full_prospectus",
        failed_capture,
    )

    with pytest.raises(SourceVerificationError, match="synthetic"):
        await ingest_one_dart_document(
            _MemoryRepository(), object(), request=request
        )

    assert not receipt_root.exists()


@pytest.mark.asyncio
async def test_ingestion_does_not_persist_a_document_over_the_token_review_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_capture(monkeypatch)
    request = replace(_request(tmp_path), selected_token_soft_limit=1)
    repository = _MemoryRepository()

    with pytest.raises(DartCorpusIngestionError) as raised:
        await ingest_one_dart_document(
            repository,
            object(),
            request=request,
            now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
        )

    assert raised.value.code == "dart_corpus_quality_review_required"
    assert repository.captured is None
    assert len(tuple(request.run_root.rglob("*.pdf"))) == 1


@pytest.mark.asyncio
async def test_ingestion_reports_pdf_extraction_failure_per_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_capture(monkeypatch)
    request = _request(tmp_path)

    def failed_processing(*args, **kwargs):
        del args, kwargs
        raise PdfExtractionError("PDF_TEXT_LAYER_MISSING")

    monkeypatch.setattr(
        "financial_agent.ingestion.document_sources.dart_ingestion."
        "process_dart_prospectus",
        failed_processing,
    )

    with pytest.raises(DartCorpusIngestionError) as raised:
        await ingest_one_dart_document(
            _MemoryRepository(), object(), request=request
        )

    assert raised.value.code == "PDF_TEXT_LAYER_MISSING"
    assert len(tuple(request.run_root.rglob("*.pdf"))) == 1


@pytest.mark.asyncio
async def test_ingestion_persists_reads_back_and_removes_only_the_source_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_capture(monkeypatch)
    request = _request(tmp_path)
    repository = _MemoryRepository()
    unrelated = request.run_root / "keep.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")

    result = await ingest_one_dart_document(
        repository,
        object(),
        request=request,
        now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
    )

    assert result.retention_disposition == "metadata_only_deleted"
    assert result.readback_verified
    assert result.deleted_bytes > 0
    assert not result.pdf_path.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert repository.captured is not None
    assert repository.captured.source_artifact.original_filename == (
        "KODEX 200 투자설명서.pdf"
    )
    assert repository.captured.source_artifact.retention_disposition == (
        "metadata_only_deleted"
    )
    assert {
        binding.entity_id for binding in repository.captured.corpus.entity_bindings
    } == set(request.target.member_entity_ids)


@pytest.mark.asyncio
async def test_ingestion_stores_one_chunk_set_for_all_organizer_member_products(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_capture(monkeypatch)
    request = _request(tmp_path)
    second_entity = "aaa-public-fund:KRZ000000002"
    request = replace(
        request,
        target=replace(
            request.target,
            product_family="public_fund",
            target_key=f"public_fund:{ENTITY_ID}",
            member_entity_ids=(ENTITY_ID, second_entity),
            identifiers=(
                (ENTITY_ID, "KSD_REPRESENTATIVE_CODE", "KR7069500007"),
                (second_entity, "KSD_SHARE_CLASS_CODE", "KRZ000000002"),
            ),
        ),
    )
    repository = _MemoryRepository()

    await ingest_one_dart_document(
        repository,
        object(),
        request=request,
        now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
    )

    assert repository.captured is not None
    corpus = repository.captured.corpus
    assert corpus.coverage.entity_id == ENTITY_ID
    assert {binding.entity_id for binding in corpus.entity_bindings} == {
        ENTITY_ID,
        second_entity,
    }
    assert {
        corpus.coverage.entity_id,
        *(coverage.entity_id for coverage in repository.captured.additional_coverages),
    } == {ENTITY_ID, second_entity}
    assert len(corpus.chunks) > 0


@pytest.mark.asyncio
async def test_ingestion_does_not_treat_a_different_organizer_binding_as_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_capture(monkeypatch)
    request = _request(tmp_path)
    repository = _MemoryRepository()
    await ingest_one_dart_document(
        repository,
        object(),
        request=request,
        now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
    )
    changed = replace(
        request,
        target=replace(
            request.target,
            member_entity_ids=(ENTITY_ID, "public-fund:unexpected"),
        ),
    )

    with pytest.raises(DartCorpusIngestionError) as raised:
        await ingest_one_dart_document(repository, object(), request=changed)

    assert raised.value.code == "dart_ingestion_existing_identity_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "crash_stage",
    ("committed", "read_back", "delete_authorized", "pdf_deleted"),
)
async def test_ingestion_resume_converges_after_each_durable_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_stage: str,
) -> None:
    _install_capture(monkeypatch)
    request = _request(tmp_path)
    repository = _MemoryRepository()
    crashed = False

    def crash_once(stage: str) -> None:
        nonlocal crashed
        if stage == crash_stage and not crashed:
            crashed = True
            raise RuntimeError(f"simulated crash after {stage}")

    monkeypatch.setattr(
        "financial_agent.ingestion.document_sources.dart_ingestion._after_stage",
        crash_once,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        await ingest_one_dart_document(
            repository,
            object(),
            request=request,
            now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
        )

    monkeypatch.setattr(
        "financial_agent.ingestion.document_sources.dart_ingestion._after_stage",
        lambda _stage: None,
    )
    resumed = await ingest_one_dart_document(
        repository,
        object(),
        request=request,
        now=lambda: datetime(2026, 8, 31, 0, 1, tzinfo=UTC),
    )

    assert resumed.retention_disposition == "metadata_only_deleted"
    assert not resumed.pdf_path.exists()
    assert repository.captured is not None
    assert repository.captured.source_artifact.retention_disposition == (
        "metadata_only_deleted"
    )
