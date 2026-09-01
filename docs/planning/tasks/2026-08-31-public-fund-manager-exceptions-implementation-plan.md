# Public-Fund Manager Exceptions Implementation Plan

**Goal:** Apply two reviewed public-fund manager bindings and suppress the
invalid `WTREWRWE` representative grouping without changing any other manager
code behavior.

**Architecture:** Keep the public-fund mapper source-specific. A tiny exact
registry keyed by `(representative_fund_value, source_manager_code)` returns a
canonical OpenDART-backed manager only for approved pairs; all other rows use
the existing source-local path. Representative placeholder handling remains
in the existing sentinel function.

**Tech Stack:** Python 3.12, pytest, PostgreSQL 15, OpenDART corporation codes.

**Decision:** `docs/planning/decisions/ADR-0026-apply-reviewed-public-fund-manager-exceptions.md`

## Global Constraints

- Preserve organizer workbook bytes and raw field Evidence unchanged.
- Do not create a global public-fund manager-code crosswalk.
- Do not modify the unresolved 제이앤제이 or 삼성 H클럽 groups.
- Keep every organizer product row.
- Write behavior tests first and confirm their expected failures.

## Task 1: Exact Reviewed Manager Resolution

**Files:**

- Modify `src/financial_agent/ingestion/mapping/asset_managers.py`
- Modify `src/financial_agent/ingestion/mapping/public_fund.py`
- Modify `tests/ingestion/test_public_fund_mapping.py`

- [ ] Add failing tests proving both approved manager-code variants resolve to
  one canonical manager only inside their exact representative group.
- [ ] Add a failing negative test proving the same source code outside the
  approved group stays source-local.
- [ ] Run the narrow tests and confirm the current mapper fails because it
  creates source-local institutions.
- [ ] Implement the minimal exact resolver and use it in the public-fund
  manager relation path while preserving raw Evidence.
- [ ] Run the complete public-fund mapping test file.

## Task 2: Invalid Representative Placeholder

**Files:**

- Modify `src/financial_agent/ingestion/mapping/public_fund.py`
- Modify `tests/ingestion/test_public_fund_mapping.py`
- Modify `tests/ingestion/test_real_organizer_data.py`

- [ ] Add a failing test proving case-insensitive `WTREWRWE` produces a
  placeholder observation and no `hasShareClass` relation.
- [ ] Confirm the test fails because the mapper currently creates a synthetic
  representative product.
- [ ] Add `WTREWRWE` to the bounded representative sentinel set.
- [ ] Update the real-data audit expectation to count the newly recognized
  placeholder without changing the raw row count.
- [ ] Run narrow and real-data-gated public-fund tests.

## Task 3: Rebuild and Inventory Verification

**Files:**

- Do not commit the organizer workbooks, local database, or generated reports.

- [ ] Run the affected ingestion and document-target tests.
- [ ] Rebuild the local `organizer-dart-2026-08-24-v1` dataset using the
  approved organizer workbooks.
- [ ] Verify the two reviewed groups each have one official DART manager,
  `WTREWRWE` creates no representative relation, and only the 제이앤제이 and
  삼성 H클럽 groups remain unresolved.
- [ ] Inspect the final diff, staged paths, and repository status for raw data,
  credentials, databases, PDFs, or generated outputs.
