# ADR-0036: Canonicalize Organizer Asset Managers

**Date:** 2026-08-31

**Status:** Accepted

**Approved:** 2026-08-31 — the user approved unifying asset-manager names
before continuing the organizer-bound DART corpus run.

**Related:** [ADR-0013](ADR-0013-use-lean-source-specific-ingestion.md),
[ADR-0016](ADR-0016-use-2026-08-24-organizer-baseline.md),
[ADR-0018](ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md),
[ADR-0035](ADR-0035-correct-organizer-dart-target-inventory.md)

## Context

All 1,235 organizer ETF rows contain `cu_fund_mgmt_co`; 1,208 also contain
`ref_fund_mgmt_co`. The values describe the same manager in different forms,
for example `삼성` and `Samsung Asset Management Co Ltd`. The existing mapper
compares normalized strings literally, treats all 1,208 bilingual pairs as
conflicts, and therefore creates only 27 ETF `managedBy` relations. OpenDART
publisher batching then lacks the manager identity required to discover the
organizer-matched prospectus.

The Korean column also has malformed product-name values. Selecting that
column unconditionally would create false institutions. The public-fund
master exposes manager codes rather than names, so a complete cross-family
name mapping cannot be inferred safely from that file alone.

## Decision

- Introduce a reviewed, deterministic asset-manager registry for the 29
  nonblank Refinitiv ETF manager names in the `2026-08-24` organizer snapshot.
- Use the corresponding OpenDART Korean corporation name as the canonical
  display name and retain the verified `DART_CORP_CODE` identifier.
- Resolve Korean abbreviations, brands, and English names only through exact
  reviewed aliases. Do not use fuzzy or substring matching in production.
- Use one source-independent institution ID for the same reviewed manager
  across organizer source modules.
- Preserve every organizer raw value and its Evidence. An unrecognized value
  may not become an institution alias merely because the other field resolves.
- Treat two different reviewed resolutions as a real conflict and create no
  relation.
- Treat only blank and literal `.` ETF manager values as absent. Nonblank
  reviewed values in the organizer manager field remain eligible for exact
  registry resolution.
- Preserve a single nonblank unreviewed ETF manager value as source-local;
  never force it onto a reviewed canonical manager or DART corporation code.
- Do not translate public-fund external institution codes into manager names
  through ETF overlaps or fund-name inference.
- Keep ETN `issuedBy` behavior unchanged.

## Rejected Alternatives

### Prefer `cu_fund_mgmt_co` verbatim

Rejected because the column contains abbreviations, brands, a dot placeholder,
and product names in place of manager names.

### Prefer `ref_fund_mgmt_co` verbatim

Rejected because 27 ETF rows are blank and an English source label is not the
official Korean OpenDART corporation identity.

### Fuzzy-match every value at ingestion time

Rejected because similar asset-manager names can bind to the wrong legal
entity and make official documents appear to support the wrong product.

### Infer every public-fund manager from its product name

Rejected because the organizer supplies only an external institution code and
fund-name prefixes are not authoritative identity keys.

## Consequences

- Resolved ETF products expose a usable canonical `managedBy` relation for
  Graph, PostgreSQL, Evidence, and DART retrieval.
- Rebuilding the organizer dataset is required because canonical institution
  IDs and relation objects change.
- The registry is intentionally small and must be updated through reviewed
  source evidence when the organizer snapshot changes.
- Public-fund manager codes remain source-local and unchanged.
