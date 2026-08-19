# NCP PostgreSQL bootstrap and verification

## Boundary and target

Use NCP Cloud DB for PostgreSQL 15 on a Private Subnet with 4 vCPU, 16 GB RAM, and SSD storage. The final evaluation database must use HA and daily automatic backups retained for 7–14 days. Do not create a Public Domain for the database. The organizer reaches only the public `/answer` API; PostgreSQL port 5432 is allowed only from the approved API-server and data-build-server ACGs.

The observed Stage 02 capability probe selected the `direct_users` layout. Provision three separate NCP console login users named `fa_migration`, `fa_build`, and `fa_runtime`. Do not combine direct users with local NOLOGIN group roles or guess a hybrid layout. Store each credential outside Git, database artifacts, shell history, and command output.

NCP does not expose selectable data-storage encryption on the approved Rocky Linux 8.10 baseline. Do not describe private networking as encryption at rest. Re-evaluate the storage platform if the managed control becomes mandatory or the stored-data classification expands.

## Console work before migrations

1. Create the private PostgreSQL 15 service with the approved sizing, backup, and ACG settings.
2. Install pgvector and `pg_stat_statements` from the NCP console. The first pgvector installation restarts the database service, so schedule it before the evaluation window.
3. Confirm both console-managed extensions are in `cdb_admin`.
4. Provision the three direct users. Grant database `CREATE` only to `fa_migration`.
5. Revoke `public.CREATE` from `PUBLIC`, `fa_build`, and `fa_runtime`; grant `public.USAGE, CREATE` to `fa_migration`; grant only `public.USAGE` to build/runtime.
6. Grant all three users `cdb_admin.USAGE` and `SELECT` on `cdb_admin.pg_stat_statements`. Grant neither application-schema creation nor `cdb_admin.CREATE` to application users.

Every connection must use the search path `"$user", public, cdb_admin`, or schema-qualify the referenced object. Alembic creates only `pg_trgm`, `pgcrypto`, and `unaccent` in `public`. It never creates, moves, upgrades, or drops the two console-managed `cdb_admin` extensions.

## Ordered bootstrap gate

The actual NCP migration and benchmark remain a separately authorized operation. Use injected environment variables; never paste a URL into a tracked command, log, issue, or report.

Run these gates in order:

1. Inject the `fa_migration` URL as `FINANCIAL_AGENT_DATABASE_URL`, then run `python scripts/db_preflight.py --phase pre-migration --database-url-env FINANCIAL_AGENT_DATABASE_URL`.
2. With that same migration identity, run `python -m alembic upgrade head`.
3. Still with `FINANCIAL_AGENT_DATABASE_URL` identifying `fa_migration`, run `python scripts/db_preflight.py --phase post-migration --database-url-env FINANCIAL_AGENT_DATABASE_URL`. Postflight needs the migration identity to inspect Alembic bookkeeping, ownership, ACLs, and the complete object inventory; do not grant those administrative reads to runtime.
4. Separately inject the `fa_runtime` URL as `FINANCIAL_AGENT_NCP_TEST_DATABASE_URL`, then run `.venv/bin/python -m pytest tests/db/test_ncp_preflight.py -m ncp_integration -k authorized_ncp_runtime_can_read_but_not_write_protected_tables -q`. This smoke gate first requires `current_user = 'fa_runtime'`, proves a representative read, and proves direct protected-table DML remains denied inside a savepoint.
5. With the migration URL, run `python scripts/export_database_objects.py --check --database-url-env FINANCIAL_AGENT_DATABASE_URL`.
6. Only on the explicitly authorized non-production target, separately inject `FINANCIAL_AGENT_DATABASE_URL` for `fa_migration`, `FINANCIAL_AGENT_NCP_BUILD_DATABASE_URL` for `fa_build`, and `FINANCIAL_AGENT_NCP_TEST_DATABASE_URL` for `fa_runtime`. Set `RUN_DB_SCALE_TESTS=1` and `RUN_NCP_SCALE_PROVISION=task8-scale-synthetic`, then run `.venv/bin/python -m pytest tests/db/test_query_plans.py -m 'performance and ncp_integration' -k authorized_ncp_synthetic_scale_provisioning -q`. Before the first write, the loader rejects ambiguous libpq routing overrides, opens all three connections, requires their exact live users, and requires their live database/server address/port identities to match. Build writes the building dataset and bulk synthetic rows; migration writes only unavoidable request scaffolding; runtime writes the minimal Evidence/Claim rows and uses the protected artifact append path. A partial run remains `building`, the loader refuses an existing dataset of the same name, and triggers remain enabled.
7. Keep only the `fa_runtime` URL in `FINANCIAL_AGENT_NCP_TEST_DATABASE_URL`, keep `RUN_DB_SCALE_TESTS=1`, and run `.venv/bin/python -m pytest tests/db/test_query_plans.py -m 'performance and ncp_integration' -k authorized_ncp_scale_p95_and_four_read_concurrency -q`. This read-only gate requires the runtime identity before reading anchors, verifies all six query results, runs five warmups plus thirty samples per query, and runs four validated reads for thirty rounds with a five-connection/no-overflow pool.

The post-migration gate verifies PostgreSQL 15, UTC, extension versions and schemas, all seven application schemas, the Alembic head, the fixed `2026-07-11` cutoff, active-dataset consistency, parameterized query/rollback capability, the public-schema boundary, the direct-user permissions, and the reviewed object manifest. A failure returns a stable code without printing the URL.

Review every `SECURITY DEFINER` routine after migration. Its owner must be `fa_migration`; its `search_path` must begin with `pg_catalog`, list the exact allowlist of every referenced application schema (including multiple schemas where required), include `cdb_admin` only for routines that call its extension objects, and end with `pg_temp`. Compare each allowlist with the tracked function configuration in the database-object manifest. PUBLIC execution must be revoked, and only the approved build/runtime identity may have explicit `EXECUTE`.

Never downgrade a shared or NCP database. The base→head→base→head proof is restricted to the named disposable local test database created by `scripts/verify_database_migrations.py`.

## Connection budget

Keep `db_read_concurrency_limit=4`, `pool_size=5`, and `max_overflow=0` until an authorized NCP benchmark record approves a change. Reserve five connections for migration and administration, then calculate the worker ceiling from the live, non-secret setting:

```text
connection_budget = floor(max_connections * 0.8)
permitted_workers = floor((connection_budget - 5) / 5)
require: permitted_workers * 5 + 5 <= connection_budget
```

For example, if `max_connections` is 100, the budget is 80 and the permitted worker count is 15: `15 * 5 + 5 = 80`. Query the actual `max_connections`, compute the number again, and record only the setting, reserve, pool size, and resulting worker count in the private deployment record. Do not record an endpoint, account identifier, database identifier, private address, or credential.

## Final activation backup

After the final dataset passes validation and activation:

1. Re-run the post-migration preflight and database-object manifest check.
2. Take an encrypted-at-rest logical backup in the approved private backup boundary using an injected URL and a timestamped custom-format `pg_dump` file. Do not place the dump in the repository or a public bucket.
3. Record the dump checksum, PostgreSQL major version, Alembic revision, active dataset version, dataset manifest hash, cutoff date, and the tracked `schemas/postgresql/v1/database-objects.json` commit in the private backup record.
4. Perform a restore drill into a separate disposable database before relying on the backup.

No organizer workbook, PDF, raw source file, endpoint, account ID, password, private address, database dump, Parquet file, embedding, cache, or runtime artifact belongs in Git.
