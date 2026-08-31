"""Fail-closed semantic validation for bounded intent-resolution drafts."""

from __future__ import annotations

from dataclasses import dataclass

from financial_agent.contracts.request import RequestContext

from .catalog import SemanticCatalogSnapshot
from .draft import AxisChoice, EntityHint, IntentFrameDraft, IntentResolutionDraft
from .errors import ResolverContractError
from .normalization import NormalizedRequest
from .resolution import ResolutionIssue, ValidationEvent
from .types import ChoiceState, ResolutionStatus, SemanticTag, SlotKind
from .view import ResolverView, ResolverViewEntityCandidate


VALIDATION_STAGES = (
    "schema",
    "offered_ids",
    "evidence_spans",
    "applicability",
    "ontology_relations",
    "literal_types",
    "frame_order",
    "slot_mutations",
    "tag_derivation",
    "resolution_status",
)

STATUS_PRECEDENCE = (
    ResolutionStatus.UNMAPPED,
    ResolutionStatus.CONTEXT_UNRESOLVED,
    ResolutionStatus.AMBIGUOUS,
    ResolutionStatus.RESOLVED,
)

_POLICY_TAGS = frozenset(
    {
        SemanticTag.FUTURE_FORECAST,
        SemanticTag.PERSONALIZED_ADVICE,
        SemanticTag.ORDER_EXECUTION,
        SemanticTag.REALTIME_REQUIRED,
    }
)
_POLICY_REASON_CODES = frozenset({"explicit", "policy_explicit"})
_LITERAL_KINDS_BY_SLOT = {
    SlotKind.FILTER_VALUE: frozenset(
        {"number", "percentage", "money", "currency", "date", "period"}
    ),
    SlotKind.PERIOD: frozenset({"period"}),
    SlotKind.CURRENCY: frozenset({"currency"}),
    SlotKind.SORT_DIRECTION: frozenset({"sort_direction"}),
    SlotKind.RESULT_LIMIT: frozenset({"result_limit"}),
    SlotKind.DATE_SCOPE: frozenset({"date"}),
}
_CONCEPT_SLOTS = frozenset(
    {
        SlotKind.METRIC,
        SlotKind.SORT_KEY,
        SlotKind.COMPARISON_BASIS,
        SlotKind.SIMILARITY_ANCHOR,
    }
)


@dataclass(frozen=True, slots=True)
class SemanticValidationState:
    """The semantic portion of a validated draft, before context validation."""

    draft: IntentResolutionDraft
    canonical_frames: tuple[IntentFrameDraft, ...]
    final_tags: tuple[SemanticTag, ...]
    resolution_status: ResolutionStatus
    issues: tuple[ResolutionIssue, ...]
    validation_events: tuple[ValidationEvent, ...]


def validate_semantics(
    draft: IntentResolutionDraft,
    context: RequestContext,
    normalized: NormalizedRequest,
    view: ResolverView,
    catalog: SemanticCatalogSnapshot,
) -> SemanticValidationState:
    """Validate registered semantics without interpreting context dependencies.

    The later context validator owns frame ordering, context links, and mutations;
    this function deliberately does not infer missing slots or reference targets.
    """

    _validate_schema(draft)
    offered = _offered(view)
    _validate_offered_ids(draft, context, offered)
    _validate_evidence_spans(draft, context)
    _validate_applicability(draft, catalog, offered.concept_ids, offered.relation_ids)
    _validate_ontology_relations(draft, catalog, offered.relation_ids)
    _validate_literal_types(draft, normalized, view, offered)

    canonical_frames = tuple(_canonical_frame(frame) for frame in draft.intent_frames)
    issues = _issues(draft)
    final_tags = _derive_tags(draft, catalog)
    return SemanticValidationState(
        draft=draft,
        canonical_frames=canonical_frames,
        final_tags=final_tags,
        resolution_status=_resolution_status(issues),
        issues=issues,
        validation_events=_events(),
    )


@dataclass(frozen=True, slots=True)
class _Offered:
    product_family_ids: frozenset[str]
    action_ids: frozenset[str]
    concept_ids: frozenset[str]
    relation_ids: frozenset[str]
    entity_type_ids: frozenset[str]
    entity_candidates_by_mention: dict[str, dict[str, ResolverViewEntityCandidate]]
    literal_by_id: dict[str, object]
    operator_ids: frozenset[str]


def _offered(view: ResolverView) -> _Offered:
    concept_ids = frozenset(item.concept_id for item in view.concept_definitions)
    relation_ids = frozenset(item.relation_id for item in view.relation_definitions)
    entity_type_ids = {
        item.entity_type
        for group in view.entity_candidates
        for item in group.items
    }
    for concept in view.concept_definitions:
        entity_type_ids.update(concept.allowed_ontology_types)
    for relation in view.relation_definitions:
        entity_type_ids.update(relation.subject_ontology_types)
        entity_type_ids.update(relation.object_ontology_types)
    return _Offered(
        product_family_ids=frozenset(view.product_family_ids),
        action_ids=frozenset(view.action_ids),
        concept_ids=concept_ids,
        relation_ids=relation_ids,
        entity_type_ids=frozenset(entity_type_ids),
        entity_candidates_by_mention={
            group.mention_id: {item.entity_id: item for item in group.items}
            for group in view.entity_candidates
        },
        literal_by_id={item.literal_id: item for item in view.literal_candidates},
        operator_ids=frozenset(
            operator
            for concept in view.concept_definitions
            for operator in concept.allowed_operators
        )
        | frozenset(
            qualifier
            for concept in view.concept_definitions
            for qualifier in concept.required_qualifiers
        )
        | frozenset(
            qualifier
            for relation in view.relation_definitions
            for qualifier in relation.required_qualifiers
        ),
    )


def _validate_schema(draft: IntentResolutionDraft) -> None:
    if not isinstance(draft, IntentResolutionDraft):
        raise ResolverContractError("MODEL_SCHEMA_INVALID")


def _validate_offered_ids(
    draft: IntentResolutionDraft,
    context: RequestContext,
    offered: _Offered,
) -> None:
    segment_ids = {segment.segment_id for segment in context.segments}
    span_ids = {span.span_id for span in draft.evidence_spans}
    entity_hint_ids = {hint.entity_hint_id for hint in draft.entity_hints}

    for frame in draft.intent_frames:
        _require_subset(frame.segment_ids, segment_ids)
        _require_subset(frame.evidence_span_ids, span_ids)
        _validate_choice(frame.action_choice, offered.action_ids, span_ids)
        _validate_choice(frame.product_family_choice, offered.product_family_ids, span_ids)
        _require_subset(frame.entity_type_ids, offered.entity_type_ids)
        _require_subset(frame.entity_hint_ids, entity_hint_ids)
        for assignment in frame.slot_assignments:
            _require_subset(assignment.evidence_span_ids, span_ids)
            _validate_slot_ids(assignment.slot_kind, assignment.value_ids, offered)

    for hint in draft.entity_hints:
        _require_subset(hint.evidence_span_ids, span_ids)
        _require_subset(hint.expected_entity_type_ids, offered.entity_type_ids)
        if hint.mention_id:
            _require_subset(
                hint.mention_id, offered.entity_candidates_by_mention.keys()
            )
            candidates = offered.entity_candidates_by_mention[hint.mention_id[0]]
            allowed_entity_ids = frozenset(candidates)
            _require_subset(hint.candidate_entity_ids, allowed_entity_ids)
            _require_subset(hint.selected_candidate_ids, hint.candidate_entity_ids)
            _validate_selected_entity_types(draft, hint.entity_hint_id, hint, candidates)
        else:
            _require_subset(hint.candidate_entity_ids, _all_entity_ids(offered))
            _require_subset(hint.selected_candidate_ids, hint.candidate_entity_ids)

    for hint in draft.reference_hints:
        _require_subset((hint.segment_id,), segment_ids)
        _require_subset(hint.evidence_span_ids, span_ids)
    for hint in draft.semantic_flag_hints:
        _require_subset(hint.evidence_span_ids, span_ids)
    for mutation in draft.slot_mutations:
        _require_subset(mutation.evidence_span_ids, span_ids)


def _validate_choice(
    choice: AxisChoice, allowed_ids: frozenset[str], span_ids: set[str]
) -> None:
    if (choice.state is ChoiceState.SELECTED) != bool(choice.selected_ids):
        raise ResolverContractError("MODEL_INVALID_CHOICE")
    _require_subset(choice.selected_ids, allowed_ids)
    _require_subset(choice.evidence_span_ids, span_ids)


def _validate_slot_ids(kind: SlotKind, values: tuple[str, ...], offered: _Offered) -> None:
    if kind is SlotKind.RELATION:
        _require_subset(values, offered.relation_ids)
    elif kind in _CONCEPT_SLOTS:
        _require_subset(values, offered.concept_ids)
    elif kind is SlotKind.DOCUMENT_TOPIC:
        _require_subset(values, offered.concept_ids)
    elif kind is SlotKind.FILTER_OPERATOR:
        _require_subset(values, offered.operator_ids)
    elif kind in _LITERAL_KINDS_BY_SLOT:
        _require_subset(values, offered.literal_by_id)
    elif kind is SlotKind.UNIT:
        raise ResolverContractError("MODEL_UNKNOWN_ID")
    elif kind is SlotKind.ENTITY:
        _require_subset(values, _all_entity_ids(offered))


def _all_entity_ids(offered: _Offered) -> frozenset[str]:
    return frozenset(
        entity_id
        for candidates in offered.entity_candidates_by_mention.values()
        for entity_id in candidates
    )


def _validate_selected_entity_types(
    draft: IntentResolutionDraft,
    hint_id: str,
    hint: EntityHint,
    candidates: dict[str, ResolverViewEntityCandidate],
) -> None:
    expected_types = set(hint.expected_entity_type_ids)
    referencing_frames = tuple(
        frame for frame in draft.intent_frames if hint_id in frame.entity_hint_ids
    )
    for entity_id in hint.selected_candidate_ids:
        candidate_type = candidates[entity_id].entity_type
        if expected_types and candidate_type not in expected_types:
            raise ResolverContractError("MODEL_INVALID_ENTITY_TYPE")
        if any(
            frame.entity_type_ids and candidate_type not in frame.entity_type_ids
            for frame in referencing_frames
        ):
            raise ResolverContractError("MODEL_INVALID_ENTITY_TYPE")


def _require_subset(values: object, allowed: object) -> None:
    value_set = set(values)  # type: ignore[arg-type]
    allowed_set = set(allowed)  # type: ignore[arg-type]
    if not value_set <= allowed_set:
        raise ResolverContractError("MODEL_UNKNOWN_ID")


def _validate_evidence_spans(draft: IntentResolutionDraft, context: RequestContext) -> None:
    segments = {segment.segment_id: segment.text for segment in context.segments}
    for span in draft.evidence_spans:
        text = segments.get(span.segment_id)
        if (
            text is None
            or not 0 <= span.start_char < span.end_char <= len(text)
            or text[span.start_char : span.end_char] != span.text
        ):
            raise ResolverContractError("LITERAL_SPAN_MISMATCH")


def _validate_applicability(
    draft: IntentResolutionDraft,
    catalog: SemanticCatalogSnapshot,
    concept_ids: frozenset[str],
    relation_ids: frozenset[str],
) -> None:
    for frame in draft.intent_frames:
        family_ids = set(frame.product_family_choice.selected_ids)
        type_ids = set(frame.entity_type_ids)
        for assignment in frame.slot_assignments:
            if assignment.slot_kind not in _CONCEPT_SLOTS | {
                SlotKind.DOCUMENT_TOPIC,
                SlotKind.RELATION,
            }:
                continue
            for concept_id in assignment.value_ids:
                _validate_concept_applicability(
                    concept_id,
                    family_ids,
                    type_ids,
                    catalog,
                    relation_ids if assignment.slot_kind is SlotKind.RELATION else concept_ids,
                )


def _validate_concept_applicability(
    concept_id: str,
    family_ids: set[str],
    type_ids: set[str],
    catalog: SemanticCatalogSnapshot,
    offered_concept_ids: frozenset[str],
) -> None:
    if concept_id not in offered_concept_ids:
        raise ResolverContractError("MODEL_UNKNOWN_ID")
    concept = catalog.concepts_by_id.get(concept_id)
    if concept is None:
        raise ResolverContractError("MODEL_UNKNOWN_ID")
    if not family_ids <= set(concept.allowed_product_families) or not type_ids <= set(
        concept.allowed_ontology_types
    ):
        raise ResolverContractError("MODEL_INAPPLICABLE_CONCEPT")


def _validate_ontology_relations(
    draft: IntentResolutionDraft,
    catalog: SemanticCatalogSnapshot,
    relation_ids: frozenset[str],
) -> None:
    hints_by_id = {hint.entity_hint_id: hint for hint in draft.entity_hints}
    for frame in draft.intent_frames:
        for assignment in frame.slot_assignments:
            if assignment.slot_kind is not SlotKind.RELATION:
                continue
            for relation_id in assignment.value_ids:
                if relation_id not in relation_ids:
                    raise ResolverContractError("MODEL_UNKNOWN_ID")
                relation = catalog.concepts_by_id.get(relation_id)
                if relation is None or relation.kind != "relation":
                    raise ResolverContractError("MODEL_INVALID_RELATION")
                subject_types = set(relation.subject_ontology_types)
                object_types = set(relation.object_ontology_types)
                if (
                    not frame.entity_type_ids
                    or not set(frame.entity_type_ids) <= subject_types
                    or not object_types
                ):
                    raise ResolverContractError("MODEL_INVALID_RELATION")
                for hint_id in frame.entity_hint_ids:
                    expected_types = set(hints_by_id[hint_id].expected_entity_type_ids)
                    if expected_types and not (
                        expected_types <= subject_types or expected_types <= object_types
                    ):
                        raise ResolverContractError("MODEL_INVALID_RELATION")


def _validate_literal_types(
    draft: IntentResolutionDraft, normalized: NormalizedRequest, view: ResolverView, offered: _Offered
) -> None:
    source_segments = {segment.segment_id: segment.original_text for segment in normalized.segments}
    for literal in view.literal_candidates:
        source = source_segments.get(literal.segment_id)
        if (
            source is None
            or not 0 <= literal.start_char < literal.end_char <= len(source)
            or source[literal.start_char : literal.end_char] != literal.original_text
        ):
            raise ResolverContractError("LITERAL_SPAN_MISMATCH")

    for frame in draft.intent_frames:
        for assignment in frame.slot_assignments:
            allowed_kinds = _LITERAL_KINDS_BY_SLOT.get(assignment.slot_kind)
            if allowed_kinds is None:
                continue
            for literal_id in assignment.value_ids:
                literal = offered.literal_by_id.get(literal_id)
                if literal is None or literal.kind not in allowed_kinds:
                    raise ResolverContractError("MODEL_INVALID_LITERAL_TYPE")


def _canonical_frame(frame: IntentFrameDraft) -> IntentFrameDraft:
    return frame.model_copy(
        update={
            "segment_ids": _sorted_unique(frame.segment_ids),
            "evidence_span_ids": _sorted_unique(frame.evidence_span_ids),
            "entity_type_ids": _sorted_unique(frame.entity_type_ids),
            "entity_hint_ids": _sorted_unique(frame.entity_hint_ids),
            "action_choice": _canonical_choice(frame.action_choice),
            "product_family_choice": _canonical_choice(frame.product_family_choice),
            "slot_assignments": tuple(
                assignment.model_copy(
                    update={
                        "value_ids": _sorted_unique(assignment.value_ids),
                        "evidence_span_ids": _sorted_unique(assignment.evidence_span_ids),
                    }
                )
                for assignment in sorted(frame.slot_assignments, key=lambda item: item.slot_assignment_id)
            ),
            "produced_result_hints": tuple(sorted(set(frame.produced_result_hints), key=lambda item: item.value)),
        }
    )


def _canonical_choice(choice: AxisChoice) -> AxisChoice:
    return choice.model_copy(
        update={
            "selected_ids": _sorted_unique(choice.selected_ids),
            "evidence_span_ids": _sorted_unique(choice.evidence_span_ids),
        }
    )


def _sorted_unique(values: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(sorted(set(values), key=lambda item: str(getattr(item, "value", item))))


def _derive_tags(
    draft: IntentResolutionDraft, catalog: SemanticCatalogSnapshot
) -> tuple[SemanticTag, ...]:
    tags: set[SemanticTag] = set()
    families = {
        family
        for frame in draft.intent_frames
        if frame.product_family_choice.state is ChoiceState.SELECTED
        for family in frame.product_family_choice.selected_ids
    }
    if len(families) > 1:
        tags.add(SemanticTag.CROSS_FAMILY)
    if len(draft.intent_frames) > 1:
        tags.add(SemanticTag.MULTI_STEP)
    if draft.reference_hints or draft.context_link_hints:
        tags.add(SemanticTag.CONTEXT_DEPENDENT)

    for frame in draft.intent_frames:
        for assignment in frame.slot_assignments:
            if assignment.slot_kind is SlotKind.RELATION:
                tags.add(SemanticTag.RELATIONSHIP_REQUIRED)
            if assignment.slot_kind is SlotKind.DOCUMENT_TOPIC:
                tags.add(SemanticTag.DOCUMENT_GROUNDED)
            if assignment.slot_kind in {SlotKind.PERIOD, SlotKind.DATE_SCOPE}:
                tags.add(SemanticTag.TEMPORAL)
            for concept_id in assignment.value_ids:
                concept = catalog.concepts_by_id.get(concept_id)
                if concept is None:
                    continue
                if concept.normalization_rule != "none":
                    tags.add(SemanticTag.NORMALIZATION_REQUIRED)
                if concept.missingness_sensitive:
                    tags.add(SemanticTag.MISSINGNESS_SENSITIVE)
                if concept.value_kind == "status" or concept_id == "pension_eligibility":
                    tags.add(SemanticTag.OPERATIONAL_STATUS)

    for hint in draft.semantic_flag_hints:
        if (
            hint.semantic_tag in _POLICY_TAGS
            and hint.evidence_span_ids
            and hint.reason_code in _POLICY_REASON_CODES
        ):
            tags.add(hint.semantic_tag)
    return tuple(sorted(tags, key=lambda item: item.value))


def _issues(draft: IntentResolutionDraft) -> tuple[ResolutionIssue, ...]:
    records: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for frame in draft.intent_frames:
        for choice in (frame.action_choice, frame.product_family_choice):
            if choice.state is ChoiceState.UNMAPPED:
                records.append(
                    ("SEMANTIC_CONCEPT_UNMAPPED", (frame.frame_id,), choice.evidence_span_ids)
                )
            elif choice.state is ChoiceState.AMBIGUOUS:
                records.append(
                    ("AMBIGUITY_UNRESOLVED", (frame.frame_id,), choice.evidence_span_ids)
                )
    for hint in draft.reference_hints:
        if hint.status == "unresolved":
            records.append(("REFERENCE_UNRESOLVED", (hint.reference_id,), hint.evidence_span_ids))
        elif hint.status == "ambiguous":
            records.append(("REFERENCE_AMBIGUOUS", (hint.reference_id,), hint.evidence_span_ids))
    if draft.frame_limit_exceeded:
        records.append(("FRAME_LIMIT_EXCEEDED", (), ()))
    return tuple(
        ResolutionIssue(
            issue_id=f"issue-{index}-{code.lower()}",
            code=code,
            related_ids=related_ids,
            evidence_span_ids=span_ids,
        )
        for index, (code, related_ids, span_ids) in enumerate(records, start=1)
    )


def _resolution_status(issues: tuple[ResolutionIssue, ...]) -> ResolutionStatus:
    codes = {issue.code for issue in issues}
    active_statuses = {ResolutionStatus.RESOLVED}
    if "SEMANTIC_CONCEPT_UNMAPPED" in codes:
        active_statuses.add(ResolutionStatus.UNMAPPED)
    if "REFERENCE_UNRESOLVED" in codes:
        active_statuses.add(ResolutionStatus.CONTEXT_UNRESOLVED)
    if {"AMBIGUITY_UNRESOLVED", "REFERENCE_AMBIGUOUS"} & codes:
        active_statuses.add(ResolutionStatus.AMBIGUOUS)
    return next(status for status in STATUS_PRECEDENCE if status in active_statuses)


def _events() -> tuple[ValidationEvent, ...]:
    implemented_stages = (
        "schema",
        "offered_ids",
        "evidence_spans",
        "applicability",
        "ontology_relations",
        "literal_types",
        "tag_derivation",
        "resolution_status",
    )
    return tuple(
        ValidationEvent(
            event_id=f"validation-{stage}",
            stage=stage,
            code="VALIDATED",
            related_ids=(),
        )
        for stage in implemented_stages
    )
