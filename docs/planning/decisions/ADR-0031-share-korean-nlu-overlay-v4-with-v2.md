# ADR-0031: Share Korean NLU Overlay V4 with V2

**Date:** 2026-09-04

**Status:** Accepted

**Approved:** 2026-09-04 — the user approved retaining the V2 request-local
candidate and HCX selection flow while adopting the Korean V4 overlay, then
committing, merging to `main`, and pushing the verified result.

**Amends:** [ADR-0030](ADR-0030-use-hybrid-full-catalog-semantic-linking.md)
only where it freezes V2 to the V3 overlay bytes. V3 remains shadow-only and
its promotion gates are unchanged.

## Context

V4 added Korean preferred labels and disambiguation for registered meanings
such as `nav`, `yield_rate`, `remaining_days`, and `remaining_maturity`, but
only the shadow V3 loader consumed that file. V2 remained pinned to V3, and a
preferred label with no explicit alias was metadata rather than a usable V2
candidate. Merely pointing V2 at the V4 file would therefore leave some of the
new Korean mappings ineffective in the request-local candidate flow.

## Decision

- Both V2 and shadow V3 compile `korean-nlu-overlay.v4.json`.
- V2 retains its existing request-local, bounded candidate generation and one
  normal HCX chooser call. It does not receive the full compact catalog.
- Every unique overlay `preferred_label` is offered as a request-local advisory
  candidate. It is not added to the deterministic alias-lock registry;
  explicit aliases retain their declared direct, ambiguous, or group behavior.
- Canonical IDs, ontology applicability, query-contract solving, physical
  bindings, and deterministic execution remain server-owned and fail closed.
- The changed candidate construction is identified by new V2, V3-hint, and
  internal semantic-candidate policy version pins; resolver schemas and prompt
  formats do not change.
- V3 remains shadow-only; sharing the language overlay is not a promotion.

## Rejected Alternatives

- **Keep V2 on V3:** rejected because it preserves avoidable divergence and
  makes reviewed V4 Korean labels unavailable to the default resolver.
- **Promote V3:** rejected because its measured HCX quality and provider gates
  remain below the accepted thresholds.
- **Treat preferred labels as display-only:** rejected because V2 could load
  V4 while still failing to offer those exact Korean meanings to HCX.
- **Create a duplicate V5 overlay:** rejected because no new vocabulary is
  needed and a second copy would introduce version drift.

## Consequences

- V2's pinned overlay version, hash, prompt inputs, and candidate manifest
  intentionally change and require fresh regression verification.
- The held-out request-local candidate recall diagnostic changes from
  `123/196` to `134/196`; the `>=99%` promotion gate still fails.
- Exact use of a unique preferred Korean label becomes an HCX-selectable
  request-local candidate without silently becoming a deterministic lock.
- Existing V2 artifacts remain readable, but new runs identify the V4 overlay.
- Historical V3 fixtures and verification records remain unchanged.
