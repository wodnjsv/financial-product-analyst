# Deterministic Orchestrator Implementation Plan

**Goal:** Compile and execute validated QueryPlans through a bounded deterministic
Orchestrator without embedding domain data engines.

**Architecture:** The graph compiler expands registered operations into the
frozen ExecutionGraph. One async scheduler invokes injected typed executors under
dependency, concurrency, retry, and deadline controls.

**Spec:** `docs/planning/specs/2026-09-02-deterministic-orchestrator-design.md`

## Global constraints

- The Orchestrator is the only scheduler.
- Hard deadline is at most 55,000 ms.
- Request-wide transient retries are at most two; same-task retry at most one.
- No LLM or production data-access implementation is added.

### Task 1: ExecutionGraph compiler

**Files:** create `src/financial_agent/orchestration/graph.py`; test in
`tests/orchestration/test_graph.py`.

- [x] Write failing tests for deterministic expansion, dependencies, fan-out,
  binding producers, evidence requirements, budgets, and critical path.
- [x] Implement the smallest graph compiler using the Phase 2 registry.
- [x] Run focused and frozen contract tests; commit.

### Task 2: Executor boundary and result validation

**Files:** create `src/financial_agent/orchestration/executors.py` and
`src/financial_agent/orchestration/validation.py`; test in
`tests/orchestration/test_executors.py`.

- [x] Write failing tests for duplicate/missing executor registration and invalid
  task ID, result type, binding, evidence, pin, and hash outputs.
- [x] Implement the protocol, registry, immutable input, and validator.
- [x] Run focused tests; commit.

### Task 3: Bounded async Orchestrator

**Files:** create `src/financial_agent/orchestration/service.py` and
`src/financial_agent/orchestration/contracts.py`; test in
`tests/orchestration/test_service.py`.

- [x] Write failing tests for parallel ready tasks, dependency ordering,
  transient retry limits, permanent no-retry, deadline cancellation, missing
  bindings, and completed/completed-with-failures/failed outcomes.
- [x] Implement the scheduler with injected clock and executor registry.
- [x] Run focused and contract tests; commit.

### Task 4: Combined Phase 1-3 verification

**Files:** create `tests/integration/test_intent_plan_orchestration.py`; update
`docs/planning/STATUS.md` and add a dated verification report.

- [x] Write an in-memory end-to-end test for rank, contextual re-rank,
  cross-family composition, Explore, and policy Abstain.
- [x] Run Phase 1-3 focused suites, schema checks, and broad offline tests.
- [x] Inspect the final diff for scope, secrets, source data, and generated files.
- [x] Record measured limitations and commit the verified deliverable.
