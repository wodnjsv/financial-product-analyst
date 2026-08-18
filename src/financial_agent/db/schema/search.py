from __future__ import annotations

from pgvector.sqlalchemy import Vector
import sqlalchemy as sa

from financial_agent.db.metadata import metadata


SHA256_PATTERN = "^[0-9a-f]{64}$"


embedding_model = sa.Table(
    "embedding_model",
    metadata,
    sa.Column("model_id", sa.Text, nullable=False),
    sa.Column("model_version", sa.Text, nullable=False),
    sa.Column("dimension", sa.Integer, nullable=False),
    sa.Column("distance_metric", sa.Text, nullable=False),
    sa.Column("approval_record_id", sa.Text, nullable=False),
    sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("model_hash", sa.CHAR(64), nullable=False),
    sa.PrimaryKeyConstraint(
        "model_id", "model_version", name="pk_embedding_model"
    ),
    sa.CheckConstraint("model_id <> ''", name="model_id"),
    sa.CheckConstraint("model_version <> ''", name="model_version"),
    sa.CheckConstraint("dimension > 0", name="dimension"),
    sa.CheckConstraint(
        "distance_metric IN ('cosine','inner_product','l2')",
        name="distance_metric",
    ),
    sa.CheckConstraint("approval_record_id <> ''", name="approval_record_id"),
    sa.CheckConstraint(
        f"model_hash ~ '{SHA256_PATTERN}'",
        name="model_hash",
    ),
    schema="search",
)


document_embedding = sa.Table(
    "document_embedding",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("embedding_id", sa.Text, nullable=False),
    sa.Column("document_id", sa.Text, nullable=False),
    sa.Column("chunk_id", sa.Text, nullable=False),
    sa.Column("chunk_content_hash", sa.CHAR(64), nullable=False),
    sa.Column("model_id", sa.Text, nullable=False),
    sa.Column("model_version", sa.Text, nullable=False),
    sa.Column("dimension", sa.Integer, nullable=False),
    sa.Column("embedding", Vector(), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_document_embedding_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "document_id", "chunk_id", "chunk_content_hash"],
        [
            "document.document_chunk.dataset_version",
            "document.document_chunk.document_id",
            "document.document_chunk.chunk_id",
            "document.document_chunk.content_hash",
        ],
        name="fk_document_embedding_exact_chunk",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["model_id", "model_version"],
        ["search.embedding_model.model_id", "search.embedding_model.model_version"],
        name="fk_document_embedding_model",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "embedding_id", name="pk_document_embedding"
    ),
    sa.CheckConstraint(
        f"chunk_content_hash ~ '{SHA256_PATTERN}'",
        name="chunk_content_hash",
    ),
    sa.CheckConstraint("dimension > 0", name="dimension"),
    schema="search",
)
sa.Index(
    "ix_document_embedding_chunk",
    document_embedding.c.dataset_version,
    document_embedding.c.document_id,
    document_embedding.c.chunk_id,
)
sa.Index(
    "ix_document_embedding_model",
    document_embedding.c.model_id,
    document_embedding.c.model_version,
)
