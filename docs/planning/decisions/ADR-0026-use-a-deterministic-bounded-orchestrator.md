# ADR-0026: Use a Deterministic Bounded Orchestrator

**Date:** 2026-09-02

**Status:** Accepted

**Approved:** 2026-09-02 — the user authorized Phase 3 planning and implementation
immediately after Phase 2.

**Related:** ADR-0004, ADR-0005, ADR-0006, ADR-0025

## Context

QueryPlan describes required work but does not schedule concrete tasks. The
system needs one authority for graph construction, bounded concurrency,
deadlines, retries, cancellation, result validation, and execution outcome.
Concrete RDB, Graph, Keyword, Vector, and financial engines are developed in
their owning stages and must plug into this authority without gaining scheduling
control.

## Decision

- Deterministically compile a successful QueryPlanCompilation into the frozen
  ExecutionGraph contract using the same primitive operation registry.
- Make one application Orchestrator the only scheduler. Executors implement one
  typed async interface and cannot enqueue work or invoke LLMs.
- Run ready independent tasks concurrently with a bounded semaphore. Release a
  task only after all dependencies have terminal successful results and required
  bindings are available.
- Enforce the 55-second request deadline, per-task budgets, request-wide two
  transient retries, and at most one retry for the same task.
- Retry only timeout, rate-limit, provider-unavailable, and declared transient
  executor failures while time remains. Contract, invalid-input, unsupported,
  and permanent failures are never retried.
- Validate every ToolResult against task identity, result type, binding names,
  evidence requirements, and immutable request pins before publishing it to
  downstream tasks.
- Classify outcomes independently from later answer disposition:
  `completed`, `completed_with_failures`, or `failed`.
- Do not implement domain SQL, Graph, Vector, or calculation algorithms here.
  Phase 3 completes the orchestration boundary with injected registered
  executors; Stage 05 supplies production executor implementations.

## Consequences

Scheduling and failure behavior are reproducible and testable without live
services. Independent tasks can fan out while dependent tasks remain ordered.
The Orchestrator cannot make a semantically invalid plan valid and cannot turn
execution failure into abstention.

## Rejected Alternatives

- Model-directed function calling or recursive agents.
- An event bus for the single-request competition runtime.
- Unbounded task retries or independent retry budgets per executor.
- Embedding concrete data-access logic in the Orchestrator.
