# V2 Korean Overlay V4 Adoption Plan

**Date:** 2026-09-04

**Status:** Complete

**Goal:** Make the default V2 resolver use the reviewed Korean V4 overlay
without changing its bounded request-local candidate and HCX selection
architecture.

## Assumptions and constraints

- V2 remains the production default and V3 remains shadow-only.
- No SQL, query-contract, routing, executor, public API, or provider-setting
  behavior changes in this task.
- Preferred Korean labels are unique server-owned semantic names and may be
  offered as advisory candidates without becoming exact locks; arbitrary
  model-authored IDs remain forbidden.
- No credentials, organizer data, live payloads, or generated runtime outputs
  are committed.

## Verifiable success criteria

- [x] A regression test fails while V2 still reads V3.
- [x] A regression test fails while a V4-only preferred label cannot become a
  V2 request-local candidate.
- [x] V2 and V3 loaders pin the same V4 overlay version and hash.
- [x] `잔여일수` resolves to the registered `remaining_days` candidate while
  the returned candidate set stays smaller than the full semantic catalog.
- [x] Changed candidate semantics have new reproducibility version pins.
- [x] Focused intent tests and the broader offline regression suite pass.
- [x] Schema freshness, Python compilation, and diff checks pass; staged-secret
  and staged-data checks run immediately before commit.
- [x] The verified branch is committed, pushed, merged to local `main`, tested
  again, and the resulting `main` is pushed to GitHub.

## Non-goals

- Promoting V3 or changing its acceptance thresholds.
- Expanding free-form Korean aliases beyond the existing reviewed V4 content.
- Running live HCX or PostgreSQL acceptance tests.

## Local verification

- Intent, intent-evaluation, query-contract evaluation, and planning:
  `1032 passed`.
- Broad offline suite excluding explicit NCP, live, PostgreSQL, and Jena
  integration markers: `2460 passed, 13 skipped, 451 deselected`.
- Python compilation and V1, V2, and V3 intent-schema freshness checks exited
  successfully.
- No live HCX, PostgreSQL, organizer-data, Object Storage, or Jena acceptance
  run was performed by this change.
- Local `main`, `origin/main`, the feature branch, and its remote branch were
  verified at commit `a03d34bd3027c92ef0132932bdfdc5cf85104de7` before this
  closure record.
