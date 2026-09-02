"""Offline-only decoupled contract metrics over injected adjudicated axes."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.axis_locks import ExactSemanticLock
from financial_agent.intent.catalog import SemanticCatalogSnapshot, load_catalog
from financial_agent.intent.draft import (
    ActionChoice,
    ProductFamilyChoice,
    SlotAssignment,
)
from financial_agent.intent.proposal import FrameSemanticCoverage
from financial_agent.intent.query_contract_registry import QueryContractRegistry
from financial_agent.intent.query_contract_solver import solve_query_contracts
from financial_agent.intent.resolution import ValidatedIntentResolutionV2
from financial_agent.intent.types import (
    ChoiceState,
    ResolutionStatus,
    SemanticCoverageReason,
    SemanticCoverageState,
    SlotKind,
)
from financial_agent.intent.view import (
    ResolverView,
    ResolverViewConcept,
    ResolverViewLiteralCandidate,
    ResolverViewRelationDefinition,
    ResolverViewSemanticCandidate,
    ResolverViewSemanticCandidateGroup,
)
from tests.evaluation.query_contract.coverage import load_requirement_snapshot
from tests.planning.fixtures import resolution as fixture_resolution
from tests.planning.fixtures import view as fixture_view


REQUIRED_CANDIDATE_RECALL = 0.99
REQUIRED_EXACT_CONTRACT = 0.95
REQUIRED_COMPILE_ELIGIBILITY = 1.0


@dataclass(frozen=True, slots=True)
class DecoupledContractCase:
    case_id: str
    injected_axes: ValidatedIntentResolutionV2
    view: ResolverView
    exact_locks: tuple[ExactSemanticLock, ...]
    expected_candidate_ids_by_frame: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class DecoupledContractMetrics:
    frame_count: int
    supported_frame_count: int
    candidate_recall_count: int
    exact_contract_count: int
    false_complete_count: int
    compile_eligible_count: int

    @property
    def candidate_recall(self) -> float:
        return (
            self.candidate_recall_count / self.supported_frame_count
            if self.supported_frame_count
            else 1.0
        )

    @property
    def exact_contract(self) -> float:
        return (
            self.exact_contract_count / self.supported_frame_count
            if self.supported_frame_count
            else 1.0
        )

    @property
    def compile_eligibility(self) -> float:
        return (
            self.compile_eligible_count / self.supported_frame_count
            if self.supported_frame_count
            else 1.0
        )


@dataclass(frozen=True, slots=True)
class FrozenSnapshotContractMetrics:
    total_frame_count: int
    supported_frame_count: int
    unsupported_frame_count: int
    intentionally_blocked_frame_count: int
    measured_frame_count: int
    evaluation_unmeasured_frame_count: int
    unmeasured_reason_counts: tuple[tuple[str, int], ...]
    candidate_recall_count: int
    exact_contract_count: int
    false_complete_count: int
    compile_eligible_count: int

    @property
    def candidate_recall(self) -> float:
        denominator = self.measured_frame_count
        return self.candidate_recall_count / denominator if denominator else 1.0

    @property
    def exact_contract(self) -> float:
        denominator = self.measured_frame_count
        return self.exact_contract_count / denominator if denominator else 1.0

    @property
    def compile_eligibility(self) -> float:
        denominator = self.measured_frame_count
        return self.compile_eligible_count / denominator if denominator else 1.0

    @property
    def passes_required_gates(self) -> bool:
        return (
            self.candidate_recall >= REQUIRED_CANDIDATE_RECALL
            and self.exact_contract >= REQUIRED_EXACT_CONTRACT
            and self.false_complete_count == 0
            and self.compile_eligibility >= REQUIRED_COMPILE_ELIGIBILITY
        )


def evaluate_decoupled_contract_resolution(
    cases: tuple[DecoupledContractCase, ...],
    registry: QueryContractRegistry,
) -> DecoupledContractMetrics:
    """Measure contract solving only; callers must inject reviewed axis artifacts."""

    frame_count = supported = recall = exact = false_complete = compile_eligible = 0
    for case in cases:
        solved = solve_query_contracts(
            resolution=case.injected_axes,
            view=case.view,
            exact_locks=case.exact_locks,
            registry=registry,
        )
        if len(solved.frames) != len(case.expected_candidate_ids_by_frame):
            raise ValueError(f"DECOUPLED_FRAME_COUNT_MISMATCH:{case.case_id}")
        for frame, expected_ids in zip(
            solved.frames, case.expected_candidate_ids_by_frame, strict=True
        ):
            frame_count += 1
            actual_ids = tuple(item.candidate_id for item in frame.complete_candidates)
            if expected_ids:
                supported += 1
                if set(expected_ids) <= set(actual_ids):
                    recall += 1
                if actual_ids == expected_ids:
                    exact += 1
                if len(actual_ids) == 1 and actual_ids == expected_ids:
                    compile_eligible += 1
            elif len(actual_ids) == 1:
                false_complete += 1
    return DecoupledContractMetrics(
        frame_count=frame_count,
        supported_frame_count=supported,
        candidate_recall_count=recall,
        exact_contract_count=exact,
        false_complete_count=false_complete,
        compile_eligible_count=compile_eligible,
    )


def evaluate_frozen_requirement_snapshot(
    project_root: Path,
    registry: QueryContractRegistry,
) -> FrozenSnapshotContractMetrics:
    """Run the real solver over every frozen, adjudicated held-out frame.

    Task 4 intentionally offers no calculation recipe registry. A frame is
    excluded from current-stage solver denominators only when its actual result
    has no candidate and every rejection is `RECIPE_NOT_OFFERED`.
    """

    root = project_root.resolve()
    snapshot = load_requirement_snapshot(root)
    payload = json.loads(
        (
            root
            / "tests/evaluation/query_contract/query_contract_requirements.v1.json"
        ).read_text(encoding="utf-8")
    )
    heldout = tuple(
        item for item in payload["requirements"] if item["source"] == "heldout"
    )
    if len(heldout) != snapshot.heldout_frame_count:
        raise ValueError("DECOUPLED_REQUIREMENT_COUNT_MISMATCH")

    source_pin = payload["sources"]["heldout"]["path"]
    heldout_source = json.loads((root / source_pin).read_text(encoding="utf-8"))
    frames_by_key = {
        (case["case_id"], frame["ordinal"]): frame
        for case in heldout_source["cases"]
        for frame in case["expected_frames"]
    }
    catalog = load_catalog(root)
    supported = unsupported = blocked = recall = exact = false_complete = eligible = 0
    measured = 0
    unmeasured: Counter[str] = Counter()
    for requirement in heldout:
        source_frame = frames_by_key[
            (requirement["case_id"], requirement["frame_ordinal"])
        ]

        if requirement["support_status"] == "supported":
            supported += 1
            if requirement["action_id"] != "calculate":
                expectation, reason = _gold_expectation(
                    requirement, source_frame, catalog, registry
                )
                if reason is not None:
                    unmeasured[reason] += 1
                    continue
                assert expectation is not None
                measured += 1
        else:
            expectation = None

        injected, resolver_view, exact_locks = _adjudicated_solver_input(
            requirement, source_frame, catalog
        )
        solved = solve_query_contracts(
            resolution=injected,
            view=resolver_view,
            exact_locks=exact_locks,
            registry=registry,
        )
        if len(solved.frames) != 1:
            raise ValueError("DECOUPLED_SOLVER_FRAME_COUNT_MISMATCH")
        actual = solved.frames[0]

        if requirement["support_status"] == "unsupported":
            unsupported += 1
            if not requirement.get("reason_code"):
                raise ValueError("DECOUPLED_UNSUPPORTED_REASON_MISSING")
            if not source_frame["action_ids"] or not (
                source_frame["product_family_ids"]
                or source_frame["entity_type_ids"]
            ):
                raise ValueError("DECOUPLED_UNSUPPORTED_SEMANTICS_MISSING")
            false_complete += int(bool(actual.complete_candidates))
            continue

        rejection_codes = {item.reason_code for item in actual.rejections}
        if (
            not actual.complete_candidates
            and rejection_codes == {"RECIPE_NOT_OFFERED"}
        ):
            blocked += 1
            continue
        if expectation is None:
            unmeasured["CALCULATION_EXPECTED_BLOCK_NOT_OBSERVED"] += 1
            continue
        compatible = tuple(
            item
            for item in actual.complete_candidates
            if _projection_compatible(
                _candidate_projection(item.contract.model_dump(mode="json")),
                expectation.roles,
            )
        )
        correct = tuple(
            item
            for item in compatible
            if _projection_exact(
                _candidate_projection(item.contract.model_dump(mode="json")),
                expectation.roles,
            )
        )
        if compatible:
            recall += 1
        if correct:
            exact += 1
            eligible += 1

    return FrozenSnapshotContractMetrics(
        total_frame_count=len(heldout),
        supported_frame_count=supported,
        unsupported_frame_count=unsupported,
        intentionally_blocked_frame_count=blocked,
        measured_frame_count=measured,
        evaluation_unmeasured_frame_count=sum(unmeasured.values()),
        unmeasured_reason_counts=tuple(sorted(unmeasured.items())),
        candidate_recall_count=recall,
        exact_contract_count=exact,
        false_complete_count=false_complete,
        compile_eligible_count=eligible,
    )


def _expected_variant_ids(
    requirement: dict[str, object], registry: QueryContractRegistry
) -> frozenset[str]:
    components = set(requirement["required_components"])
    if requirement["action_id"] == "similar":
        components.update({"scope", "similarity.coverage_threshold"})
    return frozenset(
        variant.id
        for variant in registry.variants_by_id.values()
        if variant.action_id.value == requirement["action_id"]
        and set(variant.required_components) == components
    )


@dataclass(frozen=True, slots=True)
class _GoldExpectation:
    roles: tuple[tuple[str, tuple[str, ...]], ...]


_OPERATOR_IDS = {
    "equals": "eq",
    "less_than": "lt",
    "greater_than": "gt",
}


def _gold_expectation(
    requirement: dict[str, object],
    source_frame: dict[str, object],
    catalog: SemanticCatalogSnapshot,
    registry: QueryContractRegistry,
) -> tuple[_GoldExpectation | None, str | None]:
    action = requirement["action_id"]
    slots = requirement.get("source_slot_values", {})
    overrides = requirement.get("semantic_overrides", {})
    families = tuple(source_frame["product_family_ids"])
    if not families:
        return None, "GOLD_SCOPE_IDENTITY_MISSING"
    if slots.get("relation") and not slots.get("entity"):
        return None, "GOLD_RELATION_TARGET_MISSING"

    roles: dict[str, tuple[str, ...]] = {
        "action": (action,),
        "scope.product_family": tuple(sorted(families)),
        "contract.variant": tuple(sorted(_expected_variant_ids(requirement, registry))),
    }
    fields = _explicit_fields(requirement)
    _add_gold_qualifiers(roles, slots)

    if action == "lookup":
        if not fields:
            return None, "GOLD_PROJECTION_MISSING"
        roles["projection.field"] = tuple(sorted(fields))
    elif action == "screen":
        if not fields:
            return None, "GOLD_PREDICATE_FIELD_MISSING"
        operators = tuple(slots.get("filter_operator", ()))
        if not operators:
            return None, "GOLD_PREDICATE_OPERATOR_MISSING"
        values = tuple(slots.get("filter_value", ()))
        if not values:
            return None, "GOLD_PREDICATE_VALUE_MISSING"
        roles["predicate.field"] = tuple(sorted(fields))
        roles["predicate.operator"] = tuple(
            sorted(_OPERATOR_IDS.get(item, item) for item in operators)
        )
        value_kind = _semantic_value_kind(catalog.concepts_by_id[fields[0]].value_kind)
        roles["predicate.value"] = tuple(
            sorted(f"{value_kind}:{value}" for value in values)
        )
    elif action == "rank":
        ordering = overrides.get("ordering", {}) if isinstance(overrides, dict) else {}
        if not fields:
            return None, "GOLD_ORDERING_FIELD_MISSING"
        directions = tuple(slots.get("sort_direction", ()))
        if ordering.get("direction"):
            directions = (ordering["direction"],)
        if not directions:
            return None, "GOLD_ORDERING_DIRECTION_MISSING"
        limits = tuple(slots.get("result_limit", ()))
        limit_policy = ordering.get("limit_policy")
        if not limits and not limit_policy:
            return None, "GOLD_LIMIT_MISSING"
        roles["ordering.field"] = tuple(sorted(fields))
        roles["ordering.direction"] = tuple(sorted(directions))
        roles["limit"] = (
            tuple(sorted(limits)) if limits else (f"policy:{limit_policy}",)
        )
    elif action == "compare":
        if not fields:
            return None, "GOLD_COMPARISON_FIELDS_MISSING"
        roles["comparison.field"] = tuple(sorted(fields))
        subjects = tuple(slots.get("entity", ()))
        if len(subjects) < 2:
            return None, "GOLD_COMPARISON_SUBJECTS_MISSING"
        basis = tuple(slots.get("comparison_policy", ()))
        if not basis:
            return None, "GOLD_COMPARISON_BASIS_MISSING"
        roles["comparison.subject"] = tuple(sorted(subjects))
        roles["comparison.basis"] = tuple(sorted(basis))
    elif action == "aggregate":
        functions = tuple(slots.get("aggregation_function", ()))
        if not functions:
            return None, "GOLD_AGGREGATION_FUNCTION_MISSING"
        if not fields:
            return None, "GOLD_AGGREGATION_TARGET_MISSING"
        population = tuple(slots.get("population_grain", ()))
        dedup = tuple(slots.get("dedup_policy", ()))
        if not population or not dedup:
            return None, "GOLD_AGGREGATION_POLICY_MISSING"
        roles["aggregation.function"] = tuple(sorted(functions))
        roles["aggregation.target"] = tuple(sorted(fields))
        roles["aggregation.population"] = tuple(sorted(population))
        roles["aggregation.dedup"] = tuple(sorted(dedup))
        grouping = tuple(slots.get("group_by", ()))
        if grouping:
            roles["aggregation.group"] = tuple(sorted(grouping))
    elif action == "similar":
        anchors = tuple(slots.get("similarity_anchor", ()))
        dimensions = tuple(slots.get("similarity_dimension", ()))
        policies = tuple(slots.get("similarity_policy", ()))
        if not anchors:
            return None, "GOLD_SIMILARITY_ANCHOR_MISSING"
        if not dimensions:
            return None, "GOLD_SIMILARITY_DIMENSIONS_MISSING"
        if not policies:
            return None, "GOLD_SIMILARITY_POLICY_MISSING"
        roles["similarity.anchor"] = tuple(sorted(anchors))
        roles["similarity.dimension"] = tuple(sorted(dimensions))
        roles["similarity.policy"] = tuple(sorted(policies))
        limits = tuple(slots.get("result_limit", ()))
        if limits:
            roles["limit"] = tuple(sorted(limits))
    elif action == "explain":
        topics = tuple(slots.get("document_topic", ()))
        if not topics:
            return None, "GOLD_EXPLANATION_TARGET_MISSING"
        roles["explanation.target"] = tuple(sorted(topics))
    else:
        return None, "GOLD_ACTION_NOT_MEASURABLE"
    missing_qualifier = _missing_required_qualifier(fields, slots, catalog)
    if missing_qualifier is not None:
        return None, missing_qualifier
    return _GoldExpectation(tuple(sorted(roles.items()))), None


def _candidate_matches_adjudication(
    contract: object, requirement: dict[str, object]
) -> bool:
    payload = contract.model_dump(mode="json")
    expected, missing = _available_gold_roles(requirement)
    if missing is not None:
        return False
    return _projection_compatible(_candidate_projection(payload), expected)


def _available_gold_roles(
    requirement: dict[str, object],
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], str | None]:
    action = requirement["action_id"]
    slots = requirement.get("source_slot_values", {})
    overrides = requirement.get("semantic_overrides", {})
    roles: dict[str, tuple[str, ...]] = {"action": (action,)}
    fields = _explicit_fields(requirement)
    _add_gold_qualifiers(roles, slots)
    if action == "screen":
        if not slots.get("filter_value"):
            return (), "GOLD_PREDICATE_VALUE_MISSING"
        roles["predicate.field"] = tuple(sorted(fields))
        roles["predicate.operator"] = tuple(
            sorted(
                _OPERATOR_IDS.get(item, item)
                for item in slots.get("filter_operator", ())
            )
        )
        roles["predicate.value"] = tuple(sorted(slots["filter_value"]))
    elif action == "compare":
        roles["comparison.field"] = tuple(sorted(fields))
    elif action == "rank":
        ordering = overrides.get("ordering", {}) if isinstance(overrides, dict) else {}
        roles["ordering.field"] = tuple(sorted(fields))
        directions = tuple(slots.get("sort_direction", ()))
        if ordering.get("direction"):
            directions = (ordering["direction"],)
        if directions:
            roles["ordering.direction"] = tuple(sorted(directions))
        limits = tuple(slots.get("result_limit", ()))
        if limits:
            roles["limit"] = tuple(sorted(limits))
        elif ordering.get("limit_policy"):
            roles["limit"] = (f"policy:{ordering['limit_policy']}",)
    return tuple(sorted(roles.items())), None


def _explicit_fields(requirement: dict[str, object]) -> tuple[str, ...]:
    slots = requirement.get("source_slot_values", {})
    overrides = requirement.get("semantic_overrides", {})
    ordering = overrides.get("ordering", {}) if isinstance(overrides, dict) else {}
    return tuple(
        dict.fromkeys(
            (
                *((ordering.get("field"),) if ordering.get("field") else ()),
                *slots.get("sort_key", ()),
                *slots.get("metric", ()),
                *slots.get("comparison_basis", ()),
                *slots.get("document_topic", ()),
            )
        )
    )


def _missing_required_qualifier(
    fields: tuple[str, ...],
    slots: dict[str, object],
    catalog: SemanticCatalogSnapshot,
) -> str | None:
    slot_by_qualifier = {
        "as_of": "date_scope",
        "as_of_date": "date_scope",
        "period": "period",
        "currency": "currency",
        "unit": "unit",
    }
    for field_id in fields:
        concept = catalog.concepts_by_id.get(field_id)
        if concept is None:
            return "GOLD_FIELD_NOT_IN_CATALOG"
        for qualifier in concept.required_qualifiers:
            slot = slot_by_qualifier.get(qualifier, qualifier)
            if not slots.get(slot):
                return f"GOLD_QUALIFIER_MISSING:{qualifier}"
    return None


def _add_gold_qualifiers(
    roles: dict[str, tuple[str, ...]], slots: dict[str, object]
) -> None:
    for slot, role in (
        ("period", "qualifier.period"),
        ("currency", "qualifier.currency"),
        ("unit", "qualifier.unit"),
        ("date_scope", "qualifier.as_of"),
    ):
        if values := tuple(slots.get(slot, ())):
            roles[role] = tuple(sorted(values))


def _candidate_projection(
    payload: dict[str, object],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    roles: dict[str, tuple[str, ...]] = {}
    _put(roles, "action", payload.get("action_id"))
    _put(roles, "contract.variant", payload.get("contract_variant_id"))
    scope = payload.get("scope") or {}
    _put_many(roles, "scope.product_family", scope.get("product_family_ids", ()))
    qualifiers = payload.get("qualifiers") or {}
    for key, role in (
        ("period_id", "qualifier.period"),
        ("currency_id", "qualifier.currency"),
        ("unit_id", "qualifier.unit"),
        ("as_of_date", "qualifier.as_of"),
    ):
        _put(roles, role, qualifiers.get(key))

    projections = payload.get("projections") or {}
    _put_many(roles, "projection.field", projections.get("field_concept_ids", ()))
    _put(roles, "projection.profile", projections.get("default_profile_id"))

    atoms = tuple(_predicate_atoms(payload.get("predicate")))
    _put_many(
        roles,
        "predicate.field",
        (item.get("field_concept_id") for item in atoms),
    )
    _put_many(
        roles,
        "predicate.operator",
        (item.get("operator_id") for item in atoms),
    )
    _put_many(
        roles,
        "predicate.value",
        (
            value
            for item in atoms
            for value in _typed_predicate_values(item)
        ),
    )

    ordering = payload.get("ordering") or ()
    _put_many(
        roles, "ordering.field", (item.get("field_concept_id") for item in ordering)
    )
    _put_many(
        roles,
        "ordering.direction",
        (
            item.get("direction")
            or (
                f"policy:{item['direction_policy_id']}"
                if item.get("direction_policy_id")
                else None
            )
            for item in ordering
        ),
    )
    _put(
        roles,
        "limit",
        payload.get("limit")
        if payload.get("limit") is not None
        else (
            f"policy:{payload['limit_policy_id']}"
            if payload.get("limit_policy_id")
            else None
        ),
    )

    comparison = payload.get("comparison") or {}
    _put_many(roles, "comparison.subject", comparison.get("subject_refs", ()))
    _put(roles, "comparison.subject", comparison.get("group_basis_id"))
    _put_many(
        roles, "comparison.field", comparison.get("metric_concept_ids", ())
    )
    _put(roles, "comparison.basis", comparison.get("basis_policy_id"))

    aggregation = payload.get("aggregation") or {}
    _put(roles, "aggregation.function", aggregation.get("function_id"))
    _put(roles, "aggregation.target", aggregation.get("target_field_concept_id"))
    _put_many(
        roles, "aggregation.group", aggregation.get("group_by_field_concept_ids", ())
    )
    _put(roles, "aggregation.population", aggregation.get("population_grain_id"))
    _put(roles, "aggregation.dedup", aggregation.get("dedup_policy_id"))

    similarity = payload.get("similarity") or {}
    _put(roles, "similarity.anchor", similarity.get("anchor_ref"))
    _put_many(
        roles, "similarity.dimension", similarity.get("dimension_concept_ids", ())
    )
    _put(roles, "similarity.policy", similarity.get("policy_id"))
    if similarity.get("limit") is not None:
        _put(roles, "limit", similarity["limit"])

    explanation = payload.get("explanation") or {}
    _put(
        roles,
        "explanation.target",
        explanation.get("topic_concept_id") or explanation.get("profile_id"),
    )
    return tuple(sorted(roles.items()))


def _put(
    roles: dict[str, tuple[str, ...]], role: str, value: object
) -> None:
    if value is None:
        return
    roles[role] = tuple(sorted((*roles.get(role, ()), str(value))))


def _put_many(
    roles: dict[str, tuple[str, ...]], role: str, values: object
) -> None:
    for value in values:
        if value is not None:
            _put(roles, role, value)


def _predicate_atoms(node: object):
    if not isinstance(node, dict):
        return
    if node.get("node_type", "atom") == "atom":
        yield node
        return
    for child in node.get("children", ()):
        yield from _predicate_atoms(child)
    if child := node.get("child"):
        yield from _predicate_atoms(child)


def _typed_predicate_values(atom: dict[str, object]) -> tuple[str, ...]:
    raw_values = (
        (atom["value"],) if atom.get("value") is not None else atom.get("values", ())
    )
    values: list[str] = []
    for value in raw_values:
        if not isinstance(value, dict):
            values.append(str(value))
            continue
        kind = value.get("kind")
        typed = value.get(str(kind)) if kind is not None else value.get("value")
        if typed is not None:
            values.append(f"{kind}:{typed}" if kind is not None else str(typed))
    return tuple(values)


def _semantic_value_kind(value_kind: str) -> str:
    return {
        "text": "string",
        "classification": "string",
        "status": "string",
        "currency": "string",
        "document_topic": "string",
    }.get(value_kind, value_kind)


def _projection_compatible(
    actual: tuple[tuple[str, tuple[str, ...]], ...],
    expected: tuple[tuple[str, tuple[str, ...]], ...],
) -> bool:
    actual_roles = dict(actual)
    return all(
        not (Counter(values) - Counter(actual_roles.get(role, ())))
        for role, values in expected
    )


def _projection_exact(
    actual: tuple[tuple[str, tuple[str, ...]], ...],
    expected: tuple[tuple[str, tuple[str, ...]], ...],
) -> bool:
    actual_roles = dict(actual)
    return all(actual_roles.get(role, ()) == values for role, values in expected)


def _adjudicated_solver_input(
    requirement: dict[str, object],
    source_frame: dict[str, object],
    catalog: SemanticCatalogSnapshot,
) -> tuple[
    ValidatedIntentResolutionV2,
    ResolverView,
    tuple[ExactSemanticLock, ...],
]:
    action = IntentType(
        requirement.get("action_id") or source_frame["action_ids"][0]
    )
    families = tuple(ProductFamily(item) for item in source_frame["product_family_ids"])
    supported = requirement["support_status"] == "supported"
    fields = (
        _adjudicated_fields(requirement, source_frame, catalog)
        if supported and action is not IntentType.CALCULATE
        else ()
    )
    literals, literal_locks = _adjudicated_literals(
        requirement, action, fields, catalog
    )
    semantic_groups = tuple(
        ResolverViewSemanticCandidateGroup(
            mention_id=f"mention-s1-{index}-{index + 1}",
            items=(
                ResolverViewSemanticCandidate(
                    semantic_id=field_id,
                    match_kind="direct_alias",
                    score=1_000_000,
                ),
            ),
        )
        for index, field_id in enumerate(fields)
    )
    field_locks = tuple(
        ExactSemanticLock(
            lock_id=f"lock-field-{field_id}-{index}",
            role="field",
            canonical_id=field_id,
            evidence_span_ids=(semantic_groups[index].mention_id,),
            source="direct_alias",
        )
        for index, field_id in enumerate(fields)
    )
    operator_values = tuple(
        requirement.get("source_slot_values", {}).get("filter_operator", ())
    )
    predicate_values = tuple(
        requirement.get("source_slot_values", {}).get("filter_value", ())
    )
    operator_locks = (
        (
            ExactSemanticLock(
                lock_id="lock-operator-screen",
                role="operator",
                canonical_id=_OPERATOR_IDS.get(operator_values[0], operator_values[0]),
                evidence_span_ids=("mention-s1-90-91",),
                source="canonical",
            ),
        )
        if supported
        and action is IntentType.SCREEN
        and len(operator_values) == 1
        and predicate_values
        else ()
    )
    assignments = tuple(
        SlotAssignment(
            slot_assignment_id=f"slot-eval-{index}",
            slot_kind=SlotKind(item["slot_kind"]),
            value_ids=tuple(item["value_ids"]),
            evidence_span_ids=(),
            reason_code="adjudicated",
        )
        for index, item in enumerate(source_frame.get("slots", ()))
    )
    source = fixture_resolution()
    template = source.canonical_frames[0]
    frame = template.model_copy(
        update={
            "frame_id": f"{requirement['case_id']}-f{requirement['frame_ordinal']}",
            "ordinal": 0,
            "frame_status": (
                ResolutionStatus.RESOLVED if supported else ResolutionStatus.UNMAPPED
            ),
            "segment_ids": ("s1",),
            "evidence_span_ids": (),
            "action_choice": ActionChoice(
                state=ChoiceState.SELECTED,
                selected_ids=(action,),
                evidence_span_ids=(),
                reason_code="adjudicated",
            ),
            "product_family_choice": ProductFamilyChoice(
                state=ChoiceState.SELECTED,
                selected_ids=families,
                evidence_span_ids=(),
                reason_code="adjudicated",
            ),
            "entity_type_ids": tuple(source_frame["entity_type_ids"]),
            "entity_hint_ids": (),
            "slot_assignments": assignments,
            "semantic_coverage": (
                FrameSemanticCoverage(
                    state=(
                        SemanticCoverageState.COVERED
                        if supported
                        else SemanticCoverageState.PARTIAL
                    ),
                    reason=(
                        SemanticCoverageReason.NONE
                        if supported
                        else SemanticCoverageReason.LEXICAL_OOD
                    ),
                    evidence_ids=(() if supported else ("evidence-ood",)),
                ),
            ),
        }
    )
    injected = source.model_copy(
        update={
            "canonical_frames": (frame,),
            "entity_hints": (),
            "resolution_status": frame.frame_status,
        }
    )
    base_view = fixture_view()
    concepts = tuple(
        ResolverViewConcept(
            concept_id=item.id,
            kind=item.kind,
            definition_ko=item.definition_ko,
            value_kind=item.value_kind,
            allowed_product_families=item.allowed_product_families,
            allowed_ontology_types=item.allowed_ontology_types,
            required_qualifiers=item.required_qualifiers,
            allowed_operators=item.allowed_operators,
            missingness_sensitive=item.missingness_sensitive,
            normalization_rule=item.normalization_rule,
        )
        for item in catalog.concepts_by_id.values()
        if item.kind != "relation"
    )
    resolver_view = base_view.model_copy(
        update={
            "product_family_ids": catalog.product_family_ids,
            "entity_type_ids": catalog.entity_type_ids,
            "semantic_candidates": semantic_groups,
            "concept_definitions": concepts,
            "relation_definitions": tuple(
                ResolverViewRelationDefinition(
                    relation_id=item.id,
                    definition_ko=item.definition_ko,
                    subject_ontology_types=item.subject_ontology_types,
                    object_ontology_types=item.object_ontology_types,
                    required_qualifiers=item.required_qualifiers,
                )
                for item in (
                    catalog.concepts_by_id[field_id] for field_id in fields
                )
                if item.kind == "relation"
            ),
            "literal_candidates": literals,
            "entity_candidates": (),
        }
    )
    return injected, resolver_view, (*field_locks, *operator_locks, *literal_locks)


def _adjudicated_fields(
    requirement: dict[str, object],
    source_frame: dict[str, object],
    catalog: SemanticCatalogSnapshot,
) -> tuple[str, ...]:
    candidates = _explicit_fields(requirement)
    families = set(source_frame["product_family_ids"])
    return tuple(
        item
        for item in dict.fromkeys(candidates)
        if item in catalog.concepts_by_id
        and (not families or families <= set(catalog.concepts_by_id[item].allowed_product_families))
    )


def _adjudicated_literals(
    requirement: dict[str, object],
    action: IntentType,
    fields: tuple[str, ...],
    catalog: SemanticCatalogSnapshot,
) -> tuple[tuple[ResolverViewLiteralCandidate, ...], tuple[ExactSemanticLock, ...]]:
    specs: list[tuple[str, str, str]] = []
    values = requirement.get("source_slot_values", {})
    for slot, kind in (
        ("period", "period"),
        ("currency", "currency"),
        ("unit", "unit"),
        ("date_scope", "date"),
    ):
        specs.extend((kind, str(value), str(value)) for value in values.get(slot, ()))
    filter_kind = "string"
    if fields:
        filter_kind = {
            "integer": "number",
            "decimal": "number",
            "date": "date",
        }.get(catalog.concepts_by_id[fields[0]].value_kind, "string")
    specs.extend(
        (filter_kind, str(value), str(value))
        for value in values.get("filter_value", ())
    )
    if action is IntentType.RANK:
        specs.extend(
            ("result_limit", str(value), str(value))
            for value in values.get("result_limit", ())
        )
        specs.extend(
            ("sort_direction", str(value), str(value))
            for value in values.get("sort_direction", ())
        )
        ordering = requirement.get("semantic_overrides", {}).get("ordering", {})
        if ordering.get("direction"):
            specs.append(("sort_direction", ordering["direction"], ordering["direction"]))
    literals = tuple(
        ResolverViewLiteralCandidate(
            literal_id=f"literal-eval-{index}",
            segment_id="s1",
            kind=kind,
            original_text=text,
            start_char=100 + index * 20,
            end_char=100 + index * 20 + len(text),
            canonical_value=value,
        )
        for index, (kind, value, text) in enumerate(specs)
    )
    locks = tuple(
        ExactSemanticLock(
            lock_id=f"lock-literal-eval-{index}",
            role="literal",
            canonical_id=literal.literal_id,
            evidence_span_ids=(literal.literal_id,),
            source="literal",
        )
        for index, literal in enumerate(literals)
    )
    return literals, locks
