from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from financial_agent.contracts.enums import Capability, ProductFamily, ResultType
from financial_agent.contracts.execution import NamedValue
from financial_agent.contracts.values import encode_contract_value
from financial_agent.intent.query_contract_solver import QueryContractCandidate
from financial_agent.intent.query_contracts import QueryQualifiersV2
from financial_agent.orchestration.semantic_execution import (
    BindingTypeInput,
    SemanticSqlTaskExecutionInput,
    SemanticToolTaskExecutionInput,
)
from financial_agent.orchestration.semantic_graph import (
    SemanticExecutionGraphCompilation,
    SemanticExecutionGraphCompiler,
    SemanticGraphCompilationError,
)
from financial_agent.planning.logical_query import logical_query_plan_id
from financial_agent.planning.registry import load_planning_registry
from financial_agent.sql.compiler import SemanticSqlCompiler

from tests.planning.test_semantic_compiler import (
    ACTIVE_DATASET_PIN,
    ADAPTER,
    BINDINGS,
    PLANNING,
    POLICIES,
    _assessment,
    _base,
    _compile,
    _semantic_contract,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET_PIN)


def sql_compilation():
    payload = _base("lookup")
    payload["projections"] = {
        "field_concept_ids": ["aum"],
        "default_profile_id": None,
    }
    payload["qualifiers"] = {
        "period_id": None,
        "currency_id": "KRW",
        "unit_id": "KRW",
        "as_of_date": "2026-08-24",
    }
    candidate = QueryContractCandidate(
        candidate_id="candidate-lookup",
        contract=ADAPTER.validate_json(json.dumps(payload)),
    )
    return _compile(
        (candidate,),
        (_assessment(candidate),),
        primitive_ids=("lookup-products",),
    )


def sql_request(compilation=None):
    compilation = compilation or sql_compilation()
    plan = compilation.logical_query_plan
    assert plan is not None
    outcome = SQL_COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    return outcome.request


def tool_compilation():
    candidate = QueryContractCandidate(
        candidate_id="candidate-explain",
        contract=_semantic_contract("explain"),
    )
    return _compile(
        (candidate,),
        (_assessment(candidate),),
        primitive_ids=("lookup-products", "search-documents"),
    )


def tool_dependency_compilation(cardinality="many"):
    from financial_agent.contracts.enums import Cardinality
    from financial_agent.planning.semantic_compiler import PriorResultOwnershipV2

    first_contract = _semantic_contract("explain").model_copy(update={"frame_id": "frame-1"})
    second_contract = _semantic_contract("explain").model_copy(update={"frame_id": "frame-2"})
    second_contract = second_contract.model_copy(
        update={
            "scope": second_contract.scope.model_copy(
                update={"product_family_ids": (), "prior_result_binding": "result-set-1"}
            )
        }
    )
    first = QueryContractCandidate(candidate_id="first", contract=first_contract)
    second = QueryContractCandidate(candidate_id="second", contract=second_contract)
    return _compile(
        (first, second),
        (_assessment(first), _assessment(second)),
        primitive_ids=("lookup-products", "search-documents"),
        prior_result_ownership=(
            PriorResultOwnershipV2(
                binding_id="result-set-1",
                producer_frame_id="frame-1",
                cardinality=Cardinality(cardinality),
            ),
        ),
    )


def sql_dependency_compilation():
    from financial_agent.planning.semantic_compiler import PriorResultOwnershipV2

    def qualified(candidate):
        return QueryContractCandidate(
            candidate_id=candidate.candidate_id,
            contract=candidate.contract.model_copy(
                update={
                    "qualifiers": QueryQualifiersV2(
                        currency_id="KRW",
                        unit_id="KRW",
                        as_of_date=date(2026, 8, 24),
                    )
                }
            ),
        )

    from tests.planning.test_semantic_compiler import _rank

    first = qualified(_rank("frame-1"))
    second = _rank("frame-2", "result-set-1")
    second = QueryContractCandidate(
        candidate_id=second.candidate_id,
        contract=second.contract.model_copy(
            update={
                "scope": second.contract.scope.model_copy(
                    update={"product_family_ids": (ProductFamily.DOMESTIC_ETF,)}
                )
            }
        ),
    )
    second = qualified(second)
    return _compile(
        (first, second),
        (_assessment(first), _assessment(second)),
        prior_result_ownership=(
            PriorResultOwnershipV2(
                binding_id="result-set-1",
                producer_frame_id="frame-1",
                cardinality="many",
            ),
        ),
    )


def test_semantic_graph_compiles_registered_sql_without_executing_it() -> None:
    compilation = sql_compilation()
    request = sql_request(compilation)
    provider_calls = []

    def provider(plan, task):
        provider_calls.append((plan.logical_plan_id, task.task_id))
        return request

    result = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=provider,
    ).compile(compilation)

    plan = compilation.logical_query_plan
    assert plan is not None
    assert provider_calls == [(plan.logical_plan_id, plan.tasks[0].task_id)]
    assert result.graph.tasks[0].capability is Capability.RDB_LOOKUP
    assert result.graph.tasks[0].operation_id == plan.tasks[0].task_id
    assert result.compiled_request_for(result.graph.tasks[0].task_id) == request
    assert result.graph.tasks[0].budget_ms == 3_000


def test_semantic_graph_builds_tool_task_without_requesting_sql() -> None:
    compilation = tool_compilation()

    def forbidden_provider(*_):
        raise AssertionError("semantic tool graph must not request SQL")

    result = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=forbidden_provider,
    ).compile(compilation)

    task = result.graph.tasks[0]
    assert task.capability is Capability.KEYWORD_SEARCH
    assert task.budget_ms == 7_000
    assert result.compiled_requests == ()


def test_semantic_graph_rejects_foreign_compiled_request() -> None:
    compilation = sql_compilation()
    request = sql_request(compilation).model_copy(update={"task_id": "foreign-task"})

    with pytest.raises(SemanticGraphCompilationError, match="COMPILED_SQL"):
        SemanticExecutionGraphCompiler(
            load_planning_registry(PROJECT_ROOT),
            compiled_request_provider=lambda *_: request,
        ).compile(compilation)


def test_semantic_graph_rejects_tampered_active_registry_pin() -> None:
    compilation = sql_compilation()
    assert compilation.logical_query_plan is not None
    tampered = compilation.model_copy(
        update={
            "logical_query_plan": compilation.logical_query_plan.model_copy(
                update={"planning_registry_hash": "f" * 64}
            )
        }
    )
    with pytest.raises(
        SemanticGraphCompilationError,
        match="REVALIDATION|PLANNING_REGISTRY_PIN_MISMATCH",
    ):
        SemanticExecutionGraphCompiler(
            load_planning_registry(PROJECT_ROOT),
            compiled_request_provider=lambda *_: sql_request(compilation),
        ).compile(tampered)


def test_semantic_graph_bundle_rejects_request_against_foreign_plan_instance() -> None:
    compilation = sql_compilation()
    request = sql_request(compilation)
    graph_result = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: request,
    ).compile(compilation)
    foreign_draft = graph_result.logical_query_plan.model_copy(
        update={"producer": "foreign-semantic-compiler"}
    )
    foreign_plan = foreign_draft.model_copy(
        update={"logical_plan_id": logical_query_plan_id(foreign_draft)}
    )

    with pytest.raises(
        ValueError,
        match="SEMANTIC_(?:GRAPH_DERIVATION|COMPILED_REQUEST_OWNERSHIP)_MISMATCH",
    ):
        SemanticExecutionGraphCompilation(
            graph=graph_result.graph,
            logical_query_plan=foreign_plan,
            compiled_requests=graph_result.compiled_requests,
        )


@pytest.mark.parametrize(
    ("graph_update", "task_update"),
    (
        ({"run_id": "foreign-run"}, {}),
        ({"producer": "foreign-compiler"}, {}),
        ({"critical_path": ()}, {}),
        ({}, {"task_id": "semantic-execution:foreign"}),
        ({}, {"capability": Capability.KEYWORD_SEARCH}),
        ({}, {"depends_on": ("semantic-execution:foreign",)}),
        ({}, {"expected_output_type": ResultType.SCALAR}),
        ({}, {"budget_ms": 1}),
        (
            {},
            {
                "literal_inputs": (
                    NamedValue(
                        name="forged",
                        value=encode_contract_value("forged"),
                    ),
                )
            },
        ),
    ),
)
def test_semantic_graph_bundle_rejects_graph_not_derived_from_plan(
    graph_update, task_update
) -> None:
    compilation = sql_compilation()
    request = sql_request(compilation)
    bundle = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: request,
    ).compile(compilation)
    task = bundle.graph.tasks[0].model_copy(update=task_update)
    graph = bundle.graph.model_copy(update={**graph_update, "tasks": (task,)})

    with pytest.raises(ValueError):
        SemanticExecutionGraphCompilation(
            graph=graph,
            logical_query_plan=bundle.logical_query_plan,
            compiled_requests=bundle.compiled_requests,
        )


def test_semantic_sql_execution_input_revalidates_task_plan_and_request() -> None:
    compilation = sql_compilation()
    request = sql_request(compilation)
    graph_result = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: request,
    ).compile(compilation)
    plan = compilation.logical_query_plan
    assert plan is not None
    graph_task = graph_result.graph.tasks[0]

    valid = SemanticSqlTaskExecutionInput(
        request_key=graph_result.graph.request_key,
        run_id=graph_result.graph.run_id,
        dataset_version=graph_result.graph.dataset_version,
        cutoff_date=graph_result.graph.cutoff_date,
        created_at=graph_result.graph.created_at,
        task=graph_task,
        logical_query_plan=plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(),
        compiled_request=request,
    )
    assert valid.request_kind == "semantic_sql"

    tampered = valid.model_dump()
    tampered["task"]["operation_id"] = "foreign-logical-task"
    with pytest.raises(ValueError, match="SEMANTIC_EXECUTION_TASK_OWNERSHIP_MISMATCH"):
        SemanticSqlTaskExecutionInput.model_validate(tampered)


def test_semantic_tool_input_forbids_rdb_and_requires_exact_logical_task() -> None:
    compilation = tool_compilation()
    graph_result = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: None,
    ).compile(compilation)
    plan = compilation.logical_query_plan
    assert plan is not None
    task = graph_result.graph.tasks[0]

    valid = SemanticToolTaskExecutionInput(
        request_key=graph_result.graph.request_key,
        run_id=graph_result.graph.run_id,
        dataset_version=graph_result.graph.dataset_version,
        cutoff_date=graph_result.graph.cutoff_date,
        created_at=graph_result.graph.created_at,
        task=task,
        logical_query_plan=plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(),
    )
    assert valid.request_kind == "semantic_tool"

    rdb_task = task.model_copy(update={"capability": Capability.RDB_LOOKUP})
    with pytest.raises(
        ValueError,
        match="SEMANTIC_(?:TOOL_RDB_FORBIDDEN|EXECUTION_TASK_OWNERSHIP_MISMATCH)",
    ):
        SemanticToolTaskExecutionInput.model_validate(
            {**valid.model_dump(), "task": rdb_task.model_dump()}
        )


def test_semantic_dependency_input_checks_result_and_binding_origin() -> None:
    # The exact producer/consumer validation is exercised by constructing the
    # smallest valid tool dependency graph through the V2 planning compiler.
    from financial_agent.contracts.enums import ToolStatus
    from financial_agent.contracts.execution import BindingValue
    from financial_agent.contracts.values import encode_contract_value
    from financial_agent.orchestration.executors import build_tool_result

    compilation = tool_dependency_compilation()
    graph_result = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: None,
    ).compile(compilation)
    graph = graph_result.graph
    producer, consumer = graph.tasks
    plan = compilation.logical_query_plan
    assert plan is not None
    binding_type = BindingTypeInput(
        binding_name="result-set-1", value_type="semantic-result:many"
    )
    producer_request = SemanticToolTaskExecutionInput(
        request_key=graph.request_key,
        run_id=graph.run_id,
        dataset_version=graph.dataset_version,
        cutoff_date=graph.cutoff_date,
        created_at=graph.created_at,
        task=producer,
        logical_query_plan=plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(binding_type,),
    )
    produced = BindingValue(
        binding_name="result-set-1",
        value_type="semantic-result:many",
        value=encode_contract_value(("product-1",)),
    )
    producer_result = build_tool_result(
        producer_request,
        status=ToolStatus.SUCCESS,
        binding_values=(produced,),
        latency_ms=1,
    )
    valid = SemanticToolTaskExecutionInput(
        request_key=graph.request_key,
        run_id=graph.run_id,
        dataset_version=graph.dataset_version,
        cutoff_date=graph.cutoff_date,
        created_at=graph.created_at,
        task=consumer,
        logical_query_plan=plan,
        dependency_results=(producer_result,),
        binding_values=(produced,),
        binding_types=(binding_type,),
    )
    assert valid.binding_values == (produced,)

    foreign = produced.model_copy(update={"value": encode_contract_value(("product-2",))})
    with pytest.raises(ValueError, match="SEMANTIC_BINDING_ORIGIN_MISMATCH"):
        SemanticToolTaskExecutionInput.model_validate(
            {**valid.model_dump(), "binding_values": (foreign.model_dump(),)}
        )

    unexpected = BindingValue(
        binding_name="unexpected-binding",
        value_type="semantic-result:many",
        value=encode_contract_value(("product-1",)),
    )
    producer_with_extra = build_tool_result(
        producer_request,
        status=ToolStatus.SUCCESS,
        binding_values=(produced, unexpected),
        latency_ms=1,
    )
    with pytest.raises(ValueError, match="SEMANTIC_DEPENDENCY_BINDING_MISMATCH"):
        SemanticToolTaskExecutionInput(
            request_key=graph.request_key,
            run_id=graph.run_id,
            dataset_version=graph.dataset_version,
            cutoff_date=graph.cutoff_date,
            created_at=graph.created_at,
            task=consumer,
            logical_query_plan=plan,
            dependency_results=(producer_with_extra,),
            binding_values=(produced,),
            binding_types=(binding_type,),
        )
