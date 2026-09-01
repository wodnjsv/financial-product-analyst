from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, RuntimeArtifact
from financial_agent.contracts.enums import ExecutionOutcome, ToolStatus
from financial_agent.contracts.execution import ExecutionGraph, ToolResult
from financial_agent.contracts.validation import require_unique_ids


class ExecutionAttempt(ContractModel):
    task_id: Identifier
    attempt_number: int = Field(ge=1, le=2)
    status: ToolStatus
    latency_ms: int = Field(ge=0)


class ExecutionFailure(ContractModel):
    task_id: Identifier
    code: Identifier
    transient: bool


class OrchestrationResult(RuntimeArtifact):
    graph: ExecutionGraph
    execution_outcome: ExecutionOutcome
    tool_results: tuple[ToolResult, ...]
    attempts: tuple[ExecutionAttempt, ...]
    failures: tuple[ExecutionFailure, ...]
    completed_task_ids: tuple[Identifier, ...]
    skipped_task_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_result(self) -> "OrchestrationResult":
        require_unique_ids(
            (item.task_id for item in self.tool_results),
            label="final tool results",
        )
        require_unique_ids(self.completed_task_ids, label="completed tasks")
        require_unique_ids(self.skipped_task_ids, label="skipped tasks")
        require_unique_ids(
            (item.task_id for item in self.failures),
            label="failed tasks",
        )
        attempt_keys = tuple(
            f"{item.task_id}:{item.attempt_number}" for item in self.attempts
        )
        require_unique_ids(attempt_keys, label="execution attempts")
        graph_task_ids = {item.task_id for item in self.graph.tasks}
        completed = set(self.completed_task_ids)
        skipped = set(self.skipped_task_ids)
        failed = {item.task_id for item in self.failures}
        if completed & skipped or completed & failed or skipped & failed:
            raise ValueError("task terminal states must be disjoint")
        if completed | skipped | failed != graph_task_ids:
            raise ValueError("every graph task requires one terminal state")
        result_by_task = {item.task_id: item for item in self.tool_results}
        successful = {
            task_id
            for task_id, result in result_by_task.items()
            if result.status in {ToolStatus.SUCCESS, ToolStatus.EMPTY}
        }
        unsuccessful = set(result_by_task) - successful
        if successful != completed or not unsuccessful <= failed:
            raise ValueError("tool results must match task terminal states")
        attempted = {item.task_id for item in self.attempts}
        if attempted != completed | failed:
            raise ValueError("executed terminal tasks require attempt records")
        if (
            self.graph.request_key != self.request_key
            or self.graph.run_id != self.run_id
            or self.graph.dataset_version != self.dataset_version
            or self.graph.cutoff_date != self.cutoff_date
            or any(
                item.request_key != self.request_key
                or item.run_id != self.run_id
                or item.dataset_version != self.dataset_version
                or item.cutoff_date != self.cutoff_date
                for item in self.tool_results
            )
        ):
            raise ValueError("orchestration artifact pins must match")
        return self
