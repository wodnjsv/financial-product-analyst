"""Offline-only decoupled contract metrics over injected adjudicated axes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.axis_locks import ExactSemanticLock
from financial_agent.intent.catalog import SemanticCatalogSnapshot, load_catalog
from financial_agent.intent.draft import (
    ActionChoice,
    EntityHintV2,
    ProductFamilyChoice,
    SlotAssignment,
)
from financial_agent.intent.proposal import FrameSemanticCoverage
from financial_agent.intent.query_contract_registry import QueryContractRegistry
from financial_agent.intent.query_contract_solver import solve_query_contracts
from financial_agent.intent.resolution import ValidatedIntentResolutionV2
from financial_agent.intent.types import (
    ChoiceState,
    EntitySemanticRole,
    ResolutionStatus,
    SemanticCoverageReason,
    SemanticCoverageState,
    SlotKind,
)
from financial_agent.intent.view import (
    ResolverView,
    ResolverViewConcept,
    ResolverViewLiteralCandidate,
    ResolverViewSemanticCandidate,
    ResolverViewSemanticCandidateGroup,
)
from tests.evaluation.query_contract.coverage import load_requirement_snapshot
from tests.planning.fixtures import resolution as fixture_resolution
from tests.planning.fixtures import view as fixture_view


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
    candidate_recall_count: int
    exact_contract_count: int
    false_complete_count: int
    compile_eligible_count: int

    @property
    def candidate_recall(self) -> float:
        denominator = (
            self.supported_frame_count - self.intentionally_blocked_frame_count
        )
        return self.candidate_recall_count / denominator if denominator else 1.0

    @property
    def exact_contract(self) -> float:
        denominator = (
            self.supported_frame_count - self.intentionally_blocked_frame_count
        )
        return self.exact_contract_count / denominator if denominator else 1.0

    @property
    def compile_eligibility(self) -> float:
        denominator = (
            self.supported_frame_count - self.intentionally_blocked_frame_count
        )
        return self.compile_eligible_count / denominator if denominator else 1.0


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
    for requirement in heldout:
        source_frame = frames_by_key[
            (requirement["case_id"], requirement["frame_ordinal"])
        ]
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

        supported += 1
        rejection_codes = {item.reason_code for item in actual.rejections}
        if (
            not actual.complete_candidates
            and rejection_codes == {"RECIPE_NOT_OFFERED"}
        ):
            blocked += 1
            continue

        expected_variant_ids = _expected_variant_ids(requirement, registry)
        matching = tuple(
            item
            for item in actual.complete_candidates
            if item.contract.contract_variant_id in expected_variant_ids
        )
        if matching:
            recall += 1
            eligible += 1
        if any(
            _candidate_matches_adjudication(item.contract, requirement)
            for item in matching
        ):
            exact += 1

    return FrozenSnapshotContractMetrics(
        total_frame_count=len(heldout),
        supported_frame_count=supported,
        unsupported_frame_count=unsupported,
        intentionally_blocked_frame_count=blocked,
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


def _candidate_matches_adjudication(
    contract: object, requirement: dict[str, object]
) -> bool:
    payload = contract.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    slots = requirement.get("source_slot_values", {})
    overrides = requirement.get("semantic_overrides", {})
    ordering = overrides.get("ordering", {}) if isinstance(overrides, dict) else {}
    expected_fields = tuple(
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
    if expected_fields and not any(
        f'"{field_id}"' in serialized for field_id in expected_fields
    ):
        return False
    if ordering.get("direction") and payload.get("ordering", [{}])[0].get(
        "direction"
    ) != ordering["direction"]:
        return False
    return True


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
    fields = _adjudicated_fields(requirement, source_frame, catalog) if supported else ()
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
    operator_locks = (
        (
            ExactSemanticLock(
                lock_id="lock-operator-screen",
                role="operator",
                canonical_id="is_present",
                evidence_span_ids=("mention-s1-90-91",),
                source="canonical",
            ),
        )
        if supported and action is IntentType.SCREEN
        else ()
    )

    hint_count = 2 if action is IntentType.COMPARE else int(
        action is IntentType.SIMILAR or not families
    )
    hints = tuple(
        EntityHintV2(
            entity_hint_id=f"hint-eval-{index}",
            mention_id=(),
            evidence_span_ids=(),
            expected_entity_type_ids=("FinancialProduct",),
            candidate_entity_ids=(f"entity-eval-{index}",),
            selected_candidate_ids=(f"entity-eval-{index}",),
            reason_code="adjudicated",
            semantic_role=EntitySemanticRole.FRAME_SUBJECT,
            relation_id=(),
        )
        for index in range(hint_count)
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
            "entity_hint_ids": tuple(item.entity_hint_id for item in hints),
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
            "entity_hints": hints,
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
    action = requirement["action_id"]
    slots = requirement.get("source_slot_values", {})
    override = requirement.get("semantic_overrides", {})
    candidates: list[str] = []
    if action == "rank":
        ordering = override.get("ordering", {}) if isinstance(override, dict) else {}
        candidates.extend(([ordering["field"]] if ordering.get("field") else slots.get("sort_key", ())))
    elif action in {"lookup", "compare", "aggregate", "screen"}:
        candidates.extend(slots.get("metric", ()))
        candidates.extend(slots.get("comparison_basis", ()))
        candidates.extend(slots.get("document_topic", ()))
    elif action == "explain":
        candidates.extend(slots.get("document_topic", ()))
    elif action == "calculate":
        candidates.extend(slots.get("metric", ()))

    families = set(source_frame["product_family_ids"])
    usable = tuple(
        item
        for item in dict.fromkeys(candidates)
        if item in catalog.concepts_by_id
        and catalog.concepts_by_id[item].kind != "relation"
        and (not families or families <= set(catalog.concepts_by_id[item].allowed_product_families))
    )
    if usable:
        return usable
    if action == "lookup":
        return ()
    preferred = (
        ("credit_grade", "availability_status")
        if families == {"domestic_bond"}
        else ("fee_rate", "asset_class")
    )
    return next(
        (item,)
        for item in preferred
        if not families
        or families <= set(catalog.concepts_by_id[item].allowed_product_families)
    )


def _adjudicated_literals(
    requirement: dict[str, object],
    action: IntentType,
    fields: tuple[str, ...],
    catalog: SemanticCatalogSnapshot,
) -> tuple[tuple[ResolverViewLiteralCandidate, ...], tuple[ExactSemanticLock, ...]]:
    specs: list[tuple[str, str, str]] = []
    qualifiers = {
        qualifier
        for field_id in fields
        for qualifier in catalog.concepts_by_id[field_id].required_qualifiers
    }
    if "as_of" in qualifiers:
        specs.append(("date", "2026-09-02", "2026-09-02"))
    if "period" in qualifiers:
        specs.append(("period", "P1Y", "1년"))
    if action is IntentType.RANK:
        values = requirement.get("source_slot_values", {})
        limit = next(iter(values.get("result_limit", ("5",))), "5")
        specs.append(("result_limit", limit, limit))
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
