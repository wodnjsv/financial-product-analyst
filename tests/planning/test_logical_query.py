from __future__ import annotations

from datetime import UTC, date, datetime
import json

import pytest
from pydantic import ValidationError

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import Capability, IntentType, ProductFamily
from financial_agent.intent.query_contracts import (
    ProjectionSpecV2,
    QueryQualifiersV2,
    QueryResultShape,
    QueryScopeV2,
)
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.logical_query import (
    LogicalDependencyV2,
    LogicalExecutionRoute,
    LogicalLookupOperationV2,
    LogicalPrimitiveStepV2,
    LogicalQueryPlanV2,
    LogicalQueryTaskV2,
    PriorResultInputV2,
    ProducedResultBindingV2,
    SemanticLoweringRecordV2,
    logical_query_plan_id,
)


PIN = "a" * 64


def _task() -> LogicalQueryTaskV2:
    return LogicalQueryTaskV2(
        task_id="logical-task-frame-1",
        frame_id="frame-1",
        candidate_id="query-contract-1",
        contract_hash="b" * 64,
        resolved_contract_id="resolved-query-contract-1",
        contract_variant_id="lookup.projection.v2",
        action_id=IntentType.LOOKUP,
        capability=Capability.RDB_LOOKUP,
        execution_steps=(
            LogicalPrimitiveStepV2(
                primitive_id="lookup-products",
                action_id=IntentType.LOOKUP,
                capability=Capability.RDB_LOOKUP,
                operation_kind="lookup",
                execution_route=LogicalExecutionRoute.SEMANTIC_SQL,
            ),
        ),
        scope=QueryScopeV2(product_family_ids=(ProductFamily.DOMESTIC_ETF,)),
        qualifiers=QueryQualifiersV2(),
        result_shape=QueryResultShape.PRODUCT_LIST,
        operation=LogicalLookupOperationV2(
            projections=ProjectionSpecV2(field_concept_ids=("aum",))
        ),
        binding_ids=("domestic-etf-aum.v1",),
        policy_ids=("identity-unit.v1",),
        evidence_requirements=("metric_definition", "observation_record"),
        prior_result_inputs=(),
        produced_result_bindings=(),
    )


def _plan() -> LogicalQueryPlanV2:
    task = _task()
    kwargs = dict(
        request_key=PIN,
        run_id="run-1",
        dataset_version="dataset-v1",
        cutoff_date=date(2026, 8, 24),
        producer="semantic-query-compiler.v2",
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
        logical_plan_version="2.0",
        query_contract_id="query-contract-bundle-1",
        resolution_id="resolution-1",
        route=CompilationRoute.COMPOSE,
        tasks=(task,),
        dependencies=(),
        applied_policy_ids=("identity-unit.v1",),
        primitive_ids=("lookup-products",),
        binding_registry_version="semantic-sql-bindings.v1",
        binding_registry_hash=PIN,
        physical_policy_registry_version="semantic-sql-policies.v1",
        physical_policy_registry_hash=PIN,
        contract_registry_version="query-contract-registry.v2",
        contract_registry_hash=PIN,
        operator_registry_version="query-operator-registry.v2",
        operator_registry_hash=PIN,
        semantic_policy_registry_version="query-policy-registry.v2",
        semantic_policy_registry_hash=PIN,
        planning_registry_version="query-plan-registry.v1",
        planning_registry_hash=PIN,
        dataset_pin=PIN,
        lowering_records=(
            SemanticLoweringRecordV2(
                frame_id="frame-1",
                candidate_id="query-contract-1",
                resolved_contract_id="resolved-query-contract-1",
                task_id=task.task_id,
                preserved_semantic_paths=("scope", "projections"),
                binding_ids=("domestic-etf-aum.v1",),
                policy_ids=("identity-unit.v1",),
            ),
        ),
    )
    draft = LogicalQueryPlanV2.model_construct(
        logical_plan_id="pending",
        **kwargs,
    )
    return LogicalQueryPlanV2(
        logical_plan_id=logical_query_plan_id(draft),
        **kwargs,
    )


def test_logical_plan_is_strict_immutable_and_has_no_physical_sql_fields() -> None:
    plan = _plan()

    assert plan.tasks[0].operation.projections.field_concept_ids == ("aum",)
    assert not ({"sql", "table", "column", "formula", "metric_id"} & set(
        LogicalQueryTaskV2.model_fields
    ))
    with pytest.raises(ValidationError):
        LogicalQueryTaskV2.model_validate({**plan.tasks[0].model_dump(), "sql": "SELECT 1"})
    with pytest.raises(ValidationError):
        plan.tasks[0].task_id = "changed"  # type: ignore[misc]


def test_logical_plan_validates_typed_prior_result_dependency() -> None:
    upstream = _task()
    downstream = upstream.model_copy(
        update={
            "task_id": "logical-task-frame-2",
            "frame_id": "frame-2",
            "candidate_id": "query-contract-2",
            "contract_hash": "c" * 64,
            "resolved_contract_id": "resolved-query-contract-2",
            "scope": QueryScopeV2(prior_result_binding="result-set-1"),
            "prior_result_inputs": (
                PriorResultInputV2(
                    binding_id="result-set-1",
                    producer_task_id=upstream.task_id,
                    cardinality="many",
                ),
            ),
            "produced_result_bindings": (),
        }
    )
    upstream = upstream.model_copy(
        update={
            "produced_result_bindings": (
                ProducedResultBindingV2(
                    binding_id="result-set-1",
                    cardinality="many",
                ),
            )
        }
    )
    payload = json.loads(_plan().model_dump_json())
    payload.update(
        tasks=[
            upstream.model_dump(mode="json"),
            downstream.model_dump(mode="json"),
        ],
        dependencies=[
            LogicalDependencyV2(
                upstream_task_id=upstream.task_id,
                downstream_task_id=downstream.task_id,
                binding_id="result-set-1",
            ).model_dump(mode="json"),
        ],
        lowering_records=[
            payload["lowering_records"][0],
            SemanticLoweringRecordV2(
                frame_id=downstream.frame_id,
                candidate_id=downstream.candidate_id,
                resolved_contract_id=downstream.resolved_contract_id,
                task_id=downstream.task_id,
                preserved_semantic_paths=("scope", "projections"),
                binding_ids=downstream.binding_ids,
                policy_ids=downstream.policy_ids,
            ).model_dump(mode="json"),
        ],
    )
    payload["logical_plan_id"] = "logical-query-plan-" + canonical_sha256(
        {key: value for key, value in payload.items() if key != "logical_plan_id"}
    )

    plan = LogicalQueryPlanV2.model_validate_json(json.dumps(payload))
    assert plan.dependencies[0].binding_id == "result-set-1"

    with pytest.raises(ValidationError, match="LOGICAL_DEPENDENCY_REQUIRED"):
        LogicalQueryPlanV2.model_validate_json(
            json.dumps({**payload, "dependencies": []})
        )


def test_logical_plan_rejects_policy_or_lowering_ownership_drift() -> None:
    payload = _plan().model_dump()

    with pytest.raises(ValidationError, match="APPLIED_POLICY_OWNERSHIP_MISMATCH"):
        LogicalQueryPlanV2.model_validate(
            {**payload, "applied_policy_ids": ("different-policy.v1",)}
        )
    record = payload["lowering_records"][0]
    with pytest.raises(ValidationError, match="LOWERING_RECORD_OWNERSHIP_MISMATCH"):
        LogicalQueryPlanV2.model_validate(
            {
                **payload,
                "lowering_records": (
                    {**record, "binding_ids": ("other-binding.v1",)},
                ),
            }
        )


def test_logical_task_rejects_action_capability_or_result_shape_drift() -> None:
    payload = _task().model_dump()

    with pytest.raises(ValidationError, match="LOGICAL_ACTION_CAPABILITY_MISMATCH"):
        LogicalQueryTaskV2.model_validate(
            {**payload, "capability": Capability.COMPARISON}
        )
    with pytest.raises(ValidationError, match="LOGICAL_ACTION_RESULT_SHAPE_MISMATCH"):
        LogicalQueryTaskV2.model_validate(
            {**payload, "result_shape": QueryResultShape.TOP_K}
        )
