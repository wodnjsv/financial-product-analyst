from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.schema.search import document_embedding
from financial_agent.embeddings.contracts import (
    APPROVED_MODEL,
    EmbeddingContractError,
    EmbeddingResult,
)
from financial_agent.embeddings.repository import (
    EmbeddingRepository,
    EmbeddingRepositoryError,
    PendingEmbedding,
)
from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_MANIFEST_HASH,
    VALID_RECORD_HASH,
)


@pytest_asyncio.fixture
async def embedding_engine(migrated_database_url: str) -> AsyncEngine:
    engine = create_async_engine(
        migrated_database_url,
        pool_size=5,
        max_overflow=0,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _prepare_dart_corpus(
    database_url: str,
    *,
    product_name: str = "KODEX 200",
    include_artifactless_document: bool = False,
) -> str:
    suffix = uuid4().hex
    dataset_version = f"dart-embedding-{suffix}"
    publisher_id = f"publisher-{suffix}"
    product_id = f"product-{suffix}"
    source_id = f"source-{suffix}"
    document_id = f"document-{suffix}"
    receipt_id = suffix[:14].translate(str.maketrans("abcdef", "123456"))
    receipt_id = "".join(str(ord(char) % 10) for char in receipt_id)[:14]
    assert len(receipt_id) == 14 and receipt_id.isdigit()
    strategy_text = "이 집합투자기구는 코스피 200 지수를 추종합니다."
    risk_text = "시장가격 하락에 따라 투자원금 손실이 발생할 수 있습니다."

    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        connection.execute(
            """
            INSERT INTO operations.dataset_version (
                dataset_version, cutoff_date, status, manifest_hash, created_at
            ) VALUES (%s, DATE '2026-08-24', 'building', %s, %s)
            """,
            (dataset_version, VALID_MANIFEST_HASH, CREATED_AT),
        )
        connection.execute(
            """
            INSERT INTO catalog.entity (
                dataset_version, entity_id, entity_type, canonical_name,
                normalized_name, record_hash, created_at
            ) VALUES
              (%s, %s, 'institution', 'DART 공시기관', 'dart 공시기관', %s, %s),
              (%s, %s, 'product', %s, %s, %s, %s)
            """,
            (
                dataset_version,
                publisher_id,
                VALID_RECORD_HASH,
                CREATED_AT,
                dataset_version,
                product_id,
                product_name,
                product_name.casefold(),
                VALID_RECORD_HASH,
                CREATED_AT,
            ),
        )
        connection.execute(
            """
            INSERT INTO catalog.institution (
                dataset_version, entity_id, institution_kind
            ) VALUES (%s, %s, 'regulator')
            """,
            (dataset_version, publisher_id),
        )
        connection.execute(
            """
            INSERT INTO catalog.product (
                dataset_version, entity_id, product_family
            ) VALUES (%s, %s, 'domestic_etf')
            """,
            (dataset_version, product_id),
        )
        connection.execute(
            """
            INSERT INTO evidence.source_record (
                dataset_version, source_id, publisher, publisher_type,
                source_title, source_type, authority_tier, source_locator_root,
                content_checksum, license_or_usage_note, eligible_for_claim,
                record_hash, created_at
            ) VALUES (
                %s, %s, %s, 'regulator', 'DART 투자설명서', 'filing',
                'official_primary', %s, %s, 'metadata retained', TRUE, %s, %s
            )
            """,
            (
                dataset_version,
                source_id,
                publisher_id,
                f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_id}",
                "c" * 64,
                VALID_RECORD_HASH,
                CREATED_AT,
            ),
        )
        connection.execute(
            """
            INSERT INTO document.document_record (
                dataset_version, document_id, source_id, document_title,
                document_type, object_key, content_checksum, published_at,
                available_at, record_hash, created_at
            ) VALUES (
                %s, %s, %s, 'KODEX 200 투자설명서', 'full_prospectus',
                'discarded/dart.pdf', %s, %s, %s, %s, %s
            )
            """,
            (
                dataset_version,
                document_id,
                source_id,
                "c" * 64,
                datetime(2026, 8, 20, tzinfo=UTC),
                datetime(2026, 8, 21, tzinfo=UTC),
                VALID_RECORD_HASH,
                CREATED_AT,
            ),
        )
        connection.execute(
            """
            INSERT INTO document.document_profile (
                dataset_version, document_id, document_version,
                publisher_role, jurisdiction, original_language,
                effective_from, extraction_method, cutoff_eligible,
                record_hash, created_at
            ) VALUES (
                %s, %s, '2026-08-20', 'regulator_disclosure', 'KR', 'ko',
                DATE '2026-08-20', 'pdfplumber-layout-v1', TRUE, %s, %s
            )
            """,
            (dataset_version, document_id, VALID_RECORD_HASH, CREATED_AT),
        )
        connection.execute(
            """
            INSERT INTO document.document_entity_binding (
                dataset_version, binding_id, document_id, entity_id,
                binding_role, record_hash, created_at
            ) VALUES (%s, %s, %s, %s, 'subject_product', %s, %s)
            """,
            (
                dataset_version,
                f"binding-{suffix}",
                document_id,
                product_id,
                VALID_RECORD_HASH,
                CREATED_AT,
            ),
        )
        for ordinal, (chunk_id, section_type, section_path, exact_text) in enumerate(
            (
                (
                    f"strategy-{suffix}",
                    "investment_strategy",
                    "제2부 > 투자목적 및 전략",
                    strategy_text,
                ),
                (
                    f"risk-{suffix}",
                    "risk_factor",
                    "제2부 > 주요 투자위험",
                    risk_text,
                ),
            )
        ):
            connection.execute(
                """
                INSERT INTO document.document_chunk (
                    dataset_version, chunk_id, document_id, ordinal,
                    page_start, page_end, section_type, section_path,
                    character_start, character_end, exact_text,
                    normalized_search_text, content_hash, record_hash, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    dataset_version,
                    chunk_id,
                    document_id,
                    ordinal,
                    ordinal + 1,
                    ordinal + 1,
                    section_type,
                    section_path,
                    len(exact_text),
                    exact_text,
                    exact_text.casefold(),
                    _sha256(exact_text),
                    VALID_RECORD_HASH,
                    CREATED_AT,
                ),
            )
        connection.execute(
            """
            INSERT INTO document.document_source_artifact (
                dataset_version, source_artifact_id, source_id, document_id,
                receipt_id, original_filename, filing_locator,
                attachment_locator, media_type, byte_count, source_checksum,
                text_checksum, page_count, extraction_version,
                retention_disposition, downloaded_at, persisted_at,
                verified_at, discarded_at, record_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, 'KODEX 200 투자설명서.pdf', %s, %s,
                'application/pdf', 1024, %s, %s, 2, 'pdfplumber-layout-v1',
                'metadata_only_deleted', %s, %s, %s, %s, %s, %s
            )
            """,
            (
                dataset_version,
                f"artifact-{suffix}",
                source_id,
                document_id,
                receipt_id,
                f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_id}",
                "https://dart.fss.or.kr/pdf/download/file.do?"
                f"rcp_no={receipt_id}&dcm_no=1&fl_nm=1",
                "c" * 64,
                "d" * 64,
                datetime(2026, 8, 21, 0, 0, tzinfo=UTC),
                datetime(2026, 8, 21, 0, 1, tzinfo=UTC),
                datetime(2026, 8, 21, 0, 2, tzinfo=UTC),
                datetime(2026, 8, 21, 0, 3, tzinfo=UTC),
                VALID_RECORD_HASH,
                CREATED_AT,
            ),
        )
        if include_artifactless_document:
            artifactless_document_id = f"artifactless-{suffix}"
            artifactless_text = "이 문서는 원본 파일 근거가 없습니다."
            connection.execute(
                """
                INSERT INTO document.document_record (
                    dataset_version, document_id, source_id, document_title,
                    document_type, object_key, content_checksum, record_hash,
                    created_at
                ) VALUES (%s, %s, %s, 'Unbound document', 'full_prospectus',
                          'missing.pdf', %s, %s, %s)
                """,
                (
                    dataset_version,
                    artifactless_document_id,
                    source_id,
                    "e" * 64,
                    VALID_RECORD_HASH,
                    CREATED_AT,
                ),
            )
            connection.execute(
                """
                INSERT INTO document.document_profile (
                    dataset_version, document_id, document_version,
                    publisher_role, jurisdiction, original_language,
                    effective_from, extraction_method, cutoff_eligible,
                    record_hash, created_at
                ) VALUES (
                    %s, %s, '2026-08-20', 'regulator_disclosure', 'KR', 'ko',
                    DATE '2026-08-20', 'pdfplumber-layout-v1', TRUE, %s, %s
                )
                """,
                (
                    dataset_version,
                    artifactless_document_id,
                    VALID_RECORD_HASH,
                    CREATED_AT,
                ),
            )
            connection.execute(
                """
                INSERT INTO document.document_chunk (
                    dataset_version, chunk_id, document_id, ordinal,
                    section_type, section_path, character_start, character_end,
                    exact_text, normalized_search_text, content_hash,
                    record_hash, created_at
                ) VALUES (
                    %s, %s, %s, 0, 'risk_factor', '주요 투자위험', 0, %s,
                    %s, %s, %s, %s, %s
                )
                """,
                (
                    dataset_version,
                    f"artifactless-chunk-{suffix}",
                    artifactless_document_id,
                    len(artifactless_text),
                    artifactless_text,
                    artifactless_text.casefold(),
                    _sha256(artifactless_text),
                    VALID_RECORD_HASH,
                    CREATED_AT,
                ),
            )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return dataset_version


def test_eligible_query_is_bound_to_current_public_dart_artifacts() -> None:
    statement = EmbeddingRepository.eligible_statement(
        "organizer-dart-2026-08-24-v2"
    )
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert statement.is_select
    assert "document.document_source_artifact" in compiled
    assert "evidence.source_record" in compiled
    assert "metadata_only_deleted" in compiled
    assert "application/pdf" in compiled
    assert "https://dart.fss.or.kr/" in compiled
    assert "official_primary" in compiled
    assert "eligible_for_claim" in compiled
    assert "operations.dataset_version.status = 'building'" in compiled


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_preflight_counts_only_exact_current_dart_chunks(
    embedding_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version = _prepare_dart_corpus(
        migrated_database_url,
        include_artifactless_document=True,
    )
    result = await EmbeddingRepository(embedding_engine).preflight(
        dataset_version,
        APPROVED_MODEL,
    )

    assert result.dataset_status == "building"
    assert result.eligible_chunk_count == 2
    assert result.existing_exact_embedding_count == 0
    assert result.missing_embedding_count == 2
    assert result.stale_embedding_count == 0
    assert result.orphan_embedding_count == 0

    protected = await EmbeddingRepository(
        embedding_engine
    ).snapshot_protected_counts(dataset_version)
    assert protected.evidence_count == 0
    assert protected.relation_count == 0
    assert protected.readiness_count == 0
    assert protected.active_dataset_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_model_registration_is_idempotent_and_rejects_a_mismatch(
    embedding_engine: AsyncEngine,
) -> None:
    repository = EmbeddingRepository(embedding_engine)
    await repository.register_model(APPROVED_MODEL)
    await repository.register_model(APPROVED_MODEL)

    mismatched = replace(APPROVED_MODEL, dimension=768)
    with pytest.raises(
        EmbeddingRepositoryError,
        match="model_contract_mismatch",
    ):
        await repository.register_model(mismatched)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_append_then_resume_skips_the_exact_embedding(
    embedding_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version = _prepare_dart_corpus(migrated_database_url)
    repository = EmbeddingRepository(embedding_engine)
    await repository.register_model(APPROVED_MODEL)
    chunk = (
        await repository.missing_chunks(
            dataset_version,
            APPROVED_MODEL,
            limit=1,
        )
    )[0]
    pending = PendingEmbedding(
        chunk=chunk,
        result=EmbeddingResult((0.1,) * 1024, 9, "request-1"),
    )

    assert await repository.append_embeddings(APPROVED_MODEL, (pending,)) == 1
    assert await repository.embedded_section_types(
        dataset_version,
        APPROVED_MODEL,
        entity_id=await repository.resolve_product(dataset_version, "KODEX 200"),
    ) == frozenset({chunk.section_type})
    assert await repository.has_exact_embedding(APPROVED_MODEL, chunk) is True
    assert (
        await repository.has_exact_embedding(
            APPROVED_MODEL,
            replace(chunk, content_hash="f" * 64),
        )
        is False
    )
    assert await repository.append_embeddings(APPROVED_MODEL, (pending,)) == 0
    remaining = await repository.missing_chunks(
        dataset_version,
        APPROVED_MODEL,
        limit=10,
    )
    assert len(remaining) == 1
    assert remaining[0].chunk_id != chunk.chunk_id


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_append_rejects_wrong_dimension_before_database_write(
    embedding_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version = _prepare_dart_corpus(migrated_database_url)
    repository = EmbeddingRepository(embedding_engine)
    chunk = (
        await repository.missing_chunks(
            dataset_version,
            APPROVED_MODEL,
            limit=1,
        )
    )[0]

    with pytest.raises(EmbeddingContractError, match="result_vector_invalid"):
        await repository.append_embeddings(
            APPROVED_MODEL,
            (PendingEmbedding(chunk, EmbeddingResult((0.1,) * 3, 1, None)),),
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_product_resolution_and_sample_candidates_are_exact(
    embedding_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version = _prepare_dart_corpus(migrated_database_url)
    repository = EmbeddingRepository(embedding_engine)

    entity_id = await repository.resolve_product(dataset_version, "KODEX 200")
    candidates = await repository.sample_candidates(dataset_version, limit=10)

    assert entity_id.startswith("product-")
    assert [(item.canonical_product_name, item.strategy_chunk_count, item.risk_chunk_count) for item in candidates] == [
        ("KODEX 200", 1, 1)
    ]
    with pytest.raises(EmbeddingRepositoryError, match="product_not_exact"):
        await repository.resolve_product(dataset_version, "kodex 200")


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_reconciliation_detects_a_duplicate_exact_identity(
    embedding_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version = _prepare_dart_corpus(migrated_database_url)
    repository = EmbeddingRepository(embedding_engine)
    await repository.register_model(APPROVED_MODEL)
    chunk = (
        await repository.missing_chunks(
            dataset_version,
            APPROVED_MODEL,
            limit=1,
        )
    )[0]
    pending = PendingEmbedding(
        chunk,
        EmbeddingResult((0.2,) * 1024, 7, "request-2"),
    )
    await repository.append_embeddings(APPROVED_MODEL, (pending,))
    async with embedding_engine.begin() as connection:
        await connection.execute(
            sa.insert(document_embedding).values(
                dataset_version=dataset_version,
                embedding_id=f"duplicate-{uuid4().hex}",
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                chunk_content_hash=chunk.content_hash,
                model_id=APPROVED_MODEL.model_id,
                model_version=APPROVED_MODEL.model_version,
                dimension=1024,
                embedding=[0.2] * 1024,
                created_at=CREATED_AT,
            )
        )
        await connection.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))

    result = await repository.reconcile(dataset_version, APPROVED_MODEL)

    assert result.eligible_count == 2
    assert result.exact_count == 2
    assert result.missing_count == 1
    assert result.duplicate_count == 1
    assert result.stale_count == 0
    assert result.orphan_count == 0
    assert result.wrong_dimension_count == 0
    assert result.embedding_bytes > 0
