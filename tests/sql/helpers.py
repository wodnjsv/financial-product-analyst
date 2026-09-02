from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.query_contracts import QueryQualifiersV2, QueryResultShape, QueryScopeV2
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.logical_query import (
    LogicalQueryOperationV2,
    LogicalPrimitiveStepV2,
    LogicalQueryPlanV2,
    LogicalQueryTaskV2,
    SemanticLoweringRecordV2,
    logical_query_plan_id,
    logical_resolved_contract_reference_id,
    logical_task_id,
)
from financial_agent.planning.physical_bindings import (
    DatasetEvidenceRecord,
    DatasetSourceRecord,
    PhysicalReadinessFacts,
    PopulationMetricOwnership,
    PublicFundDatasetManifest,
    RepresentativeShareEdge,
    load_physical_binding_registry,
    load_semantic_sql_policy_registry,
)
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.planning.primitive_contracts import required_primitive_roles
from financial_agent.planning.registry import load_planning_registry
from financial_agent.intent.view import ActiveDatasetPin


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PIN = "43138033043db74566a74023c18b83e01b9637c1041ae737758aef55aaa9b36f"
BINDINGS = load_physical_binding_registry(PROJECT_ROOT)
POLICIES = load_semantic_sql_policy_registry(PROJECT_ROOT)
PLANNING = load_planning_registry(PROJECT_ROOT)
ACTIVE_DATASET = ActiveDatasetPin(
    dataset_version="synthetic-dataset-v1",
    manifest_hash=DATASET_PIN,
)


def make_plan(
    operation: LogicalQueryOperationV2,
    *,
    family: ProductFamily = ProductFamily.DOMESTIC_ETF,
    binding_ids: tuple[str, ...] = ("domestic-etf-aum.v1",),
    policy_ids: tuple[str, ...] = ("identity-unit.v1", "exclude_missing.v1"),
    evidence: tuple[str, ...] = ("metric_definition", "observation_record", "source_record"),
    qualifiers: QueryQualifiersV2 | None = None,
    entity_refs: tuple[str, ...] = (),
    result_shape: QueryResultShape | None = None,
) -> LogicalQueryPlanV2:
    action = IntentType(operation.operation_type)
    roles = required_primitive_roles(action, family_count=1, relation_required=False)
    shape = result_shape or {
        IntentType.LOOKUP: QueryResultShape.PRODUCT_LIST,
        IntentType.SCREEN: QueryResultShape.PRODUCT_LIST,
        IntentType.RANK: QueryResultShape.TOP_K,
        IntentType.COMPARE: QueryResultShape.COMPARISON_TABLE,
        IntentType.AGGREGATE: QueryResultShape.SINGLE_VALUE,
    }[action]
    variant = {
        IntentType.LOOKUP: "lookup.projection.v2",
        IntentType.SCREEN: "screen.predicate.v2",
        IntentType.RANK: "rank.ordering.v2",
        IntentType.COMPARE: "compare.subjects.v2",
        IntentType.AGGREGATE: (
            "aggregate.grouped.v2"
            if shape in {QueryResultShape.GROUPED_TABLE, QueryResultShape.DISTRIBUTION}
            else "aggregate.scalar.v2"
        ),
    }[action]
    task_kwargs = dict(
        frame_id="frame-1",
        candidate_id="candidate-1",
        contract_hash="b" * 64,
        contract_variant_id=variant,
        action_id=action,
        capability=roles[-1].capability,
        execution_steps=tuple(
            LogicalPrimitiveStepV2(
                primitive_id=role.primitive_id,
                action_id=role.action_id,
                capability=role.capability,
                operation_kind=role.operation_kind,
                execution_route=role.execution_route,
            )
            for role in roles
        ),
        scope=QueryScopeV2(product_family_ids=(family,), entity_refs=entity_refs),
        qualifiers=qualifiers or QueryQualifiersV2(as_of_date=date(2026, 8, 24)),
        result_shape=shape,
        operation=operation,
        binding_ids=binding_ids,
        policy_ids=policy_ids,
        evidence_requirements=evidence,
        prior_result_inputs=(),
        produced_result_bindings=(),
    )
    draft_task = LogicalQueryTaskV2.model_construct(
        task_id="pending", resolved_contract_id="pending", **task_kwargs
    )
    resolved_id = logical_resolved_contract_reference_id(draft_task)
    draft_task = draft_task.model_copy(update={"resolved_contract_id": resolved_id})
    task = LogicalQueryTaskV2(
        task_id=logical_task_id(draft_task), resolved_contract_id=resolved_id, **task_kwargs
    )
    plan_kwargs = dict(
        request_key="e" * 64,
        run_id="run-1",
        dataset_version="synthetic-dataset-v1",
        cutoff_date=date(2026, 8, 24),
        producer="semantic-query-compiler.v2",
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
        query_contract_id="query-contract-bundle-1",
        resolution_id="resolution-1",
        route=CompilationRoute.COMPOSE,
        tasks=(task,),
        dependencies=(),
        applied_policy_ids=policy_ids,
        primitive_ids=tuple(role.primitive_id for role in roles),
        binding_registry_version=BINDINGS.registry_version,
        binding_registry_hash=BINDINGS.registry_hash,
        physical_policy_registry_version=POLICIES.registry_version,
        physical_policy_registry_hash=POLICIES.registry_hash,
        contract_registry_version=BINDINGS.semantic_registry_pins.contract_registry_version,
        contract_registry_hash=BINDINGS.semantic_registry_pins.contract_registry_hash,
        operator_registry_version=BINDINGS.semantic_registry_pins.operator_registry_version,
        operator_registry_hash=BINDINGS.semantic_registry_pins.operator_registry_hash,
        semantic_policy_registry_version=BINDINGS.semantic_registry_pins.policy_registry_version,
        semantic_policy_registry_hash=BINDINGS.semantic_registry_pins.policy_registry_hash,
        planning_registry_version=PLANNING.registry_version,
        planning_registry_hash=PLANNING.registry_hash,
        dataset_pin=DATASET_PIN,
        lowering_records=(
            SemanticLoweringRecordV2(
                frame_id=task.frame_id,
                candidate_id=task.candidate_id,
                resolved_contract_id=task.resolved_contract_id,
                task_id=task.task_id,
                preserved_semantic_paths=("scope", "operation", "qualifiers"),
                binding_ids=binding_ids,
                policy_ids=policy_ids,
            ),
        ),
    )
    draft_plan = LogicalQueryPlanV2.model_construct(logical_plan_id="pending", **plan_kwargs)
    return LogicalQueryPlanV2(logical_plan_id=logical_query_plan_id(draft_plan), **plan_kwargs)


def verified_public_fund_facts() -> PhysicalReadinessFacts:
    manifest = PublicFundDatasetManifest(
        manifest_id="synthetic-public-fund-complete.v1",
        dataset_pin=DATASET_PIN,
        physical_policy_registry_version=POLICIES.registry_version,
        physical_policy_registry_hash=POLICIES.registry_hash,
        population_grain_policy_id="representative-product.v1",
        dedup_policy_id="public-fund-representative-share.v1",
        authoritative_share_class_ids=("share-a", "share-b"),
        source_records=tuple(
            DatasetSourceRecord(dataset_pin=DATASET_PIN, source_id=item)
            for item in ("source-a", "source-b", "source-observation-a")
        ),
        evidence_records=(
            DatasetEvidenceRecord(dataset_pin=DATASET_PIN, evidence_id="evidence-a", source_id="source-a"),
            DatasetEvidenceRecord(dataset_pin=DATASET_PIN, evidence_id="evidence-b", source_id="source-b"),
            DatasetEvidenceRecord(dataset_pin=DATASET_PIN, evidence_id="evidence-observation-a", source_id="source-observation-a"),
        ),
        representative_share_edges=(
            RepresentativeShareEdge(dataset_pin=DATASET_PIN, representative_id="representative-a", share_class_id="share-a", predicate_id="hasShareClass", relation_id="relation-a", evidence_id="evidence-a", source_id="source-a"),
            RepresentativeShareEdge(dataset_pin=DATASET_PIN, representative_id="representative-a", share_class_id="share-b", predicate_id="hasShareClass", relation_id="relation-b", evidence_id="evidence-b", source_id="source-b"),
        ),
        population_metric_ownerships=(
            PopulationMetricOwnership(dataset_pin=DATASET_PIN, representative_id="representative-a", metric_id="organizer.prfd01n001.net_assets", owner_entity_id="representative-a", observation_id="observation-a", evidence_id="evidence-observation-a", source_id="source-observation-a"),
        ),
    )
    return PhysicalReadinessFacts(
        known_entity_ids=frozenset({"representative-a", "share-a", "share-b"}),
        public_fund_manifest=manifest,
        public_fund_manifest_hash=canonical_sha256(manifest),
    )
