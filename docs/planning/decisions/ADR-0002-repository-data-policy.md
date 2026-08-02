# ADR-0002: Keep Organizer Data Out of the Personal Repository

**Date:** 2026-08-02

**Status:** Accepted

## Context

The workspace contains organizer-provided financial-product workbooks and a competition briefing PDF. Their distribution terms for a personal GitHub repository have not been established, and the repository may later contain public code. Accidental publication would be difficult to reverse because Git retains file history.

## Decision

- Ignore the entire local `data/` directory and organizer PDFs under `docs/`.
- Never stage organizer-provided workbooks or the briefing PDF in the personal repository.
- Track ingestion code, validation rules, hand-authored schema documentation, and synthetic or explicitly approved sanitized fixtures instead.
- Keep secrets, credentials, local databases, Parquet files, embeddings, search indexes, caches, logs, and generated outputs untracked by default.
- Inspect the staged diff and ignored-file status before every commit and push.

If the organizer later requires source data in its own private submission repository, handle that repository and permission as a separate, explicitly approved workflow.

## Rejected Alternatives

### Commit all workspace files for convenience

Rejected because repository history can expose data even after a later deletion and because raw data is not required to preserve application logic.

### Commit the files only while the repository is private

Rejected because visibility can change, collaborators can clone the history, and the organizer's distribution terms remain unknown.

## Consequences

- A fresh checkout needs an explicit data-acquisition or local placement step before ingestion.
- Tests must use synthetic or approved sanitized fixtures.
- Repository history remains safe to publish and easier to audit.
