# ADR-0046: Linearize Document and Intent Migrations

**Date:** 2026-09-04

**Status:** Accepted

**Approved:** 2026-09-04 — the user approved merging the completed document,
Graph, Vector, and intent work into `main` before the remaining stages begin.

**Related:** [ADR-0044](ADR-0044-recover-only-missing-dart-embedding-coverage.md),
[Semantic Query Verification](../verification/2026-09-02-semantic-query-contracts-and-sql-compilation-verification.md)

## Context

The document-corpus branch and the intent-planning branch independently used
Alembic revisions `0008` and `0009`. The retained local corpus database already
contains the document-source and building-dataset revisions through `0009`.
The intent branch's PostgreSQL conformance had not been promoted, and the
previous NCP database had been deleted.

Merging both histories without resolving the duplicate revision IDs would
create two heads and make an existing corpus database ambiguous to upgrade.

## Decision

- Preserve document revisions `0008_document_source_artifact` and
  `0009_lock_building_dataset` unchanged.
- Renumber the intent revisions to `0010_intent_resolution_artifact` and
  `0011_semantic_query_artifacts`.
- Maintain exactly one linear migration head, `0011`.
- Regenerate the reviewed database-object manifest from a clean PostgreSQL 15
  database migrated through `0011`.
- Do not reingest organizer data, DART chunks, or embeddings as part of this
  history integration.

## Rejected Alternatives

### Keep two Alembic heads

Rejected because deployment and downgrade targets would be ambiguous and the
preflight contract requires one reviewed head.

### Renumber the document revisions

Rejected because it would make the retained local document/vector database
appear to have unrelated intent migrations at its existing `0008`/`0009`
revision identifiers.

## Consequences

- A retained document/vector database at revision `0009` can upgrade directly
  to the intent artifact schema at `0011` without rebuilding its corpus.
- Any environment created only from the superseded intent-branch migration
  identifiers must be recreated or stamped only after an explicit audit. No
  such promoted environment is currently retained.
