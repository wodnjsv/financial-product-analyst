# ADR-0040: Block Unusable Representative Values Before DART Discovery

**Date:** 2026-09-01

**Status:** Accepted

**Approved:** 2026-09-01 — the user directed that products whose organizer
representative value is `WTREWRWE` must not be downloaded because the value
does not identify a representative fund.

**Supersedes in part:** The 15,569-target count in
[ADR-0035](ADR-0035-correct-organizer-dart-target-inventory.md).

## Context

ADR-0037 correctly changed `WTREWRWE` from a representative-fund identifier to
a missing-value placeholder. Rebuilding the organizer dataset therefore
removes one false three-product representative group and restores its three
member products as individual organizer targets. The deterministic inventory
changes from 15,569 to 15,571 targets: three individual targets are added and
one false group is removed.

Those products remain authoritative organizer products, but the placeholder
cannot establish which DART prospectus represents them. Their valid manager
relations alone are insufficient to authorize document collection.

## Decision

- Freeze the corrected inventory at 25,239 organizer products and 15,571 DART
  targets: 1,780 domestic ETP and 13,791 public-fund targets.
- Preserve each affected product as an individual target and preserve the raw
  `WTREWRWE` Evidence.
- Mark a public-fund target with `representative_identifier_unavailable` when
  its exact organizer representative field contains `WTREWRWE`. Do not apply
  the block to a canonical domestic-ETF target merely because an overlapping
  public-fund source row preserved the same raw value.
- Partition these targets out before publisher reconciliation, DART discovery,
  attachment download, and PDF processing.
- Count the blocked targets as explicit bounded failures in run reconciliation;
  do not drop them from the organizer inventory or infer another identifier.
- Continue DART collection only for targets without a block reason and with an
  exact official publisher binding.

## Consequences

- The corrected inventory contains two more targets than ADR-0035, but no
  `WTREWRWE` product can issue a DART request.
- Full-run reconciliation remains closed: indexed plus bounded failures must
  equal all 15,571 targets.
- Existing DART documents and already verified non-placeholder targets are
  unaffected.
