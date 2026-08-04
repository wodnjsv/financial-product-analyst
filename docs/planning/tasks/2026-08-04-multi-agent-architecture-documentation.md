# Conditional-Parallel Multi-Agent Architecture Documentation Plan

**Date:** 2026-08-04

**Status:** Awaiting user review

## Goal

Replace the optional multi-agent framing with the approved conditional-parallel multi-agent graph and document enough architecture, contracts, failure behavior, latency strategy, and verification gates to support a later implementation plan.

## Assumptions

- The internal product desk Copilot remains the approved product frame.
- The user approved option A: a deterministic orchestrator with conditional routing and parallel product Specialists.
- Multi-agent architecture is a core competition differentiator, but Agent count is not a success measure by itself.
- The proposed 4-second simple-query and 10-second cross-product p95 targets remain provisional until measured.

## Intended Outcome

- The harness treats bounded multi-agent orchestration as an approved top-level architecture.
- ADR-0004 preserves the decision, alternatives, trade-offs, and partial supersession of ADR-0003.
- The architecture document defines components, contracts, execution paths, failure handling, latency strategy, and verification gates.
- SQL-first remains a candidate for the deterministic data layer rather than the top-level architecture.

## Non-Goals

- Select an orchestration framework, database, vector store, embedding model, cache, or deployment platform.
- Define final JSON Schemas, API implementation code, prompts, or infrastructure configuration.
- Add unbounded agent delegation, debate, voting, or all-Agent fan-out.
- Modify implementation files, organizer data, or the competition PDF.

## Constraints

- Use HyperCLOVA X for every language-model role.
- Keep application code in control of agent and tool dispatch.
- Keep financial calculations deterministic and evidence-bound.
- Preserve prior ADR history; use ADR-0004 to supersede only the conflicting architecture boundary.
- Do not commit organizer data, PDFs, secrets, generated indexes, or local data products.

## Success Criteria

- Agent and deterministic-service responsibilities do not overlap ambiguously.
- Every component has typed inputs, outputs, failure behavior, and an observable purpose.
- Fast, single-family, and cross-product paths are distinct.
- Retry and repair loops are bounded and the system never releases an unverified draft.
- Latency targets are labeled provisional and tied to a benchmark requirement.
- The document contains no placeholder, contradiction, unsupported absolute-accuracy promise, or unapproved implementation choice.
- Diff, link, secret, and repository-data checks pass before commit.

## Tasks

- [x] Update the harness with the approved multi-agent direction and success measures.
- [x] Add ADR-0004 and record its relationship to ADR-0003.
- [x] Add the detailed multi-agent architecture document.
- [x] Update the prior documentation task to record the requested redesign.
- [x] Verify and commit only approved planning documents on `codex/product-definition`.
- [ ] Receive user review before creating the implementation plan.

## Verification Commands

```bash
rg -n "TB[D]|TO[D]O|implement[[:space:]]+later|fill[[:space:]]+in|perfect[[:space:]]+accuracy|zero[[:space:]]+error" docs/planning
rg -n "conditional-parallel|deterministic orchestrator|parallel|EvidenceBundle|Claim Gate|p95|Supersedes" docs/planning
git diff --check
git status --short --ignored
```

Expected results:

- The placeholder and unsupported-promise scan returns no matches.
- Architecture structure and supersession markers are present.
- The diff contains no whitespace errors or unrelated files.
- No organizer workbook, competition PDF, secret-bearing file, or generated data product is selected for commit.
