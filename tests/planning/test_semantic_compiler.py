from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from financial_agent.contracts.canonical import canonical_json_bytes, canonical_sha256
from financial_agent.contracts.enums import Capability, IntentType, ProductFamily
from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.intent.query_contract_solver import QueryContractCandidate
from financial_agent.intent.query_contracts import (
    AxisReadiness,
    AxisReadinessRecordV2,
    ContractReadiness,
    ContractReadinessRecordV2,
    PlanReadiness,
    QueryQualifiersV2,
    SolvedQueryContractCandidateV2,
)
from financial_agent.intent.view import ActiveDatasetPin
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.logical_query import (
    LogicalExecutionRoute,
    LogicalPrimitiveStepV2,
    LogicalQueryTaskV2,
    logical_resolved_contract_reference_id,
    logical_task_id,
)
from financial_agent.planning.physical_bindings import (
    load_physical_binding_registry,
    load_semantic_sql_policy_registry,
)
from financial_agent.planning.readiness import PlanReadinessResult, assess_plan_readiness
from financial_agent.planning.registry import load_planning_registry
from financial_agent.planning.primitive_contracts import required_primitive_roles
from financial_agent.planning.semantic_compiler import (
    PriorResultOwnershipV2,
    SemanticPlanningCompiler,
    SemanticReadinessAssessmentV2,
    lower_semantic_operation,
    reverse_semantic_loss_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PIN = "d" * 64
REQUEST_KEY = "e" * 64
ADAPTER = TypeAdapter(SolvedQueryContractCandidateV2)
SEMANTIC = load_query_contract_registry(PROJECT_ROOT)
BINDINGS = load_physical_binding_registry(PROJECT_ROOT)
POLICIES = load_semantic_sql_policy_registry(PROJECT_ROOT)
PLANNING = load_planning_registry(PROJECT_ROOT)
ACTIVE_DATASET_PIN = ActiveDatasetPin(
    dataset_version="dataset-v1",
    manifest_hash=DATASET_PIN,
)


def _base(action: str, frame_id: str = "frame-1", family: str = "domestic_etf"):
    return {
        "contract_schema_version": "2.0",
        "contract_variant_id": {
            "lookup": "lookup.projection.v2",
            "screen": "screen.predicate.v2",
            "rank": "rank.ordering.v2",
            "compare": "compare.subjects.v2",
            "aggregate": "aggregate.scalar.v2",
            "calculate": "calculate.recipe.v2",
            "similar": "similar.policy.v2",
            "explain": "explain.topic.v2",
        }[action],
        "frame_id": frame_id,
        "action_id": action,
        "scope": {"product_family_ids": [family], "entity_refs": [], "prior_result_binding": None},
        "qualifiers": {"period_id": None, "currency_id": None, "unit_id": None, "as_of_date": None},
        "result_shape": {
            "lookup": "product_list", "screen": "product_list", "rank": "top_k",
            "compare": "comparison_table", "aggregate": "single_value",
            "calculate": "single_value", "similar": "product_list", "explain": "explanation",
        }[action],
        "provenance": [
            {
                "semantic_input_id": "scope",
                "source_kind": "exact_lock",
                "source_ref": "span-1",
            }
        ],
        "registry_pins": {
            "contract_registry_version": SEMANTIC.contract_registry_version,
            "contract_registry_hash": SEMANTIC.contract_registry_hash,
            "operator_registry_version": SEMANTIC.operator_registry_version,
            "operator_registry_hash": SEMANTIC.operator_registry_hash,
            "policy_registry_version": SEMANTIC.policy_registry_version,
            "policy_registry_hash": SEMANTIC.policy_registry_hash,
        },
    }


def _rank(frame_id: str = "frame-1", prior: str | None = None) -> QueryContractCandidate:
    payload = _base("rank", frame_id)
    payload["scope"] = (
        {"product_family_ids": [], "entity_refs": [], "prior_result_binding": prior}
        if prior else payload["scope"]
    )
    payload.update(
        ordering=[{
            "field_concept_id": "aum", "direction": "desc", "direction_policy_id": None,
            "nulls_policy_id": "exclude_missing.v1", "tie_break_policy_id": "stable-product-id.v1",
        }],
        limit=5 if not prior else 1,
        limit_policy_id=None,
        predicate=None,
    )
    contract = ADAPTER.validate_json(json.dumps(payload))
    return QueryContractCandidate(
        candidate_id=f"candidate-{frame_id}", contract=contract
    )


def _semantic_contract(action: str):
    payload = _base(action, frame_id=f"frame-{action}")
    if action == "lookup":
        payload["projections"] = {
            "field_concept_ids": ["aum", "managedBy"],
            "default_profile_id": None,
        }
    elif action == "screen":
        payload["qualifiers"]["unit_id"] = "percent"
        payload["predicate"] = {
            "node_type": "not",
            "child": {
                "node_type": "atom",
                "field_concept_id": "fee_rate",
                "operator_id": "between",
                "value": None,
                "values": [
                    {"kind": "decimal", "decimal": "1", "unit_id": "percent"},
                    {"kind": "decimal", "decimal": "2", "unit_id": "percent"},
                ],
                "null_policy_id": "exclude_missing.v1",
            },
        }
    elif action == "rank":
        payload["qualifiers"] = {
            "period_id": "P1Y",
            "currency_id": "KRW",
            "unit_id": "KRW",
            "as_of_date": "2026-08-24",
        }
        payload.update(
            ordering=[{
                "field_concept_id": "aum", "direction": None,
                "direction_policy_id": "default-direction-descending.v1",
                "nulls_policy_id": "exclude_missing.v1",
                "tie_break_policy_id": "stable-product-id.v1",
            }],
            limit=None,
            limit_policy_id="default-limit-5.v1",
            predicate=None,
        )
    elif action == "compare":
        payload["comparison"] = {
            "subject_refs": ["product-a", "product-b"],
            "group_basis_id": None,
            "metric_concept_ids": ["aum", "fee_rate"],
            "projection_profile_id": None,
            "basis_policy_id": "same-definition-period-unit.v1",
            "normalization_policy_id": "approved-cross-family.v1",
        }
    elif action == "aggregate":
        payload["contract_variant_id"] = "aggregate.grouped.v2"
        payload["result_shape"] = "grouped_table"
        payload["aggregation"] = {
            "function_id": "sum",
            "target_field_concept_id": "aum",
            "count_population_id": None,
            "group_by_field_concept_ids": ["risk_grade"],
            "bucket_policy_id": None,
            "population_grain_id": "source-product.v1",
            "dedup_policy_id": "no-dedup.v1",
        }
        payload["predicate"] = None
    elif action == "calculate":
        payload["calculation"] = {
            "recipe_id": "simple-interest.v1",
            "operands": [
                {"role_id": "principal", "value_ref": None, "field_concept_id": "aum"},
                {"role_id": "rate", "value_ref": "literal-rate", "field_concept_id": None},
            ],
        }
    elif action == "similar":
        payload["similarity"] = {
            "anchor_ref": "product-a",
            "policy_id": "cosine-complete-dimensions.v1",
            "dimension_concept_ids": ["aum", "fee_rate"],
            "default_profile_id": None,
            "coverage_threshold": "0.8",
            "limit": 7,
        }
    elif action == "explain":
        payload["explanation"] = {
            "topic_concept_id": None,
            "profile_id": "default-explanation-profile.v1",
        }
    return ADAPTER.validate_json(json.dumps(payload))


def _assessment(candidate: QueryContractCandidate, *, readiness=PlanReadiness.EXECUTABLE):
    assessed = assess_plan_readiness(
        candidate.contract,
        BINDINGS,
        POLICIES,
        active_dataset_pin=ACTIVE_DATASET_PIN,
    )
    plan = assessed.model_copy(
        update={
            "readiness": readiness,
            "reason_codes": (
                ()
                if readiness is PlanReadiness.EXECUTABLE
                else ("TEST_LIMITATION",)
            ),
        }
    )
    return SemanticReadinessAssessmentV2(
        frame_id=candidate.contract.frame_id,
        candidate_id=candidate.candidate_id,
        contract_hash=canonical_sha256(candidate.contract),
        semantic_registry_pins=candidate.contract.registry_pins,
        binding_registry_version=BINDINGS.registry_version,
        binding_registry_hash=BINDINGS.registry_hash,
        physical_policy_registry_version=POLICIES.registry_version,
        physical_policy_registry_hash=POLICIES.registry_hash,
        planning_registry_version=PLANNING.registry_version,
        planning_registry_hash=PLANNING.registry_hash,
        axis=AxisReadinessRecordV2(readiness=AxisReadiness.COMPLETE, reason_codes=()),
        contract=ContractReadinessRecordV2(readiness=ContractReadiness.COMPLETE, reason_codes=()),
        plan=plan,
    )


def _actual_assessments(candidates, *, prior_result_ownership=(), facts=None):
    complete_axis = tuple(
        AxisReadinessRecordV2(readiness=AxisReadiness.COMPLETE, reason_codes=())
        for _ in candidates
    )
    complete_contract = tuple(
        ContractReadinessRecordV2(
            readiness=ContractReadiness.COMPLETE,
            reason_codes=(),
        )
        for _ in candidates
    )
    return SemanticPlanningCompiler(
        BINDINGS, POLICIES, PLANNING
    ).assess_in_dependency_order(
        selected_candidates=tuple(candidates),
        axis_readiness=complete_axis,
        contract_readiness=complete_contract,
        active_dataset_pin=ACTIVE_DATASET_PIN,
        prior_result_ownership=tuple(prior_result_ownership),
        facts=facts,
    )


def _compile(candidates, assessments, **kwargs):
    primitive_ids = kwargs.pop(
        "primitive_ids", ("lookup-products", "rank-products")
    )
    return SemanticPlanningCompiler(BINDINGS, POLICIES, PLANNING).compile(
        request_key=REQUEST_KEY,
        run_id="run-1",
        dataset_version="dataset-v1",
        dataset_pin=DATASET_PIN,
        cutoff_date=date(2026, 8, 24),
        producer="semantic-query-compiler.v2",
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
        resolution_id="resolution-1",
        selected_candidates=tuple(candidates),
        readiness_assessments=tuple(assessments),
        primitive_ids=primitive_ids,
        **kwargs,
    )


def test_compile_is_deterministic_lossless_and_independent_of_global_promotion() -> None:
    candidate = _rank()
    assessment = _assessment(candidate)

    first = _compile((candidate,), (assessment,))
    second = _compile((candidate,), (assessment,))

    assert first.route is CompilationRoute.COMPOSE
    assert first.logical_query_plan is not None
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert type(first).model_validate_json(first.model_dump_json()) == first
    assert reverse_semantic_loss_report(
        candidate.contract, first.logical_query_plan.tasks[0]
    ) == ()
    assert first.logical_query_plan.tasks[0].operation.ordering[0].field_concept_id == "aum"
    assert first.logical_query_plan.tasks[0].operation.limit == 5

    payload = first.model_dump()
    assessment_payload = payload["readiness_assessments"][0]
    assessment_payload["plan"]["readiness"] = PlanReadiness.LIMITED
    assessment_payload["plan"]["reason_codes"] = ("FORGED_LIMITATION",)
    resolved_payload = payload["resolved_query_contracts"]["contracts"][0]
    resolved_payload["plan_readiness"]["readiness"] = PlanReadiness.LIMITED
    resolved_payload["plan_readiness"]["reason_codes"] = ("FORGED_LIMITATION",)
    with pytest.raises(ValueError, match="EXECUTABLE_READINESS_MISMATCH"):
        type(first).model_validate(payload)

    lossy_payload = json.loads(first.model_dump_json())
    lossy_payload["logical_query_plan"]["tasks"][0]["operation"]["limit"] = 6
    logical_payload = lossy_payload["logical_query_plan"]
    logical_payload["logical_plan_id"] = "logical-query-plan-" + canonical_sha256(
        {
            key: value
            for key, value in logical_payload.items()
            if key != "logical_plan_id"
        }
    )
    with pytest.raises(
        ValueError,
        match="LOGICAL_RESOLVED_CONTRACT_ID_MISMATCH|LOSSY_COMPILATION_ARTIFACT",
    ):
        type(first).model_validate_json(json.dumps(lossy_payload))


def test_compose_requires_registered_action_compatible_primitives() -> None:
    candidate = _rank()
    assessment = _assessment(candidate)

    with pytest.raises(ValueError, match="EXECUTION_PRIMITIVE_NOT_REGISTERED"):
        _compile((candidate,), (assessment,), primitive_ids=("invented-sql.v1",))
    with pytest.raises(ValueError, match="EXECUTION_PRIMITIVE_ACTION_MISMATCH"):
        _compile((candidate,), (assessment,), primitive_ids=("screen-products",))
    with pytest.raises(ValueError, match="EXECUTION_PRIMITIVE_BUNDLE_MISMATCH"):
        _compile((candidate,), (assessment,), primitive_ids=("rank-products",))
    with pytest.raises(ValueError, match="EXECUTION_PRIMITIVE_BUNDLE_MISMATCH"):
        _compile((candidate,), (assessment,), primitive_ids=("explore-catalog",))


def test_cross_family_rank_requires_comparison_and_normalization_roles() -> None:
    original = _rank()
    contract = original.contract.model_copy(
        update={
            "scope": original.contract.scope.model_copy(
                update={
                    "product_family_ids": (
                        ProductFamily.DOMESTIC_ETF,
                        ProductFamily.OVERSEAS_ETF,
                    )
                }
            )
        }
    )
    candidate = original.model_copy(update={"contract": contract})
    assessment = _assessment(candidate)

    with pytest.raises(ValueError, match="EXECUTION_PRIMITIVE_BUNDLE_MISMATCH"):
        _compile((candidate,), (assessment,))

    compilation = _compile(
        (candidate,),
        (assessment,),
        primitive_ids=(
            "lookup-products",
            "check-comparability",
            "normalize-values",
            "rank-products",
        ),
    )
    assert compilation.logical_query_plan is not None
    assert tuple(
        step.operation_kind
        for step in compilation.logical_query_plan.tasks[0].execution_steps
    ) == ("lookup", "check_comparability", "normalize_values", "rank")


def test_relation_and_explanation_roles_keep_graph_and_search_routes() -> None:
    lookup_contract = _semantic_contract("lookup")
    lookup_candidate = QueryContractCandidate(
        candidate_id="candidate-lookup",
        contract=lookup_contract,
    )
    lookup_compilation = _compile(
        (lookup_candidate,),
        (_assessment(lookup_candidate),),
        primitive_ids=("lookup-products", "traverse-relations"),
    )
    assert lookup_compilation.logical_query_plan is not None
    assert lookup_compilation.logical_query_plan.tasks[0].execution_steps[-1].execution_route is (
        LogicalExecutionRoute.GRAPH
    )

    explain_contract = _semantic_contract("explain")
    explain_candidate = QueryContractCandidate(
        candidate_id="candidate-explain",
        contract=explain_contract,
    )
    explain_compilation = _compile(
        (explain_candidate,),
        (_assessment(explain_candidate),),
        primitive_ids=("lookup-products", "search-documents"),
    )
    assert explain_compilation.logical_query_plan is not None
    assert explain_compilation.logical_query_plan.tasks[0].execution_steps[-1].execution_route is (
        LogicalExecutionRoute.SEARCH
    )


def test_fast_requires_an_exact_registered_archetype_and_its_primitive_set() -> None:
    candidate = _rank()
    assessment = _assessment(candidate)
    compilation = _compile(
        (candidate,),
        (assessment,),
        primitive_ids=("lookup-products", "rank-products"),
        matched_archetype_id="rank.single-family.v1",
    )

    assert compilation.route is CompilationRoute.FAST
    assert compilation.logical_query_plan is not None
    assert compilation.logical_query_plan.planning_registry_hash == PLANNING.registry_hash

    with pytest.raises(
        ValueError,
        match="EXECUTION_PRIMITIVE_BUNDLE_MISMATCH|ARCHETYPE_PRIMITIVE_MISMATCH",
    ):
        _compile(
            (candidate,),
            (assessment,),
            primitive_ids=("rank-products",),
            matched_archetype_id="rank.single-family.v1",
        )


def test_semantic_candidate_id_may_repeat_across_distinct_frames() -> None:
    first = _rank("frame-1")
    second_original = _rank("frame-2")
    second = second_original.model_copy(update={"candidate_id": first.candidate_id})

    compilation = _compile(
        (first, second),
        (_assessment(first), _assessment(second)),
    )

    plan = compilation.logical_query_plan
    assert plan is not None
    assert len(plan.tasks) == 2
    assert plan.tasks[0].candidate_id == plan.tasks[1].candidate_id
    assert plan.tasks[0].task_id != plan.tasks[1].task_id
    assert plan.tasks[0].resolved_contract_id != plan.tasks[1].resolved_contract_id

    duplicate_frame = second.model_copy(
        update={"contract": second.contract.model_copy(update={"frame_id": "frame-1"})}
    )
    with pytest.raises(ValueError, match="DUPLICATE_SELECTED_FRAME"):
        _compile(
            (first, duplicate_frame),
            (_assessment(first), _assessment(duplicate_frame)),
        )


def test_restoration_recomputes_bundle_plan_and_compilation_identities() -> None:
    candidate = _rank()
    compilation = _compile((candidate,), (_assessment(candidate),))

    compilation_payload = compilation.model_dump()
    compilation_payload["compilation_id"] = "forged-compilation-id"
    with pytest.raises(ValueError, match="COMPILATION_ID_MISMATCH"):
        type(compilation).model_validate(compilation_payload)

    plan_payload = compilation.logical_query_plan.model_dump()
    plan_payload["producer"] = "forged-producer"
    with pytest.raises(ValueError, match="LOGICAL_PLAN_ID_MISMATCH"):
        type(compilation.logical_query_plan).model_validate(plan_payload)

    bundle_payload = compilation.model_dump()
    bundle_payload["logical_query_plan"]["query_contract_id"] = "forged-bundle-id"
    with pytest.raises(
        ValueError,
        match="QUERY_CONTRACT_BUNDLE_ID_MISMATCH|LOGICAL_PLAN_ID_MISMATCH",
    ):
        type(compilation).model_validate(bundle_payload)

    disposition_payload = compilation.model_dump()
    disposition_payload["recommended_answer_disposition"] = "limitation"
    with pytest.raises(ValueError, match="SEMANTIC_ROUTE_DECISION_MISMATCH"):
        type(compilation).model_validate(disposition_payload)


def test_restoration_rejects_semantic_and_physical_provenance_relabelling() -> None:
    candidate = _rank()
    compilation = _compile((candidate,), (_assessment(candidate),))

    semantic_payload = compilation.model_dump()
    semantic_payload["readiness_assessments"][0]["semantic_registry_pins"][
        "contract_registry_hash"
    ] = "f" * 64
    with pytest.raises(ValueError, match="COMPILATION_READINESS_OWNERSHIP_MISMATCH"):
        type(compilation).model_validate(semantic_payload)

    physical_payload = compilation.model_dump()
    physical_payload["readiness_assessments"][0]["plan"][
        "binding_registry_hash"
    ] = "f" * 64
    with pytest.raises(ValueError, match="COMPILATION_READINESS_OWNERSHIP_MISMATCH"):
        type(compilation).model_validate(physical_payload)

    dataset_payload = compilation.model_dump()
    dataset_payload["readiness_assessments"][0]["plan"]["dataset_pin"] = "f" * 64
    with pytest.raises(ValueError, match="LOGICAL_PLAN_COMPILATION_PIN_MISMATCH"):
        type(compilation).model_validate(dataset_payload)


def test_restoration_rejects_forged_execution_step_role() -> None:
    candidate = _rank()
    compilation = _compile((candidate,), (_assessment(candidate),))
    payload = json.loads(compilation.model_dump_json())
    logical_payload = payload["logical_query_plan"]
    logical_payload["tasks"][0]["execution_steps"][1]["operation_kind"] = "lookup"
    logical_payload["logical_plan_id"] = "logical-query-plan-" + canonical_sha256(
        {
            key: value
            for key, value in logical_payload.items()
            if key != "logical_plan_id"
        }
    )

    with pytest.raises(
        ValueError,
        match="LOGICAL_PRIMITIVE_CONTRACT_MISMATCH|LOSSY_COMPILATION_ARTIFACT",
    ):
        type(compilation).model_validate_json(json.dumps(payload))


def test_abstain_with_no_primitive_has_no_executable_plan() -> None:
    candidate = _rank()
    assessment = _assessment(candidate).model_copy(
        update={
            "axis": AxisReadinessRecordV2(
                readiness=AxisReadiness.AMBIGUOUS,
                reason_codes=("AXIS_AMBIGUOUS",),
            )
        }
    )

    compilation = _compile(
        (candidate,),
        (assessment,),
        primitive_ids=(),
    )

    assert compilation.route is CompilationRoute.ABSTAIN
    assert compilation.primitive_ids == ()
    assert compilation.logical_query_plan is None


@pytest.mark.parametrize("route_kind", ["explore", "abstain"])
@pytest.mark.parametrize(
    "pin_kind",
    ["semantic", "binding", "policy", "planning", "dataset"],
)
def test_non_executable_compilation_rejects_cross_frame_pin_drift(
    route_kind,
    pin_kind,
) -> None:
    first = _rank("frame-1")
    second = _rank("frame-2")
    assessments = (
        _assessment(first, readiness=PlanReadiness.LIMITED),
        _assessment(second, readiness=PlanReadiness.LIMITED),
    )
    primitive_ids = ("lookup-products", "rank-products")
    if route_kind == "abstain":
        assessments = tuple(
            item.model_copy(
                update={
                    "axis": AxisReadinessRecordV2(
                        readiness=AxisReadiness.AMBIGUOUS,
                        reason_codes=("AXIS_AMBIGUOUS",),
                    )
                }
            )
            for item in assessments
        )
        primitive_ids = ()
    compilation = _compile(
        (first, second),
        assessments,
        primitive_ids=primitive_ids,
    )
    assert compilation.logical_query_plan is None

    payload = json.loads(compilation.model_dump_json())
    second_assessment = payload["readiness_assessments"][1]
    if pin_kind == "semantic":
        resolved = payload["resolved_query_contracts"]["contracts"][1]
        resolved["registry_pins"]["contract_registry_hash"] = "f" * 64
        second_assessment["semantic_registry_pins"][
            "contract_registry_hash"
        ] = "f" * 64
        candidate_payload = {
            key: value
            for key, value in resolved.items()
            if key
            not in {"axis_readiness", "contract_readiness", "plan_readiness"}
        }
        contract_hash = canonical_sha256(
            ADAPTER.validate_json(json.dumps(candidate_payload))
        )
        second_assessment["contract_hash"] = contract_hash
        second_assessment["plan"]["contract_hash"] = contract_hash
    elif pin_kind == "binding":
        second_assessment["binding_registry_hash"] = "f" * 64
        second_assessment["plan"]["binding_registry_hash"] = "f" * 64
    elif pin_kind == "policy":
        second_assessment["physical_policy_registry_hash"] = "f" * 64
        second_assessment["plan"]["policy_registry_hash"] = "f" * 64
    elif pin_kind == "planning":
        second_assessment["planning_registry_hash"] = "f" * 64
    else:
        second_assessment["plan"]["dataset_pin"] = "f" * 64
    payload["compilation_id"] = "semantic-compilation-" + canonical_sha256(
        {key: value for key, value in payload.items() if key != "compilation_id"}
    )

    with pytest.raises(ValueError, match="COMPILATION_REGISTRY_PIN_MISMATCH"):
        type(compilation).model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("action", [item.value for item in IntentType])
def test_every_action_specific_semantic_body_has_an_exact_logical_representation(action) -> None:
    contract = _semantic_contract(action)
    roles = required_primitive_roles(
        contract.action_id,
        family_count=len(contract.scope.product_family_ids),
        relation_required=contract.action_id is IntentType.LOOKUP,
    )
    execution_steps = tuple(
        LogicalPrimitiveStepV2(
            primitive_id=role.primitive_id,
            action_id=role.action_id,
            capability=role.capability,
            operation_kind=role.operation_kind,
            execution_route=role.execution_route,
        )
        for role in roles
    )
    kwargs = dict(
        frame_id=contract.frame_id,
        candidate_id=f"candidate-{action}",
        contract_hash=canonical_sha256(contract),
        contract_variant_id=contract.contract_variant_id,
        action_id=contract.action_id,
        capability=execution_steps[-1].capability,
        execution_steps=execution_steps,
        scope=contract.scope,
        qualifiers=contract.qualifiers,
        result_shape=contract.result_shape,
        operation=lower_semantic_operation(contract),
        binding_ids=(),
        policy_ids=(),
        evidence_requirements=(),
        prior_result_inputs=(),
        produced_result_bindings=(),
    )
    draft = LogicalQueryTaskV2.model_construct(
        task_id="pending",
        resolved_contract_id="pending",
        **kwargs,
    )
    resolved_contract_id = logical_resolved_contract_reference_id(draft)
    draft = draft.model_copy(update={"resolved_contract_id": resolved_contract_id})
    task = LogicalQueryTaskV2(
        task_id=logical_task_id(draft),
        resolved_contract_id=resolved_contract_id,
        **kwargs,
    )

    assert reverse_semantic_loss_report(contract, task) == ()


@pytest.mark.parametrize(
    "mutation",
    [
        {"frame_id": "frame-other"},
        {"candidate_id": "candidate-other"},
        {"contract_hash": "f" * 64},
        {"binding_registry_hash": "f" * 64},
        {"physical_policy_registry_hash": "f" * 64},
        {"planning_registry_hash": "f" * 64},
    ],
)
def test_finalization_rejects_foreign_readiness_evidence(mutation) -> None:
    candidate = _rank()
    assessment = _assessment(candidate).model_copy(update=mutation)

    with pytest.raises(ValueError, match="READINESS_OWNERSHIP_MISMATCH"):
        _compile((candidate,), (assessment,))


def test_prior_result_scope_becomes_typed_dependency() -> None:
    first = _rank("frame-1")
    second = _rank("frame-2", "result-set-1")
    first = QueryContractCandidate(
        candidate_id=first.candidate_id,
        contract=first.contract.model_copy(
            update={"qualifiers": QueryQualifiersV2(as_of_date=date(2026, 8, 24))}
        ),
    )
    second = QueryContractCandidate(
        candidate_id=second.candidate_id,
        contract=second.contract.model_copy(
            update={"qualifiers": QueryQualifiersV2(as_of_date=date(2026, 8, 24))}
        ),
    )
    ownership = (
        PriorResultOwnershipV2(
            binding_id="result-set-1",
            producer_frame_id="frame-1",
            cardinality="many",
        ),
    )
    assessments = _actual_assessments(
        (first, second), prior_result_ownership=ownership
    )
    compilation = _compile(
        (first, second),
        assessments,
        prior_result_ownership=ownership,
    )

    plan = compilation.logical_query_plan
    assert plan is not None
    assert plan.dependencies[0].upstream_task_id == plan.tasks[0].task_id
    assert plan.tasks[1].prior_result_inputs[0].binding_id == "result-set-1"
    assert plan.tasks[1].binding_ids == ("domestic-etf-aum.v1",)


def test_three_frame_prior_result_chain_is_assessed_from_exact_predecessors() -> None:
    first = _rank("frame-1")
    second = _rank("frame-2", "result-set-1")
    third = _rank("frame-3", "result-set-2")
    candidates = tuple(
        QueryContractCandidate(
            candidate_id=item.candidate_id,
            contract=item.contract.model_copy(
                update={
                    "qualifiers": QueryQualifiersV2(
                        as_of_date=date(2026, 8, 24)
                    )
                }
            ),
        )
        for item in (first, second, third)
    )
    ownership = (
        PriorResultOwnershipV2(
            binding_id="result-set-1",
            producer_frame_id="frame-1",
            cardinality="many",
        ),
        PriorResultOwnershipV2(
            binding_id="result-set-2",
            producer_frame_id="frame-2",
            cardinality="many",
        ),
    )

    assessments = _actual_assessments(
        candidates,
        prior_result_ownership=ownership,
    )

    assert tuple(item.plan.readiness for item in assessments) == (
        PlanReadiness.EXECUTABLE,
        PlanReadiness.EXECUTABLE,
        PlanReadiness.EXECUTABLE,
    )


def test_limited_contract_has_no_executable_plan() -> None:
    candidate = _rank()
    compilation = _compile(
        (candidate,), (_assessment(candidate, readiness=PlanReadiness.LIMITED),)
    )

    assert compilation.route is CompilationRoute.EXPLORE
    assert compilation.logical_query_plan is None
    assert (
        compilation.resolved_query_contracts.contracts[0].plan_readiness.readiness
        is PlanReadiness.LIMITED
    )


@pytest.mark.parametrize("action", ["calculate", "similar"])
def test_stage05_only_actions_never_receive_a_production_plan(action) -> None:
    contract = _semantic_contract(action)
    candidate = QueryContractCandidate(
        candidate_id=f"candidate-{action}", contract=contract
    )
    compilation = _compile(
        (candidate,),
        (_assessment(candidate),),
        primitive_ids=(("calculate-products",) if action == "calculate" else ("similar-products",)),
    )

    assert compilation.route is CompilationRoute.EXPLORE
    assert compilation.logical_query_plan is None
    assert compilation.blocking_issues[0].code == "STAGE05_EXECUTOR_NOT_IMPLEMENTED"


def test_unverified_public_fund_population_stays_limited() -> None:
    payload = _base("aggregate", family="public_fund")
    payload["qualifiers"]["as_of_date"] = "2026-08-24"
    payload["aggregation"] = {
        "function_id": "sum",
        "target_field_concept_id": "aum",
        "count_population_id": None,
        "group_by_field_concept_ids": [],
        "bucket_policy_id": None,
        "population_grain_id": "representative-product.v1",
        "dedup_policy_id": "public-fund-representative-share.v1",
    }
    payload["predicate"] = None
    contract = ADAPTER.validate_json(json.dumps(payload))
    candidate = QueryContractCandidate(candidate_id="candidate-public-fund", contract=contract)
    assessment = _assessment(candidate, readiness=PlanReadiness.LIMITED)

    compilation = _compile(
        (candidate,), (assessment,), primitive_ids=("aggregate-products",)
    )

    assert compilation.route is CompilationRoute.EXPLORE
    assert compilation.logical_query_plan is None


def test_plan_readiness_result_itself_must_match_contract_and_registry() -> None:
    candidate = _rank()
    assessment = _assessment(candidate)
    foreign_plan = PlanReadinessResult(
        **{
            **assessment.plan.model_dump(),
            "contract_hash": "f" * 64,
        }
    )

    with pytest.raises(ValueError, match="READINESS_OWNERSHIP_MISMATCH"):
        _compile((candidate,), (assessment.model_copy(update={"plan": foreign_plan}),))


def test_readiness_success_cannot_carry_failure_reasons() -> None:
    candidate = _rank()
    assessment = _assessment(candidate).model_copy(
        update={
            "axis": AxisReadinessRecordV2(
                readiness=AxisReadiness.COMPLETE,
                reason_codes=("AXIS_CONFLICT",),
            )
        }
    )

    with pytest.raises(ValueError, match="READINESS_STATE_MISMATCH"):
        _compile((candidate,), (assessment,))


def test_prior_result_must_reference_an_earlier_frame() -> None:
    consumer = _rank("frame-1", "result-set-2")
    producer = _rank("frame-2")

    with pytest.raises(ValueError, match="PRIOR_RESULT_OWNERSHIP_MISMATCH"):
        _compile(
            (consumer, producer),
            (_assessment(consumer), _assessment(producer)),
            prior_result_ownership=(
                PriorResultOwnershipV2(
                    binding_id="result-set-2",
                    producer_frame_id="frame-2",
                    cardinality="many",
                ),
            ),
        )
