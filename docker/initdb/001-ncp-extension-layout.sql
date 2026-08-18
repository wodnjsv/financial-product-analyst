CREATE SCHEMA IF NOT EXISTS cdb_admin;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA cdb_admin;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA cdb_admin;

DO $roles$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'fa_migration'
    ) THEN
        CREATE ROLE fa_migration NOLOGIN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'fa_build'
    ) THEN
        CREATE ROLE fa_build NOLOGIN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'fa_runtime'
    ) THEN
        CREATE ROLE fa_runtime NOLOGIN;
    END IF;
END
$roles$;

GRANT USAGE ON SCHEMA cdb_admin TO fa_migration, fa_build, fa_runtime;
GRANT SELECT ON cdb_admin.pg_stat_statements TO fa_migration, fa_build, fa_runtime;
REVOKE CREATE ON SCHEMA public FROM PUBLIC, fa_build, fa_runtime;
GRANT USAGE, CREATE ON SCHEMA public TO fa_migration;
GRANT USAGE ON SCHEMA public TO fa_build, fa_runtime;
