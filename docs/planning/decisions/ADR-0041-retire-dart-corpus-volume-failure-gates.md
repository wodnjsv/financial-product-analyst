# ADR-0041: Retire DART Corpus Volume Failure Gates

**Date:** 2026-09-01

**Status:** Accepted

**Approved:** 2026-09-01 — the user approved processing every required
Claim-selected chunk even when a document exceeds the former chunk-count or
selected-token review thresholds. A document-content failure is recorded only
when no required chunk can be produced.

**Supersedes:** The DART-specific 20-chunk and 8,000-selected-token failure
gates in [ADR-0033](ADR-0033-use-claim-based-vector-corpus-budgets.md), and the
DART failed-PDF retention requirement in
[ADR-0034](ADR-0034-discard-dart-pdfs-after-verified-corpus-ingestion.md).
Other source, identity, Evidence, and successful read-back rules remain in
force.

## Context

The first full DART attempt stopped on documents that produced 26 and 32
relevant chunks. The already persisted 29-chunk sample occupied only a small
amount of PostgreSQL storage, so chunk count was not a useful proxy for local
capacity. Rejecting complete, Claim-selected evidence at an arbitrary count
reduced coverage without solving an observed storage problem.

Keeping failed PDFs also conflicts with the approved low-disk streaming model.
The official receipt, byte count, checksum, and failure reason are enough to
identify and re-download a failed source for a later retry.

## Decision

- Keep Claim-based section selection. Do not admit unrelated document prose to
  increase coverage.
- Keep 300–800 tokens as the preferred chunk construction range. An
  indivisible evidence unit may exceed it and is still indexed.
- Do not reject, truncate, or quarantine a DART document because its chunk
  count or total selected-token count exceeds a threshold.
- Continue recording observed chunk count, selected-token count, and token
  counter identity for measurement only.
- Record `approved_section_not_found` when no required selected chunk can be
  produced.
- Source verification, PDF extraction, exact identity, cutoff, database
  transaction, read-back, and cleanup-integrity failures remain failures. They
  are not content-volume failures and must not be silently accepted.
- For a failed captured PDF, record the DART receipt, failure reason, byte
  count, and SHA-256 in the sanitized run report, then delete only that exact
  temporary PDF. Do not accumulate failed PDFs locally.
- Successful PDFs continue to be deleted only after committed PostgreSQL
  read-back succeeds.

## Rejected Alternatives

### Raise the soft maximum above 20

Rejected because another arbitrary count would retain the same failure mode.
Actual Claim selection and measured storage are the relevant controls.

### Keep the 8,000-token failure gate alone

Rejected because selected-token volume is still recorded and can be evaluated
before embedding, while source ingestion should preserve all required Claims.

### Keep failed PDFs for manual review

Rejected because it can halt a long run and consume limited local storage.
Recorded official identity and checksums preserve a deterministic retry path.

## Consequences

- Documents with 29 or more relevant chunks can be indexed normally.
- Corpus volume is controlled by required Claim selection and unique-document
  deduplication, not by per-document rejection.
- Embedding capacity remains a later gate based on measured corpus totals; this
  ADR does not start embedding or VectorDB population.
- A failed source is not locally recoverable after cleanup and must be
  re-downloaded from DART for retry.
