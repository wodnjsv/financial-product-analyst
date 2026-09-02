"""PostgreSQL authority boundary for approved DART document embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from financial_agent.db.schema.catalog import entity, product
from financial_agent.db.schema.document import (
    document_chunk,
    document_entity_binding,
    document_profile,
    document_record,
    document_source_artifact,
)
from financial_agent.db.schema.evidence import source_record
from financial_agent.db.schema.evidence import evidence_record
from financial_agent.db.schema.operations import (
    active_dataset,
    dataset_readiness,
    dataset_version,
)
from financial_agent.db.schema.relation import relation_record
from financial_agent.db.schema.search import document_embedding, embedding_model
from financial_agent.embeddings.contracts import (
    EmbeddingChunk,
    EmbeddingModelContract,
    EmbeddingResult,
    embedding_id,
    validate_result,
)


class EmbeddingRepositoryError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PendingEmbedding:
    chunk: EmbeddingChunk
    result: EmbeddingResult


@dataclass(frozen=True, slots=True)
class EmbeddingPreflight:
    dataset_status: str
    eligible_chunk_count: int
    existing_exact_embedding_count: int
    missing_embedding_count: int
    stale_embedding_count: int
    orphan_embedding_count: int


@dataclass(frozen=True, slots=True)
class EmbeddingReconciliation:
    eligible_count: int
    exact_count: int
    missing_count: int
    duplicate_count: int
    stale_count: int
    orphan_count: int
    wrong_dimension_count: int
    embedding_bytes: int


@dataclass(frozen=True, slots=True)
class SampleCandidate:
    canonical_product_name: str
    entity_id: str
    strategy_chunk_count: int
    risk_chunk_count: int


@dataclass(frozen=True, slots=True)
class ProtectedCounts:
    evidence_count: int
    relation_count: int
    readiness_count: int
    active_dataset_count: int


def _same_document(left: sa.FromClause, right: sa.FromClause) -> sa.ColumnElement[bool]:
    return sa.and_(
        left.c.dataset_version == right.c.dataset_version,
        left.c.document_id == right.c.document_id,
    )


def _exact_embedding_match(
    eligible: sa.FromClause,
    model: EmbeddingModelContract,
) -> sa.ColumnElement[bool]:
    return sa.and_(
        document_embedding.c.dataset_version == eligible.c.dataset_version,
        document_embedding.c.document_id == eligible.c.document_id,
        document_embedding.c.chunk_id == eligible.c.chunk_id,
        document_embedding.c.chunk_content_hash == eligible.c.content_hash,
        document_embedding.c.model_id == model.model_id,
        document_embedding.c.model_version == model.model_version,
        document_embedding.c.dimension == model.dimension,
    )


class EmbeddingRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @staticmethod
    def eligible_statement(dataset: str) -> sa.Select:
        if not isinstance(dataset, str) or not dataset.strip():
            raise EmbeddingRepositoryError("dataset_version_blank")
        return (
            sa.select(
                document_chunk.c.dataset_version,
                document_chunk.c.document_id,
                document_chunk.c.chunk_id,
                document_chunk.c.content_hash,
                document_chunk.c.section_type,
                document_record.c.document_title,
                document_chunk.c.section_path,
                document_chunk.c.exact_text,
            )
            .select_from(
                document_chunk.join(
                    document_record,
                    _same_document(document_chunk, document_record),
                )
                .join(
                    document_profile,
                    _same_document(document_chunk, document_profile),
                )
                .join(
                    document_source_artifact,
                    _same_document(document_chunk, document_source_artifact),
                )
                .join(
                    source_record,
                    sa.and_(
                        source_record.c.dataset_version
                        == document_record.c.dataset_version,
                        source_record.c.source_id == document_record.c.source_id,
                    ),
                )
                .join(
                    dataset_version,
                    dataset_version.c.dataset_version
                    == document_chunk.c.dataset_version,
                )
            )
            .where(
                document_chunk.c.dataset_version == dataset.strip(),
                dataset_version.c.status == "building",
                document_profile.c.cutoff_eligible.is_(True),
                document_source_artifact.c.media_type == "application/pdf",
                document_source_artifact.c.filing_locator.like(
                    "https://dart.fss.or.kr/%"
                ),
                document_source_artifact.c.attachment_locator.like(
                    "https://dart.fss.or.kr/%"
                ),
                document_source_artifact.c.retention_disposition
                == "metadata_only_deleted",
                source_record.c.source_type == "filing",
                source_record.c.authority_tier == "official_primary",
                source_record.c.eligible_for_claim.is_(True),
            )
        )

    async def preflight(
        self,
        dataset: str,
        model: EmbeddingModelContract,
    ) -> EmbeddingPreflight:
        eligible = self.eligible_statement(dataset).subquery("eligible_chunks")
        exact_match = _exact_embedding_match(eligible, model)
        async with self._engine.connect() as connection:
            status = await connection.scalar(
                sa.select(dataset_version.c.status).where(
                    dataset_version.c.dataset_version == dataset
                )
            )
            if status is None:
                raise EmbeddingRepositoryError("dataset_not_found")
            eligible_count = int(
                await connection.scalar(sa.select(sa.func.count()).select_from(eligible))
                or 0
            )
            exact_count = int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(
                        eligible.join(document_embedding, exact_match)
                    )
                )
                or 0
            )
            missing_count = int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(eligible)
                    .where(
                        ~sa.exists(
                            sa.select(1).select_from(document_embedding).where(
                                exact_match
                            )
                        )
                    )
                )
                or 0
            )
            stale_count, orphan_count = await self._invalid_counts(
                connection,
                eligible,
                model,
                dataset,
            )
        return EmbeddingPreflight(
            dataset_status=str(status),
            eligible_chunk_count=eligible_count,
            existing_exact_embedding_count=exact_count,
            missing_embedding_count=missing_count,
            stale_embedding_count=stale_count,
            orphan_embedding_count=orphan_count,
        )

    async def register_model(self, model: EmbeddingModelContract) -> None:
        values = {
            "model_id": model.model_id,
            "model_version": model.model_version,
            "dimension": model.dimension,
            "distance_metric": model.distance_metric,
            "approval_record_id": model.approval_record_id,
            "approved_at": model.approved_at,
            "model_hash": model.model_hash,
        }
        statement = (
            postgresql.insert(embedding_model)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    embedding_model.c.model_id,
                    embedding_model.c.model_version,
                ]
            )
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)
            row = (
                await connection.execute(
                    sa.select(embedding_model).where(
                        embedding_model.c.model_id == model.model_id,
                        embedding_model.c.model_version == model.model_version,
                    )
                )
            ).mappings().one()
            if any(row[key] != value for key, value in values.items()):
                raise EmbeddingRepositoryError("model_contract_mismatch")

    async def resolve_product(
        self,
        dataset: str,
        canonical_product_name: str,
    ) -> str:
        if not isinstance(canonical_product_name, str) or not canonical_product_name:
            raise EmbeddingRepositoryError("product_not_exact")
        eligible = self.eligible_statement(dataset).subquery("eligible_chunks")
        statement = (
            sa.select(entity.c.entity_id)
            .select_from(
                entity.join(
                    product,
                    sa.and_(
                        product.c.dataset_version == entity.c.dataset_version,
                        product.c.entity_id == entity.c.entity_id,
                    ),
                )
                .join(
                    document_entity_binding,
                    sa.and_(
                        document_entity_binding.c.dataset_version
                        == entity.c.dataset_version,
                        document_entity_binding.c.entity_id == entity.c.entity_id,
                        document_entity_binding.c.binding_role == "subject_product",
                    ),
                )
                .join(
                    eligible,
                    sa.and_(
                        eligible.c.dataset_version == entity.c.dataset_version,
                        eligible.c.document_id
                        == document_entity_binding.c.document_id,
                    ),
                )
            )
            .where(
                entity.c.dataset_version == dataset,
                entity.c.canonical_name == canonical_product_name,
            )
            .distinct()
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).scalars().all()
        if len(rows) != 1:
            raise EmbeddingRepositoryError("product_not_exact")
        return str(rows[0])

    async def sample_candidates(
        self,
        dataset: str,
        *,
        limit: int,
    ) -> tuple[SampleCandidate, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise EmbeddingRepositoryError("limit_invalid")
        eligible = self.eligible_statement(dataset).subquery("eligible_chunks")
        strategy_count = sa.func.count(
            sa.distinct(eligible.c.chunk_id)
        ).filter(eligible.c.section_type == "investment_strategy")
        risk_count = sa.func.count(sa.distinct(eligible.c.chunk_id)).filter(
            eligible.c.section_type == "risk_factor"
        )
        statement = (
            sa.select(
                entity.c.canonical_name,
                entity.c.entity_id,
                strategy_count.label("strategy_chunk_count"),
                risk_count.label("risk_chunk_count"),
            )
            .select_from(
                entity.join(
                    product,
                    sa.and_(
                        product.c.dataset_version == entity.c.dataset_version,
                        product.c.entity_id == entity.c.entity_id,
                    ),
                )
                .join(
                    document_entity_binding,
                    sa.and_(
                        document_entity_binding.c.dataset_version
                        == entity.c.dataset_version,
                        document_entity_binding.c.entity_id == entity.c.entity_id,
                        document_entity_binding.c.binding_role == "subject_product",
                    ),
                )
                .join(
                    eligible,
                    sa.and_(
                        eligible.c.dataset_version == entity.c.dataset_version,
                        eligible.c.document_id
                        == document_entity_binding.c.document_id,
                    ),
                )
            )
            .where(entity.c.dataset_version == dataset)
            .group_by(entity.c.canonical_name, entity.c.entity_id)
            .having(strategy_count > 0, risk_count > 0)
            .order_by(entity.c.canonical_name, entity.c.entity_id)
            .limit(limit)
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return tuple(
            SampleCandidate(
                canonical_product_name=row["canonical_name"],
                entity_id=row["entity_id"],
                strategy_chunk_count=row["strategy_chunk_count"],
                risk_chunk_count=row["risk_chunk_count"],
            )
            for row in rows
        )

    async def missing_chunks(
        self,
        dataset: str,
        model: EmbeddingModelContract,
        *,
        limit: int | None,
        entity_id: str | None = None,
        section_types: tuple[str, ...] = (),
    ) -> tuple[EmbeddingChunk, ...]:
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise EmbeddingRepositoryError("limit_invalid")
        eligible = self.eligible_statement(dataset).subquery("eligible_chunks")
        exact_match = _exact_embedding_match(eligible, model)
        statement = sa.select(eligible).where(
            ~sa.exists(
                sa.select(1).select_from(document_embedding).where(exact_match)
            )
        )
        if entity_id is not None:
            bound_documents = sa.select(
                document_entity_binding.c.dataset_version,
                document_entity_binding.c.document_id,
            ).where(
                document_entity_binding.c.dataset_version == dataset,
                document_entity_binding.c.entity_id == entity_id,
                document_entity_binding.c.binding_role == "subject_product",
            )
            statement = statement.where(
                sa.tuple_(eligible.c.dataset_version, eligible.c.document_id).in_(
                    bound_documents
                )
            )
        if section_types:
            statement = statement.where(
                eligible.c.section_type.in_(section_types)
            )
        statement = statement.order_by(
            eligible.c.document_id,
            eligible.c.chunk_id,
        )
        if limit is not None:
            statement = statement.limit(limit)
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return tuple(
            EmbeddingChunk(
                dataset_version=row["dataset_version"],
                document_id=row["document_id"],
                chunk_id=row["chunk_id"],
                content_hash=row["content_hash"],
                document_title=row["document_title"],
                section_path=row["section_path"],
                exact_text=row["exact_text"],
                section_type=row["section_type"],
            )
            for row in rows
        )

    async def append_embeddings(
        self,
        model: EmbeddingModelContract,
        pending: tuple[PendingEmbedding, ...],
    ) -> int:
        if not pending:
            return 0
        values: list[dict[str, object]] = []
        for item in pending:
            validate_result(item.result)
            chunk = item.chunk
            if (
                len(chunk.content_hash) != 64
                or chunk.content_hash
                != hashlib.sha256(chunk.exact_text.encode("utf-8")).hexdigest()
                or not chunk.document_title.strip()
                or not chunk.section_path.strip()
            ):
                raise EmbeddingRepositoryError("chunk_contract_invalid")
            values.append(
                {
                    "dataset_version": chunk.dataset_version,
                    "embedding_id": embedding_id(model, chunk),
                    "document_id": chunk.document_id,
                    "chunk_id": chunk.chunk_id,
                    "chunk_content_hash": chunk.content_hash,
                    "model_id": model.model_id,
                    "model_version": model.model_version,
                    "dimension": model.dimension,
                    "embedding": [float(value) for value in item.result.vector],
                    "created_at": datetime.now(UTC),
                }
            )
        statement = (
            postgresql.insert(document_embedding)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=[
                    document_embedding.c.dataset_version,
                    document_embedding.c.embedding_id,
                ]
            )
            .returning(document_embedding.c.embedding_id)
        )
        async with self._engine.begin() as connection:
            inserted = (await connection.execute(statement)).scalars().all()
            await connection.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
        return len(inserted)

    async def has_exact_embedding(
        self,
        model: EmbeddingModelContract,
        chunk: EmbeddingChunk,
    ) -> bool:
        statement = sa.select(sa.func.count()).select_from(document_embedding).where(
            document_embedding.c.dataset_version == chunk.dataset_version,
            document_embedding.c.embedding_id == embedding_id(model, chunk),
            document_embedding.c.document_id == chunk.document_id,
            document_embedding.c.chunk_id == chunk.chunk_id,
            document_embedding.c.chunk_content_hash == chunk.content_hash,
            document_embedding.c.model_id == model.model_id,
            document_embedding.c.model_version == model.model_version,
            document_embedding.c.dimension == model.dimension,
            sa.func.cdb_admin.vector_dims(document_embedding.c.embedding)
            == model.dimension,
        )
        async with self._engine.connect() as connection:
            return int(await connection.scalar(statement) or 0) == 1

    async def embedded_section_types(
        self,
        dataset: str,
        model: EmbeddingModelContract,
        *,
        entity_id: str,
    ) -> frozenset[str]:
        eligible = self.eligible_statement(dataset).subquery("eligible_chunks")
        statement = (
            sa.select(eligible.c.section_type)
            .select_from(
                eligible.join(
                    document_entity_binding,
                    sa.and_(
                        document_entity_binding.c.dataset_version
                        == eligible.c.dataset_version,
                        document_entity_binding.c.document_id
                        == eligible.c.document_id,
                        document_entity_binding.c.entity_id == entity_id,
                        document_entity_binding.c.binding_role == "subject_product",
                    ),
                ).join(
                    document_embedding,
                    _exact_embedding_match(eligible, model),
                )
            )
            .distinct()
        )
        async with self._engine.connect() as connection:
            values = (await connection.execute(statement)).scalars().all()
        return frozenset(str(value) for value in values)

    async def snapshot_protected_counts(
        self,
        dataset: str,
    ) -> ProtectedCounts:
        async with self._engine.connect() as connection:
            counts = []
            for table in (evidence_record, relation_record, dataset_readiness):
                counts.append(
                    int(
                        await connection.scalar(
                            sa.select(sa.func.count())
                            .select_from(table)
                            .where(table.c.dataset_version == dataset)
                        )
                        or 0
                    )
                )
            active_count = int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(active_dataset)
                    .where(active_dataset.c.dataset_version == dataset)
                )
                or 0
            )
        return ProtectedCounts(*counts, active_count)

    async def reconcile(
        self,
        dataset: str,
        model: EmbeddingModelContract,
    ) -> EmbeddingReconciliation:
        eligible = self.eligible_statement(dataset).subquery("eligible_chunks")
        exact_match = _exact_embedding_match(eligible, model)
        model_rows = sa.and_(
            document_embedding.c.dataset_version == dataset,
            document_embedding.c.model_id == model.model_id,
            document_embedding.c.model_version == model.model_version,
        )
        duplicate_groups = (
            sa.select(
                document_embedding.c.document_id,
                document_embedding.c.chunk_id,
                document_embedding.c.chunk_content_hash,
                (sa.func.count() - 1).label("duplicates"),
            )
            .where(model_rows)
            .group_by(
                document_embedding.c.document_id,
                document_embedding.c.chunk_id,
                document_embedding.c.chunk_content_hash,
            )
            .having(sa.func.count() > 1)
            .subquery("duplicate_groups")
        )
        async with self._engine.connect() as connection:
            eligible_count = int(
                await connection.scalar(sa.select(sa.func.count()).select_from(eligible))
                or 0
            )
            exact_count = int(
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(
                        eligible.join(document_embedding, exact_match)
                    )
                )
                or 0
            )
            missing_count = int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(eligible)
                    .where(
                        ~sa.exists(
                            sa.select(1).select_from(document_embedding).where(
                                exact_match
                            )
                        )
                    )
                )
                or 0
            )
            duplicate_count = int(
                await connection.scalar(
                    sa.select(sa.func.coalesce(sa.func.sum(duplicate_groups.c.duplicates), 0))
                )
                or 0
            )
            stale_count, orphan_count = await self._invalid_counts(
                connection,
                eligible,
                model,
                dataset,
            )
            wrong_dimension_count = int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(document_embedding)
                    .where(
                        model_rows,
                        sa.or_(
                            document_embedding.c.dimension != model.dimension,
                            sa.func.cdb_admin.vector_dims(
                                document_embedding.c.embedding
                            )
                            != model.dimension,
                        ),
                    )
                )
                or 0
            )
            embedding_bytes = int(
                await connection.scalar(
                    sa.select(
                        sa.func.pg_total_relation_size(
                            sa.literal("search.document_embedding")
                        )
                    )
                )
                or 0
            )
        return EmbeddingReconciliation(
            eligible_count=eligible_count,
            exact_count=exact_count,
            missing_count=missing_count,
            duplicate_count=duplicate_count,
            stale_count=stale_count,
            orphan_count=orphan_count,
            wrong_dimension_count=wrong_dimension_count,
            embedding_bytes=embedding_bytes,
        )

    @staticmethod
    async def _invalid_counts(
        connection: AsyncConnection,
        eligible: sa.FromClause,
        model: EmbeddingModelContract,
        dataset: str,
    ) -> tuple[int, int]:
        model_rows = sa.and_(
            document_embedding.c.dataset_version == dataset,
            document_embedding.c.model_id == model.model_id,
            document_embedding.c.model_version == model.model_version,
        )
        same_chunk = sa.and_(
            document_embedding.c.dataset_version == document_chunk.c.dataset_version,
            document_embedding.c.document_id == document_chunk.c.document_id,
            document_embedding.c.chunk_id == document_chunk.c.chunk_id,
        )
        stale_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_embedding.join(document_chunk, same_chunk))
                .where(
                    document_embedding.c.dataset_version == dataset,
                    document_embedding.c.model_id == model.model_id,
                    document_embedding.c.model_version == model.model_version,
                    document_embedding.c.chunk_content_hash
                    != document_chunk.c.content_hash,
                )
            )
            or 0
        )
        exact_eligible = _exact_embedding_match(eligible, model)
        orphan_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(document_embedding)
                .where(
                    model_rows,
                    ~sa.exists(sa.select(1).select_from(eligible).where(exact_eligible)),
                )
            )
            or 0
        )
        return stale_count, orphan_count
