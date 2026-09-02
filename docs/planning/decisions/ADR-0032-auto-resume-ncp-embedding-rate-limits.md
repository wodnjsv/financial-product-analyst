# ADR-0032: Auto-Resume NCP Embedding Builds After Rate Limits

**Date:** 2026-09-02

**Status:** Accepted

**Approved:** 2026-09-02 — the user approved keeping NCP BGE-M3 while
automatically waiting and resuming the full DART embedding build after
provider rate limits.

**Related:** [ADR-0031](ADR-0031-use-ncp-bge-m3-for-dart-embeddings.md)

## Context

The resumable full build preserved committed vectors, but its four-attempt
provider retry budget repeatedly ended the operator process at NCP rate-limit
boundaries. Manual restarts reused existing rows correctly but could not carry
the build through a long quota-reset window without supervision.

## Decision

- Keep the existing four-attempt bounded retry inside each NCP request.
- In the `full` build only, treat exhausted retryable provider failures as a
  pause rather than a terminal build failure.
- Wait for 60 seconds, 5 minutes, 30 minutes, and then 1 hour after consecutive
  exhausted retry cycles. Cap further waits at 1 hour.
- Reset the long-wait sequence after one complete embedding batch commits.
- Re-read missing chunk identities after every pause. Never delete or replace
  committed vectors.
- Do not auto-resume authentication failures, permanent HTTP failures,
  malformed responses, invalid dimensions, database failures, reconciliation
  failures, or operator cancellation.
- Keep canary, sample, and retrieval-verification commands fail-fast after the
  existing bounded provider retry.

## Rejected Alternatives

### Continue manual restarts

Rejected because it leaves a long, deterministic bulk operation dependent on
operator availability even though committed progress is already idempotent.

### Retry continuously at a fixed short interval

Rejected because a daily quota can remain unavailable for hours and repeated
short probes would create unnecessary external calls.

### Switch to a local embedding model

Rejected because it would create a second model identity, require rebuilding
the complete corpus, and consume several gigabytes of the constrained local
disk.

## Consequences

- A full build can remain alive across minute, hourly, or daily provider quota
  windows and continue without mixing embedding identities.
- Retryable provider outages can keep the operator command waiting until it is
  cancelled or the provider recovers.
- Permanent provider, data, database, and reconciliation errors remain visible
  terminal failures.
