# Final Public-Fund Manager Groups Implementation Plan

**Goal:** Apply the two final reviewed representative-group manager bindings
and measure the remaining DART document-collection coverage.

**Decision:**
`docs/planning/decisions/ADR-0038-resolve-final-public-fund-manager-groups.md`

## Constraints

- Preserve organizer source values and Evidence.
- Match only exact reviewed `(representative_fund_id, manager_code)` pairs.
- Do not treat manager mapping as proof that a prospectus exists in DART.
- Do not download or commit organizer raw data during this task.

## Task 1: Final Exact Manager Bindings

- [x] Add failing tests for both source-code variants in the J&J group.
- [x] Add failing tests for both source-code variants in the Samsung H Club
  group.
- [x] Implement the four exact pair bindings.
- [x] Verify unrelated uses of the same source codes remain source-local.

## Task 2: Collection Readiness Audit

- [x] Verify all reviewed multi-manager groups are resolved or explicitly
  unavailable.
- [x] Inspect the DART target and batch pipeline prerequisites.
- [x] Separate products eligible for automatic download from products with no
  DART filing, no canonical manager, or no cutoff-eligible prospectus.
- [x] Report whether the remaining corpus can be processed now and identify
  any blocking categories before starting a full download.

## Audit Result

- The public-fund workbook contains 23,676 rows, 275 distinct source manager
  codes, and 13,965 representative targets after placeholder handling.
- The reviewed exact exceptions cover 4 targets and 15 rows. They resolve all
  genuine multi-manager representative groups; `WTREWRWE` is unavailable.
- The other public-fund manager codes remain source-local by design and cannot
  yet be reconciled to OpenDART publishers.
- Target composition is 6,012 public-only, 7,950 private-only, and 3 mixed
  public/private targets. A manager binding does not imply a DART prospectus,
  especially for private funds.
- The full DART CLI still uses `WhitespaceTokenCounter`; an embedding-model
  tokenizer must replace it before the final full-corpus chunk run.
