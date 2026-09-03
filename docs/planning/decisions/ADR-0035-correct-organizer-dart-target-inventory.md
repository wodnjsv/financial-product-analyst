# ADR-0035: Correct the Organizer DART Target Inventory

**Date:** 2026-08-31

**Status:** Accepted

**Approved:** 2026-08-31 — the user required every DART PDF target to come
from and match the organizer competition data.

**Supersedes:** The public-fund target-count assumptions in
[ADR-0034](ADR-0034-discard-dart-pdfs-after-verified-corpus-ingestion.md) and
the related DART corpus design. It does not change the approved PDF retention,
Claim selection, or source-authority rules.

## Context

The first DART corpus estimate treated 6,885 distinct raw
`rptt_ksd_itm_no` values as nonblank representative-fund identifiers and
treated only 120 blank rows as ungrouped. A direct reconciliation against the
current `2026-08-24` organizer workbook showed that the 6,885 distinct values
also included the blank value, `KR0000000000`, and five all-zero renderings of
the documented missing-value sentinel.

The authoritative aggregate is:

- 1,780 domestic ETP rows: 1,235 ETF and 545 ETN;
- 23,676 public-fund share-class rows;
- 6,878 valid distinct representative-fund identifiers;
- 120 blank representative values;
- 5,309 `KR0000000000` sentinel rows;
- 1,653 all-zero sentinel rows, including 1,645 stored as
  `000000000000`; and
- 217 exact domestic-ETP/public-fund identity overlaps.

Grouping these sentinels as real representative funds would attach one
document target to thousands of unrelated organizer products.

## Decision

- Derive DART targets only from organizer-created products carrying the exact
  source-local `PREF01_PD_ITM_NO` or `PRFD_ITM_NO` marker.
- Treat blank, `KR0000000000`, and every all-zero representative value as
  missing. They never create a representative group. This includes numeric
  Excel cells read as `0`, `00`, `00000`, or `0000000` after formatting loss.
- Group public-fund share classes only through the normalized exact
  `hasShareClass` relation produced from a valid organizer representative
  value. A missing, ambiguous, self-referential, or cyclic relation remains an
  explicit product target with a bounded later disposition.
- Apply the accepted canonical identity rule to the 217 exact overlaps. The
  domestic ETP owns the canonical product and is counted once; its public-fund
  source row cannot create a second DART download target.
- Freeze the reconciled PostgreSQL inventory at 25,239 canonical organizer
  products and 15,569 DART targets: 1,780 domestic ETP targets and 13,789
  public-fund targets.
- Do not issue a DART request until this organizer inventory and its canonical
  hash have been produced. DART results can reduce coverage through a bounded
  failure or not-applicable disposition, but cannot add a target.

## Rejected Alternatives

### Treat every nonblank raw value as a representative identifier

Rejected because the nonblank sentinel families are documented missing values and
would create false many-product document bindings.

### Drop products without a valid representative identifier

Rejected because those products still exist in the organizer evaluation
universe. They require an exact alternate binding or an explicit failure
disposition.

### Let DART discovery repair or expand the target list

Rejected because the organizer snapshot is authoritative and DART is only a
document source for already selected products.

## Consequences

- The corpus run may contain more public-fund targets than the earlier
  estimate, but it cannot silently merge unrelated funds.
- Publisher batching and document deduplication remain necessary to keep API
  traffic and stored chunks bounded.
- Aggregate counts and the inventory hash are sufficient for reconciliation;
  organizer rows and real reports remain outside Git.
