from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from financial_agent.contracts.enums import ExecutionOutcome, SubtaskImportance, ToolStatus
from financial_agent.contracts.execution import BindingValue, ExecutionTask, ToolResult
from financial_agent.planning.contracts import QueryPlanCompilation

from .contracts import ExecutionAttempt, ExecutionFailure, OrchestrationResult
from .executors import (
    BindingTypeInput,
    ExecutorRegistry,
    TaskExecutionInput,
    build_tool_result,
)
from .graph import ExecutionGraphCompiler
from .validation import ToolResultContractError, validate_tool_result


_TRANSIENT = frozenset({ToolStatus.TIMEOUT, ToolStatus.TRANSIENT_ERROR})


@dataclass(frozen=True, slots=True)
class _TaskOutcome:
    task: ExecutionTask
    result: ToolResult | None
    attempts: tuple[ExecutionAttempt, ...]
    failure: ExecutionFailure | None


class _RetryBudget:
    def __init__(self, count: int) -> None:
        self._remaining = count
        self._lock = asyncio.Lock()

    async def consume(self) -> bool:
        async with self._lock:
            if self._remaining <= 0:
                return False
            self._remaining -= 1
            return True


class Orchestrator:
    def __init__(
        self,
        *,
        graph_compiler: ExecutionGraphCompiler,
        executors: ExecutorRegistry,
        hard_deadline_ms: int = 55_000,
        max_concurrency: int = 4,
    ) -> None:
        if not 0 < hard_deadline_ms <= 55_000:
            raise ValueError("hard deadline must be within 55 seconds")
        if max_concurrency <= 0:
            raise ValueError("max concurrency must be positive")
        self._graph_compiler = graph_compiler
        self._executors = executors
        self._hard_deadline_ms = hard_deadline_ms
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def execute(
        self,
        compilation: QueryPlanCompilation,
    ) -> OrchestrationResult:
        graph = self._graph_compiler.compile(compilation)
        self._executors.require({item.capability for item in graph.tasks})
        assert compilation.query_plan is not None
        importance_by_subtask = {
            item.subtask_id: item.importance for item in compilation.query_plan.subtasks
        }
        binding_types = tuple(
            BindingTypeInput(
                binding_name=item.binding_name,
                value_type=item.value_type,
            )
            for item in graph.binding_specs
        )
        start = time.monotonic()
        deadline = start + self._hard_deadline_ms / 1000
        retry_budget = _RetryBudget(2)
        pending = {item.task_id: item for item in graph.tasks}
        final_results: dict[str, ToolResult] = {}
        attempts: list[ExecutionAttempt] = []
        failures: list[ExecutionFailure] = []
        skipped: list[str] = []
        benign_skipped: set[str] = set()
        hard_skipped: set[str] = set()

        while pending:
            ready = [
                task
                for task in graph.tasks
                if task.task_id in pending
                and all(
                    dependency not in pending for dependency in task.depends_on
                )
            ]
            if not ready:
                raise RuntimeError("ORCHESTRATOR_GRAPH_STALLED")
            runnable: list[ExecutionTask] = []
            failed_task_ids = {item.task_id for item in failures}
            for task in ready:
                if any(
                    dependency in benign_skipped
                    or (
                        dependency in final_results
                        and final_results[dependency].status is ToolStatus.EMPTY
                    )
                    for dependency in task.depends_on
                ):
                    skipped.append(task.task_id)
                    benign_skipped.add(task.task_id)
                    pending.pop(task.task_id)
                elif any(
                    dependency in skipped
                    or dependency in failed_task_ids
                    or final_results[dependency].status is not ToolStatus.SUCCESS
                    for dependency in task.depends_on
                ):
                    skipped.append(task.task_id)
                    hard_skipped.add(task.task_id)
                    pending.pop(task.task_id)
                else:
                    runnable.append(task)
            outcomes = await asyncio.gather(
                *(
                    self._run_task(
                        task,
                        graph,
                        compilation.query_plan,
                        final_results,
                        binding_types,
                        deadline,
                        retry_budget,
                    )
                    for task in runnable
                )
            )
            for outcome in outcomes:
                pending.pop(outcome.task.task_id)
                attempts.extend(outcome.attempts)
                if outcome.result is not None:
                    final_results[outcome.task.task_id] = outcome.result
                if outcome.failure is not None:
                    failures.append(outcome.failure)

        failed_task_ids = {item.task_id for item in failures} | hard_skipped
        critical_failed = any(
            importance_by_subtask[
                next(task.subtask_id for task in graph.tasks if task.task_id == task_id)
            ]
            is SubtaskImportance.CRITICAL
            for task_id in failed_task_ids
        )
        if critical_failed:
            execution_outcome = ExecutionOutcome.FAILED
        elif failed_task_ids:
            execution_outcome = ExecutionOutcome.COMPLETED_WITH_FAILURES
        else:
            execution_outcome = ExecutionOutcome.COMPLETED
        completed = tuple(
            task.task_id
            for task in graph.tasks
            if task.task_id in final_results
            and final_results[task.task_id].status
            in {ToolStatus.SUCCESS, ToolStatus.EMPTY}
        )
        ordered_results = tuple(
            final_results[task.task_id]
            for task in graph.tasks
            if task.task_id in final_results
        )
        return OrchestrationResult(
            request_key=graph.request_key,
            run_id=graph.run_id,
            dataset_version=graph.dataset_version,
            producer="orchestrator",
            created_at=graph.created_at,
            graph=graph,
            execution_outcome=execution_outcome,
            tool_results=ordered_results,
            attempts=tuple(attempts),
            failures=tuple(failures),
            completed_task_ids=completed,
            skipped_task_ids=tuple(skipped),
        )

    async def _run_task(
        self,
        task,
        graph,
        query_plan,
        final_results,
        binding_types,
        deadline,
        retry_budget,
    ) -> _TaskOutcome:
        binding_values = _binding_values(task, final_results)
        request = TaskExecutionInput(
            request_key=graph.request_key,
            run_id=graph.run_id,
            dataset_version=graph.dataset_version,
            cutoff_date=graph.cutoff_date,
            created_at=graph.created_at,
            task=task,
            query_plan=query_plan,
            dependency_results=tuple(
                final_results[item] for item in task.depends_on
            ),
            binding_values=binding_values,
            binding_types=binding_types,
        )
        attempt_records: list[ExecutionAttempt] = []
        for attempt_number in (1, 2):
            attempt_started = time.monotonic()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result = build_tool_result(
                    request,
                    status=ToolStatus.TIMEOUT,
                    latency_ms=0,
                )
            else:
                try:
                    async with self._semaphore:
                        result = await asyncio.wait_for(
                            self._executors.get(task.capability).execute(request),
                            timeout=min(remaining, task.budget_ms / 1000),
                        )
                    validate_tool_result(request, result)
                except asyncio.TimeoutError:
                    result = build_tool_result(
                        request,
                        status=ToolStatus.TIMEOUT,
                        latency_ms=task.budget_ms,
                    )
                except ToolResultContractError as error:
                    attempt_records.append(
                        ExecutionAttempt(
                            task_id=task.task_id,
                            attempt_number=attempt_number,
                            status=result.status,
                            latency_ms=result.latency_ms,
                        )
                    )
                    return _TaskOutcome(
                        task=task,
                        result=None,
                        attempts=tuple(attempt_records),
                        failure=ExecutionFailure(
                            task_id=task.task_id,
                            code=str(error),
                            transient=False,
                        ),
                    )
                except Exception:
                    attempt_records.append(
                        ExecutionAttempt(
                            task_id=task.task_id,
                            attempt_number=attempt_number,
                            status=ToolStatus.PERMANENT_ERROR,
                            latency_ms=max(
                                0,
                                int((time.monotonic() - attempt_started) * 1000),
                            ),
                        )
                    )
                    return _TaskOutcome(
                        task=task,
                        result=None,
                        attempts=tuple(attempt_records),
                        failure=ExecutionFailure(
                            task_id=task.task_id,
                            code="EXECUTOR_EXCEPTION",
                            transient=False,
                        ),
                    )
            attempt_records.append(
                ExecutionAttempt(
                    task_id=task.task_id,
                    attempt_number=attempt_number,
                    status=result.status,
                    latency_ms=result.latency_ms,
                )
            )
            if result.status in {ToolStatus.SUCCESS, ToolStatus.EMPTY}:
                return _TaskOutcome(task, result, tuple(attempt_records), None)
            if (
                result.status not in _TRANSIENT
                or attempt_number == 2
                or deadline <= time.monotonic()
                or not await retry_budget.consume()
            ):
                return _TaskOutcome(
                    task=task,
                    result=result,
                    attempts=tuple(attempt_records),
                    failure=ExecutionFailure(
                        task_id=task.task_id,
                        code=_failure_code(result.status),
                        transient=result.status in _TRANSIENT,
                    ),
                )
        raise AssertionError("bounded attempt loop must return")


def _binding_values(task, final_results) -> tuple[BindingValue, ...]:
    available = {
        item.binding_name: item
        for result in final_results.values()
        for item in result.binding_values
    }
    missing = set(task.binding_inputs) - set(available)
    if missing:
        raise RuntimeError(f"REQUIRED_BINDING_MISSING:{sorted(missing)}")
    return tuple(available[item] for item in task.binding_inputs)


def _failure_code(status: ToolStatus) -> str:
    return {
        ToolStatus.TIMEOUT: "TASK_TIMEOUT",
        ToolStatus.TRANSIENT_ERROR: "TASK_TRANSIENT_ERROR",
        ToolStatus.PERMANENT_ERROR: "TASK_PERMANENT_ERROR",
        ToolStatus.INVALID_INPUT: "TASK_INVALID_INPUT",
        ToolStatus.UNSUPPORTED: "TASK_UNSUPPORTED",
        ToolStatus.EMPTY: "TASK_EMPTY",
    }.get(status, "TASK_FAILED")
