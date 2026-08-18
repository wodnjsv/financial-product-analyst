# ADR-0010: Use NCP Direct Database Users

**Date:** 2026-08-18

**Status:** Accepted

**Related:** [Stage 02 PostgreSQL Storage Plan](../tasks/2026-08-17-stage-02-postgresql-storage-implementation-plan.md), [NCP Deployment Architecture](../architecture/NCP_DEPLOYMENT_ARCHITECTURE.md)

## Context

Stage 02 deliberately deferred the PostgreSQL permission layout until it could run a transactional capability probe against a dedicated non-production NCP Cloud DB. The 2026-08-18 probe observed that the bootstrap user can create schemas and hardened `SECURITY DEFINER` functions and can grant and revoke object privileges. It cannot create or drop NOLOGIN roles, manage role membership, or transfer schema ownership to a created role.

The sanitized result selected the pre-approved `direct_users` branch. NCP console-created DB USER identifiers are limited to 16 characters, so the earlier provisional `financial_agent_*` names cannot be used as physical identities.

## Decision

- Use three separate NCP console-created login users named `fa_migration`, `fa_build`, and `fa_runtime`.
- Use the same three short names for local NOLOGIN group roles so preflight, migrations, ACL tests, and documentation have one physical-name registry.
- Require all three names to exist before pre-migration preflight. NCP reports them as LOGIN users; the disposable local PostgreSQL harness reports them as NOLOGIN group roles.
- Run schema-changing migrations with `fa_migration`, dataset builds with `fa_build`, and request-time reads/appends with `fa_runtime` after Task 2 installs the exact grants.
- Keep the bootstrap user outside normal migration, build, and runtime operation after provisioning and capability verification.

## Sanitized Capability Evidence

| Capability | Observed |
| --- | --- |
| Create schema | yes |
| Create hardened `SECURITY DEFINER` function | yes |
| Grant and revoke object privileges | yes |
| Create NOLOGIN role | no |
| Drop role | no |
| Manage role membership | no |
| Transfer schema ownership to created role | no |
| Selected layout | `direct_users` |

The probe rolled back its transaction and emitted no endpoint, address, database identifier, account name, or credential.

## Provisioning Observation

The console-created `fa_migration` user initially had LOGIN access but no database `CREATE` privilege. A transactional schema probe failed without leaving an object. The bootstrap identity then granted `CREATE` only on the application database to `fa_migration`; a repeated probe confirmed schema creation, hardened `SECURITY DEFINER`, and grant/revoke while role administration and ownership transfer remained unavailable. This grant is part of migration provisioning and does not extend to `fa_build` or `fa_runtime`.

Before the first NCP Alembic run, the bootstrap identity must revoke `public.CREATE` from `PUBLIC`, `fa_build`, and `fa_runtime`, then grant `fa_migration` `USAGE, CREATE` on `public`, because Alembic owns `public.alembic_version` and revision `0001` installs `pg_trgm`, `unaccent`, and `pgcrypto` there. Build/runtime receive only `public.USAGE`. All three direct users need `USAGE` on the NCP-managed `cdb_admin` schema and `SELECT` on `cdb_admin.pg_stat_statements` so preflight and later diagnostics can verify the console-managed extensions. Preflight verifies this entire role-specific bootstrap boundary before Alembic runs. Application roles receive neither `CREATE` on the database nor `CREATE` on `public` or `cdb_admin`.

## Rejected Alternatives

### Continue with NOLOGIN group roles

Rejected because the observed NCP bootstrap identity cannot create or administer them.

### Keep the long logical names and configure separate physical aliases

Rejected because no public contract depends on those provisional names. Adding a mapping layer before any migration exists would create unnecessary configuration and ACL-test complexity.

### Use one shared NCP login user

Rejected because it would prevent the database from enforcing the approved migration/build/runtime least-privilege boundary.

## Consequences

### Positive

- Physical identities fit the NCP USER_ID limit and can be provisioned through the console.
- Local and NCP permission tests use one stable set of names.
- Migration, build, and runtime access remain independently revocable and auditable.

### Costs and risks

- Three credentials must be stored and rotated independently outside Git.
- NCP direct users cannot inherit a shared group-role policy, so Task 2 must issue and test direct grants for each identity.
- Any future rename requires an explicit superseding ADR and permission migration.

## Preserved Decisions

- Permission DDL is not written until this observed layout is recorded.
- `PUBLIC` privileges remain revoked by default.
- Protected routines use hardened search paths and explicit ACLs.
- PostgreSQL remains private and the financial-data cutoff remains `2026-07-11`.
