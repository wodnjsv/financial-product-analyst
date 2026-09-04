from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.repositories.documents import DocumentCorpusRepository
from financial_agent.db.schema.search import document_embedding
from financial_agent.documents.carry_forward import carry_forward_dart_corpus
from financial_agent.embeddings.contracts import (
    APPROVED_MODEL,
    EmbeddingChunk,
    EmbeddingResult,
    embedding_id,
)
from financial_agent.embeddings.repository import EmbeddingRepository, PendingEmbedding
from tests.db.test_document_repository import _captured, _corpus
from tests.fixtures.db.synthetic_dataset import (
    insert_building_dataset,
    insert_entity,
)


def _insert_document_entities(
    database_url: str, source_dataset: str, target_dataset: str
) -> None:
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        for dataset in (source_dataset, target_dataset):
            insert_building_dataset(connection, dataset)
            insert_entity(
                connection,
                dataset_version=dataset,
                entity_id="publisher-one",
                entity_type="institution",
                canonical_name="DART Publisher",
            )
            connection.execute(
                """
                INSERT INTO catalog.institution (
                    dataset_version, entity_id, institution_kind
                ) VALUES (%s, 'publisher-one', 'regulator')
                """,
                (dataset,),
            )
            insert_entity(
                connection,
                dataset_version=dataset,
                entity_id="product-one",
                entity_type="product",
            )
            connection.execute(
                """
                INSERT INTO catalog.product (
                    dataset_version, entity_id, product_family
                ) VALUES (%s, 'product-one', 'domestic_etf')
                """,
                (dataset,),
            )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_carry_forward_preserves_text_and_vector_but_rekeys_dataset(
    ingestion_build_engine: AsyncEngine,
    ingestion_migrated_database_url: str,
) -> None:
    suffix = uuid4().hex
    source_dataset = f"carry-source-{suffix}"
    target_dataset = f"carry-target-{suffix}"
    _insert_document_entities(
        ingestion_migrated_database_url, source_dataset, target_dataset
    )
    source_corpus = _corpus(dataset_version=source_dataset)
    document_repository = DocumentCorpusRepository(ingestion_build_engine)
    await document_repository.append_captured_corpus(_captured(source_corpus))
    await document_repository.transition_source_retention(
        source_dataset,
        source_corpus.document_id,
        "delete_authorized",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    await document_repository.transition_source_retention(
        source_dataset,
        source_corpus.document_id,
        "metadata_only_deleted",
        occurred_at=datetime(2026, 9, 1, 0, 1, tzinfo=UTC),
    )

    chunk = source_corpus.chunks[0]
    embedding_chunk = EmbeddingChunk(
        dataset_version=source_dataset,
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        content_hash=chunk.content_hash,
        document_title=source_corpus.document_title,
        section_path=chunk.section_path,
        exact_text=chunk.exact_text,
        section_type=chunk.section_type.value,
    )
    embedding_repository = EmbeddingRepository(ingestion_build_engine)
    await embedding_repository.register_model(APPROVED_MODEL)
    await embedding_repository.append_embeddings(
        APPROVED_MODEL,
        (
            PendingEmbedding(
                embedding_chunk,
                EmbeddingResult((0.125,) * 1024, 1, None),
            ),
        ),
    )

    first = await carry_forward_dart_corpus(
        ingestion_build_engine,
        source_dataset=source_dataset,
        target_dataset=target_dataset,
    )
    second = await carry_forward_dart_corpus(
        ingestion_build_engine,
        source_dataset=source_dataset,
        target_dataset=target_dataset,
    )

    assert first == second
    assert first.document_count == 1
    assert first.coverage_count == 1
    assert first.chunk_count == 1
    assert first.embedding_count == 1
    target = await document_repository.get_captured_corpus(
        target_dataset, source_corpus.document_id
    )
    assert target.corpus.chunks[0].exact_text == chunk.exact_text
    assert target.corpus.chunks[0].content_hash == chunk.content_hash
    expected_target_id = embedding_id(
        APPROVED_MODEL,
        EmbeddingChunk(
            dataset_version=target_dataset,
            document_id=embedding_chunk.document_id,
            chunk_id=embedding_chunk.chunk_id,
            content_hash=embedding_chunk.content_hash,
            document_title=embedding_chunk.document_title,
            section_path=embedding_chunk.section_path,
            exact_text=embedding_chunk.exact_text,
            section_type=embedding_chunk.section_type,
        ),
    )
    async with ingestion_build_engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.select(
                    document_embedding.c.dataset_version,
                    document_embedding.c.embedding_id,
                    sa.cast(document_embedding.c.embedding, sa.Text),
                )
                .where(
                    document_embedding.c.dataset_version.in_(
                        (source_dataset, target_dataset)
                    )
                )
                .order_by(document_embedding.c.dataset_version)
            )
        ).all()
    assert len(rows) == 2
    assert rows[0][2] == rows[1][2]
    assert {row.embedding_id for row in rows if row.dataset_version == target_dataset} == {
        expected_target_id
    }
