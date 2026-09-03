"""document source artifact provenance

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-31 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_source_artifact",
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("source_artifact_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("receipt_id", sa.CHAR(length=14), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("filing_locator", sa.Text(), nullable=False),
        sa.Column("attachment_locator", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("source_checksum", sa.CHAR(length=64), nullable=False),
        sa.Column("text_checksum", sa.CHAR(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("extraction_version", sa.Text(), nullable=False),
        sa.Column("retention_disposition", sa.Text(), nullable=False),
        sa.Column("downloaded_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("persisted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("record_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "receipt_id ~ '^[0-9]{14}$'",
            name=op.f("ck_document_source_artifact_receipt_id"),
        ),
        sa.CheckConstraint(
            "original_filename <> ''",
            name=op.f("ck_document_source_artifact_original_filename"),
        ),
        sa.CheckConstraint(
            "filing_locator ~ '^https://dart[.]fss[.]or[.]kr/' "
            "AND pg_catalog.strpos(filing_locator, "
            "'rcpNo=' || receipt_id) > 0",
            name=op.f("ck_document_source_artifact_filing_locator"),
        ),
        sa.CheckConstraint(
            "attachment_locator ~ '^https://dart[.]fss[.]or[.]kr/' "
            "AND pg_catalog.strpos(attachment_locator, "
            "'rcp_no=' || receipt_id) > 0",
            name=op.f("ck_document_source_artifact_attachment_locator"),
        ),
        sa.CheckConstraint(
            "media_type = 'application/pdf'",
            name=op.f("ck_document_source_artifact_media_type"),
        ),
        sa.CheckConstraint(
            "byte_count > 0",
            name=op.f("ck_document_source_artifact_byte_count"),
        ),
        sa.CheckConstraint(
            "source_checksum ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_source_artifact_source_checksum"),
        ),
        sa.CheckConstraint(
            "text_checksum ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_source_artifact_text_checksum"),
        ),
        sa.CheckConstraint(
            "page_count > 0",
            name=op.f("ck_document_source_artifact_page_count"),
        ),
        sa.CheckConstraint(
            "extraction_version <> ''",
            name=op.f("ck_document_source_artifact_extraction_version"),
        ),
        sa.CheckConstraint(
            "retention_disposition IN ("
            "'pending_delete','delete_authorized',"
            "'metadata_only_deleted','quarantined')",
            name=op.f("ck_document_source_artifact_retention_disposition"),
        ),
        sa.CheckConstraint(
            "persisted_at >= downloaded_at",
            name=op.f("ck_document_source_artifact_persisted_at"),
        ),
        sa.CheckConstraint(
            "verified_at IS NULL OR verified_at >= persisted_at",
            name=op.f("ck_document_source_artifact_verified_at"),
        ),
        sa.CheckConstraint(
            "discarded_at IS NULL OR "
            "(verified_at IS NOT NULL AND discarded_at >= verified_at)",
            name=op.f("ck_document_source_artifact_discarded_at"),
        ),
        sa.CheckConstraint(
            "(retention_disposition = 'pending_delete' "
            "AND verified_at IS NULL AND discarded_at IS NULL) OR "
            "(retention_disposition = 'delete_authorized' "
            "AND verified_at IS NOT NULL AND discarded_at IS NULL) OR "
            "(retention_disposition = 'metadata_only_deleted' "
            "AND verified_at IS NOT NULL AND discarded_at IS NOT NULL) OR "
            "(retention_disposition = 'quarantined' AND discarded_at IS NULL)",
            name=op.f("ck_document_source_artifact_retention_state"),
        ),
        sa.CheckConstraint(
            "record_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_source_artifact_record_hash"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version", "document_id"],
            [
                "document.document_record.dataset_version",
                "document.document_record.document_id",
            ],
            name="fk_document_source_artifact_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version", "source_id"],
            [
                "evidence.source_record.dataset_version",
                "evidence.source_record.source_id",
            ],
            name="fk_document_source_artifact_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_version",
            "document_id",
            name="pk_document_source_artifact",
        ),
        sa.UniqueConstraint(
            "dataset_version",
            "source_artifact_id",
            name="uq_document_source_artifact_identity",
        ),
        schema="document",
    )
    op.execute(
        "ALTER TABLE document.document_source_artifact OWNER TO fa_migration"
    )
    op.execute(
        """
        CREATE TRIGGER reject_document_source_artifact_nonbuilding_mutation
        BEFORE INSERT OR UPDATE OR DELETE
        ON document.document_source_artifact
        FOR EACH ROW
        EXECUTE FUNCTION operations.reject_nonbuilding_dataset_mutation()
        """
    )
    op.execute(
        "REVOKE ALL ON document.document_source_artifact "
        "FROM PUBLIC, fa_build, fa_runtime"
    )
    op.execute(
        "GRANT SELECT ON document.document_source_artifact "
        "TO fa_build, fa_runtime"
    )
    op.execute(
        "GRANT INSERT, UPDATE, DELETE ON document.document_source_artifact "
        "TO fa_build"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "reject_document_source_artifact_nonbuilding_mutation "
        "ON document.document_source_artifact"
    )
    op.drop_table("document_source_artifact", schema="document")
