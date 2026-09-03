# ADR-0038: Resolve Final Public-Fund Manager Groups

**Date:** 2026-08-31

**Status:** Accepted

**Approved:** 2026-08-31 — the user approved applying the reviewed findings
for the remaining J&J and Samsung H Club representative-fund groups.

**Supersedes in part:** [ADR-0037](ADR-0037-apply-reviewed-public-fund-manager-exceptions.md)

## Context

ADR-0037 left two representative-fund groups unresolved pending official
evidence. That evidence is now available:

- The official TheJ history records the 2016 change to 제이앤제이자산운용,
  the launch of J&J private funds, and the 2022 change to 더제이자산운용.
  A separately incorporated current 제이앤제이자산운용 is not the same
  legal entity.
- Samsung Hedge Asset Management officially disclosed the 2021 transfer of
  its Equity Hedge business. The Samsung H Club Equity Hedge group belongs to
  the transferred business now managed by 삼성액티브자산운용.

## Decision

- Resolve both source-manager variants in representative group
  `034790011100` to 더제이자산운용 (`DART_CORP_CODE=00883078`).
- Resolve both source-manager variants in representative group
  `2000102M9920` to 삼성액티브자산운용
  (`DART_CORP_CODE=01194731`).
- Keep the exception key bounded to the exact pair of representative-fund
  value and source manager code.
- Preserve every organizer source code and its raw field Evidence.
- Do not infer a global public-fund manager-code crosswalk.

## Consequences

- The five reviewed multi-manager representative groups now have a canonical
  manager decision or, for `WTREWRWE`, an explicit unavailable-data decision.
- Canonical manager coverage improves DART target discovery, but it does not
  guarantee that every product has a DART-filed investment prospectus.
- Private funds and products without an eligible official filing remain
  explicit document-unavailable cases.
