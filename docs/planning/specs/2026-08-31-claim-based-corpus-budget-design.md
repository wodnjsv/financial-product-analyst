# Claim-Based Vector Corpus Budget Design

**Date:** 2026-08-31

**Status:** Approved design; implementation pending

**Decision:** [ADR-0022](../decisions/ADR-0022-use-claim-based-vector-corpus-budgets.md)

## Outcome

Corpus size is bounded without requiring a product to produce an arbitrary
number of chunks. Required Claims determine admission. Token and chunk limits
detect exceptional scopes and route them to review without deleting evidence.

## Processing Order

1. Admit only documents allowed by ADR-0021.
2. Select approved Claims using the concise-first policy.
3. Deduplicate exact selected text.
4. Reuse one canonical document for all bound product entities instead of
   creating per-product copies of identical PDFs, chunks, or embeddings.
5. Chunk within one section using the injected token counter and the existing
   300–800 quality range.
6. Calculate the total tokens represented by the selected chunks without
   double-counting overlap.
7. Return `review_required_chunk_budget` when a scope exceeds 20 chunks or
   8,000 selected tokens.
8. Preserve every generated chunk and its reason code for inspection; do not
   persist or activate an over-budget scope automatically.

## Counter Identity

The chunking request must identify the counter used. Once the embedding model
is approved, production uses that model's tokenizer and a versioned counter
identity. A whitespace or test counter remains acceptable only for synthetic
tests and provisional measurements.

Changing tokenizer identity is a corpus-version change because it may alter
chunk boundaries and IDs.

## Budget Semantics

- `target_min_tokens=300`: preferred lower size, not a minimum chunk-count
  generator.
- `target_max_tokens=800`: normal upper size; indivisible evidence may exceed
  it only with the existing review reason.
- `soft_chunk_limit=20`: maximum generated chunks per budget scope before
  review.
- `soft_total_token_limit=8000`: maximum unique selected tokens per budget
  scope before review.
- There is no minimum or target number of chunks.

The total-token measurement uses unique selected source spans before overlap so
that overlap does not make one corpus appear larger merely because of the
retrieval strategy.

## Capacity Preflight and Local Storage

Before generating embeddings for the complete scope, build a metadata-only
inventory containing unique document count, bound product count, selected-token
count, chunk count, source byte count, embedding dimension, and proposed index
type. Calculate projected storage separately for text, vectors, relational
metadata, Vector index, and retained official objects.

The first full embedding run requires review when projected persistent local
storage exceeds 8 GiB. The report must use the actual unique-document inventory;
it must not multiply one shared fund document by every share class.

Source processing uses bounded temporary storage:

1. download one bounded batch;
2. verify checksum and official-source metadata;
3. extract, select, and chunk;
4. confirm the immutable source exists in approved Object Storage; and
5. remove only the local temporary source copy.

The pipeline never deletes the sole verified source copy and never requires the
complete PDF corpus to exist locally at once.

## Verification

Tests must prove that:

- a complete three-chunk product remains indexed;
- adding irrelevant prose does not help satisfy any budget or Claim gate;
- 21 otherwise valid chunks require review;
- a scope above 8,000 unique selected tokens requires review even with 20 or
  fewer chunks;
- overlap is not double-counted in the total-token gate;
- over-budget processing does not truncate chunks; and
- changing the counter identity changes the declared corpus processing
  identity or is rejected when mixed within one dataset version.
- multiple product bindings to one document create one chunk and embedding set;
- capacity preflight uses unique documents and reports every storage component;
- a projected local persistent footprint above 8 GiB blocks the full embedding
  run pending review; and
- temporary source cleanup occurs only after verified Object Storage
  preservation.

The real-corpus report records the counter identity, chunk count, unique token
count, limits, and review reason without including source prose or embedding
vectors.

## Non-Goals

- Selecting the final embedding model in this change.
- Expanding the approved Claim vocabulary or official source tiers.
- Rebuilding the entire product database.
- Requiring every product to consume a similar amount of Vector capacity.
