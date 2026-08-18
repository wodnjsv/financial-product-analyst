"""Create the database foundation.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_SCHEMAS = (
    "catalog",
    "observation",
    "relation",
    "document",
    "search",
    "evidence",
    "operations",
)


def upgrade() -> None:
    op.execute("ALTER TABLE public.alembic_version OWNER TO fa_migration")
    op.execute("CREATE EXTENSION pg_trgm WITH SCHEMA public")
    op.execute("CREATE EXTENSION unaccent WITH SCHEMA public")
    op.execute("CREATE EXTENSION pgcrypto WITH SCHEMA public")
    for schema in APPLICATION_SCHEMAS:
        op.execute(f'CREATE SCHEMA "{schema}"')
        op.execute(f'ALTER SCHEMA "{schema}" OWNER TO fa_migration')

    op.create_table(
        "dataset_version",
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("cutoff_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'building'"),
        ),
        sa.Column("manifest_hash", sa.CHAR(64), nullable=False),
        sa.Column("previous_dataset_version", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("validated_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("activated_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "cutoff_date = DATE '2026-07-11'",
            name="cutoff_date",
        ),
        sa.CheckConstraint(
            "status IN ('building','validated','active','retired','failed')",
            name="status",
        ),
        sa.CheckConstraint(
            "manifest_hash ~ '^[0-9a-f]{64}$'",
            name="manifest_hash",
        ),
        sa.ForeignKeyConstraint(
            ["previous_dataset_version"],
            ["operations.dataset_version.dataset_version"],
            name="fk_dataset_version_previous_dataset_version_dataset_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_version",
            name="pk_dataset_version",
        ),
        sa.UniqueConstraint(
            "dataset_version",
            "manifest_hash",
            name="uq_dataset_version_manifest_hash",
        ),
        sa.UniqueConstraint(
            "dataset_version",
            "cutoff_date",
            name="uq_dataset_version_cutoff_date",
        ),
        schema="operations",
    )
    op.create_index(
        "uq_dataset_version_one_active",
        "dataset_version",
        ["status"],
        unique=True,
        schema="operations",
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "dataset_validation_run",
        sa.Column("validation_run_id", sa.Text(), nullable=False),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("dataset_manifest_hash", sa.CHAR(64), nullable=False),
        sa.Column("validator_id", sa.Text(), nullable=False),
        sa.Column("validator_version", sa.Text(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("report_hash", sa.CHAR(64), nullable=False),
        sa.CheckConstraint(
            "status IN ('pass','fail')",
            name="status",
        ),
        sa.CheckConstraint(
            "finished_at >= started_at",
            name="time_order",
        ),
        sa.CheckConstraint(
            "dataset_manifest_hash ~ '^[0-9a-f]{64}$'",
            name="dataset_manifest_hash",
        ),
        sa.CheckConstraint(
            "report_hash ~ '^[0-9a-f]{64}$'",
            name="report_hash",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version", "dataset_manifest_hash"],
            [
                "operations.dataset_version.dataset_version",
                "operations.dataset_version.manifest_hash",
            ],
            name="fk_validation_run_dataset_manifest",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "validation_run_id",
            name="pk_dataset_validation_run",
        ),
        sa.UniqueConstraint(
            "validation_run_id",
            "dataset_version",
            "status",
            name="uq_validation_run_dataset_status",
        ),
        schema="operations",
    )

    op.create_table(
        "dataset_readiness",
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column("validation_run_id", sa.Text(), nullable=False),
        sa.Column(
            "validation_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pass'"),
        ),
        sa.Column("dataset_manifest_hash", sa.CHAR(64), nullable=False),
        sa.Column("component_manifest_hash", sa.CHAR(64), nullable=False),
        sa.Column("validated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("validator_version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "component IN ('postgres','graph','vector','evidence')",
            name="component",
        ),
        sa.CheckConstraint(
            "validation_status = 'pass'",
            name="validation_status",
        ),
        sa.CheckConstraint(
            "dataset_manifest_hash ~ '^[0-9a-f]{64}$'",
            name="dataset_manifest_hash",
        ),
        sa.CheckConstraint(
            "component_manifest_hash ~ '^[0-9a-f]{64}$'",
            name="component_manifest_hash",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version", "dataset_manifest_hash"],
            [
                "operations.dataset_version.dataset_version",
                "operations.dataset_version.manifest_hash",
            ],
            name="fk_readiness_dataset_manifest",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["validation_run_id", "dataset_version", "validation_status"],
            [
                "operations.dataset_validation_run.validation_run_id",
                "operations.dataset_validation_run.dataset_version",
                "operations.dataset_validation_run.status",
            ],
            name="fk_readiness_successful_validation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_version",
            "component",
            name="pk_dataset_readiness",
        ),
        schema="operations",
    )

    op.create_table(
        "active_dataset",
        sa.Column(
            "singleton",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("dataset_version", sa.Text()),
        sa.Column("activated_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "singleton",
            name="singleton",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version"],
            ["operations.dataset_version.dataset_version"],
            name="fk_active_dataset_dataset_version_dataset_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("singleton", name="pk_active_dataset"),
        schema="operations",
    )
    op.execute(
        "INSERT INTO operations.active_dataset (singleton) VALUES (true)"
    )

    op.create_table(
        "request_run",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("request_key", sa.CHAR(64), nullable=False),
        sa.Column("question_id", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("cutoff_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("execution_outcome", sa.Text()),
        sa.Column("verification_status", sa.Text()),
        sa.Column("answer_disposition", sa.Text()),
        sa.Column("http_status", sa.SmallInteger()),
        sa.Column("terminal_failure_code", sa.Text()),
        sa.CheckConstraint(
            "request_key ~ '^[0-9a-f]{64}$'",
            name="request_key",
        ),
        sa.CheckConstraint(
            "created_at < deadline_at "
            "AND deadline_at <= created_at + interval '55 seconds'",
            name="deadline",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name="finished_at",
        ),
        sa.CheckConstraint(
            "execution_outcome IS NULL OR execution_outcome IN "
            "('completed','completed_with_failures','failed')",
            name="execution_outcome",
        ),
        sa.CheckConstraint(
            "verification_status IS NULL "
            "OR verification_status IN ('pass','fail')",
            name="verification_status",
        ),
        sa.CheckConstraint(
            "answer_disposition IS NULL OR answer_disposition IN "
            "('answer','partial','limitation','abstain')",
            name="answer_disposition",
        ),
        sa.CheckConstraint(
            "execution_outcome IS DISTINCT FROM 'failed' "
            "OR answer_disposition IS NULL",
            name="failed_without_disposition",
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="http_status",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version", "cutoff_date"],
            [
                "operations.dataset_version.dataset_version",
                "operations.dataset_version.cutoff_date",
            ],
            name="fk_request_run_dataset_cutoff",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_request_run"),
        schema="operations",
    )

    op.create_table(
        "request_subtask",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("subtask_id", sa.Text(), nullable=False),
        sa.Column("importance", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "importance IN ('critical','required_independent','optional')",
            name="importance",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["operations.request_run.run_id"],
            name="fk_request_subtask_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "subtask_id",
            name="pk_request_subtask",
        ),
        schema="operations",
    )

    op.create_table(
        "failure_event",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text()),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("remaining_budget_ms", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("dependency", sa.Text()),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category IN "
            "('transient','deadline','internal_invariant',"
            "'planner_contract','answer_contract')",
            name="category",
        ),
        sa.CheckConstraint(
            "attempt > 0",
            name="attempt",
        ),
        sa.CheckConstraint(
            "remaining_budget_ms >= 0",
            name="remaining_budget_ms",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="duration_ms",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["operations.request_run.run_id"],
            name="fk_failure_event_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_failure_event"),
        schema="operations",
    )

    for table in (
        "dataset_version",
        "dataset_validation_run",
        "dataset_readiness",
        "active_dataset",
        "request_run",
        "request_subtask",
        "failure_event",
    ):
        op.execute(f'ALTER TABLE operations."{table}" OWNER TO fa_migration')

    op.execute(
        """
        CREATE FUNCTION operations.reject_immutable_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        BEGIN
            RAISE EXCEPTION 'IMMUTABLE_RECORD'
                USING ERRCODE = '55000';
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION operations.validate_dataset_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        BEGIN
            IF OLD.status = NEW.status OR
               (OLD.status = 'building' AND NEW.status IN ('validated','failed')) OR
               (OLD.status = 'validated' AND NEW.status IN ('active','failed')) OR
               (OLD.status = 'active' AND NEW.status = 'retired') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'INVALID_DATASET_TRANSITION'
                USING ERRCODE = '55000';
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION operations.reject_nonbuilding_dataset_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        DECLARE
            target_dataset_version text;
            target_status text;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF OLD.dataset_version IS DISTINCT FROM NEW.dataset_version THEN
                    RAISE EXCEPTION 'DATASET_REASSIGNMENT_FORBIDDEN'
                        USING ERRCODE = '55000';
                END IF;
                target_dataset_version := NEW.dataset_version;
            ELSIF TG_OP = 'DELETE' THEN
                target_dataset_version := OLD.dataset_version;
            ELSE
                target_dataset_version := NEW.dataset_version;
            END IF;
            SELECT dataset.status
              INTO target_status
              FROM operations.dataset_version AS dataset
             WHERE dataset.dataset_version = target_dataset_version
             FOR SHARE;
            IF target_status IS DISTINCT FROM 'building' THEN
                RAISE EXCEPTION 'DATASET_NOT_BUILDING'
                    USING ERRCODE = '55000';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION operations.finish_dataset_validation(
            p_validation_run_id text
        ) RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        DECLARE
            validation_record operations.dataset_validation_run%ROWTYPE;
            dataset_record operations.dataset_version%ROWTYPE;
            next_status text;
        BEGIN
            SELECT validation.*
              INTO validation_record
              FROM operations.dataset_validation_run AS validation
             WHERE validation.validation_run_id = p_validation_run_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'VALIDATION_RUN_NOT_FOUND'
                    USING ERRCODE = 'P0002';
            END IF;

            SELECT dataset.*
              INTO dataset_record
              FROM operations.dataset_version AS dataset
             WHERE dataset.dataset_version = validation_record.dataset_version
             FOR UPDATE;
            IF dataset_record.status IS DISTINCT FROM 'building' THEN
                RAISE EXCEPTION 'DATASET_NOT_BUILDING'
                    USING ERRCODE = '55000';
            END IF;
            IF dataset_record.manifest_hash IS DISTINCT FROM
               validation_record.dataset_manifest_hash THEN
                RAISE EXCEPTION 'DATASET_MANIFEST_MISMATCH'
                    USING ERRCODE = '23514';
            END IF;

            next_status := CASE validation_record.status
                WHEN 'pass' THEN 'validated'
                ELSE 'failed'
            END;
            UPDATE operations.dataset_version
               SET status = next_status,
                   validated_at = validation_record.finished_at
             WHERE dataset_version = validation_record.dataset_version;
            RETURN next_status;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION operations.record_dataset_readiness(
            p_dataset_version text,
            p_component text,
            p_validation_run_id text,
            p_component_manifest_hash character(64),
            p_validated_at timestamp with time zone,
            p_validator_version text
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        DECLARE
            dataset_record operations.dataset_version%ROWTYPE;
            validation_record operations.dataset_validation_run%ROWTYPE;
        BEGIN
            SELECT validation.*
              INTO validation_record
              FROM operations.dataset_validation_run AS validation
             WHERE validation.validation_run_id = p_validation_run_id
               AND validation.dataset_version = p_dataset_version
             FOR SHARE;
            IF NOT FOUND OR validation_record.status IS DISTINCT FROM 'pass' THEN
                RAISE EXCEPTION 'SUCCESSFUL_VALIDATION_REQUIRED'
                    USING ERRCODE = '23503';
            END IF;

            SELECT dataset.*
              INTO dataset_record
              FROM operations.dataset_version AS dataset
             WHERE dataset.dataset_version = p_dataset_version
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'DATASET_NOT_FOUND'
                    USING ERRCODE = 'P0002';
            END IF;
            IF dataset_record.status NOT IN ('building','validated') THEN
                RAISE EXCEPTION 'DATASET_NOT_READY_FOR_COMPONENT'
                    USING ERRCODE = '55000';
            END IF;
            IF validation_record.dataset_manifest_hash IS DISTINCT FROM
               dataset_record.manifest_hash THEN
                RAISE EXCEPTION 'DATASET_MANIFEST_MISMATCH'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO operations.dataset_readiness (
                dataset_version,
                component,
                validation_run_id,
                validation_status,
                dataset_manifest_hash,
                component_manifest_hash,
                validated_at,
                validator_version
            ) VALUES (
                p_dataset_version,
                p_component,
                p_validation_run_id,
                'pass',
                dataset_record.manifest_hash,
                p_component_manifest_hash,
                p_validated_at,
                p_validator_version
            );
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION operations.activate_dataset(
            p_dataset_version text
        ) RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        DECLARE
            prior_active_version text;
            target_status text;
            readiness_count integer;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('operations.activate_dataset', 0)
            );
            SELECT active.dataset_version
              INTO prior_active_version
              FROM operations.active_dataset AS active
             WHERE active.singleton
             FOR UPDATE;

            SELECT dataset.status
              INTO target_status
              FROM operations.dataset_version AS dataset
             WHERE dataset.dataset_version = p_dataset_version
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'DATASET_NOT_FOUND'
                    USING ERRCODE = 'P0002';
            END IF;
            IF target_status IS DISTINCT FROM 'validated' THEN
                RAISE EXCEPTION 'DATASET_NOT_VALIDATED'
                    USING ERRCODE = '55000';
            END IF;

            SELECT count(*)
              INTO readiness_count
              FROM operations.dataset_readiness AS readiness
             WHERE readiness.dataset_version = p_dataset_version
               AND readiness.component IN (
                   'postgres', 'graph', 'vector', 'evidence'
               );
            IF readiness_count <> 4 THEN
                RAISE EXCEPTION 'DATASET_READINESS_INCOMPLETE'
                    USING ERRCODE = '23514';
            END IF;

            IF prior_active_version IS NOT NULL AND
               prior_active_version <> p_dataset_version THEN
                UPDATE operations.dataset_version AS dataset
                   SET status = 'retired'
                 WHERE dataset.dataset_version = prior_active_version
                   AND dataset.status = 'active';
            END IF;
            UPDATE operations.dataset_version
               SET status = 'active',
                   activated_at = pg_catalog.clock_timestamp()
             WHERE dataset_version = p_dataset_version
               AND status = 'validated';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'DATASET_ACTIVATION_CONFLICT'
                    USING ERRCODE = '40001';
            END IF;
            UPDATE operations.active_dataset
               SET dataset_version = p_dataset_version,
                   activated_at = pg_catalog.clock_timestamp()
             WHERE singleton;
            RETURN p_dataset_version;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION operations.start_request_run(
            p_run_id text,
            p_request_key text,
            p_question_id text,
            p_question text,
            p_schema_version text,
            p_dataset_version text,
            p_cutoff_date date,
            p_created_at timestamp with time zone,
            p_deadline_at timestamp with time zone
        ) RETURNS operations.request_run
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        DECLARE
            existing_run operations.request_run%ROWTYPE;
            active_version text;
            active_status text;
            active_cutoff date;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(p_run_id, 0)
            );
            SELECT request.*
              INTO existing_run
              FROM operations.request_run AS request
             WHERE request.run_id = p_run_id;
            IF FOUND THEN
                IF existing_run.request_key = p_request_key AND
                   existing_run.question_id = p_question_id AND
                   existing_run.question = p_question AND
                   existing_run.schema_version = p_schema_version AND
                   existing_run.dataset_version = p_dataset_version AND
                   existing_run.cutoff_date = p_cutoff_date AND
                   existing_run.created_at = p_created_at AND
                   existing_run.deadline_at = p_deadline_at THEN
                    RETURN existing_run;
                END IF;
                RAISE EXCEPTION 'REQUEST_RUN_CONFLICT'
                    USING ERRCODE = 'P0001';
            END IF;

            SELECT active.dataset_version
              INTO active_version
              FROM operations.active_dataset AS active
             WHERE active.singleton
             FOR SHARE;
            SELECT dataset.status, dataset.cutoff_date
              INTO active_status, active_cutoff
              FROM operations.dataset_version AS dataset
             WHERE dataset.dataset_version = p_dataset_version
             FOR SHARE;
            IF active_version IS DISTINCT FROM p_dataset_version OR
               active_status IS DISTINCT FROM 'active' OR
               active_cutoff IS DISTINCT FROM p_cutoff_date THEN
                RAISE EXCEPTION 'ACTIVE_DATASET_MISMATCH'
                    USING ERRCODE = '55000';
            END IF;

            INSERT INTO operations.request_run (
                run_id,
                request_key,
                question_id,
                question,
                schema_version,
                dataset_version,
                cutoff_date,
                created_at,
                deadline_at
            ) VALUES (
                p_run_id,
                p_request_key,
                p_question_id,
                p_question,
                p_schema_version,
                p_dataset_version,
                p_cutoff_date,
                p_created_at,
                p_deadline_at
            ) RETURNING * INTO existing_run;
            RETURN existing_run;
        END
        $function$
        """
    )

    op.execute(
        """
        CREATE TRIGGER validate_dataset_transition
        BEFORE UPDATE OF status ON operations.dataset_version
        FOR EACH ROW
        EXECUTE FUNCTION operations.validate_dataset_transition()
        """
    )
    op.execute(
        """
        CREATE TRIGGER reject_nonbuilding_validation_insert
        BEFORE INSERT ON operations.dataset_validation_run
        FOR EACH ROW
        EXECUTE FUNCTION operations.reject_nonbuilding_dataset_mutation()
        """
    )
    for table in (
        "dataset_validation_run",
        "dataset_readiness",
        "request_subtask",
        "failure_event",
    ):
        op.execute(
            f"""
            CREATE TRIGGER reject_{table}_mutation
            BEFORE UPDATE OR DELETE ON operations.{table}
            FOR EACH ROW
            EXECUTE FUNCTION operations.reject_immutable_mutation()
            """
        )

    function_signatures = (
        "reject_immutable_mutation()",
        "validate_dataset_transition()",
        "reject_nonbuilding_dataset_mutation()",
        "finish_dataset_validation(text)",
        (
            "record_dataset_readiness(text,text,text,character(64),"
            "timestamp with time zone,text)"
        ),
        "activate_dataset(text)",
        (
            "start_request_run(text,text,text,text,text,text,date,"
            "timestamp with time zone,timestamp with time zone)"
        ),
    )
    for signature in function_signatures:
        op.execute(
            f"ALTER FUNCTION operations.{signature} OWNER TO fa_migration"
        )
        op.execute(
            f"REVOKE ALL ON FUNCTION operations.{signature} "
            "FROM PUBLIC, fa_build, fa_runtime"
        )

    for schema in APPLICATION_SCHEMAS:
        op.execute(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC')
        op.execute(
            f'GRANT USAGE ON SCHEMA "{schema}" TO fa_build, fa_runtime'
        )
    op.execute(
        "REVOKE ALL ON ALL TABLES IN SCHEMA operations "
        "FROM PUBLIC, fa_build, fa_runtime"
    )
    op.execute("GRANT SELECT ON operations.dataset_version TO fa_build")
    op.execute(
        "GRANT INSERT (dataset_version, cutoff_date, manifest_hash, "
        "previous_dataset_version, created_at) "
        "ON operations.dataset_version TO fa_build"
    )
    op.execute(
        "GRANT SELECT, INSERT ON operations.dataset_validation_run TO fa_build"
    )
    op.execute(
        "GRANT SELECT ON operations.dataset_readiness, "
        "operations.active_dataset TO fa_build"
    )
    op.execute(
        "GRANT SELECT ON operations.dataset_version, "
        "operations.active_dataset, operations.request_run, "
        "operations.request_subtask, operations.failure_event TO fa_runtime"
    )
    op.execute(
        "GRANT INSERT ON operations.request_subtask, "
        "operations.failure_event TO fa_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "operations.finish_dataset_validation(text) TO fa_build"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "operations.record_dataset_readiness("
        "text,text,text,character(64),timestamp with time zone,text) "
        "TO fa_build"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION operations.activate_dataset(text) "
        "TO fa_build"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION operations.start_request_run("
        "text,text,text,text,text,text,date,timestamp with time zone,"
        "timestamp with time zone) TO fa_runtime"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS validate_dataset_transition "
        "ON operations.dataset_version"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS reject_nonbuilding_validation_insert "
        "ON operations.dataset_validation_run"
    )
    for table in (
        "dataset_validation_run",
        "dataset_readiness",
        "request_subtask",
        "failure_event",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS reject_{table}_mutation "
            f"ON operations.{table}"
        )
    op.execute(
        "DROP FUNCTION IF EXISTS operations.start_request_run("
        "text,text,text,text,text,text,date,timestamp with time zone,"
        "timestamp with time zone)"
    )
    op.execute("DROP FUNCTION IF EXISTS operations.activate_dataset(text)")
    op.execute(
        "DROP FUNCTION IF EXISTS operations.record_dataset_readiness("
        "text,text,text,character(64),timestamp with time zone,text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS operations.finish_dataset_validation(text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "operations.reject_nonbuilding_dataset_mutation()"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS operations.validate_dataset_transition()"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS operations.reject_immutable_mutation()"
    )
    op.drop_table("failure_event", schema="operations")
    op.drop_table("request_subtask", schema="operations")
    op.drop_table("request_run", schema="operations")
    op.drop_table("active_dataset", schema="operations")
    op.drop_table("dataset_readiness", schema="operations")
    op.drop_table("dataset_validation_run", schema="operations")
    op.drop_index(
        "uq_dataset_version_one_active",
        table_name="dataset_version",
        schema="operations",
    )
    op.drop_table("dataset_version", schema="operations")
    for schema in reversed(APPLICATION_SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
