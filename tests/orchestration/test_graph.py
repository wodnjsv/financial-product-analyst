from pathlib import Path

import pytest

from financial_agent.contracts.canonical import canonical_json_bytes
from financial_agent.contracts.enums import Capability, IntentType
from financial_agent.contracts.values import decode_contract_value
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.types import SlotKind
from financial_agent.orchestration.graph import (
    ExecutionGraphCompiler,
    GraphCompilationError,
)
from financial_agent.planning.compiler import QueryPlanCompiler
from financial_agent.planning.contracts import QueryPlanCompilation
from financial_agent.planning.registry import load_planning_registry

from tests.planning.fixtures import (
    cross_family_resolution,
    frame,
    resolution,
    slot,
    view,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def planning_compiler() -> QueryPlanCompiler:
    return QueryPlanCompiler(
        catalog=load_catalog(PROJECT_ROOT),
        registry=load_planning_registry(PROJECT_ROOT),
    )


def graph_compiler() -> ExecutionGraphCompiler:
    return ExecutionGraphCompiler(load_planning_registry(PROJECT_ROOT))


def test_rank_plan_expands_to_ordered_lookup_and_rank_tasks() -> None:
    """Catches ranking starting before its candidate lookup is complete."""
    compilation = planning_compiler().compile(resolution(), view())

    graph = graph_compiler().compile(compilation)

    assert [item.capability for item in graph.tasks] == [
        Capability.RDB_LOOKUP,
        Capability.RANKING,
    ]
    assert graph.tasks[1].depends_on == (graph.tasks[0].task_id,)
    limit = next(
        item for item in graph.tasks[1].literal_inputs if item.name == "result_limit"
    )
    assert decode_contract_value(limit.value) == 5
    policy = next(
        item
        for item in graph.tasks[1].literal_inputs
        if item.name == "policy:rank-coverage.v1"
    )
    assert decode_contract_value(policy.value) == "policy:rank-coverage.v1"
    assert graph.critical_path == tuple(item.task_id for item in graph.tasks)


def test_context_rerank_consumes_the_exact_upstream_binding() -> None:
    """Catches a downstream rank task running without the top-five binding."""
    compilation = planning_compiler().compile(
        resolution(context=True),
        view(context=True),
    )

    graph = graph_compiler().compile(compilation)

    assert len(graph.tasks) == 3
    producer = graph.tasks[1]
    consumer = graph.tasks[2]
    assert producer.produces_bindings == ("binding:frame-1:top_k_products",)
    assert consumer.binding_inputs == ("binding:frame-1:top_k_products",)
    assert producer.task_id in consumer.depends_on
    assert graph.critical_path == tuple(item.task_id for item in graph.tasks)


def test_graph_compilation_is_byte_deterministic() -> None:
    """Catches set or scheduler ordering leaking into the persisted graph."""
    compilation = planning_compiler().compile(
        resolution(context=True),
        view(context=True),
    )

    first = graph_compiler().compile(compilation)
    second = graph_compiler().compile(compilation)

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_graph_rejects_compilation_primitive_or_capability_drift() -> None:
    """Catches manifest work being omitted after the compiler boundary."""
    compiled = planning_compiler().compile(resolution(), view())

    primitive_drift = compiled.model_copy(
        update={
            "primitive_ids": (*compiled.primitive_ids, "compare-products"),
        }
    )
    with pytest.raises(GraphCompilationError, match="PRIMITIVE_SET_MISMATCH"):
        graph_compiler().compile(primitive_drift)

    assert compiled.query_plan is not None
    plan = compiled.query_plan.model_copy(
        update={
            "requested_capabilities": (
                *compiled.query_plan.requested_capabilities,
                Capability.COMPARISON,
            )
        }
    )
    capability_drift = compiled.model_copy(update={"query_plan": plan})
    with pytest.raises(GraphCompilationError, match="CAPABILITY_SET_MISMATCH"):
        graph_compiler().compile(capability_drift)


def test_graph_compiler_does_not_require_subtasks_to_be_topologically_ordered() -> None:
    """Catches critical-path calculation relying on incidental tuple order."""
    compiled = planning_compiler().compile(
        resolution(context=True),
        view(context=True),
    )
    assert compiled.query_plan is not None
    plan = compiled.query_plan
    reordered_plan = plan.model_copy(
        update={
            "subtasks": tuple(reversed(plan.subtasks)),
            "operations": tuple(
                operation
                for subtask in reversed(plan.subtasks)
                for operation in plan.operations
                if operation.subtask_id == subtask.subtask_id
            ),
        }
    )
    reordered = QueryPlanCompilation.model_validate(
        compiled.model_copy(update={"query_plan": reordered_plan}).model_dump()
    )

    graph = graph_compiler().compile(reordered)

    assert graph.critical_path[0] == "task:operation:frame-1:lookup-products"
    assert graph.critical_path[-1] == "task:operation:frame-2:rank-products"


def test_cross_family_graph_orders_comparability_normalization_and_ranking() -> None:
    """Catches normalized cross-family work disappearing during graph expansion."""
    compilation = planning_compiler().compile(cross_family_resolution(), view())

    graph = graph_compiler().compile(compilation)

    assert [item.capability for item in graph.tasks] == [
        Capability.RDB_LOOKUP,
        Capability.COMPARISON,
        Capability.FINANCIAL_CALCULATION,
        Capability.RANKING,
    ]
    assert graph.critical_path == tuple(item.task_id for item in graph.tasks)
    scopes = {
        decode_contract_value(item.value)
        for item in graph.tasks[0].literal_inputs
        if item.name.startswith("family:")
    }
    assert scopes == {"family:domestic_etf", "family:overseas_etf"}


def test_graph_preserves_distinct_metric_and_comparison_basis_roles() -> None:
    """Catches two semantic slots being collapsed into one metric tuple."""
    source = resolution()
    compare_frame = frame(
        "frame-1",
        0,
        metric_id="aum",
        limit_id="literal-limit-5",
        action=IntentType.COMPARE,
        assignments=(
            slot("slot-metric", SlotKind.METRIC, ("aum",)),
            slot(
                "slot-basis",
                SlotKind.COMPARISON_BASIS,
                ("product_risk_grade",),
            ),
        ),
    )
    resolved = source.model_copy(update={"canonical_frames": (compare_frame,)})
    compilation = planning_compiler().compile(resolved, view())

    graph = graph_compiler().compile(compilation)

    compare_task = graph.tasks[-1]
    semantic_inputs = {
        item.name: decode_contract_value(item.value)
        for item in compare_task.literal_inputs
        if item.name in {"metric", "comparison_basis"}
    }
    assert semantic_inputs == {
        "metric": "aum",
        "comparison_basis": "product_risk_grade",
    }
