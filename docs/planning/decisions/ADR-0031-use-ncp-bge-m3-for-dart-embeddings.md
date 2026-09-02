# ADR-0031: Use NCP Embedding v2 BGE-M3 for DART Document Embeddings

**Date:** 2026-09-02

**Status:** Accepted

**Approved:** 2026-09-02 — the user approved sending only public DART
prospectus chunks to NCP CLOVA Studio Embedding v2 and storing the returned
vectors in the current local PostgreSQL database.

**Related:** [ADR-0007](ADR-0007-normalized-evidence-ledger-structured-answer-plan.md),
[ADR-0021](ADR-0021-use-three-tier-official-document-sources.md),
[ADR-0022](ADR-0022-use-claim-based-vector-corpus-budgets.md),
[ADR-0030](ADR-0030-retire-dart-corpus-volume-failure-gates.md)

## Context

The DART corpus contains 37,629 Claim-selected chunks in PostgreSQL, while
`search.embedding_model` and `search.document_embedding` are empty. The
existing retrieval implementation already performs authority and metadata
filtering before pgvector ranking, but Phase 0 deliberately used synthetic
vectors and did not approve a production embedding provider.

Local disk is constrained and a local BGE-M3 checkpoint would add several
gigabytes of model cache. NCP CLOVA Studio exposes Embedding v2 using BGE-M3,
returns 1,024-dimensional dense vectors, supports inputs up to 8,192 tokens,
and recommends cosine similarity.

## Decision

- Use NCP CLOVA Studio Embedding v2 BGE-M3 for the current official DART
  document corpus.
- Send only public DART prospectus text and non-secret document search context.
  Never send organizer workbook rows, credentials, private data, user prompts,
  or the PostgreSQL evidence ledger.
- Store returned vectors only in the current local PostgreSQL
  `search.document_embedding` table during this phase. Calling the NCP model
  does not authorize an NCP database or Object Storage write.
- Register one immutable model identity with 1,024 dimensions and cosine
  distance. For the remote provider, `model_hash` is the SHA-256 of the
  canonical approval manifest containing provider, endpoint contract, model,
  dimension, distance metric, and input-template version; it is not represented
  as a hash of inaccessible provider weights.
- Embed each unique chunk once. Products or share classes bound to the same
  document reuse the same embedding.
- Build document embedding input from document title, section path, and exact
  chunk text. Do not include per-product names or IDs in the embedded text.
- Use the same provider and model identity for query embeddings. BGE-M3 query
  text receives no synthetic instruction prefix.
- Persist only validated finite 1,024-dimensional vectors and the exact current
  chunk content hash. Record the provider-reported input-token count in the run
  report without adding it to the authoritative chunk text.
- Make the build resumable and idempotent by dataset version, chunk identity,
  content hash, model identity, and model version.
- Execute one canary, then a bounded real retrieval sample, then the full build.
  Stop before the full build if authentication, dimension, token limits,
  metadata filtering, or real Top-5 retrieval checks fail.
- Keep the current exact pgvector scan initially. Add an ANN index only after
  measured latency shows it is necessary and recall is evaluated.

## Rejected Alternatives

### Run a local BGE-M3 checkpoint

Rejected for this phase because it adds a large local model cache under the
user's disk constraint without changing the selected model family.

### Store embeddings in an NCP database immediately

Rejected because local end-to-end correctness must be completed before NCP
deployment and dataset activation.

### Embed all PostgreSQL or organizer text

Rejected because the approved Vector corpus is limited to public official
document Claims. Structured organizer facts remain in PostgreSQL.

### Merge Graph Phase 1 as part of the embedding build

Rejected because the Graph implementation lives on a separately diverged
branch and has its own integration and real-data readiness gates.

## Consequences

- Public DART text leaves the local machine for model inference, while vectors
  and corpus metadata remain in local PostgreSQL.
- The build incurs NCP token charges and must respect provider QPM and TPM
  limits.
- A provider outage or rate limit can pause the build without losing committed
  progress.
- The resulting Vector index remains a candidate projection. It cannot create
  Evidence, Claims, or Graph relations without the PostgreSQL verification
  path required by ADR-0007.
