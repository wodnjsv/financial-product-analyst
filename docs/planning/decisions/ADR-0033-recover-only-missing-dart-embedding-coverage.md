# ADR-0033: Recover Only Missing DART Embedding Coverage

**Date:** 2026-09-03

**Status:** Accepted

**Approved:** 2026-09-03 — the user approved conservative DART coverage
recovery and explicitly required products with successful embeddings to be
excluded from reprocessing.

**Related:** [ADR-0024](ADR-0024-correct-organizer-dart-target-inventory.md),
[ADR-0025](ADR-0025-canonicalize-organizer-asset-managers.md),
[ADR-0028](ADR-0028-map-public-offering-manager-codes.md),
[ADR-0029](ADR-0029-block-unusable-representative-values-from-dart.md),
[ADR-0030](ADR-0030-retire-dart-corpus-volume-failure-gates.md), and
[ADR-0031](ADR-0031-use-ncp-bge-m3-for-dart-embeddings.md).

## Context

All 37,629 selected DART chunks have valid committed embeddings. Missing
product coverage is therefore caused before embedding: product scope,
publisher binding, product identity, document lineage, attachment, extraction,
or Claim-section selection.

The database category named `domestic_etf` contains 1,235 ETFs and 545 ETNs.
The ETNs currently dominate the `dart_manager_binding_missing` count even
though they use issuer relations and are not eligible for the fund
investment-prospectus path. Re-running completed products would consume DART
and NCP capacity without improving coverage.

## Decision

- Derive recovery work only from organizer targets whose required member
  products do not already have valid committed embeddings for the current
  chunk hash and approved model identity.
- Exclude completed targets before any publisher batch, DART request, PDF
  capture, chunking, or NCP call.
- Classify organizer ETNs as `not_applicable_current_scope` for the DART fund
  prospectus corpus. Do not infer an asset manager for them.
- Add manager bindings only through the existing official KOFIA-to-OpenDART
  evidence rule.
- Permit deterministic normalization of presentation-only product-name and
  explicit share-class differences within one verified publisher. Continue to
  prohibit substring, fuzzy, or embedding-based identity matching.
- Select a correction version only when one cutoff-eligible document lineage
  is deterministic. Preserve ambiguity otherwise.
- Retry attachment and OCR handling only after exact target, publisher, and
  filing identity are established. Limit OCR to PDFs without a text layer.
- Persist and embed only new chunk hashes. Never recompute or replace the
  existing 37,629 embeddings during recovery.
- Report before/after coverage and retain every unresolved reason explicitly.

## Rejected Alternatives

### Re-run the complete DART corpus

Rejected because the successful corpus is already reconciled and idempotent;
another full source and embedding pass would add cost without information.

### Use fuzzy product or manager matching

Rejected because a plausible name similarity cannot prove that an official
filing belongs to an organizer product.

### Treat ETNs as missing ETFs

Rejected because ETNs are issuer securities rather than investment funds and
do not belong in the current fund-prospectus corpus.

### OCR every downloaded PDF

Rejected because only the text-layer failures require OCR and broad OCR would
increase runtime and noise without addressing the dominant identity failures.

## Consequences

- Recovery traffic and NCP cost scale with the remaining delta rather than the
  existing corpus.
- Coverage statistics distinguish genuine source unavailability from
  non-applicable product types.
- Some products remain unavailable because accuracy and official evidence take
  priority over coverage.
- A separate official-document design is required if ETN issuance documents
  are later added to the Vector corpus.
