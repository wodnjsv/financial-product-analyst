from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from financial_agent.contracts.enums import (
    Capability,
    InitialAnswerability,
    IntentType,
    ProductFamily,
    ResultShape,
    SubtaskImportance,
)
from financial_agent.contracts.query import OperationSpec, QueryPlan, Subtask
from financial_agent.planning.contracts import (
    CompilationIssue,
    CompilationRoute,
    CompilerManifest,
    LoweringRecord,
    QueryPlanCompilation,
)


NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)
HASH = "a" * 64


def query_plan() -> QueryPlan:
    return QueryPlan(
        request_key=HASH,
        run_id="run-1",
        dataset_version="dataset-v1",
        producer="query-plan-compiler",
        created_at=NOW,
        intent_types=(IntentType.LOOKUP,),
        product_families=(ProductFamily.DOMESTIC_ETF,),
        subtasks=(
            Subtask(
                subtask_id="frame-1",
                intent_type=IntentType.LOOKUP,
                importance=SubtaskImportance.CRITICAL,
                operation_ids=("operation:frame-1:lookup-products",),
            ),
        ),
        operations=(
            OperationSpec(
                subtask_id="frame-1",
                operation_id="operation:frame-1:lookup-products",
            ),
        ),
        result_shape=ResultShape.PRODUCT_LIST,
        requested_capabilities=(Capability.RDB_LOOKUP,),
        initial_answerability=InitialAnswerability.SUPPORTED,
    )


def manifest() -> CompilerManifest:
    return CompilerManifest(
        registry_version="query-plan-registry.v1",
        registry_hash="b" * 64,
        compiler_version="query-plan-compiler.v1",
    )


def compilation_payload(route: CompilationRoute) -> dict[str, object]:
    return {
        "request_key": HASH,
        "run_id": "run-1",
        "dataset_version": "dataset-v1",
        "producer": "query-plan-compiler",
        "created_at": NOW,
        "compilation_id": "compilation-1",
        "resolution_id": "resolution-1",
        "route": route,
        "query_plan": None if route is CompilationRoute.ABSTAIN else query_plan(),
        "matched_archetype_id": None,
        "primitive_ids": (),
        "applied_default_ids": (),
        "lowering_records": (),
        "blocking_issues": (
            CompilationIssue(code="POLICY_BLOCKED", related_ids=("frame-1",)),
        )
        if route is CompilationRoute.ABSTAIN
        else (),
        "resolver_view_hash": "c" * 64,
        "compiler_manifest": manifest(),
    }


def test_executable_route_requires_query_plan() -> None:
    """Catches a route that Phase 3 cannot execute because its plan vanished."""
    payload = compilation_payload(CompilationRoute.FAST)
    payload["query_plan"] = None

    with pytest.raises(ValidationError, match="executable route requires query plan"):
        QueryPlanCompilation(**payload)


def test_abstain_forbids_query_plan_and_requires_blocking_issue() -> None:
    """Catches accidentally executable work escaping an abstention decision."""
    payload = compilation_payload(CompilationRoute.ABSTAIN)
    payload["query_plan"] = query_plan()

    with pytest.raises(ValidationError, match="abstain cannot carry query plan"):
        QueryPlanCompilation(**payload)

    payload["query_plan"] = None
    payload["blocking_issues"] = ()
    with pytest.raises(ValidationError, match="abstain requires blocking issue"):
        QueryPlanCompilation(**payload)


def test_lowering_source_is_unique_and_query_plan_pins_match() -> None:
    """Catches duplicated provenance and a plan replayed under another dataset."""
    payload = compilation_payload(CompilationRoute.COMPOSE)
    record = LoweringRecord(
        source_id="frame-1",
        target_kind="subtask",
        target_ids=("frame-1",),
    )
    payload["lowering_records"] = (record, record)
    with pytest.raises(ValidationError, match="lowering sources must be unique"):
        QueryPlanCompilation(**payload)

    payload["lowering_records"] = (record,)
    payload["query_plan"] = query_plan().model_copy(
        update={"dataset_version": "dataset-v2"}
    )
    with pytest.raises(ValidationError, match="query plan pins must match compilation"):
        QueryPlanCompilation(**payload)
