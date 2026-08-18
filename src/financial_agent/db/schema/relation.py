from __future__ import annotations

import sqlalchemy as sa

from financial_agent.db.metadata import metadata


SHA256_PATTERN = "^[0-9a-f]{64}$"


relation_record = sa.Table(
    "relation_record",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("relation_id", sa.Text, nullable=False),
    sa.Column("subject_id", sa.Text, nullable=False),
    sa.Column("predicate_id", sa.Text, nullable=False),
    sa.Column("object_id", sa.Text, nullable=False),
    sa.Column("valid_from", sa.Date),
    sa.Column("valid_to", sa.Date),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_relation_record_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "subject_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_relation_record_subject",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "object_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_relation_record_object",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "relation_id", name="pk_relation_record"
    ),
    sa.CheckConstraint("predicate_id <> ''", name="predicate_id"),
    sa.CheckConstraint(
        "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
        name="valid_dates",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="relation",
)
sa.Index(
    "ix_relation_record_lookup",
    relation_record.c.dataset_version,
    relation_record.c.predicate_id,
    relation_record.c.subject_id,
    relation_record.c.object_id,
)
