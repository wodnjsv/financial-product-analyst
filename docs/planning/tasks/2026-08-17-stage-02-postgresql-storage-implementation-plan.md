# Stage 02 PostgreSQL Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-08-17 (final review amended 2026-08-18)

**Status:** Stage 02A core persistence implemented and verified; Tasks 1-7 complete, Stage 02B pending

**Goal:** Implement the PostgreSQL 15 physical storage boundary for the seven approved logical schemas, preserve the Stage 01 contract IDs and immutable artifacts without renaming public interfaces, and prove that the migrations and persistence layer run in an NCP-compatible Linux/amd64 environment.

**Architecture:** PostgreSQL is the authoritative store for normalized catalog facts, observations, relation history, document metadata, search projections, evidence lineage, and request artifacts. SQLAlchemy Core defines the application-side table metadata, Alembic owns ordered DDL changes, and Psycopg 3 supplies asynchronous runtime connections. Financial source records and Claim lineage are normalized; tagged values use the frozen Stage 01 JSON shape, while runtime artifacts preserve canonical JSON text and have PostgreSQL derive JSONB plus SHA-256 before insert. Graph and Vector consumers remain projections bound to PostgreSQL IDs and a single `dataset_version`.

**Tech Stack:** Python 3.12, PostgreSQL 15, SQLAlchemy 2.x Core, Alembic 1.x, Psycopg 3.x, pgvector, `pg_trgm`, `unaccent`, `pg_stat_statements`, `pgcrypto`, pytest 8.x, pytest-asyncio, Docker Compose, Linux/amd64.

**Authoritative design references:**

- [Planning Harness](../HARNESS.md)
- [Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md)
- [Stage 01 Closure Hardening Design](../specs/2026-08-18-stage-01-closure-hardening-design.md)
- [Evidence, Verification, and Rendering](../architecture/EVIDENCE_VERIFICATION_AND_RENDERING.md)
- [NCP Deployment Architecture](../architecture/NCP_DEPLOYMENT_ARCHITECTURE.md)
- [Repository Data Policy](../decisions/ADR-0002-repository-data-policy.md)
- [Bounded LLM and Capability Execution](../decisions/ADR-0005-bounded-llm-typed-capability-execution.md)
- [Failure and Disposition Policy](../decisions/ADR-0006-separate-disposition-and-bound-recovery.md)
- [Normalized Evidence Ledger](../decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md)
- [Lossless Tagged Contract Values](../decisions/ADR-0008-lossless-tagged-contract-values.md)
- [Stage 01 Runtime Contracts plan](2026-08-17-stage-01-runtime-contracts-implementation-plan.md)
- [NCP Cloud DB for PostgreSQL Extension 관리](https://guide.ncloud-docs.com/docs/clouddbforpostgresql-postgresqlextension)
- [Alembic autogenerate limits](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

## 1. Entry Gate

Stage 01 is frozen at `8f3152f0b6f55228bc013f387abc4f5b5099b615`. Before Stage 02 implementation, run these commands from a clean `codex/stage-02-storage` branch based on that commit or a later explicitly approved `main`:

```bash
python -m pytest tests/contracts -q
python scripts/export_contract_schemas.py --check
docker build --platform linux/amd64 -f docker/contracts.Dockerfile -t financial-agent-contracts:stage-01 .
docker run --rm --platform linux/amd64 financial-agent-contracts:stage-01
git status --short
```

The freshly exported JSON Schemas and these public symbols are frozen inputs:

```python
from financial_agent.contracts import (
    RequestContext,
    QueryPlan,
    ExecutionGraph,
    ToolResult,
    SourceRecord,
    EvidenceRecord,
    CalculationRecord,
    AtomicClaim,
    ClaimSupport,
    EvidenceBundle,
    CheckResult,
    VerificationReport,
    AnswerPlan,
    ReleasedAnswer,
    EvaluationApiResponse,
)
```

The expected final `ExecutionTask` contract includes `subtask_id` and `produces_bindings`; Stage 02 must preserve them in immutable request-artifact JSON and any indexed execution metadata it chooses to add. Stage 02 may add persistence-only scope columns and association tables. After the amended Stage 01 freeze, it must not rename a contract field, change a contract Enum, relax contract validation, or turn a contract model into an ORM model.

### 1.1 Final review closure matrix

Every blocking review item must have both a database-enforced rule and a failing-before/passing-after test. Narrative or repository-only validation does not close an item.

| Review item | Required proof in this plan | Owning task |
| --- | --- | --- |
| NCP extension and role ownership | console-managed extensions exist and are usable in `cdb_admin`; a disposable NCP capability probe decides whether NOLOGIN group roles or separate console-managed login users implement least privilege | Tasks 1, 2, 8 |
| Release boundary | runtime artifacts may be stored, but Stage 02 creates no Claim-Gate approval record, release cache, or cache API | Task 7 |
| Cutoff/status consistency | each of the four temporal fields conflicts with `eligible` after `2026-07-11`, including direct SQL | Tasks 5, 6 |
| Mixed-tuple losslessness | every tuple item has its own tag and malformed tag/value JSON fails a database CHECK | Tasks 5, 6 |
| Tagged-value ownership | Stage 02 stores and validates the frozen Stage 01 tagged shape without a second Python codec | Tasks 5, 6 |
| Calculation DAG | two-node and three-node cycles fail when deferred constraints are forced or committed | Tasks 5, 6 |
| Entity/version integrity | Evidence and entity-bound Claim subjects/objects use composite dataset foreign keys; request-scoped exceptions are closed | Tasks 2, 3, 5 |
| Auditable activation | four manifest-backed readiness rows reference successful validation runs; permissions and concurrent activation are tested | Tasks 2, 8 |
| Artifact identity and hash | a persistence UUID is separate from nullable contract IDs; canonical text is the retry/restore authority and PostgreSQL derives JSONB plus SHA-256 | Task 7 |
| Concurrent idempotency | two independent connections prove same-ID/same-payload convergence and same-ID/different-payload conflict without global write serialization | Tasks 6, 7 |
| Additional correctness | numeric zero, append-only FailureEvents and registries, DB-object definition drift, no-cascade deletion policy, and representative query plans are proven | Tasks 2, 4, 5, 7, 8 |

### 1.2 Approved delivery split

- **Stage 02A — Core persistence:** Tasks 1–7 implement the dependency lock, local PostgreSQL harness, observed NCP permission-layout selection, migrations, normalized schemas, repositories, tagged-value parity, request-run lifecycle, and immutable runtime artifacts. Stage 02A may finish only after the authorized capability probe plus local PostgreSQL and contract gates pass.
- **Stage 02B — NCP and portability proof:** Task 8 revalidates the selected permission layout and performs the migration cycle, object-manifest drift detection, bounded scale/concurrency tests, Linux/amd64 container verification, and NCP runbook proof.
- Stage 02B hardens the exact Stage 02A schema. It does not add product logic, ingestion, Graph/Fuseki projection, an embedding model, Claim Gate Registry, Renderer, verified-answer cache, or the public API.

## 2. Assumptions and Intended Outcome

### Assumptions

- The active financial-data cutoff remains exactly `2026-07-11`.
- The initial NCP target remains Cloud DB for PostgreSQL 15, 4 vCPU, 16 GB RAM, private subnet, SSD, with HA enabled for final evaluation.
- PostgreSQL is the evidence authority. Fuseki and pgvector rows are derived projections and cannot independently authorize an answer Claim.
- The organizer's four masters total about 145,000 source rows, with later additions for ETF constituents, relations, documents, market values, and exchange rates.
- The evaluation system sends requests sequentially, while one request may execute independent capability reads in parallel.
- Stage 01 contract objects are immutable. Database persistence must preserve that property for evidence, calculations, Claims, supports, and request artifacts.

### Intended outcome

At the end of Stage 02, a developer can:

1. start an empty PostgreSQL 15 instance whose `cdb_admin` extension layout matches NCP and pass extension preflight before migrations;
2. migrate it from zero to the Alembic head and back to zero without manual SQL edits;
3. create and activate a synthetic `2026-07-11-v1` dataset only after four manifest-backed readiness records bind validation runs to that exact dataset;
4. persist and reload Stage 01 Source, Evidence, Calculation, Claim, support, and runtime artifacts without losing IDs, numeric precision, dates, or type information;
5. prove database constraints for version isolation, cutoff/date consistency, recursively tagged values, Calculation DAGs, Claim support XOR, canonical artifact hashing, and immutable audit events;
6. run the same checks in a Linux/amd64 container and against an explicitly configured non-production NCP Cloud DB instance.

## 3. Non-Goals

- Do not read, transform, or load organizer workbooks in this stage.
- Do not collect FRED, KRX, ECOS, fund-manager, index-provider, or other external data.
- Do not activate an external source that has not passed the source-approval process.
- Do not implement Graph RDF generation, SHACL validation, Fuseki loading, SPARQL queries, or Graph traversal.
- Do not select an embedding model or create a dimension-specific ANN index. NCP console provisioning installs pgvector before migrations; this stage creates only the immutable model registry and storage table that consume it.
- Do not implement product filtering, ranking, return normalization, exchange-rate conversion, similarity scoring, or other financial calculations.
- Do not implement the HyperCLOVA X roles, Orchestrator, Verifier, Renderer, FastAPI, or public `GET /answer` endpoint.
- Do not implement the Claim Gate Registry, release authorization record, verified-answer cache, `cache_verified_release()`, or `get_cached_release()`; these remain mandatory in the later Claim Gate/Renderer stage.
- Do not provision NCP VPCs, accounts, passwords, endpoints, HA, backups, or public networking from repository code.
- Do not introduce table partitioning, a message broker, Redis, OpenSearch, a second SQL database, or an ORM entity layer.
- Do not commit organizer data, PDFs, local database volumes, `.env` files, NCP identifiers, credentials, generated embeddings, or runtime artifacts.
- The observed NCP PostgreSQL 15.17/Rocky Linux 8.10 baseline does not offer selectable data-storage encryption. Follow ADR-0009: never claim the control is enabled, keep the database private, restrict ACG and identities, and do not store credentials or unrelated personal data in database artifacts.

## 4. Chosen Physical Design and Rejected Alternatives

### 4.1 SQLAlchemy Core, not ORM state

Use SQLAlchemy Core `Table` definitions and explicit repository functions. Stage 01 Pydantic contracts remain the domain boundary; a second mutable ORM object graph would duplicate validation and blur immutability.

Rejected alternatives:

- **Pydantic models as ORM models:** couples public contracts to persistence-only columns and sessions.
- **Raw SQL only:** makes metadata drift and portable tests harder to inspect.
- **One generic key/value table:** loses foreign keys, typed indexes, and financial-value constraints.

### 4.2 Composite scope for IDs that are not globally unique

Use these identity scopes:

- dataset records: `(dataset_version, record_id)`;
- request calculations and Claims: `(run_id, calculation_id)` and `(run_id, claim_id)`;
- globally unique request execution: `run_id`;
- request grouping: non-unique `request_key`, with each execution attempt identified by globally unique `run_id`.

This preserves Stage 01 IDs without assuming that a request-local `claim_id` is globally unique.

### 4.3 Normalized lineage plus bounded JSONB

Normalize input Evidence, calculation dependencies, exclusions, population filters, qualifiers, and Claim supports into association tables. Use JSONB only for:

- a scalar or tuple value accompanied by an explicit value-type tag; and
- the database-generated query projection of a complete immutable Stage 01 runtime artifact whose canonical UTF-8 JSON text is stored separately and hashed by PostgreSQL.

Do not store Evidence or calculation ID arrays only inside JSONB. The database must enforce their foreign keys.

### 4.4 Preserve after-cutoff records for rejection and enforce their status

The fixed dataset cutoff is enforced on `operations.dataset_version.cutoff_date`. An Evidence row with an `applicable_date`, `published_at`, `available_at`, or `vintage_date` after `2026-07-11` may be stored only with `cutoff_status='after_cutoff'` so the Verifier can explain its rejection. An immediate `BEFORE INSERT OR UPDATE` database trigger derives the required status from all four temporal fields and rejects `eligible` or any other inconsistent label. Such a row must not appear in the safe eligible-Evidence view and must never support a released Claim.

Do not add a blanket `date <= cutoff` CHECK to Evidence. That would erase the distinction between “not collected” and “collected but ineligible because it is future data.”

### 4.5 NCP-managed extensions precede Alembic

NCP console provisioning installs `pgvector` and `pg_stat_statements` into `cdb_admin`; the first pgvector installation restarts the DB service. Alembic must not issue `CREATE EXTENSION` for either one. A pre-migration check verifies their extension names, schemas, and usable objects, and every migration/runtime connection uses a safe search path that includes `cdb_admin` after `"$user"` and `public`.

Local PostgreSQL creates the same `cdb_admin` layout through an initialization script. Alembic may directly create only `pg_trgm`, `pgcrypto`, and `unaccent`, which NCP documents as user-installable extensions.

### 4.6 No premature partitioning or ANN index

At the approved initial scale, composite B-tree, partial, GIN trigram, and foreign-key indexes are sufficient. PostgreSQL partitioning would complicate foreign keys and migrations before measurements justify it. pgvector is installed now, but its ANN index is deferred until the embedding model, vector dimensions, and measured recall/latency are approved.

### 4.7 No cascading application-data deletion

Application-data foreign keys use `RESTRICT` or `NO ACTION`; migrations must not add `ON DELETE CASCADE`. Dataset/audit/lineage/registry/request records are never directly deleted. Catalog, relation, observation, document, and search projection rows are mutable only while their dataset is `building`; an invalid build is marked `failed` and replaced by a new dataset version. Full downgrade is reserved for disposable local databases and an explicitly authorized non-production NCP database.

### 4.8 Request attempts are distinct from request identity

`request_key` groups equivalent organizer requests but is not unique. `run_id` identifies one execution attempt. `operations.start_request_run(...)` locks the active-dataset singleton, verifies the supplied version is the current active dataset, and inserts one immutable attempt. Repeating the same `run_id` with byte-equivalent request fields returns the existing run; reusing it with different fields raises a stable conflict. Different `run_id` values for one `request_key` remain independent, including overlapping evaluator retries.

## 5. Logical-to-Physical Storage Map

| Schema | Physical table | Purpose and key constraints |
| --- | --- | --- |
| `operations` | `dataset_version` | Dataset manifest, fixed cutoff, and lifecycle; PK `dataset_version` |
| `operations` | `dataset_validation_run` | Immutable validation execution, validator version, outcome, report hash, and timing |
| `operations` | `dataset_readiness` | One manifest-backed readiness record per PostgreSQL, Graph, Vector, and Evidence component |
| `operations` | `active_dataset` | Singleton pointer to the one active version; activation requires four valid readiness records |
| `operations` | `request_run` | One execution attempt, original question, deadline, outcome axes, and timing; PK `run_id` |
| `operations` | `request_subtask` | Immutable QueryPlan subtask IDs scoped to one run for request-scoped Claims |
| `operations` | `failure_event` | Append-only retry/failure event with stage, category, attempt, budget, latency, and dependency |
| `operations` | `request_artifact` | Persistence UUID, nullable contract ID, canonical Stage 01 JSON text, database-derived JSONB/hash, artifact type, schema version, and producer/model metadata |
| `operations` | `artifact_evidence_ref` | Artifact-to-Evidence references with stable ordinal and FK |
| `operations` | `artifact_calculation_ref` | Artifact-to-Calculation references with stable ordinal and FK |
| `operations` | `artifact_claim_ref` | Artifact-to-Claim references with stable ordinal and FK |
| `catalog` | `entity` | Versioned product, security, company, institution, index, and theme identities |
| `catalog` | `product` | Product family and common identity fields; one-to-one subtype of entity |
| `catalog` | `security` | Security type and stable security identity fields; one-to-one subtype |
| `catalog` | `institution` | Publisher, issuer, manager, exchange, and regulator types; one-to-one subtype |
| `catalog` | `identifier` | Scheme/value identifiers with validity and primary flag |
| `catalog` | `alias` | Original and normalized names with validity; trigram indexed |
| `relation` | `relation_record` | Versioned subject-predicate-object edge and validity; Graph projection authority |
| `observation` | `metric_definition` | Append-only metric meaning keyed by metric ID and definition version |
| `observation` | `observation_record` | Typed entity- or relation-level value, status, period, unit, currency, and dates |
| `document` | `document_record` | Official document identity, source, object key, checksum, and temporal fields |
| `document` | `document_chunk` | Parent-aware page/section/sentence chunk and exact text hash |
| `search` | `embedding_model` | Append-only approved model/version, dimension, and distance metric |
| `search` | `document_embedding` | Chunk embedding bound to dataset, model, dimensions, and content hash |
| `evidence` | `source_record` | Versioned official source metadata and claim eligibility |
| `evidence` | `evidence_record` | Original Evidence fields, locator columns, cutoff status, and record hash |
| `evidence` | `evidence_observation_origin` | Evidence-to-observation FK without polymorphic foreign keys |
| `evidence` | `evidence_relation_origin` | Evidence-to-relation FK used by Graph projection lineage |
| `evidence` | `evidence_document_origin` | Evidence-to-document-chunk FK used by grounded excerpts |
| `evidence` | `calculation_record` | Formula identity, result, unit, currency, tie-break, and hash |
| `evidence` | `calculation_parameter` | Ordered tagged parameters |
| `evidence` | `calculation_evidence_input` | Ordered input Evidence FKs |
| `evidence` | `calculation_dependency` | Ordered prior Calculation FKs within the same run |
| `evidence` | `calculation_exclusion` | Ordered exclusion Evidence FKs |
| `evidence` | `calculation_population` | Ranking/aggregation population and scope Evidence |
| `evidence` | `calculation_population_filter` | Ordered filter IDs for the population |
| `evidence` | `atomic_claim` | Request-scoped deterministic Claim and tagged value/object XOR |
| `evidence` | `claim_qualifier` | Ordered tagged Claim qualifiers |
| `evidence` | `claim_support` | Claim-to-Evidence or Claim-to-Calculation XOR with role and ordinal |

## 6. Cross-Schema Invariants

1. Every versioned row references `operations.dataset_version`.
2. Every entity, relation, observation, document, source, and Evidence FK includes `dataset_version`; cross-version joins cannot satisfy a foreign key.
3. A relation references subject and object entities from the same dataset version.
4. An observation targets exactly one entity or one relation.
5. A present observation stores exactly one typed value. Missing, placeholder, unavailable, and inapplicable observations store no typed value and preserve a reason code.
6. All financial decimal values use `NUMERIC(38, 12)` or a tagged lossless JSON representation; no database column uses `REAL` or `DOUBLE PRECISION` for money, rates, weights, or returns.
7. Every Calculation has at least one Evidence input or prior Calculation dependency. Ranking requires population and tie-break rows; aggregation requires population; the complete dependency graph must be acyclic.
8. Every Claim has exactly one object or non-null value, except approved qualifier-only `data_limitation` and `policy_boundary` Claims.
9. Every Claim support row points to exactly one Evidence or Calculation. A Calculation support must be from the same run; Evidence must be from the run's dataset.
10. Source, Evidence, Calculation, Claim, support, failure-event, registry-version, and request-artifact rows are append-only. Corrections create a new ID, version, hash, run, or dataset version.
11. Dataset rows may be edited only while `status='building'`. Lifecycle may move forward but cannot return an active or retired dataset to building.
12. `active_dataset` can point only to a dataset whose four readiness rows reference successful validation runs, the parent dataset manifest, component manifests, and the `2026-07-11` cutoff.
13. A request's deadline satisfies `created_at < deadline_at <= created_at + interval '55 seconds'`.
14. Artifact indexed columns must equal the same metadata inside the validated JSON payload before insert; canonical text is the restore/retry authority, and a PostgreSQL trigger derives the JSONB projection and SHA-256.
15. Stored `VerificationReport=pass`, `AnswerPlan`, or `ReleasedAnswer` artifacts do not constitute release authorization. Stage 02 has no release cache or Claim-Gate approval record.
16. `request_key` is non-unique, `run_id` is the attempt identity, and a run captures the active dataset at request start for its full lifetime.
17. Application-data foreign keys never cascade deletes; validated or terminal audit history cannot be removed through a parent delete.
18. No raw model chain-of-thought, credential, or authentication header has a persistence field.

## 7. Planned File Structure

```text
alembic.ini
alembic/
├─ env.py
├─ script.py.mako
└─ versions/
   ├─ 0001_database_foundation.py
   ├─ 0002_catalog_schema.py
   ├─ 0003_fact_document_search_schemas.py
   ├─ 0004_evidence_ledger.py
   └─ 0005_request_artifacts.py
docker/
├─ database-check.Dockerfile
├─ initdb/
│  └─ 001-ncp-extension-layout.sql
└─ postgres.compose.yml
requirements/
└─ storage.lock
docs/
└─ runbooks/
   └─ ncp-postgresql-bootstrap.md
scripts/
├─ db_preflight.py
├─ export_database_objects.py
├─ probe_ncp_db_capabilities.py
└─ verify_database_migrations.py
schemas/
└─ postgresql/
   └─ v1/
      └─ database-objects.json
src/
└─ financial_agent/
   └─ db/
      ├─ __init__.py
      ├─ config.py
      ├─ engine.py
      ├─ metadata.py
      ├─ repositories/
      │  ├─ __init__.py
      │  ├─ artifacts.py
      │  ├─ evidence.py
      │  └─ operations.py
      └─ schema/
         ├─ __init__.py
         ├─ catalog.py
         ├─ document.py
         ├─ evidence.py
         ├─ observation.py
         ├─ operations.py
         ├─ relation.py
         └─ search.py
tests/
├─ db/
│  ├─ __init__.py
│  ├─ conftest.py
│  ├─ test_artifact_repository.py
│  ├─ test_catalog_schema.py
│  ├─ test_database_permissions.py
│  ├─ test_database_config.py
│  ├─ test_storage_lock.py
│  ├─ test_evidence_repository.py
│  ├─ test_evidence_schema.py
│  ├─ test_extension_preflight.py
│  ├─ test_fact_document_search_schema.py
│  ├─ test_foundation_migration.py
│  ├─ test_migration_cycle.py
│  ├─ test_ncp_capability_probe.py
│  ├─ test_ncp_preflight.py
│  ├─ test_operations_repository.py
│  ├─ test_concurrent_idempotency.py
│  ├─ test_tagged_value_parity.py
│  └─ test_query_plans.py
└─ fixtures/
   └─ db/
      ├─ synthetic_dataset.py
      └─ tagged_value_corpus.py
```

---

### Task 1: Add the database toolchain and isolated PostgreSQL test harness

**Files:**

- Modify: `pyproject.toml`
- Create: `requirements/storage.lock`
- Create: `src/financial_agent/db/__init__.py`
- Create: `src/financial_agent/db/config.py`
- Create: `src/financial_agent/db/capabilities.py`
- Create: `src/financial_agent/db/engine.py`
- Create: `src/financial_agent/db/metadata.py`
- Create: `src/financial_agent/db/preflight.py`
- Create: `tests/db/__init__.py`
- Create: `tests/db/conftest.py`
- Create: `tests/db/test_container_config.py`
- Create: `tests/db/test_database_config.py`
- Create: `tests/db/test_db_preflight_cli.py`
- Create: `tests/db/test_engine_metadata.py`
- Create: `tests/db/test_storage_lock.py`
- Create: `tests/db/test_extension_preflight.py`
- Create: `tests/db/test_ncp_capability_probe.py`
- Create: `scripts/db_preflight.py`
- Create: `scripts/probe_ncp_db_capabilities.py`
- Create: `docker/initdb/001-ncp-extension-layout.sql`
- Create: `docker/postgres.compose.yml`

**Interfaces:**

- `DatabaseConfig.from_env(variable="FINANCIAL_AGENT_DATABASE_URL")`
- `create_database_engine(config: DatabaseConfig) -> AsyncEngine`
- `metadata: sqlalchemy.MetaData`
- `python scripts/db_preflight.py --phase pre-migration --database-url-env <ENV_NAME>`
- `python scripts/probe_ncp_db_capabilities.py --database-url-env <ENV_NAME>`
- pytest marker `postgres` for tests that require a disposable PostgreSQL instance
- pytest marker `ncp_integration` for explicitly authorized NCP-only verification

- [x] **Step 1: Write failing configuration tests**

Test that the database URL is mandatory, only PostgreSQL URLs are accepted, the URL is never included in `repr(config)`, pool timeouts are positive, no NCP host/account/password default exists, and the session search path is exactly `"$user", public, cdb_admin`. The initial runtime defaults are `db_read_concurrency_limit=4`, `pool_size=5`, and `max_overflow=0`; configuration rejects a pool smaller than `db_read_concurrency_limit + 1`.

```python
def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINANCIAL_AGENT_DATABASE_URL", raising=False)
    with pytest.raises(DatabaseConfigurationError):
        DatabaseConfig.from_env()


def test_database_config_hides_credentials() -> None:
    config = DatabaseConfig(
        url="postgresql+psycopg://user:secret@db.invalid/financial_agent"
    )
    assert "secret" not in repr(config)
```

- [x] **Step 2: Add the minimum dependencies**

Add compatible bounded ranges rather than unbounded latest versions:

```toml
[project.optional-dependencies]
storage = [
  "SQLAlchemy>=2.0,<3",
  "alembic>=1.13,<2",
  "psycopg[binary]>=3.2,<4",
  "pgvector>=0.3,<1",
  "pytest-asyncio>=0.24,<1",
]
```

Preserve every Stage 01 base and `dev` dependency and every tool setting. Put Stage 02-only runtime and test dependencies in the `storage` optional group so the frozen Stage 01 contracts image continues to install `.[dev]` against `contracts.lock`. Generate `requirements/storage.lock` for CPython 3.12 with exact transitive pins for the base, `dev`, and `storage` dependencies. Leave `requirements/contracts.lock` byte-for-byte unchanged. All Stage 02 database verification installs use `PIP_CONSTRAINT=/app/requirements/storage.lock` and install `.[dev,storage]`; a lock refresh requires the full contract, database, migration-cycle, and Linux/amd64 container gates.

`tests/db/test_storage_lock.py` parses the lock and asserts exact `==` pins, presence of SQLAlchemy/Alembic/Psycopg/pgvector/pytest-asyncio, absence of editable or URL dependencies, and unchanged Stage 01 contract lock bytes relative to the branch baseline.

- [x] **Step 3: Implement connection configuration and naming metadata**

`DatabaseConfig` owns URL, DB read concurrency limit, pool size, max overflow, connect timeout, statement timeout, application name, and the fixed search path. The engine and Alembic environment must set UTC, an application name, and `search_path='"$user", public, cdb_admin'` on every ordinary connection. Use SQLAlchemy naming conventions for primary keys, foreign keys, unique constraints, checks, and indexes so Alembic names are deterministic.

Do not create a global engine at import time. Tests and the future API create and dispose engines explicitly.

- [x] **Step 4: Create the disposable PostgreSQL 15 service**

`docker/postgres.compose.yml` must:

- use a reviewed PostgreSQL 15 pgvector image reference containing both an exact tag and a Linux/amd64 digest; tag-only references fail `test_storage_lock.py`;
- run on `linux/amd64`;
- enable `shared_preload_libraries=pg_stat_statements`;
- mount `docker/initdb/001-ncp-extension-layout.sql` as a read-only initialization script;
- expose only a local development port selected through `${FINANCIAL_AGENT_TEST_DB_PORT:-55432}`;
- use synthetic local-only credentials declared in the compose file;
- include a `pg_isready` health check;
- store data in a named Docker volume that remains ignored by Git.

Do not reuse this password or public port in NCP.

The initialization script must create `cdb_admin`, install `vector` and `pg_stat_statements` into that schema, create the three local NOLOGIN group roles used by permission tests, and grant those roles only the `cdb_admin` usage and `pg_stat_statements` read access required by preflight and diagnostics. It models NCP's console-provisioned layout; Alembic does not own or remove these two extensions. Tests query `pg_extension.extnamespace` and usable objects such as `cdb_admin.vector`/`cdb_admin.pg_stat_statements`, not merely extension names. The NCP runbook provisions equivalent roles through an authorized bootstrap account before the pre-migration check.

- [x] **Step 5: Implement the shared PostgreSQL fixture**

`tests/db/conftest.py` must read `FINANCIAL_AGENT_TEST_DATABASE_URL`, skip only tests marked `ncp_integration` when their explicit URL is absent, and fail ordinary database tests with an actionable start command when local PostgreSQL is unavailable. Ordinary constraint and repository tests run in one connection transaction that rolls back. Commit-time deferred-trigger, two-connection concurrency, permission, and migration-cycle tests receive a disposable per-test or per-module database and perform real commits. No NCP test may create, downgrade, or clean a shared or production database.

`db_preflight.py --phase pre-migration` checks PostgreSQL 15, `server_encoding='UTF8'`, UTC, `vector` and `pg_stat_statements` in `cdb_admin`, the fixed search path, the three stable logical role names in the probe-selected group-role or direct-user layout, and a working `cdb_admin.vector(3)` cast. It must run successfully before any Alembic revision. Missing console-managed extensions return `MISSING_NCP_EXTENSION`; a wrong schema returns `NCP_EXTENSION_SCHEMA_MISMATCH`; a restart/incomplete activation returns `NCP_EXTENSION_UNUSABLE`; a missing role returns `MISSING_DB_ROLE`; a role shape inconsistent with the selected layout returns `DB_ROLE_LAYOUT_MISMATCH`.

- [x] **Step 6: Probe the real NCP permission capability before permission DDL**

With explicit user authorization, run only against a disposable or dedicated non-production NCP Cloud DB. The probe creates uniquely prefixed temporary objects, tests creation and deletion of a NOLOGIN role, schema ownership transfer, `SECURITY DEFINER`, `GRANT`/`REVOKE`, and role membership, then removes every temporary object in a `finally` path. It prints capability booleans and stable error codes but never the URL, username, server address, or database identifier.

If all role capabilities pass, Task 2 uses the three NOLOGIN group roles. If NCP forbids NOLOGIN role creation or membership, create separate migration/build/runtime login users through the NCP console and apply direct least-privilege grants to those observed identities. Do not guess the permission layout and do not proceed to Task 2 until one branch has a saved, sanitized probe result in the local verification log.

The 2026-08-18 non-production probe selected `direct_users`: schema creation, hardened `SECURITY DEFINER`, and grant/revoke succeeded; NOLOGIN role creation/deletion, membership management, and ownership transfer did not. ADR-0010 records this sanitized result and fixes the three NCP-compatible physical names as `fa_migration`, `fa_build`, and `fa_runtime`.

Observed provisioning state on 2026-08-18: a non-production PostgreSQL 15.17 Standalone service was created in a Private Subnet at the approved 4 vCPU/16 GB size, and the NCP console installed `pgvector` and `pg_stat_statements` for the test database. The database ACG permits port 5432 only from the application server ACG in addition to NCP-managed internal rules, and automatic backup retention is seven days. The three direct users were provisioned and preflight returned `permission_layout=direct_users`. The initial migration-user probe showed no database `CREATE` privilege; the bootstrap identity granted only `CREATE` on the application database to `fa_migration`, after which schema creation, hardened `SECURITY DEFINER`, and grant/revoke all passed while role administration and ownership transfer remained unavailable. Before the first NCP migration, bootstrap must additionally apply the documented role-specific `public` grants/revocations and read-only `cdb_admin` grants, then preflight must run while connected as `fa_migration`. No endpoint, address, account name, resource ID, or credential is recorded.

- [x] **Step 7: Run the focused tests**

```bash
python -m pytest tests/db/test_database_config.py -v
python -m pytest tests/db/test_storage_lock.py -v
docker compose -f docker/postgres.compose.yml config
docker compose -f docker/postgres.compose.yml up -d --wait postgres
FINANCIAL_AGENT_TEST_DATABASE_URL="postgresql+psycopg://financial_agent_test:financial_agent_test@localhost:55432/financial_agent_test" \
  python scripts/db_preflight.py --phase pre-migration --database-url-env FINANCIAL_AGENT_TEST_DATABASE_URL
FINANCIAL_AGENT_TEST_DATABASE_URL="postgresql+psycopg://financial_agent_test:financial_agent_test@localhost:55432/financial_agent_test" \
  python -m pytest tests/db/test_extension_preflight.py -v
```

Expected: configuration tests pass, Compose resolves without a secret-bearing host path, and the local database exposes the same `cdb_admin` extension layout required on NCP.

- [x] **Step 8: Commit the database harness**

```bash
git add pyproject.toml requirements/storage.lock docker/initdb/001-ncp-extension-layout.sql docker/postgres.compose.yml scripts/db_preflight.py scripts/probe_ncp_db_capabilities.py src/financial_agent/db tests/db/__init__.py tests/db/conftest.py tests/db/test_container_config.py tests/db/test_database_config.py tests/db/test_db_preflight_cli.py tests/db/test_engine_metadata.py tests/db/test_storage_lock.py tests/db/test_extension_preflight.py tests/db/test_ncp_capability_probe.py
git diff --cached --check
git diff --cached
git commit -m "build: add postgres test harness"
```

### Task 2: Create user-managed extensions, audit-ready dataset activation, and database permissions

**Files:**

- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_database_foundation.py`
- Create: `src/financial_agent/db/schema/__init__.py`
- Create: `src/financial_agent/db/schema/operations.py`
- Create: `tests/db/test_foundation_migration.py`
- Create: `tests/db/test_database_permissions.py`

**Interfaces:**

- Alembic head begins at revision `0001`.
- `operations.dataset_version`
- `operations.dataset_validation_run`
- `operations.dataset_readiness`
- `operations.active_dataset`
- `operations.request_run`
- `operations.request_subtask`
- `operations.failure_event`
- database function `operations.record_dataset_readiness(...)`
- database function `operations.finish_dataset_validation(...)`
- database function `operations.activate_dataset(text)`
- database function `operations.start_request_run(...)`
- database trigger function `operations.reject_nonbuilding_dataset_mutation()`

- [x] **Step 1: Write failing foundation tests**

Cover all of these cases:

```python
REQUIRED_SCHEMAS = {
    "catalog", "observation", "relation", "document",
    "search", "evidence", "operations",
}

NCP_MANAGED_EXTENSIONS = {
    "vector": "cdb_admin",
    "pg_stat_statements": "cdb_admin",
}
MIGRATION_MANAGED_EXTENSIONS = {
    "pg_trgm": "public",
    "unaccent": "public",
    "pgcrypto": "public",
}
```

- PostgreSQL major version is exactly 15 in the local compatibility suite.
- pre-migration checks fail before Alembic if either NCP-managed extension is absent, unusable, or installed outside `cdb_admin`.
- migration `0001` leaves the two NCP-managed extensions untouched and creates only the three user-installable extensions.
- every required schema and extension exists in its exact expected namespace after `alembic upgrade head`.
- `cutoff_date != date(2026, 7, 11)` is rejected.
- a malformed `manifest_hash` is rejected.
- a readiness row is rejected unless it references a successful validation run for the same dataset and its dataset-manifest hash matches the parent row.
- direct insert/update/delete on readiness rows is rejected for build and runtime roles.
- direct dataset lifecycle updates are rejected; `finish_dataset_validation` alone maps an immutable validation run's pass/fail outcome to `validated`/`failed`.
- activation fails unless exactly one ready record exists for each of `postgres`, `graph`, `vector`, and `evidence`.
- activation succeeds transactionally when all four readiness records and manifests are valid.
- activating a second version replaces the singleton pointer and retires the prior active version.
- two concurrent first activations serialize on the seeded singleton row and leave exactly one active dataset plus one matching pointer.
- an active or retired version cannot transition back to building.
- a request deadline equal to 55 seconds after creation is accepted, while 56 seconds is rejected.
- a request deadline before or equal to creation is rejected by the ordering constraint.
- runtime direct INSERT into `request_run` is denied; `start_request_run` accepts only the current active dataset and captures it for the run lifetime.
- two calls with the same `run_id` and identical request fields return the same row; the same `run_id` with any different field raises `REQUEST_RUN_CONFLICT`; the same `request_key` with distinct run IDs creates independent attempts.
- execution outcome, verification status, and answer disposition remain separate nullable columns.
- a failed execution cannot store an answer disposition, and no raw chain-of-thought column exists.
- multiple `FailureEvent` rows preserve stage, category, retryability, attempt, remaining budget, duration, and dependency for one run.
- a runtime role cannot alter schemas, datasets, readiness, registry rows, or prior audit rows.

- [x] **Step 2: Define the dataset tables**

`operations.dataset_version` uses these columns:

| Column | Type and rule |
| --- | --- |
| `dataset_version` | `TEXT PRIMARY KEY` |
| `cutoff_date` | `DATE NOT NULL CHECK = DATE '2026-07-11'` |
| `status` | `TEXT CHECK IN ('building','validated','active','retired','failed')` |
| `manifest_hash` | `CHAR(64)` lowercase SHA-256 check |
| `previous_dataset_version` | nullable self-FK |
| `created_at` | `TIMESTAMPTZ NOT NULL` |
| `validated_at` | nullable `TIMESTAMPTZ` |
| `activated_at` | nullable `TIMESTAMPTZ` |

Add a unique `(dataset_version, manifest_hash)` key. `dataset_validation_run` stores `validation_run_id`, dataset version, validator ID/version, `started_at`, `finished_at`, `status=pass|fail`, and a report SHA-256. It is immutable after insertion.

`dataset_readiness` stores `(dataset_version, component)` as its primary key plus `validation_run_id`, `dataset_manifest_hash`, `component_manifest_hash`, `validated_at`, and validator version. A composite FK binds the dataset manifest; another FK binds the successful validation run. Only `operations.record_dataset_readiness(...)`, owned by the migration role with a fixed safe search path, may insert the one immutable readiness record for a component while the dataset is `building` or `validated`. A conflicting revalidation creates a new dataset version rather than replacing audit history.

`operations.finish_dataset_validation(...)` locks a building dataset and one immutable validation run, checks its dataset and manifest, and advances to `validated` for pass or `failed` for fail. Build receives EXECUTE on this function but no direct dataset-status update.

`operations.active_dataset` is created with one seeded boolean singleton row whose dataset FK is initially null. The activation function takes a transaction-scoped advisory lock, locks the singleton and both dataset rows, validates all four readiness/manifests, retires the old version, activates the new version, and updates the pointer in one transaction. `reject_nonbuilding_dataset_mutation()` is a reusable trigger applied by later migrations to versioned catalog, fact, relation, document, and search rows.

Add a partial unique index on `dataset_version.status='active'` so direct SQL cannot create two active versions. Application and data-build code may activate a version only through `operations.activate_dataset(text)`.

`operations.request_run` is also created in revision `0001` because request-scoped Calculations and Claims in revision `0004` must reference it. It stores `run_id`, non-unique `request_key`, `question_id`, the original `question`, `schema_version`, `dataset_version`, `cutoff_date`, `created_at`, `deadline_at`, `finished_at`, the three separate outcome axes, HTTP status, and stable failure code. A composite FK to a unique `(dataset_version, cutoff_date)` pair guarantees that the request cutoff matches the dataset. Its deadline CHECK is `created_at < deadline_at AND deadline_at <= created_at + interval '55 seconds'`. It has no field for raw Chain-of-Thought.

Only `operations.start_request_run(...)` may insert runtime requests. The `SECURITY DEFINER` function locks the active-dataset singleton, requires the supplied dataset to be both the pointer target and `status='active'`, compares the supplied cutoff, and inserts the attempt. A repeated identical `run_id` returns the existing row after exact field comparison; a conflicting reuse raises `REQUEST_RUN_CONFLICT`. Later active-dataset changes never alter an in-flight run's stored version.

`operations.request_subtask` stores `(run_id, subtask_id)` and the subtask importance copied deterministically from the validated QueryPlan artifact. It is append-only. Request-scoped Claims can reference only one of these registered subtasks.

`operations.failure_event` is append-only and stores `event_id`, `run_id`, nullable task ID, `stage`, stable `code`, `category`, `retryable`, positive `attempt`, nonnegative `remaining_budget_ms`, nonnegative `duration_ms`, nullable dependency, and UTC `occurred_at`. `request_run.terminal_failure_code` is only a final summary and never replaces these events.

Dataset transitions are exactly `building -> validated|failed`, `validated -> active|failed`, and `active -> retired`; `retired` and `failed` are terminal. The activation function is the only path from validated to active.

- [x] **Step 3: Implement the migration environment**

Configure Alembic to import the shared metadata, compare server defaults and types, include only the seven named application schemas plus public `alembic_version`, and reject an empty or non-PostgreSQL URL. Its `include_name` filter explicitly excludes `cdb_admin`, so autogenerate cannot propose changes to NCP-managed objects. It first calls pre-migration preflight. Migration `0001` creates only `pg_trgm`, `unaccent`, and `pgcrypto`, then schemas, tables, constraints, immutable-event triggers, transition functions, and grants. It must never create, move, alter, or drop `vector`, `pg_stat_statements`, or `cdb_admin`.

Use the three stable names `fa_migration`, `fa_build`, and `fa_runtime`, provisioned as separate NCP console-created login users before migration and checked by preflight. In the `direct_users` layout, preflight rejects every migration connection whose current identity is not exactly `fa_migration`. The disposable local harness uses NOLOGIN roles with the same names and also tests a fresh base-to-`0001` migration through temporary direct logins. The bootstrap identity, not Alembic, revokes default `PUBLIC` creation access and denies build/runtime `CREATE` in `public`; preflight proves this before migration. Migration owns application DDL; build can write only building-version data and execute readiness/activation functions; runtime can read active data and append request-scoped records only through approved repositories/functions. Neither build nor runtime receives direct `INSERT` on `request_run`/`request_artifact`, or direct `UPDATE`/`DELETE` on readiness, active dataset, Evidence, Claim, audit, or artifact tables.

Every `SECURITY DEFINER` routine is owned by `fa_migration`, revokes `PUBLIC EXECUTE`, grants only the required build/runtime `EXECUTE`, schema-qualifies referenced objects, and sets a function-specific search path containing only `pg_catalog`, required migration-owned schemas, and `pg_temp` last. Dynamic SQL is forbidden unless the routine has an approved test proving identifiers and values are safely bound. Permission tests inspect `pg_proc.prosecdef`, `proconfig`, owner and ACLs, and prove build/runtime cannot replace a routine or create objects in any referenced schema.

All application-data foreign keys in this and later migrations explicitly use `RESTRICT` or `NO ACTION`. No migration may add `ON DELETE CASCADE`.

- [x] **Step 4: Run the migration and focused tests**

```bash
docker compose -f docker/postgres.compose.yml up -d --wait postgres
FINANCIAL_AGENT_DATABASE_URL="postgresql+psycopg://financial_agent_test:financial_agent_test@localhost:55432/financial_agent_test" \
  python scripts/db_preflight.py --phase pre-migration --database-url-env FINANCIAL_AGENT_DATABASE_URL
FINANCIAL_AGENT_DATABASE_URL="postgresql+psycopg://financial_agent_test:financial_agent_test@localhost:55432/financial_agent_test" \
  python -m alembic upgrade head
FINANCIAL_AGENT_TEST_DATABASE_URL="postgresql+psycopg://financial_agent_test:financial_agent_test@localhost:55432/financial_agent_test" \
  python -m pytest tests/db/test_foundation_migration.py tests/db/test_database_permissions.py -v
```

Expected: revision `0001` is current and every constraint case passes.

- [x] **Step 5: Commit the foundation**

```bash
git add alembic.ini alembic src/financial_agent/db/schema tests/db/test_foundation_migration.py tests/db/test_database_permissions.py
git diff --cached --check
git diff --cached
git commit -m "feat: add postgres dataset foundation"
```

### Task 3: Implement the versioned catalog schema

**Files:**

- Create: `alembic/versions/0002_catalog_schema.py`
- Create: `src/financial_agent/db/schema/catalog.py`
- Create: `tests/db/test_catalog_schema.py`
- Create: `tests/fixtures/db/synthetic_dataset.py`

**Interfaces:**

- `catalog.entity`, `catalog.product`, `catalog.security`, `catalog.institution`
- `catalog.identifier`, `catalog.alias`

- [x] **Step 1: Write failing catalog constraints**

Tests must prove:

- the same `entity_id` may exist in two dataset versions, but only once per version;
- subtype rows cannot point to an entity in another dataset version;
- `product_family` accepts only `domestic_bond`, `domestic_etf`, `overseas_etf`, or `public_fund`;
- a product row can attach only to an entity whose `entity_type='product'` through a deferred constraint trigger;
- `(dataset_version, scheme, identifier_value)` is unique, so one identifier cannot be reassigned inside one immutable dataset version;
- only one primary identifier exists per entity and scheme;
- aliases preserve original text and separately store normalized text;
- modifying versioned catalog rows after dataset validation is rejected.

- [x] **Step 2: Define catalog columns and keys**

Use composite `(dataset_version, entity_id)` keys. `entity_type` permits `product`, `security`, `company`, `institution`, `index`, and `theme`. `entity` stores canonical name, normalized name, record hash, and creation time. Subtype tables store only stable identity fields required before ingestion mapping:

- `product`: product family and nullable primary currency;
- `security`: security kind and nullable ticker/ISIN display fields;
- `institution`: institution kind.

Do not copy all four organizer master columns into `catalog.product`. Stage 03 maps identity attributes, observations, and relations deliberately after profiling each source field.

Apply `operations.reject_nonbuilding_dataset_mutation()` to all versioned catalog tables. Rows remain editable while their dataset is building and become immutable as soon as it is validated.

- [x] **Step 3: Define identifier and alias indexes**

Add:

- B-tree indexes for product family and entity type;
- one unique and one lookup index for identifier scheme/value;
- a partial unique index for primary identifier;
- B-tree lookup on normalized alias;
- `GIN (... gin_trgm_ops)` on normalized canonical and alias names.

- [x] **Step 4: Generate and review migration `0002`**

Use Alembic autogenerate with explicit revision ID, then inspect every schema, FK target, check, and index. Do not accept an unnamed constraint or an FK that omits `dataset_version`.

```bash
python -m alembic revision --autogenerate --rev-id 0002 -m "catalog schema"
python -m alembic upgrade head
python -m alembic check
```

- [x] **Step 5: Run catalog tests**

```bash
python -m pytest tests/db/test_catalog_schema.py -v
```

- [x] **Step 6: Commit the catalog schema**

```bash
git add alembic/versions/0002_catalog_schema.py src/financial_agent/db/schema/catalog.py tests/db/test_catalog_schema.py tests/fixtures/db/synthetic_dataset.py
git diff --cached --check
git diff --cached
git commit -m "feat: add versioned product catalog"
```

### Task 4: Implement relation, observation, document, and search storage

**Files:**

- Create: `alembic/versions/0003_fact_document_search_schemas.py`
- Create: `src/financial_agent/db/schema/relation.py`
- Create: `src/financial_agent/db/schema/observation.py`
- Create: `src/financial_agent/db/schema/document.py`
- Create: `src/financial_agent/db/schema/search.py`
- Create: `src/financial_agent/db/schema/evidence.py`
- Create: `tests/db/test_fact_document_search_schema.py`

**Interfaces:**

- `relation.relation_record`
- `observation.metric_definition`, `observation.observation_record`
- `document.document_record`, `document.document_chunk`
- `search.embedding_model`, `search.document_embedding`
- `evidence.source_record`

- [x] **Step 1: Write failing relation and observation tests**

Tests must reject:

- a relation whose subject and object come from different dataset versions;
- `valid_to < valid_from`;
- an observation with both an entity target and a relation target;
- an observation with neither target;
- a present observation with zero or two typed value columns;
- a missing/placeholder/unavailable/inapplicable observation with any typed value;
- `value_status='zero'` with a nonzero numeric, text, boolean, date, or timestamp value;
- `value_status='present'` with `numeric_value=0`, which must use the explicit zero state;
- an unregistered metric or a value kind that conflicts with the metric definition.

Tests must accept a true numeric zero with `value_status='zero'`; zero is not missing.

- [x] **Step 2: Define relation and observation storage**

`relation_record` stores versioned relation ID, subject entity, predicate ID, object entity, validity dates, record hash, and creation time.

`metric_definition` is append-only with composite primary key `(metric_id, definition_version)` and stores semantic family, value kind, default unit, description, definition hash, and approval time. An observation references that exact composite version so a later definition cannot change historical meaning. `observation_record` stores:

- exactly one target: entity or relation;
- value status: `present`, `zero`, `missing`, `placeholder`, `unavailable`, `inapplicable`, `unknown`;
- exactly one of `numeric_value NUMERIC(38,12)`, `text_value`, `boolean_value`, `date_value`, or `timestamp_value` when present;
- exactly `numeric_value=0` and no other typed value when status is `zero`;
- `unit`, `currency`, period start/end, applicable date, published/available/vintage times;
- a reason code for non-present values and a record hash.

Do not infer a missing currency, date, period, or unit in the table layer.

Use a deferred `observation.validate_metric_value_kind()` trigger to compare each row with the referenced metric-definition version. Apply `operations.reject_nonbuilding_dataset_mutation()` to relation and observation rows after creation, and an unconditional append-only trigger to the metric registry.

- [x] **Step 3: Write failing Source, document, and embedding tests**

Verify Source rows are unique by `(dataset_version, source_id)`, require lowercase SHA-256 checksum/record hashes, and use same-version publisher FKs. Verify parent chunks stay within one document/version, document rows reference an existing same-version Source immediately in revision `0003`, sentence and page ranges are ordered, document checksum and chunk text hashes are valid SHA-256, embedding rows reference the exact chunk content hash, the stored vector dimension equals the registered model version, and registry updates/deletes are rejected.

- [x] **Step 4: Define document and search storage**

Migration `0003` creates `evidence.source_record` before the document tables in the same `upgrade()` body. `source_record` includes all Stage 01 `SourceRecord` fields plus `dataset_version`; its publisher uses a composite FK to a same-version catalog institution/entity and a deferred institution-type check. `document_record` then creates its same-version composite Source FK immediately. Revision `0003` must never leave an indexed but unconstrained `source_id`, even transiently.

`document_chunk` stores parent chunk, ordinal, page, section, sentence bounds, exact text, normalized search text, and hashes. Add a trigram GIN index to normalized search text; do not claim that PostgreSQL's built-in parser solves Korean full-text morphology.

`embedding_model` is append-only with composite primary key `(model_id, model_version)` and records dimension, distance metric, approval record ID, approval time, and model hash. Only already-approved model versions may be inserted; changing approval creates a new version row. `document_embedding` references that exact version, uses the schema-qualified `cdb_admin.vector` type, records the explicit dimension and content hash, and verifies both with a trigger. Do not create HNSW or IVFFlat indexes in this stage.

Apply `operations.reject_nonbuilding_dataset_mutation()` to versioned document and embedding rows. Metric and embedding-model registries reject all updates/deletes; replacement means a new immutable composite version.

- [x] **Step 5: Generate, inspect, and run migration `0003`**

```bash
python -m alembic revision --autogenerate --rev-id 0003 -m "fact document search schemas"
python -m alembic upgrade head
python -m alembic check
python -m pytest tests/db/test_fact_document_search_schema.py -v
```

- [x] **Step 6: Commit fact and search storage**

```bash
git add alembic/versions/0003_fact_document_search_schemas.py src/financial_agent/db/schema tests/db/test_fact_document_search_schema.py
git diff --cached --check
git diff --cached
git commit -m "feat: add fact and search storage"
```

### Task 5: Implement the normalized Evidence ledger

**Files:**

- Create: `alembic/versions/0004_evidence_ledger.py`
- Modify: `src/financial_agent/db/schema/evidence.py`
- Create: `tests/db/test_evidence_schema.py`

**Interfaces:**

- All `evidence.*` tables in the storage map
- read-only view `evidence.claim_eligible_evidence`
- append-only trigger function `evidence.reject_mutation()`
- immediate trigger function `evidence.validate_cutoff_status()`
- deferred trigger function `evidence.reject_calculation_cycle()`
- immutable SQL function `evidence.is_valid_tagged_value(jsonb)`

- [x] **Step 1: Write failing source and Evidence tests**

Cover:

- an Evidence row cannot reference a Source from another dataset;
- `valid_to >= valid_from` when both exist;
- `query_scope` requires `scope_completeness`, and other Evidence kinds reject it;
- an after-cutoff Evidence row is stored with `cutoff_status='after_cutoff'`;
- each of `applicable_date='2026-07-12'`, `published_at='2026-07-12T00:00:00Z'`, `available_at='2026-07-12T00:00:00Z'`, and `vintage_date='2026-07-12'` is rejected when paired with `cutoff_status='eligible'`;
- `cutoff_status='after_cutoff'` is rejected when none of the four cutoff-bearing fields is after the dataset cutoff;
- after-cutoff, unknown-vintage, inapplicable, or source-ineligible rows do not appear in `claim_eligible_evidence`;
- an Evidence subject from another dataset or a nonexistent catalog entity is rejected, while the explicitly subjectless Evidence kinds remain valid;
- all SourceLocator components round-trip without one opaque locator JSON object.

- [x] **Step 2: Define tagged scalar storage**

For Evidence raw/normalized values, calculation results/parameters, and Claim values/qualifiers, use one recursively tagged JSONB object. Allowed scalar tags are:

```text
null, string, integer, decimal, boolean, date, datetime, tuple
```

Scalar representation is `{"type": <tag>, "value": <json-scalar>}`. Tuple representation is `{"type": "tuple", "items": [<tagged-scalar>, ...]}`; every tuple element keeps its own tag. Nested tuples, mappings, floats, extra keys, and untagged values are rejected. Decimal values serialize as canonical strings and are validated before returning to contracts.

The Python representation is the frozen discriminated `ScalarValue`/`ContractValue` union owned by the amended Stage 01 `contracts/values.py`. Stage 02 must not define a persistence-only duplicate. PostgreSQL function `evidence.is_valid_tagged_value(jsonb)` recursively checks the exact Stage 01 keys, tag names, JSON types, integer form, canonical decimal syntax, ISO dates, UTC datetimes, and per-item tuple tags. Every tagged-value column has a named CHECK that invokes it, so direct SQL cannot store a decimal tag with an object or erase mixed-tuple type information.

- [x] **Step 3: Define Source, Evidence, and origin links**

`evidence_record` includes all Stage 01 fields, explicit SourceLocator columns, tagged raw/normalized values, and the composite Source FK created in migration `0003`. Nullable `(dataset_version, subject_id)` references `catalog.entity`; `observation`, `relation`, and `document_span` Evidence requires a subject, while `query_scope`, `exclusion`, and `policy` may be explicitly subjectless.

`evidence.validate_cutoff_status()` obtains the parent dataset cutoff and checks all four cutoff-bearing fields before the row becomes visible. If any is after the cutoff, status must be `after_cutoff`; if none is after, status cannot be `after_cutoff`. `unknown_vintage` and `inapplicable` remain explicit semantic states and cannot be converted to eligible merely because their nullable dates are absent.

Add separate origin tables for observation, relation, and document chunk. Each origin table has a composite FK on both sides and a primary key on the Evidence identity. Deferred database constraint triggers enforce exactly one matching origin row for `observation`, `relation`, and `document_span` Evidence, forbid the other two origin tables, and forbid every origin row for `query_scope`, `exclusion`, and `policy`. The repository performs the same check before forcing deferred constraints, but the commit-time database rule is authoritative.

- [x] **Step 4: Write failing Calculation and Claim tests**

Verify:

- a Calculation with no input Evidence or dependency is rejected;
- dependency rows stay in the same run and cannot self-reference;
- two-node `A -> B -> A` and three-node `A -> B -> C -> A` dependency cycles fail at constraint-check/commit time;
- ranking requires one population row, at least one population filter, and a tie-break rule;
- aggregation requires one population row;
- every population scope references Evidence from the request dataset;
- ordinal values are unique and nonnegative for every association;
- AtomicClaim object/value XOR and qualifier-only exceptions match Stage 01;
- entity-bound Claim types reject nonexistent or cross-version `subject_id`/`object_id`, while `no_match`, `data_limitation`, and `policy_boundary` reject any subject not registered as the same run's QueryPlan subtask;
- ClaimSupport accepts exactly one target and enforces same-run/same-dataset scope;
- update and delete attempts on Source, Evidence, Calculation, Claim, qualifier, and support rows fail.

- [x] **Step 5: Define normalized Calculation and Claim tables**

Do not place arrays of input IDs, filter IDs, exclusions, qualifiers, or support IDs in `calculation_record` or `atomic_claim`. Store their order in the association tables listed in section 5.

`calculation_dependency` is a directed edge from a Calculation to its prior input Calculation. Deferred function `evidence.reject_calculation_cycle()` uses a recursive CTE over all same-run edges and rejects a path that returns to its origin. The repository may pre-check for a clearer error, but the database check at constraint/commit time is authoritative.

`atomic_claim` stores persistence-only `dataset_version` from `request_run`, the original contract `subject_id`, `subject_kind=entity|request`, nullable `subject_entity_id`, nullable `request_subject_id`, and nullable `object_id`. For `direct_fact`, `relation`, `derived_metric`, `rank`, and `similarity`, `subject_entity_id` must equal `subject_id`, `request_subject_id` is null, and a composite FK targets catalog. For `no_match`, `data_limitation`, and `policy_boundary`, `subject_kind='request'`, `subject_entity_id IS NULL`, `request_subject_id=subject_id=subtask_id`, and `(run_id, request_subject_id)` references `operations.request_subtask`. Every non-null `object_id` has a same-dataset composite catalog FK.

Use deferred constraints where a complete aggregate invariant spans multiple rows. The repository inserts a Calculation or Claim and all child rows in one transaction, then explicitly validates aggregate invariants before commit. Database functions provide the same checks so a non-repository client cannot commit an incomplete ranking or unsupported Claim. Tests for every deferred rule must execute `SET CONSTRAINTS ALL IMMEDIATE` or commit an inner transaction before asserting failure; an outer pytest rollback alone is not evidence that the trigger ran.

- [x] **Step 6: Add indexes and the safe Evidence view**

At minimum add:

- Evidence `(dataset_version, subject_id, predicate_id, applicable_date DESC)`;
- Evidence `(dataset_version, source_id)` and cutoff-status partial indexes;
- relation `(dataset_version, predicate_id, subject_id, object_id)`;
- observation target/metric/date indexes;
- Calculation and Claim hash indexes within run scope;
- ClaimSupport Evidence and Calculation reverse-lookup indexes.

The safe view joins `source_record` and returns only `eligible_for_claim=true`, `cutoff_status='eligible'`, and rows whose four cutoff-bearing fields independently satisfy the dataset cutoff. The repeated date predicate is deliberate defense in depth against trigger or migration drift; it is not a substitute for the later deterministic Verifier.

- [x] **Step 7: Generate, inspect, and run migration `0004`**

```bash
python -m alembic revision --autogenerate --rev-id 0004 -m "evidence ledger"
python -m alembic upgrade head
python -m alembic check
python -m pytest tests/db/test_evidence_schema.py -v
```

- [x] **Step 8: Commit the Evidence DDL**

```bash
git add alembic/versions/0004_evidence_ledger.py src/financial_agent/db/schema/evidence.py tests/db/test_evidence_schema.py
git diff --cached --check
git diff --cached
git commit -m "feat: add normalized evidence ledger"
```

### Task 6: Implement lossless Evidence persistence adapters

**Files:**

- Create: `src/financial_agent/db/repositories/__init__.py`
- Create: `src/financial_agent/db/repositories/evidence.py`
- Create: `tests/db/test_evidence_repository.py`
- Create: `tests/db/test_concurrent_idempotency.py`
- Create: `tests/db/test_tagged_value_parity.py`
- Create: `tests/fixtures/db/tagged_value_corpus.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class RequestScope:
    request_key: str
    run_id: str
    dataset_version: str


@dataclass(frozen=True, slots=True)
class OriginReference:
    origin_kind: Literal["observation", "relation", "document_chunk"]
    dataset_version: str
    record_id: str


class EvidenceLedgerRepository:
    async def append_source(
        self, dataset_version: str, source: SourceRecord
    ) -> None: ...

    async def append_evidence(
        self, evidence: EvidenceRecord, *, origin: OriginReference | None = None
    ) -> None: ...

    async def append_calculation(
        self, scope: RequestScope, calculation: CalculationRecord
    ) -> None: ...

    async def append_claim(
        self,
        scope: RequestScope,
        claim: AtomicClaim,
        *,
        supports: tuple[ClaimSupport, ...],
    ) -> None: ...

    async def append_support(
        self, scope: RequestScope, support: ClaimSupport
    ) -> None: ...

    async def get_evidence(
        self, dataset_version: str, evidence_id: str
    ) -> EvidenceRecord: ...

    async def get_calculation(
        self, run_id: str, calculation_id: str
    ) -> CalculationRecord: ...

    async def get_claim(
        self, run_id: str, claim_id: str
    ) -> AtomicClaim: ...
```

`RequestScope` is a persistence-only frozen dataclass containing `request_key`, `run_id`, and `dataset_version`. It does not replace RuntimeArtifact metadata. Tagged value types and `encode_contract_value`/`decode_contract_value` are imported from Stage 01 contracts and are never redeclared under `db`.

`append_claim()` requires at least one initial `ClaimSupport` and inserts the Claim, its ordered qualifiers, and those supports in one transaction. This atomic boundary is required because migration `0004` rejects a Claim with no support when deferred constraints are forced or the transaction commits, while a support cannot reference a Claim that has not yet been inserted. `append_support()` remains available only for adding subsequent supports to an already persisted Claim; the database invariant is not weakened to accommodate split writes.

- [x] **Step 1: Write failing tagged-value database parity tests**

Create one shared valid/invalid corpus consumed by the Stage 01 compatibility test and direct PostgreSQL CHECK test. Persist and reload the exact Stage 01 tagged JSON shapes for:

- `Decimal("0")`, `Decimal("0.000100000000")`, and a large AUM value;
- `date(2026, 7, 11)` and a UTC datetime;
- strings that look like dates or decimals but must remain strings;
- booleans without converting them to integers;
- tagged null and homogeneous/mixed TupleValue;
- `(date(2026, 7, 11), "2026-07-11", Decimal("1.0"), "1.0")`, whose four encoded items must have `date`, `string`, `decimal`, and `string` tags respectively.

The corpus fixes the canonical outputs `Decimal("1.00") -> {"type":"decimal","value":"1"}`, exact UTC `2026-07-11T00:00:00Z`, and microsecond UTC `2026-07-11T00:00:00.123456Z`. It includes every scalar tag plus homogeneous, mixed, and empty tuples. Invalid cases include noncanonical/overflowing decimals, impossible and leap-date errors, naive/non-UTC/noncanonical datetimes, extra/missing keys, wrong tag/value JSON types, nested tuples, mappings, floats, and untagged values. Every valid Stage 01 JSON-mode output must pass the DB CHECK, and every invalid corpus member must fail it.

The Stage 01 contract tests already reject float input, naive datetime, non-UTC datetime, nested tuple, mapping, and unsupported native values. At the database boundary, insert an unknown type tag, nested tuple, extra tagged-object key, noncanonical Decimal, and every tag/value mismatch with direct SQL and require the named CHECK to fail.

- [x] **Step 2: Bind Stage 01 tagged contracts to JSONB without a second codec**

Repository writes call the frozen Stage 01 model's `model_dump(mode="json")` and Stage 01 `encode_contract_value` directly. Repository reads call the owning Stage 01 model's `model_validate_json` and, when a native scalar is explicitly needed, Stage 01 `decode_contract_value`. No `db/codec.py`, forwarding codec abstraction, persistence-only TaggedValue, `mixed_tuple` shortcut, or context-based type inference is allowed.

- [x] **Step 3: Write failing repository round-trip tests**

Using only synthetic fixtures, append and reload:

- a claim-eligible official source and direct Evidence;
- an after-cutoff Evidence retained for rejection;
- a ranking Calculation with ordered Evidence inputs, exclusions, population filters, and tie-break;
- an AtomicClaim with ordered qualifiers and at least one initial support in the same transaction;
- an additional direct or Calculation ClaimSupport row appended after the Claim transaction.

Compare reconstructed Pydantic objects for exact equality. Verify an attempted second insert with the same ID but different hash fails; identical retries may return the existing row only after byte-equivalent canonical comparison. For `SourceRecord` and `EvidenceRecord`, use two independent committed connections: same ID plus same canonical payload converges on one row and the same persisted identity, while same ID plus different payload produces one success and one stable conflict without a table-wide or global advisory lock.

- [x] **Step 4: Implement transactional append and load methods**

Use SQLAlchemy Core statements and `AsyncConnection.begin()`. Repository methods have no update or delete operation. Insert all parent and association rows in one transaction; specifically, `append_claim()` inserts the Claim, qualifiers, and a non-empty initial support tuple atomically, while `append_support()` adds only later supports to an existing Claim. Derive Claim entity/request subject scope from the closed Claim-type registry, and execute `SET CONSTRAINTS ALL IMMEDIATE` before commit so cutoff, DAG, type, and aggregate checks run inside the method. Catch unique conflicts only to implement deterministic identical-retry behavior; never silently accept a different payload under an existing ID.

- [x] **Step 5: Run codec and repository tests**

```bash
python -m pytest tests/db/test_evidence_repository.py -v
```

- [x] **Step 6: Commit persistence adapters**

```bash
git add src/financial_agent/db/repositories tests/db/test_evidence_repository.py tests/db/test_concurrent_idempotency.py tests/db/test_tagged_value_parity.py tests/fixtures/db/tagged_value_corpus.py
git diff --cached --check
git diff --cached
git commit -m "feat: persist evidence contracts losslessly"
```

### Task 7: Persist immutable runtime artifacts without granting release authority

**Files:**

- Create: `alembic/versions/0005_request_artifacts.py`
- Modify: `src/financial_agent/db/schema/operations.py`
- Create: `src/financial_agent/db/repositories/artifacts.py`
- Create: `src/financial_agent/db/repositories/operations.py`
- Create: `tests/db/test_artifact_repository.py`
- Create: `tests/db/test_operations_repository.py`

**Interfaces:**

```python
ArtifactType = Literal[
    "request_context",
    "query_plan",
    "execution_graph",
    "tool_result",
    "evidence_bundle",
    "verification_report",
    "answer_plan",
    "released_answer",
]

ARTIFACT_MODELS: Mapping[ArtifactType, type[RuntimeArtifact]] = {
    "request_context": RequestContext,
    "query_plan": QueryPlan,
    "execution_graph": ExecutionGraph,
    "tool_result": ToolResult,
    "evidence_bundle": EvidenceBundle,
    "verification_report": VerificationReport,
    "answer_plan": AnswerPlan,
    "released_answer": ReleasedAnswer,
}


class RequestArtifactRepository:
    async def start_run(self, context: RequestContext) -> str: ...
    async def append(
        self,
        artifact_type: ArtifactType,
        artifact: RuntimeArtifact,
        *,
        model_id: str | None = None,
        prompt_version: str | None = None,
    ) -> UUID: ...
    async def get(
        self, run_id: str, artifact_record_id: UUID
    ) -> RuntimeArtifact: ...


@dataclass(frozen=True, slots=True)
class FailureEventRecord:
    event_id: str
    run_id: str
    task_id: str | None
    stage: str
    code: str
    category: Literal[
        "transient", "deadline", "internal_invariant",
        "planner_contract", "answer_contract"
    ]
    retryable: bool
    attempt: int
    remaining_budget_ms: int
    duration_ms: int
    dependency: str | None
    occurred_at: datetime


class RequestRunRepository:
    async def append_failure_event(self, event: FailureEventRecord) -> None: ...
    async def finish_run(
        self,
        run_id: str,
        *,
        execution_outcome: ExecutionOutcome,
        verification_status: VerificationStatus | None,
        answer_disposition: AnswerDisposition | None,
        http_status: int,
        final_verification_report_id: str | None,
        terminal_failure_code: str | None,
        finished_at: datetime,
    ) -> None: ...
```

- [x] **Step 1: Write failing request-run and artifact repository tests**

The request-run table already exists from revision `0001`; these tests exercise it through `operations.start_request_run(...)` and the repository boundary. Verify:

- deadline equality at 55 seconds is accepted;
- `2026-08-17T00:00:56Z` for a `2026-08-17T00:00:00Z` start is rejected;
- a deadline before or equal to creation is rejected for its own ordering rule;
- dataset version and cutoff must match the referenced dataset;
- supplied dataset must be the locked current active dataset at start, while a later active-version switch does not change the run;
- identical concurrent starts with the same `run_id` return one row; a conflicting reuse raises `REQUEST_RUN_CONFLICT`; distinct run IDs for one request key are allowed;
- `ExecutionOutcome`, `VerificationStatus`, and `AnswerDisposition` remain separate nullable columns;
- a failed execution cannot store an answer disposition;
- `finish_run` permits exactly one open-to-terminal transition and rejects a second conflicting terminal state;
- a semantic processing result requires HTTP 200, `verification_status=pass`, a final VerificationReport artifact, and a non-null matching disposition, but does not authorize release;
- a 5xx terminal run requires `execution_outcome=failed`, null verification/disposition/final report, and a stable terminal failure code;
- multiple append-only FailureEvents retain every retry rather than overwriting one failure code;
- no column exists for raw chain-of-thought.

- [x] **Step 2: Define runtime artifact tables**

`request_artifact` has server-generated `artifact_record_id UUID PRIMARY KEY`, nullable `contract_object_id`, indexed metadata, `canonical_payload TEXT`, a database-derived JSONB projection, and a database-derived SHA-256. A `BEFORE INSERT` trigger ignores caller-supplied projection/hash values, parses `canonical_payload::jsonb`, and computes `encode(digest(canonical_payload, 'sha256'), 'hex')`; the UTF-8 preflight makes this the same byte encoding used by Stage 01. `artifact_type` permits exactly the eight `ARTIFACT_MODELS` keys. Unique constraints cover `(run_id, artifact_type, contract_object_id)` when the contract ID exists and `(run_id, artifact_type, payload_hash)` for canonical retry identity. All artifact/reference FKs target `artifact_record_id`, never an assumed contract ID.

The explicit contract-ID extraction map uses `graph_id`, `task_id`, `bundle_id`, and `verification_report_id` for their matching artifact types; types without an explicit top-level object ID store null rather than repurposing a content hash as a public contract ID. `model_id` and `prompt_version` are keyword-only persistence metadata and must be supplied together. QueryPlan requires both; AnswerPlan accepts both for model production or neither for the deterministic fallback; deterministic artifact types reject them.

The repository validates with `ARTIFACT_MODELS[artifact_type].model_validate_json(...)` before opening the insert transaction, then calls the Stage 01 artifact's `model_dump(mode="json")` and `canonical_json_bytes()` directly. PostgreSQL derives JSONB and hash from the canonical text. Reads pass `canonical_payload` to the selected model's `model_validate_json`; they never reconstruct from JSONB text. Identical retries compare canonical text as well as hash, so a hash match alone is insufficient.

The three reference tables preserve explicit Evidence, Calculation, and Claim FKs with `artifact_record_id`, `reference_role`, and stable ordinals. They are populated from the validated artifact's ID collections, not caller-supplied unrelated lists. Persisting a QueryPlan also populates immutable `request_subtask` rows before any Claim can be inserted. VerificationReport Claim references use `releaseable` or `rejected`; ReleasedAnswer ClaimBinding references use `bound`.

Migration `0005` adds nullable `request_run.final_verification_artifact_id UUID` with a same-run Artifact FK and creates `operations.append_request_artifact(...)` plus `operations.finish_request_run(...)` as hardened `SECURITY DEFINER` functions. Runtime receives only `EXECUTE`; it has no direct INSERT/UPDATE/DELETE on artifact, reference, subtask, or terminal run state tables. This revision creates no release table, release status, release timestamp, cache function, or cache lookup API.

- [x] **Step 3: Write failing immutability and idempotency tests**

Test that:

- indexed `schema_version`, `request_key`, `run_id`, `dataset_version`, `cutoff_date`, `producer`, and `created_at` must equal database-derived JSONB metadata;
- all eight DB artifact types exactly equal the `ARTIFACT_MODELS` keys; unknown types, cross-type payloads, and extra JSON fields are rejected by the selected Stage 01 Pydantic model;
- changing canonical text changes the database-generated hash, and retrieval returns the original canonical text rather than PostgreSQL JSONB serialization;
- update/delete on an artifact or reference fails;
- the same canonical artifact retry returns the existing `artifact_record_id`;
- two independent connections inserting the same contract ID and canonical payload converge on one row and one UUID;
- two independent connections inserting the same contract ID with different canonical payloads produce one success and one stable `ARTIFACT_CONFLICT`;
- no `release_cache`, `cache_verified_release`, `get_cached_release`, release ACL, or release-authorization column exists;
- storing `VerificationReport=pass`, AnswerPlan, or ReleasedAnswer never creates release authority;
- a 5xx execution result cannot be represented as a successful semantic processing result.

- [x] **Step 4: Implement artifact schema and repository**

`ARTIFACT_MODELS` is a Stage 02 routing map only. It selects the frozen Stage 01 Pydantic class and contains no new validation logic, tagged-value codec, Claim predicate rules, template rules, or release policy. The future Claim Gate Registry remains a separate mandatory component.

`finish_run` calls `operations.finish_request_run(...)`, which locks the run and final report artifact, validates the one-way processing-state transition, and records the three terminal axes. These fields describe execution and deterministic verification only. They do not mean the AnswerPlan passed the future Claim Gate and do not authorize external publication. A later migration must add an explicit Claim-Gate decision and verified cache; it may not retroactively trust existing artifacts.

Do not log artifact payloads at error level. Redact the database URL and preserve only stable reason codes in raised persistence errors.

- [x] **Step 5: Generate and run migration `0005`**

```bash
python -m alembic revision --autogenerate --rev-id 0005 -m "request artifacts"
python -m alembic upgrade head
python -m alembic check
python -m pytest tests/db/test_artifact_repository.py tests/db/test_operations_repository.py -v
```

- [x] **Step 6: Commit artifact persistence**

```bash
git add alembic/versions/0005_request_artifacts.py src/financial_agent/db/schema/operations.py src/financial_agent/db/repositories/artifacts.py src/financial_agent/db/repositories/operations.py tests/db/test_artifact_repository.py tests/db/test_operations_repository.py
git diff --cached --check
git diff --cached
git commit -m "feat: persist immutable request artifacts"
```

## 8. Stage 02A Completion Gate

Do not begin Stage 02B until fresh local output proves:

- all Stage 01 contract tests and schema export pass unchanged;
- the sanitized non-production NCP capability probe selects one permission layout before permission DDL;
- `requirements/contracts.lock` is unchanged and all Stage 02 verification installs are constrained by exact `requirements/storage.lock` pins;
- migrations `0001`–`0005` apply to an empty PostgreSQL 15 database;
- all ordinary repository/constraint tests pass under rollback isolation and all deferred/concurrency tests pass with real commits in disposable databases;
- Source, Evidence, and artifact two-connection idempotency tests pass without global write serialization;
- the tagged-value corpus has full Stage 01/DB parity;
- the active-dataset start function, no-cascade policy, protected routines, canonical artifact hash, and absence of release-cache objects are proven;
- no organizer data, PDF, secret, database file, generated embedding, or runtime artifact is staged.

### Task 8: Prove migration reversibility and NCP Cloud DB compatibility (Stage 02B)

**Files:**

- Modify: `scripts/db_preflight.py`
- Create: `scripts/export_database_objects.py`
- Create: `scripts/verify_database_migrations.py`
- Create: `schemas/postgresql/v1/database-objects.json`
- Create: `tests/db/test_migration_cycle.py`
- Create: `tests/db/test_ncp_preflight.py`
- Create: `tests/db/test_query_plans.py`
- Create: `docker/database-check.Dockerfile`
- Modify: `docker/postgres.compose.yml`
- Create: `docs/runbooks/ncp-postgresql-bootstrap.md`

**Interfaces:**

- `python scripts/db_preflight.py --phase pre-migration|post-migration --database-url-env <ENV_NAME>`
- `python scripts/export_database_objects.py [--check]`
- `python scripts/verify_database_migrations.py`
- pytest marker `ncp_integration`
- pytest marker `performance`

- [ ] **Step 1: Write failing migration-cycle tests**

On a disposable empty database:

1. run pre-migration preflight against the externally provisioned `cdb_admin` extensions and roles;
2. upgrade from base to head;
3. inspect all tables, checks, FKs, indexes, views, functions, triggers, and ACLs;
4. run `alembic check` and require no table-metadata drift;
5. downgrade from head to base;
6. verify all seven application schemas and owned objects are removed while `cdb_admin`, `vector`, `pg_stat_statements`, and bootstrap roles remain untouched;
7. upgrade to head again and rerun the foundation tests.

The cycle uses the commit-capable disposable-database fixture. It never runs downgrade against a shared or production database and never relies on transaction rollback to simulate schema cleanup.

- [ ] **Step 2: Verify function, view, trigger, CHECK, and ACL definitions outside Alembic autogenerate**

Alembic autogenerate does not fully compare function, view, trigger, or CHECK expression bodies. `export_database_objects.py` must query and normalize:

- `pg_get_functiondef` for every application function;
- `pg_get_viewdef` for every application view;
- `pg_get_triggerdef` for every non-internal trigger;
- named CHECK expressions from `pg_constraint`;
- grants from `information_schema.role_table_grants`, routine grants, and schema ACLs.

It writes deterministic sorted JSON to `schemas/postgresql/v1/database-objects.json`. Normalize whitespace and the three stable logical role names, exclude environment-specific member-login/owner identities and all `cdb_admin` objects, and retain executable SQL meaning. `--check` exports to memory/a temporary file and exits nonzero on a missing, extra, or byte-different definition. Tests must prove that changing only a function body, function `search_path`, owner/EXECUTE ACL, view predicate, trigger timing, cutoff CHECK, or runtime grant is detected even when `alembic check` still passes.

After all migration-managed objects are defined, generate and immediately verify the reviewed baseline:

```bash
python scripts/export_database_objects.py
git diff -- schemas/postgresql/v1/database-objects.json
python scripts/export_database_objects.py --check
```

- [ ] **Step 3: Write failing post-migration preflight tests**

`--phase post-migration` repeats every pre-migration check and additionally checks, without printing credentials:

- PostgreSQL major version 15;
- UTC database/session timezone;
- required extensions, installed versions, and exact extension schemas;
- all seven schemas;
- Alembic head equality;
- fixed dataset cutoff;
- active-dataset readiness/validation/manifest consistency;
- ability to begin, roll back, and execute a parameterized query;
- absence of public-schema application tables other than Alembic's `alembic_version` bookkeeping table;
- `cdb_admin.vector` type/dimension function and `cdb_admin.pg_stat_statements` availability;
- expected role membership and denial of direct runtime/build mutations;
- database-object manifest equality.

It exits nonzero with stable codes such as `DB_VERSION_MISMATCH`, `MISSING_NCP_EXTENSION`, `NCP_EXTENSION_SCHEMA_MISMATCH`, `MIGRATION_BEHIND`, `OBJECT_DEFINITION_DRIFT`, `DATABASE_PERMISSION_DRIFT`, or `ACTIVE_DATASET_INCONSISTENT`.

- [ ] **Step 4: Add index-plan and bounded scale tests**

Generate synthetic rows only: at least 100,000 catalog aliases, 250,000 relations, 250,000 observations, and the minimal linked Evidence/Claim rows needed for representative plans. Bulk load them into a disposable building dataset, run `ANALYZE`, then use `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for:

- normalized/trigram entity alias lookup;
- ETF-to-constituent relation lookup;
- latest metric by entity/metric/date;
- Evidence-to-Claim lineage traversal;
- `(run_id, artifact_type, contract_object_id)` artifact lookup and `(run_id, artifact_type, payload_hash)` identical-retry lookup.

For selective predicates, tests fail on a sequential scan of the large relation, observation, alias, Evidence, or artifact table and require the named planned index. Record rows examined, planning time, and execution time. Tests marked `performance` skip unless `RUN_DB_SCALE_TESTS=1`; the Stage 02 completion run sets it explicitly. The gated NCP run executes each core query 30 times after five warmups and requires p95 below the approved 500 ms core-SQL threshold. It also runs four representative reads concurrently for 30 rounds using `db_read_concurrency_limit=4`, `pool_size=5`, and `max_overflow=0`; no pool timeout is allowed, and individual query plus round latency is reported. Local CI asserts plan shape rather than hardware-specific latency. NCP measurements may change these three configuration defaults only through a reviewed benchmark record; they do not weaken the 55-second request hard deadline or evidence checks.

- [ ] **Step 5: Implement the local Linux/amd64 database-check image**

`database-check.Dockerfile` installs the package and database test dependencies under `PIP_CONSTRAINT=/app/requirements/storage.lock`, copies no source data, and runs migrations plus `tests/db`. Add a Compose `db-check` service that connects to the PostgreSQL service over the Compose network. Both database image and check image build/run paths target Linux/amd64; the PostgreSQL service uses the reviewed exact tag plus digest from Task 1.

```bash
docker compose -f docker/postgres.compose.yml build db-check
docker compose -f docker/postgres.compose.yml up -d --wait postgres
docker compose -f docker/postgres.compose.yml run --rm db-check
```

Expected: migrations and all non-NCP database tests pass on Linux/amd64.

- [ ] **Step 6: Document the NCP bootstrap boundary**

`docs/runbooks/ncp-postgresql-bootstrap.md` must state:

- Cloud DB PostgreSQL 15, private subnet, 4 vCPU/16 GB, SSD, final-evaluation HA and daily 7–14 day backups;
- install pgvector and `pg_stat_statements` from the NCP console before migrations; pgvector's first installation restarts the DB service, so schedule it before evaluation;
- both console-managed extensions live in `cdb_admin`, and every connection uses `"$user", public, cdb_admin` or an explicitly schema-qualified object;
- record the sanitized Task 1 permission-capability result; use either the three stable NOLOGIN group roles with separate login members or three NCP console-created stable login users with direct grants, never a guessed hybrid;
- Alembic creates only `pg_trgm`, `pgcrypto`, and `unaccent`; it never manages the two `cdb_admin` extensions;
- run pre-migration preflight, Alembic, post-migration preflight, permission tests, and the database-object manifest check in that order;
- verify every `SECURITY DEFINER` owner, fixed function search path, explicit EXECUTE ACL, and revoked PUBLIC access;
- PostgreSQL port 5432 is allowed only from API and data-build servers;
- total application connections obey `worker_processes * pool_size + migration_admin_reserve <= floor(max_connections * 0.8)`; with the initial pool size of five, the runbook must compute and record the permitted worker count without exposing an endpoint or account identifier;
- the database is never made public for the organizer; only the `/answer` API is public;
- how to take a logical backup plus manifest after final dataset activation;
- no endpoint, account ID, password, or private address is committed.

- [ ] **Step 7: Run the gated non-production NCP integration test**

This step requires explicit user authorization and a disposable or non-production NCP database. It is skipped in ordinary local CI.

First complete the two NCP console installations and role bootstrap from the runbook. Then run:

```bash
FINANCIAL_AGENT_DATABASE_URL="<injected-NCP-migration-url>" \
  python scripts/db_preflight.py --phase pre-migration --database-url-env FINANCIAL_AGENT_DATABASE_URL
FINANCIAL_AGENT_DATABASE_URL="<injected-NCP-migration-url>" \
  python -m alembic upgrade head
FINANCIAL_AGENT_NCP_TEST_DATABASE_URL="<injected-NCP-runtime-test-url>" \
  python scripts/db_preflight.py --phase post-migration --database-url-env FINANCIAL_AGENT_NCP_TEST_DATABASE_URL
FINANCIAL_AGENT_NCP_TEST_DATABASE_URL="<injected-NCP-runtime-test-url>" \
  python -m pytest -m ncp_integration tests/db/test_ncp_preflight.py -v
RUN_DB_SCALE_TESTS=1 FINANCIAL_AGENT_NCP_TEST_DATABASE_URL="<injected-NCP-runtime-test-url>" \
  python -m pytest -m performance tests/db/test_query_plans.py -v
```

No command may print its URL. The migration may create only the three user-installable extensions, Alembic bookkeeping table, and objects under the seven application schemas in the approved test database. Do not run a downgrade against a shared or production NCP database.

- [ ] **Step 8: Run the complete Stage 02 verification**

```bash
python -m pytest tests/contracts tests/db -m "not performance and not ncp_integration" -q
RUN_DB_SCALE_TESTS=1 python -m pytest -m performance tests/db/test_query_plans.py -v
python scripts/export_contract_schemas.py --check
python scripts/export_database_objects.py --check
python scripts/verify_database_migrations.py
docker compose -f docker/postgres.compose.yml run --rm db-check
git diff --check
git status --short --ignored
```

Verify manually that no organizer workbook/PDF, file under `data/`, database volume, `.env`, credential, NCP identifier, local dump, Parquet file, embedding, cache, or runtime artifact is staged.

- [ ] **Step 9: Commit the portability proof and runbook**

```bash
git add docker/database-check.Dockerfile docker/postgres.compose.yml docs/runbooks/ncp-postgresql-bootstrap.md schemas/postgresql/v1/database-objects.json scripts/db_preflight.py scripts/export_database_objects.py scripts/verify_database_migrations.py tests/db/test_migration_cycle.py tests/db/test_ncp_preflight.py tests/db/test_query_plans.py
git diff --cached --check
git diff --cached
git status --short
git commit -m "test: verify postgres storage on ncp baseline"
```

## 9. Stage 02 Completion Gate

Stage 02 is complete only when fresh output proves all of the following:

- Stage 01 contract tests and deterministic schema export still pass unchanged.
- Stage 01's `pydantic>=2.10,<3` lower bound remains unchanged.
- Pre-migration checks prove `vector` and `pg_stat_statements` are usable in `cdb_admin`; Alembic neither creates nor drops them.
- A preflight-ready empty PostgreSQL 15 application database, with NCP-managed extensions and bootstrap roles already provisioned, upgrades to Alembic head and downgrades to base without manual SQL intervention.
- Downgrade removes only application-owned objects and preserves NCP-managed extensions and bootstrap roles.
- `alembic check` reports no table-metadata drift, and the database-object manifest reports no function/view/trigger/CHECK/ACL drift.
- All seven logical schemas, required extensions, constraints, views, triggers, and indexes exist.
- The active dataset cannot be switched until four readiness rows reference successful validation runs and matching dataset/component manifests; concurrent first activations leave one consistent winner.
- Build/runtime roles cannot bypass readiness, activation, append-only, or registry restrictions with direct DML.
- NCP's observed permission capabilities select one documented least-privilege layout; every protected function has a fixed safe search path, explicit owner/ACL, and no PUBLIC execution.
- Catalog, relations, observations, documents, Sources, Evidence, and entity-bound Claims cannot cross dataset versions through a valid FK.
- Zero requires numeric zero; missing, placeholder, unavailable, and inapplicable values carry no typed value and remain distinguishable.
- Every future cutoff-bearing Evidence date conflicts with `eligible`; retained after-cutoff Evidence is absent from the claim-eligible view.
- Homogeneous and mixed tuples round-trip with an independent tag per element, and direct SQL tag/value mismatches fail.
- Ranking and aggregation inputs, populations, filters, exclusions, dependencies, and tie-breaks are normalized and reproducible; two- and three-node Calculation cycles fail at constraint/commit time.
- Claim support enforces exactly one Evidence or Calculation target.
- Evidence and request artifacts round-trip to the exact Stage 01 Pydantic contracts, including Decimal/date/datetime types.
- Runtime artifact rows use a persistence UUID distinct from nullable contract IDs; canonical text round-trips byte-equivalently while PostgreSQL derives matching JSONB and SHA-256.
- Append-only data rejects updates and deletes; a conflicting duplicate ID never silently overwrites prior content.
- Application FKs never cascade deletes, and deleting a parent cannot erase validated lineage or request audit history.
- Metric and embedding registries preserve immutable composite versions referenced by historical rows.
- FailureEvents retain every retry attempt and budget observation without raw Chain-of-Thought or stack/data payloads.
- Request keys group attempts without uniqueness; same-run identical starts converge, conflicting starts fail, and distinct run IDs remain independent.
- No Claim-Gate approval or release-cache object exists; stored pass/AnswerPlan/ReleasedAnswer artifacts have no release authority.
- Representative large-table queries use the planned indexes; the gated NCP run keeps core SQL p95 below 500 ms and completes the approved four-read concurrency test without pool timeout.
- The database suite passes in the NCP-compatible Linux/amd64 Compose environment.
- The NCP preflight is runnable with an injected non-production URL and never exposes credentials.
- No raw organizer/external data, PDFs, secrets, database files, embeddings, or generated runtime artifacts are staged.

## 10. Verification Map

```text
Operator bootstrap
  -> NCP capability probe
       -> group-role layout OR direct-user layout
  -> extension/UTF-8/UTC preflight
  -> Alembic 0001..0005
  -> object/ACL manifest
  -> migration downgrade/upgrade (disposable DB only)

Dataset build
  -> building rows
  -> validation run + four readiness manifests
  -> atomic active pointer
  -> start_request_run locks/captures active dataset
       -> same run + same input: converge
       -> same run + different input: REQUEST_RUN_CONFLICT
       -> different run + same request: independent attempt

Financial lineage
  Source -> Observation/Relation/Document -> Evidence origin
       -> origin kinds requiring exactly one matching row
       -> policy/scope/exclusion kinds requiring zero origin rows
  Evidence -> Calculation DAG -> AtomicClaim -> ClaimSupport
       -> cutoff/type/version/XOR/deferred-cycle failures

Runtime artifacts
  Stage 01 Pydantic validation
  -> canonical UTF-8 JSON text
  -> protected DB append
       -> derived JSONB + SHA-256
       -> normalized Evidence/Calculation/Claim references
       -> byte-equivalent retry convergence
       -> conflicting contract ID rejection
  -> processing finish
       -> no Claim-Gate approval and no release cache in Stage 02

Performance/portability
  100k aliases + 250k relations + 250k observations
  -> index-plan assertions locally
  -> five warmups + 30 NCP measurements
  -> four concurrent reads, pool_size=5, max_overflow=0
  -> core SQL p95 <= 500 ms and zero pool timeouts
  -> Linux/amd64 locked container gate
```

Minimum acceptance coverage:

| Area | Minimum proof set | Isolation |
| --- | ---: | --- |
| Stage 01 regression | 224 existing contract tests + deterministic 14-schema export | host and Linux/amd64 image |
| Tagged values | every scalar tag, empty/homogeneous/mixed tuple, and at least 12 invalid wire-shape families | rollback DB plus direct SQL |
| Request start | inactive/stale dataset, cutoff/deadline, identical conflict pair, divergent conflict pair, and independent retry pair | two committed connections |
| Dataset activation | incomplete readiness, bad manifests, one activation, replacement activation, and concurrent first activation | disposable committed DB |
| Evidence origins | three required-origin kinds × matching/wrong/missing cases, plus three zero-origin kinds | deferred constraint forced and commit |
| Calculation/Claim | empty inputs, 2-node/3-node cycles, rank/aggregate completeness, object/value XOR, support XOR, cross-version scope | rollback plus committed deferred tests |
| Concurrent idempotency | Source, Evidence, and request artifact: same/same and same/different pairs | two committed connections per case |
| Permissions | migration/build/runtime allow/deny matrix, protected-routine owner/search-path/ACL checks, no parent-delete bypass | role-switched disposable DB and authorized NCP DB |
| Migration drift | base→head→base→head, Alembic metadata check, function/view/trigger/CHECK/ACL manifest mutations | disposable DB |
| Performance | five representative lookup families plus four-read pool test | local plan shape and gated NCP latency |

## 11. What Already Exists

- Frozen Stage 01 Pydantic contracts, canonical JSON/hash helpers, tagged-value encoders/decoders, JSON Schema exporter, and 224 passing contract tests.
- `requirements/contracts.lock`, `.dockerignore`, and `docker/contracts.Dockerfile` verified on NCP Ubuntu/Linux-amd64 at the frozen Stage 01 commit.
- Approved seven-schema physical direction, three-store/five-layer architecture, 2026-07-11 cutoff, failure/disposition policy, and NCP PostgreSQL target sizing.
- Stage 02 Tasks 1-7 have implemented the PostgreSQL harness, Alembic revisions `0001`-`0005`, lossless Evidence repositories, request-run lifecycle, and immutable runtime-artifact persistence. No migration has been applied to the actual NCP Cloud DB.

## 12. Explicitly Not in Scope

- Organizer workbook or approved external-data ingestion, correction, or publication.
- Fuseki RDF/SHACL projection, SPARQL execution, embedding-model selection, vector generation, or ANN indexes.
- Financial filtering/ranking/normalization/similarity algorithms and expected-question evaluation.
- Intent Resolver, Orchestrator, Capability Executors, Verifier implementation, Answer Composer, Claim Gate Registry, Renderer, verified response cache, FastAPI, and public NCP endpoint.
- Production NCP provisioning, credentials, firewall changes, Load Balancer, monitoring, backup execution, or production downgrade.
- Data-retention deletion jobs, partitioning, Redis, OpenSearch, or a second SQL database.

## 13. Stage 03 Handoff

Stage 03 may begin only after Stage 02 is implemented, verified, reviewed, and explicitly approved. It will:

1. profile the four organizer masters without modifying them;
2. define source-to-catalog/observation/relation mappings and missingness rules;
3. load synthetic tests first, then approved local/Object Storage source data into a `building` dataset version;
4. generate SourceRecord and EvidenceRecord lineage for every answerable field;
5. validate row counts, identifiers, duplicates, units, currency, dates, sentinels, and the `2026-07-11` cutoff;
6. activate the dataset only after PostgreSQL validation and the later Graph/Vector projections are ready.

Stage 03 must use the repository and migrations from this plan. It must not bypass them with ad hoc tables, mutate an active dataset, or commit the organizer's raw files.

## GSTACK REVIEW REPORT

**Review date:** 2026-08-18

**Review-time result:** No unresolved design blocker remained, and implementation still required the explicit Stage 02 scope/implementation approval gate in `HARNESS.md`. That gate was subsequently approved; the current implementation state is recorded at the top of this plan and in `docs/planning/STATUS.md`.

The final review approved nineteen choices: full scope split into Stage 02A/02B; observed NCP permission probing; persistence UUIDs distinct from contract IDs; exact Evidence-origin cardinality; Source creation before document FKs in migration `0003`; Stage 01 Pydantic validation authority; active-dataset capture at request start; a separate storage lock and exact container digest; no DB codec; two-tier DB test isolation; shared tagged-value parity corpus; real two-connection idempotency; four-read bounded concurrency; hardened `SECURITY DEFINER` routines; request/run retry separation; canonical text with DB-derived JSONB/hash; a persistence-only artifact model map; no cascading deletes; and processing completion separated from future release authorization.

No project task-ledger file was found that requires migration into this plan. The only observed-state gates are deliberate: Task 1 must record the real non-production NCP role capability before Task 2 permission DDL, and must resolve the exact Linux/amd64 PostgreSQL image digest before committing Compose. Neither gate permits an implementation guess or a production mutation.

A fresh-eyes self-review covered scope, type names, migration ordering, failure modes, and placeholder scans. A delegated outside-voice agent was not invoked because this session's active collaboration policy prohibits spawning agents without an explicit user request.
