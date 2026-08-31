# Canonical Asset-Manager Identity Implementation Plan

**Goal:** Canonicalize organizer ETF manager names into OpenDART-backed
institutions while preserving raw Evidence and safe conflict handling.

**Architecture:** A small pure registry resolves exact reviewed aliases and
known organizer manager codes. Existing source-specific mappers continue to
own row parsing and Evidence, but use the registry's source-independent
institution identity for reviewed managers.

**Tech Stack:** Python 3.12, pytest, SQLAlchemy, PostgreSQL 15, OpenDART
corporation codes.

**Spec:** `docs/planning/specs/2026-08-31-canonical-asset-manager-identity-design.md`

## Global Constraints

- Preserve organizer workbook bytes and raw field Evidence unchanged.
- Use no fuzzy, prefix, substring, or product-name inference in production.
- Keep ETN `issuedBy` behavior unchanged.
- Do not commit organizer workbooks, credentials, databases, or generated
  reports.
- Write each behavior test first and verify its expected failure before
  implementation.

## Task 1: Pure Asset-Manager Registry

**Files:**

- Create `src/financial_agent/ingestion/mapping/asset_managers.py`
- Create `tests/ingestion/test_asset_managers.py`

**Produces:** `resolve_etf_asset_manager(cu_name, refinitiv_name)` returning an
immutable resolution with canonical key, name, DART code, accepted aliases,
supporting inputs, and conflicting inputs.

- [x] Add failing tests for Samsung bilingual resolution, malformed Korean
  input with valid Refinitiv resolution, blank-Refinitiv brand resolution,
  reviewed-manager conflict, exact-equal fallback, single-value source-local
  preservation, and blank-or-dot absence.
- [x] Run `pytest tests/ingestion/test_asset_managers.py -q` and confirm failure
  because the registry module does not exist.
- [x] Implement the 29-entry reviewed registry and exact resolver.
- [x] Re-run the test file and confirm it passes.

## Task 2: Domestic ETF Mapping

**Files:**

- Modify `src/financial_agent/ingestion/mapping/domestic_etp.py`
- Modify `tests/ingestion/test_domestic_etp_mapping.py`

**Consumes:** Task 1 ETF resolution.

**Produces:** canonical `managedBy` institution, aliases, DART identifier, and
field-level relation or fallback Evidence.

- [x] Add a failing KODEX-style mapping test asserting canonical
  `삼성자산운용`, the reviewed institution ID, `DART_CORP_CODE=00260453`, and
  both accepted source aliases.
- [x] Add a failing malformed-Korean-value test asserting that Refinitiv still
  resolves the manager and the malformed product name is not registered as an
  alias.
- [x] Run the two narrow tests and confirm the current literal-conflict mapper
  fails them.
- [x] Change only ETF manager relation construction to consume the registry;
  retain the existing fallback path for unsupported and conflicting inputs.
- [x] Run the complete domestic ETP mapping tests.

## Task 3: DART Target and Real-Data Verification

**Files:**

- Modify `tests/db/test_document_target_repository.py` if a canonical-name
  assertion is not already covered.
- Do not create or commit a real-data fixture.

- [x] Add or update a PostgreSQL repository test proving an ETF target returns
  its canonical manager entity and name.
- [x] Run the narrow PostgreSQL test against PostgreSQL 15.
- [x] Run the organizer-gated ETF mapping audit and record aggregate counts for
  all 1,235 rows without exposing workbook rows.
- [x] Run the DART one-product KODEX test and verify exact official-name or
  official-identifier publisher binding.
- [x] Run the affected ingestion suite, inspect the diff, and verify no raw
  data, API key, PDF, database, or generated report is staged.
