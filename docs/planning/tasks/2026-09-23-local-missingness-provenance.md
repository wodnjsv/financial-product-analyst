# Local missingness and source display — 2026-09-23

User approved correcting missing-data handling and provenance display. Continue
existing personal local branch, preserving prior work. Relevant decisions:
ADR-0007 deterministic rendering; ADR-0014 source snapshots; ADR-0020 missing
versus zero; ADR-0050 bounded local profile. Existing accepted approvals cover
this scope; no additional model calls or production rollout.

## Findings and choice

50 selected KRX captures contain 2,952 raw rows: 19 populated weights and
2,933 blank weights. PostgreSQL has 2,925 resolved holdings: 19 present weights
and 2,906 unknown/SOURCE_VALUE_MISSING. All 9 Samsung common-stock rows are
blank in source. Verify exact evidence-to-source values and source checksums
before concluding no recoverable ingestion loss. Unresolved raw rows are not
proof of absent holdings.

Do not substitute newer/older dates or derive weight from valuation amounts;
these change semantics. Preserve unknowns and explicitly disable complete
ranking when any matched weight is missing or completeness is unknown.

## Implementation and success criteria

1. Add repeatable read-only audit of selected source captures and DB evidence;
   report mismatches and distinguish unresolved raw rows from missing weights.
2. Add server-owned local result rendering: dataset, returned/matched counts,
   known/missing weights, rank availability, row date/status, observation and
   holding evidence locators, document filing/attachment and page-range labels.
   Distinguish zero from null and incomplete source metadata from complete
   provenance. Missing information is reported, not silently omitted.
3. Wire a saved-result text CLI to the renderer and existing validation/quote
   functions. Deterministic output replaces old model prose for these local
   result logs; it does not certify the old prose or integrate the full service.
4. Test zero/null/mixed/unknown coverage, source omissions, malformed counts,
   workbook/CSV sources, document page ranges, and no input mutation.
5. Replay Q1/Q2/Q3 without touching original records. Q2 must state 9/0/9,
   refuse ranking, show 5 examples and source CSV rows. Q3 must label 58 as a
   count and preserve exact quotes. Audit live DB and selected sources read-only.

Non-goals: new external collection, hypothetical imputation, production provider
integration, bulk reload, changes to raw data, commit/push. If no retained raw
weight is recoverable, data supplementation remains explicitly unresolved.

## Results

- 129 related release, contract, KRX ingestion, and audit tests passed. New
  renderer tests first failed for the absent module, then passed after implementation.
- Read-only audit verified all 50 source checksums and 2,925 DB observations:
  no value/status/reason mismatches; 19 known values in both raw sources and DB.
  27 raw rows have no weight observation; none contains a populated weight.
- No source value is available to restore the nine missing Samsung weights.
  Supplementation remains unresolved; no database values were imputed or changed.
- Saved three-query replay renders all source locators and dates. Q2 reports
  matched 9, known 0, missing 9, displayed 5, ranking unavailable. Q3 reports
  58 as document count and preserves literal excerpts. Original SHA256 unchanged.
- Text log: parent workspace data/personal-search-20260918/source-display-20260923.txt.
  Audit: parent workspace data/personal-search-20260918/holdings-audit-20260923.json.
- Files remain local; no live model call, production rollout, commit, or push.
