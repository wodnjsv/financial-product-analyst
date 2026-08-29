from __future__ import annotations

from datetime import UTC, date, datetime

import psycopg

from financial_agent.documents import SectionType
from financial_agent.retrieval.documents import DocumentCandidateHit
from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_MANIFEST_HASH,
    VALID_RECORD_HASH,
)


DATASET_VERSION = "document-search-v1"
MODEL_ID = "synthetic-embedding"
MODEL_VERSION = "1"
CUTOFF_DATE = date(2026, 8, 24)


def candidate_hit(
    chunk_id: str,
    *,
    document_id: str = "document-risk",
    entity_id: str = "selected-etf",
    keyword_rank: int | None = None,
    vector_rank: int | None = None,
) -> DocumentCandidateHit:
    return DocumentCandidateHit(
        dataset_version=DATASET_VERSION,
        entity_id=entity_id,
        document_id=document_id,
        chunk_id=chunk_id,
        section_type=SectionType.RISK_FACTOR,
        exact_text=f"Synthetic exact text for {chunk_id}.",
        source_id="source-approved",
        source_locator=f"synthetic/source#{document_id}/{chunk_id}",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        effective_from=date(2026, 8, 1),
        effective_to=None,
        document_version="2026-08-01",
        cutoff_eligible=True,
        publisher_approved=True,
        keyword_rank=keyword_rank,
        vector_rank=vector_rank,
        fused_score=None,
        evidence_id=None,
    )


def keyword_hits() -> tuple[DocumentCandidateHit, ...]:
    return (
        candidate_hit("risk-specific", keyword_rank=1),
        candidate_hit("risk-currency", keyword_rank=2),
    )


def vector_hits() -> tuple[DocumentCandidateHit, ...]:
    return (
        candidate_hit("risk-index", vector_rank=1),
        candidate_hit("risk-specific", vector_rank=2),
    )


def tied_keyword_hits() -> tuple[DocumentCandidateHit, ...]:
    return (
        candidate_hit("chunk-b", document_id="document-b", keyword_rank=1),
        candidate_hit("chunk-a", document_id="document-a", keyword_rank=1),
    )


def insert_document_search_corpus(
    connection: psycopg.Connection, *, dataset_version: str = DATASET_VERSION
) -> None:
    _insert_dataset(connection, dataset_version, status="building")
    _insert_entity(connection, dataset_version, "publisher-approved", "institution")
    _insert_entity(connection, dataset_version, "publisher-unofficial", "institution")
    _insert_entity(connection, dataset_version, "selected-etf", "product")
    _insert_entity(connection, dataset_version, "wrong-etf", "product")
    _insert_entity(connection, dataset_version, "selected-index", "index")
    _insert_entity(connection, dataset_version, "selected-policy", "institution")
    connection.execute(
        """
        INSERT INTO catalog.institution (dataset_version, entity_id, institution_kind)
        VALUES
          (%s, 'publisher-approved', 'regulator'),
          (%s, 'publisher-unofficial', 'media'),
          (%s, 'selected-policy', 'policy_authority')
        """,
        (dataset_version, dataset_version, dataset_version),
    )
    _insert_source(
        connection, dataset_version, "source-approved", "publisher-approved", True
    )
    _insert_source(
        connection,
        dataset_version,
        "source-unofficial",
        "publisher-unofficial",
        False,
    )
    connection.execute(
        """
        INSERT INTO search.embedding_model (
            model_id, model_version, dimension, distance_metric,
            approval_record_id, approved_at, model_hash
        ) VALUES (%s, %s, 3, 'cosine', 'synthetic-approval', %s, %s)
        ON CONFLICT (model_id, model_version) DO NOTHING
        """,
        (MODEL_ID, MODEL_VERSION, CREATED_AT, "d" * 64),
    )

    _insert_document(
        connection,
        dataset_version=dataset_version,
        document_id="document-risk",
        entity_id="selected-etf",
        source_id="source-approved",
        coverage_role="product_summary",
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        chunks=(
            ("risk-specific", "risk_factor", "specific risk", "[0.98,0.02,0]"),
            ("risk-index", "risk_factor", "index risk", "[0.95,0.05,0]"),
            ("risk-currency", "risk_factor", "currency risk", "[0.90,0.10,0]"),
            ("performance-near", "historical_performance_table", "performance risk", "[1,0,0]"),
            ("holdings-near", "full_holdings_table", "holdings risk", "[1,0,0]"),
        ),
    )
    _insert_document(
        connection,
        dataset_version=dataset_version,
        document_id="document-wrong",
        entity_id="wrong-etf",
        source_id="source-approved",
        coverage_role="product_summary",
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        chunks=(("wrong-near", "risk_factor", "identical risk", "[1,0,0]"),),
    )
    _insert_document(
        connection,
        dataset_version=dataset_version,
        document_id="document-late",
        entity_id="selected-etf",
        source_id="source-approved",
        coverage_role="product_full",
        # Still 2026-08-24 in UTC, but 2026-08-25 at the approved Seoul boundary.
        available_at=datetime(2026, 8, 24, 15, 30, tzinfo=UTC),
        chunks=(("late-near", "risk_factor", "late risk", "[1,0,0]"),),
    )
    _insert_document(
        connection,
        dataset_version=dataset_version,
        document_id="document-unofficial",
        entity_id="selected-etf",
        source_id="source-unofficial",
        coverage_role="official_update",
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        chunks=(("unofficial-near", "risk_factor", "unofficial risk", "[1,0,0]"),),
    )
    _insert_document(
        connection,
        dataset_version=dataset_version,
        document_id="document-expired",
        entity_id="selected-etf",
        source_id="source-approved",
        coverage_role="index_methodology",
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        effective_to=date(2026, 8, 23),
        chunks=(("expired-near", "risk_factor", "expired risk", "[1,0,0]"),),
    )
    _insert_document(
        connection,
        dataset_version=dataset_version,
        document_id="document-ineligible",
        entity_id="selected-etf",
        source_id="source-approved",
        coverage_role="policy_base",
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        cutoff_eligible=False,
        chunks=(("ineligible-near", "risk_factor", "ineligible risk", "[1,0,0]"),),
    )
    _insert_document(
        connection,
        dataset_version=dataset_version,
        document_id="document-index",
        entity_id="selected-index",
        source_id="source-approved",
        coverage_role="index_methodology",
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        binding_role="subject_index",
        chunks=(("index-method", "index_methodology", "index selection rules", "[0,1,0]"),),
    )
    _insert_document(
        connection,
        dataset_version=dataset_version,
        document_id="document-policy",
        entity_id="selected-policy",
        source_id="source-approved",
        coverage_role="policy_base",
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        binding_role="subject_policy",
        chunks=(("policy-structure", "legal_structure", "policy fund structure", "[0,0,1]"),),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def _insert_dataset(
    connection: psycopg.Connection, dataset_version: str, *, status: str
) -> None:
    connection.execute(
        """
        INSERT INTO operations.dataset_version (
            dataset_version, cutoff_date, status, manifest_hash, created_at
        ) VALUES (%s, DATE '2026-08-24', %s, %s, %s)
        """,
        (dataset_version, status, VALID_MANIFEST_HASH, CREATED_AT),
    )


def _insert_entity(
    connection: psycopg.Connection,
    dataset_version: str,
    entity_id: str,
    entity_type: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog.entity (
            dataset_version, entity_id, entity_type, canonical_name,
            normalized_name, record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            entity_id,
            entity_type,
            f"Canonical {entity_id}",
            f"canonical {entity_id}",
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def _insert_source(
    connection: psycopg.Connection,
    dataset_version: str,
    source_id: str,
    publisher: str,
    eligible_for_claim: bool,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence.source_record (
            dataset_version, source_id, publisher, publisher_type,
            source_title, source_type, authority_tier, source_locator_root,
            content_checksum, eligible_for_claim, record_hash, created_at
        ) VALUES (%s, %s, %s, 'synthetic', 'Synthetic source', 'document',
                  'synthetic', %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            source_id,
            publisher,
            f"synthetic/{source_id}",
            "c" * 64,
            eligible_for_claim,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )


def _insert_document(
    connection: psycopg.Connection,
    *,
    dataset_version: str,
    document_id: str,
    entity_id: str,
    source_id: str,
    coverage_role: str,
    available_at: datetime,
    chunks: tuple[tuple[str, str, str, str], ...],
    binding_role: str = "subject_product",
    effective_to: date | None = None,
    cutoff_eligible: bool = True,
) -> None:
    published_at = datetime(2026, 8, 1, tzinfo=UTC)
    connection.execute(
        """
        INSERT INTO document.document_record (
            dataset_version, document_id, source_id, document_title,
            document_type, object_key, content_checksum, published_at,
            available_at, record_hash, created_at
        ) VALUES (%s, %s, %s, %s, 'summary_prospectus', %s, %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            document_id,
            source_id,
            f"Synthetic {document_id}",
            f"synthetic/{document_id}.pdf",
            "e" * 64,
            published_at,
            available_at,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO document.document_profile (
            dataset_version, document_id, document_version, publisher_role,
            jurisdiction, original_language, effective_from, effective_to,
            extraction_method, cutoff_eligible, record_hash, created_at
        ) VALUES (%s, %s, '2026-08-01', 'regulator_disclosure', 'US', 'en',
                  DATE '2026-08-01', %s, 'text_layer', %s, %s, %s)
        """,
        (
            dataset_version,
            document_id,
            effective_to,
            cutoff_eligible,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO document.document_entity_binding (
            dataset_version, binding_id, document_id, entity_id, binding_role,
            record_hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            dataset_version,
            f"binding-{document_id}",
            document_id,
            entity_id,
            binding_role,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO document.document_coverage (
            dataset_version, coverage_id, entity_id, required_document_role,
            coverage_status, document_id, record_hash, created_at
        ) VALUES (%s, %s, %s, %s, 'indexed', %s, %s, %s)
        """,
        (
            dataset_version,
            f"coverage-{document_id}",
            entity_id,
            coverage_role,
            document_id,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    for ordinal, (chunk_id, section_type, exact_text, vector) in enumerate(chunks):
        content_hash = _sha256(exact_text)
        connection.execute(
            """
            INSERT INTO document.document_chunk (
                dataset_version, chunk_id, document_id, ordinal,
                page_start, page_end, section, section_type, section_path,
                character_start, character_end, exact_text,
                normalized_search_text, content_hash, record_hash, created_at
            ) VALUES (%s, %s, %s, %s, 1, 1, %s, %s, %s, 0, %s, %s, %s,
                      %s, %s, %s)
            """,
            (
                dataset_version,
                chunk_id,
                document_id,
                ordinal,
                section_type,
                section_type,
                section_type,
                len(exact_text),
                exact_text,
                exact_text.casefold(),
                content_hash,
                VALID_RECORD_HASH,
                CREATED_AT,
            ),
        )
        connection.execute(
            """
            INSERT INTO search.document_embedding (
                dataset_version, embedding_id, document_id, chunk_id,
                chunk_content_hash, model_id, model_version, dimension,
                embedding, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 3,
                      %s::cdb_admin.vector, %s)
            """,
            (
                dataset_version,
                f"embedding-{chunk_id}",
                document_id,
                chunk_id,
                content_hash,
                MODEL_ID,
                MODEL_VERSION,
                vector,
                CREATED_AT,
            ),
        )


def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()
