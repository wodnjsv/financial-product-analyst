"""Deterministically rebase verified document corpus rows to a new dataset."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from enum import Enum
import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.db.repositories.documents import (
    CapturedDocumentCorpus,
    DocumentCorpusRepository,
    source_artifact_record_hash,
)
from financial_agent.db.schema.catalog import entity
from financial_agent.db.schema.document import (
    document_chunk,
    document_coverage,
    document_entity_binding,
    document_record,
)
from financial_agent.db.schema.evidence import source_record
from financial_agent.db.schema.operations import dataset_version
from financial_agent.db.schema.search import document_embedding
from financial_agent.documents.models import DocumentChunkDraft, DocumentCoverageDraft
from financial_agent.embeddings.contracts import (
    APPROVED_MODEL,
    EmbeddingChunk,
    EmbeddingResult,
)
from financial_agent.embeddings.repository import EmbeddingRepository, PendingEmbedding


class CorpusCarryForwardError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CorpusCarryForwardReport:
    source_dataset: str
    target_dataset: str
    document_count: int
    coverage_count: int
    chunk_count: int
    embedding_count: int


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _record_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_value(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _rebase_chunk(
    chunk: DocumentChunkDraft, target_dataset: str
) -> DocumentChunkDraft:
    target = replace(chunk, dataset_version=target_dataset, record_hash="0" * 64)
    payload = asdict(target)
    payload.pop("embedding_text")
    payload.pop("record_hash")
    return replace(target, record_hash=_record_hash(payload))


def _rebase_coverage(
    coverage: DocumentCoverageDraft, target_dataset: str
) -> DocumentCoverageDraft:
    coverage_id = (
        f"coverage:{target_dataset}:{coverage.entity_id}:"
        f"{coverage.required_document_role.value}"
    )
    target = replace(
        coverage,
        coverage_id=coverage_id,
        dataset_version=target_dataset,
        record_hash="0" * 64,
    )
    payload = asdict(target)
    payload.pop("record_hash")
    return replace(target, record_hash=_record_hash(payload))


def rebase_captured_corpus(
    captured: CapturedDocumentCorpus,
    *,
    target_dataset: str,
) -> CapturedDocumentCorpus:
    """Return the same verified corpus under a new dataset-scoped identity."""

    if not target_dataset.strip():
        raise ValueError("target_dataset_blank")

    source_corpus = captured.corpus
    profile = replace(
        source_corpus.profile,
        dataset_version=target_dataset,
        record_hash="0" * 64,
    )
    profile_payload = asdict(profile)
    profile_payload.pop("record_hash")
    profile = replace(profile, record_hash=_record_hash(profile_payload))

    bindings = []
    for source_binding in source_corpus.entity_bindings:
        binding = replace(
            source_binding,
            dataset_version=target_dataset,
            record_hash="0" * 64,
        )
        binding_payload = asdict(binding)
        binding_payload.pop("record_hash")
        bindings.append(
            replace(binding, record_hash=_record_hash(binding_payload))
        )

    corpus = replace(
        source_corpus,
        dataset_version=target_dataset,
        profile=profile,
        entity_bindings=tuple(bindings),
        chunks=tuple(
            _rebase_chunk(chunk, target_dataset)
            for chunk in source_corpus.chunks
        ),
        coverage=_rebase_coverage(source_corpus.coverage, target_dataset),
    )
    artifact = replace(
        captured.source_artifact,
        dataset_version=target_dataset,
        record_hash="0" * 64,
    )
    artifact = replace(
        artifact,
        record_hash=source_artifact_record_hash(artifact),
    )
    rebased = CapturedDocumentCorpus(
        source=captured.source,
        corpus=corpus,
        source_artifact=artifact,
        additional_coverages=tuple(
            _rebase_coverage(coverage, target_dataset)
            for coverage in captured.additional_coverages
        ),
    )
    DocumentCorpusRepository.validate_captured_corpus(rebased)
    return rebased


async def _require_compatible_datasets(
    engine: AsyncEngine,
    source_dataset: str,
    target_dataset: str,
) -> None:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.select(
                    dataset_version.c.dataset_version,
                    dataset_version.c.cutoff_date,
                    dataset_version.c.status,
                ).where(
                    dataset_version.c.dataset_version.in_(
                        (source_dataset, target_dataset)
                    )
                )
            )
        ).mappings().all()
    by_version = {row["dataset_version"]: row for row in rows}
    if set(by_version) != {source_dataset, target_dataset}:
        raise CorpusCarryForwardError("dataset_not_found")
    if by_version[target_dataset]["status"] != "building":
        raise CorpusCarryForwardError("target_dataset_not_building")
    if (
        by_version[source_dataset]["cutoff_date"]
        != by_version[target_dataset]["cutoff_date"]
    ):
        raise CorpusCarryForwardError("dataset_cutoff_mismatch")


async def _eligible_document_ids(
    engine: AsyncEngine, source_dataset: str
) -> tuple[str, ...]:
    eligible = EmbeddingRepository.eligible_statement(source_dataset).subquery()
    async with engine.connect() as connection:
        return tuple(
            str(value)
            for value in (
                await connection.execute(
                    sa.select(eligible.c.document_id)
                    .distinct()
                    .order_by(eligible.c.document_id)
                )
            ).scalars()
        )


async def _source_counts(
    engine: AsyncEngine,
    *,
    source_dataset: str,
    document_ids: tuple[str, ...],
) -> tuple[int, int, int, int]:
    filters = (
        document_record.c.dataset_version == source_dataset,
        document_record.c.document_id.in_(document_ids),
    )
    async with engine.connect() as connection:
        documents = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_record)
                .where(*filters)
            )
            or 0
        )
        coverages = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_coverage)
                .where(
                    document_coverage.c.dataset_version == source_dataset,
                    document_coverage.c.document_id.in_(document_ids),
                )
            )
            or 0
        )
        chunks = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_chunk)
                .where(
                    document_chunk.c.dataset_version == source_dataset,
                    document_chunk.c.document_id.in_(document_ids),
                )
            )
            or 0
        )
        embeddings = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_embedding)
                .where(
                    document_embedding.c.dataset_version == source_dataset,
                    document_embedding.c.document_id.in_(document_ids),
                    document_embedding.c.model_id == APPROVED_MODEL.model_id,
                    document_embedding.c.model_version
                    == APPROVED_MODEL.model_version,
                )
            )
            or 0
        )
    counts = (documents, coverages, chunks, embeddings)
    if documents != len(document_ids) or chunks != embeddings:
        raise CorpusCarryForwardError("source_count_mismatch")
    return counts


async def _require_target_entities(
    engine: AsyncEngine,
    *,
    source_dataset: str,
    target_dataset: str,
    document_ids: tuple[str, ...],
) -> None:
    if not document_ids:
        raise CorpusCarryForwardError("source_corpus_empty")
    async with engine.connect() as connection:
        bound_ids = set(
            str(value)
            for value in (
                await connection.execute(
                    sa.select(document_entity_binding.c.entity_id).where(
                        document_entity_binding.c.dataset_version == source_dataset,
                        document_entity_binding.c.document_id.in_(document_ids),
                    )
                )
            ).scalars()
        )
        publisher_ids = set(
            str(value)
            for value in (
                await connection.execute(
                    sa.select(source_record.c.publisher)
                    .select_from(
                        source_record.join(
                            document_record,
                            sa.and_(
                                source_record.c.dataset_version
                                == document_record.c.dataset_version,
                                source_record.c.source_id == document_record.c.source_id,
                            ),
                        )
                    )
                    .where(
                        source_record.c.dataset_version == source_dataset,
                        document_record.c.document_id.in_(document_ids),
                    )
                )
            ).scalars()
        )
        required = bound_ids | publisher_ids
        present = set(
            str(value)
            for value in (
                await connection.execute(
                    sa.select(entity.c.entity_id).where(
                        entity.c.dataset_version == target_dataset,
                        entity.c.entity_id.in_(required),
                    )
                )
            ).scalars()
        )
    if present != required:
        raise CorpusCarryForwardError("target_entity_missing")


async def _copy_document_embeddings(
    engine: AsyncEngine,
    *,
    source_dataset: str,
    rebased: CapturedDocumentCorpus,
) -> None:
    corpus = rebased.corpus
    async with engine.connect() as connection:
        source_rows = (
            await connection.execute(
                sa.select(
                    document_embedding.c.chunk_id,
                    document_embedding.c.embedding,
                )
                .where(
                    document_embedding.c.dataset_version == source_dataset,
                    document_embedding.c.document_id == corpus.document_id,
                    document_embedding.c.model_id == APPROVED_MODEL.model_id,
                    document_embedding.c.model_version == APPROVED_MODEL.model_version,
                    document_embedding.c.dimension == APPROVED_MODEL.dimension,
                )
                .order_by(document_embedding.c.chunk_id)
            )
        ).all()
    vectors = {
        str(row.chunk_id): tuple(float(value) for value in row.embedding)
        for row in source_rows
    }
    if set(vectors) != {chunk.chunk_id for chunk in corpus.chunks}:
        raise CorpusCarryForwardError("source_embedding_coverage_mismatch")

    pending = tuple(
        PendingEmbedding(
            chunk=EmbeddingChunk(
                dataset_version=corpus.dataset_version,
                document_id=corpus.document_id,
                chunk_id=chunk.chunk_id,
                content_hash=chunk.content_hash,
                document_title=corpus.document_title,
                section_path=chunk.section_path,
                exact_text=chunk.exact_text,
                section_type=chunk.section_type.value,
            ),
            result=EmbeddingResult(vectors[chunk.chunk_id], 1, None),
        )
        for chunk in corpus.chunks
    )
    repository = EmbeddingRepository(engine)
    await repository.append_embeddings(APPROVED_MODEL, pending)

    async with engine.connect() as connection:
        target_rows = (
            await connection.execute(
                sa.select(
                    document_embedding.c.chunk_id,
                    document_embedding.c.embedding,
                )
                .where(
                    document_embedding.c.dataset_version == corpus.dataset_version,
                    document_embedding.c.document_id == corpus.document_id,
                    document_embedding.c.model_id == APPROVED_MODEL.model_id,
                    document_embedding.c.model_version == APPROVED_MODEL.model_version,
                )
            )
        ).all()
    target_vectors = {
        str(row.chunk_id): tuple(float(value) for value in row.embedding)
        for row in target_rows
    }
    if target_vectors != vectors:
        raise CorpusCarryForwardError("target_embedding_mismatch")


async def carry_forward_dart_corpus(
    engine: AsyncEngine,
    *,
    source_dataset: str,
    target_dataset: str,
) -> CorpusCarryForwardReport:
    """Copy an eligible DART corpus locally without calling an embedder."""

    if source_dataset == target_dataset:
        raise CorpusCarryForwardError("source_target_same")
    await _require_compatible_datasets(engine, source_dataset, target_dataset)
    document_ids = await _eligible_document_ids(engine, source_dataset)
    expected_counts = await _source_counts(
        engine,
        source_dataset=source_dataset,
        document_ids=document_ids,
    )
    await _require_target_entities(
        engine,
        source_dataset=source_dataset,
        target_dataset=target_dataset,
        document_ids=document_ids,
    )

    documents = DocumentCorpusRepository(engine)
    embeddings = EmbeddingRepository(engine)
    await embeddings.register_model(APPROVED_MODEL)
    for document_id in document_ids:
        source = await documents.get_captured_corpus(source_dataset, document_id)
        target = rebase_captured_corpus(source, target_dataset=target_dataset)
        await documents.append_captured_corpus(target)
        await _copy_document_embeddings(
            engine,
            source_dataset=source_dataset,
            rebased=target,
        )

    async with engine.connect() as connection:
        document_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_record)
                .where(
                    document_record.c.dataset_version == target_dataset,
                    document_record.c.document_id.in_(document_ids),
                )
            )
            or 0
        )
        coverage_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_coverage)
                .where(
                    document_coverage.c.dataset_version == target_dataset,
                    document_coverage.c.document_id.in_(document_ids),
                )
            )
            or 0
        )
        chunk_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_chunk)
                .where(
                    document_chunk.c.dataset_version == target_dataset,
                    document_chunk.c.document_id.in_(document_ids),
                )
            )
            or 0
        )
        embedding_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_embedding)
                .where(
                    document_embedding.c.dataset_version == target_dataset,
                    document_embedding.c.document_id.in_(document_ids),
                    document_embedding.c.model_id == APPROVED_MODEL.model_id,
                    document_embedding.c.model_version == APPROVED_MODEL.model_version,
                )
            )
            or 0
        )
    if (
        document_count,
        coverage_count,
        chunk_count,
        embedding_count,
    ) != expected_counts:
        raise CorpusCarryForwardError("target_count_mismatch")
    return CorpusCarryForwardReport(
        source_dataset=source_dataset,
        target_dataset=target_dataset,
        document_count=document_count,
        coverage_count=coverage_count,
        chunk_count=chunk_count,
        embedding_count=embedding_count,
    )
