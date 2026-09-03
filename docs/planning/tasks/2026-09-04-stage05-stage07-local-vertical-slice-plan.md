# Stage 05–07 Local Vertical Slice Implementation Plan

**Date:** 2026-09-04

**Status:** Implemented and locally verified
**Design:** [Stage 05–07 Local Vertical Slice](../specs/2026-09-04-stage05-stage07-local-vertical-slice-design.md)

## Step 1 — Freeze executable registries and adapters

- [x] Add closed Graph predicate and document-topic mappings.
- [x] Add Graph and hybrid document executor adapters.
- [x] Verify ownership, exact scope, deterministic ordering, evidence promotion, and
  fail-closed behavior with focused tests.

## Step 2 — Keep the deterministic calculation boundary fail-closed

- [x] Confirm that V2 operand `value_ref` values are not available to the executor
  and that the active similarity policy is explicitly unverified.
- [x] Preserve the production route block instead of adding an unsafe generic
  evaluator.
- [x] Verify only the registered one-input identity recipe by exact recomputation;
  reject unregistered formulas and all similarity results in the Stage 07 path.
- [ ] Add approved calculation/similarity recipes and typed literal-value handoff
  in a separate Stage 05 task before enabling those production routes.

## Step 3 — Assemble claims and EvidenceBundle

- [x] Add deterministic claim factories for direct, relation, and registered
  calculated results plus missing-data limitation assembly.
- [x] Keep closed-world/no-match claim creation deferred until a scope Evidence
  executor exists.
- [x] Add the minimal ledger read methods required for exact support recovery.
- [x] Verify that global or ambiguous Evidence references never become field claims.

## Step 4 — Implement Verifier and Claim Gate

- [x] Implement the fixed verifier rule order and disposition calculation.
- [x] Implement immutable server-owned renderer/template/slot registry checks.
- [x] Add PostgreSQL release-decision and verified-cache persistence after the pure
  contract tests demonstrate the release boundary.

## Step 5 — Implement deterministic Renderer

- [x] Render only approved claim IDs from ledger values and source locators.
- [x] Produce `answer`, `retrieved_context`, `think_trace`, bindings, and response
  hash deterministically.
- [x] Verify lossless evaluation response conversion and cache equivalence.

## Step 6 — Integrate and verify

- [x] Verify completed executors through the bounded Orchestrator registry.
- [x] Run focused unit/integration tests, PostgreSQL 15 migrations/repositories, and
  the broad non-live suite.
- [x] Inspect the final diff and staged paths for secrets, raw source data, databases,
  embeddings, and unrelated changes.
- [x] Update status and write a verification report. Commit and push only a verified,
  independently useful deliverable; do not merge to `main` without a new explicit
  merge approval.
