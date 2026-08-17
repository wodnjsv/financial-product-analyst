# Stage 02 PostgreSQL Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-08-17

**Status:** Proposed Stage 02 plan; implementation starts only after the Stage 01 completion gate and explicit user approval

**Goal:** Implement the PostgreSQL 15 physical storage boundary for the seven approved logical schemas, preserve the Stage 01 contract IDs and immutable artifacts without renaming public interfaces, and prove that the migrations and persistence layer run in an NCP-compatible Linux/amd64 environment.

**Architecture:** PostgreSQL is the authoritative store for normalized catalog facts, observations, relation history, document metadata, search projections, evidence lineage, and request artifacts. SQLAlchemy Core defines the application-side table metadata, Alembic owns ordered DDL changes, and Psycopg 3 supplies asynchronous runtime connections. Financial source records and Claim lineage are normalized; JSONB is restricted to tagged contract scalar values and immutable request-artifact payloads. Graph and Vector consumers remain projections bound to PostgreSQL IDs and a single `dataset_version`.

**Tech Stack:** Python 3.12, PostgreSQL 15, SQLAlchemy 2.x Core, Alembic 1.x, Psycopg 3.x, pgvector, `pg_trgm`, `unaccent`, `pg_stat_statements`, `pgcrypto`, pytest 8.x, pytest-asyncio, Docker Compose, Linux/amd64.

**Authoritative design references:**

- [Planning Harness](../HARNESS.md)
- [Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md)
- [Evidence, Verification, and Rendering](../architecture/EVIDENCE_VERIFICATION_AND_RENDERING.md)
- [NCP Deployment Architecture](../architecture/NCP_DEPLOYMENT_ARCHITECTURE.md)
- [Repository Data Policy](../decisions/ADR-0002-repository-data-policy.md)
- [Bounded LLM and Capability Execution](../decisions/ADR-0005-bounded-llm-typed-capability-execution.md)
- [Failure and Disposition Policy](../decisions/ADR-0006-separate-disposition-and-bound-recovery.md)
- [Normalized Evidence Ledger](../decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md)
- [Stage 01 Runtime Contracts plan](2026-08-17-stage-01-runtime-contracts-implementation-plan.md)

## 1. Entry Gate

Do not start Stage 02 implementation until Stage 01 has been implemented and all of these commands pass from a clean task branch based on the latest `main`:

```bash
python -m pytest tests/contracts -q
python scripts/export_contract_schemas.py --check
docker build --platform linux/amd64 -f docker/contracts.Dockerfile -t financial-agent-contracts:stage-01 .
docker run --rm --platform linux/amd64 financial-agent-contracts:stage-01
git status --short
```

The Stage 01 exported JSON Schemas and these public symbols are frozen inputs:

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

Stage 02 may add persistence-only scope columns and association tables. It must not rename a contract field, change a contract Enum, relax contract validation, or turn a contract model into an ORM model.

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

1. start an empty PostgreSQL 15 instance that matches the required NCP extensions;
2. migrate it from zero to the Alembic head and back to zero without manual SQL edits;
3. create and activate a synthetic `2026-07-11-v1` dataset only after every required store-ready flag is true;
4. persist and reload Stage 01 Source, Evidence, Calculation, Claim, support, and runtime artifacts without losing IDs, numeric precision, dates, or type information;
5. prove database constraints for version isolation, cutoff status, typed values, Claim support XOR, immutable artifacts, and idempotent released-answer caching;
6. run the same checks in a Linux/amd64 container and against an explicitly configured non-production NCP Cloud DB instance.

## 3. Non-Goals

- Do not read, transform, or load organizer workbooks in this stage.
- Do not collect FRED, KRX, ECOS, fund-manager, index-provider, or other external data.
- Do not activate an external source that has not passed the source-approval process.
- Do not implement Graph RDF generation, SHACL validation, Fuseki loading, SPARQL queries, or Graph traversal.
- Do not select an embedding model or create a dimension-specific ANN index. This stage installs pgvector and creates a model registry plus storage table only.
- Do not implement product filtering, ranking, return normalization, exchange-rate conversion, similarity scoring, or other financial calculations.
- Do not implement the HyperCLOVA X roles, Orchestrator, Verifier, Renderer, FastAPI, or public `GET /answer` endpoint.
- Do not provision NCP VPCs, accounts, passwords, endpoints, HA, backups, or public networking from repository code.
- Do not introduce table partitioning, a message broker, Redis, OpenSearch, a second SQL database, or an ORM entity layer.
- Do not commit organizer data, PDFs, local database volumes, `.env` files, NCP identifiers, credentials, generated embeddings, or runtime artifacts.

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
- released answer idempotency: `(request_key, dataset_version)`.

This preserves Stage 01 IDs without assuming that a request-local `claim_id` is globally unique.

### 4.3 Normalized lineage plus bounded JSONB

Normalize input Evidence, calculation dependencies, exclusions, population filters, qualifiers, and Claim supports into association tables. Use JSONB only for:

- a scalar or tuple value accompanied by an explicit value-type tag; and
- a complete immutable Stage 01 runtime artifact accompanied by its schema version and SHA-256 hash.

Do not store Evidence or calculation ID arrays only inside JSONB. The database must enforce their foreign keys.

### 4.4 Preserve after-cutoff records for rejection

The fixed dataset cutoff is enforced on `operations.dataset_version.cutoff_date`. A source record with an `applicable_date`, `published_at`, `available_at`, or `vintage_date` after `2026-07-11` may be stored only with `cutoff_status='after_cutoff'` so the Verifier can explain its rejection. It must not appear in the safe eligible-Evidence view and must never support a released Claim.

Do not add a blanket `date <= cutoff` CHECK to Evidence. That would erase the distinction between “not collected” and “collected but ineligible because it is future data.”

### 4.5 No premature partitioning or ANN index

At the approved initial scale, composite B-tree, partial, GIN trigram, and foreign-key indexes are sufficient. PostgreSQL partitioning would complicate foreign keys and migrations before measurements justify it. pgvector is installed now, but its ANN index is deferred until the embedding model, vector dimensions, and measured recall/latency are approved.

## 5. Logical-to-Physical Storage Map

| Schema | Physical table | Purpose and key constraints |
| --- | --- | --- |
| `operations` | `dataset_version` | Dataset manifest, fixed cutoff, lifecycle, readiness flags, manifest hash; PK `dataset_version` |
| `operations` | `active_dataset` | Singleton pointer to the one active version; activation requires PostgreSQL, Graph, Vector, and evidence readiness |
| `operations` | `request_run` | One execution attempt, original question, deadline, outcome axes, and timing; PK `run_id` |
| `operations` | `request_artifact` | Immutable Stage 01 contract JSON, artifact type, schema version, producer, model/prompt metadata, hash |
| `operations` | `artifact_evidence_ref` | Artifact-to-Evidence references with stable ordinal and FK |
| `operations` | `artifact_calculation_ref` | Artifact-to-Calculation references with stable ordinal and FK |
| `operations` | `artifact_claim_ref` | Artifact-to-Claim references with stable ordinal and FK |
| `operations` | `release_cache` | One immutable released response per `request_key + dataset_version` |
| `catalog` | `entity` | Versioned product, security, company, institution, index, and theme identities |
| `catalog` | `product` | Product family and common identity fields; one-to-one subtype of entity |
| `catalog` | `security` | Security type and stable security identity fields; one-to-one subtype |
| `catalog` | `institution` | Publisher, issuer, manager, exchange, and regulator types; one-to-one subtype |
| `catalog` | `identifier` | Scheme/value identifiers with validity and primary flag |
| `catalog` | `alias` | Original and normalized names with validity; trigram indexed |
| `relation` | `relation_record` | Versioned subject-predicate-object edge and validity; Graph projection authority |
| `observation` | `metric_definition` | Registered metric meaning, scalar type, semantic family, and definition version |
| `observation` | `observation_record` | Typed entity- or relation-level value, status, period, unit, currency, and dates |
| `document` | `document_record` | Official document identity, source, object key, checksum, and temporal fields |
| `document` | `document_chunk` | Parent-aware page/section/sentence chunk and exact text hash |
| `search` | `embedding_model` | Approved model/version, dimension, distance metric, activation state |
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
7. Every Calculation has at least one Evidence input or prior Calculation dependency. Ranking requires population and tie-break rows; aggregation requires population.
8. Every Claim has exactly one object or non-null value, except approved qualifier-only `data_limitation` and `policy_boundary` Claims.
9. Every Claim support row points to exactly one Evidence or Calculation. A Calculation support must be from the same run; Evidence must be from the run's dataset.
10. Source, Evidence, Calculation, Claim, support, and request-artifact rows are append-only. Corrections create a new ID, hash, run, or dataset version.
11. Dataset rows may be edited only while `status='building'`. Lifecycle may move forward but cannot return an active or retired dataset to building.
12. `active_dataset` can point only to a dataset whose four readiness flags are true and whose cutoff equals `2026-07-11`.
13. A request's deadline satisfies `created_at < deadline_at <= created_at + interval '55 seconds'`.
14. Artifact indexed columns must equal the same metadata inside the validated JSON payload before insert.
15. No raw model chain-of-thought, credential, or authentication header has a persistence field.

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
└─ postgres.compose.yml
docs/
└─ runbooks/
   └─ ncp-postgresql-bootstrap.md
scripts/
├─ db_preflight.py
└─ verify_database_migrations.py
src/
└─ financial_agent/
   └─ db/
      ├─ __init__.py
      ├─ codec.py
      ├─ config.py
      ├─ engine.py
      ├─ metadata.py
      ├─ repositories/
      │  ├─ __init__.py
      │  ├─ artifacts.py
      │  └─ evidence.py
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
│  ├─ test_database_config.py
│  ├─ test_evidence_repository.py
│  ├─ test_evidence_schema.py
│  ├─ test_fact_document_search_schema.py
│  ├─ test_foundation_migration.py
│  ├─ test_migration_cycle.py
│  └─ test_ncp_preflight.py
└─ fixtures/
   └─ db/
      └─ synthetic_dataset.py
```

---

### Task 1: Add the database toolchain and isolated PostgreSQL test harness

**Files:**

- Modify: `pyproject.toml`
- Create: `src/financial_agent/db/__init__.py`
- Create: `src/financial_agent/db/config.py`
- Create: `src/financial_agent/db/engine.py`
- Create: `src/financial_agent/db/metadata.py`
- Create: `tests/db/__init__.py`
- Create: `tests/db/conftest.py`
- Create: `tests/db/test_database_config.py`
- Create: `docker/postgres.compose.yml`

**Interfaces:**

- `DatabaseConfig.from_env(variable="FINANCIAL_AGENT_DATABASE_URL")`
- `create_database_engine(config: DatabaseConfig) -> AsyncEngine`
- `metadata: sqlalchemy.MetaData`
- pytest marker `postgres` for tests that require a disposable PostgreSQL instance

- [ ] **Step 1: Write failing configuration tests**

Test that the database URL is mandatory, only PostgreSQL URLs are accepted, the URL is never included in `repr(config)`, pool timeouts are positive, and no NCP host/account/password default exists.

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

- [ ] **Step 2: Add the minimum dependencies**

Add compatible bounded ranges rather than unbounded latest versions:

```toml
dependencies = [
  "pydantic>=2.8,<3",
  "SQLAlchemy>=2.0,<3",
  "alembic>=1.13,<2",
  "psycopg[binary]>=3.2,<4",
  "pgvector>=0.3,<1",
]

[project.optional-dependencies]
dev = [
  "jsonschema>=4.23,<5",
  "pytest>=8.3,<9",
  "pytest-asyncio>=0.24,<1",
]
```

Preserve every Stage 01 dependency and tool setting.

- [ ] **Step 3: Implement connection configuration and naming metadata**

`DatabaseConfig` owns URL, pool size, max overflow, connect timeout, statement timeout, and application name. The engine must set UTC and an application name on connection. Use SQLAlchemy naming conventions for primary keys, foreign keys, unique constraints, checks, and indexes so Alembic names are deterministic.

Do not create a global engine at import time. Tests and the future API create and dispose engines explicitly.

- [ ] **Step 4: Create the disposable PostgreSQL 15 service**

`docker/postgres.compose.yml` must:

- use a pgvector image compatible with PostgreSQL 15;
- run on `linux/amd64`;
- enable `shared_preload_libraries=pg_stat_statements`;
- expose only a local development port selected through `${FINANCIAL_AGENT_TEST_DB_PORT:-55432}`;
- use synthetic local-only credentials declared in the compose file;
- include a `pg_isready` health check;
- store data in a named Docker volume that remains ignored by Git.

Do not reuse this password or public port in NCP.

- [ ] **Step 5: Implement the shared PostgreSQL fixture**

`tests/db/conftest.py` must read `FINANCIAL_AGENT_TEST_DATABASE_URL`, skip only tests marked `ncp_integration` when their explicit URL is absent, and fail ordinary database tests with an actionable start command when local PostgreSQL is unavailable. Each test gets a transaction or freshly migrated database and leaves no row state behind.

- [ ] **Step 6: Run the focused tests**

```bash
python -m pytest tests/db/test_database_config.py -v
docker compose -f docker/postgres.compose.yml config
```

Expected: configuration tests pass and Compose resolves without a secret-bearing host path.

- [ ] **Step 7: Commit the database harness**

```bash
git add pyproject.toml docker/postgres.compose.yml src/financial_agent/db tests/db/__init__.py tests/db/conftest.py tests/db/test_database_config.py
git diff --cached --check
git diff --cached
git commit -m "build: add postgres test harness"
```

### Task 2: Create extensions, logical schemas, and atomic dataset activation

**Files:**

- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_database_foundation.py`
- Create: `src/financial_agent/db/schema/__init__.py`
- Create: `src/financial_agent/db/schema/operations.py`
- Create: `tests/db/test_foundation_migration.py`

**Interfaces:**

- Alembic head begins at revision `0001`.
- `operations.dataset_version`
- `operations.active_dataset`
- `operations.request_run`
- database function `operations.activate_dataset(text)`
- database trigger function `operations.reject_nonbuilding_dataset_mutation()`

- [ ] **Step 1: Write failing foundation tests**

Cover all of these cases:

```python
REQUIRED_SCHEMAS = {
    "catalog", "observation", "relation", "document",
    "search", "evidence", "operations",
}

REQUIRED_EXTENSIONS = {
    "vector", "pg_trgm", "unaccent", "pg_stat_statements", "pgcrypto"
}
```

- PostgreSQL major version is exactly 15 in the local compatibility suite.
- Every required schema and extension exists after `alembic upgrade head`.
- `cutoff_date != date(2026, 7, 11)` is rejected.
- a malformed `manifest_hash` is rejected.
- activation fails when any readiness flag is false.
- activation succeeds transactionally when all readiness flags are true.
- activating a second version replaces the singleton pointer and retires the prior active version.
- an active or retired version cannot transition back to building.
- a request deadline equal to 55 seconds after creation is accepted, while 56 seconds is rejected.
- a request deadline before or equal to creation is rejected by the ordering constraint.
- execution outcome, verification status, and answer disposition remain separate nullable columns.
- a failed execution cannot store an answer disposition, and no raw chain-of-thought column exists.

- [ ] **Step 2: Define the dataset tables**

`operations.dataset_version` uses these columns:

| Column | Type and rule |
| --- | --- |
| `dataset_version` | `TEXT PRIMARY KEY` |
| `cutoff_date` | `DATE NOT NULL CHECK = DATE '2026-07-11'` |
| `status` | `TEXT CHECK IN ('building','validated','active','retired','failed')` |
| `manifest_hash` | `CHAR(64)` lowercase SHA-256 check |
| `previous_dataset_version` | nullable self-FK |
| `postgres_ready` | boolean, default false |
| `graph_ready` | boolean, default false |
| `vector_ready` | boolean, default false |
| `evidence_ready` | boolean, default false |
| `created_at` | `TIMESTAMPTZ NOT NULL` |
| `validated_at` | nullable `TIMESTAMPTZ` |
| `activated_at` | nullable `TIMESTAMPTZ` |

`operations.active_dataset` has a boolean singleton key constrained to `true`, one dataset FK, and `activated_at`. The activation function locks the pointer row and both dataset-version rows, verifies readiness and state, retires the old version, activates the new version, and updates the pointer in one transaction. `reject_nonbuilding_dataset_mutation()` is a reusable trigger applied by later migrations to versioned catalog, fact, relation, document, and search rows.

Add a partial unique index on `dataset_version.status='active'` so direct SQL cannot create two active versions. Application and data-build code may activate a version only through `operations.activate_dataset(text)`.

`operations.request_run` is also created in revision `0001` because request-scoped Calculations and Claims in revision `0004` must reference it. It stores `run_id`, `request_key`, `question_id`, the original `question`, `schema_version`, `dataset_version`, `cutoff_date`, `created_at`, `deadline_at`, `finished_at`, the three separate outcome axes, HTTP status, and stable failure code. A composite FK to a unique `(dataset_version, cutoff_date)` pair guarantees that the request cutoff matches the dataset. Its deadline CHECK is `created_at < deadline_at AND deadline_at <= created_at + interval '55 seconds'`. It has no field for raw Chain-of-Thought.

Dataset transitions are exactly `building -> validated|failed`, `validated -> active|failed`, and `active -> retired`; `retired` and `failed` are terminal. The activation function is the only path from validated to active.

- [ ] **Step 3: Implement the migration environment**

Configure Alembic to import the shared metadata, compare server defaults and types, include all seven named schemas, and reject an empty or non-PostgreSQL URL. Migration `0001` creates the required extensions using the migration account, then schemas, tables, constraints, transition trigger, and activation function. Runtime application credentials must not need extension or schema-creation privileges.

- [ ] **Step 4: Run the migration and focused tests**

```bash
docker compose -f docker/postgres.compose.yml up -d --wait postgres
FINANCIAL_AGENT_DATABASE_URL="postgresql+psycopg://financial_agent_test:financial_agent_test@localhost:55432/financial_agent_test" \
  python -m alembic upgrade head
FINANCIAL_AGENT_TEST_DATABASE_URL="postgresql+psycopg://financial_agent_test:financial_agent_test@localhost:55432/financial_agent_test" \
  python -m pytest tests/db/test_foundation_migration.py -v
```

Expected: revision `0001` is current and every constraint case passes.

- [ ] **Step 5: Commit the foundation**

```bash
git add alembic.ini alembic src/financial_agent/db/schema tests/db/test_foundation_migration.py
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

- [ ] **Step 1: Write failing catalog constraints**

Tests must prove:

- the same `entity_id` may exist in two dataset versions, but only once per version;
- subtype rows cannot point to an entity in another dataset version;
- `product_family` accepts only `domestic_bond`, `domestic_etf`, `overseas_etf`, or `public_fund`;
- a product row can attach only to an entity whose `entity_type='product'` through a deferred constraint trigger;
- `(dataset_version, scheme, identifier_value)` is unique, so one identifier cannot be reassigned inside one immutable dataset version;
- only one primary identifier exists per entity and scheme;
- aliases preserve original text and separately store normalized text;
- modifying versioned catalog rows after dataset validation is rejected.

- [ ] **Step 2: Define catalog columns and keys**

Use composite `(dataset_version, entity_id)` keys. `entity_type` permits `product`, `security`, `company`, `institution`, `index`, and `theme`. `entity` stores canonical name, normalized name, record hash, and creation time. Subtype tables store only stable identity fields required before ingestion mapping:

- `product`: product family and nullable primary currency;
- `security`: security kind and nullable ticker/ISIN display fields;
- `institution`: institution kind.

Do not copy all four organizer master columns into `catalog.product`. Stage 03 maps identity attributes, observations, and relations deliberately after profiling each source field.

Apply `operations.reject_nonbuilding_dataset_mutation()` to all versioned catalog tables. Rows remain editable while their dataset is building and become immutable as soon as it is validated.

- [ ] **Step 3: Define identifier and alias indexes**

Add:

- B-tree indexes for product family and entity type;
- one unique and one lookup index for identifier scheme/value;
- a partial unique index for primary identifier;
- B-tree lookup on normalized alias;
- `GIN (... gin_trgm_ops)` on normalized canonical and alias names.

- [ ] **Step 4: Generate and review migration `0002`**

Use Alembic autogenerate with explicit revision ID, then inspect every schema, FK target, check, and index. Do not accept an unnamed constraint or an FK that omits `dataset_version`.

```bash
python -m alembic revision --autogenerate --rev-id 0002 -m "catalog schema"
python -m alembic upgrade head
python -m alembic check
```

- [ ] **Step 5: Run catalog tests**

```bash
python -m pytest tests/db/test_catalog_schema.py -v
```

- [ ] **Step 6: Commit the catalog schema**

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
- Create: `tests/db/test_fact_document_search_schema.py`

**Interfaces:**

- `relation.relation_record`
- `observation.metric_definition`, `observation.observation_record`
- `document.document_record`, `document.document_chunk`
- `search.embedding_model`, `search.document_embedding`

- [ ] **Step 1: Write failing relation and observation tests**

Tests must reject:

- a relation whose subject and object come from different dataset versions;
- `valid_to < valid_from`;
- an observation with both an entity target and a relation target;
- an observation with neither target;
- a present observation with zero or two typed value columns;
- a missing/placeholder/unavailable/inapplicable observation with any typed value;
- an unregistered metric or a value kind that conflicts with the metric definition.

Tests must accept a true numeric zero with `value_status='zero'`; zero is not missing.

- [ ] **Step 2: Define relation and observation storage**

`relation_record` stores versioned relation ID, subject entity, predicate ID, object entity, validity dates, record hash, and creation time.

`metric_definition` stores metric ID, semantic family, value kind, definition version, default unit, and description. `observation_record` stores:

- exactly one target: entity or relation;
- value status: `present`, `zero`, `missing`, `placeholder`, `unavailable`, `inapplicable`, `unknown`;
- exactly one of `numeric_value NUMERIC(38,12)`, `text_value`, `boolean_value`, `date_value`, or `timestamp_value` when present/zero;
- `unit`, `currency`, period start/end, applicable date, published/available/vintage times;
- a reason code for non-present values and a record hash.

Do not infer a missing currency, date, period, or unit in the table layer.

Use a deferred `observation.validate_metric_value_kind()` trigger to compare each row with `metric_definition`. Apply `operations.reject_nonbuilding_dataset_mutation()` to relation and observation rows after creation.

- [ ] **Step 3: Write failing document and embedding tests**

Verify parent chunks stay within one document/version, sentence and page ranges are ordered, document checksum and chunk text hashes are valid SHA-256, embedding rows reference the exact chunk content hash, and the stored vector dimension equals the registered model dimension.

- [ ] **Step 4: Define document and search storage**

`document_record` references a SourceRecord-compatible source ID only after migration `0004` adds that FK; migration `0003` initially stores the source ID and creates an index. This avoids a cyclic migration dependency without weakening the final head.

`document_chunk` stores parent chunk, ordinal, page, section, sentence bounds, exact text, normalized search text, and hashes. Add a trigram GIN index to normalized search text; do not claim that PostgreSQL's built-in parser solves Korean full-text morphology.

`embedding_model` records model ID, model version, dimension, distance metric, approval state, and activation time. `document_embedding` uses pgvector's `vector` type, records the explicit dimension and content hash, and verifies it with a trigger. Do not create HNSW or IVFFlat indexes in this stage.

Apply `operations.reject_nonbuilding_dataset_mutation()` to versioned document and embedding rows. Metric and embedding-model registries are definition registries and use explicit version/approval changes rather than dataset-row mutation.

- [ ] **Step 5: Generate, inspect, and run migration `0003`**

```bash
python -m alembic revision --autogenerate --rev-id 0003 -m "fact document search schemas"
python -m alembic upgrade head
python -m alembic check
python -m pytest tests/db/test_fact_document_search_schema.py -v
```

- [ ] **Step 6: Commit fact and search storage**

```bash
git add alembic/versions/0003_fact_document_search_schemas.py src/financial_agent/db/schema tests/db/test_fact_document_search_schema.py
git diff --cached --check
git diff --cached
git commit -m "feat: add fact and search storage"
```

### Task 5: Implement the normalized Evidence ledger

**Files:**

- Create: `alembic/versions/0004_evidence_ledger.py`
- Create: `src/financial_agent/db/schema/evidence.py`
- Modify: `src/financial_agent/db/schema/document.py`
- Create: `tests/db/test_evidence_schema.py`

**Interfaces:**

- All `evidence.*` tables in the storage map
- read-only view `evidence.claim_eligible_evidence`
- append-only trigger function `evidence.reject_mutation()`

- [ ] **Step 1: Write failing source and Evidence tests**

Cover:

- a SourceRecord is unique by dataset and source ID;
- source checksums and record hashes require 64 lowercase hexadecimal characters;
- an Evidence row cannot reference a Source from another dataset;
- `valid_to >= valid_from` when both exist;
- `query_scope` requires `scope_completeness`, and other Evidence kinds reject it;
- an after-cutoff Evidence row is stored with `cutoff_status='after_cutoff'`;
- after-cutoff, unknown-vintage, inapplicable, or source-ineligible rows do not appear in `claim_eligible_evidence`;
- all SourceLocator components round-trip without one opaque locator JSON object.

- [ ] **Step 2: Define tagged scalar storage**

For Evidence raw/normalized values, calculation results/parameters, and Claim values/qualifiers, use a nullable JSONB value paired with one of:

```text
null, string, integer, decimal, boolean, date, datetime,
string_tuple, integer_tuple, decimal_tuple, boolean_tuple,
date_tuple, datetime_tuple, mixed_tuple
```

The Python codec, not PostgreSQL numeric guessing, reconstructs the Stage 01 scalar type. Decimal values serialize as canonical strings and are validated before returning to contracts.

The persistence-only representation is a frozen `TaggedValue(value_type: ValueType, value: JsonValue)` object. `JsonValue` is limited to JSON scalars and tuples/lists of JSON scalars; mappings and floats are rejected. These types live in `db/codec.py`, not in the Stage 01 public contracts.

- [ ] **Step 3: Define Source, Evidence, and origin links**

`source_record` includes all Stage 01 `SourceRecord` fields plus `dataset_version`. Its publisher uses a composite FK to a same-version catalog institution/entity, with a deferred type check that permits only `entity_type='institution'`. `evidence_record` includes all Stage 01 fields, explicit SourceLocator columns, tagged raw/normalized values, and the composite Source FK.

Add separate origin tables for observation, relation, and document chunk. Each origin table has a composite FK on both sides and a primary key on the Evidence identity. Repository validation allows at most one source-record origin for an Evidence row unless a later ADR permits combined origin kinds.

Update `document.py` at this point so migration `0004` also adds the deferred document-to-source composite FK promised by migration `0003`.

- [ ] **Step 4: Write failing Calculation and Claim tests**

Verify:

- a Calculation with no input Evidence or dependency is rejected;
- dependency rows stay in the same run and cannot self-reference;
- ranking requires one population row, at least one population filter, and a tie-break rule;
- aggregation requires one population row;
- every population scope references Evidence from the request dataset;
- ordinal values are unique and nonnegative for every association;
- AtomicClaim object/value XOR and qualifier-only exceptions match Stage 01;
- ClaimSupport accepts exactly one target and enforces same-run/same-dataset scope;
- update and delete attempts on Source, Evidence, Calculation, Claim, qualifier, and support rows fail.

- [ ] **Step 5: Define normalized Calculation and Claim tables**

Do not place arrays of input IDs, filter IDs, exclusions, qualifiers, or support IDs in `calculation_record` or `atomic_claim`. Store their order in the association tables listed in section 5.

Use deferred constraints where a complete aggregate invariant spans multiple rows. The repository inserts a Calculation or Claim and all child rows in one transaction, then explicitly validates aggregate invariants before commit. Database functions provide the same checks so a non-repository client cannot commit an incomplete ranking or unsupported Claim.

- [ ] **Step 6: Add indexes and the safe Evidence view**

At minimum add:

- Evidence `(dataset_version, subject_id, predicate_id, applicable_date DESC)`;
- Evidence `(dataset_version, source_id)` and cutoff-status partial indexes;
- relation `(dataset_version, predicate_id, subject_id, object_id)`;
- observation target/metric/date indexes;
- Calculation and Claim hash indexes within run scope;
- ClaimSupport Evidence and Calculation reverse-lookup indexes.

The safe view joins `source_record` and returns only `eligible_for_claim=true` plus `cutoff_status='eligible'`. It is a retrieval convenience, not a substitute for the later deterministic Verifier.

- [ ] **Step 7: Generate, inspect, and run migration `0004`**

```bash
python -m alembic revision --autogenerate --rev-id 0004 -m "evidence ledger"
python -m alembic upgrade head
python -m alembic check
python -m pytest tests/db/test_evidence_schema.py -v
```

- [ ] **Step 8: Commit the Evidence DDL**

```bash
git add alembic/versions/0004_evidence_ledger.py src/financial_agent/db/schema/document.py src/financial_agent/db/schema/evidence.py tests/db/test_evidence_schema.py
git diff --cached --check
git diff --cached
git commit -m "feat: add normalized evidence ledger"
```

### Task 6: Implement lossless Evidence persistence adapters

**Files:**

- Create: `src/financial_agent/db/codec.py`
- Create: `src/financial_agent/db/repositories/__init__.py`
- Create: `src/financial_agent/db/repositories/evidence.py`
- Create: `tests/db/test_evidence_repository.py`

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
```

```python
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
        self, scope: RequestScope, claim: AtomicClaim
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

`RequestScope` is a persistence-only frozen dataclass containing `request_key`, `run_id`, and `dataset_version`. It does not replace RuntimeArtifact metadata.

- [ ] **Step 1: Write failing tagged-value codec tests**

Round-trip all Stage 01 scalar types, including:

- `Decimal("0")`, `Decimal("0.000100000000")`, and a large AUM value;
- `date(2026, 7, 11)` and a UTC datetime;
- strings that look like dates or decimals but must remain strings;
- booleans without converting them to integers;
- `None` and homogeneous/mixed tuples.

Reject float input, naive datetime, non-UTC datetime, an unknown type tag, and a tag/value mismatch.

- [ ] **Step 2: Implement the minimal codec**

Expose only `encode_contract_value(value) -> TaggedValue` and `decode_contract_value(tagged) -> ContractValue`. Reuse Stage 01 canonical JSON rules. Do not create a general-purpose serializer framework.

- [ ] **Step 3: Write failing repository round-trip tests**

Using only synthetic fixtures, append and reload:

- a claim-eligible official source and direct Evidence;
- an after-cutoff Evidence retained for rejection;
- a ranking Calculation with ordered Evidence inputs, exclusions, population filters, and tie-break;
- an AtomicClaim with ordered qualifiers;
- direct and Calculation ClaimSupport rows.

Compare reconstructed Pydantic objects for exact equality. Verify an attempted second insert with the same ID but different hash fails; identical retries may return the existing row only after byte-equivalent canonical comparison.

- [ ] **Step 4: Implement transactional append and load methods**

Use SQLAlchemy Core statements and `AsyncConnection.begin()`. Repository methods have no update or delete operation. Insert all parent and association rows in one transaction. Catch unique conflicts only to implement deterministic identical-retry behavior; never silently accept a different payload under an existing ID.

- [ ] **Step 5: Run codec and repository tests**

```bash
python -m pytest tests/db/test_evidence_repository.py -v
```

- [ ] **Step 6: Commit persistence adapters**

```bash
git add src/financial_agent/db/codec.py src/financial_agent/db/repositories tests/db/test_evidence_repository.py
git diff --cached --check
git diff --cached
git commit -m "feat: persist evidence contracts losslessly"
```

### Task 7: Persist immutable runtime artifacts and idempotent released answers

**Files:**

- Create: `alembic/versions/0005_request_artifacts.py`
- Modify: `src/financial_agent/db/schema/operations.py`
- Create: `src/financial_agent/db/repositories/artifacts.py`
- Create: `tests/db/test_artifact_repository.py`

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


class RequestArtifactRepository:
    async def start_run(self, context: RequestContext) -> None: ...
    async def append(self, artifact_type: ArtifactType, artifact: RuntimeArtifact) -> str: ...
    async def get(self, run_id: str, artifact_id: str) -> RuntimeArtifact: ...
    async def cache_released(self, released: ReleasedAnswer) -> None: ...
    async def get_cached_release(
        self, request_key: str, dataset_version: str
    ) -> ReleasedAnswer | None: ...
```

- [ ] **Step 1: Write failing request-run and artifact repository tests**

The request-run table already exists from revision `0001`; these tests exercise it through the new repository boundary. Verify:

- deadline equality at 55 seconds is accepted;
- `2026-08-17T00:00:56Z` for a `2026-08-17T00:00:00Z` start is rejected;
- a deadline before or equal to creation is rejected for its own ordering rule;
- dataset version and cutoff must match the referenced dataset;
- `ExecutionOutcome`, `VerificationStatus`, and `AnswerDisposition` remain separate nullable columns;
- a failed execution cannot store an answer disposition;
- no column exists for raw chain-of-thought.

- [ ] **Step 2: Define runtime artifact tables**

`request_artifact` stores indexed metadata plus the exact contract JSONB and canonical hash. `artifact_type` permits only the Stage 01 top-level artifacts. It also has nullable `model_id` and `prompt_version`; repository rules require them for model-produced QueryPlan and AnswerPlan artifacts and reject them for deterministic ToolResult/Verification artifacts.

The three reference tables preserve explicit Evidence, Calculation, and Claim FKs with stable ordinals. They are populated from the validated artifact's ID collections, not caller-supplied unrelated lists.

- [ ] **Step 3: Write failing immutability and idempotency tests**

Test that:

- indexed `schema_version`, `request_key`, `run_id`, `dataset_version`, `cutoff_date`, `producer`, and `created_at` must equal payload metadata;
- unknown artifact types and extra JSON fields are rejected through the Stage 01 schema registry;
- update/delete on an artifact or reference fails;
- the same canonical artifact retry returns the existing artifact ID;
- the same artifact ID with different bytes fails;
- `release_cache` accepts the first verified ReleasedAnswer and never overwrites it;
- repeated organizer retries read the same response hash for the same request key and dataset version;
- a 5xx execution result cannot be stored as a released answer.

- [ ] **Step 4: Implement artifact schema and repository**

The repository validates payloads through the Stage 01 model registry before opening the insert transaction. It derives canonical bytes and hash itself. `artifact_id` is the contract's own top-level ID when available and otherwise a deterministic type-prefixed hash ID.

Do not log artifact payloads at error level. Redact the database URL and preserve only stable reason codes in raised persistence errors.

- [ ] **Step 5: Generate and run migration `0005`**

```bash
python -m alembic revision --autogenerate --rev-id 0005 -m "request artifacts"
python -m alembic upgrade head
python -m alembic check
python -m pytest tests/db/test_artifact_repository.py -v
```

- [ ] **Step 6: Commit artifact persistence**

```bash
git add alembic/versions/0005_request_artifacts.py src/financial_agent/db/schema/operations.py src/financial_agent/db/repositories/artifacts.py tests/db/test_artifact_repository.py
git diff --cached --check
git diff --cached
git commit -m "feat: persist immutable request artifacts"
```

### Task 8: Prove migration reversibility and NCP Cloud DB compatibility

**Files:**

- Create: `scripts/db_preflight.py`
- Create: `scripts/verify_database_migrations.py`
- Create: `tests/db/test_migration_cycle.py`
- Create: `tests/db/test_ncp_preflight.py`
- Create: `docker/database-check.Dockerfile`
- Modify: `docker/postgres.compose.yml`
- Create: `docs/runbooks/ncp-postgresql-bootstrap.md`

**Interfaces:**

- `python scripts/db_preflight.py --database-url-env <ENV_NAME>`
- `python scripts/verify_database_migrations.py`
- pytest marker `ncp_integration`

- [ ] **Step 1: Write failing migration-cycle tests**

On a disposable empty database:

1. upgrade from base to head;
2. inspect all tables, checks, FKs, indexes, views, functions, and triggers;
3. run `alembic check` and require no metadata drift;
4. downgrade from head to base;
5. verify all seven application schemas and owned objects are removed while PostgreSQL itself remains healthy;
6. upgrade to head again and rerun the foundation tests.

- [ ] **Step 2: Write failing preflight tests**

The preflight must check and report, without printing credentials:

- PostgreSQL major version 15;
- UTC database/session timezone;
- required extensions and their installed versions;
- all seven schemas;
- Alembic head equality;
- fixed dataset cutoff;
- active-dataset readiness consistency;
- ability to begin, roll back, and execute a parameterized query;
- absence of public-schema application tables other than Alembic's `alembic_version` bookkeeping table;
- pgvector dimension function availability;
- `pg_stat_statements` availability.

It exits nonzero with stable codes such as `DB_VERSION_MISMATCH`, `MISSING_EXTENSION`, `MIGRATION_BEHIND`, or `ACTIVE_DATASET_INCONSISTENT`.

- [ ] **Step 3: Implement the local Linux/amd64 database-check image**

`database-check.Dockerfile` installs the package and database test dependencies, copies no source data, and runs migrations plus `tests/db`. Add a Compose `db-check` service that connects to the PostgreSQL service over the Compose network.

```bash
docker compose -f docker/postgres.compose.yml build db-check
docker compose -f docker/postgres.compose.yml up -d --wait postgres
docker compose -f docker/postgres.compose.yml run --rm db-check
```

Expected: migrations and all non-NCP database tests pass on Linux/amd64.

- [ ] **Step 4: Document the NCP bootstrap boundary**

`docs/runbooks/ncp-postgresql-bootstrap.md` must state:

- Cloud DB PostgreSQL 15, private subnet, 4 vCPU/16 GB, SSD, final-evaluation HA and daily 7–14 day backups;
- migration credentials and runtime credentials are separate NCP-managed secrets/environment variables;
- only the migration account provisions extensions and DDL;
- PostgreSQL port 5432 is allowed only from API and data-build servers;
- the database is never made public for the organizer; only the `/answer` API is public;
- how to run preflight and migrations from the private build/API subnet;
- how to take a logical backup plus manifest after final dataset activation;
- no endpoint, account ID, password, or private address is committed.

- [ ] **Step 5: Run the gated non-production NCP integration test**

This step requires explicit user authorization and a disposable or non-production NCP database. It is skipped in ordinary local CI.

```bash
FINANCIAL_AGENT_DATABASE_URL="<injected-NCP-migration-url>" \
  python -m alembic upgrade head
FINANCIAL_AGENT_NCP_TEST_DATABASE_URL="<injected-NCP-runtime-test-url>" \
  python -m pytest -m ncp_integration tests/db/test_ncp_preflight.py -v
```

Neither command may print its URL. The migration may create only the approved extensions, Alembic bookkeeping table, and objects under the seven application schemas in the approved test database. Do not run a downgrade against a shared or production NCP database.

- [ ] **Step 6: Run the complete Stage 02 verification**

```bash
python -m pytest tests/contracts tests/db -q
python scripts/export_contract_schemas.py --check
python scripts/verify_database_migrations.py
docker compose -f docker/postgres.compose.yml run --rm db-check
git diff --check
git status --short --ignored
```

Verify manually that no organizer workbook/PDF, file under `data/`, database volume, `.env`, credential, NCP identifier, local dump, Parquet file, embedding, cache, or runtime artifact is staged.

- [ ] **Step 7: Commit the portability proof and runbook**

```bash
git add docker/database-check.Dockerfile docker/postgres.compose.yml docs/runbooks/ncp-postgresql-bootstrap.md scripts/db_preflight.py scripts/verify_database_migrations.py tests/db/test_migration_cycle.py tests/db/test_ncp_preflight.py
git diff --cached --check
git diff --cached
git status --short
git commit -m "test: verify postgres storage on ncp baseline"
```

## 8. Stage 02 Completion Gate

Stage 02 is complete only when fresh output proves all of the following:

- Stage 01 contract tests and deterministic schema export still pass unchanged.
- A blank PostgreSQL 15 database upgrades to Alembic head and downgrades to base without manual intervention.
- `alembic check` reports no difference between SQLAlchemy metadata and the migration head.
- All seven logical schemas, required extensions, constraints, views, triggers, and indexes exist.
- The active dataset cannot be switched until PostgreSQL, Graph, Vector, and Evidence readiness flags are all true.
- Catalog, relations, observations, documents, Sources, and Evidence cannot cross dataset versions through a valid FK.
- Zero, missing, placeholder, unavailable, and inapplicable values remain distinguishable.
- After-cutoff Evidence can be retained for rejection but is absent from the claim-eligible view.
- Ranking and aggregation inputs, populations, filters, exclusions, dependencies, and tie-breaks are normalized and reproducible.
- Claim support enforces exactly one Evidence or Calculation target.
- Evidence and request artifacts round-trip to the exact Stage 01 Pydantic contracts, including Decimal/date/datetime types.
- Append-only data rejects updates and deletes; a conflicting duplicate ID never silently overwrites prior content.
- Released-answer caching is idempotent for `(request_key, dataset_version)` and does not cache 5xx failures.
- The database suite passes in the NCP-compatible Linux/amd64 Compose environment.
- The NCP preflight is runnable with an injected non-production URL and never exposes credentials.
- No raw organizer/external data, PDFs, secrets, database files, embeddings, or generated runtime artifacts are staged.

## 9. Stage 03 Handoff

Stage 03 may begin only after Stage 02 is implemented, verified, reviewed, and explicitly approved. It will:

1. profile the four organizer masters without modifying them;
2. define source-to-catalog/observation/relation mappings and missingness rules;
3. load synthetic tests first, then approved local/Object Storage source data into a `building` dataset version;
4. generate SourceRecord and EvidenceRecord lineage for every answerable field;
5. validate row counts, identifiers, duplicates, units, currency, dates, sentinels, and the `2026-07-11` cutoff;
6. activate the dataset only after PostgreSQL validation and the later Graph/Vector projections are ready.

Stage 03 must use the repository and migrations from this plan. It must not bypass them with ad hoc tables, mutate an active dataset, or commit the organizer's raw files.
