"""persist semantic query contract and logical plan artifacts

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ARTIFACT_TYPES = (
    "request_context",
    "intent_resolution",
    "query_plan",
    "query_contract",
    "logical_query_plan",
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
    if artifact_type not in {"query_contract", "logical_query_plan"}
)


def _artifact_type_check(artifact_types: tuple[str, ...]) -> str:
    values = ",".join(f"'{artifact_type}'" for artifact_type in artifact_types)
    return f"artifact_type IN ({values})"


def _replace_derive_request_artifact(*, include_semantic_query: bool) -> None:
    semantic_cases = (
        "                WHEN 'query_contract' "
        "THEN NEW.payload_jsonb ->> 'query_contract_id'\n"
        "                WHEN 'logical_query_plan' "
        "THEN NEW.payload_jsonb ->> 'logical_plan_id'\n"
        if include_semantic_query
        else ""
    )
    semantic_guard = (
        "            IF NEW.artifact_type IN "
        "('query_contract','logical_query_plan')\n"
        "               AND (NEW.contract_object_id IS NULL\n"
        "                    OR NEW.contract_object_id "
        "!~ '[^[:space:]]')\n"
        "            THEN\n"
        "                RAISE EXCEPTION "
        "'SEMANTIC_QUERY_OBJECT_ID_REQUIRED'\n"
        "                    USING ERRCODE = '22023';\n"
        "            END IF;\n\n"
        if include_semantic_query
        else ""
    )
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
                WHEN 'intent_resolution' THEN NEW.payload_jsonb ->> 'resolution_id'
{semantic_cases}                WHEN 'execution_graph' THEN NEW.payload_jsonb ->> 'graph_id'
                WHEN 'tool_result' THEN NEW.payload_jsonb ->> 'task_id'
                WHEN 'evidence_bundle' THEN NEW.payload_jsonb ->> 'bundle_id'
                WHEN 'verification_report'
                    THEN NEW.payload_jsonb ->> 'verification_report_id'
                ELSE NULL
            END;

            IF NEW.artifact_type = 'intent_resolution'
               AND (NEW.contract_object_id IS NULL
                    OR NEW.contract_object_id !~ '[^[:space:]]')
            THEN
                RAISE EXCEPTION 'INTENT_RESOLUTION_ID_REQUIRED'
                    USING ERRCODE = '22023';
            END IF;

{semantic_guard}            IF NEW.schema_version IS NULL OR NEW.request_key IS NULL
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


def _replace_append_request_artifact(*, include_semantic_query: bool) -> None:
    if include_semantic_query:
        old = """candidate_contract_id := CASE p_artifact_type
                    WHEN 'execution_graph'"""
        new = """candidate_contract_id := CASE p_artifact_type
                    WHEN 'query_contract'
                        THEN candidate_jsonb ->> 'query_contract_id'
                    WHEN 'logical_query_plan'
                        THEN candidate_jsonb ->> 'logical_plan_id'
                    WHEN 'execution_graph'"""
    else:
        old = """candidate_contract_id := CASE p_artifact_type
                    WHEN 'query_contract'
                        THEN candidate_jsonb ->> 'query_contract_id'
                    WHEN 'logical_query_plan'
                        THEN candidate_jsonb ->> 'logical_plan_id'
                    WHEN 'execution_graph'"""
        new = """candidate_contract_id := CASE p_artifact_type
                    WHEN 'execution_graph'"""
    old_sql = old.replace("'", "''")
    new_sql = new.replace("'", "''")
    op.execute(
        f"""
        DO $block$
        DECLARE
            function_definition text;
            replaced_definition text;
        BEGIN
            SELECT pg_catalog.pg_get_functiondef(
                'operations.append_request_artifact(text,text,text,text)'::regprocedure
            ) INTO function_definition;
            replaced_definition := pg_catalog.replace(
                function_definition, '{old_sql}', '{new_sql}'
            );
            IF replaced_definition = function_definition THEN
                RAISE EXCEPTION 'APPEND_ARTIFACT_FUNCTION_SHAPE_UNEXPECTED'
                    USING ERRCODE = 'P0001';
            END IF;
            EXECUTE replaced_definition;
        END
        $block$
        """
    )


def upgrade() -> None:
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
        op.f("ck_request_artifact_semantic_query_contract_object_id"),
        "request_artifact",
        "artifact_type NOT IN ('query_contract','logical_query_plan') OR "
        "(contract_object_id IS NOT NULL AND "
        "contract_object_id ~ '[^[:space:]]')",
        schema="operations",
    )
    _replace_derive_request_artifact(include_semantic_query=True)
    _replace_append_request_artifact(include_semantic_query=True)


def downgrade() -> None:
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM operations.request_artifact
                WHERE artifact_type IN ('query_contract','logical_query_plan')
            ) THEN
                RAISE EXCEPTION 'SEMANTIC_QUERY_ARTIFACTS_PREVENT_DOWNGRADE'
                    USING ERRCODE = 'P0001';
            END IF;
        END
        $block$
        """
    )
    _replace_append_request_artifact(include_semantic_query=False)
    _replace_derive_request_artifact(include_semantic_query=False)
    op.drop_constraint(
        op.f("ck_request_artifact_semantic_query_contract_object_id"),
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
