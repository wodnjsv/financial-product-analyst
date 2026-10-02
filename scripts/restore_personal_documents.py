"""Restore at most 100 verified document corpora from retained binary exports.

The unlogged staging schema is temporary to this command. Real records go
through the existing corpus/embedding repositories with rebased identities.
No provider is called.
"""

import argparse
import asyncio
import json
from pathlib import Path

import psycopg
from psycopg import sql
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.db.repositories.documents import DocumentCorpusRepository
from financial_agent.db.schema.catalog import entity, institution
from financial_agent.db.schema.search import document_embedding
from financial_agent.documents.carry_forward import rebase_captured_corpus
from financial_agent.embeddings.contracts import APPROVED_MODEL, EmbeddingChunk, EmbeddingResult
from financial_agent.embeddings.repository import EmbeddingRepository, PendingEmbedding
from financial_agent.ingestion.local_budget import BudgetedWriter, StorageBudget, require_local_target
from financial_agent.ingestion.models import MappedRow
from financial_agent.ingestion.sources import sha256_path


DATASET = "personal-2026-08-24-v1"
STAGING = "personal_corpus_restore"
TABLES = {
    "dataset_version": "operations", "entity": "catalog", "institution": "catalog",
    "source_record": "evidence", "document_record": "document",
    "document_profile": "document", "document_entity_binding": "document",
    "document_coverage": "document", "document_chunk": "document",
    "document_source_artifact": "document", "embedding_model": "search",
    "document_embedding": "search",
}


async def restore(root: Path, url: str):
    require_local_target(url)
    output = root / "data/personal-local"
    structured = json.loads((output / "structured-report.json").read_text())
    if not structured["passed"] or structured["dataset_version"] != DATASET:
        raise RuntimeError("STRUCTURED_BUILD_REQUIRED")
    export = root / "data/generated/local-postgres/dart-source-export"
    manifest = json.loads((output / "manifest.json").read_text())
    expected = manifest["personal_scope"]["document_export_hashes"]
    for name in TABLES:
        if sha256_path(export / f"{name}.bin") != expected.get(f"{name}.bin"):
            raise RuntimeError("CORPUS_EXPORT_HASH_MISMATCH")
    engine_url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    target = create_async_engine(engine_url, pool_size=2, max_overflow=0,
        connect_args={"options": "-c timezone=UTC -c role=fa_build -c statement_timeout=300000"})
    reader = create_async_engine(engine_url, pool_size=2, max_overflow=0,
        execution_options={"schema_translate_map": {s: STAGING for s in set(TABLES.values())}},
        connect_args={"options": "-c timezone=UTC"})
    writer = BudgetedWriter(target, StorageBudget(**json.loads((output / "budget.json").read_text())), root)
    staging_created = False
    try:
        await writer.check_capacity()
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(STAGING)))
            staging_created = True
            for name, schema in TABLES.items():
                await writer.check_capacity()
                connection.execute(sql.SQL("CREATE UNLOGGED TABLE {}.{} (LIKE {}.{})").format(
                    sql.Identifier(STAGING), sql.Identifier(name), sql.Identifier(schema), sql.Identifier(name)))
                with connection.cursor().copy(sql.SQL("COPY {}.{} FROM STDIN (FORMAT BINARY)").format(
                    sql.Identifier(STAGING), sql.Identifier(name))) as copy:
                    with (export / f"{name}.bin").open("rb") as source:
                        while block := source.read(1024 * 1024):
                            copy.write(block)
            source_dataset = connection.execute(f"SELECT dataset_version FROM {STAGING}.dataset_version").fetchone()[0]
            # Include only documents whose entire binding set resolves to current
            # canonical entities. Prefer sampled holdings products, then stable IDs.
            selected = connection.execute(f"""
                SELECT d.document_id FROM {STAGING}.document_record d
                WHERE EXISTS (SELECT 1 FROM {STAGING}.document_embedding v
                    WHERE v.document_id=d.document_id AND v.dataset_version=d.dataset_version)
                AND EXISTS (SELECT 1 FROM {STAGING}.document_entity_binding b
                    WHERE b.document_id=d.document_id AND b.dataset_version=d.dataset_version)
                AND NOT EXISTS (SELECT 1 FROM {STAGING}.document_entity_binding b
                    WHERE b.document_id=d.document_id AND b.dataset_version=d.dataset_version
                    AND NOT EXISTS (SELECT 1 FROM catalog.entity e
                        WHERE e.dataset_version=%s AND e.entity_id=b.entity_id))
                ORDER BY EXISTS (
                    SELECT 1 FROM {STAGING}.document_entity_binding b
                    JOIN relation.relation_record r ON r.subject_id=b.entity_id
                    WHERE b.document_id=d.document_id AND r.dataset_version=%s
                        AND r.predicate_id='holdsSecurity'
                ) DESC, d.document_id
                LIMIT 100
            """, (DATASET, DATASET)).fetchall()
            document_ids = tuple(row[0] for row in selected)
            if len(document_ids) != 100:
                raise RuntimeError("LOCAL_DOCUMENT_SAMPLE_INSUFFICIENT")
            # Speed the per-document reader without duplicating production indexes.
            for name in ("document_chunk", "document_embedding", "document_record",
                         "document_profile", "document_entity_binding", "document_coverage",
                         "document_source_artifact"):
                connection.execute(sql.SQL("CREATE INDEX ON {}.{} (document_id)").format(
                    sql.Identifier(STAGING), sql.Identifier(name)))

        source_repo = DocumentCorpusRepository(reader)
        target_repo = DocumentCorpusRepository(target)
        embeddings = EmbeddingRepository(target)
        await embeddings.register_model(APPROVED_MODEL)
        chunk_count = 0
        for index, document_id in enumerate(document_ids, start=1):
            await writer.check_capacity()
            captured = await source_repo.get_captured_corpus(source_dataset, document_id)
            rebased = rebase_captured_corpus(captured, target_dataset=DATASET)
            publisher = captured.source.publisher
            async with target.connect() as connection:
                exists = await connection.scalar(sa.select(entity.c.entity_id).where(
                    entity.c.dataset_version == DATASET, entity.c.entity_id == publisher))
            if not exists:
                records = {}
                async with reader.connect() as connection:
                    for table in (entity, institution):
                        row = (await connection.execute(sa.select(table).where(
                            table.c.dataset_version == source_dataset,
                            table.c.entity_id == publisher))).mappings().one()
                        records[table.fullname] = ({k: v for k, v in row.items()
                            if k not in {"dataset_version", "created_at"}},)
                await writer.write_rows(DATASET, (MappedRow(0, "accepted", records, ()),))
            await target_repo.append_captured_corpus(rebased)
            async with reader.connect() as connection:
                vectors = {row.chunk_id: tuple(float(v) for v in row.embedding)
                    for row in (await connection.execute(sa.select(document_embedding).where(
                        document_embedding.c.dataset_version == source_dataset,
                        document_embedding.c.document_id == document_id,
                        document_embedding.c.model_id == APPROVED_MODEL.model_id,
                        document_embedding.c.model_version == APPROVED_MODEL.model_version,
                        document_embedding.c.dimension == APPROVED_MODEL.dimension))).all()}
            if set(vectors) != {chunk.chunk_id for chunk in rebased.corpus.chunks}:
                raise RuntimeError("SOURCE_EMBEDDING_COVERAGE_MISMATCH")
            await embeddings.append_embeddings(APPROVED_MODEL, tuple(PendingEmbedding(
                chunk=EmbeddingChunk(dataset_version=DATASET, document_id=document_id,
                    chunk_id=c.chunk_id, content_hash=c.content_hash,
                    document_title=rebased.corpus.document_title, section_path=c.section_path,
                    exact_text=c.exact_text, section_type=c.section_type.value),
                result=EmbeddingResult(vectors[c.chunk_id], 1, None),
            ) for c in rebased.corpus.chunks))
            async with target.connect() as connection:
                restored_vectors = {row.chunk_id: tuple(float(v) for v in row.embedding)
                    for row in (await connection.execute(sa.select(document_embedding).where(
                        document_embedding.c.dataset_version == DATASET,
                        document_embedding.c.document_id == document_id,
                        document_embedding.c.model_id == APPROVED_MODEL.model_id,
                        document_embedding.c.model_version == APPROVED_MODEL.model_version))).all()}
            if restored_vectors != vectors:
                raise RuntimeError("RESTORED_EMBEDDING_VALUE_MISMATCH")
            chunk_count += len(rebased.corpus.chunks)
            print({"documents_restored": index, "chunks": chunk_count}, flush=True)
        report = {"dataset_version": DATASET, "documents": len(document_ids),
            "document_ids": document_ids, "chunks": chunk_count, "embeddings": chunk_count,
            "embedding_api_calls": 0, "source_dataset": source_dataset,
            "storage": await writer.check_capacity()}
        (output / "document-report.json").write_text(json.dumps(report, indent=2))
    finally:
        await reader.dispose()
        await target.dispose()
        if staging_created:
            with psycopg.connect(url, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(STAGING)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--database-url", default="postgresql://localhost/financial_agent_local")
    args = parser.parse_args()
    asyncio.run(restore(args.workspace_root.resolve(), args.database_url))
