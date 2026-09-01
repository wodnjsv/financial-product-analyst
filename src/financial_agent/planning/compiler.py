from __future__ import annotations

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import (
    Capability,
    InitialAnswerability,
    IntentType,
    ResultShape,
    SubtaskImportance,
)
from financial_agent.contracts.query import (
    AmbiguityDecision,
    OperationSpec,
    QueryPlan,
    Subtask,
)
from financial_agent.intent.catalog import SemanticCatalogSnapshot
from financial_agent.intent.resolution import ValidatedIntentResolutionV2
from financial_agent.intent.types import SemanticTag, SlotKind
from financial_agent.intent.view import ResolverView

from .contracts import (
    CompilationIssue,
    CompilationRoute,
    CompilerManifest,
    QueryPlanCompilation,
)
from .lowering import LoweringError, lower_inputs
from .registry import PlanningRegistry, PrimitiveDefinition
from .router import decide_route


_ACTION_PRIMITIVES = {
    IntentType.LOOKUP: ("lookup-products",),
    IntentType.SCREEN: ("lookup-products", "screen-products"),
    IntentType.RANK: ("lookup-products", "rank-products"),
    IntentType.COMPARE: ("lookup-products", "compare-products"),
    IntentType.AGGREGATE: ("lookup-products", "aggregate-products"),
    IntentType.CALCULATE: ("lookup-products", "calculate-products"),
    IntentType.SIMILAR: ("lookup-products", "similar-products"),
    IntentType.EXPLAIN: ("lookup-products",),
}
_RESULT_SHAPES = {
    IntentType.LOOKUP: ResultShape.PRODUCT_LIST,
    IntentType.SCREEN: ResultShape.PRODUCT_LIST,
    IntentType.RANK: ResultShape.TOP_K,
    IntentType.COMPARE: ResultShape.COMPARISON_TABLE,
    IntentType.AGGREGATE: ResultShape.SINGLE_VALUE,
    IntentType.CALCULATE: ResultShape.SINGLE_VALUE,
    IntentType.SIMILAR: ResultShape.PRODUCT_LIST,
    IntentType.EXPLAIN: ResultShape.EXPLANATION,
}


class CompilerInvariantError(RuntimeError):
    pass


class QueryPlanCompiler:
    def __init__(
        self,
        *,
        catalog: SemanticCatalogSnapshot,
        registry: PlanningRegistry,
    ) -> None:
        self._catalog = catalog
        self._registry = registry

    def compile(
        self,
        resolution: ValidatedIntentResolutionV2,
        view: ResolverView,
    ) -> QueryPlanCompilation:
        self._validate_pins(resolution, view)
        view_hash = canonical_sha256(view)
        decision = decide_route(resolution, self._registry)
        if decision.route is CompilationRoute.ABSTAIN:
            return self._abstain(
                resolution,
                view_hash,
                decision.issue_code or "COMPILATION_BLOCKED",
            )
        try:
            lowered = lower_inputs(resolution, view)
            primitive_ids = self._primitive_ids(resolution, decision.route, decision.archetype)
            self._validate_applicability(resolution, lowered.assignments_by_frame)
            query_plan = self._build_query_plan(
                resolution,
                lowered,
                primitive_ids,
                decision.archetype.result_shape if decision.archetype else None,
                explore=decision.route is CompilationRoute.EXPLORE,
            )
        except LoweringError as error:
            return self._abstain(resolution, view_hash, error.code, error.related_ids)
        compilation_id = _compilation_id(
            resolution.resolution_id,
            view_hash,
            self._registry.registry_hash,
            decision.route,
        )
        return QueryPlanCompilation(
            request_key=resolution.request_key,
            run_id=resolution.run_id,
            dataset_version=resolution.dataset_version,
            producer="query-plan-compiler",
            created_at=resolution.created_at,
            compilation_id=compilation_id,
            resolution_id=resolution.resolution_id,
            route=decision.route,
            query_plan=query_plan,
            matched_archetype_id=(decision.archetype.id if decision.archetype else None),
            primitive_ids=primitive_ids,
            applied_default_ids=(),
            lowering_records=lowered.records,
            blocking_issues=(),
            resolver_view_hash=view_hash,
            compiler_manifest=self._manifest(),
        )

    def _validate_pins(
        self,
        resolution: ValidatedIntentResolutionV2,
        view: ResolverView,
    ) -> None:
        if resolution.build_manifest != view.build_manifest:
            raise CompilerInvariantError("RESOLVER_MANIFEST_MISMATCH")
        if (
            resolution.dataset_version != view.active_dataset_pin.dataset_version
            or resolution.active_dataset_manifest_hash
            != view.active_dataset_pin.manifest_hash
        ):
            raise CompilerInvariantError("DATASET_PIN_MISMATCH")
        if (
            resolution.build_manifest.catalog_version != self._catalog.catalog_version
            or resolution.build_manifest.catalog_hash != self._catalog.catalog_hash
        ):
            raise CompilerInvariantError("CATALOG_PIN_MISMATCH")

    def _primitive_ids(self, resolution, route, archetype) -> tuple[str, ...]:
        if route is CompilationRoute.EXPLORE:
            return ("explore-catalog",)
        if archetype is not None:
            return archetype.primitive_ids
        selected: list[str] = []
        for frame in resolution.canonical_frames:
            action = frame.action_choice.selected_ids[0]
            selected.extend(_ACTION_PRIMITIVES[action])
            kinds = {item.slot_kind for item in frame.slot_assignments}
            if SlotKind.RELATION in kinds:
                selected.append("traverse-relations")
            if SlotKind.DOCUMENT_TOPIC in kinds:
                selected.append("search-documents")
        return _unique(selected)

    def _validate_applicability(self, resolution, assignments_by_frame) -> None:
        concepts = self._catalog.concepts_by_id
        for frame in resolution.canonical_frames:
            families = {item.value for item in frame.product_family_choice.selected_ids}
            for assignment in assignments_by_frame[frame.frame_id]:
                for value_id in assignment.value_ids:
                    concept = concepts.get(value_id)
                    if concept and not families <= set(concept.allowed_product_families):
                        raise LoweringError("CONCEPT_NOT_APPLICABLE", (value_id,))

    def _build_query_plan(
        self,
        resolution,
        lowered,
        primitive_ids,
        archetype_shape,
        *,
        explore,
    ) -> QueryPlan:
        operations: list[OperationSpec] = []
        subtasks: list[Subtask] = []
        for frame in resolution.canonical_frames:
            action = frame.action_choice.selected_ids[0]
            family_parameters = tuple(
                f"family:{family.value}"
                for family in frame.product_family_choice.selected_ids
            )
            coverage_parameters = tuple(
                f"evidence:{evidence_id}"
                for coverage in frame.semantic_coverage
                for evidence_id in coverage.evidence_ids
            )
            entity_parameters = tuple(
                f"entity:{value_id}"
                for assignment in lowered.assignments_by_frame[frame.frame_id]
                if assignment.slot_kind is SlotKind.ENTITY
                for value_id in assignment.value_ids
            ) + tuple(
                f"entity_request:resolve:{hint.entity_hint_id}"
                for hint in resolution.entity_hints
                if hint.entity_hint_id in frame.entity_hint_ids
                and not hint.selected_candidate_ids
            )
            semantic_slot_parameters = tuple(
                f"slot:{assignment.slot_kind.value}:{value_id}"
                for assignment in lowered.assignments_by_frame[frame.frame_id]
                if assignment.slot_kind
                in {
                    SlotKind.METRIC,
                    SlotKind.SORT_KEY,
                    SlotKind.RELATION,
                    SlotKind.COMPARISON_BASIS,
                    SlotKind.SIMILARITY_ANCHOR,
                    SlotKind.DOCUMENT_TOPIC,
                }
                for value_id in assignment.value_ids
            )
            frame_primitives = (
                ("explore-catalog",)
                if explore
                else tuple(
                    primitive_id
                    for primitive_id in primitive_ids
                    if action in self._registry.primitives_by_id[primitive_id].action_ids
                )
            )
            if not frame_primitives:
                raise LoweringError("NO_PRIMITIVE_FOR_FRAME", (frame.frame_id,))
            operation_ids: list[str] = []
            present_slots = {
                item.slot_kind.value
                for item in lowered.assignments_by_frame[frame.frame_id]
            }
            link_parameters = lowered.link_parameters_by_frame.get(frame.frame_id, ())
            for primitive_id in frame_primitives:
                if primitive_id == "lookup-products" and any(
                    item.startswith("binding:") for item in link_parameters
                ):
                    continue
                primitive = self._registry.primitives_by_id[primitive_id]
                if not explore and not set(primitive.required_slots) <= present_slots:
                    continue
                operation_id = f"operation:{frame.frame_id}:{primitive_id}"
                parameter_ids = tuple(
                    parameter
                    for parameter in primitive.parameter_ids
                    if parameter in present_slots
                    or parameter == "semantic_evidence"
                    or parameter.startswith("policy:")
                ) + (
                    link_parameters
                    + family_parameters
                    + coverage_parameters
                    + entity_parameters
                    + semantic_slot_parameters
                )
                operations.append(
                    OperationSpec(
                        subtask_id=frame.frame_id,
                        operation_id=operation_id,
                        parameter_ids=_unique(parameter_ids),
                    )
                )
                operation_ids.append(operation_id)
            if not operation_ids:
                raise LoweringError("REQUIRED_SLOT_MISSING", (frame.frame_id,))
            subtasks.append(
                Subtask(
                    subtask_id=frame.frame_id,
                    intent_type=action,
                    importance=SubtaskImportance.CRITICAL,
                    operation_ids=tuple(operation_ids),
                )
            )
        capabilities = tuple(
            capability
            for capability in Capability
            if any(
                self._registry.primitives_by_id[item].capability is capability
                for item in primitive_ids
            )
        )
        actions = _unique(
            frame.action_choice.selected_ids[0]
            for frame in resolution.canonical_frames
        )
        families = tuple(
            sorted(
                {
                    family
                    for frame in resolution.canonical_frames
                    for family in frame.product_family_choice.selected_ids
                },
                key=lambda item: item.value,
            )
        )
        initial = (
            InitialAnswerability.REQUIRES_ADDITIONAL_DATA
            if explore
            else InitialAnswerability.REQUIRES_NORMALIZATION
            if SemanticTag.NORMALIZATION_REQUIRED in resolution.final_tags
            else InitialAnswerability.SUPPORTED
        )
        return QueryPlan(
            request_key=resolution.request_key,
            run_id=resolution.run_id,
            dataset_version=resolution.dataset_version,
            producer="query-plan-compiler",
            created_at=resolution.created_at,
            intent_types=actions,
            product_families=families,
            subtasks=tuple(subtasks),
            entity_resolution_requests=lowered.entity_requests,
            resolved_references=lowered.resolved_references,
            binding_specs=lowered.binding_specs,
            dependency_edges=lowered.dependency_edges,
            filters=lowered.filters,
            metrics=lowered.metrics,
            operations=tuple(operations),
            result_shape=(
                ResultShape.EXPLANATION
                if explore
                else archetype_shape or _RESULT_SHAPES[actions[-1]]
            ),
            ambiguity_decisions=(
                AmbiguityDecision(
                    issue_code="SEMANTIC_COVERAGE_GAP",
                    policy_id="bounded_explore",
                    outcome_id="explore_catalog",
                    disclosure_required=True,
                ),
            )
            if explore
            else (),
            requested_capabilities=capabilities,
            initial_answerability=initial,
        )

    def _abstain(self, resolution, view_hash, code, related_ids=()):
        route = CompilationRoute.ABSTAIN
        return QueryPlanCompilation(
            request_key=resolution.request_key,
            run_id=resolution.run_id,
            dataset_version=resolution.dataset_version,
            producer="query-plan-compiler",
            created_at=resolution.created_at,
            compilation_id=_compilation_id(
                resolution.resolution_id,
                view_hash,
                self._registry.registry_hash,
                route,
            ),
            resolution_id=resolution.resolution_id,
            route=route,
            query_plan=None,
            matched_archetype_id=None,
            primitive_ids=(),
            applied_default_ids=(),
            lowering_records=(),
            blocking_issues=(CompilationIssue(code=code, related_ids=related_ids),),
            resolver_view_hash=view_hash,
            compiler_manifest=self._manifest(),
        )

    def _manifest(self) -> CompilerManifest:
        return CompilerManifest(
            registry_version=self._registry.registry_version,
            registry_hash=self._registry.registry_hash,
            compiler_version=self._registry.compiler_version,
        )


def _compilation_id(resolution_id, view_hash, registry_hash, route):
    seed = canonical_sha256(
        {
            "resolution_id": resolution_id,
            "resolver_view_hash": view_hash,
            "registry_hash": registry_hash,
            "route": route.value,
        }
    )
    return f"compilation-{seed[:24]}"


def _unique(values):
    result = []
    seen = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)
