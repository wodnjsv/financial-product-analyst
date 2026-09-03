"""add Claim-Gate-authorized verified release cache

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verified_release_cache",
        sa.Column("request_key", sa.CHAR(length=64), nullable=False),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("cutoff_date", sa.Date(), nullable=False),
        sa.Column("verification_artifact_id", sa.UUID(), nullable=False),
        sa.Column("answer_plan_artifact_id", sa.UUID(), nullable=False),
        sa.Column("released_answer_artifact_id", sa.UUID(), nullable=False),
        sa.Column("response_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "request_key ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_verified_release_cache_request_key"),
        ),
        sa.CheckConstraint(
            "response_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_verified_release_cache_response_hash"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "request_key", "dataset_version", "cutoff_date", "schema_version"],
            [
                "operations.request_run.run_id",
                "operations.request_run.request_key",
                "operations.request_run.dataset_version",
                "operations.request_run.cutoff_date",
                "operations.request_run.schema_version",
            ],
            name="fk_verified_release_cache_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_artifact_id", "run_id", "dataset_version"],
            [
                "operations.request_artifact.artifact_record_id",
                "operations.request_artifact.run_id",
                "operations.request_artifact.dataset_version",
            ],
            name="fk_verified_release_cache_verification",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["answer_plan_artifact_id", "run_id", "dataset_version"],
            [
                "operations.request_artifact.artifact_record_id",
                "operations.request_artifact.run_id",
                "operations.request_artifact.dataset_version",
            ],
            name="fk_verified_release_cache_answer_plan",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["released_answer_artifact_id", "run_id", "dataset_version"],
            [
                "operations.request_artifact.artifact_record_id",
                "operations.request_artifact.run_id",
                "operations.request_artifact.dataset_version",
            ],
            name="fk_verified_release_cache_released_answer",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "request_key",
            "dataset_version",
            "schema_version",
            name=op.f("pk_verified_release_cache"),
        ),
        sa.UniqueConstraint(
            "released_answer_artifact_id",
            name=op.f("uq_verified_release_cache_released_answer_artifact_id"),
        ),
        schema="operations",
    )
    op.execute(
        """
        CREATE TRIGGER reject_verified_release_cache_mutation
        BEFORE UPDATE OR DELETE ON operations.verified_release_cache
        FOR EACH ROW
        EXECUTE FUNCTION operations.reject_immutable_mutation()
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION operations.cache_verified_release(
            p_run_id text,
            p_verification_artifact_id uuid,
            p_answer_plan_artifact_id uuid,
            p_released_answer_artifact_id uuid
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        DECLARE
            verification operations.request_artifact%ROWTYPE;
            answer_plan operations.request_artifact%ROWTYPE;
            released operations.request_artifact%ROWTYPE;
            existing operations.verified_release_cache%ROWTYPE;
            releaseable_claims text[];
            planned_claims text[];
            bound_claims text[];
            response_hash character(64);
        BEGIN
            SELECT * INTO verification
              FROM operations.request_artifact
             WHERE run_id = p_run_id
               AND artifact_record_id = p_verification_artifact_id
             FOR SHARE;
            SELECT * INTO answer_plan
              FROM operations.request_artifact
             WHERE run_id = p_run_id
               AND artifact_record_id = p_answer_plan_artifact_id
             FOR SHARE;
            SELECT * INTO released
              FROM operations.request_artifact
             WHERE run_id = p_run_id
               AND artifact_record_id = p_released_answer_artifact_id
             FOR SHARE;
            IF verification.artifact_record_id IS NULL
               OR answer_plan.artifact_record_id IS NULL
               OR released.artifact_record_id IS NULL
            THEN
                RAISE EXCEPTION 'VERIFIED_RELEASE_ARTIFACT_NOT_FOUND'
                    USING ERRCODE = 'P0001';
            END IF;
            IF verification.artifact_type <> 'verification_report'
               OR answer_plan.artifact_type <> 'answer_plan'
               OR released.artifact_type <> 'released_answer'
               OR verification.dataset_version <> answer_plan.dataset_version
               OR verification.dataset_version <> released.dataset_version
               OR verification.request_key <> answer_plan.request_key
               OR verification.request_key <> released.request_key
               OR verification.schema_version <> answer_plan.schema_version
               OR verification.schema_version <> released.schema_version
               OR verification.cutoff_date <> answer_plan.cutoff_date
               OR verification.cutoff_date <> released.cutoff_date
            THEN
                RAISE EXCEPTION 'VERIFIED_RELEASE_SCOPE_MISMATCH'
                    USING ERRCODE = 'P0001';
            END IF;
            IF verification.payload_jsonb ->> 'verification_status' <> 'pass'
               OR answer_plan.payload_jsonb ->> 'verification_report_id'
                  IS DISTINCT FROM verification.contract_object_id
               OR answer_plan.payload_jsonb ->> 'answer_disposition'
                  IS DISTINCT FROM verification.payload_jsonb
                    ->> 'recommended_answer_disposition'
               OR released.payload_jsonb ->> 'answer_disposition'
                  IS DISTINCT FROM answer_plan.payload_jsonb
                    ->> 'answer_disposition'
            THEN
                RAISE EXCEPTION 'VERIFIED_RELEASE_GATE_MISMATCH'
                    USING ERRCODE = 'P0001';
            END IF;

            SELECT ARRAY(
                SELECT value
                  FROM pg_catalog.jsonb_array_elements_text(
                      COALESCE(
                          verification.payload_jsonb -> 'releaseable_claim_ids',
                          '[]'::jsonb
                      )
                  ) AS item(value)
                 ORDER BY value
            ) INTO releaseable_claims;
            SELECT ARRAY(
                SELECT slot.value ->> 'claim_id'
                  FROM pg_catalog.jsonb_array_elements(
                      COALESCE(answer_plan.payload_jsonb -> 'blocks', '[]'::jsonb)
                  ) AS block(value)
                  CROSS JOIN LATERAL pg_catalog.jsonb_array_elements(
                      COALESCE(block.value -> 'claim_slots', '[]'::jsonb)
                  ) AS slot(value)
                 ORDER BY slot.value ->> 'claim_id'
            ) INTO planned_claims;
            SELECT ARRAY(
                SELECT claim.value
                  FROM pg_catalog.jsonb_array_elements(
                      COALESCE(released.payload_jsonb -> 'claim_bindings', '[]'::jsonb)
                  ) AS binding(value)
                  CROSS JOIN LATERAL pg_catalog.jsonb_array_elements_text(
                      COALESCE(binding.value -> 'claim_ids', '[]'::jsonb)
                  ) AS claim(value)
                 ORDER BY claim.value
            ) INTO bound_claims;
            IF releaseable_claims IS DISTINCT FROM planned_claims
               OR releaseable_claims IS DISTINCT FROM bound_claims
               OR pg_catalog.cardinality(planned_claims)
                  <> pg_catalog.cardinality(
                      ARRAY(SELECT DISTINCT value FROM pg_catalog.unnest(planned_claims) value)
                  )
            THEN
                RAISE EXCEPTION 'VERIFIED_RELEASE_CLAIM_SET_MISMATCH'
                    USING ERRCODE = 'P0001';
            END IF;
            response_hash := released.payload_jsonb ->> 'response_hash';
            IF response_hash IS NULL OR response_hash !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'VERIFIED_RELEASE_RESPONSE_HASH_INVALID'
                    USING ERRCODE = 'P0001';
            END IF;

            INSERT INTO operations.verified_release_cache (
                request_key, dataset_version, schema_version, run_id,
                cutoff_date, verification_artifact_id, answer_plan_artifact_id,
                released_answer_artifact_id, response_hash
            ) VALUES (
                released.request_key, released.dataset_version,
                released.schema_version, released.run_id, released.cutoff_date,
                verification.artifact_record_id, answer_plan.artifact_record_id,
                released.artifact_record_id, response_hash
            )
            ON CONFLICT DO NOTHING
            RETURNING * INTO existing;
            IF FOUND THEN
                RETURN existing.released_answer_artifact_id;
            END IF;
            SELECT * INTO existing
              FROM operations.verified_release_cache
             WHERE request_key = released.request_key
               AND dataset_version = released.dataset_version
               AND schema_version = released.schema_version;
            IF existing.verification_artifact_id = verification.artifact_record_id
               AND existing.answer_plan_artifact_id = answer_plan.artifact_record_id
               AND existing.released_answer_artifact_id = released.artifact_record_id
               AND existing.response_hash = response_hash
            THEN
                RETURN existing.released_answer_artifact_id;
            END IF;
            RAISE EXCEPTION 'VERIFIED_RELEASE_CACHE_CONFLICT'
                USING ERRCODE = 'P0001';
        END
        $function$
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION operations.get_cached_release(
            p_request_key text,
            p_dataset_version text,
            p_schema_version text
        ) RETURNS text
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
            SELECT artifact.canonical_payload
              FROM operations.verified_release_cache AS cache
              JOIN operations.request_artifact AS artifact
                ON artifact.artifact_record_id = cache.released_answer_artifact_id
               AND artifact.run_id = cache.run_id
               AND artifact.dataset_version = cache.dataset_version
             WHERE cache.request_key = p_request_key
               AND cache.dataset_version = p_dataset_version
               AND cache.schema_version = p_schema_version
        $function$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION operations.cache_verified_release(text,uuid,uuid,uuid) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION operations.get_cached_release(text,text,text) FROM PUBLIC"
    )
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'fa_runtime'
            ) THEN
                GRANT EXECUTE ON FUNCTION
                    operations.cache_verified_release(text,uuid,uuid,uuid)
                    TO fa_runtime;
                GRANT EXECUTE ON FUNCTION
                    operations.get_cached_release(text,text,text)
                    TO fa_runtime;
                GRANT SELECT ON operations.verified_release_cache TO fa_runtime;
            END IF;
        END
        $block$
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS operations.get_cached_release(text,text,text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS operations.cache_verified_release(text,uuid,uuid,uuid)"
    )
    op.drop_table("verified_release_cache", schema="operations")
