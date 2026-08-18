from __future__ import annotations

import sqlalchemy as sa

from financial_agent.db.metadata import metadata


SHA256_PATTERN = "^[0-9a-f]{64}$"


document_record = sa.Table(
    "document_record",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("document_id", sa.Text, nullable=False),
    sa.Column("source_id", sa.Text, nullable=False),
    sa.Column("document_title", sa.Text, nullable=False),
    sa.Column("document_type", sa.Text, nullable=False),
    sa.Column("object_key", sa.Text, nullable=False),
    sa.Column("content_checksum", sa.CHAR(64), nullable=False),
    sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("available_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_document_record_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "source_id"],
        ["evidence.source_record.dataset_version", "evidence.source_record.source_id"],
        name="fk_document_record_source",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "document_id", name="pk_document_record"
    ),
    sa.CheckConstraint("document_title <> ''", name="document_title"),
    sa.CheckConstraint("document_type <> ''", name="document_type"),
    sa.CheckConstraint("object_key <> ''", name="object_key"),
    sa.CheckConstraint(
        f"content_checksum ~ '{SHA256_PATTERN}'",
        name="content_checksum",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="document",
)
sa.Index(
    "ix_document_record_source",
    document_record.c.dataset_version,
    document_record.c.source_id,
)


document_chunk = sa.Table(
    "document_chunk",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("chunk_id", sa.Text, nullable=False),
    sa.Column("document_id", sa.Text, nullable=False),
    sa.Column("parent_chunk_id", sa.Text),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("page_start", sa.Integer),
    sa.Column("page_end", sa.Integer),
    sa.Column("section", sa.Text),
    sa.Column("sentence_start", sa.Integer),
    sa.Column("sentence_end", sa.Integer),
    sa.Column("exact_text", sa.Text, nullable=False),
    sa.Column("normalized_search_text", sa.Text, nullable=False),
    sa.Column("content_hash", sa.CHAR(64), nullable=False),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_document_chunk_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "document_id"],
        ["document.document_record.dataset_version", "document.document_record.document_id"],
        name="fk_document_chunk_document",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "document_id", "parent_chunk_id"],
        [
            "document.document_chunk.dataset_version",
            "document.document_chunk.document_id",
            "document.document_chunk.chunk_id",
        ],
        name="fk_document_chunk_parent",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "chunk_id", name="pk_document_chunk"
    ),
    sa.UniqueConstraint(
        "dataset_version",
        "document_id",
        "chunk_id",
        name="uq_document_chunk_document_chunk",
    ),
    sa.UniqueConstraint(
        "dataset_version",
        "document_id",
        "chunk_id",
        "content_hash",
        name="uq_document_chunk_exact_content",
    ),
    sa.UniqueConstraint(
        "dataset_version",
        "document_id",
        "ordinal",
        name="uq_document_chunk_ordinal",
    ),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    sa.CheckConstraint(
        "page_start IS NULL OR page_start >= 1",
        name="page_start",
    ),
    sa.CheckConstraint(
        "page_end IS NULL OR (page_start IS NOT NULL AND page_end >= page_start)",
        name="page_range",
    ),
    sa.CheckConstraint(
        "sentence_start IS NULL OR sentence_start >= 0",
        name="sentence_start",
    ),
    sa.CheckConstraint(
        "sentence_end IS NULL OR "
        "(sentence_start IS NOT NULL AND sentence_end >= sentence_start)",
        name="sentence_range",
    ),
    sa.CheckConstraint("exact_text <> ''", name="exact_text"),
    sa.CheckConstraint(
        f"content_hash ~ '{SHA256_PATTERN}'",
        name="content_hash",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="document",
)
sa.Index(
    "ix_document_chunk_normalized_search_text_trgm",
    document_chunk.c.normalized_search_text,
    postgresql_using="gin",
    postgresql_ops={"normalized_search_text": "gin_trgm_ops"},
)
