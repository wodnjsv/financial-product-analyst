# ADR-0039: Map Public-Offering Fund Manager Codes

**Date:** 2026-08-31

**Status:** Accepted

**Approved:** 2026-08-31 — the user approved completing the manager-code
mapping and rebuilding PostgreSQL before any further PDF collection.

**Supersedes in part:**
[ADR-0036](ADR-0036-canonicalize-organizer-asset-managers.md)

## Context

The organizer public-fund source contains 90 distinct nonblank manager codes
on public-offering rows. ADR-0036 kept those codes source-local because the
organizer file does not contain a legal manager name and product-name prefixes
are not authoritative. The resulting products cannot be reconciled reliably
to an OpenDART filing publisher.

The code-to-manager crosswalk can instead be reviewed against official fund
information and the resulting legal name can be reconciled to the official
OpenDART corporation list. This supplies evidence that was absent when
ADR-0036 was accepted.

## Decision

- Review only the 90 manager codes occurring on public-offering rows in the
  organizer `2026-08-24` snapshot.
- Bind a code to a canonical manager only when an official fund-information
  source identifies its legal manager. Add an OpenDART corporation code only
  when the same legal entity can also be reconciled in the official OpenDART
  corporation list.
- Store the reviewed source code, canonical manager identity, optional
  OpenDART corporation code, and evidence reference in a deterministic
  registry.
- Preserve the original organizer manager code and its Evidence unchanged.
- Leave codes unresolved when official manager evidence is missing or
  ambiguous. A KOFIA-confirmed manager without an OpenDART match remains a
  valid manager identity but is not eligible for automatic DART collection.
  Do not infer a manager from a product name, brand, ETF overlap, or
  similarity.
- Keep private-only manager codes source-local. A reviewed code may resolve on
  a private row only when that exact code was independently reviewed through
  the public-offering subset; no additional private-code expansion is made.
- Rebuild the organizer PostgreSQL dataset under a new dataset version after
  the reviewed registry is applied.

## Rejected Alternatives

### Map all 275 public-fund manager codes

Rejected because 185 codes occur only on private-fund rows and are outside the
current official-prospectus collection need.

### Infer managers from product names

Rejected because brands, historical names, and similarly named legal entities
can produce false official-document bindings.

### Patch the existing dataset in place

Rejected because dataset-scoped identities and relations must remain
reproducible from source and mapping version.

## Consequences

- ADR-0036's prohibition on global public-fund code translation is relaxed
  only for the reviewed public-offering code registry.
- Unresolved codes remain explicit and cannot be used for automatic OpenDART
  publisher selection.
- PDF download, extraction, chunking, and embedding remain a later task.
