from __future__ import annotations

import sqlalchemy as sa

from financial_agent.db.metadata import metadata


SHA256_PATTERN = "^[0-9a-f]{64}$"

DOCUMENT_ROLES = (
    "product_summary",
    "product_full",
    "index_methodology",
    "official_update",
    "policy_base",
)

COVERAGE_STATUSES = (
    "indexed",
    "document_not_found",
    "ambiguous_entity_binding",
    "after_cutoff_only",
    "version_unknown",
    "unreadable_document",
    "publisher_not_approved",
    "section_missing",
    "not_applicable_current_scope",
    "review_required_chunk_budget",
)

BINDING_ROLES = ("subject_product", "subject_index", "subject_policy")


def _sql_values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


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


document_profile = sa.Table(
    "document_profile",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("document_id", sa.Text, nullable=False),
    sa.Column("document_version", sa.Text, nullable=False),
    sa.Column("publisher_role", sa.Text, nullable=False),
    sa.Column("jurisdiction", sa.Text, nullable=False),
    sa.Column("original_language", sa.Text, nullable=False),
    sa.Column("effective_from", sa.Date, nullable=False),
    sa.Column("effective_to", sa.Date),
    sa.Column("amends_document_id", sa.Text),
    sa.Column("extraction_method", sa.Text, nullable=False),
    sa.Column("cutoff_eligible", sa.Boolean, nullable=False),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_document_profile_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "document_id"],
        [
            "document.document_record.dataset_version",
            "document.document_record.document_id",
        ],
        name="fk_document_profile_document",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "amends_document_id"],
        [
            "document.document_record.dataset_version",
            "document.document_record.document_id",
        ],
        name="fk_document_profile_amends_document",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "document_id", name="pk_document_profile"
    ),
    sa.CheckConstraint("btrim(document_version) <> ''", name="document_version"),
    sa.CheckConstraint("publisher_role <> ''", name="publisher_role"),
    sa.CheckConstraint("jurisdiction <> ''", name="jurisdiction"),
    sa.CheckConstraint("original_language <> ''", name="original_language"),
    sa.CheckConstraint("extraction_method <> ''", name="extraction_method"),
    sa.CheckConstraint(
        "effective_to IS NULL OR effective_to >= effective_from",
        name="effective_dates",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="document",
)


document_entity_binding = sa.Table(
    "document_entity_binding",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("binding_id", sa.Text, nullable=False),
    sa.Column("document_id", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text, nullable=False),
    sa.Column("binding_role", sa.Text, nullable=False),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_document_entity_binding_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "document_id"],
        [
            "document.document_record.dataset_version",
            "document.document_record.document_id",
        ],
        name="fk_document_entity_binding_document",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "entity_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_document_entity_binding_entity",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "binding_id", name="pk_document_entity_binding"
    ),
    sa.UniqueConstraint(
        "dataset_version",
        "document_id",
        "entity_id",
        "binding_role",
        name="uq_document_entity_binding_document_entity_role",
    ),
    sa.CheckConstraint(
        f"binding_role IN ({_sql_values(BINDING_ROLES)})",
        name="binding_role",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="document",
)
sa.Index(
    "ix_document_entity_binding_entity",
    document_entity_binding.c.dataset_version,
    document_entity_binding.c.entity_id,
)


document_coverage = sa.Table(
    "document_coverage",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("coverage_id", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text, nullable=False),
    sa.Column("required_document_role", sa.Text, nullable=False),
    sa.Column("coverage_status", sa.Text, nullable=False),
    sa.Column("document_id", sa.Text),
    sa.Column("scope_evidence_id", sa.Text),
    sa.Column("reason_code", sa.Text),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_document_coverage_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "entity_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_document_coverage_entity",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "document_id"],
        [
            "document.document_record.dataset_version",
            "document.document_record.document_id",
        ],
        name="fk_document_coverage_document",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "scope_evidence_id"],
        [
            "evidence.evidence_record.dataset_version",
            "evidence.evidence_record.evidence_id",
        ],
        name="fk_document_coverage_scope_evidence",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "coverage_id", name="pk_document_coverage"
    ),
    sa.UniqueConstraint(
        "dataset_version",
        "entity_id",
        "required_document_role",
        name="uq_document_coverage_entity_role",
    ),
    sa.CheckConstraint(
        f"required_document_role IN ({_sql_values(DOCUMENT_ROLES)})",
        name="required_document_role",
    ),
    sa.CheckConstraint(
        f"coverage_status IN ({_sql_values(COVERAGE_STATUSES)})",
        name="coverage_status",
    ),
    sa.CheckConstraint(
        "(coverage_status = 'indexed' "
        "AND document_id IS NOT NULL "
        "AND scope_evidence_id IS NULL "
        "AND reason_code IS NULL) OR "
        "(coverage_status <> 'indexed' "
        "AND document_id IS NULL "
        "AND scope_evidence_id IS NOT NULL "
        "AND reason_code IS NOT NULL "
        "AND reason_code <> '')",
        name="state",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="document",
)
sa.Index(
    "ix_document_coverage_status",
    document_coverage.c.dataset_version,
    document_coverage.c.coverage_status,
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
    sa.Column("section_type", sa.Text, nullable=False),
    sa.Column("section_path", sa.Text, nullable=False),
    sa.Column("character_start", sa.Integer, nullable=False),
    sa.Column("character_end", sa.Integer, nullable=False),
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
        [
            "document.document_record.dataset_version",
            "document.document_record.document_id",
        ],
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
    sa.CheckConstraint("section_type <> ''", name="section_type"),
    sa.CheckConstraint("section_path <> ''", name="section_path"),
    sa.CheckConstraint("character_start >= 0", name="character_start"),
    sa.CheckConstraint(
        "character_end >= character_start",
        name="character_range",
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
