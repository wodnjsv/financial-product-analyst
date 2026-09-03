from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.contracts import CutoffStatus, EvidenceKind
from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.repositories.evidence import EvidenceLedgerRepository
from financial_agent.documents import SectionType
from financial_agent.retrieval.document_evidence import (
    DocumentEvidencePromoter,
    DocumentEvidencePromotionError,
)
from financial_agent.retrieval.documents import (
    DocumentCandidateHit,
    DocumentCandidateRepository,
    DocumentSearchRequest,
)
from tests.fixtures.db.synthetic_dataset import CREATED_AT, VALID_RECORD_HASH
from tests.fixtures.document_corpus import (
    CUTOFF_DATE,
    DATASET_VERSION,
    insert_document_search_corpus,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def postgres_database_url() -> str:
    database_url = os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail("FINANCIAL_AGENT_TEST_DATABASE_URL is required")
    return database_url


@pytest.fixture(scope="session")
def migrated_database_url(postgres_database_url: str) -> str:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_database_url)
    command.upgrade(config, "head")
    return postgres_database_url


def _insert_source_artifact(
    connection: psycopg.Connection,
    dataset_version: str,
    *,
    document_id: str,
    source_id: str,
    retention_disposition: str = "metadata_only_deleted",
) -> None:
    downloaded_at = datetime(2026, 8, 2, tzinfo=UTC)
    persisted_at = datetime(2026, 8, 2, 1, tzinfo=UTC)
    verified_at = (
        None
        if retention_disposition == "pending_delete"
        else datetime(2026, 8, 2, 2, tzinfo=UTC)
    )
    discarded_at = (
        datetime(2026, 8, 2, 3, tzinfo=UTC)
        if retention_disposition == "metadata_only_deleted"
        else None
    )
    receipt_id = "20260801000001"
    connection.execute(
        """
        INSERT INTO document.document_source_artifact (
            dataset_version, source_artifact_id, source_id, document_id,
            receipt_id, original_filename, filing_locator,
            attachment_locator, media_type, byte_count, source_checksum,
            text_checksum, page_count, extraction_version,
            retention_disposition, downloaded_at, persisted_at, verified_at,
            discarded_at, record_hash, created_at
        ) VALUES (
            %s, %s, %s, %s, %s, 'synthetic.pdf', %s, %s,
            'application/pdf', 100, %s, %s, 1, 'pdf-text-v1', %s,
            %s, %s, %s, %s, %s, %s
        )
        """,
        (
            dataset_version,
            f"artifact-{document_id}",
            source_id,
            document_id,
            receipt_id,
            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_id}",
            f"https://dart.fss.or.kr/pdf/download/main.do?rcp_no={receipt_id}",
            "a" * 64,
            "b" * 64,
            retention_disposition,
            downloaded_at,
            persisted_at,
            verified_at,
            discarded_at,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def _unchecked_candidate(
    dataset_version: str,
    *,
    document_id: str,
    entity_id: str,
    chunk_id: str,
    exact_text: str,
    source_id: str = "source-approved",
    available_at: datetime = datetime(2026, 8, 2, tzinfo=UTC),
) -> DocumentCandidateHit:
    return DocumentCandidateHit(
        dataset_version=dataset_version,
        entity_id=entity_id,
        document_id=document_id,
        chunk_id=chunk_id,
        section_type=SectionType.RISK_FACTOR,
        exact_text=exact_text,
        source_id=source_id,
        source_locator=(
            f"synthetic/{source_id}#synthetic/{document_id}.pdf"
            f";document={document_id};chunk={chunk_id};page=1"
            f";section=risk_factor;characters=0-{len(exact_text)}"
        ),
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        available_at=available_at,
        effective_from=date(2026, 8, 1),
        effective_to=None,
        document_version="2026-08-01",
        cutoff_eligible=True,
        publisher_approved=True,
        keyword_rank=1,
        vector_rank=None,
        fused_score=None,
        evidence_id=None,
    )


@dataclass(frozen=True, slots=True)
class PromotionContext:
    database_url: str
    dataset_version: str
    engine: AsyncEngine
    promoter: DocumentEvidencePromoter
    candidate: DocumentCandidateHit


async def _selected_candidate(
    engine: AsyncEngine, dataset_version: str
) -> DocumentCandidateHit:
    request = DocumentSearchRequest(
        dataset_version=dataset_version,
        entity_ids=("selected-etf",),
        claim_type="product_risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=CUTOFF_DATE,
        top_k=5,
    )
    hits = await DocumentCandidateRepository(engine).search_keyword(
        request, "specific risk"
    )
    return next(hit for hit in hits if hit.chunk_id == "risk-specific")


@pytest_asyncio.fixture
async def promotion_context(migrated_database_url: str) -> PromotionContext:
    dataset_version = f"{DATASET_VERSION}-evidence-{uuid4().hex}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_document_search_corpus(connection, dataset_version=dataset_version)
        _insert_source_artifact(
            connection,
            dataset_version,
            document_id="document-risk",
            source_id="source-approved",
        )
        _insert_source_artifact(
            connection,
            dataset_version,
            document_id="document-late",
            source_id="source-approved",
        )
        _insert_source_artifact(
            connection,
            dataset_version,
            document_id="document-unofficial",
            source_id="source-unofficial",
        )
    engine = create_async_engine(migrated_database_url, pool_size=3, max_overflow=0)
    candidate = await _selected_candidate(engine, dataset_version)
    context = PromotionContext(
        database_url=migrated_database_url,
        dataset_version=dataset_version,
        engine=engine,
        promoter=DocumentEvidencePromoter(engine),
        candidate=candidate,
    )
    yield context
    await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_promote_selected_chunk_round_trips_exact_document_evidence(
    promotion_context: PromotionContext,
) -> None:
    first = await promotion_context.promoter.promote(
        promotion_context.candidate,
        claim_type="product_risk_factor",
    )
    second = await promotion_context.promoter.promote(
        promotion_context.candidate,
        claim_type="product_risk_factor",
    )

    assert first == second
    assert first.candidate == promotion_context.candidate
    evidence = first.evidence
    assert evidence.dataset_version == promotion_context.dataset_version
    assert evidence.evidence_kind is EvidenceKind.DOCUMENT_SPAN
    assert evidence.subject_id == "selected-etf"
    assert evidence.predicate_id == "product_risk_factor"
    assert evidence.value_or_object_id.value == "risk-specific"
    assert evidence.normalized_value.value == "risk-specific"
    assert evidence.source_id == "source-approved"
    assert evidence.published_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert evidence.available_at == datetime(2026, 8, 2, tzinfo=UTC)
    assert evidence.valid_from == date(2026, 8, 1)
    assert evidence.valid_to is None
    assert evidence.cutoff_status is CutoffStatus.ELIGIBLE
    assert evidence.raw_value_repr == "specific risk"
    assert evidence.source_locator.record_key == "artifact-document-risk"
    assert evidence.source_locator.page == 1
    assert evidence.source_locator.section == "risk_factor"
    assert evidence.source_locator.sentence_start is None
    assert evidence.source_locator.sentence_end is None

    stored = await EvidenceLedgerRepository(promotion_context.engine).get_evidence(
        promotion_context.dataset_version, evidence.evidence_id
    )
    assert stored == evidence
    with psycopg.connect(
        normalize_psycopg_url(promotion_context.database_url)
    ) as connection:
        assert connection.execute(
            """
            SELECT origin.chunk_id, chunk.document_id, evidence.source_id,
                   evidence.subject_id, evidence.locator_page,
                   evidence.locator_section
            FROM evidence.evidence_document_origin AS origin
            JOIN document.document_chunk AS chunk
              ON chunk.dataset_version = origin.dataset_version
             AND chunk.chunk_id = origin.chunk_id
            JOIN evidence.evidence_record AS evidence
              ON evidence.dataset_version = origin.dataset_version
             AND evidence.evidence_id = origin.evidence_id
            WHERE origin.dataset_version = %s AND origin.evidence_id = %s
            """,
            (promotion_context.dataset_version, evidence.evidence_id),
        ).fetchone() == (
            "risk-specific",
            "document-risk",
            "source-approved",
            "selected-etf",
            1,
            "risk_factor",
        )


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("candidate_change", "reason"),
    [
        ({"entity_id": "wrong-etf"}, "entity_binding_not_found"),
        (
            {"exact_text": "changed after retrieval"},
            "candidate_metadata_mismatch:exact_text",
        ),
        (
            {"document_version": "wrong-version"},
            "candidate_metadata_mismatch:document_version",
        ),
    ],
)
async def test_promote_rejects_candidate_that_no_longer_matches_authority(
    promotion_context: PromotionContext,
    candidate_change: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(DocumentEvidencePromotionError, match=reason):
        await promotion_context.promoter.promote(
            replace(promotion_context.candidate, **candidate_change),
            claim_type="product_risk_factor",
        )


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        pytest.param(
            lambda dataset: _unchecked_candidate(
                dataset,
                document_id="document-unofficial",
                entity_id="unofficial-etf",
                chunk_id="unofficial-near",
                exact_text="unofficial risk",
                source_id="source-unofficial",
            ),
            "source_not_claim_eligible",
            id="ineligible-source",
        ),
        pytest.param(
            lambda dataset: _unchecked_candidate(
                dataset,
                document_id="document-late",
                entity_id="late-etf",
                chunk_id="late-near",
                exact_text="late risk",
                available_at=datetime(2026, 8, 24, 15, 30, tzinfo=UTC),
            ),
            "document_not_eligible_at_cutoff",
            id="after-cutoff",
        ),
    ],
)
async def test_promote_revalidates_source_and_cutoff(
    promotion_context: PromotionContext,
    candidate,
    reason: str,
) -> None:
    with pytest.raises(DocumentEvidencePromotionError, match=reason):
        await promotion_context.promoter.promote(
            candidate(promotion_context.dataset_version),
            claim_type="product_risk_factor",
        )


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("artifact_state", [None, "pending_delete"])
async def test_promote_requires_verified_source_artifact(
    migrated_database_url: str,
    artifact_state: str | None,
) -> None:
    dataset_version = f"{DATASET_VERSION}-artifact-{uuid4().hex}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_document_search_corpus(connection, dataset_version=dataset_version)
        if artifact_state is not None:
            _insert_source_artifact(
                connection,
                dataset_version,
                document_id="document-risk",
                source_id="source-approved",
                retention_disposition=artifact_state,
            )
    engine = create_async_engine(migrated_database_url)
    try:
        candidate = await _selected_candidate(engine, dataset_version)
        expected_reason = (
            "source_artifact_not_found"
            if artifact_state is None
            else "source_artifact_not_verified"
        )
        with pytest.raises(DocumentEvidencePromotionError, match=expected_reason):
            await DocumentEvidencePromoter(engine).promote(
                candidate, claim_type="product_risk_factor"
            )
    finally:
        await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_promote_rejects_unsupported_claim_type(
    promotion_context: PromotionContext,
) -> None:
    with pytest.raises(ValueError, match="unsupported claim_type"):
        await promotion_context.promoter.promote(
            promotion_context.candidate,
            claim_type="invented_claim",
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_promote_rejects_stored_chunk_content_hash_mismatch(
    promotion_context: PromotionContext,
) -> None:
    with psycopg.connect(
        normalize_psycopg_url(promotion_context.database_url)
    ) as connection:
        connection.execute(
            """
            DELETE FROM search.document_embedding
            WHERE dataset_version = %s AND chunk_id = 'risk-specific'
            """,
            (promotion_context.dataset_version,),
        )
        connection.execute(
            """
            UPDATE document.document_chunk
            SET content_hash = %s
            WHERE dataset_version = %s AND chunk_id = 'risk-specific'
            """,
            ("0" * 64, promotion_context.dataset_version),
        )

    with pytest.raises(
        DocumentEvidencePromotionError, match="candidate_content_hash_mismatch"
    ):
        await promotion_context.promoter.promote(
            promotion_context.candidate,
            claim_type="product_risk_factor",
        )
