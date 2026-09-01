import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from financial_agent.contracts.enums import (
    Capability,
    ExecutionOutcome,
    SubtaskImportance,
    ToolStatus,
)
from financial_agent.contracts.execution import BindingValue, ToolResult
from financial_agent.contracts.values import encode_contract_value
from financial_agent.intent.catalog import load_catalog
from financial_agent.orchestration.executors import (
    CapabilityExecutor,
    ExecutorRegistry,
    TaskExecutionInput,
    build_tool_result,
)
from financial_agent.orchestration.graph import ExecutionGraphCompiler
from financial_agent.orchestration.service import Orchestrator
from financial_agent.orchestration.contracts import OrchestrationResult
from financial_agent.planning.compiler import QueryPlanCompiler
from financial_agent.planning.registry import load_planning_registry

from tests.planning.fixtures import frame, resolution, view


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def compilation(*, context: bool = False):
    return QueryPlanCompiler(
        catalog=load_catalog(PROJECT_ROOT),
        registry=load_planning_registry(PROJECT_ROOT),
    ).compile(resolution(context=context), view(context=context))


def parallel_compilation(*, optional_second: bool = False):
    source = resolution(context=True)
    resolved = source.model_copy(
        update={
            "context_links": (),
            "final_tags": (),
        }
    )
    compiled = QueryPlanCompiler(
        catalog=load_catalog(PROJECT_ROOT),
        registry=load_planning_registry(PROJECT_ROOT),
    ).compile(resolved, view(context=True))
    if optional_second:
        assert compiled.query_plan is not None
        subtasks = tuple(
            item.model_copy(
                update={"importance": SubtaskImportance.OPTIONAL}
            )
            if item.subtask_id == "frame-2"
            else item
            for item in compiled.query_plan.subtasks
        )
        compiled = compiled.model_copy(
            update={
                "query_plan": compiled.query_plan.model_copy(
                    update={"subtasks": subtasks}
                )
            }
        )
    return compiled


@dataclass
class RecordingExecutor(CapabilityExecutor):
    transient_first: bool = False
    permanent: bool = False
    delay_seconds: float = 0.0
    calls: list[TaskExecutionInput] = field(default_factory=list)
    active: int = 0
    max_active: int = 0
    tamper_hash: bool = False
    permanent_subtask_ids: frozenset[str] = frozenset()
    empty: bool = False

    async def execute(self, request: TaskExecutionInput) -> ToolResult:
        self.calls.append(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            if self.empty:
                status = ToolStatus.EMPTY
            elif self.permanent or request.task.subtask_id in self.permanent_subtask_ids:
                status = ToolStatus.PERMANENT_ERROR
            elif self.transient_first and len(self.calls) == 1:
                status = ToolStatus.TRANSIENT_ERROR
            else:
                status = ToolStatus.SUCCESS
            bindings = (
                tuple(
                    BindingValue(
                        binding_name=name,
                        value_type=request.binding_type(name),
                        value=encode_contract_value(("entity-1", "entity-2")),
                    )
                    for name in request.task.produces_bindings
                )
                if status is ToolStatus.SUCCESS
                else ()
            )
            result = build_tool_result(
                request,
                status=status,
                binding_values=bindings,
                evidence_refs=("evidence-1",)
                if status is ToolStatus.SUCCESS
                else (),
                latency_ms=1,
            )
            return (
                result.model_copy(update={"result_hash": "0" * 64})
                if self.tamper_hash
                else result
            )
        finally:
            self.active -= 1


@dataclass
class TransientOncePerTaskExecutor(CapabilityExecutor):
    attempts_by_task: dict[str, int] = field(default_factory=dict)

    async def execute(self, request: TaskExecutionInput) -> ToolResult:
        count = self.attempts_by_task.get(request.task.task_id, 0) + 1
        self.attempts_by_task[request.task.task_id] = count
        return build_tool_result(
            request,
            status=(ToolStatus.TRANSIENT_ERROR if count == 1 else ToolStatus.SUCCESS),
            evidence_refs=("evidence-1",) if count > 1 else (),
            latency_ms=1,
        )


class RaisingExecutor(CapabilityExecutor):
    async def execute(self, request: TaskExecutionInput) -> ToolResult:
        raise RuntimeError("executor implementation bug")


def orchestrator(executors: ExecutorRegistry, *, deadline_ms: int = 5_000):
    registry = load_planning_registry(PROJECT_ROOT)
    return Orchestrator(
        graph_compiler=ExecutionGraphCompiler(registry),
        executors=executors,
        hard_deadline_ms=deadline_ms,
        max_concurrency=4,
    )


def test_context_pipeline_publishes_binding_before_downstream_execution() -> None:
    """Catches a dependent executor seeing no value for its declared binding."""
    lookup = RecordingExecutor()
    rank = RecordingExecutor()
    service = orchestrator(
        ExecutorRegistry(
            (
                (Capability.RDB_LOOKUP, lookup),
                (Capability.RANKING, rank),
            )
        )
    )

    result = asyncio.run(service.execute(compilation(context=True)))

    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert len(result.tool_results) == 3
    assert rank.calls[0].dependency_results[0].task_id == (
        "task:operation:frame-1:lookup-products"
    )
    assert rank.calls[1].binding_values[0].binding_name == (
        "binding:frame-1:top_k_products"
    )
    assert rank.calls[1].dependency_results[0].task_id == (
        "task:operation:frame-1:rank-products"
    )
    assert rank.calls[1].binding_values[0].value_type == "top_k_products"
    assert rank.calls[1].query_plan == compilation(context=True).query_plan


def test_transient_result_retries_once_and_permanent_result_does_not() -> None:
    """Catches unbounded retry loops or retries of deterministic failures."""
    lookup = RecordingExecutor()
    transient_rank = RecordingExecutor(transient_first=True)
    retry_result = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, lookup),
                    (Capability.RANKING, transient_rank),
                )
            )
        ).execute(compilation())
    )

    assert retry_result.execution_outcome is ExecutionOutcome.COMPLETED
    assert len(transient_rank.calls) == 2
    assert [item.attempt_number for item in retry_result.attempts][-2:] == [1, 2]

    permanent_rank = RecordingExecutor(permanent=True)
    failed = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, RecordingExecutor()),
                    (Capability.RANKING, permanent_rank),
                )
            )
        ).execute(compilation())
    )
    assert failed.execution_outcome is ExecutionOutcome.FAILED
    assert len(permanent_rank.calls) == 1


def test_deadline_cancels_slow_executor_and_returns_failed_outcome() -> None:
    """Catches work continuing beyond the request hard deadline."""
    slow_lookup = RecordingExecutor(delay_seconds=0.05)
    result = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, slow_lookup),
                    (Capability.RANKING, RecordingExecutor()),
                )
            ),
            deadline_ms=5,
        ).execute(compilation())
    )

    assert result.execution_outcome is ExecutionOutcome.FAILED
    assert result.failures[0].code == "TASK_TIMEOUT"
    assert result.skipped_task_ids


def test_independent_lookup_tasks_run_concurrently() -> None:
    """Catches a scheduler accidentally serializing independent family work."""
    lookup = RecordingExecutor(delay_seconds=0.02)
    result = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, lookup),
                    (Capability.RANKING, RecordingExecutor()),
                )
            )
        ).execute(parallel_compilation())
    )

    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert lookup.max_active == 2


def test_optional_failure_is_completed_with_failures() -> None:
    """Catches an optional comparison failure invalidating a verified critical rank."""
    result = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, RecordingExecutor()),
                    (
                        Capability.RANKING,
                        RecordingExecutor(
                            permanent_subtask_ids=frozenset({"frame-2"})
                        ),
                    ),
                )
            )
        ).execute(parallel_compilation(optional_second=True))
    )

    assert result.execution_outcome is ExecutionOutcome.COMPLETED_WITH_FAILURES
    assert result.failures[0].code == "TASK_PERMANENT_ERROR"


def test_invalid_producer_result_fails_and_skips_downstream_without_crashing() -> None:
    """Catches contract-invalid output causing a scheduler KeyError."""
    result = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, RecordingExecutor(tamper_hash=True)),
                    (Capability.RANKING, RecordingExecutor()),
                )
            )
        ).execute(compilation())
    )

    assert result.execution_outcome is ExecutionOutcome.FAILED
    assert result.failures[0].code == "TOOL_RESULT_HASH_MISMATCH"
    assert result.attempts[0].task_id == "task:operation:frame-1:lookup-products"
    assert result.skipped_task_ids == ("task:operation:frame-1:rank-products",)


def test_executor_exception_becomes_a_permanent_failure_result() -> None:
    """Catches one executor implementation error crashing the request scheduler."""
    result = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, RaisingExecutor()),
                    (Capability.RANKING, RecordingExecutor()),
                )
            )
        ).execute(compilation())
    )

    assert result.execution_outcome is ExecutionOutcome.FAILED
    assert result.failures[0].code == "EXECUTOR_EXCEPTION"
    assert result.failures[0].transient is False
    assert result.attempts[0].status is ToolStatus.PERMANENT_ERROR


def test_empty_lookup_is_completed_and_benignly_skips_downstream() -> None:
    """Catches a verified zero-row query being misreported as a system failure."""
    result = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, RecordingExecutor(empty=True)),
                    (Capability.RANKING, RecordingExecutor()),
                )
            )
        ).execute(compilation())
    )

    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert result.failures == ()
    assert result.tool_results[0].status is ToolStatus.EMPTY
    assert result.completed_task_ids == (
        "task:operation:frame-1:lookup-products",
    )
    assert result.skipped_task_ids == (
        "task:operation:frame-1:rank-products",
    )


def test_orchestration_result_rejects_a_graph_task_without_terminal_state() -> None:
    """Catches a scheduler returning while work is neither done, failed, nor skipped."""
    result = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, RecordingExecutor()),
                    (Capability.RANKING, RecordingExecutor()),
                )
            )
        ).execute(compilation())
    )
    payload = result.model_dump()
    payload["completed_task_ids"] = payload["completed_task_ids"][:-1]

    with pytest.raises(ValueError, match="one terminal state"):
        OrchestrationResult.model_validate(payload)


def test_transient_retry_budget_is_shared_across_tasks() -> None:
    """Catches each task incorrectly receiving its own two-retry allowance."""
    source = resolution()
    frames = tuple(
        frame(
            f"frame-{index}",
            index - 1,
            metric_id="aum",
            limit_id="literal-limit-5",
        )
        for index in (1, 2, 3)
    )
    three = source.model_copy(
        update={"canonical_frames": frames, "resolution_id": "resolution-three"}
    )
    compiled = QueryPlanCompiler(
        catalog=load_catalog(PROJECT_ROOT),
        registry=load_planning_registry(PROJECT_ROOT),
    ).compile(three, view())
    ranking = TransientOncePerTaskExecutor()

    result = asyncio.run(
        orchestrator(
            ExecutorRegistry(
                (
                    (Capability.RDB_LOOKUP, RecordingExecutor()),
                    (Capability.RANKING, ranking),
                )
            )
        ).execute(compiled)
    )

    assert result.execution_outcome is ExecutionOutcome.FAILED
    assert sum(ranking.attempts_by_task.values()) == 5
    assert sorted(ranking.attempts_by_task.values()) == [1, 2, 2]
