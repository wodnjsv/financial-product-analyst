# ADR-0011: Allow the NCP-Managed Statistics Membership

**Date:** 2026-08-20

**Status:** Accepted

**Related:** [ADR-0010: Use NCP Direct Database Users](ADR-0010-use-ncp-direct-database-users.md), [NCP PostgreSQL Bootstrap and Verification](../../runbooks/ncp-postgresql-bootstrap.md)

## Context

The first post-migration verification of the dedicated NCP PostgreSQL 15 service found one permission difference from the reviewed `direct_users` baseline. NCP made each of `fa_migration`, `fa_build`, and `fa_runtime` a direct member of PostgreSQL's predefined `pg_read_all_stats` role. The observed relationships had no admin option, and the granted role was NOLOGIN, non-superuser, without database creation, role creation, or row-level-security bypass attributes.

The NCP console did not expose a control for removing only this managed relationship. Rejecting it would make the verification gate incompatible with the managed platform even though it does not grant application-table writes, schema creation, database creation, role administration, or membership administration.

## Decision

- In the `direct_users` layout, permit either no role memberships or the exact direct relationships `pg_read_all_stats -> fa_migration`, `pg_read_all_stats -> fa_build`, and `pg_read_all_stats -> fa_runtime`.
- An allowed relationship requires `pg_read_all_stats` to remain NOLOGIN, non-superuser, without `CREATEDB`, `CREATEROLE`, or `BYPASSRLS`, and requires `admin_option = false`.
- Continue rejecting every other direct or transitive membership involving a stable application identity, including `pg_monitor`, `pg_read_all_data`, reverse relationships, application-role overlap, and any relationship with the admin option.
- Preserve the existing database `CREATE`, schema `CREATE`, protected-table DML, object-manifest, and recursive membership checks without weakening them.
- Do not add or remove this role in migrations. The verifier observes and bounds the NCP-managed state; local disposable PostgreSQL may continue to have no such membership.

## Sanitized Evidence

The observed difference consisted of three rows with the same granted role and one stable application user per row. No endpoint, address, database identifier, account identifier, credential, or environment-specific role name was recorded.

## Rejected Alternatives

### Revoke the predefined role with SQL

Rejected because the relationship is part of the observed managed-service user baseline and the NCP console did not offer the equivalent per-user removal control. Bypassing the console-managed state would make provisioning less reproducible.

### Allow every PostgreSQL predefined monitoring role

Rejected because broader roles such as `pg_monitor` include capabilities outside the observed requirement. The exception is deliberately limited to one exact role and safe attributes.

### Ignore all memberships in direct-user mode

Rejected because it would hide privilege expansion, reverse relationships, or collapsing of the separate migration/build/runtime identities.

## Consequences

### Positive

- Post-migration verification can represent the actual NCP managed baseline without disabling least-privilege checks.
- Any privilege expansion beyond the one observed statistics role remains a stable verification failure.
- Local and NCP verification continue to use the same code while allowing the managed relationship to be absent locally.

### Costs and risks

- All three application identities can read PostgreSQL statistics exposed by `pg_read_all_stats`.
- A future NCP change to the role, its attributes, the admin option, or the membership graph will require a fresh review rather than passing automatically.

## Preserved Decisions

- The three direct login identities remain separate and retain their existing application grants.
- Only `fa_migration` may create in the application database and `public` schema.
- Build and runtime remain unable to write protected operations tables directly.
- The database remains private, credentials remain outside Git, and no NCP database is downgraded.
