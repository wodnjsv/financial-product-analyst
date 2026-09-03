from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.repositories import documents as document_repository
from financial_agent.db.repositories.documents import (
    CapturedDocumentCorpus,
    DocumentCorpusConflict,
    DocumentCorpusRecord,
    DocumentCorpusRepository,
    DocumentCorpusStateError,
    DocumentCorpusValidationError,
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
)
from tests.fixtures.db.synthetic_dataset import (
    insert_building_dataset,
    insert_entity,
    insert_institution,
    insert_scope_evidence,
    insert_source,
)


def _sha256(text_value: str) -> str:
    return hashlib.sha256(text_value.encode()).hexdigest()


def _token() -> str:
    return uuid4().hex


def _chunk_record_hash(chunk: DocumentChunkDraft) -> str:
    payload = {
        "dataset_version": chunk.dataset_version,
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "ordinal": chunk.ordinal,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "section_type": chunk.section_type.value,
        "section_path": chunk.section_path,
        "character_start": chunk.character_start,
        "character_end": chunk.character_end,
        "exact_text": chunk.exact_text,
        "normalized_search_text": chunk.normalized_search_text,
        "content_hash": chunk.content_hash,
    }
    return _sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _corpus(
    *,
    dataset_version: str = "documents-v1",
    document_id: str = "document-one",
    entity_id: str = "product-one",
) -> DocumentCorpusRecord:
    exact_text = "The fund may lose value when market prices decline."
    section_path = "Principal Risks"
    document_type = "summary_prospectus"
    canonical_name = f"Canonical {entity_id}"
    chunk_without_record_hash = DocumentChunkDraft(
        dataset_version=dataset_version,
        chunk_id="chunk-one",
        document_id=document_id,
        ordinal=0,
        page_start=3,
        page_end=3,
        section_type=SectionType.RISK_FACTOR,
        section_path=section_path,
        character_start=120,
        character_end=120 + len(exact_text),
        exact_text=exact_text,
        normalized_search_text=exact_text,
        embedding_text="\n".join(
            (canonical_name, document_type, section_path, exact_text)
        ),
        content_hash=_sha256(exact_text),
        record_hash="0" * 64,
    )
    chunk = replace(
        chunk_without_record_hash,
        record_hash=_chunk_record_hash(chunk_without_record_hash),
    )
    profile = DocumentProfileRecord(
        dataset_version=dataset_version,
        document_id=document_id,
        document_version="2026-08-01",
        publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
        jurisdiction="US",
        original_language="en",
        effective_from=date(2026, 8, 1),
        effective_to=None,
        amends_document_id=None,
        extraction_method="text_layer",
        cutoff_eligible=True,
        record_hash="5" * 64,
    )
    binding = DocumentEntityBindingRecord(
        dataset_version=dataset_version,
        binding_id="binding-one",
        document_id=document_id,
        entity_id=entity_id,
        binding_role="subject_product",
        record_hash="6" * 64,
    )
    coverage = DocumentCoverageDraft(
        coverage_id="coverage-one",
        dataset_version=dataset_version,
        entity_id=entity_id,
        required_document_role=DocumentRole.PRODUCT_SUMMARY,
        coverage_status=CoverageStatus.INDEXED,
        document_id=document_id,
        scope_evidence_id=None,
        reason_code=None,
        record_hash="7" * 64,
    )
    return DocumentCorpusRecord(
        dataset_version=dataset_version,
        document_id=document_id,
        source_id="source-one",
        document_title="Synthetic summary prospectus",
        document_type=document_type,
        object_key="synthetic/document-one.pdf",
        content_checksum="3" * 64,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        profile=profile,
        entity_bindings=(binding,),
        chunks=(chunk,),
        required_document_role=DocumentRole.PRODUCT_SUMMARY,
        coverage=coverage,
    )


def _source_artifact(
    *,
    retention_disposition: str = "pending_delete",
    verified_at: datetime | None = None,
    discarded_at: datetime | None = None,
) -> DocumentSourceArtifactRecord:
    record = DocumentSourceArtifactRecord(
        dataset_version="documents-2026-08-24-building-v1",
        source_artifact_id="artifact:dart:20260716000161",
        source_id="source:dart:20260716000161",
        document_id="dart:20260716000161:full-prospectus",
        receipt_id="20260716000161",
        original_filename="KODEX 200 투자설명서.pdf",
        filing_locator=(
            "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260716000161"
        ),
        attachment_locator=(
            "https://dart.fss.or.kr/pdf/download/file.do?"
            "rcp_no=20260716000161&dcm_no=1&fl_nm=1"
        ),
        media_type="application/pdf",
        byte_count=918714,
        source_checksum="c" * 64,
        text_checksum="b" * 64,
        page_count=68,
        extraction_version="pdfplumber-layout-v1",
        retention_disposition=retention_disposition,
        downloaded_at=datetime(2026, 8, 31, tzinfo=UTC),
        persisted_at=datetime(2026, 8, 31, 0, 1, tzinfo=UTC),
        verified_at=verified_at,
        discarded_at=discarded_at,
        record_hash="0" * 64,
    )
    return replace(
        record,
        record_hash=document_repository._source_artifact_record_hash(record),
    )


def _source(corpus: DocumentCorpusRecord) -> SourceRecord:
    return SourceRecord(
        source_id=corpus.source_id,
        publisher="publisher-one",
        publisher_type="regulator",
        source_title="Synthetic DART prospectus",
        source_type="filing",
        authority_tier="official_primary",
        source_locator_root=(
            "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260716000161"
        ),
        content_checksum=corpus.content_checksum,
        license_or_usage_note="temporary local capture; metadata retained",
        eligible_for_claim=True,
    )


def _artifact(corpus: DocumentCorpusRecord) -> DocumentSourceArtifactRecord:
    base = _source_artifact()
    artifact = replace(
        base,
        dataset_version=corpus.dataset_version,
        source_id=corpus.source_id,
        document_id=corpus.document_id,
        source_checksum=corpus.content_checksum,
    )
    return replace(
        artifact,
        record_hash=document_repository._source_artifact_record_hash(artifact),
    )


def _captured(corpus: DocumentCorpusRecord) -> CapturedDocumentCorpus:
    return CapturedDocumentCorpus(
        source=_source(corpus),
        corpus=corpus,
        source_artifact=_artifact(corpus),
        additional_coverages=(),
    )


def _negative_coverage(dataset_version: str, entity_id: str) -> DocumentCoverageDraft:
    return DocumentCoverageDraft(
        coverage_id="coverage-negative",
        dataset_version=dataset_version,
        entity_id=entity_id,
        required_document_role=DocumentRole.PRODUCT_SUMMARY,
        coverage_status=CoverageStatus.DOCUMENT_NOT_FOUND,
        document_id=None,
        scope_evidence_id="scope-one",
        reason_code="approved_sources_exhausted",
        record_hash="8" * 64,
    )


def _prepare_context(
    database_url: str,
    *,
    with_scope_evidence: bool = False,
    with_source: bool = True,
) -> tuple[str, str]:
    token = _token()
    dataset_version = f"documents-{token}"
    entity_id = f"product-{token}"
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        insert_building_dataset(connection, dataset_version)
        insert_institution(connection, dataset_version=dataset_version)
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id=entity_id,
        )
        if with_source:
            insert_source(connection, dataset_version=dataset_version)
        if with_scope_evidence:
            insert_scope_evidence(
                connection,
                dataset_version=dataset_version,
                entity_id=entity_id,
            )
    return dataset_version, entity_id


def _set_dataset_status(
    database_url: str,
    dataset_version: str,
    status: str,
) -> None:
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        if status == "active":
            connection.execute(
                """
                UPDATE operations.dataset_version
                SET status = 'retired'
                WHERE status = 'active'
                """
            )
            connection.execute(
                """
                UPDATE operations.dataset_version
                SET status = 'validated'
                WHERE dataset_version = %s
                """,
                (dataset_version,),
            )
        connection.execute(
            """
            UPDATE operations.dataset_version
            SET status = %s
            WHERE dataset_version = %s
            """,
            (status, dataset_version),
        )


@pytest_asyncio.fixture
async def repository_engine(migrated_database_url: str) -> AsyncEngine:
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    yield engine
    await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_document_corpus_round_trips_idempotently(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(migrated_database_url)
    corpus = _corpus(dataset_version=dataset_version, entity_id=entity_id)
    repository = DocumentCorpusRepository(repository_engine)

    await repository.append_corpus(corpus)
    await repository.append_corpus(corpus)

    coverage = await repository.get_coverage(
        corpus.dataset_version,
        corpus.entity_bindings[0].entity_id,
        corpus.required_document_role,
    )
    assert coverage.coverage_status is CoverageStatus.INDEXED
    assert await repository.list_chunks(
        corpus.dataset_version,
        corpus.document_id,
    ) == corpus.chunks
    async with repository_engine.connect() as connection:
        counts = (
            await connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM document.document_record
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_profile
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_entity_binding
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_chunk
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_coverage
                         WHERE dataset_version = :dataset_version)
                    """
                ),
                {"dataset_version": dataset_version},
            )
        ).one()
        evidence_text_count = (
            await connection.execute(
                text(
                    """
                    SELECT count(*) FROM evidence.evidence_record
                    WHERE dataset_version = :dataset_version
                      AND raw_value_repr = :embedding_text
                    """
                ),
                {
                    "dataset_version": dataset_version,
                    "embedding_text": corpus.chunks[0].embedding_text,
                },
            )
        ).scalar_one()
    assert counts == (1, 1, 1, 1, 1)
    assert evidence_text_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_captured_corpus_round_trips_atomically_with_multiple_products(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(
        migrated_database_url, with_source=False
    )
    second_entity_id = f"product-{_token()}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id=second_entity_id,
        )
    corpus = _corpus(dataset_version=dataset_version, entity_id=entity_id)
    second_binding = DocumentEntityBindingRecord(
        dataset_version=dataset_version,
        binding_id="binding-two",
        document_id=corpus.document_id,
        entity_id=second_entity_id,
        binding_role="subject_product",
        record_hash="9" * 64,
    )
    second_coverage = replace(
        corpus.coverage,
        coverage_id="coverage-two",
        entity_id=second_entity_id,
        record_hash="8" * 64,
    )
    corpus = replace(
        corpus,
        entity_bindings=(corpus.entity_bindings[0], second_binding),
    )
    captured = replace(
        _captured(corpus), additional_coverages=(second_coverage,)
    )
    repository = DocumentCorpusRepository(repository_engine)

    await repository.append_captured_corpus(captured)
    await repository.append_captured_corpus(captured)

    assert await repository.get_captured_corpus(
        dataset_version, corpus.document_id
    ) == captured
    async with repository_engine.connect() as connection:
        counts = (
            await connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM evidence.source_record
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_record
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_source_artifact
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_entity_binding
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_chunk
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_coverage
                         WHERE dataset_version = :dataset_version)
                    """
                ),
                {"dataset_version": dataset_version},
            )
        ).one()
    assert counts == (1, 1, 1, 2, 1, 2)


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_group",
    ("source", "document", "bindings", "chunks", "coverages", "artifact"),
)
async def test_captured_corpus_rolls_back_every_group_on_late_failure(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    failure_group: str,
) -> None:
    dataset_version, entity_id = _prepare_context(
        migrated_database_url, with_source=False
    )
    captured = _captured(
        _corpus(dataset_version=dataset_version, entity_id=entity_id)
    )

    async def fail_after_group(_connection: object, group: str) -> None:
        if group == failure_group:
            raise RuntimeError("injected failure")

    monkeypatch.setattr(
        DocumentCorpusRepository,
        "_after_insert_group",
        staticmethod(fail_after_group),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="injected failure"):
        await DocumentCorpusRepository(repository_engine).append_captured_corpus(
            captured
        )

    async with repository_engine.connect() as connection:
        counts = (
            await connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM evidence.source_record
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_record
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_chunk
                         WHERE dataset_version = :dataset_version),
                        (SELECT count(*) FROM document.document_source_artifact
                         WHERE dataset_version = :dataset_version)
                    """
                ),
                {"dataset_version": dataset_version},
            )
        ).one()
    assert counts == (0, 0, 0, 0)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_captured_corpus_changed_file_provenance_conflicts(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(
        migrated_database_url, with_source=False
    )
    captured = _captured(
        _corpus(dataset_version=dataset_version, entity_id=entity_id)
    )
    repository = DocumentCorpusRepository(repository_engine)
    await repository.append_captured_corpus(captured)
    changed_artifact = replace(
        captured.source_artifact,
        original_filename="different-prospectus.pdf",
    )
    changed_artifact = replace(
        changed_artifact,
        record_hash=document_repository._source_artifact_record_hash(
            changed_artifact
        ),
    )

    with pytest.raises(DocumentCorpusConflict):
        await repository.append_captured_corpus(
            replace(captured, source_artifact=changed_artifact)
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_source_artifact_retention_transitions_are_read_back(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(
        migrated_database_url, with_source=False
    )
    captured = _captured(
        _corpus(dataset_version=dataset_version, entity_id=entity_id)
    )
    repository = DocumentCorpusRepository(repository_engine)
    await repository.append_captured_corpus(captured)
    verified_at = datetime(2026, 8, 31, 0, 2, tzinfo=UTC)
    discarded_at = datetime(2026, 8, 31, 0, 3, tzinfo=UTC)

    authorized = await repository.transition_source_retention(
        dataset_version,
        captured.corpus.document_id,
        "delete_authorized",
        occurred_at=verified_at,
    )
    deleted = await repository.transition_source_retention(
        dataset_version,
        captured.corpus.document_id,
        "metadata_only_deleted",
        occurred_at=discarded_at,
    )

    assert authorized.verified_at == verified_at
    assert authorized.discarded_at is None
    assert deleted.verified_at == verified_at
    assert deleted.discarded_at == discarded_at
    assert (
        await repository.get_captured_corpus(
            dataset_version, captured.corpus.document_id
        )
    ).source_artifact == deleted


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_same_document_identity_with_different_bytes_conflicts(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(migrated_database_url)
    corpus = _corpus(dataset_version=dataset_version, entity_id=entity_id)
    repository = DocumentCorpusRepository(repository_engine)
    await repository.append_corpus(corpus)

    with pytest.raises(DocumentCorpusConflict, match="DOCUMENT_CORPUS_CONFLICT"):
        await repository.append_corpus(
            replace(corpus, document_title="Byte-different title")
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_negative_coverage_round_trips_idempotently_without_a_document(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(
        migrated_database_url,
        with_scope_evidence=True,
    )
    coverage = _negative_coverage(dataset_version, entity_id)
    repository = DocumentCorpusRepository(repository_engine)

    await repository.append_coverage(coverage)
    await repository.append_coverage(coverage)

    assert await repository.get_coverage(
        dataset_version,
        entity_id,
        coverage.required_document_role,
    ) == coverage
    async with repository_engine.connect() as connection:
        document_count = (
            await connection.execute(
                text(
                    """
                    SELECT count(*) FROM document.document_record
                    WHERE dataset_version = :dataset_version
                    """
                ),
                {"dataset_version": dataset_version},
            )
        ).scalar_one()
    assert document_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_negative_coverage_same_identity_with_different_bytes_conflicts(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(
        migrated_database_url,
        with_scope_evidence=True,
    )
    coverage = _negative_coverage(dataset_version, entity_id)
    repository = DocumentCorpusRepository(repository_engine)
    await repository.append_coverage(coverage)

    with pytest.raises(DocumentCorpusConflict, match="DOCUMENT_CORPUS_CONFLICT"):
        await repository.append_coverage(
            replace(coverage, reason_code="different_reason")
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_foreign_dataset_entity_is_rejected(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    first_dataset, entity_id = _prepare_context(migrated_database_url)
    second_dataset, _ = _prepare_context(migrated_database_url)
    corpus = _corpus(dataset_version=second_dataset, entity_id=entity_id)

    with pytest.raises(DocumentCorpusValidationError, match="embedding context"):
        await DocumentCorpusRepository(repository_engine).append_corpus(corpus)

    assert first_dataset != second_dataset


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_foreign_dataset_document_is_rejected(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    first_dataset, first_entity = _prepare_context(migrated_database_url)
    second_dataset, second_entity = _prepare_context(migrated_database_url)
    repository = DocumentCorpusRepository(repository_engine)
    first = _corpus(dataset_version=first_dataset, entity_id=first_entity)
    await repository.append_corpus(first)
    second = _corpus(
        dataset_version=second_dataset,
        document_id="document-two",
        entity_id=second_entity,
    )
    second = replace(
        second,
        profile=replace(second.profile, amends_document_id=first.document_id),
    )

    with pytest.raises(IntegrityError) as error:
        await repository.append_corpus(second)

    assert error.value.orig.diag.constraint_name == (
        "fk_document_profile_amends_document"
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_foreign_dataset_scope_evidence_is_rejected(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    first_dataset, first_entity = _prepare_context(
        migrated_database_url,
        with_scope_evidence=True,
    )
    second_dataset, second_entity = _prepare_context(migrated_database_url)
    coverage = replace(
        _negative_coverage(second_dataset, second_entity),
        scope_evidence_id="scope-one",
    )

    with pytest.raises(IntegrityError) as error:
        await DocumentCorpusRepository(repository_engine).append_coverage(coverage)

    assert error.value.orig.diag.constraint_name == (
        "fk_document_coverage_scope_evidence"
    )
    assert first_dataset != second_dataset
    assert first_entity != second_entity


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("status", ("validated", "active"))
@pytest.mark.parametrize("append_kind", ("corpus", "coverage"))
async def test_nonbuilding_dataset_rejects_repository_inserts(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
    status: str,
    append_kind: str,
) -> None:
    dataset_version, entity_id = _prepare_context(
        migrated_database_url,
        with_scope_evidence=append_kind == "coverage",
    )
    _set_dataset_status(migrated_database_url, dataset_version, status)

    with pytest.raises(DocumentCorpusStateError):
        repository = DocumentCorpusRepository(repository_engine)
        if append_kind == "corpus":
            await repository.append_corpus(
                _corpus(dataset_version=dataset_version, entity_id=entity_id)
            )
        else:
            await repository.append_coverage(
                _negative_coverage(dataset_version, entity_id)
            )


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("status", ("validated", "active"))
@pytest.mark.parametrize("operation", ("UPDATE", "DELETE"))
async def test_nonbuilding_document_rows_reject_update_and_delete(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
    status: str,
    operation: str,
) -> None:
    dataset_version, entity_id = _prepare_context(migrated_database_url)
    repository = DocumentCorpusRepository(repository_engine)
    corpus = _corpus(dataset_version=dataset_version, entity_id=entity_id)
    await repository.append_corpus(corpus)
    _set_dataset_status(migrated_database_url, dataset_version, status)

    statement = (
        """
        UPDATE document.document_coverage
        SET record_hash = :record_hash
        WHERE dataset_version = :dataset_version
        """
        if operation == "UPDATE"
        else """
        DELETE FROM document.document_coverage
        WHERE dataset_version = :dataset_version
        """
    )
    with pytest.raises(DBAPIError) as error:
        async with repository_engine.begin() as connection:
            await connection.execute(
                text(statement),
                {"dataset_version": dataset_version, "record_hash": "9" * 64},
            )
    assert error.value.orig.sqlstate == "55000"


def test_chunk_content_hash_must_match_exact_text() -> None:
    corpus = _corpus()
    invalid = replace(
        corpus,
        chunks=(replace(corpus.chunks[0], content_hash="f" * 64),),
    )

    with pytest.raises(DocumentCorpusValidationError, match="content_hash"):
        DocumentCorpusRepository.validate_corpus(invalid)


def test_valid_corpus_passes_repository_validation() -> None:
    DocumentCorpusRepository.validate_corpus(_corpus())


@pytest.mark.parametrize(
    "document_version",
    (None, "", " ", "\t", "\n", "\r", "\f", "\v", " \t\n\r\f\v "),
)
def test_corpus_rejects_blank_document_version(
    document_version: str | None,
) -> None:
    corpus = _corpus()

    with pytest.raises(DocumentCorpusValidationError, match="document_version"):
        DocumentCorpusRepository.validate_corpus(
            replace(
                corpus,
                profile=replace(
                    corpus.profile,
                    document_version=document_version,
                ),
            )
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_corpus_preserves_surrounding_document_version_whitespace(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(migrated_database_url)
    corpus = _corpus(dataset_version=dataset_version, entity_id=entity_id)
    version = " \t\n 2026-08-01 \r\f\v "
    corpus = replace(
        corpus,
        profile=replace(corpus.profile, document_version=version),
    )

    await DocumentCorpusRepository(repository_engine).append_corpus(corpus)

    async with repository_engine.connect() as connection:
        stored_version = (
            await connection.execute(
                text(
                    """
                    SELECT document_version
                    FROM document.document_profile
                    WHERE dataset_version = :dataset_version
                      AND document_id = :document_id
                    """
                ),
                {
                    "dataset_version": dataset_version,
                    "document_id": corpus.document_id,
                },
            )
        ).scalar_one()
    assert stored_version == version


def test_chunk_record_hash_must_match_authoritative_locators_and_text() -> None:
    corpus = _corpus()
    invalid = replace(
        corpus,
        chunks=(
            replace(corpus.chunks[0], page_start=4, page_end=4),
        ),
    )

    with pytest.raises(DocumentCorpusValidationError, match="record_hash"):
        DocumentCorpusRepository.validate_corpus(invalid)


@pytest.mark.parametrize(
    "invalid_corpus",
    (
        replace(
            _corpus(),
            profile=replace(_corpus().profile, dataset_version="foreign-v1"),
        ),
        replace(
            _corpus(),
            entity_bindings=(
                replace(_corpus().entity_bindings[0], document_id="foreign-document"),
            ),
        ),
        replace(
            _corpus(),
            chunks=(replace(_corpus().chunks[0], dataset_version="foreign-v1"),),
        ),
        replace(
            _corpus(),
            coverage=replace(_corpus().coverage, entity_id="foreign-product"),
        ),
        replace(
            _corpus(),
            coverage=replace(_corpus().coverage, document_id="foreign-document"),
        ),
    ),
)
def test_corpus_children_must_match_the_exact_parent_and_binding(
    invalid_corpus: DocumentCorpusRecord,
) -> None:
    with pytest.raises(DocumentCorpusValidationError):
        DocumentCorpusRepository.validate_corpus(invalid_corpus)


def test_append_coverage_accepts_only_documentless_negative_coverage() -> None:
    with pytest.raises(DocumentCorpusValidationError, match="negative"):
        DocumentCorpusRepository.validate_standalone_coverage(_corpus().coverage)


def test_offset_equivalent_document_datetimes_have_one_canonical_identity() -> None:
    seoul = ZoneInfo("Asia/Seoul")
    seoul_corpus = replace(
        _corpus(),
        published_at=datetime(2026, 8, 1, 9, tzinfo=seoul),
        available_at=datetime(2026, 8, 2, 9, tzinfo=seoul),
    )
    utc_corpus = replace(
        seoul_corpus,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert document_repository._corpus_bytes(
        seoul_corpus
    ) == document_repository._corpus_bytes(utc_corpus)


@pytest.mark.parametrize("field_name", ("published_at", "available_at"))
def test_corpus_rejects_naive_persisted_datetimes(field_name: str) -> None:
    corpus = replace(_corpus(), **{field_name: datetime(2026, 8, 1)})

    with pytest.raises(DocumentCorpusValidationError, match=field_name):
        DocumentCorpusRepository.validate_corpus(corpus)


def test_valid_pending_source_artifact_passes_validation() -> None:
    DocumentCorpusRepository.validate_source_artifact(_source_artifact())


def test_valid_captured_corpus_passes_cross_record_validation() -> None:
    DocumentCorpusRepository.validate_captured_corpus(_captured(_corpus()))


@pytest.mark.parametrize(
    "captured",
    (
        replace(
            _captured(_corpus()),
            source=_source(_corpus()).model_copy(
                update={"source_id": "different-source"}
            ),
        ),
        replace(
            _captured(_corpus()),
            source_artifact=replace(
                _artifact(_corpus()), document_id="different-document"
            ),
        ),
    ),
)
def test_captured_corpus_rejects_cross_record_identity_mismatch(
    captured: CapturedDocumentCorpus,
) -> None:
    with pytest.raises(DocumentCorpusValidationError):
        DocumentCorpusRepository.validate_captured_corpus(captured)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("receipt_id", "2026071600016"),
        ("receipt_id", "2026071600016x"),
        ("filing_locator", "https://example.com/main.do?rcpNo=20260716000161"),
        (
            "attachment_locator",
            "https://evil.example/pdf/download/file.do?rcp_no=20260716000161",
        ),
        ("media_type", "text/plain"),
        ("byte_count", 0),
        ("page_count", 0),
        ("source_checksum", "C" * 64),
        ("text_checksum", "b" * 63),
    ),
)
def test_source_artifact_rejects_invalid_file_provenance(
    field_name: str,
    invalid_value: str | int,
) -> None:
    artifact = replace(_source_artifact(), **{field_name: invalid_value})

    with pytest.raises(DocumentCorpusValidationError, match=field_name):
        DocumentCorpusRepository.validate_source_artifact(artifact)


@pytest.mark.parametrize("field_name", ("downloaded_at", "persisted_at"))
def test_source_artifact_rejects_naive_required_timestamps(
    field_name: str,
) -> None:
    artifact = replace(
        _source_artifact(), **{field_name: datetime(2026, 8, 31)}
    )

    with pytest.raises(DocumentCorpusValidationError, match=field_name):
        DocumentCorpusRepository.validate_source_artifact(artifact)


@pytest.mark.parametrize(
    "artifact",
    (
        _source_artifact(
            retention_disposition="metadata_only_deleted",
            verified_at=None,
            discarded_at=datetime(2026, 8, 31, 0, 3, tzinfo=UTC),
        ),
        _source_artifact(
            retention_disposition="metadata_only_deleted",
            verified_at=datetime(2026, 8, 31, 0, 2, tzinfo=UTC),
            discarded_at=None,
        ),
        _source_artifact(
            retention_disposition="pending_delete",
            verified_at=datetime(2026, 8, 31, 0, 2, tzinfo=UTC),
        ),
        _source_artifact(
            retention_disposition="delete_authorized",
            verified_at=None,
        ),
    ),
)
def test_source_artifact_rejects_incoherent_retention_state(
    artifact: DocumentSourceArtifactRecord,
) -> None:
    with pytest.raises(DocumentCorpusValidationError, match="retention"):
        DocumentCorpusRepository.validate_source_artifact(artifact)


def test_source_artifact_record_hash_covers_file_identity() -> None:
    artifact = _source_artifact()

    with pytest.raises(DocumentCorpusValidationError, match="record_hash"):
        DocumentCorpusRepository.validate_source_artifact(
            replace(artifact, original_filename="different.pdf")
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_asia_seoul_corpus_and_utc_equivalent_retry_converge(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(migrated_database_url)
    seoul = ZoneInfo("Asia/Seoul")
    seoul_corpus = replace(
        _corpus(dataset_version=dataset_version, entity_id=entity_id),
        published_at=datetime(2026, 8, 1, 9, tzinfo=seoul),
        available_at=datetime(2026, 8, 2, 9, tzinfo=seoul),
    )
    utc_equivalent = replace(
        seoul_corpus,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    repository = DocumentCorpusRepository(repository_engine)

    await repository.append_corpus(seoul_corpus)
    await repository.append_corpus(seoul_corpus)
    await repository.append_corpus(utc_equivalent)

    async with repository_engine.connect() as connection:
        count = (
            await connection.execute(
                text(
                    """
                    SELECT count(*) FROM document.document_record
                    WHERE dataset_version = :dataset_version
                    """
                ),
                {"dataset_version": dataset_version},
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_multibinding_chunks_round_trip_with_the_covered_entity_context(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, covered_entity_id = _prepare_context(migrated_database_url)
    earlier_binding_entity_id = f"index-{_token()}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id=earlier_binding_entity_id,
            entity_type="index",
        )
    corpus = _corpus(
        dataset_version=dataset_version,
        entity_id=covered_entity_id,
    )
    earlier_binding = DocumentEntityBindingRecord(
        dataset_version=dataset_version,
        binding_id="a-index-binding",
        document_id=corpus.document_id,
        entity_id=earlier_binding_entity_id,
        binding_role="subject_index",
        record_hash="9" * 64,
    )
    covered_binding = replace(
        corpus.entity_bindings[0],
        binding_id="z-covered-product-binding",
    )
    corpus = replace(
        corpus,
        entity_bindings=(earlier_binding, covered_binding),
    )
    repository = DocumentCorpusRepository(repository_engine)

    await repository.append_corpus(corpus)

    assert await repository.list_chunks(
        dataset_version,
        corpus.document_id,
    ) == corpus.chunks


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_incoherent_embedding_context_is_rejected_before_corpus_rows_commit(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, entity_id = _prepare_context(migrated_database_url)
    corpus = _corpus(dataset_version=dataset_version, entity_id=entity_id)
    incoherent = replace(
        corpus,
        chunks=(replace(corpus.chunks[0], embedding_text="wrong context"),),
    )

    with pytest.raises(DocumentCorpusValidationError, match="embedding_text"):
        await DocumentCorpusRepository(repository_engine).append_corpus(incoherent)

    async with repository_engine.connect() as connection:
        count = (
            await connection.execute(
                text(
                    """
                    SELECT count(*) FROM document.document_record
                    WHERE dataset_version = :dataset_version
                    """
                ),
                {"dataset_version": dataset_version},
            )
        ).scalar_one()
    assert count == 0
