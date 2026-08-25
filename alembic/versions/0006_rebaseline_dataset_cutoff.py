"""rebaseline dataset cutoff

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CURRENT_ACTIVATION_FUNCTION = r"""
CREATE OR REPLACE FUNCTION operations.activate_dataset(
    p_dataset_version text
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations, pg_temp
AS $function$
DECLARE
    prior_active_version text;
    target_status text;
    target_cutoff date;
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

    SELECT dataset.status, dataset.cutoff_date
      INTO target_status, target_cutoff
      FROM operations.dataset_version AS dataset
     WHERE dataset.dataset_version = p_dataset_version
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'DATASET_NOT_FOUND'
            USING ERRCODE = 'P0002';
    END IF;
    IF target_cutoff IS DISTINCT FROM DATE '2026-08-24' THEN
        RAISE EXCEPTION 'LEGACY_DATASET_CANNOT_ACTIVATE'
            USING ERRCODE = '23514';
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


_LEGACY_ACTIVATION_FUNCTION = r"""
CREATE OR REPLACE FUNCTION operations.activate_dataset(
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


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_dataset_version_cutoff_date"),
        "dataset_version",
        schema="operations",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_dataset_version_cutoff_date"),
        "dataset_version",
        "cutoff_date IN (DATE '2026-07-11', DATE '2026-08-24')",
        schema="operations",
    )
    op.execute(_CURRENT_ACTIVATION_FUNCTION)


def downgrade() -> None:
    op.execute(
        r"""
        DO $migration$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM operations.dataset_version
                WHERE cutoff_date = DATE '2026-08-24'
            ) THEN
                RAISE EXCEPTION 'CURRENT_CUTOFF_DATASET_PREVENTS_DOWNGRADE'
                    USING ERRCODE = '23514';
            END IF;
        END
        $migration$
        """
    )
    op.execute(_LEGACY_ACTIVATION_FUNCTION)
    op.drop_constraint(
        op.f("ck_dataset_version_cutoff_date"),
        "dataset_version",
        schema="operations",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_dataset_version_cutoff_date"),
        "dataset_version",
        "cutoff_date = DATE '2026-07-11'",
        schema="operations",
    )
