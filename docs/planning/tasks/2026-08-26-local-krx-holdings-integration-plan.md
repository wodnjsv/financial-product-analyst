# Local KRX ETF Holdings Integration Implementation Plan

> **Execution note:** Follow the repository planning harness and the approved
> TDD cycle. Keep raw organizer and KRX files outside Git. Do not write NCP or
> activate a dataset in this plan.

**Goal:** Bind all approved `2026-08-22` KRX ETF portfolio files to the latest
organizer domestic ETF products, normalize their holdings as existing
`holdsSecurity` relations with numeric observations and row-level Evidence,
and prove representative holdings queries against an inactive local dataset.

**Architecture:** Reuse the Stage 02 PostgreSQL ledger, the organizer-authority
identity index, the existing KRX PDF parser/mapper, and the approved 13-relation
ontology vocabulary. The organizer's validated six-character `pd_ticker` is
the exact domestic ETF binding axis. KRX security identifiers resolve through
the official security index; unresolved non-corporate rows remain explicit
source-local securities and limited Evidence. No fuzzy name matching and no
new physical table or ontology predicate are introduced.

**Current inputs:**

- Organizer workbook:
  `ai-festival2026_금융상품Agent_DtataSet260824/pref01n001_data.xlsx`
- KRX holdings directory:
  `data/official/krx_etf_pdf/2026-08-22/`
- Approved availability cutoff: end of `2026-08-24` Asia/Seoul
- Holdings applicable date: `2026-08-22`

## Assumptions

- The latest organizer workbook is authoritative when an organizer fact and
  an external fact conflict.
- Eligible organizer holdings population means `pd_grp_no == ETF`, a valid
  unique six-character `pd_ticker`, and no listing end before `2026-08-22`.
- Every approved file is named `<pd_ticker>_20260822.csv` and follows the fixed
  CP949 KRX header contract.
- A file missing from the approved population means uncovered data, not proof
  that the ETF has no constituents.

## Non-goals

- NCP database, Object Storage, Fuseki, load-balancer, or public API acceptance.
- Dataset activation.
- Public-fund constituent holdings or new overseas source acquisition.
- Fuzzy product matching, name-based identity promotion, or ontology expansion.
- Reworking the already approved KRX numeric semantics.

## Verifiable Success Criteria

1. Exactly 1,161 eligible organizer ETFs, 1,161 unique KRX filenames, and 1,161
   exact `pd_ticker` bindings are reported, with zero missing, extra, duplicate,
   or malformed binding axes.
2. Every non-summary KRX row produces one `holdsSecurity` relation, four
   relation-bound observations, relation Evidence, and observation Evidence.
3. Applicable dates remain `2026-08-22`; cutoff/availability remains bounded by
   `2026-08-24`; no fact is relabeled to a later applicable date.
4. Two local builds from the same bytes produce identical manifest/component
   hashes and aggregate relation, observation, Evidence, and issue counts.
5. A representative local query can find ETFs holding Samsung Electronics and
   order those products deterministically by the organizer-authoritative AUM,
   while returning Evidence locators for both membership and AUM.
6. The focused suite and the broader non-live contract/database/ingestion suite
   pass, and no raw data, workbook, manifest payload, credential, or local DB is
   staged.

## Alternatives and Trade-offs

- Deriving the KRX code from ISIN is historically compatible but duplicates a
  direct organizer field and can hide malformed current rows. Use `pd_ticker`.
- Requiring KRX daily market data before holdings mapping adds an unnecessary
  dependency. Use the organizer ticker for holdings and keep daily price/NAV
  validation as a separate source gate.
- Creating a new holding table would simplify one query but duplicate the
  approved Relation/Observation/Evidence model. Reuse the existing model.

---

### Task 1: Freeze the Current Binding and Date Contracts

**Files:**

- Modify: `src/financial_agent/ingestion/official/capture.py`
- Modify: `src/financial_agent/ingestion/official/krx_holdings.py`
- Modify: `tests/ingestion/test_real_official_sources.py`
- Modify: `tests/ingestion/test_krx_holdings.py`

- [x] Add failing tests for the `2026-08-22` KRX applicable date and
  `<ticker>_20260822.csv` contract.
- [x] Add failing tests proving exact organizer `pd_ticker` binding succeeds
  without deriving a code from ISIN or using a product name.
- [x] Add malformed, duplicate, missing, and extra ticker/file fail-closed
  cases with literal expected counts.
- [x] Implement the minimum date and binding changes and rerun the focused
  tests.

### Task 2: Integrate Holdings Without a Market-Data Dependency

**Files:**

- Modify: `src/financial_agent/ingestion/official_pipeline.py`
- Modify: `tests/ingestion/test_official_pipeline.py`
- Modify: `tests/ingestion/test_official_question_gates.py`

- [x] Add a failing pipeline test with organizer plus KRX holdings and no KRX
  daily snapshot.
- [x] Build the holdings binding map from organizer `pd_ticker`; use KRX daily
  only for its own price/NAV facts and coverage audit.
- [x] Verify fixed source ordering, organizer-authority entity reuse, bounded
  coverage, and no duplicate product entity.

### Task 3: Verify the Real 1,161-File Inventory Locally

**Files:**

- Modify: `tests/ingestion/test_real_official_sources.py`
- Create or modify only if needed: a small deterministic inventory helper under
  `src/financial_agent/ingestion/official/`

- [x] Run a gated read-only test over the actual ignored organizer workbook and
  KRX directory.
- [x] Verify headers, checksums, non-empty rows, exact filename set, applicable
  date, and aggregate constituent counts.
- [x] Generate canonical ignored manifests from the approved bytes and verify
  they reload byte-for-byte. Do not publish them to NCP.

### Task 4: Prove the Local PostgreSQL Ledger and Query Path

**Files:**

- Create: `tests/ingestion/test_real_current_krx_holdings.py`
- Reuse: `src/financial_agent/ingestion/capacity_probe.py`
- Reuse: `src/financial_agent/ingestion/official_pipeline.py`

- [x] Load organizer plus KRX holdings into a fresh inactive local PostgreSQL
  dataset using the existing migrations and writer.
- [x] Repeat the build in a second fresh dataset/database and compare hashes and
  aggregate counts after excluding database-generated timestamps.
- [x] Execute the Samsung Electronics membership plus organizer AUM ranking
  query and verify deterministic order, source dates, and Evidence locators.
- [x] Confirm the current dataset remains inactive and runtime writes remain
  outside this plan.

**Measured result (2026-08-27):** Two fresh local PostgreSQL 15 databases
produced the same manifest
`55ca10de77068b42947f9cbe0e0ef2095938e55ba5cc162bc7ea3f10858a978a`,
reproducibility hash
`dd79cff75807b62c325c9c687510cb3c16b3d405ed1db0fcf45ef270e1fc84dc`,
PostgreSQL component hash
`4cd43fa48179de735c7884cb7fc77ae6873d8526a5da726eb46d7775f10e2602`,
and Evidence component hash
`6b87dd1ea57304efb593902c6069b9fcb1ad2b4e675443330e7932c57c460c25`.
Each build contained 77,832 entities, 58,651 products, 152,555 relations,
3,859,702 observations, and 4,042,495 Evidence records. The second build
completed in 9,358.67 seconds and passed the Samsung Electronics AUM top-five
query with KRX holding date `2026-08-22`, organizer AUM date `2026-08-21`,
both source locators, `status=building`, and no active pointer for the current
dataset. Local `group_roles` postflight and the reviewed database-object
manifest check also passed.

The retained local handoff is the ignored PostgreSQL 15 cluster at
`data/generated/local-postgres/current-krx-pg15/data`, database
`financial_agent_krx_local_b`, port `55434`. It remains `building` and
inactive for Stage 04 development; it is not a deployment artifact.

### Task 5: Regression and Repository Audit

- [x] Run the focused KRX, official pipeline, question-gate, and real-source
  tests.
- [x] Run the broader non-live contract, database, and ingestion tests.
- [x] Check contract schemas and database object manifests.
- [x] Inspect the final diff and staged paths for raw data and secrets.
- [x] Update `STATUS.md` with measured results only; do not claim NCP readiness.

**Verification result (2026-08-27):** The real 1,161-file inventory gate
passed in 66.97 seconds, the focused suite passed 47 tests, and the broader
non-live contract/database/ingestion suite passed 683 tests with 334 explicitly
deselected live or infrastructure cases. Contract Schema freshness, Python
compilation, PostgreSQL object-manifest parity, postflight, and `git diff
--check` passed. The changed-path audit found no organizer workbook, KRX raw
file, `data/` payload, environment file, credential, or local database.

## Completion Gate

This plan is complete only when all six success criteria pass locally. The
result is an inactive local data boundary that Stage 04 can consume. NCP
acceptance remains mandatory under ADR-0019 and occurs only in the final
deployment stage.
