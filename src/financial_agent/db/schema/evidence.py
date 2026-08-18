from __future__ import annotations

import sqlalchemy as sa

from financial_agent.db.metadata import metadata


SHA256_PATTERN = "^[0-9a-f]{64}$"


source_record = sa.Table(
    "source_record",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("source_id", sa.Text, nullable=False),
    sa.Column("publisher", sa.Text, nullable=False),
    sa.Column("publisher_type", sa.Text, nullable=False),
    sa.Column("source_title", sa.Text, nullable=False),
    sa.Column("source_type", sa.Text, nullable=False),
    sa.Column("authority_tier", sa.Text, nullable=False),
    sa.Column("source_locator_root", sa.Text, nullable=False),
    sa.Column("content_checksum", sa.CHAR(64), nullable=False),
    sa.Column("license_or_usage_note", sa.Text),
    sa.Column("eligible_for_claim", sa.Boolean, nullable=False),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_source_record_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "publisher"],
        [
            "catalog.institution.dataset_version",
            "catalog.institution.entity_id",
        ],
        name="fk_source_record_publisher",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "source_id", name="pk_source_record"
    ),
    sa.CheckConstraint("publisher_type <> ''", name="publisher_type"),
    sa.CheckConstraint("source_title <> ''", name="source_title"),
    sa.CheckConstraint("source_type <> ''", name="source_type"),
    sa.CheckConstraint("authority_tier <> ''", name="authority_tier"),
    sa.CheckConstraint("source_locator_root <> ''", name="source_locator_root"),
    sa.CheckConstraint(
        f"content_checksum ~ '{SHA256_PATTERN}'",
        name="content_checksum",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="evidence",
)
