# ADR-0009: Accept the NCP PostgreSQL Storage-Encryption Boundary

**Date:** 2026-08-18

**Status:** Accepted

**Related:** [NCP Deployment Architecture](../architecture/NCP_DEPLOYMENT_ARCHITECTURE.md), [Stage 02 PostgreSQL Storage Plan](../tasks/2026-08-17-stage-02-postgresql-storage-implementation-plan.md)

## Context

The approved deployment plan originally required selectable data-storage encryption for Cloud DB for PostgreSQL. During Stage 02 provisioning, the current NCP console exposed PostgreSQL 15.17 on Rocky Linux 8.10 but disabled the data-storage-encryption option. NCP's current DB Server guide states that Cloud DB for PostgreSQL no longer provides this option on Rocky Linux 8.10 for clusters created after 2024-10-17.

The project cannot claim that this control is enabled when the managed service does not provide it. Moving to a self-managed database solely to recover that checkbox would add patching, backup, failover, extension, and operational responsibilities before the competition workload justifies them.

## Decision

- Keep Cloud DB for PostgreSQL as the Stage 02 database and record selectable storage encryption as unavailable on the observed NCP baseline.
- Do not emulate or falsely report managed storage encryption in application code, migrations, or deployment evidence.
- Require a Private Subnet, no Public Domain, ACG access limited to approved application/build servers, separate least-privilege database identities, credential storage outside Git and database artifacts, and automatic backups.
- Keep organizer raw files and official source documents in the separately controlled Object Storage boundary; do not copy credentials, private keys, or unrelated personal data into PostgreSQL.
- Re-evaluate the control before final deployment if NCP adds encryption support or if the stored-data classification expands to require encryption at rest. If it becomes mandatory and the managed service still cannot provide it, select a separately approved database platform rather than silently weakening the requirement.

## Rejected Alternatives

### Treat the disabled option as a console error

Rejected because the NCP documentation explicitly describes the feature as unavailable on the current Rocky Linux 8.10 baseline.

### Claim that private networking is equivalent to storage encryption

Rejected because network isolation and encryption at rest mitigate different threats. Private networking is a compensating control, not a replacement claim.

### Add application-level encryption to every financial field

Rejected for the current competition data because it would complicate deterministic filtering, indexing, ranking, and evidence queries without protecting credentials or personal data that the database is prohibited from storing. Field-level encryption requires a separate data-classification and key-management design if later needed.

### Replace Cloud DB with self-managed PostgreSQL now

Rejected because it materially expands operational scope and risk before a requirement or benchmark demonstrates that the managed-service limitation is unacceptable.

## Consequences

### Positive

- Deployment evidence accurately reflects the control NCP actually provides.
- The project keeps managed backups, operations, PostgreSQL 15.17, and console-managed extensions without adding speculative infrastructure.
- Compensating network, identity, and data-handling controls remain explicit and testable.

### Costs and risks

- PostgreSQL data is not covered by a user-selectable NCP storage-encryption control on this baseline.
- A later compliance or data-classification change may require migration to another approved storage platform.
- Operations documentation must not describe the PostgreSQL storage as encrypted at rest unless NCP later supplies verifiable evidence for that claim.

## Preserved Decisions

- PostgreSQL remains private and is never exposed through a Public Domain.
- PostgreSQL 15 remains the tested Stage 02 major version.
- NCP console manages `pgvector` and `pg_stat_statements` in `cdb_admin`.
- Stage 02 still requires the observed permission capability probe before permission DDL.
- The financial-data cutoff remains `2026-07-11`.
