# Project Agent Instructions

## Scope

These instructions apply to the entire repository. They define how AI agents plan, implement, verify, commit, and push work for the Financial Product Analyst project.

## Required Planning Gate

Before any meaningful implementation task:

1. Read `docs/planning/HARNESS.md`.
2. Read every accepted decision in `docs/planning/decisions/` relevant to the task.
3. State the task's assumptions, intended outcome, non-goals, constraints, and verifiable success criteria.
4. Present material alternatives and trade-offs when more than one reasonable approach exists.
5. Obtain explicit user approval for the proposed direction before changing implementation files.
6. Create or update a dated task plan under `docs/planning/tasks/` for multi-step work.

Analysis-only work must not modify implementation files and must not be committed. A trivial, single-file corrective change may use a short in-conversation brief, but it still requires explicit success criteria and verification.

## Problem and Decision Discipline

- Preserve the user's `what` and `why`; do not over-specify `how` unless an implementation choice has been approved.
- When a new request conflicts with the harness or an accepted decision, identify the conflict and request a direction change instead of silently overriding it.
- Record durable decisions as ADRs with date, status, chosen option, rejected alternatives, and reasons.
- Do not rewrite an accepted ADR to hide history. Add a new ADR that supersedes it.
- Prefer the smallest design that satisfies the approved outcome. Do not add speculative infrastructure or features.

## Implementation and Verification

- Keep changes surgical and trace every changed line to the approved task.
- Preserve organizer-provided source data unchanged.
- Keep deterministic filtering, sorting, ranking, aggregation, and financial calculations outside the language model.
- Add or update tests for behavior changes before claiming completion.
- Run the narrowest relevant checks first, followed by the appropriate broader verification.
- Inspect the final diff for scope, secrets, generated files, and accidental data inclusion.
- Do not report a task as complete when required checks are failing or were not run.

## Git and GitHub Policy

- The one-time repository bootstrap may create and push `main` after explicit user approval.
- After bootstrap, start meaningful work from an up-to-date `main` on a branch named `codex/<topic>`.
- Commit only a verified, independently useful deliverable. Do not commit analysis-only notes unless the user requested them as project documentation.
- Stage only task-related paths; inspect `git diff --cached --check`, `git diff --cached`, and `git status --short` before committing.
- Use concise conventional commit messages such as `feat:`, `fix:`, `docs:`, `test:`, or `chore:`.
- Push a verified task branch when the user has authorized that workflow. Merging to `main`, releasing, or deploying requires explicit user approval.
- Never force-push, rewrite published history, delete remote branches, or bypass branch protection without explicit user approval.
- Stop automatic pushes when the official competition submission freeze takes effect. The latest official competition notice governs the exact cutoff.

## Repository Data Policy

- Never commit `.env` files, tokens, credentials, private keys, logs containing secrets, or cloud configuration with account identifiers.
- Do not commit organizer-provided raw workbooks or the competition PDF to this personal repository.
- Use ingestion scripts, documented schemas, and synthetic or explicitly approved sanitized fixtures for reproducibility.
- Local databases, Parquet files, embeddings, vector indexes, model caches, and generated outputs stay untracked unless explicitly approved.
- Before every commit and push, verify that no file under `data/`, no organizer PDF, and no secret-bearing file is staged.

## Instruction Precedence

For project decisions, the latest explicit user approval governs, followed by `docs/planning/HARNESS.md`, accepted ADRs, and the current task plan. When these disagree, stop and surface the conflict before implementation.
