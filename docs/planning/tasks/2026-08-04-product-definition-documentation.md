# Internal Product Desk Copilot Definition Documentation Plan

**Date:** 2026-08-04

**Status:** Superseded by the approved multi-agent architecture redesign

## Goal

Record the approved competition-first product definition, operational pain points, required capabilities, and success measures in the project planning harness without selecting an implementation architecture.

## Assumptions

- Competition evaluation is the highest-priority outcome.
- “Internal financial-product desk Copilot” is the product frame for the evaluated workflow, not a decision to optimize for one commercial persona.
- The organizer brief and applicable financial-product sales and explanation rules support the pain-point model, but no quantified user-interview evidence is claimed.
- Existing accepted planning and repository-data decisions remain in force.

## Intended Outcome

- `docs/planning/HARNESS.md` gives future contributors a stable, testable definition of the problem, product, core job flow, pain points, required behaviors, competition mapping, scope, and success measures.
- A new ADR preserves the choice of the product-desk Copilot frame and the alternatives that were rejected.
- The proposed SQL-first hybrid remains explicitly unapproved until a separate architecture decision.

## Non-Goals

- Select a database, retrieval pattern, Agent framework, deployment platform, or detailed component architecture.
- Design a persona-specific user interface or authorization model.
- Add personalized investment advice, portfolio allocation, live trading, or real-time market data.
- Modify implementation files, organizer data, or the competition PDF.

## Constraints

- Preserve the organizer's product scope, data priority, evidence rules, HyperCLOVA X restriction, and recommendation guardrails.
- Keep deterministic filtering, sorting, ranking, aggregation, and financial calculations outside the language model.
- Do not commit organizer data, PDFs, secrets, generated indexes, or local data products.
- Keep every document change traceable to the approved product-definition request.

## Success Criteria

- The harness states that competition alignment outranks persona-specific expansion.
- The product definition covers clarification, candidate screening, comparison validation, deterministic calculation, grounded explanation, and evidence.
- Pain points are separated from unverified quantitative user-research claims.
- Required capabilities map directly to competition requirements and have verifiable outcomes.
- Personalized advice and implementation architecture remain outside the approved scope.
- A placeholder scan, consistency review, diff review, and repository-data audit pass before commit.

## Tasks

- [x] Update the planning harness with the approved problem and product definition.
- [x] Add an accepted ADR for the internal product desk Copilot framing.
- [x] Verify terminology, internal consistency, scope, links, placeholders, and accidental data inclusion.
- [x] Receive user review; the product frame was retained and the optional multi-agent architecture boundary was rejected.
- [x] Continue the requested redesign in `2026-08-04-multi-agent-architecture-documentation.md`.

## Verification Commands

```bash
rg -n "TB[D]|TO[D]O|implement[[:space:]]+later|fill[[:space:]]+in" docs/planning
rg -n "competition|Copilot|deterministic|evidence|clarif|abstent|Non-Goals|Success" docs/planning/HARNESS.md docs/planning/decisions/ADR-0003-internal-product-desk-copilot.md
git diff --check
git diff -- docs/planning/HARNESS.md docs/planning/decisions/ADR-0003-internal-product-desk-copilot.md docs/planning/tasks/2026-08-04-product-definition-documentation.md
git status --short --ignored
```

Expected results:

- The placeholder scan returns no matches.
- The structure scan finds the approved product definition, constraints, and success measures.
- The diff has no whitespace errors or unrelated file changes.
- No organizer workbook, competition PDF, secret-bearing file, or generated data product is selected for commit.
