CREATE SCHEMA IF NOT EXISTS cdb_admin;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA cdb_admin;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA cdb_admin;

DO $roles$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'financial_agent_migration'
    ) THEN
        CREATE ROLE financial_agent_migration NOLOGIN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'financial_agent_build'
    ) THEN
        CREATE ROLE financial_agent_build NOLOGIN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'financial_agent_runtime'
    ) THEN
        CREATE ROLE financial_agent_runtime NOLOGIN;
    END IF;
END
$roles$;
