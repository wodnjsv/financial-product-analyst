# ADR-0047: Assemble a New Final Stage 03/04 Dataset

- Date: 2026-09-04
- Status: Accepted

## Context

The local PostgreSQL 15 database contains the current organizer baseline and a
verified DART corpus under `organizer-dart-2026-08-24-v2`. The DART corpus has
2,214 official documents, 40,149 selected chunks, and 40,149 NCP BGE-M3
embeddings. Current KRX, ECOS, and SEC snapshots have been captured and
verified, but have not been combined with that dataset. No dataset is active.

Changing the existing dataset in place would make its immutable source
manifest cease to describe its contents. Re-downloading DART PDFs or calling
the embedding API again would add cost without adding information.

## Decision

Create `competition-2026-08-24-final-v1` in the existing PostgreSQL database.

1. Build the organizer and official structured sources into the new version.
2. Carry forward the verified DART corpus from
   `organizer-dart-2026-08-24-v2`, regenerating only dataset-scoped hashes and
   embedding IDs while preserving exact text, locators, checksums, and vector
   values.
3. Build the Graph projection from the new PostgreSQL version.
4. Record passing readiness for `postgres`, `graph`, `vector`, and `evidence`.
5. Activate the new version only after the validation run passes.

The source dataset remains unchanged until post-activation verification. Raw
organizer files, official captures, databases, graph artifacts, and embeddings
remain untracked.

## Rejected Alternatives

### Mutate the existing DART dataset

Rejected because the stored manifest would no longer describe the dataset and
rollback would be unreliable.

### Re-download and re-embed every DART document

Rejected because the approved text and vectors already exist and can be
verified by their hashes.

### Build a second PostgreSQL cluster

Rejected for this local run because it requires materially more temporary disk
space without improving the dataset-version isolation already enforced by the
schema.

## Consequences

- Structured rows are written again under a new dataset version.
- DART vectors are copied locally and are not sent to NCP again.
- Dataset-scoped document hashes and embedding IDs must be regenerated.
- Final activation is atomic and can be withheld without damaging the source
  dataset.
