"""document corpus metadata

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunk",
        sa.Column("section_type", sa.Text(), nullable=True),
        schema="document",
    )
    op.add_column(
        "document_chunk",
        sa.Column("section_path", sa.Text(), nullable=True),
        schema="document",
    )
    op.add_column(
        "document_chunk",
        sa.Column("character_start", sa.Integer(), nullable=True),
        schema="document",
    )
    op.add_column(
        "document_chunk",
        sa.Column("character_end", sa.Integer(), nullable=True),
        schema="document",
    )
    op.execute(
        """
        UPDATE document.document_chunk AS chunk
           SET section_type = 'legacy_unclassified',
               section_path = COALESCE(
                   NULLIF(chunk.section, ''), record.document_title
               ),
               character_start = 0,
               character_end = pg_catalog.length(chunk.exact_text)
          FROM document.document_record AS record
         WHERE record.dataset_version = chunk.dataset_version
           AND record.document_id = chunk.document_id
        """
    )
    for column_name in (
        "section_type",
        "section_path",
        "character_start",
        "character_end",
    ):
        op.alter_column(
            "document_chunk",
            column_name,
            existing_type=(
                sa.Integer()
                if column_name in {"character_start", "character_end"}
                else sa.Text()
            ),
            nullable=False,
            schema="document",
        )
    op.create_check_constraint(
        op.f("ck_document_chunk_section_type"),
        "document_chunk",
        "section_type <> ''",
        schema="document",
    )
    op.create_check_constraint(
        op.f("ck_document_chunk_section_path"),
        "document_chunk",
        "section_path <> ''",
        schema="document",
    )
    op.create_check_constraint(
        op.f("ck_document_chunk_character_start"),
        "document_chunk",
        "character_start >= 0",
        schema="document",
    )
    op.create_check_constraint(
        op.f("ck_document_chunk_character_range"),
        "document_chunk",
        "character_end >= character_start",
        schema="document",
    )

    op.create_table(
        "document_profile",
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("document_version", sa.Text(), nullable=False),
        sa.Column("publisher_role", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.Column("original_language", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("amends_document_id", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.Text(), nullable=False),
        sa.Column("cutoff_eligible", sa.Boolean(), nullable=False),
        sa.Column("record_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "btrim(document_version) <> ''",
            name=op.f("ck_document_profile_document_version"),
        ),
        sa.CheckConstraint(
            "publisher_role <> ''",
            name=op.f("ck_document_profile_publisher_role"),
        ),
        sa.CheckConstraint(
            "jurisdiction <> ''",
            name=op.f("ck_document_profile_jurisdiction"),
        ),
        sa.CheckConstraint(
            "original_language <> ''",
            name=op.f("ck_document_profile_original_language"),
        ),
        sa.CheckConstraint(
            "extraction_method <> ''",
            name=op.f("ck_document_profile_extraction_method"),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name=op.f("ck_document_profile_effective_dates"),
        ),
        sa.CheckConstraint(
            "record_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_profile_record_hash"),
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
            ["dataset_version"],
            ["operations.dataset_version.dataset_version"],
            name="fk_document_profile_dataset_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_version", "document_id", name="pk_document_profile"
        ),
        schema="document",
    )
    op.create_table(
        "document_entity_binding",
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("binding_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("binding_role", sa.Text(), nullable=False),
        sa.Column("record_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "binding_role IN "
            "('subject_product','subject_index','subject_policy')",
            name=op.f("ck_document_entity_binding_binding_role"),
        ),
        sa.CheckConstraint(
            "record_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_entity_binding_record_hash"),
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
        sa.ForeignKeyConstraint(
            ["dataset_version"],
            ["operations.dataset_version.dataset_version"],
            name="fk_document_entity_binding_dataset_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_version",
            "binding_id",
            name="pk_document_entity_binding",
        ),
        sa.UniqueConstraint(
            "dataset_version",
            "document_id",
            "entity_id",
            "binding_role",
            name="uq_document_entity_binding_document_entity_role",
        ),
        schema="document",
    )
    op.create_index(
        "ix_document_entity_binding_entity",
        "document_entity_binding",
        ["dataset_version", "entity_id"],
        unique=False,
        schema="document",
    )
    op.create_table(
        "document_coverage",
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("coverage_id", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("required_document_role", sa.Text(), nullable=False),
        sa.Column("coverage_status", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column("scope_evidence_id", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("record_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "required_document_role IN "
            "('product_summary','product_full','index_methodology',"
            "'official_update','policy_base')",
            name=op.f("ck_document_coverage_required_document_role"),
        ),
        sa.CheckConstraint(
            "coverage_status IN ("
            "'indexed','document_not_found','ambiguous_entity_binding',"
            "'after_cutoff_only','version_unknown','unreadable_document',"
            "'publisher_not_approved','section_missing',"
            "'not_applicable_current_scope',"
            "'review_required_chunk_budget')",
            name=op.f("ck_document_coverage_coverage_status"),
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
            name=op.f("ck_document_coverage_state"),
        ),
        sa.CheckConstraint(
            "record_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_coverage_record_hash"),
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
            ["dataset_version", "entity_id"],
            ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
            name="fk_document_coverage_entity",
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
        sa.ForeignKeyConstraint(
            ["dataset_version"],
            ["operations.dataset_version.dataset_version"],
            name="fk_document_coverage_dataset_version",
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
        schema="document",
    )
    op.create_index(
        "ix_document_coverage_status",
        "document_coverage",
        ["dataset_version", "coverage_status"],
        unique=False,
        schema="document",
    )

    for table_name in (
        "document_profile",
        "document_entity_binding",
        "document_coverage",
    ):
        op.execute(
            f"ALTER TABLE document.{table_name} OWNER TO fa_migration"
        )
        op.execute(
            f"""
            CREATE TRIGGER reject_{table_name}_nonbuilding_mutation
            BEFORE INSERT OR UPDATE OR DELETE ON document.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION operations.reject_nonbuilding_dataset_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION document.validate_document_coverage_scope_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, document, evidence, pg_temp
        AS $function$
        DECLARE
            scope_evidence_kind text;
        BEGIN
            IF NEW.coverage_status <> 'indexed' THEN
                SELECT evidence_record.evidence_kind
                  INTO scope_evidence_kind
                  FROM evidence.evidence_record AS evidence_record
                 WHERE evidence_record.dataset_version = NEW.dataset_version
                   AND evidence_record.evidence_id = NEW.scope_evidence_id
                 FOR KEY SHARE;
                IF scope_evidence_kind IS NULL OR
                   scope_evidence_kind NOT IN ('query_scope', 'policy') THEN
                    RAISE EXCEPTION 'DOCUMENT_COVERAGE_SCOPE_EVIDENCE_INVALID'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER validate_document_coverage_scope_evidence
        AFTER INSERT OR UPDATE OF dataset_version, coverage_status,
            scope_evidence_id
        ON document.document_coverage
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION document.validate_document_coverage_scope_evidence()
        """
    )
    op.execute(
        "ALTER FUNCTION document.validate_document_coverage_scope_evidence() "
        "OWNER TO fa_migration"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "document.validate_document_coverage_scope_evidence() "
        "FROM PUBLIC, fa_build, fa_runtime"
    )
    op.execute(
        "REVOKE ALL ON document.document_profile, "
        "document.document_entity_binding, document.document_coverage "
        "FROM PUBLIC, fa_build, fa_runtime"
    )
    op.execute(
        "GRANT SELECT ON document.document_profile, "
        "document.document_entity_binding, document.document_coverage "
        "TO fa_build, fa_runtime"
    )
    op.execute(
        "GRANT INSERT, UPDATE, DELETE ON document.document_profile, "
        "document.document_entity_binding, document.document_coverage "
        "TO fa_build"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS validate_document_coverage_scope_evidence "
        "ON document.document_coverage"
    )
    for table_name in (
        "document_coverage",
        "document_entity_binding",
        "document_profile",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS "
            f"reject_{table_name}_nonbuilding_mutation "
            f"ON document.{table_name}"
        )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "document.validate_document_coverage_scope_evidence()"
    )
    op.drop_index(
        "ix_document_coverage_status",
        table_name="document_coverage",
        schema="document",
    )
    op.drop_table("document_coverage", schema="document")
    op.drop_index(
        "ix_document_entity_binding_entity",
        table_name="document_entity_binding",
        schema="document",
    )
    op.drop_table("document_entity_binding", schema="document")
    op.drop_table("document_profile", schema="document")
    for constraint_name in (
        "ck_document_chunk_character_range",
        "ck_document_chunk_character_start",
        "ck_document_chunk_section_path",
        "ck_document_chunk_section_type",
    ):
        op.drop_constraint(
            op.f(constraint_name),
            "document_chunk",
            schema="document",
            type_="check",
        )
    for column_name in (
        "character_end",
        "character_start",
        "section_path",
        "section_type",
    ):
        op.drop_column("document_chunk", column_name, schema="document")
