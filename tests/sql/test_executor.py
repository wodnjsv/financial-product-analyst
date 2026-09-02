from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from financial_agent.intent.query_contracts import (
    AggregationFunction,
    AggregationSpecV2,
    ProjectionSpecV2,
    QueryQualifiersV2,
    QueryResultShape,
)
from financial_agent.planning.logical_query import (
    LogicalAggregateOperationV2,
    LogicalLookupOperationV2,
)
from financial_agent.sql.compiler import SemanticSqlCompiler
from financial_agent.sql.executor import ReadOnlySqlRunner, SqlExecutionError

from .helpers import ACTIVE_DATASET, BINDINGS, PLANNING, POLICIES, make_plan
from .test_result_mapping import _lookup_row


COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)


class _Mappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _Mappings(self._rows)


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_):
        return False


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.driver_sql = []
        self.executions = []

    def begin(self):
        return _Context(None)

    async def exec_driver_sql(self, statement):
        self.driver_sql.append(statement)

    async def execute(self, statement, parameters):
        self.executions.append((str(statement), parameters))
        if str(statement).startswith("SELECT set_config"):
            return _Result([])
        return _Result(self.rows)


class FakeEngine:
    def __init__(self, rows):
        self.connection = FakeConnection(rows)
        self.connect_count = 0

    def connect(self):
        self.connect_count += 1
        return _Context(self.connection)


def _plan_and_request():
    plan = make_plan(
        LogicalLookupOperationV2(
            projections=ProjectionSpecV2(field_concept_ids=("aum",))
        )
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    return plan, outcome.request


@pytest.mark.asyncio
async def test_runner_revalidates_then_sets_read_only_timeout_and_executes_once() -> None:
    plan, request = _plan_and_request()
    engine = FakeEngine([_lookup_row(Decimal("0"))])
    runner = ReadOnlySqlRunner(engine, COMPILER, default_timeout_ms=4321)
    before = request.model_dump_json()

    result = await runner.execute(request, plan)

    assert result.result_rows[0].fields[1].value.value == Decimal("0")
    assert engine.connection.driver_sql == ["SET TRANSACTION READ ONLY"]
    assert len(engine.connection.executions) == 2
    assert engine.connection.executions[0][0].startswith("SELECT set_config")
    assert engine.connection.executions[0][1] == {"statement_timeout": "4321ms"}
    assert engine.connection.executions[1][0] == request.statement
    assert request.model_dump_json() == before


@pytest.mark.asyncio
async def test_invalid_plan_or_active_registry_is_rejected_before_database_access() -> None:
    plan, request = _plan_and_request()
    engine = FakeEngine([_lookup_row()])
    runner = ReadOnlySqlRunner(engine, COMPILER)

    with pytest.raises(SqlExecutionError, match="EXECUTION_REQUEST_REJECTED"):
        await runner.execute(request, plan.model_copy(update={"dataset_pin": "f" * 64}))
    assert engine.connect_count == 0

    forged_request = request.model_copy(update={"task_id": "logical-task-forged"})
    with pytest.raises(SqlExecutionError, match="EXECUTION_REQUEST_REJECTED"):
        await runner.execute(forged_request, plan)
    assert engine.connect_count == 0


@pytest.mark.asyncio
async def test_defense_in_depth_rejects_non_select_before_database_access() -> None:
    plan, request = _plan_and_request()
    forged = request.model_copy(update={"statement": "DELETE FROM catalog.product"})
    engine = FakeEngine([])
    runner = ReadOnlySqlRunner(engine, COMPILER)

    with pytest.raises(SqlExecutionError, match="SQL_READ_ONLY_STATEMENT_REQUIRED"):
        await runner.execute(forged, plan)
    assert engine.connect_count == 0


@pytest.mark.asyncio
async def test_runner_does_not_retry_after_database_failure() -> None:
    plan, request = _plan_and_request()

    class FailingConnection(FakeConnection):
        async def execute(self, statement, parameters):
            self.executions.append((str(statement), parameters))
            if str(statement).startswith("SELECT set_config"):
                return _Result([])
            raise RuntimeError("database unavailable")

    engine = FakeEngine([])
    engine.connection = FailingConnection([])
    runner = ReadOnlySqlRunner(engine, COMPILER)
    with pytest.raises(SqlExecutionError, match="SQL_EXECUTION_FAILED"):
        await runner.execute(request, plan)
    assert sum(item[0] == request.statement for item in engine.connection.executions) == 1


@pytest.mark.asyncio
async def test_timeout_is_bounded_before_database_access() -> None:
    plan, request = _plan_and_request()
    engine = FakeEngine([])
    runner = ReadOnlySqlRunner(engine, COMPILER)
    with pytest.raises(SqlExecutionError, match="SQL_TIMEOUT_OUT_OF_RANGE"):
        await runner.execute(request, plan, timeout_ms=55_001)
    assert engine.connect_count == 0


def test_period_is_fail_closed_until_binding_and_lowering_are_registered() -> None:
    plan = make_plan(
        LogicalLookupOperationV2(
            projections=ProjectionSpecV2(field_concept_ids=("aum",))
        ),
        qualifiers=QueryQualifiersV2(
            period_id="one-year", as_of_date=date(2026, 8, 24)
        ),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is None
    assert outcome.rejection.code == "PHYSICAL_QUALIFIER_UNSUPPORTED"


@pytest.mark.parametrize(
    ("function_id", "shape"),
    (
        (AggregationFunction.COUNT_DISTINCT, QueryResultShape.SINGLE_VALUE),
        (AggregationFunction.DISTRIBUTION, QueryResultShape.DISTRIBUTION),
    ),
)
def test_registered_but_unbound_aggregate_variants_fail_closed(
    function_id: AggregationFunction,
    shape: QueryResultShape,
) -> None:
    plan = make_plan(
        LogicalAggregateOperationV2(
            aggregation=AggregationSpecV2(
                function_id=function_id,
                target_field_concept_id="aum",
                population_grain_id="source-product.v1",
                dedup_policy_id="no-dedup.v1",
            )
        ),
        policy_ids=(
            "source-product.v1",
            "no-dedup.v1",
            "identity-unit.v1",
            "exclude_missing.v1",
        ),
        result_shape=shape,
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is None
    assert outcome.rejection.code == "PHYSICAL_AGGREGATE_UNSUPPORTED"
