# ADR-0033: Use Claim-Based Vector Corpus Budgets

**Date:** 2026-08-31

**Status:** Accepted

**Approved:** 2026-08-31 — the user removed the 8–15 chunk-count target and
approved Claim-based selection with bounded chunk and total-token review gates,
including the 8,000-token soft limit and capacity preflight.

**Supersedes:** The 8–15 target in
[ADR-0032](ADR-0032-use-three-tier-official-document-sources.md). All other
ADR-0032 source, authority, change-disclosure, and Evidence decisions remain in
force.

## Context

The earlier corpus policy used a target of 8–15 chunks per product scope to
discourage both oversized documents and unbounded corpus growth. A real KODEX
200 prospectus test showed that concise, question-relevant strategy and risk
Claims can fit into fewer chunks. Enforcing a minimum would split coherent
evidence, increase overlap, or encourage admission of irrelevant prose merely
to reach a count.

Chunk count is an indirect proxy for the actual risks. The relevant controls
are which Claims enter the corpus, how large one retrieval unit becomes, and
the total indexed text retained for a product scope.

## Decision

- Select text only through the approved Claim vocabulary and concise-first
  document policy. Full-document text fills a missing Claim only.
- Remove the minimum and target chunk counts. A product may validly produce one
  or a few chunks when those chunks cover its required Claims.
- Keep 300–800 tokens as a per-chunk quality range, measured by the selected
  embedding model's tokenizer when that tokenizer is available. This range is
  not a reason to add prose or split an indivisible evidence unit.
- Keep 20 chunks as a soft maximum per product or index budget scope.
- Add a provisional soft maximum of 8,000 selected tokens per budget scope.
  Recalibrate it only from measured corpus coverage and retrieval results after
  the embedding model is approved; do not tune it to reproduce 8–15 chunks.
- Exceeding either soft maximum produces
  `review_required_chunk_budget`. It never silently truncates a Claim, drops
  Evidence, or admits unrelated text.
- Record observed chunk count, observed selected-token count, counter identity,
  and the exceeded gate in the quality report.
- Reuse one canonical document and its embeddings across every product entity
  bound to that document. Share classes do not receive duplicate document
  embeddings merely to preserve their product bindings.
- Before full embedding, calculate projected text, vector, metadata, index, and
  retained-source storage from the actual unique-document inventory and
  approved embedding dimension. A projected local persistent footprint above
  8 GiB requires review before embedding starts.
- Process official source files through bounded temporary storage. Preserve the
  verified immutable source in approved Object Storage, then remove only the
  local temporary copy; do not accumulate the complete PDF corpus locally.

## Rejected Alternatives

### Preserve 8–15 as a target

Rejected because it rewards a storage shape rather than Claim coverage and can
increase duplicate overlap and retrieval noise for concise official documents.

### Remove all quantitative limits

Rejected because Claim classification can still admit unusually long risk or
methodology sections, and a deterministic review boundary is needed to prevent
unnoticed corpus growth.

### Hard-truncate at the limit

Rejected because truncation can remove material risk language and break exact
Evidence spans. Review is safer than partial indexing.

## Consequences

- Small but complete products are accepted without artificial fragmentation.
- Corpus growth is controlled by Claim admission and actual indexed tokens,
  with chunk count retained only as a safety ceiling.
- Final enforcement depends on the approved embedding tokenizer. Until then,
  injected deterministic counters may be used for tests and measurement, but
  their results must identify the counter and must not be presented as final
  model-token counts.
- Capacity is forecast from unique documents rather than product rows, avoiding
  repeated PDFs and vectors for public-fund share classes or other products
  that share one official document.
- PostgreSQL remains version 15. This decision does not change the accepted NCP
  PostgreSQL deployment boundary.
