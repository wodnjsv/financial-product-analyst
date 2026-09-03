# Canonical Asset-Manager Identity Design

**Date:** 2026-08-31

**Status:** Approved

## Goal

Represent one asset manager as one institution even when the organizer ETF
master supplies a Korean abbreviation, a brand-prefixed value, a malformed
product-name value, and a Refinitiv English legal name for the same company.
Make the resulting institution directly usable for exact OpenDART publisher
reconciliation without changing the organizer source bytes.

## Scope

- Domestic ETF `managedBy` relations from `cu_fund_mgmt_co` and
  `ref_fund_mgmt_co`.
- Canonical institution entities, reviewed aliases, and official
  `DART_CORP_CODE` identifiers.
- DART target enumeration through the existing `managedBy` relation.

ETN issuer normalization, inference from product names, and public-fund
external manager-code translation are not part of this change.

## Authority and Resolution

The registry contains the 29 nonblank Refinitiv ETF manager names present in
the organizer snapshot and their OpenDART Korean corporation names and
corporation codes verified on 2026-08-31. It also contains short Korean brand
aliases required by the 27 ETF rows without a Refinitiv value.

Resolution is deterministic:

1. Resolve each nonblank source value only by an exact reviewed alias.
2. When both values resolve to the same institution, use that institution and
   attach both source fields as relation Evidence.
3. When the Refinitiv value resolves and the Korean value is unrecognized,
   use the Refinitiv result; retain the Korean raw value as fallback Evidence,
   but do not register it as an alias.
4. When only the Korean value resolves, use it.
5. When the two values resolve to different institutions, create no relation
   and report a source conflict.
6. Preserve the prior exact-equal fallback for synthetic or future values not
   yet in the registry. It does not receive a DART identifier.
7. Preserve a single nonblank, non-dot unreviewed organizer value as a
   source-local manager. Do not attach it to a reviewed canonical manager or
   assign a DART identifier.

No substring, prefix, fuzzy, product-brand, or product-name inference is
allowed at ingestion time.

## Canonical Records

Every reviewed manager produces:

- one source-independent institution ID derived from the registry key;
- the OpenDART Korean corporation name as `canonical_name`;
- one `asset_manager` institution row;
- one `DART_CORP_CODE` identifier;
- only reviewed source values as aliases; and
- the existing `managedBy` relation and field-level Evidence.

The organizer workbook values remain immutable. Canonicalization changes only
the normalized projection.

## Missing-Value and Public-Fund Boundary

Only a blank value or the literal `.` means that the ETF manager is absent.
Nonblank reviewed values such as `TIGER`, `ACE`, and `삼성` remain eligible for
exact registry resolution. Other single nonblank values remain source-local
rather than being dropped or guessed. A product name accidentally placed in
the manager column is not an alias when the other source column supplies the
reviewed official manager.

The public-fund master contains `or_co_xtn_itt_cd`, an external institution
code, but no manager-name column. This change does not translate that code by
using ETF overlaps or fund-name inference. The public-fund mapper retains the
organizer code as its source-local value.

## Verification

- KODEX 200 resolves to `삼성자산운용` and DART code `00260453`.
- A malformed Korean manager cell plus a valid Refinitiv name still resolves,
  while the malformed value is not added as an alias.
- Conflicting reviewed managers create no relation.
- All 1,235 organizer ETF rows are accounted for with resolved, unresolved,
  or conflict dispositions.
- DART target enumeration returns canonical manager names for resolved ETFs.
- Raw source values and Evidence remain available.
