# NCP BGE-M3 DART Document Embedding Design

**Date:** 2026-09-02

**Status:** Approved design direction; implementation plan pending review

**Decision:** [ADR-0031](../decisions/ADR-0031-use-ncp-bge-m3-for-dart-embeddings.md)

## 1. Goal

Create one validated NCP BGE-M3 embedding for every current DART document chunk,
store it in local PostgreSQL, and prove that metadata-scoped real document
questions retrieve the expected official sections in the Top 5.

The current measured input is:

- dataset version: `organizer-dart-2026-08-24-v2`;
- documents: 1,958;
- unique chunks: 37,629;
- bound product entities: 6,540; and
- existing production embeddings: 0.

## 2. Scope

### In scope

- NCP CLOVA Studio Embedding v2 client for BGE-M3;
- secure key-file loading for the existing `NCP_CLOVA_STUDIO_API` entry;
- immutable embedding-model registration;
- deterministic document and query embedding inputs;
- resumable, idempotent pgvector population;
- canary, bounded sample, full build, and sanitized run reports;
- real metadata-filtered keyword, Vector, and fused Top-5 checks; and
- final count, hash, dimension, database-size, and temporary-artifact checks.

### Out of scope

- re-downloading PDFs or re-chunking the corpus;
- organizer data, private data, user-question, or credential transmission;
- Evidence, ClaimSupport, `hasRiskFactor`, or other Graph relation creation;
- merging `codex/graph-phase1-core`;
- NCP PostgreSQL, Object Storage, or Fuseki writes;
- dataset activation;
- an ANN index before exact-scan latency measurement; and
- embedding overseas ETF, index-methodology, or policy documents not yet in the
  current DART corpus.

## 3. Approved Model Contract

| Field | Value |
| --- | --- |
| provider | `ncp_clova_studio` |
| API | `embedding_v2` |
| model | `bge-m3` |
| vector dimension | `1024` |
| distance metric | `cosine` |
| maximum provider input | `8192` tokens |
| document input template | `dart-search-text-v1` |
| query input template | `bge-m3-query-v1` |

The persisted model identity is versioned by the provider API contract and the
input-template contract. The model manifest is canonical JSON with sorted keys
and compact separators. Its SHA-256 is persisted as `model_hash`. For this
remote provider it proves the approved invocation contract, not the provider's
private runtime weights.

## 4. Data Boundary

The only external payload text is:

```text
문서: {document_title}
섹션: {section_path}
본문:
{exact_text}
```

The builder must reject a row before API invocation when it cannot join the
chunk to a current DART document and source artifact in the approved dataset.
It must not add product names, entity IDs, organizer values, Evidence raw
values, database locators, API keys, or local paths to the payload.

API keys are read from the configured absolute key file, selected only by the
normalized name `NCP_CLOVA_STUDIO_API`, held in memory, sent only in the
authorization header, and never logged or written to reports.

NCP receives public official text for inference. The returned vector is stored
in local PostgreSQL. No corpus text or vector is deliberately written to NCP
storage by this workflow.

## 5. Components

### 5.1 Provider boundary

The provider accepts one nonblank input and returns:

- exactly 1,024 finite floats;
- a positive provider-reported input-token count; and
- a non-secret request identifier suitable for diagnostics when available.

Authentication failure, unsupported response shape, non-finite values,
dimension mismatch, and token-limit errors are permanent for the current item
or configuration. Timeouts, 429 responses, and retryable 5xx responses use a
bounded retry policy with server rate-limit information when available.

### 5.2 Model registry

The builder registers the approved model row before any embedding row. An
existing row is accepted only when dimension, metric, approval ID, approval
time, and manifest hash all match. A mismatch aborts the run; it is never
updated in place.

### 5.3 Corpus reader

Read only current DART chunks that have an exact join across:

- `document.document_chunk`;
- `document.document_record`;
- `document.document_profile`;
- `document.document_source_artifact`; and
- the approved dataset version.

Sort deterministically by `document_id, chunk_id`. The current chunk content
hash is the persistence boundary.

### 5.4 Resumable writer

Generate a stable embedding ID from dataset version, document ID, chunk ID,
content hash, model ID, and model version. Before invoking NCP, skip an existing
exact row only after validating its dimension and vector length. A stale hash or
model version is a distinct embedding identity and is not silently overwritten.

Commit in small bounded batches. On restart, query only missing exact
identities. A run report records counts, token totals, retry totals, failures,
model manifest hash, and final database reconciliation without source text or
credentials.

### 5.5 Retrieval validation

Use the existing `DocumentCandidateRepository` and its authority-first filters.
For each approved local validation question:

1. resolve the exact organizer entity;
2. generate the query embedding with the same provider;
3. search only the required section and Claim type;
4. compare keyword, Vector, and reciprocal-rank-fused Top 5; and
5. confirm every hit joins back to the current document, source, and content
   hash.

The real validation report remains untracked because it contains product and
document results derived from local competition data. Committed tests use only
synthetic fixtures.

## 6. Execution Stages

### Stage A: preflight

- confirm the dataset remains writable and contains 37,629 chunks;
- confirm no production model or embedding rows already exist;
- estimate raw vector storage from `chunk_count * 1024 * 4`;
- validate the key-file format without exposing the key; and
- create no external request when a preflight check fails.

### Stage B: one-chunk canary

- choose one deterministic current DART chunk;
- send only the approved search-text payload;
- require a successful 1,024-dimensional finite vector;
- record returned input tokens and observed rate-limit headers; and
- write and read back one exact embedding row.

### Stage C: bounded real sample

- embed a small deterministic sample spanning strategy and risk sections;
- run real metadata-scoped Top-5 checks;
- verify interruption and resume behavior; and
- stop for review when expected sections are not retrieved.

### Stage D: full build

- process every missing exact chunk identity;
- respect provider QPM and TPM limits;
- retain committed progress across interruption;
- keep API text and vectors out of logs; and
- stop on a permanent configuration error instead of creating partial invalid
  rows.

### Stage E: final verification

- embedding count equals the eligible unique chunk count;
- every row has dimension 1,024 and an exact current chunk hash;
- duplicate exact embedding identities equal zero;
- orphan and stale-hash embeddings equal zero for the approved model version;
- actual database size increase is reported;
- real retrieval checks meet the approved Top-5 gate;
- no Graph relation, Evidence, ClaimSupport, or dataset activation was created;
  and
- Git contains no vectors, reports, source documents, or credentials.

## 7. Error and Recovery Policy

| Failure | Action |
| --- | --- |
| invalid or unauthorized key | stop before full build |
| provider dimension or response mismatch | stop; persist no invalid row |
| input exceeds 8,192 provider tokens | record item failure and stop for chunk-policy review |
| timeout, retryable 5xx, 429 | bounded retry, then leave item missing for resume |
| PostgreSQL write/read-back failure | roll back the batch and stop |
| content hash changes during the run | reject the item and require a new snapshot |
| process interruption | restart and select missing exact identities only |
| retrieval Top-5 gate failure | keep canary/sample rows, do not start full build |

## 8. Capacity and Operations

The raw float payload is approximately 147 MiB for 37,629 vectors. PostgreSQL
row and index overhead is expected to keep the first build well below the prior
8 GiB review threshold, but the final report uses measured table sizes rather
than this estimate.

Provider cost is calculated from returned input-token counts and the current NCP
price. Provider throughput depends on whether the configured key is a test key
or an approved service-app key. The canary records observed limits; the builder
must not assume service-app throughput.

Exact pgvector search remains the initial implementation. HNSW is a later
measured decision because adding it before recall and latency measurements would
increase build time and storage without an observed need.

## 9. Graph Integration Status

Graph Phase 1 core exists on `codex/graph-phase1-core` with ontology, SHACL,
PostgreSQL projection, Jena/TDB2, and read-only Fuseki verification. It is not
present on the current corpus branch and has not consumed the current real DART
dataset. The embedding build must not merge or modify it.

After Vector completion, a separate approved integration plan may merge Graph
Phase 1, reconcile its earlier database assumptions with migrations `0007`–
`0009`, and run real dataset-relative projection and readiness checks.

## 10. Success Criteria

The implementation is complete only when:

1. the approved model registry row is immutable and reproducible;
2. the NCP canary proves authentication, dimension, token count, and local
   write/read-back;
3. bounded real strategy and risk questions retrieve their expected sections
   within Top 5 under exact entity and cutoff filters;
4. every eligible current chunk has exactly one valid embedding for the
   approved model version;
5. an interrupted build resumes without duplicate valid embeddings;
6. no organizer or private data is sent to NCP;
7. no Graph relation, Evidence, ClaimSupport, or activation state is changed;
8. focused tests and the relevant non-live regression suite pass; and
9. the final diff contains no credential, raw source, embedding, local report,
   or organizer-provided data.

## 11. Provider References

- [NCP CLOVA Studio Embedding v2 API](https://api.ncloud-docs.com/docs/clovastudio-embeddingv2)
- [NCP CLOVA Studio embedding model guide](https://guide.ncloud-docs.com/docs/ko/clovastudio-explorer03)
- [NCP CLOVA Studio usage-control policy](https://guide.ncloud-docs.com/docs/clovastudio-ratelimiting)
- [NCP CLOVA Studio pricing](https://www.ncloud.com/charge/price/ko)
