# WTREWRWE DART Block and Public-Fund Canary Plan

**Goal:** Prevent unusable organizer representative values from issuing DART
requests, then run one exact multi-class public-fund document through the
existing streaming corpus pipeline.

**Decision:**
`docs/planning/decisions/ADR-0029-block-unusable-representative-values-from-dart.md`

## Scope and success criteria

- Keep the corrected 15,571-target inventory and its canonical hash.
- Derive the block from preserved organizer field Evidence, not product names.
- Reconcile every blocked target as
  `representative_identifier_unavailable` before any network request.
- Prove with a failing test that a blocked target cannot enter publisher
  reconciliation or discovery.
- Run one DART-eligible multi-class public fund end to end against PostgreSQL
  15 and verify one document/chunk set binds every member Entity.
- Delete the successful temporary PDF only after commit and read-back.

## Non-goals

- Inferring a replacement representative identifier.
- Embedding, VectorDB population, Graph projection, activation, or NCP writes.
- Starting the full organizer run before the canary and capacity gates pass.

## Tasks

- [x] Add failing repository, inventory, and pre-discovery partition tests.
- [x] Implement the minimal Evidence-derived block reason and partition.
- [x] Rebuild or migrate only if the stored organizer dataset requires it.
- [x] Run the multi-class public-fund canary and verify cleanup/read-back.
- [x] Retire the DART volume failure gates after measuring persisted chunks.
- [ ] Continue the full organizer run with exact failed-PDF cleanup.
- [ ] Record exact counts, failures, tests, and local-storage impact.

## 2026-09-01 checkpoint

- PostgreSQL 15 inventory: 25,239 organizer products and 15,571 DART targets
  (1,780 domestic ETP and 13,791 public fund).
- Exactly three public-fund targets are blocked before network discovery with
  `representative_identifier_unavailable`; no canonical domestic ETF is
  blocked by overlapping raw Evidence.
- Inventory hash:
  `158452e05fc8cf27aa833eba7ebe477b45caa018c48f16524e35a6b4ece77d02`.
- Focused repository, inventory, and CLI checks pass: 29 tests.
- The multi-class canary uncovered a separate exact-identity prerequisite:
  organizer representative Entities currently carry the representative code
  as `canonical_name`, while DART publisher filings carry the classless
  official fund name. PDF collection remains paused until an official exact
  name bridge is approved; class-suffix guessing is not permitted.

## 2026-09-01 continuation

- The exact publisher-scoped official-name bridge was implemented and the
  multi-class public-fund canary succeeded: one 74-page DART document produced
  11 chunks and bound six organizer member Entities. PostgreSQL read-back
  passed and the temporary PDF was deleted.
- The first resumed corpus attempt persisted seven public-fund documents and
  29 chunks. The exact chunk text occupied about 105 KiB; the PostgreSQL chunk
  relation including indexes and TOAST occupied about 304 KiB.
- Two otherwise usable documents were rejected only because they produced 32
  and 26 chunks. ADR-0030 therefore removes count and selected-token volume as
  DART ingestion failure conditions. A missing required chunk remains
  `approved_section_not_found`; technical integrity failures remain explicit.
- The next run uses a fresh bounded temporary root. Failed PDFs are recorded by
  receipt, reason, byte count, and SHA-256, then deleted instead of accumulated.
- The resumed batch reached 251 committed documents and 5,089 chunks before a
  database operation exceeded the batch's 30-second statement timeout during
  long PostgreSQL checkpoints. Receipt `20251024000177` was not committed; its
  1,730,372-byte temporary PDF had SHA-256
  `e6a7f3fb3777a8512bd7f0282766fbf43e9ab6bfc2f944d8bacff368bc44d4b3`
  and is discarded before retry. The DART batch timeout is raised to 180
  seconds; no organizer data is rebuilt.
- Earlier quarantined receipts `20100831000781` (573,846 bytes, SHA-256
  `f16eaaf2f5815379c28d4780c8f0b2801e19e4edd98f4790961270a72bcc7201`)
  and `20101014000023` (659,237 bytes, SHA-256
  `72401f5ef1eed130a20b2e3d5775d4b1a0d6864163b87fb77027ae9892a934d7`)
  passed under ADR-0030 and are committed. Receipt `20101130001038` (888,942
  bytes, SHA-256
  `8e4be43f36981cf5ad198fe524d6fc1ca427f040f9b13fb86764fe7dd650acdd`)
  produced no approved chunk. All three superseded temporary copies are
  deleted after this identity record is written.
- Receipt `20251024000177` initially raised a PostgreSQL `DataError`, which the
  CLI's broad database boundary reported as `DATABASE_UNREACHABLE`. The actual
  cause was a NUL (`0x00`) character emitted by the PDF text layer. PDF layout
  text is now sanitized before canonical offsets, spans, and checksums are
  built. The exact one-target rerun then passed with one 66-page document, 21
  chunks, seven member-Entity bindings, zero failures, and zero retained PDFs.
