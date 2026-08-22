# Stage 03A Organizer Master Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-08-20

**Status:** In progress — Task 9 local implementation verified; private Object Storage and Linux/amd64 gates pending

**Goal:** Normalize the four organizer workbooks into a reproducible, evidence-backed, non-active PostgreSQL `building` dataset while preserving every source row's disposition and the `2026-07-11` cutoff.

**Architecture:** Read immutable local or private Object Storage XLSX files through one verified streaming boundary, pass rows to four explicit pure mapper modules, and write typed batches through one `DatasetBuildWriter` into the frozen Stage 02 schema. Produce one canonical BuildReport; do not add a mapping DSL, generic plugin framework, new database migration, Graph/Vector projection, or final NCP activation.

**Tech Stack:** Python 3.12, Pydantic 2.13.4, openpyxl read-only mode, boto3 S3-compatible client, SQLAlchemy 2.0 async, psycopg 3, PostgreSQL 15.17, pytest 8, NCP Private Object Storage and Cloud DB for PostgreSQL.

**Spec:** [Stage 03 Lean Data Ingestion Design](../specs/2026-08-20-stage-03-lean-data-ingestion-design.md)

## Global Constraints

- The exact cutoff date is `2026-07-11`.
- Organizer master values win when an external source later conflicts on the same evaluation field.
- Never modify, save over, commit, or print raw organizer workbooks or row values.
- Never commit a file under `data/`, a generated BuildReport containing real data, an Object Storage object, a database dump, a Parquet file, a credential, or an NCP account identifier.
- Stage 01 tagged values and canonical JSON/hash helpers are the only contract value boundary.
- Stage 02 Alembic `0001`~`0005`, SQLAlchemy metadata, role grants, dataset lifecycle, Source/Evidence ledger, and exact retry semantics are frozen inputs.
- Do not add Alembic `0006` in this plan. Stop and request a separately approved storage design if a tested mandatory fact cannot fit the existing schema.
- Use `fa_build` for all ingestion writes and reject active or validated dataset targets.
- Create Evidence only for answerable normalized facts, with exact workbook/sheet/row/column/record-key locators.
- For answerable catalog names and identifiers, emit the companion text observation required by the Stage 02 Evidence-origin boundary; do not add catalog-origin storage.
- Keep deterministic IDs, normalization, missingness, filtering, and counts outside an LLM.
- Stage 03A ends with a disposable, non-active `building` verification dataset. The final NCP dataset is rebuilt in Stage 03C after all approved source manifests are frozen.
- Real-data and NCP tests are opt-in and must emit only aggregate counts and stable error codes.

## Assumptions, Outcome, and Non-Goals

### Assumptions

- The four organizer data workbooks and four schema workbooks remain available in the user's local ignored `data/` directory.
- The existing reference documents correctly record baseline row counts, field counts, natural-key behavior, ETF/ETN splits, and public-fund duplication structure.
- A private NCP Object Storage bucket and credentials will be supplied only for the explicit Task 9 integration run.
- A disposable PostgreSQL 15 database with the Stage 02 migrations can be provided through `FINANCIAL_AGENT_TEST_DATABASE_URL`.
- The final field-level meanings are not inferred from column names alone; Task 1 records and approves every source field before mapper code begins.

### Intended outcome

The same four source bytes, mapping versions, and parser version produce the same dataset manifest, stable IDs, normalized payload hashes, aggregate counts, Evidence locators, and BuildReport. Missing and sentinel values remain distinguishable, public-fund duplicate grains are not silently aggregated, retries converge only on byte-equivalent payloads, and the resulting dataset remains non-active.

### Non-goals

- No external official API, ETF holdings, exchange rate, corporate relationship, or identifier-master ingestion.
- No official document parsing, chunking, RDF, SHACL, Fuseki, embedding, pgvector population, or dataset activation.
- No retrieval, ranking, return normalization, similarity scoring, LLM, API, or answer rendering.
- No correction or imputation of organizer data and no name-only cross-source entity merge.
- No generic ingestion SDK, configuration DSL, web UI, cleanup job, or production scheduler.

### Verifiable success criteria

1. The source-to-target matrix accounts for all 207 source fields and receives explicit approval before mapper code.
2. Synthetic workbooks prove read-only streaming, exact headers, source-specific sentinels, deterministic IDs, and accepted/limited/quarantined accounting.
3. PostgreSQL tests prove FK-ordered batch writes, exact retry convergence, payload conflict rollback, Evidence origin cardinality, and role/state restrictions.
4. The gated local run confirms `42,394 + 1,734 + 5,646 + 95,619 = 145,393` raw rows and the documented key/distribution invariants.
5. The gated Object Storage run proves local bytes, downloaded bytes, and SourceRecord checksums are identical.
6. The final Stage 03A BuildReport passes, contains no raw values, and the verification dataset remains `building` and absent from `active_dataset`.
7. Contract, database, ingestion, schema-export, compile, dependency, diff, secret, and data-path checks all pass before commit.

## File Responsibility Map

| File | Responsibility |
| --- | --- |
| `docs/planning/specs/organizer-master-field-matrix.md` | approved classification and target of all 207 fields |
| `src/financial_agent/ingestion/models.py` | `SourceSpec`, `MappingIssue`, `MappedRow`, `BuildReport` only |
| `src/financial_agent/ingestion/sources.py` | local/Object Storage materialization, SHA-256, XLSX read-only row iterator |
| `src/financial_agent/ingestion/mapping/common.py` | deterministic ID, name, Decimal, date, Boolean, status, Evidence helpers |
| `src/financial_agent/ingestion/mapping/domestic_bond.py` | `PRBD01N001` explicit field coverage and row mapping |
| `src/financial_agent/ingestion/mapping/domestic_etp.py` | `PREF01N001` explicit ETF/ETN mapping |
| `src/financial_agent/ingestion/mapping/overseas_etp.py` | `PREF02N001` explicit ETF/ETN mapping |
| `src/financial_agent/ingestion/mapping/public_fund.py` | `PRFD01N001` attribute-row, share-class, representative-fund mapping |
| `src/financial_agent/ingestion/writer.py` | one FK-ordered, exact-conflict, batched Stage 02 writer |
| `src/financial_agent/ingestion/pipeline.py` | source verification, mapper dispatch, row accounting, BuildReport orchestration |
| `src/financial_agent/ingestion/cli.py` | sanitized `validate`, `load`, and `verify-object-storage` commands |
| `tests/fixtures/ingestion.py` | generated synthetic XLSX fixtures with no real product data |
| `tests/ingestion/` | four bounded test groups: mapping, workbook, PostgreSQL, real/NCP acceptance, including its own disposable-DB fixture |
| `requirements/ingestion.lock` | exact CPython 3.12 ingestion verification environment |
| `docker/ingestion-check.Dockerfile` | Linux/amd64 reproducibility without raw data in the image |

---

### Task 1: Freeze the 207-field source-to-target matrix

**Files:**

- Create: `docs/planning/specs/organizer-master-field-matrix.md`
- Read: `docs/reference/domestic-bond-master.md`
- Read: `docs/reference/domestic-etf-master.md`
- Read: `docs/reference/overseas-etf-master.md`
- Read: `docs/reference/public-fund-master.md`
- Read only: the four ignored schema workbooks under the local `data/` directory

**Interfaces:**

- Consumes: exact workbook headers and the Stage 02 catalog/observation/relation/evidence columns.
- Produces: four approved tables whose rows define `source_field`, `source_type`, `classification`, `target`, `value_status_rule`, `date_or_period`, `unit`, `currency`, `evidence`, and `reason`.

- [x] **Step 1: Extract and compare the schema and data headers without copying rows**

Use openpyxl read-only mode in an ephemeral command. Emit only table ID, ordered header names, header count, and whether the schema/data headers agree. Do not redirect the raw workbook contents to a tracked file.

Expected counts:

```text
PRBD01N001  40
PREF01N001  73
PREF02N001  49
PRFD01N001  45
TOTAL       207
```

- [x] **Step 2: Write one explicit matrix row for every field**

Use exactly these classification values:

```text
identifier | catalog | relation | observation | evidence_only | ignored
```

For `observation`, specify one existing Stage 02 value kind and one stable metric ID/version. For `relation`, use one approved ontology predicate only when the source meaning supports it. For `ignored`, provide a fixed reason such as `DUPLICATE_RUNTIME_VALUE`, `NO_TRUSTED_TIME_BASIS`, `UNDEFINED_SOURCE_CODE`, or `NOT_ANSWERABLE`.

- [x] **Step 3: Record the source-grain and identifier invariants**

The document must contain these exact baselines:

```text
PRBD01N001: PD_NO unique and non-null across 42,394 rows
PREF01N001: 1,202 ETF + 532 ETN; pd_itm_no query identity
PREF02N001: 5,587 ETF + 59 ETN; pd_itm_no identity; ISIN not unique
PRFD01N001: 95,619 attribute rows; 11,139 itm_no; 2,626 valid representative groups
```

- [x] **Step 4: Check for unsafe inferred semantics**

Search the matrix and confirm:

```text
- no missing Boolean is mapped to false;
- no placeholder index text creates an Index entity;
- no overseas ETF 1-day zero series is marked usable return;
- no public-fund representative sentinel creates a representative fund;
- no source-local institution name is marked cross-source canonical;
- no file extraction date replaces a field-specific applicable date.
```

- [x] **Step 5: Obtain explicit user approval of the matrix**

Stop after presenting counts by classification and all `evidence_only`, `ignored`, `unknown`, and relation decisions. Do not change files under `src/`, `tests/`, `requirements/`, or `docker/` until the user approves this matrix.

- [x] **Step 6: Commit the independently useful mapping decision**

```bash
git add docs/planning/specs/organizer-master-field-matrix.md
git diff --cached --check
git commit -m "docs: define organizer master field mappings"
```

Expected: exactly one tracked documentation file; no file under `data/` and no real row value staged.

---

### Task 2: Add the minimal ingestion models and verified source reader

**Files:**

- Create: `src/financial_agent/ingestion/__init__.py`
- Create: `src/financial_agent/ingestion/models.py`
- Create: `src/financial_agent/ingestion/sources.py`
- Create: `tests/fixtures/ingestion.py`
- Create: `tests/ingestion/__init__.py`
- Create: `tests/ingestion/test_sources.py`
- Modify: `pyproject.toml`
- Create: `requirements/ingestion.lock`

**Interfaces:**

- Produces:

```python
sha256_path(path: Path) -> str
verify_local_source(path: Path, expected_sha256: str | None = None) -> str
download_verified_object(
    client: object,
    *,
    bucket: str,
    key: str,
    expected_sha256: str,
    destination: Path,
) -> Path
verify_schema_header(path: Path, spec: SourceSpec) -> tuple[str, ...]
iter_workbook_rows(path: Path, spec: SourceSpec) -> Iterator[Mapping[str, object]]
```

- Also produces the four data models named in the spec: `SourceSpec`, `MappingIssue`, `MappedRow`, and `BuildReport`.
- Consumes later: the four mappers receive dictionaries from `iter_workbook_rows`; the pipeline receives verified paths and source hashes.

- [x] **Step 1: Write failing tests for exact models and source verification**

Add tests with these behaviors:

```python
def test_reader_rejects_changed_header(tmp_path): ...
def test_reader_rejects_unexpected_row_count(tmp_path): ...
def test_reader_preserves_zero_blank_and_string_null(tmp_path): ...
def test_local_checksum_must_match_expected(tmp_path): ...
def test_object_download_is_rehashed_instead_of_trusting_etag(tmp_path): ...
def test_source_errors_do_not_include_credentials_or_cell_values(tmp_path): ...
```

Generate XLSX files inside `tmp_path` with `openpyxl.Workbook(write_only=True)`. Use identifiers such as `SYN-BOND-001`; do not include organizer rows.

- [x] **Step 2: Run the focused test and capture the missing-module RED**

```bash
.venv/bin/python -m pytest tests/ingestion/test_sources.py -q
```

Expected: collection fails because `financial_agent.ingestion` does not exist.

- [x] **Step 3: Add bounded dependencies and an exact lock**

Add one optional extra:

```toml
ingestion = [
  "openpyxl>=3.1,<4",
  "boto3>=1.35,<2",
]
```

Also register only these new pytest markers:

```toml
"organizer_data: requires the ignored local organizer workbooks",
"object_storage: requires an explicitly configured private Object Storage target",
```

Generate `requirements/ingestion.lock` for CPython 3.12 containing the existing storage verification stack plus exact openpyxl, boto3, botocore, s3transfer, jmespath, python-dateutil, six, and et-xmlfile versions. Do not relax `requirements/contracts.lock` or `requirements/storage.lock`.

- [x] **Step 4: Implement only the four approved data models**

Follow the spec fields exactly. `BuildReport.to_json_mapping()` must convert dates to ISO text, sort source/table/issue/component keys, and return only canonical-JSON-native values accepted by `canonical_sha256`.

```python
def manifest_hash(manifest: Mapping[str, object]) -> str:
    return canonical_sha256(manifest)
```

- [x] **Step 5: Implement read-only XLSX and Object Storage verification**

Use:

```python
load_workbook(path, read_only=True, data_only=True)
```

Require the exact configured data/schema sheets and exact ordered header agreement. Count data rows while iterating; do not use worksheet `max_row` as the final authority. Object Storage reads use the configured HTTPS endpoint and download to a temporary file, then calculate SHA-256 from downloaded bytes. Convert boto3 and workbook exceptions to stable codes without preserving credential-bearing causes.

- [x] **Step 6: Run focused and existing contract tests**

```bash
.venv/bin/python -m pytest tests/ingestion/test_sources.py -q
.venv/bin/python -m pytest tests/contracts -q
.venv/bin/python -m pip check
```

Expected: all pass.

- [x] **Step 7: Commit the minimal source boundary**

```bash
git add pyproject.toml requirements/ingestion.lock \
  src/financial_agent/ingestion tests/fixtures/ingestion.py \
  tests/ingestion/__init__.py tests/ingestion/test_sources.py
git diff --cached --check
git commit -m "feat: add verified organizer source reader"
```

---

### Task 3: Implement deterministic common mapping helpers

**Files:**

- Create: `src/financial_agent/ingestion/mapping/__init__.py`
- Create: `src/financial_agent/ingestion/mapping/common.py`
- Create: `tests/ingestion/test_mapping_common.py`

**Interfaces:**

- Produces:

```python
stable_id(kind: str, source_code: str, natural_key: str) -> str
normalize_name(value: str) -> str
parse_decimal(value: object) -> Decimal | None
parse_yyyymmdd(value: object, *, sentinels: frozenset[str]) -> date | None
parse_tristate(value: object, *, true_values: frozenset[str], false_values: frozenset[str]) -> bool | None
classify_value(
    raw: object,
    *,
    missing_values: frozenset[object],
    placeholder_values: frozenset[str],
    zero_is_value: bool,
) -> tuple[str, object | None, str | None]
make_record_hash(payload: Mapping[str, object]) -> str
```

The tuple contains `value_status`, normalized value, and reason code. Do not introduce a `FieldRule`, policy object, or class hierarchy around it.

- [x] **Step 1: Write failing tests for IDs, parsing, and statuses**

Cover Unicode NFKC plus whitespace normalization, Decimal without float, YYYYMMDD, `0`, `99991231`, literal `NULL`, blank, placeholder text, tri-state Boolean, and source-local institution IDs. Assert stable IDs do not contain `dataset_version`.

- [x] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/ingestion/test_mapping_common.py -q
```

Expected: missing mapping module.

- [x] **Step 3: Implement the smallest pure helpers**

Use one fixed project UUID namespace and UUIDv5:

```python
return str(uuid5(PROJECT_NAMESPACE, f"{kind}:{source_code}:{natural_key}"))
```

Reject floats before Decimal construction. Return explicit status/reason pairs compatible with the Stage 02 `observation_record` CHECK constraint.

- [x] **Step 4: Run GREEN and mutation checks**

Temporarily including `dataset_version` in the ID input must fail the stable-across-version test. Temporarily mapping blank to zero must fail the missingness test. Restore both and rerun:

```bash
.venv/bin/python -m pytest tests/ingestion/test_mapping_common.py -q
```

- [x] **Step 5: Commit**

```bash
git add src/financial_agent/ingestion/mapping tests/ingestion/test_mapping_common.py
git diff --cached --check
git commit -m "feat: add deterministic ingestion mapping helpers"
```

---

### Task 4: Map the domestic bond master

**Files:**

- Create: `src/financial_agent/ingestion/mapping/domestic_bond.py`
- Create: `tests/ingestion/test_domestic_bond_mapping.py`

**Interfaces:**

- Consumes: approved `PRBD01N001` rows and common helpers.
- Produces:

```python
SPEC: SourceSpec
HANDLED_COLUMNS: frozenset[str]
IGNORED_COLUMNS: Mapping[str, str]
map_row(row_number: int, row: Mapping[str, object]) -> MappedRow
```

- [x] **Step 1: Write failing coverage and behavior tests**

Assert all 40 matrix fields are handled or ignored exactly once. Cover unique `PD_NO`, product/security identity, issuer as source-local institution, `issuedBy`, currency, issue/maturity dates, coupon, yield, price, duration, credit grade, buyable quantity, `NULL`, `0`, `99991231`, `000`, old update dates, and a row with missing natural key.

- [x] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/ingestion/test_domestic_bond_mapping.py -q
```

- [x] **Step 3: Implement the approved matrix literally**

Create one product entity and product row with `product_family="domestic_bond"`, one security row for the bond, identifiers for `PD_NO` and approved codes, and only officially supported relations/observations. Do not infer current purchase availability from workbook presence.

For a product name or identifier that must support a later Claim, also create the companion text observation required by the Stage 02 Evidence-origin boundary. Do not add a catalog-origin table.

- [x] **Step 4: Verify the Evidence payloads**

For every answerable field, assert locator sheet, row, column, source record key, raw representation, normalized tagged value, applicable date, mapping version, and cutoff status. Missing/inapplicable facts must not generate a present-valued Evidence.

- [x] **Step 5: Run GREEN and commit**

```bash
.venv/bin/python -m pytest tests/ingestion/test_domestic_bond_mapping.py \
  tests/ingestion/test_mapping_common.py -q
git add src/financial_agent/ingestion/mapping/domestic_bond.py \
  tests/ingestion/test_domestic_bond_mapping.py
git diff --cached --check
git commit -m "feat: map organizer domestic bonds"
```

---

### Task 5: Map the domestic ETF and ETN master

**Files:**

- Create: `src/financial_agent/ingestion/mapping/domestic_etp.py`
- Create: `tests/ingestion/test_domestic_etp_mapping.py`

**Interfaces:**

```python
SPEC: SourceSpec
HANDLED_COLUMNS: frozenset[str]
IGNORED_COLUMNS: Mapping[str, str]
map_row(row_number: int, row: Mapping[str, object]) -> MappedRow
```

These symbols cover `PREF01N001` only.

- [x] **Step 1: Write failing 73-field coverage and ETF/ETN tests**

Cover separate ETF/ETN `security_kind`, product family `domestic_etf`, `pd_itm_no`, exchange code, ISIN where valid, trade-stop meaning, sale and pension fields, risk, AUM, price, NAV, period returns, asset class, region, manager relation only where the matrix confirms it, and field-specific dates.

Include these mandatory negatives:

```text
pd_tr_yn=1 is stopped, not tradable;
missing leverage is not normal leverage;
zero/blank intraday values are not current market facts;
-100 return candidate is not silently present;
2026-07-11 extraction date is not substituted for 2026-06-15 market date.
```

- [x] **Step 2: Run RED, implement the approved matrix, then run GREEN**

```bash
.venv/bin/python -m pytest tests/ingestion/test_domestic_etp_mapping.py -q
```

Expected before implementation: missing module. Expected after implementation: pass.

- [x] **Step 3: Commit**

```bash
git add src/financial_agent/ingestion/mapping/domestic_etp.py \
  tests/ingestion/test_domestic_etp_mapping.py
git diff --cached --check
git commit -m "feat: map organizer domestic etps"
```

---

### Task 6: Map the overseas ETF and ETN master

**Files:**

- Create: `src/financial_agent/ingestion/mapping/overseas_etp.py`
- Create: `tests/ingestion/test_overseas_etp_mapping.py`

**Interfaces:**

```python
SPEC: SourceSpec
HANDLED_COLUMNS: frozenset[str]
IGNORED_COLUMNS: Mapping[str, str]
map_row(row_number: int, row: Mapping[str, object]) -> MappedRow
```

These symbols cover `PREF02N001` only.

- [x] **Step 1: Write failing 49-field coverage and basis-date tests**

Cover ETF/ETN separation, `pd_itm_no`, nonunique/missing ISIN and Lipper IDs, product versus trading currency, asset class, investment region, source-local provider/manager semantics, price, NAV, AUM, volume, and available dates.

Include these mandatory negatives:

```text
placeholder base-index sentences do not create Index entities;
all-zero one-day return does not become a usable return series;
NAV date without NAV value remains missing;
price and NAV with mismatched dates do not produce a derived premium/discount;
ru_* without a trustworthy timestamp is not labeled real-time;
missing inverse/leverage fields do not prove a normal product.
```

- [x] **Step 2: Run RED, implement, and run GREEN**

```bash
.venv/bin/python -m pytest tests/ingestion/test_overseas_etp_mapping.py -q
```

- [x] **Step 3: Commit**

```bash
git add src/financial_agent/ingestion/mapping/overseas_etp.py \
  tests/ingestion/test_overseas_etp_mapping.py
git diff --cached --check
git commit -m "feat: map organizer overseas etps"
```

---

### Task 7: Map public-fund attribute rows, share classes, and representatives

**Files:**

- Create: `src/financial_agent/ingestion/mapping/public_fund.py`
- Create: `tests/ingestion/test_public_fund_mapping.py`

**Interfaces:**

```python
SPEC: SourceSpec
HANDLED_COLUMNS: frozenset[str]
IGNORED_COLUMNS: Mapping[str, str]
map_row(row_number: int, row: Mapping[str, object]) -> MappedRow
```

These symbols cover `PRFD01N001` only.

- [x] **Step 1: Write failing 45-field coverage and three-grain tests**

Cover the raw composite key, share-class `itm_no`, representative `rptt_ksd_itm_no`, attribute-code duplication, public/private label, sale status, manager code, region, asset type, currency, hedge tri-state, risk, benchmark text, NAV/AUM, and all available return horizons.

Assert:

```text
repeated attribute rows produce one stable share-class entity;
repeated facts have the same observation/evidence identity rather than duplicate rank inputs;
representative sentinels KR0000000000 and 000000000000 create no representative entity;
hasShareClass is emitted only for a valid representative identifier;
representative-fund AUM is not calculated by summing classes;
string NULL risk and unknown code 06 remain limited/unknown;
return outliers are retained with a quality issue, not corrected or forecast.
```

- [x] **Step 2: Run RED, implement, and run GREEN**

```bash
.venv/bin/python -m pytest tests/ingestion/test_public_fund_mapping.py -q
```

- [x] **Step 3: Commit**

```bash
git add src/financial_agent/ingestion/mapping/public_fund.py \
  tests/ingestion/test_public_fund_mapping.py
git diff --cached --check
git commit -m "feat: map organizer public funds"
```

---

### Task 8: Add one exact, FK-ordered dataset build writer

**Files:**

- Create: `src/financial_agent/ingestion/writer.py`
- Create: `tests/ingestion/conftest.py`
- Create: `tests/ingestion/test_writer.py`

**Interfaces:**

- Consumes: `MappedRow`, Stage 02 SQLAlchemy Tables, `EvidenceLedgerConflict` meaning, and an `AsyncEngine` connected as `fa_build`.
- Produces:

```python
class DatasetBuildWriter:
    async def create_building_dataset(
        self, dataset_version: str, manifest_hash: str, cutoff_date: date
    ) -> None: ...

    async def write_rows(
        self, dataset_version: str, rows: Sequence[MappedRow]
    ) -> None: ...

    async def table_counts(self, dataset_version: str) -> Mapping[str, int]: ...
```

- [x] **Step 1: Write PostgreSQL RED tests before implementation**

Mark tests `@pytest.mark.postgres`. Cover:

```python
async def test_batch_writes_in_fk_order_and_links_evidence_origins(...): ...
async def test_identical_batch_retry_converges(...): ...
async def test_same_id_different_payload_rolls_back_whole_batch(...): ...
async def test_writer_rejects_nonbuilding_dataset(...): ...
async def test_runtime_role_cannot_use_writer_path(...): ...
async def test_two_connections_same_batch_converge_or_conflict_stably(...): ...
```

Create `tests/ingestion/conftest.py` with a session fixture that reads only `FINANCIAL_AGENT_TEST_DATABASE_URL`, upgrades the disposable target through the existing `alembic.ini`, and returns the migrated URL. Add an async engine fixture that disposes the engine after each test. Do not import or alter sibling `tests/db/conftest.py`.

- [x] **Step 2: Run RED**

```bash
FINANCIAL_AGENT_TEST_DATABASE_URL="$TEST_URL" \
  .venv/bin/python -m pytest tests/ingestion/test_writer.py -q
```

Expected: missing writer module.

- [x] **Step 3: Implement batched exact comparison**

Use one connection and transaction per `write_rows` call. Insert tables in the spec's FK order. For duplicate IDs, load existing rows and compare every non-generated persisted field; ignore only `created_at`. Never accept a shorter association set or silently ignore a changed qualifier/origin.

Before issuing SQL, collapse duplicate IDs inside the batch only when their entire payloads are equal. A differing duplicate in the same batch raises the same stable build conflict and writes nothing.

The default caller batch is 1,000 source rows. Do not add queues, workers, multiprocessing, COPY-specific abstractions, or a second repository hierarchy in this task.

- [x] **Step 4: Run focused GREEN and existing storage regression**

```bash
FINANCIAL_AGENT_TEST_DATABASE_URL="$TEST_URL" \
  .venv/bin/python -m pytest tests/ingestion/test_writer.py -q
FINANCIAL_AGENT_TEST_DATABASE_URL="$TEST_URL" \
  .venv/bin/python -m pytest tests/contracts tests/db -m "not performance and not ncp_integration" -q
```

- [x] **Step 5: Commit**

```bash
git add src/financial_agent/ingestion/writer.py tests/ingestion/test_writer.py
git diff --cached --check
git commit -m "feat: add organizer dataset batch writer"
```

---

### Task 9: Orchestrate the four sources and prove local/Object Storage acceptance

**Files:**

- Create: `src/financial_agent/ingestion/pipeline.py`
- Create: `src/financial_agent/ingestion/cli.py`
- Create: `tests/ingestion/test_pipeline.py`
- Create: `tests/ingestion/test_real_organizer_data.py`
- Create: `tests/ingestion/test_ncp_object_storage.py`
- Create: `docker/ingestion-check.Dockerfile`
- Modify: `pyproject.toml`
- Modify: `.dockerignore` only if a new generated ingestion artifact is not already excluded
- Modify: `docs/planning/STATUS.md`

**Interfaces:**

- Produces:

```python
async def build_organizer_dataset(
    engine: AsyncEngine,
    *,
    dataset_version: str,
    data_paths: Mapping[str, Path],
    schema_paths: Mapping[str, Path],
    data_sha256: Mapping[str, str],
    schema_sha256: Mapping[str, str],
    batch_size: int = 1000,
) -> BuildReport: ...
```

CLI commands:

```text
python -m financial_agent.ingestion.cli validate
python -m financial_agent.ingestion.cli load
python -m financial_agent.ingestion.cli verify-object-storage
```

Database URLs, bucket names, endpoint, and credentials come from named environment variables, never command-line values.

- [x] **Step 1: Write pipeline RED tests**

Cover source order independence, stable manifest sorting, exactly one disposition per row, fatal-header failure after aggregate reporting, no database row on preflight checksum failure, 1,000-row batch boundaries, source failure leaving the dataset non-active, and BuildReport raw-value redaction.

- [x] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/ingestion/test_pipeline.py -q
```

- [x] **Step 3: Implement the sequential streaming pipeline**

Use a fixed mapper registry:

```python
MAPPERS = {
    "PRBD01N001": map_domestic_bond_row,
    "PREF01N001": map_domestic_etp_row,
    "PREF02N001": map_overseas_etp_row,
    "PRFD01N001": map_public_fund_row,
}
```

Do not add dynamic imports or plugins. Verify all source checksums and headers before creating a dataset row. Stream one source at a time and one batch at a time. At completion query actual table counts, compute PostgreSQL and Evidence component hashes, and return one BuildReport. Do not call `finish_dataset_validation`, `record_dataset_readiness`, or `activate_dataset` in 03A.

- [x] **Step 4: Add sanitized CLI boundaries**

Use these environment variables:

```text
FINANCIAL_AGENT_SOURCE_ROOT
FINANCIAL_AGENT_BUILD_DATABASE_URL
FINANCIAL_AGENT_OBJECT_STORAGE_ENDPOINT
FINANCIAL_AGENT_OBJECT_STORAGE_BUCKET
FINANCIAL_AGENT_OBJECT_STORAGE_ACCESS_KEY_ID
FINANCIAL_AGENT_OBJECT_STORAGE_SECRET_ACCESS_KEY
```

On failure print only a stable code such as `SOURCE_HEADER_MISMATCH`, `SOURCE_CHECKSUM_MISMATCH`, `BUILD_PAYLOAD_CONFLICT`, or `DATABASE_UNREACHABLE`. Suppress credential-bearing exception causes.

- [x] **Step 5: Run the gated local organizer acceptance test**

The test skips when `RUN_ORGANIZER_DATA_TESTS` is not `1`. Once explicitly enabled, a missing source root or disposable database URL fails with `ORGANIZER_DATA_CONFIGURATION_MISSING` rather than silently skipping. It may print only this aggregate shape:

```text
PRBD01N001 rows=42394 fields=40
PREF01N001 rows=1734 fields=73 etf=1202 etn=532
PREF02N001 rows=5646 fields=49 etf=5587 etn=59
PRFD01N001 rows=95619 fields=45 items=11139 representatives=2626
TOTAL rows=145393
```

Run:

```bash
RUN_ORGANIZER_DATA_TESTS=1 \
FINANCIAL_AGENT_SOURCE_ROOT="$SOURCE_ROOT" \
FINANCIAL_AGENT_TEST_DATABASE_URL="$TEST_URL" \
  .venv/bin/python -m pytest tests/ingestion/test_real_organizer_data.py -q
```

Expected: pass and dataset status remains `building`.

- [ ] **Step 6: Run the explicit private Object Storage checksum test**

The test skips when `RUN_NCP_OBJECT_STORAGE_TESTS` is not `1`. Once explicitly enabled, missing Object Storage or build-database configuration fails with `OBJECT_STORAGE_CONFIGURATION_MISSING` rather than silently skipping. Upload or verify only the eight approved workbook objects, then re-read and hash the four data workbooks used by Stage 03A. Assert local, object, manifest, and SourceRecord SHA-256 equality. Never print the bucket, endpoint query, credentials, or raw object content.

```bash
RUN_NCP_OBJECT_STORAGE_TESTS=1 \
  .venv/bin/python -m pytest tests/ingestion/test_ncp_object_storage.py -q
```

- [ ] **Step 7: Verify Linux/amd64 without copying raw data into the image**

`docker/ingestion-check.Dockerfile` must install from `requirements/ingestion.lock`, copy only tracked source/tests/configuration, and run the contract plus synthetic source/mapping tests that do not require PostgreSQL. PostgreSQL integration remains a separate run supplied with the disposable test URL. `.dockerignore` must exclude `data/`, BuildReports, local object downloads, `.env*`, `.gstack/`, `.agents/`, and `.codex/`.

Build and run on the NCP Ubuntu host:

```bash
docker build --no-cache --platform linux/amd64 \
  -f docker/ingestion-check.Dockerfile \
  -t financial-agent-ingestion:stage-03a .
docker run --rm --platform linux/amd64 financial-agent-ingestion:stage-03a
```

Expected: exit code 0. Real organizer data is mounted only for the explicit acceptance command and is never part of an image layer.

- [x] **Step 8: Run final verification**

```bash
.venv/bin/python -m pytest tests/ingestion -m "not ncp_integration" -q
FINANCIAL_AGENT_TEST_DATABASE_URL="$TEST_URL" \
  .venv/bin/python -m pytest tests/contracts tests/db tests/ingestion \
  -m "not performance and not ncp_integration" -q
.venv/bin/python scripts/export_contract_schemas.py --check
.venv/bin/python scripts/export_database_objects.py --check
.venv/bin/python -m compileall -q src scripts tests
.venv/bin/python -m pip check
git diff --check
```

Inspect:

```bash
git status --short
git diff --stat
git diff -- . ':!docs/planning/tasks/2026-08-20-stage-03a-organizer-master-ingestion-plan.md'
```

Verify that no `data/` file, workbook, raw row, real BuildReport, database URL, Object Storage identifier, `.env`, dump, Parquet, embedding, cache, or runtime output is tracked or staged.

- [x] **Step 9: Update status and commit Stage 03A**

Record exact test counts, the safe aggregate real-data counts, the NCP Object Storage checksum result, the Linux/amd64 result, and any intentionally unrun gate in `STATUS.md`. Do not mark all of Stage 03 complete and do not mark the data version active.

```bash
git add src/financial_agent/ingestion tests/ingestion tests/fixtures/ingestion.py \
  requirements/ingestion.lock docker/ingestion-check.Dockerfile \
  pyproject.toml .dockerignore docs/planning/STATUS.md
git diff --cached --check
git diff --cached
git status --short
git commit -m "feat: ingest organizer product masters"
```

Expected: one verified Stage 03A deliverable; `.gstack/` and all user-owned untracked state remain untouched.

## Self-Review Checklist

- [x] Every design requirement maps to one Task and one verification command.
- [x] Task 1 blocks mapper implementation until all field meanings are explicit and approved.
- [x] Type and function names are identical across Tasks 2~9.
- [x] There is only one new service class, `DatasetBuildWriter`.
- [x] No task adds DDL, Graph, Vector, external official data, documents, LLM, API, activation, or cleanup.
- [x] The dataset manifest is computed before dataset creation and never mutated.
- [x] 03A and 03B cannot partially mutate the final NCP dataset; 03C owns the final rebuild.
- [x] Raw workbooks and real BuildReports never enter Git or Docker layers.
- [x] All required real/NCP operations are gated, sanitized, and explicitly reported if unrun.
