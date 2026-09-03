# DART Missing-Embedding Recovery Design

**Date:** 2026-09-03

**Status:** Approved direction; implementation pending

## Objective

Increase official-document coverage for organizer domestic ETFs and public
funds that currently have no DART-backed embedding, without reprocessing
products that already have a committed embedding and without weakening the
project's evidence boundary.

## Assumptions

- `organizer-dart-2026-08-24-v2` remains the authoritative organizer-bound
  corpus dataset.
- The 37,629 committed NCP BGE-M3 embeddings are complete and valid for their
  existing chunks.
- A public-fund representative target may cover multiple organizer share
  classes through the exact `hasShareClass` relation.
- The source cutoff remains 2026-08-24.

## Intended Outcome

- Separate the 545 ETNs from domestic-ETF prospectus recovery because ETNs do
  not use the fund investment-prospectus path.
- Retry only targets whose member products have no valid committed embedding.
- Recover additional DART prospectuses through reviewed manager bindings,
  bounded product-name normalization, deterministic correction lineage, and
  narrowly targeted attachment or PDF handling.
- Produce a before/after reconciliation by failure reason, target, product,
  document, chunk, and embedding count.

## Non-Goals

- Rebuilding or replacing existing embeddings.
- Adding GraphDB relations or changing the retrieval architecture.
- Expanding beyond the approved DART source or cutoff.
- Inferring a manager from a product name, brand, ETF overlap, or fuzzy
  similarity.
- Modifying organizer-provided source data.
- Running OCR across the complete corpus.

## Constraints

- Organizer products and exact source-local identifiers remain authoritative.
- Existing embedded products and documents must be excluded before any DART
  network request.
- A recovered document must resolve to one organizer target, one approved
  publisher, and one cutoff-eligible document lineage.
- Ambiguous candidates remain unavailable; coverage may not be raised by
  choosing among unresolved candidates.
- Only newly committed chunks are sent to NCP. Public DART text is the only
  remote embedding input.
- Downloaded PDFs remain temporary and are deleted after verified database
  read-back, or after a sanitized failure record is written.

## Recovery Pipeline

### 1. Build the missing-only inventory

Start from the frozen organizer DART target inventory. Exclude a target when
every required member already resolves to a document whose current chunk hash
has a valid `ncp-clova-bge-m3` embedding. Preserve shared-document reuse: a
public-fund target is already complete when its document embeddings cover all
of its member share classes.

The exclusion happens before publisher batching so completed products do not
consume DART requests or NCP calls.

### 2. Correct the domestic product scope

Read the organizer `product_type` observation. Domestic ETF rows continue
through the DART fund-prospectus path. ETN rows receive an explicit
`not_applicable_current_scope` disposition for this corpus and do not enter
manager reconciliation or DART discovery.

This is a classification correction, not recovered coverage. It prevents the
545 ETNs from appearing as missing asset-manager failures.

### 3. Recover exact manager bindings

Review unresolved public-offering manager codes using official fund-manager
information and the OpenDART corporation list. Add a binding only when the
same legal entity is established by both sources. Keep unresolved and
private-only codes unresolved unless they independently satisfy the approved
evidence rule.

No product-name inference or global code extrapolation is permitted.

### 4. Normalize product names conservatively

Apply deterministic normalization only to presentation differences that do
not change product identity:

- Unicode compatibility and whitespace;
- balanced outer punctuation used by the filing format;
- explicitly recognized share-class markers; and
- reviewed boilerplate tokens already represented by the DART report type.

A normalized match is accepted only within the already verified publisher and
only when it produces one product identity. Partial-string, edit-distance, or
embedding similarity matching is prohibited. Multiple candidates retain an
ambiguous disposition.

### 5. Resolve document lineage

Group exact-name candidates by document type and report identity. Select only
the latest cutoff-eligible filing in a lineage whose correction state can be
determined. A withdrawal, correction order, or competing unresolved lineage
remains unavailable and records a more specific reason.

### 6. Recover attachment and text failures narrowly

Retry attachment discovery only for targets whose filing identity is already
exact. If one approved investment-prospectus PDF is present, process it through
the existing streaming path. Multiple eligible PDFs remain ambiguous.

OCR is limited to the known `PDF_TEXT_LAYER_MISSING` set after exact source and
attachment validation. OCR output must still yield at least one approved Claim
section. Invalid PDFs are recorded and discarded without broad retries.

### 7. Chunk and embed only deltas

Use the existing Claim-based selection and preferred 300-800-token chunk
construction. Persist recovered documents and chunks idempotently. Query the
embedding repository again after commit and submit only missing chunk hashes
to NCP. Existing vectors are never deleted, replaced, or recomputed.

## Failure Semantics

The run report must distinguish at least:

- `not_applicable_current_scope` for ETNs;
- manager identity unavailable;
- exact product identity not found;
- multiple product identities;
- correction lineage unresolved;
- prospectus attachment absent or ambiguous;
- PDF text unavailable or invalid; and
- approved Claim section not found.

These dispositions are evidence about unavailable coverage, not generic
embedding failures.

## Verification

1. Unit tests prove that ETNs never enter DART fund-prospectus discovery.
2. Unit tests cover each newly admitted formatting variant and prove that
   multi-candidate, cross-publisher, substring, and fuzzy matches fail closed.
3. Unit tests cover deterministic cutoff and correction-lineage selection.
4. A small missing-only canary verifies download, extraction, chunking,
   database read-back, PDF cleanup, and delta embedding.
5. Existing embedded chunk and vector counts are unchanged before delta
   insertion.
6. Every newly committed chunk has exactly one valid 1,024-dimensional vector
   for the approved model identity.
7. Final reconciliation reports the before/after failure counts and accounts
   for every selected missing-only target.

## Implementation Order

1. Missing-only target selection and ETN classification.
2. Failure diagnostics and reviewed manager-registry deltas.
3. Conservative name and correction-lineage improvements.
4. Attachment retry and narrowly scoped OCR.
5. Missing-only corpus run followed by delta embedding and reconciliation.
