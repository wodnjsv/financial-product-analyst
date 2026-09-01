# Deterministic Orchestrator Design

**Status:** Approved for implementation on 2026-09-02

## Goal

Compile a successful QueryPlanCompilation into an ExecutionGraph and execute it
with bounded concurrency, deadlines, retries, typed results, and deterministic
failure classification.

## Components

- `ExecutionGraphCompiler`: expands QueryPlan operations through registered
  primitive task templates, adds data dependencies, computes a deterministic
  critical path, and validates the frozen ExecutionGraph.
- `CapabilityExecutor`: async protocol accepting one ExecutionTask and immutable
  execution input; it returns one ToolResult and cannot schedule other work.
- `ExecutorRegistry`: exact Capability-to-executor mapping; duplicates and
  missing required executors fail before execution.
- `Orchestrator`: dependency scheduler, semaphore owner, retry/deadline budget
  owner, binding publisher, result validator, and outcome classifier.
- `OrchestrationResult`: immutable internal result containing graph, ordered
  ToolResults, attempt records, execution outcome, and stable failure events.

## Scheduling and failure rules

Only dependency-ready tasks run. Independent ready tasks may run concurrently,
bounded by configuration. A downstream task is skipped when a required
dependency is non-success or its binding is absent. Retries are limited to two
request-wide transient retries and one retry for the same task. Every attempt
must fit the remaining hard deadline and the task budget. Deadline exhaustion
is a failed execution, not an answer disposition.

ToolResult validation checks request metadata, task ID, result type, binding
names and types, evidence references for successful factual outputs, and
canonical result hash. Invalid output is a permanent contract failure.

`completed` means all critical and required-independent tasks succeeded.
`completed_with_failures` means all critical tasks succeeded but optional or
independent work failed. `failed` means a critical task failed, the graph was
invalid, a required binding was unavailable, or the deadline expired.

## Boundaries

This phase supplies fake/in-memory executors for behavior tests and the public
executor protocol. Production SQL, SPARQL, search, similarity, comparison, and
calculation implementations remain outside the Orchestrator and are registered
later. No LLM is called by Phase 3.
