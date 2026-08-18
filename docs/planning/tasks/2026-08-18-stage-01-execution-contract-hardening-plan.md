# Stage 01 Execution Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-08-18

**Status:** Implemented in `60de716` and verified on the development host and NCP Ubuntu/Linux-amd64; the separate Stage 01 closure-review register remains open

**Goal:** Make every compiled task and intermediate binding traceable from `QueryPlan` through `ExecutionGraph` to `ToolResult`, and reject contradictory result states and impossible serial budgets before later storage or orchestration work begins.

**Architecture:** Keep the official evaluation API unchanged. Add explicit subtask ownership and binding-output declarations to the internal `ExecutionTask`, enforce graph-local invariants inside Pydantic models, and add deterministic compatibility functions for invariants that span separately created artifacts. Do not infer binding ownership from names or LLM prose.

**Tech Stack:** Python 3.12, Pydantic 2.x, pytest 8.x, deterministic JSON Schema export, Docker Linux/amd64 verification on Naver Cloud Ubuntu.

## Implementation and Verification Record at 2026-08-18

- `ExecutionTask` ownership and binding-output declarations, graph-local invariants, cross-artifact compatibility checks, coherent fixtures, and refreshed schemas were implemented in `60de716`.
- The development host passed all 116 contract tests, deterministic Schema freshness checking, Python bytecode compilation, and repository diff checks before the commit was pushed.
- The NCP Ubuntu host pulled `60de716` and successfully built the Linux/amd64 verification image. The image build completed its locked dependency installation, full contract suite, and Schema freshness check.
- Running the resulting image without local volumes or secrets exited with code 0.
- This completes the execution-contract hardening amendment only. Stage 01 remains open until every item in the closure-review register is decided, implemented where required, and reverified.

## Global Constraints

- The cutoff remains exactly `2026-07-11`.
- The official five-string evaluation API does not change.
- Contract models remain immutable, reject unknown fields, and normalize JSON arrays to tuples.
- `ExecutionTask.operation_id` references a `QueryPlan.operations.operation_id` owned by the same `subtask_id`; multiple compiled tasks may reference the same logical operation.
- Every `binding_inputs` and `produces_bindings` name exists in `ExecutionGraph.binding_specs`.
- Each binding has exactly one declared producer task, whose `subtask_id` equals `BindingSpec.producer_subtask_id`.
- A binding consumer depends transitively on its producer and cannot also produce that binding.
- `critical_path` is a duplicate-free direct DAG path and its serial budget sum cannot exceed `total_budget_ms`.
- `ToolResult` cannot release a binding not declared by its task.
- `Cardinality.ONE` uses a non-tuple scalar; `Cardinality.MANY` uses a tuple.
- Filtering, ranking, arithmetic, retries, and runtime dispatch remain outside this plan.
- Tests use only synthetic fixtures; no organizer data or secrets enter Git or the Docker context.

---

## Assumptions, Outcome, and Non-Goals

### Assumptions

- Stage 01 schemas are not field-frozen until this approved amendment passes.
- QueryPlan operation IDs are logical registered operations. Capability-specific execution is identified by the pair `(ExecutionTask.capability, ExecutionTask.operation_id)`.
- A ToolResult is validated against one ExecutionTask at a time; orchestration completeness across all scheduled tasks belongs to a later Orchestrator state model.
- Empty and error results may retain evidence references, exclusions, and warnings for audit, but never successful rows or binding values.

### Intended outcome

At completion:

1. a task can be traced to one QueryPlan subtask and operation;
2. every intermediate value has one declared producer and dependency-safe consumers;
3. one-versus-many binding shape is verified before a value reaches a downstream task;
4. critical-path budgets cannot silently exceed the graph budget;
5. contradictory ToolResult states fail validation;
6. exported schemas, host tests, Linux/amd64 image tests, and the NCP container command all pass.

### Non-goals

- Do not implement an Orchestrator, task scheduler, Capability Executor, retry loop, database, or API endpoint.
- Do not add a general registry framework; operation and Capability membership is checked against the supplied QueryPlan only.
- Do not implement the later Claim Gate renderer/template Registry checks.
- Do not address the separate closure-review items for strict ingress, canonical scalar coverage, ClaimSupport semantics, or schema mutation testing in this change.

## File Responsibility Map

| File | Responsibility |
| --- | --- |
| `src/financial_agent/contracts/execution.py` | task ownership, declared outputs, graph-local invariants, ToolResult state invariants |
| `src/financial_agent/contracts/compatibility.py` | deterministic QueryPlan–ExecutionGraph and ExecutionGraph–ToolResult compatibility checks |
| `src/financial_agent/contracts/__init__.py` | export the two compatibility functions without renaming existing symbols |
| `tests/contracts/test_execution.py` | graph-local and ToolResult state regression tests |
| `tests/contracts/test_compatibility.py` | cross-artifact identity, ownership, result-type, value-type, and cardinality tests |
| `tests/fixtures/contracts/v1/query_plan.json` | coherent synthetic logical subtasks, operations, capabilities, and binding declarations |
| `tests/fixtures/contracts/v1/execution_graph.json` | coherent compiled tasks, unique producers, dependencies, and budget path |
| `tests/fixtures/contracts/v1/tool_result.json` | a valid many-valued output produced by its declared task |
| `schemas/contracts/v1/*.schema.json` | freshly exported structural contract schemas |

## Rejected Alternatives

### Infer ownership only from `operation_id`

Rejected because the current fixture already contains lower-level operation names absent from QueryPlan, and one logical operation may compile to several Capability tasks. Explicit `subtask_id` is cheaper and auditable.

### Keep only a cross-artifact validator

Rejected because undeclared inputs, duplicate producers, disconnected consumers, and impossible critical paths are invalid inside an ExecutionGraph even when no QueryPlan or ToolResult object is present.

### Add a new aggregate runtime artifact

Rejected because it would create a ninth persisted contract solely to run validation. Two focused deterministic functions preserve the existing seven contract groups.

---

### Task 1: Make task ownership, binding production, and serial budgets explicit

**Files:**

- Modify: `src/financial_agent/contracts/execution.py`
- Modify: `tests/contracts/test_execution.py`
- Modify: `tests/fixtures/contracts/v1/query_plan.json`
- Modify: `tests/fixtures/contracts/v1/execution_graph.json`
- Modify: `tests/fixtures/contracts/v1/tool_result.json`

**Interfaces:**

- Consumes: `BindingSpec`, `Cardinality`, existing DAG helpers.
- Produces: `ExecutionTask.subtask_id: Identifier`, `ExecutionTask.produces_bindings: tuple[Identifier, ...]`, graph-local producer and critical-path validation.

- [ ] **Step 1: Rewrite the synthetic fixtures into one coherent execution chain**

Use these binding definitions:

```json
[
  {
    "binding_name": "s1.company",
    "value_type": "entity_ref",
    "producer_subtask_id": "q1",
    "cardinality": "one"
  },
  {
    "binding_name": "s1.candidate_products",
    "value_type": "product_ref_list",
    "producer_subtask_id": "q1",
    "cardinality": "many"
  },
  {
    "binding_name": "s1.top5_products",
    "value_type": "product_ref_list",
    "producer_subtask_id": "q1",
    "cardinality": "many"
  }
]
```

Keep `q1` with the logical operation `op-screen-top5` and `q2` with `op-rank-return`. Build tasks `t1` through `t4` with matching `subtask_id`; `t1`, `t2`, and `t3` all reference `op-screen-top5`, while their different Capability values identify entity search, graph traversal, and ranking stages. `t4` references `op-rank-return`. Make each task after `t1` consume the preceding binding, make `t3` produce `s1.top5_products`, and make `t4` consume it. Use a direct critical path `t1 → t2 → t3 → t4` with budgets `4_000`, `4_000`, `5_000`, and `7_000`, which sum to `20_000`. Keep `tool_result.json` attached to `t3` and encode `s1.top5_products` as a JSON array.

- [ ] **Step 2: Write failing graph-local invariant tests**

Add focused mutations proving rejection of:

```python
@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["tasks"][1].update(binding_inputs=["missing.binding"]),
        lambda payload: payload["tasks"][1].update(produces_bindings=["missing.binding"]),
        lambda payload: payload["tasks"][1].update(
            binding_inputs=["s1.company"],
            produces_bindings=["s1.company"],
        ),
        lambda payload: payload["tasks"][1].update(depends_on=[]),
        lambda payload: payload["tasks"][2].update(
            produces_bindings=["s1.company", "s1.top5_products"]
        ),
        lambda payload: payload.update(critical_path=["t1", "t3"]),
        lambda payload: payload.update(critical_path=["t1", "t2", "t2"]),
        lambda payload: payload["tasks"][3].update(budget_ms=7_001),
    ],
)
def test_execution_graph_rejects_binding_and_path_inconsistencies(
    load_fixture, mutation
) -> None:
    payload = load_fixture("execution_graph.json")
    mutation(payload)
    with pytest.raises(ValidationError):
        ExecutionGraph.model_validate(payload)
```

- [ ] **Step 3: Run the focused tests and verify they fail**

Run: `python -m pytest tests/contracts/test_execution.py -q`

Expected: FAIL because `subtask_id`, `produces_bindings`, producer ownership, and serial path-budget validation are not implemented.

- [ ] **Step 4: Implement the minimal graph-local validation**

Extend the task contract exactly as follows:

```python
class ExecutionTask(ContractModel):
    task_id: Identifier
    subtask_id: Identifier
    capability: Capability
    operation_id: Identifier
    literal_inputs: tuple[NamedValue, ...] = ()
    binding_inputs: tuple[Identifier, ...] = ()
    produces_bindings: tuple[Identifier, ...] = ()
    depends_on: tuple[Identifier, ...] = ()
    expected_output_type: ResultType
    required_evidence_fields: tuple[Identifier, ...]
    budget_ms: int = Field(gt=0)
```

Inside `ExecutionGraph.validate_graph`, validate unique binding definitions, known input/output names, unique output ownership, producer-subtask equality, no input/output overlap, producer ancestry for every consumer, unique/direct critical-path IDs, and `sum(task.budget_ms for task in critical_path) <= total_budget_ms`.

- [ ] **Step 5: Run the focused tests**

Run: `python -m pytest tests/contracts/test_execution.py -q`

Expected: all execution tests PASS.

- [ ] **Step 6: Commit the graph-local contract**

```bash
git add src/financial_agent/contracts/execution.py tests/contracts/test_execution.py tests/fixtures/contracts/v1/query_plan.json tests/fixtures/contracts/v1/execution_graph.json tests/fixtures/contracts/v1/tool_result.json
git diff --cached --check
git diff --cached
git commit -m "fix: enforce execution graph bindings"
```

### Task 2: Validate QueryPlan and ExecutionGraph compatibility

**Files:**

- Create: `src/financial_agent/contracts/compatibility.py`
- Modify: `src/financial_agent/contracts/__init__.py`
- Create: `tests/contracts/test_compatibility.py`

**Interfaces:**

- Consumes: `QueryPlan`, `ExecutionGraph`.
- Produces: `validate_execution_graph_compatibility(query_plan: QueryPlan, execution_graph: ExecutionGraph) -> None`.

- [ ] **Step 1: Write the passing baseline and failing compatibility tests**

```python
def test_query_plan_and_execution_graph_are_compatible(load_fixture) -> None:
    plan = QueryPlan.model_validate(load_fixture("query_plan.json"))
    graph = ExecutionGraph.model_validate(load_fixture("execution_graph.json"))
    validate_execution_graph_compatibility(plan, graph)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(run_id="other-run"),
        lambda payload: payload["binding_specs"][0].update(value_type="wrong-type"),
        lambda payload: payload["tasks"][3].update(subtask_id="missing-subtask"),
        lambda payload: payload["tasks"][0].update(operation_id="op-rank-return"),
        lambda payload: payload["tasks"][0].update(capability="vector_search"),
    ],
)
def test_query_plan_and_execution_graph_reject_mismatches(
    load_fixture, mutation
) -> None:
    plan = QueryPlan.model_validate(load_fixture("query_plan.json"))
    payload = load_fixture("execution_graph.json")
    mutation(payload)
    graph = ExecutionGraph.model_validate(payload)
    with pytest.raises(ValueError):
        validate_execution_graph_compatibility(plan, graph)
```

- [ ] **Step 2: Run the focused test and verify the module is missing**

Run: `python -m pytest tests/contracts/test_compatibility.py -q`

Expected: collection FAIL because `financial_agent.contracts.compatibility` does not exist.

- [ ] **Step 3: Implement exact cross-artifact checks**

The function must compare `request_key`, `run_id`, `dataset_version`, and `cutoff_date`; compare binding specs by `binding_name` without depending on tuple order; require each task subtask and operation to exist and belong together; and require every task capability to be listed in `QueryPlan.requested_capabilities`. Raise `ValueError` with a stable field-oriented message at the first mismatch.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/contracts/test_compatibility.py -q`

Expected: all QueryPlan–ExecutionGraph compatibility tests PASS.

- [ ] **Step 5: Commit cross-artifact plan validation**

```bash
git add src/financial_agent/contracts/compatibility.py src/financial_agent/contracts/__init__.py tests/contracts/test_compatibility.py
git diff --cached --check
git diff --cached
git commit -m "feat: validate compiled execution graphs"
```

### Task 3: Validate ToolResult state and graph compatibility

**Files:**

- Modify: `src/financial_agent/contracts/execution.py`
- Modify: `src/financial_agent/contracts/compatibility.py`
- Modify: `tests/contracts/test_execution.py`
- Modify: `tests/contracts/test_compatibility.py`

**Interfaces:**

- Consumes: `ExecutionGraph`, `ToolResult`, declared task outputs and BindingSpecs.
- Produces: `validate_tool_result_compatibility(execution_graph: ExecutionGraph, tool_result: ToolResult) -> None`.

- [ ] **Step 1: Write failing ToolResult state tests**

```python
@pytest.mark.parametrize(
    "status",
    [
        "empty",
        "unsupported",
        "invalid_input",
        "timeout",
        "transient_error",
        "permanent_error",
    ],
)
def test_non_success_tool_result_rejects_success_payload(
    load_fixture, status
) -> None:
    payload = load_fixture("tool_result.json")
    payload["status"] = status
    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)
```

Also prove that `empty` remains valid when both payload collections are empty.

- [ ] **Step 2: Write failing graph–result compatibility tests**

Mutate one field at a time and require rejection for a mismatched run ID, unknown task ID, wrong result type, undeclared output binding, wrong `value_type`, scalar value for `many`, and tuple value for `one`.

- [ ] **Step 3: Run the focused tests and verify they fail**

Run: `python -m pytest tests/contracts/test_execution.py tests/contracts/test_compatibility.py -q`

Expected: FAIL because state-shape and graph–result compatibility checks are missing.

- [ ] **Step 4: Implement the minimal validators**

`ToolResult.validate_result` rejects rows or binding values for every status other than `success`. `validate_tool_result_compatibility` compares runtime identity fields, finds the declared task, compares `result_type`, requires each binding name in the task's `produces_bindings`, compares `value_type`, and checks tuple-versus-scalar shape from `Cardinality`.

- [ ] **Step 5: Run the focused and full host test suites**

Run: `python -m pytest tests/contracts/test_execution.py tests/contracts/test_compatibility.py -q`

Run: `python -m pytest tests/contracts -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit ToolResult compatibility**

```bash
git add src/financial_agent/contracts/execution.py src/financial_agent/contracts/compatibility.py tests/contracts/test_execution.py tests/contracts/test_compatibility.py
git diff --cached --check
git diff --cached
git commit -m "fix: validate tool result compatibility"
```

### Task 4: Regenerate schemas and re-prove NCP portability

**Files:**

- Modify: `schemas/contracts/v1/execution-graph.schema.json`
- Verify: all `schemas/contracts/v1/*.schema.json`
- Verify: `docker/contracts.Dockerfile`
- Verify: `.dockerignore`

**Interfaces:**

- Consumes: final Stage 01 contract models and schema registry.
- Produces: byte-current schemas and host/Linux/NCP verification evidence.

- [ ] **Step 1: Regenerate schemas**

Run: `python scripts/export_contract_schemas.py`

Expected: the execution-graph schema changes for `subtask_id` and `produces_bindings`; unrelated schemas change only if required by shared definitions.

- [ ] **Step 2: Verify host contracts and schema parity**

Run: `python -m pytest tests/contracts -q`

Run: `python scripts/export_contract_schemas.py --check`

Run: `git diff --check`

Expected: all commands succeed.

- [ ] **Step 3: Build and run the Linux/amd64 verification image**

Run: `docker build --platform linux/amd64 -f docker/contracts.Dockerfile -t financial-agent-contracts:stage-01 .`

Run: `docker run --rm --platform linux/amd64 financial-agent-contracts:stage-01`

Expected: the image build runs the complete contract suite successfully and the container exits 0.

- [ ] **Step 4: Inspect scope and repository safety**

Run: `git status --short --ignored`

Run: `git diff -- schemas/contracts/v1`

Confirm that no organizer data, PDF, workbook, secret, local database, embedding, cache, or runtime output is staged.

- [ ] **Step 5: Commit generated schemas and portability proof**

```bash
git add schemas/contracts/v1
git diff --cached --check
git diff --cached
git commit -m "test: refresh execution contract schemas"
```

- [ ] **Step 6: Repeat on the NCP Ubuntu server**

Pull the verified branch, build the same Linux/amd64 image, and run it without local volumes or secrets.

Expected: build succeeds, all contract tests pass inside the image, and `docker run` exits 0.

## Completion Gate

- Both compatibility functions are public imports and deterministic.
- The coherent fixtures validate individually and across their artifact boundaries.
- Every approved negative ownership, dependency, budget, state, type, and cardinality case fails for the intended reason.
- Contract schemas are byte-current.
- Host tests, Linux/amd64 build tests, and the NCP container command pass.
- The official evaluation API schema is unchanged.
- The Stage 01 closure-review register remains visible for the next focused decision.
