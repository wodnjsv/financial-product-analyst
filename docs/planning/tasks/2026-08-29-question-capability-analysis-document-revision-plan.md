# Question Capability Analysis Document Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revise the existing 52-question analysis document so it faithfully separates requirements, retrieval roles, support state, response disposition, and runtime verification without changing the source gold contract.

**Architecture:** Treat `tests/gold/core_questions.json` 1.2 as the source for exact question text, status, subtasks, and Evidence requirements, and apply the approved normalization design as a presentation-layer interpretation. The revised Markdown remains a human review artifact; it does not become a second machine-readable source of truth.

**Tech Stack:** Markdown, Python 3 read-only JSON transformation, project gold JSON 1.2

**Spec:** `docs/planning/specs/2026-08-29-question-capability-contract-normalization-design.md`

## Global Constraints

- Preserve all 52 case IDs, exact question strings, support levels, expected dispositions, and expected Evidence lists.
- Keep the support distribution at 16 `supported`, 18 `limited`, 11 `requires_additional_data`, and 7 `unsupported`.
- Use only the 13 predicates approved by ADR-0018 in the Graph-relation column.
- Keep PostgreSQL metrics and status facts out of the Graph-relation column.
- Mark runtime execution as `not_run`; do not present frozen design coverage as a live DB test result.
- Do not change `core_questions.json`, implementation code, organizer data, or current Stage 03 ingestion work.
- Do not infer the 35 private evaluation questions.

---

### Task 1: Rebuild the 52-question analysis matrix

**Files:**
- Modify: `/Users/kimjaewon/Documents/Codex/2026-08-29/referenced-chatgpt-conversation-this-is-an/outputs/stage03-question-capability-analysis.md`

**Interfaces:**
- Consumes: `tests/gold/core_questions.json` schema 1.2 and the approved normalization design.
- Produces: one human-readable Markdown document with 52 exact question records and no competing machine-readable contract.

- [x] **Step 1: Preserve the document purpose and authority boundary**

State that `core_questions.json` is authoritative, the Markdown is a reviewed projection, the cutoff is `2026-08-24`, and runtime execution is not yet verified.

- [x] **Step 2: Replace the compressed table with exact question records**

For every case, preserve the exact `question` and show:

```text
ID
exact question
question type
entities
metrics
approved relations
document claims
control checks
capabilities
retrieval profile and roles
calculation requirement
Evidence requirements
support level
requires_data
expected disposition
runtime verification
```

- [x] **Step 3: Resolve storage roles from the approved routing model**

Use explicit per-case routes when present, otherwise resolve from category defaults. Override policy-only, snapshot-scope, ontology-vocabulary, and identity-evidence abstention cases so unsupported status does not automatically invoke every store.

- [x] **Step 4: Add the normalized Capability catalog and execution patterns**

Include retrieval, calculation, missingness, closed-world coverage, EvidenceBundle, AtomicClaim, Claim Gate, disposition, and deterministic rendering capabilities.

- [x] **Step 5: Add the official 35-question family boundary and Stage 03/04 conflict notes**

Record only announced counts, public families, and the eight official sample case IDs. Keep document collection and final Graph/Vector scope undecided.

### Task 2: Verify the revised artifact

**Files:**
- Verify: `/Users/kimjaewon/Documents/Codex/2026-08-29/referenced-chatgpt-conversation-this-is-an/outputs/stage03-question-capability-analysis.md`
- Source: `tests/gold/core_questions.json`

**Interfaces:**
- Consumes: revised Markdown and source JSON.
- Produces: validation output showing complete, internally consistent coverage.

- [x] **Step 1: Validate identity and exact question preservation**

Run a read-only comparison that asserts 52 source cases, 52 document case headings, no missing IDs, and exact question text for every ID.

- [x] **Step 2: Validate status and routing invariants**

Assert the four support counts, `requires_data` derivation, 13-predicate allowlist, Vector use only for document/federated paths, and policy gates with no storage roles.

- [x] **Step 3: Validate document quality**

Check for `TODO`, `TBD`, placeholder sections, trailing whitespace, malformed headings, and contradictory claims that current DB execution passed.

- [x] **Step 4: Inspect final scope**

Confirm that no project implementation file, source data, credential, or unrelated dirty-worktree path changed.
