# QueryPlan Compiler Implementation Plan

**Goal:** Deterministically lower Phase 1 output into a routed frozen QueryPlan.

**Architecture:** A strict internal compilation contract surrounds the unchanged
QueryPlan. Versioned registries control all archetypes, primitives, policies,
defaults, and operation parameters.

**Spec:** `docs/planning/specs/2026-09-02-query-plan-compiler-design.md`

## Global constraints

- Use TDD for every behavior.
- Never read `tests/gold/core_questions.json` from production code.
- Never generate SQL, SPARQL, field names, formulas, or registry IDs.
- Keep live Phase 1 promotion disabled.

### Task 1: Compilation contracts and registry

**Files:** create `src/financial_agent/planning/contracts.py`,
`src/financial_agent/planning/registry.py`, `config/planning/query-plan-registry.v1.json`;
test in `tests/planning/test_contracts.py` and `tests/planning/test_registry.py`.

- [ ] Write failing tests for strict route/result invariants, duplicate registry
  IDs, unknown capabilities, and deterministic registry hashing.
- [ ] Run the tests and confirm missing-module failures.
- [ ] Implement the minimum strict models and loader.
- [ ] Run the focused tests and commit.

### Task 2: Slot and context lowering

**Files:** create `src/financial_agent/planning/lowering.py`; test in
`tests/planning/test_lowering.py`.

- [ ] Write failing tests for literal decoding, filter evidence grouping,
  entity resolution, produced bindings, all context link types, selectors, and
  carryover/update/delete/dontcare precedence.
- [ ] Confirm the tests fail for missing lowering behavior.
- [ ] Implement deterministic lowering and stable issue codes.
- [ ] Run focused and Intent contract tests; commit.

### Task 3: Router and compiler

**Files:** create `src/financial_agent/planning/router.py`,
`src/financial_agent/planning/compiler.py`; test in
`tests/planning/test_router.py` and `tests/planning/test_compiler.py`.

- [ ] Write failing table tests for Fast, Compose, Explore, Abstain and false-fast
  negative cases using hand-checked expected QueryPlans.
- [ ] Confirm expected failures.
- [ ] Implement route precedence, archetype matching, primitive composition,
  QueryPlan validation, and provenance coverage.
- [ ] Run focused compiler, Intent, and contract suites; commit.

### Task 4: Decoupled evaluation and documentation

**Files:** create `src/financial_agent/planning/evaluation.py`,
`tests/evaluation/planning/test_query_plan_evaluation.py`; update `STATUS.md`.

- [ ] Write failing tests for deterministic exact match, route confusion,
  lossless coverage, unknown-ID acceptance, and false-fast metrics.
- [ ] Implement the evaluator and fail-closed promotion report.
- [ ] Run Phase 2 and broad offline suites; record exact evidence; commit.
