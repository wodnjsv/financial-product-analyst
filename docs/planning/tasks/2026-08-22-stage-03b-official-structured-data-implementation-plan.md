# Stage 03B Official Structured Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-08-22

**Status:** Approved for staged implementation on 2026-08-22; Task 4 bounded KRX PDF holdings is now prioritized before Task 5

**Goal:** Preserve and normalize the minimum official identifiers, domestic and overseas ETF holdings, compatible KRX price/NAV observations, and ECOS exchange rates required by the approved evaluation questions, while enforcing the `2026-07-11` information cutoff and explicit coverage limits.

**Architecture:** Capture exact official response bytes or files into NCP Private Object Storage before normalization, verify one immutable source-specific snapshot manifest, map each approved source through a small explicit module into the frozen Stage 02 catalog/relation/observation/Evidence tables, and reproduce a combined Stage 03A+03B dataset only in disposable PostgreSQL `building` versions. Do not build a generic connector framework, do not add Alembic `0006`, and do not mutate the final NCP PostgreSQL dataset before Stage 03C.

**Tech Stack:** Python 3.12, standard-library `urllib`/`json`/`csv`/`zipfile`, boto3 S3-compatible client, SQLAlchemy 2.0 async, psycopg 3, PostgreSQL 15.17, pytest 8, KRX official data, ECOS `731Y001`, SEC Series/Class Report, SEC Form N-PORT datasets, NCP Private Object Storage.

**Spec:** [Stage 03B Official Structured Data Design](../specs/2026-08-22-stage-03b-official-structured-data-design.md), [ADR-0014](../decisions/ADR-0014-use-bounded-official-source-snapshots.md)

## Global Constraints

- The exact cutoff is `2026-07-11`; a later collection date never replaces an official applicable, publication, availability, or vintage date.
- Preserve official raw bytes before mapping. ETag is metadata, not a SHA-256 substitute.
- Never commit official raw responses, downloaded archives, real snapshot manifests, bucket names, NCP identifiers, API keys, credentials, database URLs, or real BuildReports.
- The organizer masters remain authoritative for the same evaluation field. External values enrich or validate them and never silently overwrite them.
- Never resolve entities by name alone. Exact identifiers or an explicitly approved compound key are required.
- Preserve missing coverage as unknown. `NOT_COVERED` never means a product has no holding.
- Only a complete publisher-defined snapshot may produce `scope_completeness='closed_world'`; every partial, unresolved, or missing scope is `bounded_unknown`.
- Stage 01 tagged values and canonical hashing remain the only polymorphic JSON boundary.
- Stage 02 migrations `0001` through `0005`, role grants, immutable dataset manifest, writer conflict behavior, and Evidence-origin constraints are frozen inputs.
- Because catalog identifiers and aliases have no direct Evidence-origin table, every answerable official identifier or alias must also emit the reviewed companion text Observation and Evidence required by the Stage 02 boundary.
- Stop and request a separately approved ADR if a mandatory tested fact cannot fit Stage 02. Do not create migration `0006` inside this plan.
- Use one sequential source pipeline and the existing `DatasetBuildWriter`. Do not add queues, workers, a scheduler, a mapping DSL, a plugin loader, or a data-lake abstraction.
- Use `fa_build` for ingestion. Reject active and validated dataset targets.
- Stage 03B may upload official raw objects to Private Object Storage, but it may write normalized rows only to a disposable PostgreSQL `building` dataset.
- The final NCP PostgreSQL rebuild, validation, and activation remain Stage 03C responsibilities.
- Real official-source, Object Storage, and database tests are opt-in, print only aggregate counts and stable codes, and suppress credential-bearing exception causes.
- An unselected asset-manager file is not an implementation target. Add one only after its publisher, URL or file-delivery path, full/partial scope, dates, fields, and usage terms receive a separate source-matrix approval.

## Assumptions, Outcome, and Non-Goals

### Assumptions

- Stage 03A commit `c2065fe` or its merged successor remains the organizer-ingestion baseline.
- The four organizer workbooks remain immutable in private Object Storage and locally available only for gated rebuild verification.
- The user can provision KRX and ECOS API credentials when their live access gates are reached.
- SEC's public 2026 Q2 Form N-PORT archive is an eligible candidate because it was officially published before the cutoff, but each filing still requires its own report and filing/public-availability checks.
- The KRX Data Marketplace exposes ETF PDF data, but its exact historical export endpoint, access method, header, and publisher-defined completeness must be observed and approved in Task 1. They are not inferred in this plan.
- The Stage 03B combined build can start from empty disposable PostgreSQL and reproduce Stage 03A rows before adding external rows.

### Intended outcome

The same organizer bytes plus the same approved external object manifests, parser versions, and mapping versions produce the same immutable dataset manifest, stable catalog IDs, relations, observations, Evidence locators, coverage counts, and component hashes. Domestic ETF holdings can answer membership questions only after a reproducible official historical holdings export passes the separate Task 4 gate; overseas holdings answers disclose the bounded SEC or manager-covered population; eligible KRX and ECOS observations retain their actual dates.

### Non-goals

- No official document parsing, chunking, OCR, risk-factor extraction, news, or web-search fallback.
- No FRED data and no mixing of exchange-rate definitions.
- No return normalization, currency conversion execution, AUM ranking, ETF similarity scoring, recommendation, or answer composition.
- No Graph/RDF, SHACL, keyword index, embeddings, pgvector population, or search projection.
- No universal issuer/company master. Create `securityOfCompany` only when an approved source supplies a strong company identifier.
- No guarantee of full overseas ETF coverage.
- No automatic reconciliation of conflicting official values and no averaging.
- No final NCP PostgreSQL load, validation, activation, deployment, or evaluation API work.

### Verifiable success criteria

1. The exact source-access and source-to-target matrix is approved before any official mapper is implemented.
2. Every real official object has a sanitized manifest, SHA-256, byte count, official dates, parser/mapping version, and private object key.
3. After-cutoff, schema-drift, checksum, pagination, and archive-safety mutations fail before any database write.
4. Identity tests prove exact-key linking, ambiguous-key quarantine, duplicate-ID preservation, and no name-only merge.
5. ECOS FX and SEC Series/Class plus N-PORT synthetic fixtures map deterministically into existing Stage 02 tables with exact Evidence; KRX holdings and KRX market product facts do so only after their explicit source and crosswalk gates pass.
6. Coverage tests distinguish `COVERED`, `PARTIALLY_COVERED`, `NOT_COVERED`, and `CONFLICT`, and never convert missing coverage into absence.
7. A disposable combined Stage 03A+03B rebuild creates one immutable manifest before the first database row, retries exactly, remains `building`, and is absent from `active_dataset`.
8. Gated live-source tests verify official bytes and aggregate source invariants without printing secrets or raw facts.
9. Gated Object Storage tests prove each captured/downloaded object hash equals its manifest entry and the SourceRecord checksum equals the canonical snapshot-manifest hash.
10. Contract, ingestion, PostgreSQL, schema export, compile, dependency, Linux/amd64, diff, secret, and forbidden-data checks pass before the Stage 03B branch is considered complete.

## File Responsibility Map

| File | Responsibility |
| --- | --- |
| `docs/planning/specs/stage-03b-official-source-field-matrix.md` | exact publisher, access path, dates, fields, target, coverage, and conflict decisions |
| `src/financial_agent/ingestion/official/models.py` | immutable object/snapshot/coverage and exact-resolution value objects only |
| `src/financial_agent/ingestion/official/snapshot.py` | bounded HTTP capture, canonical manifest, private Object Storage byte verification |
| `src/financial_agent/ingestion/official/identity.py` | exact identifier and approved compound-key resolution; never fuzzy name matching |
| `src/financial_agent/ingestion/official/krx_identity.py` | KRX KOSPI/KOSDAQ security codes and aliases approved in the field matrix |
| `src/financial_agent/ingestion/official/krx_holdings.py` | one approved KRX ETF PDF export format and holdings mapper |
| `src/financial_agent/ingestion/official/krx_market.py` | KRX ETF daily close/NAV and approved security identifiers |
| `src/financial_agent/ingestion/official/ecos_fx.py` | ECOS `731Y001` four-item response and FX observations |
| `src/financial_agent/ingestion/official/sec_series_class.py` | SEC Series/Class Report and exact `(CIK, Class Ticker) -> Series ID` crosswalk |
| `src/financial_agent/ingestion/official/sec_nport.py` | bounded 2026 Q2 archive extraction, TSV joins, eligible filing selection, holdings mapping |
| `src/financial_agent/ingestion/official_pipeline.py` | combined immutable manifest and sequential Stage 03A+03B `building` rebuild |
| `src/financial_agent/ingestion/pipeline.py` | minimally expose reusable Stage 03A preflight/write phases without changing Stage 03A output |
| `src/financial_agent/ingestion/cli.py` | sanitized official capture, validate, load, and Object Storage commands |
| `tests/fixtures/official_ingestion.py` | generated synthetic KRX, ECOS, and N-PORT fixtures only |
| `tests/ingestion/test_official_*.py` | source-specific synthetic and PostgreSQL verification |
| `tests/ingestion/test_real_official_sources.py` | explicitly gated official-source access and aggregate invariants |
| `tests/ingestion/test_ncp_official_object_storage.py` | explicitly gated private Object Storage byte and manifest verification |
| `docker/ingestion-check.Dockerfile` | existing raw-data-free Linux/amd64 verification, extended only for synthetic official tests |
| `pyproject.toml` | add only the `official_data` marker if needed; no new runtime dependency |
| `requirements/ingestion.lock` | unchanged unless the existing dependency set cannot run a verified requirement |
| `docs/planning/STATUS.md` | Stage 03B completion evidence and intentionally unrun gates |

---

### Task 1: Freeze exact source access and field mappings

**Files:**

- Create: `docs/planning/specs/stage-03b-official-source-field-matrix.md`
- Read: `docs/planning/specs/official-api-source-matrix.md`
- Read: `docs/planning/specs/authoritative-data-requirements.md`
- Read: the official KRX Open API and Data Marketplace descriptions
- Read: the official ECOS API response documentation for `731Y001`
- Read: the SEC Form N-PORT dataset page and official readme

**Produces:** one approved row per consumed source field with these columns:

```text
source_code
publisher
access_method
object_name
source_field
source_type
source_grain
classification
target
identifier_or_metric
unit
currency
applicable_date_rule
published_at_rule
available_at_rule
vintage_date_rule
coverage_rule
conflict_rule
evidence_locator
usage_note
```

- [x] **Step 1: Record exact fixed candidates without credentials**

Record the approved candidate boundaries:

```text
KRX_ETF_DAILY
  official service: ETF daily trading information
  required fields: BAS_DD, ISU_CD, ISU_NM, TDD_CLSPRC, NAV

KRX_KOSPI_BASIC / KRX_KOSDAQ_BASIC
  official service: market issue basic information
  required fields: freeze the exact official issue-code and alias fields
                   observed in the Task 1 access response

ECOS_731Y001
  item codes: 0000001, 0000002, 0000003, 0000053
  required fields: STAT_CODE, item code/name, UNIT_NAME, TIME, DATA_VALUE

SEC_NPORT_2026Q2
  required files: SUBMISSION.tsv, REGISTRANT.tsv,
                  FUND_REPORTED_INFO.tsv, FUND_REPORTED_HOLDING.tsv,
                  IDENTIFIERS.tsv

SEC_SERIES_CLASS_20260601
  required fields: CIK, Series ID, Series Name,
                   Class ID, Class Name, Class Ticker
```

Do not put an API key, authenticated URL, bucket, account, or live object key in the document.

- [x] **Step 2: Perform the KRX ETF PDF access probe and stop on ambiguity**

Using the user's authorized KRX access, inspect only the official historical ETF PDF export for an eligible date. Record endpoint or console export name, authentication placement, pagination or file boundary, ordered header, weight unit, quantity/value definitions, cash/derivative representation, and whether the publisher defines the file as a complete portfolio.

Emit only header and aggregate metadata during the probe. Do not commit the response.

If the exact historical export cannot be reproduced, mark `KRX_ETF_PDF` as `ACCESS_NOT_CONFIRMED` and block Task 4. Do not invent a private KRX endpoint. KRX market and ECOS/SEC tasks may proceed independently.

Result: `KRX_ETF_PDF=ACCESS_NOT_CONFIRMED`. Task 4 is blocked. The KRX market response may be captured, but product-level price/NAV mapping is separately blocked until the approved ETF basic export supplies a strong crosswalk.

- [x] **Step 3: Freeze identifier linking rules**

Approve only these initial product crosswalks:

```text
domestic organizer ETF -> KRX ETF:
  unique exact (normalized official name, official listing date)
  using the still-required KRX ETF basic export

overseas organizer ETF -> SEC fund series:
  unique exact organizer (CIK, normalized ticker) -> SEC class
  then exact SEC class -> SEC series

SEC holding -> security:
  unique valid ISIN, else unique valid CUSIP,
  else snapshot-local HOLDING_ID
```

Ticker alone, product name alone, issuer name, and embedding similarity are forbidden. The domestic compound key must be bijective in both directions; otherwise the product remains unresolved. The observed `PREF01_PD_ITM_NO` values matched KRX issue codes zero times and are not a KRX crosswalk.

- [x] **Step 4: Freeze dates and authority per field**

For every field, record how `applicable_date`, `published_at`, and `available_at` are derived from official metadata. A field without a defensible publication or availability rule cannot be eligible for a historical Claim; map it as `unknown_vintage` or exclude it with an explicit reason.

- [x] **Step 5: Freeze coverage and conflict rules**

The matrix must state whether each holdings source is publisher-complete or partial. It must also say which key identifies one portfolio snapshot, which rows may be aggregated, and which official conflicts become `source_value_conflict`.

- [x] **Step 6: Obtain explicit approval before mapper code**

Present the selected sources, exact field counts, excluded fields, identifier rules, cutoff rules, coverage definition, and any blocked source. Do not change `src/`, `tests/`, `docker/`, `requirements/`, or `pyproject.toml` before approval.

Result: the user approved the constrained A boundary on 2026-08-22: proceed with snapshot capture, KRX security identity, ECOS, SEC Series/Class and bounded N-PORT; keep KRX ETF product facts and holdings gated.

- [x] **Step 7: Commit the approved source boundary**

```bash
git add docs/planning/specs/stage-03b-official-source-field-matrix.md \
  docs/planning/tasks/2026-08-22-stage-03b-official-structured-data-implementation-plan.md \
  docs/planning/STATUS.md
git diff --cached --check
git diff --cached
git commit -m "docs: freeze stage 03b official source mappings"
```

Expected: exactly the field matrix, reconciled implementation plan, and status index, with no raw response or account detail.

---

### Task 2: Add immutable official snapshot capture and verification

**Files:**

- Create: `src/financial_agent/ingestion/official/__init__.py`
- Create: `src/financial_agent/ingestion/official/models.py`
- Create: `src/financial_agent/ingestion/official/snapshot.py`
- Create: `tests/ingestion/test_official_snapshot.py`
- Modify: `src/financial_agent/ingestion/sources.py` only for a symmetric verified-upload helper

**Interfaces:**

```python
CoverageStatus = Literal[
    "COVERED", "PARTIALLY_COVERED", "NOT_COVERED", "CONFLICT"
]

@dataclass(frozen=True, slots=True)
class OfficialObjectManifest:
    object_name: str
    object_key: str
    media_type: str
    size_bytes: int
    sha256: str

@dataclass(frozen=True, slots=True)
class OfficialSnapshotManifest:
    source_code: str
    snapshot_id: str
    publisher_code: str
    cutoff_date: date
    applicable_date: date | None
    published_at: datetime | None
    available_at: datetime | None
    vintage_date: date | None
    parser_version: str
    mapping_version: str
    objects: tuple[OfficialObjectManifest, ...]

def validate_official_snapshot(
    manifest: OfficialSnapshotManifest,
) -> str: ...

def capture_http_object(
    opener: object,
    *,
    request: object,
    destination: Path,
    object_name: str,
    object_key: str,
    expected_media_type: str,
    maximum_bytes: int,
) -> OfficialObjectManifest: ...

def write_canonical_manifest(
    manifest: OfficialSnapshotManifest, destination: Path
) -> str: ...
```

- [x] **Step 1: Write RED tests for the immutable boundary**

Cover canonical object ordering, stable manifest hash, duplicate object keys, wrong SHA-256, zero or oversized response, truncated response, wrong media type, after-cutoff dates, missing eligible availability metadata, and a URL/header containing a synthetic secret. Assert exceptions expose only stable codes and never retain the request or credential in `str`, `repr`, or `__cause__`.

- [x] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/ingestion/test_official_snapshot.py -q
```

Expected: missing official snapshot module.

Result: collection failed with `ModuleNotFoundError: financial_agent.ingestion.official`, proving the new boundary was absent before implementation.

- [x] **Step 3: Implement bounded streaming capture**

Use 1 MiB chunks and a temporary file in the destination directory. Hash as bytes stream, enforce `Content-Length` when present and the actual byte limit always, fsync, then atomically replace the destination. Do not place a credential-bearing URL or headers in an exception or manifest.

Keep transport small: accept an opener in tests and use standard-library HTTPS in production. Do not add `requests`, an HTTP SDK wrapper, retries, concurrency, or provider plugins.

- [x] **Step 4: Add verified private Object Storage upload**

Add a small `ObjectUploadClient` protocol and `upload_verified_object(...)` beside the existing verified download. Verify local SHA-256, upload to the approved key, re-download to a temporary path, and compare bytes by SHA-256 before success. Never infer integrity from ETag.

- [x] **Step 5: Prove manifest publication is atomic**

Add tests showing checksum, schema, cutoff, upload, or re-download failure leaves no published `manifest.json`. Database no-write-before-preflight behavior is proved at the combined pipeline boundary in Task 8.

- [x] **Step 6: Run focused and Stage 03A regression**

```bash
.venv/bin/python -m pytest \
  tests/ingestion/test_official_snapshot.py \
  tests/ingestion/test_sources.py \
  tests/ingestion/test_pipeline.py -q
```

Result: official snapshot `23 passed`; focused non-PostgreSQL regression `57 passed, 1 deselected`; all non-live, non-PostgreSQL ingestion tests `154 passed, 12 deselected`. Compile, dependency, and diff checks passed.

- [x] **Step 7: Commit**

```bash
git add src/financial_agent/ingestion/official \
  src/financial_agent/ingestion/sources.py \
  src/financial_agent/ingestion/__init__.py \
  tests/ingestion/test_official_snapshot.py \
  docs/planning/tasks/2026-08-22-stage-03b-official-structured-data-implementation-plan.md \
  docs/planning/STATUS.md
git diff --cached --check
git commit -m "feat: capture immutable official source snapshots"
```

---

### Task 3: Implement exact official identity resolution

**Files:**

- Create: `src/financial_agent/ingestion/official/identity.py`
- Create: `src/financial_agent/ingestion/official/krx_identity.py`
- Create: `src/financial_agent/ingestion/official/sec_series_class.py`
- Create: `tests/ingestion/test_official_identity.py`
- Create: `tests/ingestion/test_krx_identity.py`
- Create: `tests/ingestion/test_sec_series_class.py`
- Create: `tests/fixtures/official_ingestion.py`

**Interfaces:**

```python
ResolutionStatus = Literal["exact", "unresolved", "conflict"]

@dataclass(frozen=True, slots=True)
class IdentityCandidate:
    scheme: str
    value: str

@dataclass(frozen=True, slots=True)
class IdentityResolution:
    status: ResolutionStatus
    entity_id: str | None
    matched_scheme: str | None
    issue_code: str | None

class OfficialIdentityIndex:
    def resolve_product(
        self, candidates: Sequence[IdentityCandidate]
    ) -> IdentityResolution: ...

    def resolve_compound_product(
        self, scheme: str, values: tuple[str, ...]
    ) -> IdentityResolution: ...

def parse_krx_security_basic(
    payload: bytes, *, market: Literal["KOSPI", "KOSDAQ"]
) -> tuple[Mapping[str, object], ...]: ...

def map_krx_security_basic(
    manifest: OfficialSnapshotManifest,
    rows: Iterable[Mapping[str, object]],
) -> Iterator[MappedRow]: ...
```

- [x] **Step 1: Generate synthetic identity fixtures**

Use obviously synthetic identifiers. Include one domestic exact issue code, one unique overseas ISIN, one duplicated ISIN, one unique `(CIK, ticker)` resolving through SEC class to series, one duplicated ticker across CIKs, and two different names sharing no identifier.

- [x] **Step 2: Write RED tests**

Prove:

```text
exact strong key -> one entity
same strong key -> two entities -> conflict
name-only candidate -> unresolved
ticker alone -> unresolved
unique CIK+ticker -> one SEC class -> one series -> one product
duplicated overseas ISIN from organizer pre-scan -> conflict
source-local holding ID -> stable security within source snapshot only
```

- [x] **Step 3: Implement normalized exact maps only**

Normalize schemes explicitly. ISIN uses uppercase ASCII and exact length/check format; CIK strips only documented leading zeros; ticker normalization is source-specific and never a global identifier. Reject empty and invalid identifiers instead of repairing them.

The resolver returns a status and stable code. It never selects the first candidate and never creates a relation on conflict.

- [x] **Step 4: Add official entity record helpers**

Create helpers that emit Stage 02 `catalog.entity`, subtype, `catalog.identifier`, and `catalog.alias` payloads with existing `stable_id` and `make_record_hash`. For every answerable identifier or alias, also emit the Task 1-approved companion text Observation, Evidence, and observation origin. Promote an identifier only after the source pre-scan proves its required uniqueness. Preserve ambiguous raw IDs in Evidence rather than `catalog.identifier`.

- [x] **Step 5: Map the approved KRX KOSPI/KOSDAQ basic information and SEC Series/Class Report**

Parse only the exact Task 1-approved response envelopes and fields. Create Security entities and approved issue-code identifiers/aliases. Create a Company entity and `securityOfCompany` only when the response contains a separately approved strong company identifier; a company-like name alone is not enough.

Parse the six approved SEC Series/Class fields separately. Build only the exact `(normalized CIK, source-specific normalized Class Ticker) -> Class ID -> Series ID` crosswalk. Do not promote Class Ticker to a global identifier and do not resolve a product from ticker alone.

- [x] **Step 6: Run GREEN and duplicate-ID regression**

```bash
.venv/bin/python -m pytest \
  tests/ingestion/test_official_identity.py \
  tests/ingestion/test_krx_identity.py \
  tests/ingestion/test_sec_series_class.py \
  tests/ingestion/test_overseas_etp_mapping.py -q
```

Result: each missing production module produced the expected RED. The final identity, KRX basic, SEC Series/Class, and overseas duplicate-ID selection passed `36` tests. All non-live, non-PostgreSQL ingestion tests passed `176`, with `12` deselected. Empty official populations and non-unique `(CIK, Class Ticker)` mappings fail closed.

- [x] **Step 7: Commit**

```bash
git add src/financial_agent/ingestion/official/identity.py \
  src/financial_agent/ingestion/official/krx_identity.py \
  src/financial_agent/ingestion/official/sec_series_class.py \
  tests/fixtures/official_ingestion.py \
  tests/ingestion/test_official_identity.py \
  tests/ingestion/test_krx_identity.py \
  tests/ingestion/test_sec_series_class.py \
  src/financial_agent/ingestion/official/__init__.py \
  docs/planning/tasks/2026-08-22-stage-03b-official-structured-data-implementation-plan.md \
  docs/planning/STATUS.md
git diff --cached --check
git commit -m "feat: resolve official identities by exact keys"
```

---

### Task 4: Map the approved domestic ETF holdings snapshot

**Gate:** Satisfied on 2026-08-22 for an ETF-by-date official CSV export with the exact six-column header recorded in the field matrix. Map it only as a setting/redemption basket with `PARTIALLY_COVERED/bounded_unknown`; never as a complete economic portfolio.

**Files:**

- Create: `src/financial_agent/ingestion/official/krx_holdings.py`
- Create: `tests/ingestion/test_krx_holdings.py`
- Modify: `tests/fixtures/official_ingestion.py`

**Interfaces:**

```python
def parse_krx_etf_pdf_csv(payload: bytes) -> tuple[Mapping[str, str], ...]: ...

def build_krx_etf_product_bindings(...) -> KrxEtfBindingResult: ...

def map_krx_holding_snapshot(
    manifest: OfficialSnapshotManifest,
    rows: Iterable[Mapping[str, str]],
    *,
    binding: KrxEtfProductBinding,
    security_index: OfficialIdentityIndex,
) -> MappedRow: ...
```

- [x] **Step 1: Encode the exact approved schema as constants**

Use only the header approved in Task 1. Record which columns identify ETF, holding security, weight, quantity, value, currency, and record key. No alias header matching and no guessing Korean/English variants.

- [x] **Step 2: Write RED mapping tests**

Cover one ETF with equity, cash, derivative, and setting-cash summary rows; missing values; signed cash values; repeated source lots; exact, unresolved, and conflicting holding identifiers; an empty publisher file; wrong bound ETF object; and an after-cutoff manifest. Negative cash values are valid source facts and must not be rejected.

Assert the intended Stage 02 shape:

```text
ETF --holdsSecurity--> Security
relation observation: official holding weight and optional quantity/value
relation Evidence: exact object key + source record key + official dates
query_scope Evidence: always bounded_unknown for KRX PDF
```

- [x] **Step 3: Implement source-preserving mapping**

Do not merge same-name holdings. Aggregate repeated lots only if Task 1 documents that the publisher defines them as parts of the same holding and the strong security identifier, currency, and payoff profile agree. Otherwise keep separate source-local securities or mark the product partial.

Store percentage values as the official percentage unit, not as a guessed 0-to-1 fraction. Weight-sum diagnostics do not force 100% and do not reject valid cash, derivatives, shorts, or rounding.

- [x] **Step 4: Emit coverage Evidence**

For each requested organizer ETF snapshot emit one `query_scope` Evidence row. Task 8 combines the captured-object inventory with all organizer ETF bindings to emit `NOT_COVERED` for uncaptured ETFs:

```text
PARTIALLY_COVERED   -> bounded_unknown
NOT_COVERED         -> bounded_unknown
CONFLICT            -> bounded_unknown and source_value_conflict issue
```

The absence of a holdings row is never emitted as a negative `holdsSecurity` fact.

- [x] **Step 5: Run focused GREEN**

```bash
.venv/bin/python -m pytest tests/ingestion/test_krx_holdings.py -q
```

Result on 2026-08-22:

- missing production module produced the intended collection RED;
- focused Task 4 suite passed `14` tests;
- contracts plus non-live ingestion suite passed `455` tests with `12` deselected;
- real organizer and historical KRX files produced `1,133` exact bindings, `69` unresolved organizer ETFs, `8` KRX-only ETFs, `1` invalid ISIN, and `1` name drift;
- one real 2026-07-10 KRX PDF file parsed `200` rows and emitted `200` bounded `holdsSecurity` relations plus `800` relation observations;
- writer payload preparation accepted the resulting Stage 02 record shapes.

The per-ETF full capture inventory remains a separate pending source-acquisition step; no uncaptured ETF is represented as a negative holding fact.

- [x] **Step 6: Commit**

```bash
git add src/financial_agent/ingestion/official/krx_holdings.py \
  tests/fixtures/official_ingestion.py \
  tests/ingestion/test_krx_holdings.py
git diff --cached --check
git commit -m "feat: map official domestic etf holdings"
```

---

### Task 5: Map eligible KRX ETF close and NAV observations

**Gate:** Snapshot parsing and date validation may proceed after Task 2. Product observations use only the ADR-0015 checksum-valid organizer ISIN to unique historical KRX short-code binding.

**Files:**

- Create: `src/financial_agent/ingestion/official/krx_market.py`
- Create: `tests/ingestion/test_krx_market.py`
- Modify: `tests/fixtures/official_ingestion.py`

**Interfaces:**

```python
def parse_krx_etf_daily(payload: bytes) -> tuple[Mapping[str, object], ...]: ...

def select_latest_eligible_krx_date(
    available_dates: Iterable[date], cutoff: date
) -> date: ...

def map_krx_etf_daily(
    manifest: OfficialSnapshotManifest,
    rows: Iterable[Mapping[str, object]],
    identities: OfficialIdentityIndex,
) -> tuple[MappedRow, ...]: ...
```

- [x] **Step 1: Write RED parser and date-selection tests**

Use synthetic JSON with the exact approved response envelope and fields. Prove `2026-07-10` is selected when the cutoff is Saturday, `2026-07-13` is rejected, actual `BAS_DD` is preserved, duplicate pages fail, missing mandatory fields fail the snapshot, and numeric strings are parsed without float conversion.

- [x] **Step 2: Add fixed metric definitions**

Use reviewed IDs and version `1`:

```text
krx_etf_market_close_krw
krx_etf_nav_per_share_krw
```

Both target the organizer ETF entity, use `KRW`, retain actual `applicable_date`, and have separate Evidence. Do not replace organizer AUM or returns.

- [x] **Step 3: Map only exact domestic ETF identities**

Resolve `ISU_CD` using the separately approved Task 1 crosswalk. Until that crosswalk exists, every row remains `LINK_BLOCKED` and produces no product Observation. ETNs, unknown products, ambiguous codes, and non-ETF rows do not produce ETF price/NAV facts. Preserve their aggregate disposition codes.

- [x] **Step 4: Prove compatible same-date values**

Add a test showing close and NAV for a product are both emitted only from the same selected `BAS_DD`. A missing NAV remains missing; it is not copied from price.

- [x] **Step 5: Run GREEN**

```bash
.venv/bin/python -m pytest tests/ingestion/test_krx_market.py -q
```

Result on 2026-08-23:

- the missing `krx_market` module produced the intended collection RED;
- mixed-date KRX objects and a missing public export each produced a separate
  RED before the minimum fix;
- the focused Task 5 suite passed `13` tests;
- contracts plus non-live ingestion passed `468` tests with `12` deselected;
- the live 2026-07-10 KRX response parsed all `1,141` rows without exposing
  raw values and confirmed six-character `ISU_CD` keys;
- the approved organizer-to-KRX binding reproduced `1,133` exact products,
  `69` unresolved organizer ETFs, `8` KRX-only ETFs, one invalid organizer
  ISIN, and one name-only audit drift;
- close and NAV are separate Decimal observations with separate Evidence, and
  missing NAV remains unknown rather than copying close.

- [x] **Step 6: Commit**

```bash
git add src/financial_agent/ingestion/official/krx_market.py \
  tests/fixtures/official_ingestion.py \
  tests/ingestion/test_krx_market.py
git diff --cached --check
git commit -m "feat: map eligible krx etf market facts"
```

---

### Task 6: Map the four approved ECOS exchange rates

**Files:**

- Create: `src/financial_agent/ingestion/official/ecos_fx.py`
- Create: `tests/ingestion/test_ecos_fx.py`
- Modify: `tests/fixtures/official_ingestion.py`

**Interfaces:**

```python
ECOS_ITEMS = {
    "0000001": "KRW_PER_USD",
    "0000002": "KRW_PER_100_JPY",
    "0000003": "KRW_PER_EUR",
    "0000053": "KRW_PER_CNY",
}

def parse_ecos_731y001(payload: bytes) -> tuple[Mapping[str, object], ...]: ...

def map_ecos_fx(
    manifest: OfficialSnapshotManifest,
    rows: Iterable[Mapping[str, object]],
) -> tuple[MappedRow, ...]: ...
```

- [x] **Step 1: Write RED tests for direction and units**

Prove all four item codes are required, `0000002` remains KRW per 100 JPY, an unknown item is rejected, comma-formatted or malformed numbers do not become floats, after-cutoff dates are rejected, and the latest eligible observation is chosen independently per item.

- [x] **Step 2: Add the Bank of Korea publisher entity and fixed metrics**

Create one official institution with an approved stable identifier and one metric per rate definition. Store base/quote/rate type in the metric description and Evidence normalized value; do not infer direction from the user question.

Approved metric IDs:

```text
ecos_731y001_krw_per_usd
ecos_731y001_krw_per_100_jpy
ecos_731y001_krw_per_eur
ecos_731y001_krw_per_cny
```

- [x] **Step 3: Implement deterministic Decimal mapping**

Map one eligible Observation per item with unit `KRW`, actual `TIME` as `applicable_date`, and exact source item code in Evidence. Keep `published_at` and `available_at` from the approved snapshot metadata.

- [x] **Step 4: Run GREEN**

```bash
.venv/bin/python -m pytest tests/ingestion/test_ecos_fx.py -q
```

Result: the missing ECOS production module produced the expected import RED. The final ECOS tests passed `13`; the focused official-source regression passed `50`; all non-live, non-PostgreSQL ingestion tests passed `189`, with `12` deselected. The Stage 02 writer payload check deduplicated the Bank of Korea entity and Source while preserving four Metric, Observation, Evidence, and origin records.

- [x] **Step 5: Commit**

```bash
git add src/financial_agent/ingestion/official/ecos_fx.py \
  src/financial_agent/ingestion/official/__init__.py \
  tests/fixtures/official_ingestion.py \
  tests/ingestion/test_ecos_fx.py \
  docs/planning/tasks/2026-08-22-stage-03b-official-structured-data-implementation-plan.md \
  docs/planning/STATUS.md
git diff --cached --check
git commit -m "feat: map approved ecos exchange rates"
```

---

### Task 7: Parse eligible SEC N-PORT holdings with bounded coverage

**Files:**

- Create: `src/financial_agent/ingestion/official/sec_nport.py`
- Create: `tests/ingestion/test_sec_nport.py`
- Read: `src/financial_agent/ingestion/official/sec_series_class.py`
- Modify: `tests/fixtures/official_ingestion.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class NportArchiveLimits:
    maximum_archive_bytes: int = 805_306_368
    maximum_expanded_bytes: int = 8_589_934_592
    maximum_members: int = 64

@dataclass(frozen=True, slots=True)
class NportProductBinding:
    product_entity_id: str
    cik: str
    class_ticker: str

def verify_and_extract_nport(
    archive: Path, destination: Path, limits: NportArchiveLimits
) -> Mapping[str, Path]: ...

def iter_eligible_nport_funds(
    files: Mapping[str, Path],
    cutoff: date,
    *,
    manifest: OfficialSnapshotManifest,
    series_class_index: OfficialIdentityIndex,
    product_bindings: Iterable[NportProductBinding],
) -> Iterator[MappedRow]: ...
```

**Approved reconciliation (2026-08-22):** The organizer product entity ID is
an explicit input binding because the SEC Series/Class index intentionally
resolves to a Series identity, not to an organizer product entity. The mapper
must verify exact `(CIK, normalized Class Ticker) -> Series ID`, compare that
Series ID with the eligible N-PORT filing, and attach `holdsSecurity` to the
bound organizer product. It must not promote one `SEC_SERIES_ID` onto every
organizer product class, create a new SEC Series table, add an ontology
predicate, or change the Stage 02 DDL. Series, Class, and accession identifiers
remain Evidence provenance. An unresolved or conflicting binding emits bounded
coverage without an inferred holding relation.

- [x] **Step 1: Build a tiny synthetic N-PORT ZIP**

Generate one synthetic Series/Class CSV and UTF-8 tab-separated files with exact official headers for `SUBMISSION`, `REGISTRANT`, `FUND_REPORTED_INFO`, `FUND_REPORTED_HOLDING`, and `IDENTIFIERS`. Include an original filing, an eligible amendment, an after-cutoff amendment, two fund series under one registrant, a duplicate holding lot, an unresolved holding identifier, and a second organizer product with no matched filing.

- [x] **Step 2: Write archive-safety RED tests**

Cover path traversal, symlink-like entry, duplicate member, missing required file, unexpected case-variant file, excessive member count, excessive expanded size, suspicious compression expansion, invalid UTF-8, and wrong TSV header. Fail the whole snapshot before yielding one mapped row.

- [x] **Step 3: Implement disk-bounded extraction and streaming joins**

Never load the approximately 420 MB official archive or all expanded holdings into memory. Validate ZIP metadata first, extract only approved files into a newly created temporary directory, and parse TSV rows with `csv.DictReader(delimiter="\t")`.

Use bounded on-disk or keyed intermediate files for the accession/holding joins if memory measurement shows the archive exceeds the approved ingestion budget. Do not add DuckDB, Pandas, or a general staging database without a separate plan amendment.

- [x] **Step 4: Select filings as known at cutoff**

Require both report date and `FILING_DATE` to be on or before `2026-07-11`. For one `(CIK, SERIES_ID, REPORT_DATE)`, choose the latest eligible official amendment by filing date, then accession number as a deterministic tie-breaker. Preserve the selected accession and filing type in Evidence. Never use an after-cutoff amendment even if it corrects older holdings.

- [x] **Step 5: Resolve fund series and holdings**

Resolve organizer products through the approved Series/Class crosswalk: unique exact `(CIK, normalized Class Ticker)` to Class ID, then exact Class ID to Series ID, then Series ID to the eligible N-PORT filing. Create or enrich the asset-manager institution with official CIK/LEI. Resolve holdings by unique valid ISIN, then unique valid CUSIP, otherwise a snapshot-scoped `HOLDING_ID`; do not promote ticker, an untyped other identifier, or a duplicated identifier.

N-PORT `PERCENTAGE` is stored as percentage units exactly as documented. Separate holdings or derivative legs remain separate unless the official schema and all identity/payoff fields prove they are aggregable.

- [x] **Step 6: Emit bounded coverage**

Use `COVERED` only if the selected public filing is complete, every required file and holding row is accounted for, and all rows needed for the requested population are resolved. Any unresolved security, partial manager supplement, or missing eligible filing yields `PARTIALLY_COVERED` or `NOT_COVERED` with `bounded_unknown`.

- [x] **Step 7: Run RED then GREEN**

```bash
.venv/bin/python -m pytest tests/ingestion/test_sec_nport.py -q
```

Result: the missing mapping contract produced the expected import RED. The
archive and mapper suite passed `28`; the focused official-source suite passed
`86`; all non-live, non-PostgreSQL contract and ingestion tests passed `441`,
with `12` deselected. Extraction writes only the five approved members, and
the mapper streams all holding and identifier rows while retaining full row
payloads only for accessions selected by the explicit organizer bindings.
Primary-key accounting still keeps compact key sets in memory; the first live
Task 9 capture must measure them and use the already-approved keyed spill path
if the ingestion budget is exceeded. The Stage 02 writer payload check passed
without a new origin type, DDL, Series table, or ontology predicate.

- [x] **Step 8: Commit**

```bash
git add src/financial_agent/ingestion/official/sec_nport.py \
  tests/fixtures/official_ingestion.py \
  tests/ingestion/test_sec_nport.py
git diff --cached --check
git commit -m "feat: map bounded sec nport holdings"
```

---

### Task 8: Build one combined Stage 03A plus 03B disposable dataset

**Files:**

- Create: `src/financial_agent/ingestion/official_pipeline.py`
- Create: `tests/ingestion/test_official_pipeline.py`
- Modify: `src/financial_agent/ingestion/pipeline.py`
- Modify: `src/financial_agent/ingestion/cli.py`
- Modify: `tests/ingestion/test_pipeline.py`
- Modify: `tests/ingestion/test_writer.py` only for newly used existing-table payloads

**Interfaces:**

```python
async def build_stage03b_dataset(
    engine: AsyncEngine,
    *,
    dataset_version: str,
    organizer_inputs: OrganizerInputs,
    official_manifests: Sequence[OfficialSnapshotManifest],
    official_object_root: Path,
    batch_size: int = 1000,
) -> BuildReport: ...
```

CLI commands:

```text
python -m financial_agent.ingestion.cli capture-official
python -m financial_agent.ingestion.cli validate-official
python -m financial_agent.ingestion.cli load-stage03b
python -m financial_agent.ingestion.cli verify-official-object-storage
```

- [ ] **Step 1: Write combined-manifest RED tests**

Prove manifest order independence, organizer-only manifest hash backward compatibility, one combined manifest before `create_building_dataset`, duplicate snapshot ID rejection, missing official object rejection, changed parser/mapping version changing the manifest, and any preflight failure leaving the database empty.

- [ ] **Step 2: Refactor Stage 03A only at the preflight/write seam**

Expose the organizer manifest mapping and a reusable function that writes already-preflighted organizer rows into an already-created `building` dataset. Keep `build_organizer_dataset(...)` behavior, hash, row counts, and tests unchanged. Do not change mapper output or writer semantics.

- [ ] **Step 3: Implement the sequential combined build**

The order is fixed:

```text
1. snapshot all organizer inputs
2. validate every organizer and official checksum/schema/cutoff
3. compute one combined canonical manifest
4. create one building dataset
5. write organizer rows
6. build exact identity indexes
7. write official publisher entities and one SourceRecord per canonical snapshot manifest
8. write official identity rows
9. write KRX holdings
10. write KRX market facts
11. write ECOS FX
12. write SEC N-PORT holdings
13. query actual table and coverage counts
14. compute PostgreSQL and Evidence component hashes
15. return BuildReport; do not validate or activate
```

Use batches of 1,000 `MappedRow` values and the existing writer. A structural failure in one snapshot fails the combined build report and leaves the dataset non-active; a mapped individual conflict remains quarantined with Evidence and aggregate issue counts.

- [ ] **Step 4: Reuse BuildReport without a new report model**

Store `COVERED`, `PARTIALLY_COVERED`, `NOT_COVERED`, and `CONFLICT` aggregate counts under each official source's existing `BuildReport.source_counts` mapping. Do not change the `BuildReport` dataclass or Stage 03A serialization. Do not add raw IDs, names, values, object keys, or URLs to BuildReport.

- [ ] **Step 5: Add sanitized environment boundaries**

Use only named environment variables:

```text
FINANCIAL_AGENT_SOURCE_ROOT
FINANCIAL_AGENT_BUILD_DATABASE_URL
FINANCIAL_AGENT_DATASET_VERSION
FINANCIAL_AGENT_OFFICIAL_MANIFEST_ROOT
FINANCIAL_AGENT_OBJECT_STORAGE_ENDPOINT
FINANCIAL_AGENT_OBJECT_STORAGE_BUCKET
FINANCIAL_AGENT_OBJECT_STORAGE_ACCESS_KEY_ID
FINANCIAL_AGENT_OBJECT_STORAGE_SECRET_ACCESS_KEY
FINANCIAL_AGENT_KRX_API_KEY
FINANCIAL_AGENT_ECOS_API_KEY
FINANCIAL_AGENT_SEC_USER_AGENT
```

The SEC user agent is required for live SEC capture but is not secret. Never print any value above. Stable failures include `OFFICIAL_SOURCE_CONFIGURATION_MISSING`, `OFFICIAL_SCHEMA_MISMATCH`, `OFFICIAL_CUTOFF_INELIGIBLE`, `OFFICIAL_IDENTITY_CONFLICT`, `OFFICIAL_COVERAGE_INCOMPLETE`, and existing build/database codes.

- [ ] **Step 6: Run focused PostgreSQL GREEN**

```bash
FINANCIAL_AGENT_TEST_DATABASE_URL="$TEST_URL" \
  .venv/bin/python -m pytest \
    tests/ingestion/test_official_pipeline.py \
    tests/ingestion/test_pipeline.py \
    tests/ingestion/test_writer.py -q
```

Assert the resulting dataset is `building` and absent from `active_dataset`.

- [ ] **Step 7: Run all non-live regression**

```bash
FINANCIAL_AGENT_TEST_DATABASE_URL="$TEST_URL" \
  .venv/bin/python -m pytest tests/contracts tests/db tests/ingestion \
    -m "not performance and not ncp_integration and not organizer_data and not object_storage and not official_data" -q
```

- [ ] **Step 8: Commit**

```bash
git add src/financial_agent/ingestion/pipeline.py \
  src/financial_agent/ingestion/official_pipeline.py \
  src/financial_agent/ingestion/cli.py \
  tests/ingestion/test_pipeline.py \
  tests/ingestion/test_writer.py \
  tests/ingestion/test_official_pipeline.py
git diff --cached --check
git commit -m "feat: build combined official data snapshot"
```

---

### Task 9: Prove live-source, coverage, Object Storage, and Linux acceptance

**Files:**

- Create: `tests/ingestion/test_real_official_sources.py`
- Create: `tests/ingestion/test_ncp_official_object_storage.py`
- Create: `tests/ingestion/test_official_question_gates.py`
- Modify: `pyproject.toml`
- Modify: `docker/ingestion-check.Dockerfile`
- Modify: `.dockerignore` only if the existing rules do not exclude a new generated path
- Modify: `docs/planning/STATUS.md`

- [ ] **Step 1: Add explicit live markers and fail-closed configuration**

Register `official_data`. Tests skip only when the corresponding run flag is not `1`. Once enabled, missing credentials, source manifest, Object Storage, or disposable database configuration fails with a stable configuration code instead of skipping.

Run flags:

```text
RUN_OFFICIAL_DATA_TESTS=1
RUN_NCP_OBJECT_STORAGE_TESTS=1
RUN_ORGANIZER_DATA_TESTS=1
```

- [ ] **Step 2: Capture and verify eligible official objects**

Capture only Task 1-approved sources. Store each under:

```text
external/2026-07-11/{source_code}/{snapshot_id}/{object_name}
```

Upload a canonical manifest into the same prefix. Re-download all objects and prove each captured/downloaded SHA-256 equals its manifest entry. Persist one SourceRecord per snapshot with the canonical manifest SHA-256 as `content_checksum`; Evidence locators point to the exact contributing object and record key. Print only source code, object count, byte count, eligible date range, and stable result code.

- [ ] **Step 3: Run source-specific aggregate gates**

The live test must verify without printing product-level facts:

```text
KRX market: selected date <= cutoff, unique issue/date grain, required fields complete
KRX holdings: approved schema, portfolio count, exact row accounting, coverage distribution
ECOS: exactly four approved item codes, one latest eligible row per item
N-PORT: required files, selected filing count, matched/partial/uncovered product counts
```

No hard-coded count is approved until the first capture is inspected. After the first verified capture, record exact safe aggregate invariants in `STATUS.md` and freeze them as test expectations for that snapshot ID.

- [ ] **Step 4: Run the disposable combined rebuild**

Use an empty PostgreSQL 15 database, migrations through `0005`, organizer private inputs, and downloaded official objects. Rebuild twice under different dataset version names and assert equal manifest and component hashes, equal aggregate counts, exact retry convergence, `status='building'`, and no `active_dataset` row.

- [ ] **Step 5: Add expected-question data gates**

Use deterministic SQL, not an LLM, to prove the data can support these shapes:

```text
domestic ETF -> holdsSecurity -> Samsung Electronics candidate
matching ETFs -> KRX price/NAV actual eligible date
official FX -> four fixed ECOS definitions and actual date
overseas ETF holdings -> bounded covered population
product -> manager/registrant exact identifier
```

The gate verifies relation/observation/Evidence joins and coverage disclosure, not final ranking, similarity, or natural-language answers. Use synthetic fixtures in ordinary tests and aggregate-only checks in live tests.

- [ ] **Step 6: Run Linux/amd64 synthetic verification**

Extend the existing Dockerfile command to include official synthetic tests that need neither network nor PostgreSQL. Do not copy raw data or real manifests into the image.

```bash
docker build --no-cache --platform linux/amd64 \
  -f docker/ingestion-check.Dockerfile \
  -t financial-agent-ingestion:stage-03b .
docker run --rm --platform linux/amd64 \
  financial-agent-ingestion:stage-03b
```

Expected: exit code `0`. Run PostgreSQL tests separately with an explicitly disposable URL.

- [ ] **Step 7: Run final verification**

```bash
.venv/bin/python -m pytest tests/contracts tests/ingestion \
  -m "not postgres and not organizer_data and not object_storage and not official_data and not ncp_integration" -q

FINANCIAL_AGENT_TEST_DATABASE_URL="$TEST_URL" \
  .venv/bin/python -m pytest tests/contracts tests/db tests/ingestion \
    -m "not performance and not ncp_integration and not organizer_data and not object_storage and not official_data" -q

.venv/bin/python scripts/export_contract_schemas.py --check
.venv/bin/python -m compileall -q src tests scripts alembic
.venv/bin/python -m pip check
git diff --check
```

Run the three live flags only with the approved private sources and disposable database. Record any unavailable KRX holdings access or intentionally unrun live gate; never report it as passed.

- [ ] **Step 8: Audit secrets, data, and Docker context**

Confirm:

```text
no file under data/ is tracked or staged
no official response/archive/manifest/BuildReport is staged
no bucket, NCP account/resource ID, API key, URL credential, .env, dump,
Parquet, embedding, cache, or runtime output is staged
.dockerignore excludes data/, downloads, manifests, reports, .env*,
.gstack/, .agents/, and .codex/
```

- [ ] **Step 9: Update status and commit Stage 03B**

Record exact test counts, approved snapshot IDs only if they are non-sensitive, aggregate coverage, actual eligible dates, component hash equality, Object Storage result, Linux/amd64 result, blocked manager files, and intentionally unrun gates. State explicitly that no final NCP PostgreSQL dataset was loaded or activated.

```bash
git add tests/ingestion/test_real_official_sources.py \
  tests/ingestion/test_ncp_official_object_storage.py \
  tests/ingestion/test_official_question_gates.py \
  docker/ingestion-check.Dockerfile pyproject.toml .dockerignore \
  docs/planning/STATUS.md
git diff --cached --check
git diff --cached
git status --short
git commit -m "test: verify stage 03b official ingestion"
```

Expected: one independently verifiable Stage 03B deliverable. Do not push, merge, rebuild final NCP PostgreSQL, or activate a dataset without separate user authorization.

## Task Checkpoints

- Task 1 is a mandatory user approval gate before Tasks 3 through 7.
- Task 4 has an additional KRX holdings access gate; failure to confirm access blocks only that source and must remain visible.
- Each Task begins with focused RED, reaches focused GREEN, runs the listed regression, receives a diff review, and creates one narrow commit.
- Do not combine tasks to bypass an approval or source-access gate.
- A discovered Stage 02 representation gap stops implementation; it does not authorize schema expansion.

## Self-Review Checklist

- [ ] Every approved Stage 03B design requirement maps to a Task and verification command.
- [ ] Domestic maximum coverage and overseas bounded coverage are represented differently.
- [ ] Publication/availability dates cannot be replaced by collection time.
- [ ] KRX holdings access is not assumed or reverse-engineered.
- [ ] No manager source is generalized before source-specific approval.
- [ ] Entity linking never uses names or ticker alone.
- [ ] Duplicate identifiers and holdings are preserved or quarantined, not silently merged.
- [ ] SEC archive handling is disk-bounded and path-safe.
- [ ] ECOS currency direction and 100-JPY unit are fixed by metric definition.
- [ ] Combined manifest exists before the first database row and cannot be mutated later.
- [ ] Stage 03A organizer-only output remains byte/hash compatible after the pipeline seam refactor.
- [ ] Stage 03B ends with Object Storage plus disposable `building` evidence, not final NCP PostgreSQL mutation.
- [ ] No task adds DDL, Graph, Vector, document parsing, LLM behavior, ranking, or activation.
