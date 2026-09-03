"""persist validated intent resolutions

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ARTIFACT_TYPES = (
    "request_context",
    "intent_resolution",
    "query_plan",
    "execution_graph",
    "tool_result",
    "evidence_bundle",
    "verification_report",
    "answer_plan",
    "released_answer",
)

PREVIOUS_ARTIFACT_TYPES = tuple(
    artifact_type
    for artifact_type in ARTIFACT_TYPES
    if artifact_type != "intent_resolution"
)


def _artifact_type_check(artifact_types: tuple[str, ...]) -> str:
    values = ",".join(f"'{artifact_type}'" for artifact_type in artifact_types)
    return f"artifact_type IN ({values})"


def _replace_derive_request_artifact(*, include_intent_resolution: bool) -> None:
    if include_intent_resolution:
        intent_resolution_case = (
            "                WHEN 'intent_resolution' "
            "THEN NEW.payload_jsonb ->> 'resolution_id'\n"
        )
        intent_resolution_guard = (
            "            IF NEW.artifact_type = 'intent_resolution'\n"
            "               AND (NEW.contract_object_id IS NULL\n"
            "                    OR NEW.contract_object_id "
            "!~ '[^[:space:]]')\n"
            "            THEN\n"
            "                RAISE EXCEPTION "
            "'INTENT_RESOLUTION_ID_REQUIRED'\n"
            "                    USING ERRCODE = '22023';\n"
            "            END IF;\n\n"
        )
    else:
        intent_resolution_case = ""
        intent_resolution_guard = ""
    op.execute(
        rf"""
        CREATE OR REPLACE FUNCTION operations.derive_request_artifact()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        BEGIN
            NEW.payload_jsonb := NEW.canonical_payload::jsonb;
            IF pg_catalog.jsonb_typeof(NEW.payload_jsonb) IS DISTINCT FROM 'object'
            THEN
                RAISE EXCEPTION 'ARTIFACT_PAYLOAD_INVALID'
                    USING ERRCODE = '22023';
            END IF;

            NEW.payload_hash := pg_catalog.encode(
                public.digest(NEW.canonical_payload, 'sha256'), 'hex'
            );
            NEW.schema_version := NEW.payload_jsonb ->> 'schema_version';
            NEW.request_key := NEW.payload_jsonb ->> 'request_key';
            NEW.run_id := NEW.payload_jsonb ->> 'run_id';
            NEW.dataset_version := NEW.payload_jsonb ->> 'dataset_version';
            NEW.cutoff_date := (NEW.payload_jsonb ->> 'cutoff_date')::date;
            NEW.producer := NEW.payload_jsonb ->> 'producer';
            NEW.created_at := (NEW.payload_jsonb ->> 'created_at')::timestamptz;
            NEW.contract_object_id := CASE NEW.artifact_type
{intent_resolution_case}                WHEN 'execution_graph' THEN NEW.payload_jsonb ->> 'graph_id'
                WHEN 'tool_result' THEN NEW.payload_jsonb ->> 'task_id'
                WHEN 'evidence_bundle' THEN NEW.payload_jsonb ->> 'bundle_id'
                WHEN 'verification_report'
                    THEN NEW.payload_jsonb ->> 'verification_report_id'
                ELSE NULL
            END;

{intent_resolution_guard}            IF NEW.schema_version IS NULL OR NEW.request_key IS NULL
               OR NEW.run_id IS NULL OR NEW.dataset_version IS NULL
               OR NEW.cutoff_date IS NULL OR NEW.producer IS NULL
               OR NEW.created_at IS NULL
            THEN
                RAISE EXCEPTION 'ARTIFACT_METADATA_INVALID'
                    USING ERRCODE = '22023';
            END IF;
            RETURN NEW;
        EXCEPTION
            WHEN invalid_text_representation OR datetime_field_overflow
                 OR invalid_datetime_format THEN
                RAISE EXCEPTION 'ARTIFACT_PAYLOAD_INVALID'
                    USING ERRCODE = '22023';
        END
        $function$
        """
    )


def upgrade() -> None:
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM operations.request_artifact
                WHERE artifact_type = 'query_plan'
                  AND (model_id IS NOT NULL OR prompt_version IS NOT NULL)
            ) THEN
                RAISE EXCEPTION
                    'LEGACY_QUERY_PLAN_PROVENANCE_PREVENTS_UPGRADE'
                    USING ERRCODE = 'P0001';
            END IF;
        END
        $block$
        """
    )
    op.add_column(
        "failure_event",
        sa.Column("payload_hash", sa.CHAR(length=64), nullable=True),
        schema="operations",
    )
    op.add_column(
        "failure_event",
        sa.Column("payload_size_bytes", sa.BigInteger(), nullable=True),
        schema="operations",
    )
    op.create_check_constraint(
        op.f("ck_failure_event_payload_hash"),
        "failure_event",
        "payload_hash IS NULL OR payload_hash ~ '^[0-9a-f]{64}$'",
        schema="operations",
    )
    op.create_check_constraint(
        op.f("ck_failure_event_payload_size_bytes"),
        "failure_event",
        "payload_size_bytes IS NULL OR payload_size_bytes >= 0",
        schema="operations",
    )
    op.create_check_constraint(
        op.f("ck_failure_event_payload_audit_pair"),
        "failure_event",
        "(payload_hash IS NULL) = (payload_size_bytes IS NULL)",
        schema="operations",
    )

    op.drop_constraint(
        op.f("ck_request_artifact_model_metadata"),
        "request_artifact",
        schema="operations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_request_artifact_artifact_type"),
        "request_artifact",
        schema="operations",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_request_artifact_artifact_type"),
        "request_artifact",
        _artifact_type_check(ARTIFACT_TYPES),
        schema="operations",
    )
    op.create_check_constraint(
        op.f("ck_request_artifact_model_metadata"),
        "request_artifact",
        "(model_id IS NULL) = (prompt_version IS NULL) AND "
        "(model_id IS NULL OR (model_id ~ '[^[:space:]]' AND "
        "prompt_version ~ '[^[:space:]]')) AND "
        "(artifact_type = 'intent_resolution' AND model_id IS NOT NULL OR "
        "artifact_type = 'answer_plan' OR "
        "artifact_type NOT IN ('intent_resolution','answer_plan') "
        "AND model_id IS NULL)",
        schema="operations",
    )
    op.create_check_constraint(
        op.f("ck_request_artifact_intent_resolution_contract_object_id"),
        "request_artifact",
        "artifact_type <> 'intent_resolution' OR "
        "(contract_object_id IS NOT NULL AND "
        "contract_object_id ~ '[^[:space:]]')",
        schema="operations",
    )
    _replace_derive_request_artifact(include_intent_resolution=True)


def downgrade() -> None:
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM operations.request_artifact
                WHERE artifact_type = 'intent_resolution'
            ) OR EXISTS (
                SELECT 1
                FROM operations.failure_event
                WHERE payload_hash IS NOT NULL OR payload_size_bytes IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'INTENT_RESOLUTION_AUDIT_PREVENTS_DOWNGRADE'
                    USING ERRCODE = 'P0001';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM operations.request_artifact
                WHERE artifact_type = 'query_plan'
                  AND (model_id IS NULL OR prompt_version IS NULL)
            ) THEN
                RAISE EXCEPTION
                    'QUERY_PLAN_PROVENANCE_POLICY_PREVENTS_DOWNGRADE'
                    USING ERRCODE = 'P0001';
            END IF;
        END
        $block$
        """
    )

    _replace_derive_request_artifact(include_intent_resolution=False)
    op.drop_constraint(
        op.f("ck_request_artifact_intent_resolution_contract_object_id"),
        "request_artifact",
        schema="operations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_request_artifact_model_metadata"),
        "request_artifact",
        schema="operations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_request_artifact_artifact_type"),
        "request_artifact",
        schema="operations",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_request_artifact_artifact_type"),
        "request_artifact",
        _artifact_type_check(PREVIOUS_ARTIFACT_TYPES),
        schema="operations",
    )
    op.create_check_constraint(
        op.f("ck_request_artifact_model_metadata"),
        "request_artifact",
        "(model_id IS NULL) = (prompt_version IS NULL) AND "
        "(artifact_type = 'query_plan' AND model_id IS NOT NULL OR "
        "artifact_type = 'answer_plan' OR "
        "artifact_type NOT IN ('query_plan','answer_plan') "
        "AND model_id IS NULL)",
        schema="operations",
    )

    op.drop_constraint(
        op.f("ck_failure_event_payload_audit_pair"),
        "failure_event",
        schema="operations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_failure_event_payload_size_bytes"),
        "failure_event",
        schema="operations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_failure_event_payload_hash"),
        "failure_event",
        schema="operations",
        type_="check",
    )
    op.drop_column("failure_event", "payload_size_bytes", schema="operations")
    op.drop_column("failure_event", "payload_hash", schema="operations")
