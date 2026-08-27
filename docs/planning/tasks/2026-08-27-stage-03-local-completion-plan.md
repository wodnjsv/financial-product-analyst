# Stage 03 Current Official Source Local Completion Implementation Plan

**Status:** Approved — sequential implementation started 2026-08-27

> **For agentic workers:** Execute this plan task-by-task in the current
> conversation with review checkpoints. Do not dispatch subagents unless the
> user explicitly requests delegation. Track progress with the checkbox steps
> below.

**Goal:** Freeze the remaining current official sources, enforce organizer
missingness as authoritative, and produce two matching inactive local Stage 03
PostgreSQL builds that are safe inputs to Stage 04.

**Architecture:** Keep the latest four organizer masters as the product-fact
authority and permit official sources only through a small explicit
enrichment allowlist. Reuse the existing source-specific adapters, immutable
manifests, Stage 02 ledger, and combined build; do not create a connector
framework, new storage schema, or NCP dataset. Finalize support coverage before
the two clean local builds.

**Tech Stack:** Python 3.12, Pydantic, openpyxl, SQLAlchemy 2, psycopg 3,
PostgreSQL 15, pytest, KRX official files/API responses, ECOS `731Y001`, SEC
Series/Class and Form N-PORT datasets.

**Spec:**
[Organizer Rebaseline Design](../specs/2026-08-24-stage-03-organizer-rebaseline-design.md),
[Stage 03B Structured Data Design](../specs/2026-08-22-stage-03b-official-structured-data-design.md),
[ADR-0020](../decisions/ADR-0020-treat-organizer-missingness-as-authoritative.md)

## Global Constraints

- The eight replacement workbooks are the only organizer baseline.
- External information must be available no later than
  `2026-08-24T23:59:59+09:00`; preserve every actual applicable, publication,
  and availability date.
- Organizer `present` and `zero` values win. Organizer `missing`, `placeholder`,
  and reviewed unavailable values remain unavailable and cannot be filled from
  an external source.
- External sources may add only reviewed organizer-absent relations,
  identifiers, FX inputs, and coverage/lineage facts.
- Do not infer an absence from partial overseas or public-fund holdings
  coverage. Only a validated closed-world snapshot may support a negative
  holding Claim.
- Preserve organizer and official raw bytes unchanged and outside Git.
- Keep generated databases, captures, manifests, reports, RDF, and embeddings
  ignored.
- PostgreSQL remains the fact and Evidence authority. Do not add Alembic
  `0007` or change the frozen Stage 01 contract.
- Every intermediate and final local dataset stays `building` and absent from
  `active_dataset`.
- Do not write NCP PostgreSQL, Object Storage, Fuseki, or Vector state in this
  plan. Stage 08 owns those checks.
- Use TDD for behavior changes. Run the narrow source test first, then the
  ordinary non-live regression, then the real-source gate where configured.

## Assumptions

- Commit `00b1e66` is the verified current organizer plus KRX ETF holdings
  baseline.
- The 1,161 local KRX ETF PDF files dated `2026-08-22` remain byte-identical and
  ignored.
- Existing SEC Series/Class and 2026 Q2 N-PORT bytes may be reapproved only if
  their checksums, publication date, availability date, and source schema still
  pass the current cutoff gate. Reapproval does not mean rewriting their actual
  dates.
- A public-fund holdings source is optional for Stage 03 completion only when
  its absence is recorded as `requires_data` with the affected question types.

## Non-Goals

- Replacing organizer AUM, return, price, NAV, risk, fee, sale status, or any
  other organizer-defined product field with an external value.
- Collecting FRED or broad macroeconomic datasets that no approved question
  requires.
- Making overseas or public-fund holdings coverage appear complete.
- Implementing ontology projections, retrieval, orchestration, Claim Gate, or
  the evaluation API; those remain Stage 04 through Stage 07.
- Activating or deploying a dataset.

## Verifiable Success Criteria

1. An organizer-null/external-present product fact produces no releaseable
   external product observation and retains organizer missing Evidence.
2. Zero remains zero and is not classified as missing.
3. The current combined manifest excludes KRX ETF daily close/NAV but includes
   approved current KRX security identity, KRX ETF holdings, ECOS FX, SEC
   Series/Class, and eligible N-PORT snapshots.
4. KRX holding relations reuse a current KRX security entity only on one exact
   official identifier match; ambiguous identifiers fail closed and unresolved
   holdings remain source-local with bounded coverage.
5. All approved official objects pass checksum, schema, cutoff, row accounting,
   and identity gates.
6. Public-fund holdings finish with either one separately approved official
   source or a documented `requires_data` decision; no unofficial substitute is
   ingested.
7. Every internal question case and each organizer-announced evaluation family
   has one measured support state and source/limitation reason.
8. Two clean PostgreSQL 15 builds have identical manifest, reproducibility,
   PostgreSQL, and Evidence component hashes and identical representative query
   results.
9. Both builds remain inactive `building` versions and pass database-object and
   `group_roles` postflight checks.
10. Focused, ordinary non-live, real-source, schema, compile, diff, forbidden
    data, and secret audits pass before the branch is committed or pushed.

---

### Task 1: Enforce the Organizer-Only Product-Fact Boundary

**Files:**

- Create: `src/financial_agent/ingestion/official/authority.py`
- Modify: `src/financial_agent/ingestion/official/capture.py`
- Modify: `src/financial_agent/ingestion/official/krx_holdings.py`
- Modify: `src/financial_agent/ingestion/official/sec_nport.py`
- Modify: `src/financial_agent/ingestion/official_pipeline.py`
- Modify: `src/financial_agent/ingestion/official/__init__.py`
- Create: `tests/ingestion/test_official_authority.py`
- Modify: `tests/ingestion/test_real_official_sources.py`
- Modify: `tests/ingestion/test_official_pipeline.py`
- Modify: `tests/ingestion/test_pipeline.py`
- Modify: `tests/ingestion/test_krx_holdings.py`
- Modify: `tests/ingestion/test_sec_nport.py`
- Modify: `tests/ingestion/test_official_question_gates.py`

**Interfaces:**

- Consumes: `MappedRow`, `MappingIssue`, source code, and the existing records
  produced by each official adapter.
- Produces:
  `validate_official_enrichment_scope(source_code: str, row: MappedRow) -> None`.
- Raises: `OfficialEnrichmentScopeError` with code
  `OFFICIAL_ENRICHMENT_SCOPE_VIOLATION` when a source emits a product fact
  outside its exact allowlist.
- Current allowlist:
  - `KRX_KOSPI_BASIC`, `KRX_KOSDAQ_BASIC`: security identity and alias facts;
  - `KRX_ETF_PDF`: `holdsSecurity`, holding-level observations, coverage, and
    lineage;
  - `ECOS_731Y001`: four reviewed FX observations and lineage;
  - `SEC_SERIES_CLASS_20260601`: regulator source and binding index only;
  - `SEC_NPORT_2026Q2`: `holdsSecurity`, holding-level observations, coverage,
    and lineage.

- [x] **Step 1: Write failing authority tests**

Add tests proving:

```python
def test_external_product_metric_is_rejected_even_when_organizer_is_missing():
    row = mapped_official_product_observation(
        metric_id="krx_etf_nav_per_share_krw",
        value="12345.67",
    )
    with pytest.raises(OfficialEnrichmentScopeError) as captured:
        validate_official_enrichment_scope("KRX_ETF_DAILY", row)
    assert captured.value.code == "OFFICIAL_ENRICHMENT_SCOPE_VIOLATION"


def test_holding_relation_and_holding_metrics_are_allowed():
    validate_official_enrichment_scope(
        "KRX_ETF_PDF",
        mapped_holding_row(),
    )
```

Also assert that the current approved capture source codes do not contain
`KRX_ETF_DAILY` and that a current manifest containing that source fails closed
as unsupported.

- [x] **Step 2: Run the tests and confirm the old behavior fails**

Run:

```bash
.venv/bin/python -m pytest \
  tests/ingestion/test_official_authority.py \
  tests/ingestion/test_real_official_sources.py \
  tests/ingestion/test_official_pipeline.py -q
```

Expected: failure because the authority module does not exist and the current
capture plan still permits KRX daily price/NAV.

- [x] **Step 3: Implement the minimal source-specific allowlist**

Create frozen allowed table/predicate/metric-prefix sets in `authority.py`.
Inspect only normalized identifiers and record keys; never include raw values
in an exception. Call the validator before each official `MappedRow` enters the
writer batch. Remove `KRX_ETF_DAILY` from the current capture specs,
`_OFFICIAL_SOURCE_ORDER`, and `_SUPPORTED_SOURCES`; retain its parser module and
historical tests without including it in the current combined build.
Remove the KRX PDF summary-row product metric and the SEC N-PORT `managedBy`
enrichment because both overlap organizer-defined product facts; preserve the
raw source bytes and the approved holdings facts.

- [x] **Step 4: Run the focused authority suite**

Run the Step 2 command.

Expected: all selected tests pass and no current source can emit an
organizer-overlapping product metric.

- [x] **Step 5: Commit the authority boundary**

```bash
git add \
  src/financial_agent/ingestion/official/authority.py \
  src/financial_agent/ingestion/official/capture.py \
  src/financial_agent/ingestion/official_pipeline.py \
  src/financial_agent/ingestion/official/__init__.py \
  tests/ingestion/test_official_authority.py \
  tests/ingestion/test_real_official_sources.py \
  tests/ingestion/test_official_pipeline.py
git diff --cached --check
git commit -m "feat: enforce organizer fact authority"
```

---

### Task 2: Freeze Current KRX Security Identity and Rebind Holdings

**Files:**

- Modify: `src/financial_agent/ingestion/official/capture.py`
- Modify: `src/financial_agent/ingestion/official/krx_identity.py`
- Modify: `src/financial_agent/ingestion/official/krx_holdings.py`
- Modify: `src/financial_agent/ingestion/official_pipeline.py`
- Modify: `tests/ingestion/test_krx_identity.py`
- Modify: `tests/ingestion/test_krx_holdings.py`
- Modify: `tests/ingestion/test_real_current_krx_holdings.py`
- Local ignored output:
  `data/generated/stage03b/current-official-capture/`

**Interfaces:**

- Consumes: the official `2026-08-22` KOSPI and KOSDAQ basic snapshots, the
  frozen organizer identity index, and the 1,161 KRX ETF PDF snapshots.
- Produces: an `OfficialIdentityIndex` that resolves holding securities by one
  exact KRX standard or short issue code before source-local fallback.
- Preserves: 75,216 `holdsSecurity` source lots; identity enrichment must not
  merge or aggregate lots.

- [x] **Step 1: Add identity-precedence and ambiguity tests**

Add cases for one exact KRX match, an ambiguous code, and no KRX match. Assert:

```python
assert exact_holding.object_entity_id == krx_security_entity_id
assert ambiguous_holding.disposition == "limited"
assert unresolved_holding.issue.code == (
    "KRX_ETF_HOLDING_SOURCE_LOCAL_IDENTITY"
)
```

Assert that security-name or ticker similarity never creates a binding.

- [x] **Step 2: Run the focused KRX tests and record the failing assertion**

```bash
.venv/bin/python -m pytest \
  tests/ingestion/test_krx_identity.py \
  tests/ingestion/test_krx_holdings.py -q
```

- [x] **Step 3: Capture or import the exact current KRX basic bytes**

Use the existing KRX API capture boundary and the configured secret file. The
capture must write immutable objects and manifests under the ignored output
root, with:

```text
source_code: KRX_KOSPI_BASIC / KRX_KOSDAQ_BASIC
applicable_date: 2026-08-22
cutoff_date: 2026-08-24
publisher_code: KRX
```

Reject empty responses, duplicate standard codes, duplicate short codes,
schema drift, future dates, checksum mismatch, and partial pagination.

- [x] **Step 4: Reuse the security index in the holdings mapper**

Keep organizer exact identity first, current KRX identity second, and
source-local security last. Quarantine ambiguity. Do not overwrite organizer
names or organizer product facts.

- [x] **Step 5: Run the real inventory and binding gate**

```bash
RUN_CURRENT_KRX_HOLDINGS_TESTS=1 \
FINANCIAL_AGENT_PREF01N001_DATA_PATH="$CURRENT_ORGANIZER_ROOT/pref01n001_data.xlsx" \
FINANCIAL_AGENT_KRX_HOLDINGS_ROOT="$CURRENT_KRX_HOLDINGS_ROOT" \
FINANCIAL_AGENT_CURRENT_KRX_IDENTITY_CAPTURE_ROOT="$CURRENT_KRX_IDENTITY_CAPTURE_ROOT" \
.venv/bin/python -m pytest \
  tests/ingestion/test_real_current_krx_holdings.py -m organizer_data -q
```

Expected: 1,161 ETF files and 75,216 holding relations remain; the test records
measured exact, ambiguous, and source-local identity counts without assuming
that every holding is a KRX-listed equity.

- [x] **Step 6: Commit current KRX security enrichment**

```bash
git add \
  src/financial_agent/ingestion/official/capture.py \
  src/financial_agent/ingestion/official/krx_identity.py \
  src/financial_agent/ingestion/official/krx_holdings.py \
  src/financial_agent/ingestion/official_pipeline.py \
  tests/ingestion/test_krx_identity.py \
  tests/ingestion/test_krx_holdings.py \
  tests/ingestion/test_real_current_krx_holdings.py
git diff --cached --check
git commit -m "feat: bind current krx holding securities"
```

---

### Task 3: Freeze the Current ECOS FX Snapshot

**Files:**

- Modify: `src/financial_agent/ingestion/official/capture.py`
- Modify: `src/financial_agent/ingestion/official/ecos_fx.py`
- Modify: `tests/ingestion/test_ecos_fx.py`
- Modify: `tests/ingestion/test_real_official_sources.py`
- Local ignored output:
  `data/generated/stage03b/current-official-capture/`

**Interfaces:**

- Consumes: ECOS statistic `731Y001` for USD, JPY(100), EUR, and CNY.
- Produces: one eligible latest observation per approved currency with actual
  date and a manifest available no later than the cutoff.
- Metric IDs remain:
  `ecos_731y001_krw_per_usd`, `ecos_731y001_krw_per_100_jpy`,
  `ecos_731y001_krw_per_eur`, and `ecos_731y001_krw_per_cny`.

- [x] **Step 1: Add exact item, date, and uniqueness tests**

Ignore unrelated official `731Y001` items returned by the broad ECOS response,
but require that a duplicate approved currency/date row, altered approved item
semantics, a future available timestamp, or a missing approved currency fails
the snapshot. Assert that JPY retains the per-100 unit.

- [x] **Step 2: Run the focused ECOS suite**

```bash
.venv/bin/python -m pytest tests/ingestion/test_ecos_fx.py -q
```

- [x] **Step 3: Capture and validate the eligible ECOS response**

Use the configured API key without printing it. Preserve the actual latest
eligible observation date rather than rewriting the value date to
`2026-08-24`. Re-read the captured object and require byte hash, manifest hash,
row count, and four-currency coverage.

- [x] **Step 4: Run the configured real-source gate**

```bash
RUN_CURRENT_ECOS_TESTS=1 \
FINANCIAL_AGENT_CURRENT_ECOS_CAPTURE_ROOT="$CURRENT_ECOS_CAPTURE_ROOT" \
.venv/bin/python -m pytest \
  tests/ingestion/test_real_official_sources.py -m official_data -q
```

Expected: the ECOS object and manifest pass without adding any product fact.

- [x] **Step 5: Commit the current FX boundary**

```bash
git add \
  src/financial_agent/ingestion/official/capture.py \
  src/financial_agent/ingestion/official/ecos_fx.py \
  tests/ingestion/test_ecos_fx.py \
  tests/ingestion/test_real_official_sources.py
git diff --cached --check
git commit -m "feat: freeze current ecos exchange rates"
```

---

### Task 4: Reapprove SEC Series/Class and N-PORT Against the Current Organizer

**Files:**

- Modify: `src/financial_agent/ingestion/official/capture.py`
- Modify: `src/financial_agent/ingestion/official/sec_series_class.py`
- Modify: `src/financial_agent/ingestion/official/sec_nport.py`
- Modify: `src/financial_agent/ingestion/official_pipeline.py`
- Modify: `tests/ingestion/test_sec_series_class.py`
- Modify: `tests/ingestion/test_sec_nport.py`
- Modify: `tests/ingestion/test_official_pipeline.py`
- Modify: `tests/ingestion/test_real_official_sources.py`
- Create: `tests/ingestion/test_real_current_sec.py`
- Local ignored output:
  `data/generated/stage03b/current-sec-capture/`

**Interfaces:**

- Consumes: exact organizer overseas product entity, CIK and class ticker;
  official SEC Series/Class report; official 2026 Q2 N-PORT five-file dataset.
- Produces: exact eligible product bindings, bounded `holdsSecurity` relations,
  holding-level observations, and coverage Evidence.
- Must not produce: organizer product AUM, return, NAV, fee, risk, or
  classification replacements.

- [x] **Step 1: Write current-organizer binding and authority tests**

Cover exact CIK+ticker match, duplicate organizer identifier, unmatched class,
amendment selection, filing availability, and an N-PORT holding whose ISIN
matches one organizer entity. Assert that an attempted product-level external
metric fails the Task 1 authority gate.

- [x] **Step 2: Run the focused SEC suite**

```bash
.venv/bin/python -m pytest \
  tests/ingestion/test_sec_series_class.py \
  tests/ingestion/test_sec_nport.py \
  tests/ingestion/test_official_pipeline.py -q
```

- [x] **Step 3: Reapprove or recapture immutable SEC bytes**

If the prior object checksum and official publication/availability metadata
still match, copy the bytes into the current ignored capture and generate a
current-cutoff manifest while preserving actual dates. Otherwise download once
with the configured SEC user agent and verify the official checksum/size. Do
not download a second copy merely because the organizer cutoff changed.

- [x] **Step 4: Run full bounded mapping with disk-spilled joins**

Use the existing SQLite keyed join and record batching. Preserve all source
lots, select only eligible filings, and record `COVERED`,
`PARTIALLY_COVERED`, `NOT_COVERED`, and `CONFLICT` counts. Do not claim that
the SEC population covers every organizer overseas ETF.

- [x] **Step 5: Run the configured real SEC gate**

```bash
RUN_CURRENT_SEC_TESTS=1 \
FINANCIAL_AGENT_CURRENT_ORGANIZER_ROOT=... \
FINANCIAL_AGENT_CURRENT_SEC_CAPTURE_ROOT=... \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/ingestion/test_real_current_sec.py -q
```

Expected: exact object/manifests and measured binding/coverage counts pass;
raw CIKs, tickers, holdings, and object keys are absent from BuildReport.

Result: the two prior immutable objects were reapproved without a second
download. Their SHA-256 values remained unchanged while the new manifests use
the `2026-08-24` cutoff and preserve the actual SEC publication and
availability dates. Full current-organizer mapping processed `6,037` overseas
product bindings through the disk-spilled join in `10,072` output batches:
`COVERED=6`, `PARTIALLY_COVERED=4,247`, `NOT_COVERED=1,781`, and three holding
identity conflicts. The configured deterministic ten-product real gate passed
in `230.78s`; the final focused SEC suite passed `75` tests with three
explicitly configured real-data gates skipped by default.

- [x] **Step 6: Commit the current SEC binding**

```bash
git add \
  src/financial_agent/ingestion/official/capture.py \
  src/financial_agent/ingestion/official/sec_series_class.py \
  src/financial_agent/ingestion/official/sec_nport.py \
  src/financial_agent/ingestion/official_pipeline.py \
  tests/ingestion/test_sec_series_class.py \
  tests/ingestion/test_sec_nport.py \
  tests/ingestion/test_official_pipeline.py \
  tests/ingestion/test_real_official_sources.py
git diff --cached --check
git commit -m "feat: reapprove current sec holdings"
```

---

### Task 5: Decide Public-Fund Holdings Coverage Without Guessing

**Files:**

- Create: `docs/planning/specs/public-fund-holdings-source-decision-2026-08-24.md`
- Modify: `docs/planning/specs/official-api-source-matrix.md`
- Modify: `docs/planning/specs/authoritative-data-requirements.md`
- Modify: `tests/gold/core_questions.json`
- Modify: `tests/ingestion/test_official_question_gates.py`

**Interfaces:**

- Consumes: public sources available by the cutoff and the organizer public-fund
  identifiers.
- Produces exactly one decision:
  - `approved`: a publisher-official, date-verifiable, stably bindable holdings
    source receives a separate ADR and implementation plan before ingestion;
  - `requires_data`: no source satisfies every gate, so affected questions stay
    limited and no holdings are inferred.

- [x] **Step 1: Write the source-approval checklist**

Require all of the following:

```text
publisher is regulator, association, exchange, or fund manager
publicly obtainable by 2026-08-24
actual portfolio date is preserved
publication and availability dates are verifiable
stable fund/share-class identifier binds exactly to organizer identity
constituent identifier and weight/quantity semantics are documented
coverage population is measurable
raw bytes and usage terms can be preserved
```

- [x] **Step 2: Evaluate candidates and record evidence URLs and dates**

Use only primary official pages or files. Aggregators, search snippets, inferred
portfolio text, and current pages without historical availability evidence
fail the gate. The document records each failed criterion and the affected
question IDs without copying raw organizer values.

- [x] **Step 3: Update question support deterministically**

If no source passes, keep the relevant domestic/public-fund constituent cases
as `requires_additional_data`; do not silently downgrade them to a false empty
answer. Add a test that a cross-family Samsung holding question reports the
fund coverage limitation instead of asserting that no public fund holds it.

Result: KOFIA performance comparison, KOFIA asset-management reports, KOFIA
Fund One-Click, OpenDART, and manager-site documents were evaluated against all
eight gates. None established a security-level, date-verifiable, exact
share-class-bound, measurable current-organizer population. The final decision
is `requires_data`. `REL-HOLD-001` now models the organizer's domestic ETF,
overseas ETF, and public-fund Samsung Electronics example and requires a
public-fund coverage limitation instead of a false empty result.

- [x] **Step 4: Commit the source decision**

```bash
git add \
  docs/planning/specs/public-fund-holdings-source-decision-2026-08-24.md \
  docs/planning/specs/official-api-source-matrix.md \
  docs/planning/specs/authoritative-data-requirements.md \
  tests/gold/core_questions.json \
  tests/ingestion/test_official_question_gates.py
git diff --cached --check
git commit -m "docs: decide public fund holdings coverage"
```

Stop after this task and request separate user approval if and only if a new
public-fund source passes every criterion. Do not add its adapter under this
plan without that approval.

---

### Task 6: Freeze the Stage 03 Question-Coverage Matrix

**Files:**

- Create: `docs/planning/specs/stage-03-question-coverage-2026-08-24.md`
- Modify: `tests/gold/core_questions.json`
- Modify: `tests/ingestion/test_official_question_gates.py`
- Modify: `docs/planning/specs/core-evaluation-set.md`

**Interfaces:**

- Consumes: all 52 internal cases, organizer-announced easy/medium/hard and
  answer-impossible categories, and measured source coverage.
- Produces: `supported`, `limited`, `requires_data`, or `unsupported` for every
  internal case plus coverage rules for the four organizer product families and
  five answer-impossible cases.

- [x] **Step 1: Add gold-set status validation**

Require every JSON case to contain:

```json
{
  "support_level": "supported|limited|requires_additional_data|unsupported",
  "required_sources": [],
  "closed_world_scope": null,
  "missingness_policy": "organizer_authoritative"
}
```

The validator must reject unknown sources, an empty limitation reason for a
limited case, and `closed_world_scope` on partial SEC or unapproved fund
coverage.

- [x] **Step 2: Rebase the 52 cases to measured current coverage**

Keep question wording and archetype identity stable. Change only current data
support, current required source, and limitation state. Add explicit adversarial
cases for organizer-null/external-present AUM, return, price, NAV, and risk.

- [x] **Step 3: Document hidden-evaluation family coverage**

Because the 35 exact questions are private, map the announced categories rather
than inventing question text. Cover single-family lookup, cross-family filter,
holding-to-product, sector-to-product, ranking, comparison, multi-sentence
reference, and answer-impossible families.

- [x] **Step 4: Run the question gates**

```bash
.venv/bin/python -m pytest \
  tests/ingestion/test_official_question_gates.py -q
```

- [x] **Step 5: Commit the coverage boundary**

```bash
git add \
  docs/planning/specs/stage-03-question-coverage-2026-08-24.md \
  docs/planning/specs/core-evaluation-set.md \
  tests/gold/core_questions.json \
  tests/ingestion/test_official_question_gates.py
git diff --cached --check
git commit -m "test: freeze stage 03 question coverage"
```

---

### Task 7: Build and Compare Two Clean Inactive Local Datasets

**Files:**

- Modify: `src/financial_agent/ingestion/official_pipeline.py`
- Modify: `src/financial_agent/ingestion/capacity_probe.py`
- Modify: `src/financial_agent/ingestion/cli.py`
- Modify: `tests/ingestion/test_official_pipeline.py`
- Modify: `tests/ingestion/test_capacity_probe.py`
- Create: `tests/ingestion/test_real_stage03_completion.py`
- Local ignored outputs:
  `data/generated/local-postgres/stage03-final-a/` and
  `data/generated/local-postgres/stage03-final-b/`

**Interfaces:**

- Consumes: the eight organizer workbooks and only the manifests approved by
  Tasks 2 through 5.
- Produces: two separate PostgreSQL 15 `building` datasets and a safe aggregate
  comparison report containing hashes, counts, coverage totals, and no raw
  values.

- [ ] **Step 1: Write failing final-build invariants**

Add tests for:

```python
assert report_a.dataset_manifest_hash == report_b.dataset_manifest_hash
assert report_a.component_hashes == report_b.component_hashes
assert state_a == state_b == ("building", False)
assert "KRX_ETF_DAILY" not in approved_source_codes
assert organizer_missing_external_substitute_count == 0
```

Add representative database checks:

- Samsung Electronics domestic ETF AUM top five uses KRX holding Evidence and
  organizer AUM Evidence;
- covered overseas ETF holdings return only inside the SEC bounded population;
- a public-fund holding search reports the Task 5 coverage state;
- an organizer-null AUM, return, close, NAV, or risk field never falls back to
  an external product value;
- zero remains eligible where the metric permits zero.

- [ ] **Step 2: Run the focused final-build tests against a disposable database**

```bash
FINANCIAL_AGENT_TEST_DATABASE_URL="$LOCAL_STAGE03_TEST_DATABASE_URL" \
.venv/bin/python -m pytest \
  tests/ingestion/test_official_pipeline.py \
  tests/ingestion/test_capacity_probe.py -m postgres -q
```

- [ ] **Step 3: Build database A from an empty PostgreSQL 15 cluster**

Run migrations through the current head, run `group_roles` preflight, create a
new dataset version, and execute one combined build. Do not reuse the existing
KRX-only database and do not activate the dataset.

- [ ] **Step 4: Build database B from a second empty PostgreSQL 15 cluster**

Use the same frozen inputs and a different database and dataset version. Do not
copy database A.

- [ ] **Step 5: Compare deterministic and Evidence results**

Require equality for the manifest hash, source counts, table counts,
reproducibility hash, PostgreSQL component hash, Evidence component hash, and
ordered representative query result payloads. Record measured durations and
storage sizes; do not turn local measurements into NCP claims.

- [ ] **Step 6: Run database object and permission checks on both builds**

```bash
.venv/bin/python scripts/export_database_objects.py \
  --check --database-url-env LOCAL_STAGE03_A_DATABASE_URL
.venv/bin/python scripts/export_database_objects.py \
  --check --database-url-env LOCAL_STAGE03_B_DATABASE_URL
```

Run post-migration preflight with `permission_layout=group_roles` for both URLs.

- [ ] **Step 7: Commit the final-build gate**

```bash
git add \
  src/financial_agent/ingestion/official_pipeline.py \
  src/financial_agent/ingestion/capacity_probe.py \
  src/financial_agent/ingestion/cli.py \
  tests/ingestion/test_official_pipeline.py \
  tests/ingestion/test_capacity_probe.py \
  tests/ingestion/test_real_stage03_completion.py
git diff --cached --check
git commit -m "test: verify stage 03 local completion"
```

---

### Task 8: Run the Stage 03 Completion Audit and Handoff

**Files:**

- Modify: `docs/planning/STATUS.md`
- Modify: `docs/planning/ROADMAP.md`
- Modify: `docs/planning/tasks/2026-08-27-stage-03-local-completion-plan.md`

**Interfaces:**

- Consumes: measured results from Tasks 1 through 7.
- Produces: one reviewed Stage 03 local completion record and an inactive local
  PostgreSQL handoff for Stage 04.

- [ ] **Step 1: Run focused real-source gates**

Run the configured KRX, ECOS, SEC, question-coverage, and final-build tests.
Expected: every configured real-source gate passes; an unavailable approved
credential or source is reported as an explicit unrun gate, never silently
skipped in a completion claim.

- [ ] **Step 2: Run the ordinary non-live regression**

```bash
FINANCIAL_AGENT_PROJECT_ROOT="$PWD" \
.venv/bin/python -m pytest \
  tests/contracts tests/db tests/ingestion \
  -m "not postgres and not organizer_data and not object_storage and not ncp_integration" \
  -q
```

- [ ] **Step 3: Run artifact and syntax checks**

```bash
.venv/bin/python scripts/export_contract_schemas.py --check
.venv/bin/python -m compileall -q src tests
git diff --check
```

- [ ] **Step 4: Audit the final diff**

Verify that no path under `data/`, organizer workbook, official raw object,
PDF, `.env`, `api.txt`, credential, local database, log, generated RDF, or
embedding is staged. Scan the staged diff for access keys, secret keys,
password assignments, and private-key blocks.

- [ ] **Step 5: Update status with measured facts only**

Record source snapshot counts, actual dates, coverage states, table counts,
hashes, build durations, storage sizes, test counts, the public-fund source
decision, and the inactive handoff. State explicitly that NCP readiness remains
unverified until Stage 08.

- [ ] **Step 6: Commit and push the reviewed Stage 03 completion**

```bash
git add \
  docs/planning/STATUS.md \
  docs/planning/ROADMAP.md \
  docs/planning/tasks/2026-08-27-stage-03-local-completion-plan.md \
  docs/planning/decisions/ADR-0020-treat-organizer-missingness-as-authoritative.md
git diff --cached --check
git commit -m "docs: close stage 03 local data gate"
git push -u origin codex/stage03-local-completion
```

Expected: Stage 03 is locally complete, all datasets remain inactive, and
Stage 04 may begin from the retained local handoff. Merging, activation, NCP
write, or deployment requires separate user approval.

## Self-Review Checklist

- [ ] Every ADR-0020 rule maps to a test or final database assertion.
- [ ] No task treats external availability as permission to replace an
  organizer-defined missing fact.
- [ ] KRX daily close/NAV is absent from the current combined source set.
- [ ] ETF holdings remain source-lot preserving and coverage-aware.
- [ ] Public-fund holdings has a deterministic approval-or-`requires_data`
  outcome with no unofficial fallback.
- [ ] The exact two-build interfaces, hashes, and inactive state agree across
  Tasks 7 and 8.
- [ ] The plan contains no NCP write or activation step.
- [ ] The plan contains no raw organizer value, external raw value, secret, or
  generated-data path intended for Git.
