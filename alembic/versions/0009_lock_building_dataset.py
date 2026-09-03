"""protected building-dataset lock

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-31 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION operations.lock_building_dataset(
            p_dataset_version text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, operations, pg_temp
        AS $function$
        DECLARE
            current_status text;
        BEGIN
            IF p_dataset_version IS NULL
               OR pg_catalog.btrim(p_dataset_version) = '' THEN
                RETURN false;
            END IF;

            SELECT dataset.status
              INTO current_status
              FROM operations.dataset_version AS dataset
             WHERE dataset.dataset_version = p_dataset_version
             FOR SHARE;

            RETURN current_status IS NOT DISTINCT FROM 'building';
        END
        $function$
        """
    )
    op.execute(
        "ALTER FUNCTION operations.lock_building_dataset(text) "
        "OWNER TO fa_migration"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION operations.lock_building_dataset(text) "
        "FROM PUBLIC, fa_build, fa_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION operations.lock_building_dataset(text) "
        "TO fa_build"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS operations.lock_building_dataset(text)"
    )
